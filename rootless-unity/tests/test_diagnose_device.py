import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_native_metadata import ready_metadata
spec=importlib.util.spec_from_file_location('diagnose_core',Path(__file__).resolve().parents[1]/'diagnose_device.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def runtime():return {'frida_version':'17.24.1','arch':'arm64','platform':'linux'}
def evidence():
    return {'maps_available':True,'maps_complete':True,'map_line_count':20,'map_limit_reached':False,
            'mapped_ranges':{n:0 for n in m.FIXED_MODULES},'apk_mappings_present':False,
            'global_export_api_available':True,'global_exports':{n:False for n in m.EXPORTS},'global_export_errors':0}


def modules(ready=True):
    return {'module_count':100,'fixed_modules':{n:ready for n in m.FIXED_MODULES},
            'il2cpp_exports':{n:ready for n in m.EXPORTS},'engine_name_matches':2 if ready else 0}


class Guard:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def cancel(self):pass


class FakeFrida:
    __version__='17.24.1'
    Cancellable=Guard
    def __init__(self,name='Gadget',phase_error=None,ready=True,count=1):
        self.name=name;self.phase_error=phase_error;self.ready=ready;self.count=count;self.attached_to=None
        self.script_unloaded=False;self.detached=False;self.removed=False
    def get_device_manager(self):return self
    def add_remote_device(self,address,token):return self
    def remove_remote_device(self,address):self.removed=True
    def enumerate_processes(self):
        if self.phase_error=='enumerate':raise type('ServerNotRunningError',(Exception,),{})('PRIVATE TOKEN')
        return [SimpleNamespace(pid=123456789,name=self.name) for _ in range(self.count)]
    def attach(self,target):self.attached_to=target;return self
    def create_script(self,source,name):
        self.script_source=source
        self.exports_sync=SimpleNamespace(runtime=lambda:runtime(),modules=self.get_modules,evidence=evidence,native=ready_metadata)
        return self
    def get_modules(self):
        if self.phase_error=='rpc':raise type('RPCException',(Exception,),{})('PRIVATE TOKEN')
        return modules(self.ready)
    def load(self):pass
    def unload(self):self.script_unloaded=True
    def detach(self):self.detached=True


class Inspect(unittest.TestCase):
    def test_attach_numeric_unique_pid_not_legacy_name(self):
        f=FakeFrida(name='private dynamic process name')
        r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f)
        self.assertEqual(f.attached_to,123456789)
        self.assertEqual(r['stage'],'metadata-ready');self.assertTrue(r['rpc_runtime_ok'])
        self.assertEqual(r['discovery_stage'],'modules-ready');self.assertTrue(r['rpc_native_ok'])
        self.assertEqual(r['process_name_kind'],'other-name-not-recorded')
        text=json.dumps(r)
        self.assertNotIn('123456789',text);self.assertNotIn('private dynamic',text)
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
    def test_partial_module_result_not_hidden_as_timeout(self):
        r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=FakeFrida(ready=False))
        self.assertEqual(r['stage'],'metadata-ready')
        self.assertEqual(r['discovery_stage'],'engine-not-confirmed')
        self.assertTrue(r['connected'] and r['attached'] and r['rpc_modules_ok'])
        self.assertEqual(r['modules']['engine_name_matches'],0)
    def test_rpc_error_keeps_stage_not_sensitive_exception(self):
        r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=FakeFrida(phase_error='rpc'))
        self.assertEqual(r['stage'],'modules-rpc');self.assertTrue(r['rpc_runtime_ok'])
        self.assertFalse(r['rpc_modules_ok'])
        self.assertEqual(r['error_types'],[{'stage':'modules-rpc','type':'RPCException'}])
        self.assertNotIn('PRIVATE',json.dumps(r))
    def test_connection_failure_preserves_type_and_finite_attempts(self):
        r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=FakeFrida(phase_error='enumerate'))
        self.assertFalse(r['connected']);self.assertEqual(r['attempts'],3)
        self.assertEqual(r['stage'],'enumerate-processes')
        self.assertEqual(len(r['error_types']),3);self.assertNotIn('PRIVATE',json.dumps(r))
    def test_no_attach_when_multiple_or_no_processes(self):
        for count in (0,2):
            f=FakeFrida(count=count);r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=f)
            self.assertIsNone(f.attached_to);self.assertEqual(r['stage'],'not-exactly-one-process')
    def test_cancel_and_cleanup(self):
        f=FakeFrida();r=m.inspect_gadget(37149,'a'*64,lambda:True,frida_api=f)
        self.assertEqual(r['stage'],'cancelled');self.assertIsNone(f.attached_to)
    def test_arch_is_diagnostic_not_silently_discarded(self):
        self.assertEqual(m.validate_runtime({'frida_version':'17.24.1','arch':'x64','platform':'linux'})['arch'],'x64')
    def test_schema_blocks_extra_data_and_invalid_counts(self):
        for bad in ({**runtime(),'profile':'private'},{**runtime(),'arch':'secret' }):
            with self.assertRaises(m.TestError):m.validate_runtime(bad)
        for bad in ({**modules(),'paths':['private']},{**modules(),'module_count':-1},{**modules(),'module_count':True}):
            with self.assertRaises(m.TestError):m.validate_modules(bad)
    def test_non_arm_runtime_does_not_call_native(self):
        with patch.object(m,'validate_runtime',return_value={'frida_version':'17.24.1','arch':'x64','platform':'linux'}):
            with patch(__name__+'.ready_metadata',side_effect=AssertionError('must not call')):
                r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=FakeFrida())
        self.assertEqual(r['stage'],'modules-ready');self.assertFalse(r['rpc_native_ok'])
    def test_native_failure_is_not_retried(self):
        with patch(__name__+'.ready_metadata',side_effect=RuntimeError('PRIVATE POINTER')) as native:
            r=m.inspect_gadget(37149,'a'*64,lambda:False,frida_api=FakeFrida())
        self.assertEqual(native.call_count,1)
        self.assertEqual(r['stage'],'native-metadata-rpc')
        self.assertTrue(r['rpc_evidence_ok']);self.assertFalse(r['rpc_native_ok'])
        self.assertNotIn('PRIVATE',json.dumps(r))
    def test_fixed_script_metadata_only(self):
        for text in ('il2cpp_runtime_invoke','il2cpp_runtime_class_init','Interceptor','Java.perform','setText','set_text','sendMessage'):
            self.assertNotIn(text,m.SCRIPT)


