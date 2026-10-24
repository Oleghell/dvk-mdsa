"""Reported draft/navigation failures, no real accounts or provider requests."""
import json
from unittest.mock import MagicMock
from test_inbox_profiles import Base, WHO, OTHER, GREETING, nav, msg, snap
import assistant_inbox as inbox
import assistant_error_notify as notify
import dialog_browser as browser
from assistant_navigation_check import safe_diagnostic
from test_dialog_browser import raw_open

class DraftIsolation(Base):
    def prepare_bad(self):
        self.journal();before=snap(msg(1002,'Привет'))
        model=MagicMock(return_value=dict(decision='reply',text='Как настроение?'))
        chain=inbox.InboxChain(self.store,responder=model,seal=lambda v:v,unseal=lambda v:v)
        chain.bind(before,(GREETING,),approved=True);chain.proposal(before)
        with self.store.connection() as db:
            db.execute('UPDATE ai_drafts SET payload=?',(b'CORRUPT_PRIVATE',))
            draft=db.execute('SELECT * FROM ai_drafts').fetchall()
            actions=db.execute('SELECT * FROM chain_actions').fetchall()
        model.reset_mock()
        return chain,model,before,draft,actions
    def test_bad_saved_draft_isolated_then_next_chat_runs(self):
        chain,model,before,draft,actions=self.prepare_bad();self.journal(OTHER)
        other=snap(msg(1002,'Привет',who=OTHER),who=OTHER)
        after=snap(msg(1002,'Привет',who=OTHER),msg(1003,'Как настроение?',True,who=OTHER),who=OTHER)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('opened',OTHER),nav('returned',OTHER),nav('search-ready')],
            [before,other,other,after],chain=chain)
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['isolated_reasons'],{'groq-draft-unavailable':1})
        self.assertEqual(self.sent,['Как настроение?']);self.assertEqual(model.call_count,1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT * FROM ai_drafts WHERE chat=?',(WHO['chat'],)).fetchall(),draft)
            self.assertEqual(db.execute('SELECT * FROM chain_actions WHERE chat=?',(WHO['chat'],)).fetchall(),actions)
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs WHERE peer=?',(WHO['peer'],)).fetchone()[0],'manual-review')
        active=sum(inbox.inbox_targets(self.chain()),[])
        self.assertNotIn(WHO['peer'],[x['peer'] for x in active])
        self.assertNotIn('CORRUPT_PRIVATE',json.dumps(out))
    def test_bad_back_retains_block_and_never_sends_or_regenerates(self):
        chain,model,before,draft,actions=self.prepare_bad()
        out=self.walk([nav('opened',WHO),nav('returned',OTHER)],[before],chain=chain)
        self.assertEqual(out['status'],'inbox-stopped');self.assertFalse(self.sent)
        model.assert_not_called();self.assertEqual(inbox.inbox_targets(self.chain()),([],[]))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT * FROM ai_drafts').fetchall(),draft)
            self.assertEqual(db.execute('SELECT * FROM chain_actions').fetchall(),actions)

class NavigationEvidence(Base):
    def test_slow_entry_retry_counter_bounded_not_boolean(self):
        for bad in (-1,4,True,'1'):
            v=raw_open();v['navigation']['entry_read_budget_retries']=bad
            with self.assertRaises(ValueError):browser.validate(v,'open',allowed=[WHO])
        for n in range(4):
            v=raw_open();v['navigation']['entry_read_budget_retries']=n
            out=browser.validate(v,'open',allowed=[WHO]);safe_diagnostic(out['diagnostic'])
    def test_json_keeps_closed_phase_actions_and_counters_without_raw_data(self):
        report=dict(status='stopped',last_navigation=dict(stage='navigation-stopped',error='frame-budget',phase='entry',
            action_attempted=False,action_completed=False,selection_checkpoint='not-checked',entry_read_budget_retries=3,
            raw='PRIVATE',identity=WHO))
        data=notify.diagnostic_json(report);n=json.loads(data)['diagnostic']['last_navigation']
        self.assertEqual(n['phase'],'entry');self.assertIs(n['action_attempted'],False)
        self.assertIs(n['action_completed'],False);self.assertEqual(n['entry_read_budget_retries'],3)
        self.assertNotIn(b'PRIVATE',data);self.assertNotIn(b'peer',data)
        report['last_navigation']['phase']='PRIVATE';self.assertNotIn(b'PRIVATE',notify.diagnostic_json(report))
