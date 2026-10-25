"""Single whitelisted submission via the reader's pinned test-only ADB path.
The caller must hold the shared operation lock and commit authorization first.
"""
import threading
import one_chat_send as sender
from one_chat_preview import QUESTION
from one_chat_device import capture, ReadStopped
from diagnose_device import cleanup_frida, validate_runtime
from test_device import PACKAGE

class SubmissionNotStarted(ReadStopped):
    """Only a transient transport failure before root RPC was invoked."""
    def __init__(self,stage):
        if stage not in {'gadget-manager','gadget-connect','gadget-process','gadget-attach','script-create','script-load','runtime-check'}:
            raise ValueError('Invalid pre-invocation checkpoint')
        super().__init__('send-setup-unavailable')
        self.stage=stage


def inspect_submission(port, token, cancelled, before, *, text=QUESTION, frida_api=None):
    if frida_api is None:
        import frida as frida_api
    f = frida_api
    if f.__version__ != '17.24.1':
        raise ReadStopped('client-version')
    # Build only fixed code with validated decimal IDs; no user code is accepted.
    source = sender.build(before, text=text) + '''
    rpc.exports={runtime(){return {frida_version:Frida.version,arch:Process.arch,platform:Process.platform};},
      root(){return probeUIKitRoot();},cancel(){cancelNavigation();}};
    '''
    manager = None
    root_started = False
    stage = 'gadget-manager'
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
            manager = f.get_device_manager()
            stage='gadget-connect'
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
            script = session.create_script(source, name='dvk-one-chat-manual-send-0.3.35')
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
            root_started=True  # Before RPC: loss of its response remains UNKNOWN.
            result = script.exports_sync.root()
            private = sender.validate(result, before)
            private['native_check'] = sender.diagnostic(result)
            if cancelled():
                raise ReadStopped('cancelled')
            return private
    except Exception as error:
        from startup_failure import record
        record(error,stage)
        if not root_started and type(error).__name__ in {'TransportError','TimedOutError','ServerNotRunningError'}:
            raise SubmissionNotStarted(stage) from None
        raise
    finally:
        done.set()
        timer.cancel()
        if monitor:
            monitor.join(timeout=1)
        cleanup_frida(f, manager, address, script, session, device)



def submit(executable, folder, before, cancelled=lambda: False, *, text=QUESTION):
    text = sender.checked_reply(text)
    before = sender.checked(before)
    def inspector(port, token, cancel, expected):
        if expected != before['identity']:
            raise ReadStopped('identity-not-bound')
        return inspect_submission(port, token, cancel, before, text=text)
    return capture(executable, folder, cancelled, before['identity'], inspector=inspector)
