"""Regression matching user's sanitized SSH/DNS response; no live accounts."""
import sys,socket
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from morelogin_client import plan,compatibility_option
from morelogin_common import CloudError
import morelogin_ssh as ssh

def entry(command=None,host='phone-a.example.test'):
    return dict(id='101',supportAdb=True,enableAdb=True,envStatus=4,remark=None,
        adbIp=host,adbPort='1824',adbPassword='SYNTHETIC-nonnumeric-secret',
        command=command or ('ssh -oHostKeyAlgorithms="+ssh-rsa" cloud_user@'+host+' -p 1824 -L 9897:adb-proxy:14566 -Nf'))

class DomainPlans(unittest.TestCase):
    def test_user_report_shape_ssh_option_userhost_port_forward_Nf(self):
        p=plan(entry(),'101')
        self.assertEqual((p.host,p.user,p.ssh_port,p.remote_host,p.remote_port),('phone-a.example.test','cloud_user',1824,'adb-proxy',14566))
        self.assertNotIn('SYNTHETIC',repr(p))
    def test_quoted_separate_and_algorithm_list_hints(self):
        for hint in ('-oHostKeyAlgorithms="+ssh-rsa"','-o HostKeyAlgorithms=+ssh-rsa,ssh-dss','-o "HostKeyAlgorithms=+ssh-rsa"','-oHostKeyAlgorithms=+ssh-rsa -oPubkeyAcceptedAlgorithms=+ssh-rsa','-oStrictHostKeyChecking=no'):
            command=entry()['command'].replace('-oHostKeyAlgorithms="+ssh-rsa"',hint)
            self.assertEqual(plan(entry(command),'101').host,'phone-a.example.test')
    def test_matching_dns_endpoint_case_and_trailing_dot(self):
        v=entry();v['command']=v['command'].replace('phone-a.example.test','PHONE-A.EXAMPLE.TEST.')
        self.assertEqual(plan(v,'101').host,'phone-a.example.test')
    def test_unknown_options_not_silently_executed(self):
        for option in ('ProxyCommand=whoami','LocalCommand=whoami','HostName=localhost','IdentityFile=/tmp/private','ForwardAgent=yes','HostKeyAlgorithms=+unknown'):
            with self.subTest(option=option),self.assertRaisesRegex(CloudError,'ssh-options-format'):compatibility_option(option)
    def test_dns_must_match_separate_api_endpoint(self):
        for host in ('another.example.test',None,'https://phone-a.example.test','phone-a.example.test:1824','127.0.0.1'):
            v=entry();v['adbIp']=host
            with self.subTest(host=host),self.assertRaisesRegex(CloudError,'ssh-host-format'):plan(v,'101')
    def test_shell_fragments_still_blocked(self):
        for suffix in (' ; whoami',' && whoami',' -oProxyCommand=whoami',' whoami',' -R 9897:localhost:22'):
            with self.subTest(suffix=suffix),self.assertRaises(CloudError):plan(entry(entry()['command']+suffix),'101')
    def test_unrelated_forward_destination_stays_blocked(self):
        with self.assertRaisesRegex(CloudError,'ssh-forward-format'):plan(entry(entry()['command'].replace('adb-proxy','evil.test')),'101')

class DnsTransport(unittest.TestCase):
    def answer(self,ip):return (socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,1824))
    def test_resolves_once_and_connects_numeric_address(self):
        with patch.object(ssh.socket,'getaddrinfo',return_value=[self.answer('8.8.8.8')]) as resolve,patch.object(ssh.socket,'create_connection') as connect:
            self.assertIs(ssh.domain_connection(('phone-a.example.test',1824)),connect.return_value)
            resolve.assert_called_once();connect.assert_called_once_with(('8.8.8.8',1824),timeout=15)
    def test_private_mixed_multicast_or_empty_dns_fail_before_connect(self):
        for ips in ([],['127.0.0.1'],['10.1.2.3'],['169.254.169.254'],['224.0.0.1'],['8.8.8.8','127.0.0.1']):
            with self.subTest(ips=ips),patch.object(ssh.socket,'getaddrinfo',return_value=[self.answer(x) for x in ips]),patch.object(ssh.socket,'create_connection') as connect:
                with self.assertRaisesRegex(CloudError,'ssh-unavailable'):ssh.domain_connection(('phone-a.example.test',1824))
                connect.assert_not_called()
    def test_dns_exception_text_not_exported(self):
        with patch.object(ssh.socket,'getaddrinfo',side_effect=OSError('SECRET')):
            with self.assertRaisesRegex(CloudError,'^ssh-unavailable$'):ssh.domain_connection(('phone-a.example.test',1824))

class SafeFormatReport(unittest.TestCase):
    def test_only_static_diagnostics_no_raw_endpoint_or_secrets(self):
        import json
        from morelogin_diagnostics import format_summary
        e=entry();text=json.dumps(format_summary(e))
        for private in ('cloud_user','phone-a.example.test','9897','14566','1824','SYNTHETIC'):
            self.assertNotIn(private,text)
        self.assertEqual(format_summary(e)['option_keys'],['hostkeyalgorithms'])
        self.assertEqual(format_summary(e)['token_count'],8)

if __name__=='__main__':unittest.main()
