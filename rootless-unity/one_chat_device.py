"""Test-only, button-start transport. Private snapshots never enter reports."""
from pathlib import Path
import threading

import one_chat_probe as probe
from diagnose_device import cleanup_frida, validate_runtime
from target_only import TargetOnlyAdb, preflight, recheck
from test_device import TARGET, PACKAGE, bundle_token


class ReadStopped(Exception):
    def __init__(self, code, diagnostic=None):
        super().__init__(code)
        self.diagnostic = diagnostic


def inspect(port, token, cancelled, expected=None, *, frida_api=None, read_name=False, read_latest=False, read_input=False, read_name_optional=False):
    if frida_api is None:
        import frida as frida_api
    f = frida_api
    if f.__version__ != '17.24.1':
        raise ReadStopped('client-version')
    # Build only fixed code with validated decimal IDs; no user code is accepted.
    source = probe.build(expected, read_name=read_name, scoped_traversal=True, read_latest=read_latest, read_input=read_input, read_name_optional=read_name_optional) + '''
    rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
      root(){return probeUIKitRoot();},cancel(){cancelNavigation();}};
    '''
    from startup_failure import record
    try:manager = f.get_device_manager()
    except Exception as error:
        record(error,'gadget-manager');raise
    address = '127.0.0.1:' + str(port)
    device = session = script = None
    guard = f.Cancellable()
    timer = threading.Timer(25, guard.cancel)
    timer.daemon = True
    done = threading.Event()
    monitor = None
    timer.start()
    stage='gadget-connect'
    try:
        with guard:
            if cancelled():
                raise ReadStopped('cancelled')
            device = manager.add_remote_device(address, token=token)
            stage='gadget-process'
            processes = device.enumerate_processes()
            if len(processes) != 1 or type(processes[0].pid) is not int or processes[0].pid <= 0:
                raise ReadStopped('ambiguous-process')
            if processes[0].name not in ('Gadget', PACKAGE):
                raise ReadStopped('unexpected-process')
            stage='gadget-attach'
            session = device.attach(processes[0].pid)
            stage='script-create'
            script = session.create_script(source, name='dvk-one-chat-readonly-0.3.35')
            stage='script-load'
            script.load()
            stage='runtime-check'
            runtime = validate_runtime(script.exports_sync.runtime())
            if runtime['arch'] != 'arm64' or runtime['platform'] != 'linux':
                raise ReadStopped('unsupported-runtime')
            def watch():
                while not done.wait(.1):
                    if cancelled():
                        try:
                            script.exports_sync.cancel()
                        except Exception:
                            pass
                        return
            monitor = threading.Thread(target=watch, daemon=True)
            monitor.start()
            stage='script-run'
            result = script.exports_sync.root()
            stage='result-validation'
            private = probe.private_snapshot(result, expected, read_name=read_name, read_latest=read_latest, read_input=read_input, read_name_optional=read_name_optional)
            n = result['navigation']
            if private is None:
                # Only fixed stage names may leave the native result.
                raise ReadStopped(n['error'] if n['error'] != 'none' else 'not-ready',
                  dict({key: n[key] for key in ('stage','metadata_checkpoint','read_checkpoint','wait_reason','frames','managed_calls')}, **probe.diagnostic(n)))
            if cancelled():
                raise ReadStopped('cancelled')
            return private
    except Exception as error:
        # Authored fixed read-only source: even a lost root result has no UI or
        # send side effect. Never give this proof to a mutating inspector.
        error._dvk_readonly_transport=(stage in {'gadget-connect','gadget-process','gadget-attach','script-create','script-load','runtime-check','script-run'}
            and type(error).__name__ in {'TransportError','ServerNotRunningError','TimedOutError'})
        record(error,stage)
        raise
    finally:
        done.set()
        timer.cancel()
        if monitor:
            monitor.join(timeout=1)
        cleanup_frida(f, manager, address, script, session, device)


