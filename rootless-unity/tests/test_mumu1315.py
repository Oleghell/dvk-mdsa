"""Synthetic refusal regression and transport fault injection; no user API calls."""
import json,unittest
from unittest.mock import MagicMock,patch
from test_mumu1311_context import Refusals as Fixture
from test_guided_chain import snapshot,WHO,GREETING,QUESTIONS,CONTACT_TEXT
import assistant_contact_followup as follow
import startup_failure as failure
import assistant_error_notify as notify
from assistant_failure import category
from test_one_chat import ReadTransport as TransportBase
from test_inbox_profiles import Base,nav

PRIVATE='PRIVATE BODY TOKEN PHONE PATH'

def error_at(stage,name='TransportError'):
    error=type(name,(Exception,),{})(PRIVATE)
    failure.record(error,stage)
    return error

class Refusals(unittest.TestCase):
    chain=Fixture.chain
    def test_bare_here_is_context_gated_and_not_substring(self):
        for text in ('Тут)','тут','Здесь!','здесь ))'):
            self.assertTrue(follow.refused([dict(text=text)],requested=True),text)
            self.assertFalse(follow.refused([dict(text=text)],requested=False),text)
        for text in ('Ты тут?','Я тут работаю','Тут у тебя номер?','> Тут)\nДля чего?','Здесь мой номер 89123456789'):
            self.assertFalse(follow.refused([dict(text=text)],requested=True),text)
    def test_new_here_declines_before_ai_and_future_questions_never_reopen(self):
        for text in ('Тут)','Здесь'):
            c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
            self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
            self.assertEqual(c.proposal(snapshot(*h,(text,False),('Женат?',False))),('declined',None))
            c.responder.assert_not_called()
            with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM chain_actions').fetchone()[0],2)
    def test_old_here_already_answered_by_previous_version_is_terminal(self):
        c,store,h=self.chain();h += [('Тут)',False)]
        with patch('assistant_contact_followup.refused',return_value=False),patch('assistant_chain.contact_refused',return_value=False):
            _,a=c.proposal(snapshot(*h));c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            h += [(a['text'],True)];c.proposal(snapshot(*h))
        c.responder=MagicMock(side_effect=AssertionError('No AI'))
        self.assertEqual(c.proposal(snapshot(*h,('Женат?',False))),('declined',None))
        c.responder.assert_not_called()
    def test_bare_here_before_contact_is_not_retrospective_refusal(self):
        c,store,h=self.chain()
        # Same complete verified messages; change an early peer input before
        # initial binding, not a fingerprint already journaled by consume.
        import tempfile
        from pathlib import Path
        from assistant_store import Store
        from assistant_guided_chain import GuidedChain
        with tempfile.TemporaryDirectory() as folder:
            c=GuidedChain(Store(Path(folder)/'x.sqlite3',Path(folder)/'old'),choose=lambda:0,seal=lambda x:x,unseal=lambda x:x)
            c.bind(snapshot(),(GREETING,),approved=True)
            history=[('Тут)',False),(QUESTIONS[0],True),('Отлично',False),(CONTACT_TEXT,True)]
            for i in range(1,5):
                _,a=c.proposal(snapshot(*history[:i]))
                if a:c.reserve_confirmed(WHO,a);c.finish(WHO,a,True)
            stage,a=c.proposal(snapshot(*history,('Для чего?',False)))
            self.assertNotEqual(stage,'declined');self.assertIsNotNone(a)
    def test_here_does_not_reset_unknown_action(self):
        c,store,h=self.chain()
        with store.connection() as db:db.execute("UPDATE chain_actions SET status='reserved-unknown' WHERE kind='contact'")
        self.assertEqual(c.proposal(snapshot(*h,('Тут)',False))),('declined',None))
        with store.connection() as db:self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone()[0],'reserved-unknown')

