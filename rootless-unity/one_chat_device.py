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


def inspect(port, token, cancelled, expected=None, *, frida_api=None):
    if frida_api is None:
        import frida as frida_api
    f = frida_api
    if f.__version__ != '17.24.1':
        raise ReadStopped('client-version')
    # Build only fixed code with validated decimal IDs; no user code is accepted.
    source = probe.build(expected) + '''
    rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
      root(){return probeUIKitRoot();},cancel(){cancelNavigation();}};
    '''
    manager = f.get_device_manager()
    address = '127.0.0.1:' + str(port)
    device = session = script = None
    guard = f.Cancellable()
    timer = threading.Timer(25, guard.cancel)
    timer.daemon = True
    done = threading.Event()
    monitor = None
    timer.start()
    try:
        with guard:
            if cancelled():
                raise ReadStopped('cancelled')
            device = manager.add_remote_device(address, token=token)
            processes = device.enumerate_processes()
            if len(processes) != 1 or type(processes[0].pid) is not int or processes[0].pid <= 0:
                raise ReadStopped('ambiguous-process')
            if processes[0].name not in ('Gadget', PACKAGE):
                raise ReadStopped('unexpected-process')
            session = device.attach(processes[0].pid)
            script = session.create_script(source, name='dvk-one-chat-readonly-0.3.33')
            script.load()
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
            result = script.exports_sync.root()
            private = probe.private_snapshot(result, expected)
            n = result['navigation']
            if private is None:
                # Only fixed stage names may leave the native result.
                raise ReadStopped(n['error'] if n['error'] != 'none' else 'not-ready',
                  dict({key: n[key] for key in ('stage','metadata_checkpoint','read_checkpoint','wait_reason','frames','managed_calls')}, **probe.diagnostic(n)))
            if cancelled():
                raise ReadStopped('cancelled')
            return private
    finally:
        done.set()
        timer.cancel()
        if monitor:
            monitor.join(timeout=1)
        cleanup_frida(f, manager, address, script, session, device)


def capture(executable, folder, cancelled=lambda: False, expected=None, *, inspector=inspect):
    """Private data remains in memory; no JSON serialization in this layer."""
    folder = Path(folder).resolve(strict=True)
    adb = TargetOnlyAdb(executable, folder)
    token = bundle_token(folder)  # Pins existing test APKs; no install/launch.
    boot = preflight(adb)
    recheck(adb, boot)
    if cancelled():
        raise ReadStopped('cancelled')
    private = None
    try:
        port = adb.run(['-s', TARGET, 'forward', 'tcp:0', 'tcp:27042'])
        if not port.isdecimal() or not 1024 <= int(port) <= 65535:
            raise ReadStopped('invalid-forward')
        adb.forward_port = int(port)
        private = inspector(adb.forward_port, token, cancelled, expected)
        recheck(adb, boot)
        if cancelled():
            raise ReadStopped('cancelled')
    finally:
        if adb.forward_port is not None:
            # A failed cleanup also prevents consuming the result.
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
            if type(outcome[key]) is not int or not 0 <= outcome[key] <= 20:
                raise ValueError('Invalid diagnostic count')
        if outcome['baseline_recorded'] is not True:
            raise ValueError('Invalid baseline')
        if not outcome['new_incoming'] <= outcome['incoming_messages'] <= outcome['observed_messages']:
            raise ValueError('Invalid diagnostic counters')
        result.update(outcome)
    return result
