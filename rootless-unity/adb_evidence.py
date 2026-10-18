"""Data-minimal ADB evidence: fixed labels/categories, never raw output or argv."""
import re
from test_device import TARGET,WORKING,PACKAGE,BOOT_ID

MAX_EVENTS=40
REASONS={'none','connection-refused','connection-timeout','connection-failed','device-offline',
         'device-unauthorized','device-not-found','no-device','ambiguous-device','adb-version-mismatch',
         'adb-server-unavailable','permission-denied','unsupported-command','command-failed',
         'command-timeout','executable-launch-failed','oversized-output','unexpected-response'}


def check_label(args):
    a=tuple(args)
    if a==('version',):return 'adb-version'
    for serial,prefix in ((WORKING,'working'),(TARGET,'test')):
        if a==('connect',serial):return prefix+'-connect'
        if a==('-s',serial,'get-state'):return prefix+'-state'
        if a==('-s',serial,'shell','cat',BOOT_ID):return prefix+'-identity'
    fixed={('shell','getprop','sys.boot_completed'):'test-boot-completed',
           ('shell','pm','list','packages',PACKAGE):'test-package-presence',
           ('shell','pidof',PACKAGE):'test-process-presence',
           ('shell','ss','-ltn'):'test-listener-presence',
           ('shell','getprop','ro.product.cpu.abi'):'test-primary-abi',
           ('shell','getprop','ro.dalvik.vm.native.bridge'):'test-native-bridge',
           ('forward','tcp:0','tcp:27042'):'test-forward-open'}
    if a[:2]==('-s',TARGET):
        op=a[2:]
        if op in fixed:return fixed[op]
        if len(op)==3 and op[:2]==('forward','--remove') and re.fullmatch(r'tcp:[0-9]{4,5}',op[2]):return 'test-forward-close'
    return 'unrecognized-check'


def classify(text):
    s=text.lower()
    # Output is inspected in memory only. No substring, address, path or exception leaves this function.
    patterns=[
        ('adb-version-mismatch',("doesn't match this client",'server version mismatch','client version mismatch')),
        ('device-unauthorized',('unauthorized','authentication failed')),
        ('device-offline',('device offline',)),
        ('no-device',('no devices/emulators found','no devices found')),
        ('ambiguous-device',('more than one device/emulator',)),
        ('device-not-found',('device not found',)),
        ('adb-server-unavailable',('cannot connect to daemon','failed to start daemon',"server didn't ack",'cannot bind','cannot connect to server','could not read ok from adb server')),
        ('permission-denied',('permission denied','access is denied')),
        ('connection-refused',('connection refused','actively refused')),
        ('connection-timeout',('connection timed out',)),
        ('unsupported-command',('unknown command','unknown option','unrecognized command')),
        ('connection-failed',('cannot connect to','failed to connect to','unable to connect to')),
    ]
    if re.search(r'\b10061\b',s):return 'connection-refused'
    if re.search(r'\b10060\b',s):return 'connection-timeout'
    for reason,terms in patterns:
        if any(term in s for term in terms):return reason
    if re.search(r'\bdevice\s+[\'\"][^\r\n]*?[\'\"]\s+not found\b',s):return 'device-not-found'
    return 'none'


def event(args,returncode,text,outcome='completed'):
    label=check_label(args)
    reason={'timeout':'command-timeout','launch-failed':'executable-launch-failed',
            'oversized-output':'oversized-output'}.get(outcome)
    if reason is None:reason=classify(text)
    if reason=='none' and returncode!=0:reason='command-failed'
    if reason=='none':
        value=text.strip()
        if label.endswith('-state') and value!='device':
            reason={'offline':'device-offline','unauthorized':'device-unauthorized','unknown':'device-not-found'}.get(value,'unexpected-response')
        elif label.endswith('-identity') and not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value):reason='unexpected-response'
        elif label=='test-boot-completed' and value!='1':reason='unexpected-response'
        elif label=='test-package-presence' and value not in ('','package:'+PACKAGE):reason='unexpected-response'
    code=returncode if type(returncode) is int and -32768<=returncode<=65535 else None
    return {'check':label,'status':'passed' if reason=='none' else 'failed','reason':reason,'return_code':code}
