"""Only synthetic CLI responses; no real ADB or installation."""
import subprocess,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import apk_installer as app

class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.adb=self.root/'adb.exe';self.adb.touch()
        for f in ('base.apk','split-001.apk','split-002.apk'):(self.root/f).touch()
        self.stop=threading.Event();self.calls=[]
    def plan(self,ports='5557 5567'):return app.make_plan(str(self.adb),str(self.root),ports)
    def command(self,args,timeout):
        self.calls.append((args,timeout))
        output='Success\n' if 'install-multiple' in args else 'device\n' if 'get-state' in args else 'connected\n'
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    def test_ports_local_unique_bounded(self):
        self.assertEqual(app.parse_ports('5557,127.0.0.1:5567;5557'),(5557,5567))
        for text in ('','5037','27042','65536','05557','host:5567','127.0.0.2:5567','5557;shutdown','１234'):
            with self.assertRaises(ValueError):app.parse_ports(text)
    def test_missing_apk_fails_before_process(self):
        for p in self.root.glob('split-*.apk'):p.unlink()
        with self.assertRaises(ValueError):self.plan()
        self.assertFalse(self.calls)
    def test_installs_once_explicit_targets_no_uninstall_or_launch(self):
        self.assertEqual(app.install(self.plan(),self.stop,lambda x:None,command=self.command),[(5557,'installed'),(5567,'installed')])
        installs=[a for a,_ in self.calls if 'install-multiple' in a];self.assertEqual(len(installs),2)
        for p,args in zip((5557,5567),installs):
            self.assertEqual(args[:5],[str(self.adb),'-s',f'127.0.0.1:{p}','install-multiple','-r']);self.assertEqual(len(args),8)
        for args,_ in self.calls:
            for bad in ('uninstall','root','shell','devices'):self.assertNotIn(bad,args)
    def test_offline_skipped_next_port_continues(self):
        def command(args,timeout):
            if 'get-state' in args and '127.0.0.1:5557' in args:return SimpleNamespace(returncode=1,stdout='',stderr='offline')
            return self.command(args,timeout)
        self.assertEqual(app.install(self.plan(),self.stop,lambda x:None,command=command),[(5557,'unavailable'),(5567,'installed')])
        self.assertEqual(sum('install-multiple' in a for a,_ in self.calls),1)
    def test_timeout_unknown_no_automatic_replay(self):
        def command(args,timeout):
            self.calls.append((args,timeout))
            if 'install-multiple' in args:raise subprocess.TimeoutExpired(args,timeout)
            return SimpleNamespace(returncode=0,stdout='device\n',stderr='')
        self.assertEqual(app.install(self.plan('5567'),self.stop,lambda x:None,command=command),[(5567,'unknown')])
        self.assertEqual(sum('install-multiple' in a for a,_ in self.calls),1)
    def test_zero_exit_without_success_not_reported_installed(self):
        command=lambda *a:SimpleNamespace(returncode=0,stdout='device\n',stderr='')
        self.assertEqual(app.install(self.plan('5567'),self.stop,lambda x:None,command=command),[(5567,'failed')])
    def test_stop_finishes_current_install_only(self):
        def command(args,timeout):
            value=self.command(args,timeout)
            if 'install-multiple' in args:self.stop.set()
            return value
        self.assertEqual(app.install(self.plan(),self.stop,lambda x:None,command=command),[(5557,'installed')])
        self.assertFalse(any('127.0.0.1:5567' in a for a,_ in self.calls))
    def test_no_shell(self):
        with patch.object(subprocess,'run') as run:app.execute(['adb.exe','-s','127.0.0.1:5567','get-state'],20)
        self.assertIsInstance(run.call_args.args[0],list);self.assertFalse(run.call_args.kwargs.get('shell',False))
    def test_selfcheck_has_no_device_activity(self):
        with patch.object(app.sys,'argv',['installer','--self-check']),patch.object(app,'execute') as run:
            self.assertEqual(app.main(),0);run.assert_not_called()

if __name__=='__main__':unittest.main()