def capture(executable, folder, cancelled=lambda: False, expected=None, *, inspector=inspect, read_name=False, read_latest=False, read_input=False, preexecution_retry=None, read_name_optional=False):
    """Private data remains in memory; no JSON serialization in this layer."""
    from dialog_browser import PreparedNavigation
    navigation_operation=type(inspector) is PreparedNavigation
    readonly_operation=inspector is inspect
    if type(read_name_optional) is not bool or read_name_optional and not read_name:
        raise ValueError('Optional name requires name reading')
    if read_name or read_latest or read_input:
        if expected is None or inspector is not inspect:
            raise ValueError('Name requires the fixed bound reader')
        inspector = lambda port, token, cancel, who: inspect(port, token, cancel, who, read_name=read_name, read_latest=read_latest, read_input=read_input, read_name_optional=read_name_optional)
    if preexecution_retry is not None and not callable(preexecution_retry):
        raise ValueError('Invalid pre-execution retry callback')
    from startup_failure import checkpoint
    with checkpoint('bundle-check'):
        folder = Path(folder).resolve(strict=True)
        token = bundle_token(folder)  # Pins existing test APKs; no install/launch.
    with checkpoint('adb-create'):
        adb = TargetOnlyAdb(executable, folder)
    with checkpoint('adb-preflight', adb=adb):
        boot = preflight(adb)
    with checkpoint('device-recheck', adb=adb):
        recheck(adb, boot)
    if cancelled():
        raise ReadStopped('cancelled')
    private = None
    try:
        with checkpoint('forward-open', adb=adb):
            port = adb.run(['-s', TARGET, 'forward', 'tcp:0', 'tcp:27042'])
            if not port.isdecimal() or not 1024 <= int(port) <= 65535:
                raise ReadStopped('invalid-forward')
            adb.forward_port = int(port)
        from startup_failure import retryable_connection
        connection_attempt = 0
        setup_attempt = 0
        read_attempt = 0
        navigation_attempt = 0
        def refresh_forward():
            # Only before a profile script load OR after the authored read-only
            # inspector. Original explicit endpoint/boot is checked every time.
            with checkpoint('device-recheck',adb=adb):recheck(adb,boot)
            with checkpoint('forward-close',adb=adb):
                adb.run(['-s',TARGET,'forward','--remove',f'tcp:{adb.forward_port}'],timeout=10)
                adb.forward_port=None
            with checkpoint('forward-open',adb=adb):
                fresh=adb.run(['-s',TARGET,'forward','tcp:0','tcp:27042'])
                if not fresh.isdecimal() or not 1024<=int(fresh)<=65535:raise ReadStopped('invalid-forward')
                adb.forward_port=int(fresh)
            with checkpoint('device-recheck',adb=adb):recheck(adb,boot)
        while True:
            try:
                with checkpoint('device-inspection'):
                    private = inspector(adb.forward_port, token, cancelled, expected)
                break
            except Exception as error:
                from assistant_setup_retry import retryable_profile_setup
                if preexecution_retry is not None and retryable_profile_setup(error):
                    # inspect() has already joined threads/detached its session.
                    # No UI action or journal authorization happened in this try.
                    # Hold the original explicit endpoint/boot; replace only
                    # its disposable local forward after inspector cleanup.
                    if cancelled():
                        error_cancelled=ReadStopped('cancelled')
                        error_cancelled._dvk_profile_not_executed=True
                        raise error_cancelled from None
                    setup_attempt += 1
                    delay=min(30,2**min(setup_attempt-1,5))
                    interrupted=preexecution_retry(error,setup_attempt,delay)
                    if interrupted or cancelled():
                        error_cancelled=ReadStopped('cancelled')
                        error_cancelled._dvk_profile_not_executed=True
                        raise error_cancelled from None
                    try:refresh_forward()
                    except Exception as setup_error:
                        setup_error._dvk_profile_not_executed=True
                        raise
                    continue
                if navigation_operation and getattr(error,'_dvk_navigation_not_loaded',False) is True:
                    from startup_failure import clean
                    failure=clean(getattr(error,'_dvk_failure',None))
                    verified=(failure is not None and failure['stage']=='script-create'
                        and failure['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError'})
                    if verified:
                        if navigation_attempt>=2 or cancelled():raise
                        navigation_attempt+=1
                        inspector.reconnecting(navigation_attempt)
                        refresh_forward()
                        if cancelled():raise ReadStopped('cancelled')
                        continue
                if readonly_operation and verified_readonly_transport(error):
                    if read_attempt>=2 or cancelled():raise
                    read_attempt+=1
                    refresh_forward()
                    if cancelled():raise ReadStopped('cancelled')
                    continue
                if connection_attempt or cancelled() or not retryable_connection(error):raise
                connection_attempt += 1
                # Existing one-shot connection retry, never load/root replay.
                with checkpoint('device-recheck', adb=adb):
                    recheck(adb, boot)
        with checkpoint('device-recheck-after', adb=adb):
            recheck(adb, boot)
        if cancelled():
            raise ReadStopped('cancelled')
    finally:
        if adb.forward_port is not None:
            # Cleanup failure still prevents consuming the result. Never retry UI actions.
            with checkpoint('forward-close', adb=adb):
                adb.run(['-s', TARGET, 'forward', '--remove', f'tcp:{adb.forward_port}'], timeout=10)
    return private