class ReadOnly(unittest.TestCase):
    def test_no_install_launch_clear_or_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'adb.exe').touch();adb=m.DiagnosticAdb(str(root/'adb.exe'),root)
            for args in (['-s',m.TARGET,'install-multiple',str(root/'base.apk'),str(root/'split-001.apk')],
                         ['-s',m.TARGET,'shell','am','start','-n','drug.vokrug/drug.vokrug.activity.Launcher'],
                         ['-s',m.TARGET,'shell','pm','clear','drug.vokrug'],
                         ['-s',m.WORKING,'shell','ss','-ltn'],['-s',m.TARGET,'root']):
                with self.assertRaises(m.TestError):adb.validate(args)
            adb.validate(['-s',m.TARGET,'shell','pidof','drug.vokrug'])
            adb.validate(['-s',m.TARGET,'shell','ss','-ltn'])
    def test_listening_parser_boolean_only(self):
        self.assertTrue(m.listening_port('LISTEN 0 10 127.0.0.1:27042 0.0.0.0:*'))
        self.assertTrue(m.listening_port('LISTEN 0 10 [::1]:27042 *:*'))
        self.assertFalse(m.listening_port('LISTEN 0 10 127.0.0.1:27043 0.0.0.0:*'))


class Report(unittest.TestCase):
    def test_report_no_ids_pid_socket_addresses_or_token(self):
        class Adb:
            forward_port=None
            def run(self,args,timeout=30):
                if 'pidof' in args:return '123456789'
                if 'ss' in args:return 'LISTEN 0 10 127.0.0.1:27042 0.0.0.0:*'
                if args[-2:]==['tcp:0','tcp:27042']:return '37149'
                return ''
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir()
            with patch.object(m,'bundle_token',return_value='a'*64),patch.object(m,'preflight',return_value=('PRIVATE ID1','PRIVATE ID2')),patch.object(m,'recheck'):
                result,path=m.diagnose(Adb(),folder,inspector=lambda *a:{'stage':'modules-ready'})
            self.assertEqual(result['status'],'modules-ready');self.assertFalse(result['install_requested'])
            text=path.read_text(encoding='utf-8')
            for secret in ('a'*64,'123456789','PRIVATE ID','0.0.0.0:*'):self.assertNotIn(secret,text)
            self.assertTrue(result['guest_port_27042_listening'])
            self.assertEqual(path.name,'rootless-diagnostics-0.1.3.json')


if __name__=='__main__':unittest.main()
