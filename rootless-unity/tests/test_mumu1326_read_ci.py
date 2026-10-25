"""Exact 5561 report: interrupted IsActual is a read budget, not chat failure."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import assistant_history_wait as history
import one_chat_probe
from one_chat_device import ReadStopped
from test_inbox_profiles import Base,nav,snap,msg,WHO
from assistant_exit_notify import notify_exit,REASONS
import assistant_reply_window as window


def actual_budget(**changes):
    value=dict(stage='navigation-stopped',metadata_checkpoint='ready',read_checkpoint='identity',
        wait_reason='none',frames=3,managed_calls=199,scalar_checkpoint='chat-id',
        identity_checkpoint='actual-server-chat',message_slot=4,scalar_state='positive',
        message_direction='own',message_kind='text')
    value.update(changes)
    return ReadStopped('frame-budget',value)


class ActualReadBudget(Base):
    def test_uploaded_exact_shape_retries_then_answers_once(self):
        self.journal();hello=msg(1002,'Привет');q=msg(1003,'Как дела?)',True)
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
            [actual_budget(),snap(hello),snap(hello),snap(hello,q)])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(self.sent,['Как дела?)'])
        self.assertEqual(out['last_chat_diagnostics']['read_retries'],1)
        self.assertEqual(self.nav.call_count,3)
    def test_four_budgets_defer_with_verified_back_no_review_no_send(self):
        self.journal()
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
            [actual_budget() for _ in range(4)])
        self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['history_deferred'],1)
        self.assertEqual(self.reader.call_count,4);self.assertFalse(self.sent)
        self.assertEqual(out['isolated_dialogs'],0)
    def test_identity_or_schema_failure_never_retried_as_budget(self):
        value=dict(error='frame-budget',**actual_budget().diagnostic)
        self.assertTrue(history.verified_read_budget(value))
        for change in (dict(error='identity-not-bound'),dict(error='identity-changed'),
            dict(identity_checkpoint='saved-binding'),dict(scalar_state='zero'),dict(scalar_state='negative'),
            dict(scalar_checkpoint='peer-id'),dict(read_checkpoint='last-message'),dict(metadata_checkpoint='base')):
            self.assertFalse(history.verified_read_budget(dict(value,**change)))
    def test_failed_back_keeps_port_stopped(self):
        self.journal();bad=nav('returned',WHO);bad['diagnostic']['destination_verified']=False
        out=self.walk([nav('opened',WHO),bad],[actual_budget() for _ in range(4)])
        self.assertEqual(out['status'],'inbox-stopped');self.assertFalse(self.sent)
    def test_new_mode_explanation_is_specific_and_policy_stays_blocked(self):
        self.journal();c=self.chain();window.enable(self.store,new_only=True)
        sender=MagicMock(return_value=True)
        out=notify_exit(c,WHO,dict(reason='reply-excluded'),sender=sender)
        self.assertEqual(out['reason'],'new-start-excluded')
        self.assertIn('до запуска',sender.call_args.args[0])
        self.assertEqual(window.reason(self.store,WHO),'new-start-excluded')
    def test_expired_explanation_not_confused_with_new_mode(self):
        self.journal();c=self.chain();window.enable(self.store)
        with self.store.connection() as db:
            db.execute("UPDATE manual_actions SET created_at=datetime('now','-3601 seconds')")
        out=notify_exit(c,WHO,dict(reason='reply-excluded'),sender=lambda text:True)
        self.assertEqual(out['reason'],'reply-window-expired')
    def test_age_unverified_explanation_preserves_fail_closed_rule(self):
        self.journal();c=self.chain();window.enable(self.store)
        with self.store.connection() as db:db.execute("UPDATE manual_actions SET created_at='invalid'")
        out=notify_exit(c,WHO,dict(reason='reply-excluded'),sender=lambda text:True)
        self.assertEqual(out['reason'],'reply-age-unverified')


class NativeCI(unittest.TestCase):
    def test_all_previous_native_suites_preserved_and_unique(self):
        import run_native_tests as runner
        suites=[suite for _,group in runner.SUITES for suite in group]
        self.assertEqual(len(suites),12);self.assertEqual(len(suites),len(set(suites)))
        self.assertEqual(set(suites),{'assistant_pass','mumu_claims','assistant_preview','search_online',
            'search_city','one_chat','one_chat_send','one_chat_name','dialog_navigation',
            'dialog_browser','contact_profile','dialog_models'})
    def test_chunk_specialization_keeps_long_history_bounds_and_two_samples(self):
        source=one_chat_probe.build(WHO,scoped_traversal=True)
        self.assertIn('const chunkSize=first<=16?1:4;',source)
        self.assertIn('n.samples=2',source)
        self.assertIn('chunk.identity!==JSON.stringify(who)',source)
        self.assertIn("if(chunk.localOwn>0&&chunk.peerAnchors===0)fail('local-own-message-unanchored');",source)
        self.assertIn('const deadline=Date.now()+100;',source)