def report(outcome=None, *, failure=False):
    # Allowlist only counts and fixed statuses; never arbitrary errors/RPC data.
    result = dict(tool_version=probe.VERSION, mode='one-bound-test-chat-read-only',
                  status='stopped' if failure else 'binding-ready', device_scope='test-only',
                  working_device_contacted=False, ui_actions_attempted=False, messages_sent=0,
                  telegram_used=False, enrollment_journal_used=False, message_text_exported=False,
                  identity_exported=False, chronological_order_verified=False,
                  automatic_replies_available=False)
    if outcome:
        allowed = {'status','observed_messages','incoming_messages','new_incoming','baseline_recorded'}
        if set(outcome) != allowed or outcome['status'] not in ('baseline-recorded','read-complete'):
            raise ValueError('Invalid diagnostic outcome')
        for key in ('observed_messages','incoming_messages','new_incoming'):
            if type(outcome[key]) is not int or not 0 <= outcome[key] <= probe.MAX_MESSAGES:
                raise ValueError('Invalid diagnostic count')
        if outcome['baseline_recorded'] is not True:
            raise ValueError('Invalid baseline')
        if not outcome['new_incoming'] <= outcome['incoming_messages'] <= outcome['observed_messages']:
            raise ValueError('Invalid diagnostic counters')
        result.update(outcome)
    return result


def safe_read_failure(error):
    """Export only authored codes and validated diagnostic categories, never bodies/IDs."""
    import chat_state_probe as state
    code = str(error)
    out = {'error': code if code in probe.ERRORS | {
        'client-version', 'cancelled', 'ambiguous-process', 'unexpected-process',
        'unsupported-runtime', 'invalid-forward', 'not-ready'} else 'read-stopped'}
    value = error.diagnostic
    if not isinstance(value, dict):
        return out
    for key, choices in (('stage', {'navigation-ready', 'navigation-stopped', 'not-attempted'}),
                         ('metadata_checkpoint', state.CHECKPOINTS),
                         ('read_checkpoint', state.READ_STEPS), ('wait_reason', state.WAIT_REASONS)):
        if isinstance(value.get(key), str) and value[key] in choices:
            out[key] = value[key]
    for key in ('frames', 'managed_calls'):
        number = value.get(key)
        if type(number) is int and 0 <= number <= 1000000:
            out[key] = number
    try:
        out.update(probe.diagnostic(value))
    except (ValueError, KeyError, TypeError):
        pass
    return out


def verified_early_wrong_screen(value):
    """An interrupted screen observation, NOT identity or message proof.

    Only permits one fresh SAME-bound read. No Back, input or send is allowed
    from this diagnostic; a successful fresh snapshot must verify identity.
    """
    if not isinstance(value,dict):return False
    expected=dict(error='wrong-screen',stage='navigation-stopped',metadata_checkpoint='ready',
        read_checkpoint='not-checked',wait_reason='not-checked',message_slot=-1,
        message_kind='not-read',message_direction='not-read',scalar_state='not-read',
        identity_checkpoint='not-checked',scalar_checkpoint='not-read')
    return (all(value.get(key)==item for key,item in expected.items())
        and all(type(value.get(key)) is int and 0<value[key]<=1000000 for key in ('frames','managed_calls')))


def verified_sample_wrong_screen(value):
    """Report 237: visibility lost between complete read samples, not identity proof.

    Permit only one fresh SAME-bound read. No partial messages are consumed;
    successful retries still require both full samples and the expected IDs.
    Identity/signature failures never enter this path.
    """
    if not isinstance(value,dict):return False
    expected=dict(error='wrong-screen',stage='navigation-stopped',metadata_checkpoint='ready',
        read_checkpoint='sample',wait_reason='none',identity_checkpoint='recheck',
        scalar_checkpoint='chat-id',scalar_state='positive',message_kind='text')
    return (all(value.get(key)==item for key,item in expected.items())
        and value.get('message_direction') in ('own','not-own')
        and type(value.get('message_slot')) is int and 0<=value['message_slot']<probe.MAX_MESSAGES
        and all(type(value.get(key)) is int and 0<value[key]<=1000000 for key in ('frames','managed_calls')))


def transient_read_failure(error):
    """Only bounded read-only retries for loading/changing history, not changed identity."""
    value = safe_read_failure(error)
    return (verified_early_wrong_screen(value) or verified_sample_wrong_screen(value) or value['error'] in {'history-not-ready', 'frame-limit', 'frame-budget'}
            and value.get('wait_reason') in {'history-loading', 'history-not-loaded',
                'null-history-manager', 'null-loaded-flag', 'changing-count',
                'changing-last-message', 'view-not-ready'})


def verified_readonly_transport(error):
    from startup_failure import clean
    value=clean(getattr(error,'_dvk_failure',None))
    return (getattr(error,'_dvk_readonly_transport',False) is True and value is not None
        and value['stage'] in {'gadget-connect','gadget-process','gadget-attach','script-create','script-load','runtime-check','script-run'}
        and value['error_type'] in {'TransportError','ServerNotRunningError','TimedOutError'})
