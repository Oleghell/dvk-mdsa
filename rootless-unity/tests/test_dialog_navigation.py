import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import dialog_navigation as route
import assistant_cycle as cycle
from assistant_settings import Settings
from test_uikit_navigation import ready_navigation


def ready_route():
    value=ready_navigation();n=value['navigation']
    n['dialogs_verified']=n.pop('filters_verified')
    n['back_attempted']=n.pop('cancel_attempted')
    n['back_completed']=n.pop('cancel_completed')
    return value


class RouteSchema(unittest.TestCase):
    def test_roundtrip_success_has_no_private_values(self):
        v=ready_route();self.assertIs(route.validate(v),v)
        self.assertNotIn('filters_verified',v['navigation'])
        self.assertFalse(v['navigation']['ui_text_read'])

    def test_unknown_fields_and_legacy_aliases_rejected(self):
        for field in ('peer_name','filters_verified','cancel_attempted','cancel_completed','private_result'):
            v=ready_route();v['navigation'][field]='PRIVATE'
            with self.assertRaises(ValueError):route.validate(v)

    def test_all_flags_and_attached_same_search_required(self):
        for flag in ('search_verified','dialogs_verified','return_verified','open_attempted','open_completed','back_attempted','back_completed'):
            v=ready_route();v['navigation'][flag]=False
            with self.assertRaises(ValueError):route.validate(v)
        for k,vv in [('main_thread_confirmed',False),('cleanup_failed',True)]:
            v=ready_route();v[k]=vv
            with self.assertRaises(ValueError):route.validate(v)

    def test_unknown_screens_and_old_phases_rejected(self):
        for k,x in [('phase','wait-filters'),('root_top_kind','filters'),('controller_path',['private-person']),('ui_text_read',True)]:
            v=ready_route();v['navigation'][k]=x
            with self.assertRaises(ValueError):route.validate(v)

    def test_only_one_fixed_tab_action_no_chat_read_or_send(self):
        s=route.FUNCTION
        for text in ('OnSend','get_Text','get_Name','get_ItemId','ShowChat','OnCellDidClicked','ShowSearchSettings','DismissWithCancel','get_Subviews','il2cpp_field_','input tap','setInterval','rpc.exports'):
            self.assertNotIn(text,s)
        for text in ('DV.IMainTabsController.SwitchToTab','MessagesTabController','ChatsViewController','get_TopViewController','routeSignature','type_get_object','class_get_type','main-thread-check',"for(const key of ['card','origin','tabs'])"):
            self.assertIn(text,s)
        self.assertEqual(s.count('switchTab(s.messageTab)'),1)
        self.assertEqual(s.count('switchTab(s.search)'),1)

    def test_snapshot_reader_cannot_be_substituted_for_route(self):
        with self.assertRaises(ValueError):route.inspect(1,'secret',lambda:False,expected={'chat':'1'})


class CycleReport(unittest.TestCase):
    def call(self,result=None,error=None,stopped=None):
        with tempfile.TemporaryDirectory() as temp, patch.object(cycle,'operation_lock'), \
             patch.object(cycle,'data_directory',return_value=Path(temp)), \
             patch.object(cycle,'run_route',return_value=result,side_effect=error) as run:
            outcome=cycle.start(Settings(),stopped or threading.Event())
            p=Path(temp)/'messages-navigation-check.json'
            report=json.loads(p.read_text()) if p.exists() else None
            return outcome,report,run.call_count

    def test_transport_error_exports_no_exception_secrets(self):
        outcome,report,_=self.call(error=RuntimeError('TOKEN PRIVATE PATH'))
        self.assertEqual(outcome['status'],'blocked')
        self.assertNotIn('TOKEN',json.dumps(report));self.assertNotIn('PRIVATE',json.dumps(report))
        self.assertTrue(report['ui_actions_may_have_occurred'])
        self.assertEqual(report['messages_sent'],0)

    def test_invalid_private_result_cannot_enter_report(self):
        value=ready_route();value['navigation']['private_result']='PRIVATE'
        outcome,report,_=self.call(result=value)
        self.assertEqual(outcome['status'],'blocked')
        self.assertNotIn('PRIVATE',json.dumps(report));self.assertNotIn('navigation',report)

    def test_partial_transition_never_claims_success(self):
        v=ready_route();v['navigation'].update(stage='navigation-stopped',error='managed-exception',return_verified=False,back_completed=False)
        outcome,report,_=self.call(result=v)
        self.assertEqual(outcome['status'],'blocked');self.assertEqual(report['status'],'route-stopped')
        self.assertFalse(outcome['live_cycle_available'])

    def test_stop_before_start_has_no_device_or_disk_activity(self):
        stop=threading.Event();stop.set()
        outcome,report,calls=self.call(stopped=stop)
        self.assertEqual(outcome['status'],'cancelled');self.assertIsNone(report);self.assertEqual(calls,0)

    def test_atomic_report_has_only_fixed_evidence(self):
        outcome,report,_=self.call(result=ready_route())
        self.assertEqual(outcome['status'],'dialog-route-ready')
        self.assertEqual(outcome['report_name'],'messages-navigation-check.json')
        self.assertFalse(report['live_cycle_available'])
        self.assertFalse(report['personal_data_exported'])
        self.assertEqual(report['device_scope'],'MuMu-4-only')

if __name__=='__main__':unittest.main()