class Diagnostics(unittest.TestCase):
    def test_closed_native_categories(self):
        for name,code in [('TransportError','native-transport-error'),('RPCException','native-script-error'),('OperationCancelledError','native-operation-cancelled'),('ProcessNotFoundError','native-process-unavailable'),('InvalidOperationError','native-state-error')]:
            self.assertEqual(category(error_at('script-run',name)),code)
    def test_cloud_keeps_exact_failure_stage_and_type_not_exception_body(self):
        for stage in failure.STAGES:
            data=notify.diagnostic_json(dict(status='stopped',last_pass=dict(last_navigation_failure=failure.record(error_at(stage),stage))))
            value=json.loads(data)['diagnostic']['last_pass']['last_navigation_failure']
            self.assertEqual(value['stage'],stage);self.assertEqual(value['error_type'],'TransportError')
            self.assertNotIn(PRIVATE.encode(),data)
    def test_adb_evidence_remains_closed(self):
        e=error_at('forward-open');v=e._dvk_failure;v.update(adb_check='test-forward-open',adb_reason='command-timeout')
        data=json.loads(notify.diagnostic_json(dict(last_preparation_failure=v)))['diagnostic']['last_preparation_failure']
        self.assertEqual(data['adb_reason'],'command-timeout')
    def test_retry_only_pre_script_transport_not_rpc_or_post_root(self):
        for stage in failure.STAGES:
            for name in ('TransportError','RPCException','RuntimeError','TimedOutError'):
                self.assertEqual(failure.retryable_connection(error_at(stage,name)),stage in {'gadget-connect','gadget-process','gadget-attach'} and name in {'TransportError','TimedOutError'})

class Connection(TransportBase):
    def test_single_transient_setup_reconnect_then_success(self):
        from test_target_only import BOOT
        self.identities=iter([BOOT]*8)
        read=MagicMock(side_effect=[error_at('gadget-connect'),{'ok':True}])
        self.assertEqual(self.run_capture(read),{'ok':True});self.assertEqual(read.call_count,2)
    def test_persistent_setup_failure_is_bounded(self):
        read=MagicMock(side_effect=error_at('gadget-attach'))
        with self.assertRaises(Exception):self.run_capture(read)
        self.assertEqual(read.call_count,2)
    def test_root_unknown_script_load_and_validation_never_repeat(self):
        from test_target_only import BOOT
        for stage in ('script-create','script-load','script-run','result-validation'):
            self.identities=iter([BOOT]*8)
            read=MagicMock(side_effect=error_at(stage))
            with self.assertRaises(Exception):self.run_capture(read)
            self.assertEqual(read.call_count,1)
    def test_cancel_does_not_reconnect(self):
        import one_chat_device as device
        read=MagicMock(side_effect=error_at('gadget-connect'))
        cancel=MagicMock(side_effect=[False,True])
        with self.patched(),patch.object(device,'TargetOnlyAdb',return_value=self.adb),patch.object(device,'bundle_token',return_value='PRIVATE TOKEN'):
            with self.assertRaises(Exception):device.capture('adb',self.folder,cancelled=cancel,inspector=read)
        self.assertEqual(read.call_count,1)

class InboxEvidence(Base):
    def test_open_failure_preserved_no_send(self):
        self.journal()
        out=self.walk([error_at('script-run','RPCException')],[])
        self.assertEqual(out['host_failure'],'native-script-error')
        self.assertEqual(out['last_navigation_failure']['stage'],'script-run');self.assertFalse(self.sent)
        self.assertNotIn(PRIVATE.encode(),notify.diagnostic_json(out))

if __name__=='__main__':unittest.main()

class ProfileTransportEvidence(unittest.TestCase):
    def test_profile_pre_script_connection_phase_is_recorded(self):
        import assistant_pass as native
        from test_search_online import OnlineFake
        for method,stage in [('add_remote_device','gadget-connect'),('enumerate_processes','gadget-process'),('attach','gadget-attach'),('load','script-load')]:
            f=OnlineFake();bad=MagicMock(side_effect=error_at(stage));setattr(f,method,bad)
            store=MagicMock();store.visited_peers.return_value=[]
            with self.assertRaises(Exception) as e:native.inspect(37149,'private',lambda:False,'Hi',store,lambda *a:False,frida_api=f)
            self.assertEqual(e.exception._dvk_failure['stage'],stage);bad.assert_called_once()
    def test_profile_root_rpc_failure_is_not_replayed(self):
        import assistant_pass as native
        from test_search_online import OnlineFake
        f=OnlineFake();original=f.create_script;root=MagicMock(side_effect=error_at('script-run','RPCException'))
        def create(*a,**kw):
            value=original(*a,**kw);f.exports_sync.root=root;return value
        f.create_script=create;store=MagicMock();store.visited_peers.return_value=[]
        with self.assertRaises(Exception) as e:native.inspect(37149,'private',lambda:False,'Hi',store,lambda *a:False,frida_api=f)
        self.assertEqual(e.exception._dvk_failure['stage'],'script-run');root.assert_called_once()
        self.assertTrue(f.script_unloaded and f.detached and f.removed)
