import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from mumu_bridge import AdbReader, BridgeError, GREETINGS, content_pixel_sha256, input_context_sha256, profile_guard
from session_bridge import SupervisedReader, matches, GRID_BOX, GRID_SHA, EMPTY_BOX, EMPTY_SHA, SEND_BOX, SEND_SHA
from test_session import TestSession, SessionError

FIXTURES=json.loads((Path(__file__).parent/'session-ui-fixtures.json').read_text())

class SyntheticTransport:
    """Runs the REAL Python transport and session facade, but NO Android/ADB."""
    def __init__(self,path):
        adb=path/'adb.exe';adb.touch()
        self.reader=AdbReader(adb);self.reader.helper_ready=True
        self.reader.screen=lambda:self.frame
        self.reader.inspect_layout=self.inspect
        self.reader._instrument=self.instrument
        self.native='';self.focused=False;self.person=1;self.mode='grid';self.switch_fixture='online';self.fail=None;self.events=[]
        self.render()
    def render(self):
        im=Image.new('RGB',(900,1600),'white');draw=ImageDraw.Draw(im)
        # Synthetic recipient marker only. No real names, avatars or screenshots.
        draw.rectangle((120,70,150,100),fill=(self.person,0,0))
        if self.mode=='profile':
            icon=Image.open(BytesIO(base64.b64decode((Path(__file__).resolve().parents[1]/'button-fixture-base64.txt').read_text()))).convert('RGB');im.paste(icon,(274,1468))
        keys={'grid':['grid'],'chat':['empty'],'draft':['empty'],'finished':['empty','send'],'sent':[],'profile':[],'filter':['filter','online_label',self.switch_fixture]}[self.mode]
        for key in keys:
            item=FIXTURES[key];im.paste(Image.open(BytesIO(base64.b64decode(item['png']))),tuple(item['box'][:2]))
        if self.native:draw.text((160,1500),self.native,fill='black')
        if self.mode=='sent':draw.text((650,1100),'synthetic outgoing',fill='black')
        b=BytesIO();im.save(b,format='PNG');self.frame=b.getvalue()
    def inspect(self):
        nodes=[]
        if self.mode in ('chat','draft','finished','sent'):
            nodes=[{'editable':True,'text':self.native,'enabled':True,'class':'android.widget.EditText','bounds':[152,1488,748,1544],'focused':self.focused}]
        return {'nodes':nodes,'content_sha256':content_pixel_sha256(self.frame),'truncated':False}
    def instrument(self,op,sha='0'*64,x=0,y=0):
        self.events.append((op,x,y))
        if self.fail:raise BridgeError('Synthetic timeout')
        if op=='tap':
            if self.mode=='grid':self.mode='filter' if x>=770 else 'profile'
            elif self.mode=='filter':
                if y>=1468:self.mode='grid'
                else:self.switch_fixture='online' if self.switch_fixture=='offline' else 'offline'
            elif self.mode=='chat':self.focused=True
            elif self.mode=='finished':self.mode='sent';self.native=''
        elif op=='profile_chat':self.mode='chat'
        elif op=='greeting':self.native=GREETINGS[x];self.mode='draft'
        elif op=='finish_input':self.focused=False;self.mode='finished'
        elif op in ('back','profile_back'):self.mode='grid'
        self.render()
        return ('greeting_draft_verified' if op=='greeting' else 'input_injected','')

class SessionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.transport=SyntheticTransport(self.path);self.ledger=TestSession(self.path/'test.sqlite');self.r=SupervisedReader(self.transport.reader,self.ledger)
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def sha(self):return content_pixel_sha256(self.transport.frame)
    def authorize_online(self):
        self.r.navigate('tap',self.sha(),815,1514)
        self.r.navigate('tap',self.sha(),808,1515)
    def enter(self,n=1):
        if not self.r.online_confirmed:self.authorize_online()
        self.transport.person=n;self.transport.render()
        self.r.begin_profile(self.sha(),120,200)
        self.r.open_profile_chat(profile_guard(self.transport.frame)['profile_sha256'])
        return self.r.check_new_chat(self.sha())
    def draft(self):
        self.enter();self.r.navigate('tap',self.sha(),400,1515)
        self.r.prepare_greeting(input_context_sha256(self.transport.frame),0)
    def finish(self):
        self.draft();self.r.finish_greeting_input(input_context_sha256(self.transport.frame),0)
    def test_static_control_fixtures_match(self):
        self.assertTrue(matches(self.transport.frame,GRID_BOX,GRID_SHA))
        self.transport.mode='chat';self.transport.render();self.assertTrue(matches(self.transport.frame,EMPTY_BOX,EMPTY_SHA))
        self.transport.mode='finished';self.transport.render();self.assertTrue(matches(self.transport.frame,SEND_BOX,SEND_SHA))
    def test_no_mutation_before_local_start(self):
        with self.assertRaises(BridgeError):self.r.begin_profile(self.sha(),120,200)
        self.assertEqual(self.transport.events,[])
    def test_complete_five_profile_supervised_path(self):
        self.ledger.start(5)
        for n in range(1,6):
            self.assertTrue(self.enter(n)['eligible'])
            self.r.navigate('tap',self.sha(),400,1515)
            self.r.prepare_greeting(input_context_sha256(self.transport.frame),n-1)
            self.r.finish_greeting_input(input_context_sha256(self.transport.frame),n-1)
            result=self.r.send_prepared(self.sha())
            self.assertFalse(result['message_sent_verified'])
            self.assertEqual(self.ledger.status()['sent_observed_by_agent'],n-1)
            self.r.review_visit(self.sha(),'sent_observed')
            self.r.return_to_grid(self.sha())
        s=self.ledger.status();self.assertEqual((s['visited'],s['send_attempts'],s['sent_observed_by_agent'],s['state']),(5,5,5,'completed'))
        with self.assertRaises(BridgeError):self.r.begin_profile(self.sha(),120,200)
    def test_grid_tiles_not_accessible_by_generic_tap(self):
        self.ledger.start(5)
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),120,200)
        self.assertFalse(self.transport.events)
    def test_stale_grid_consumes_no_visit(self):
        self.ledger.start(5)
        with self.assertRaises(BridgeError):self.r.begin_profile('0'*64,120,200)
        self.assertEqual(self.ledger.status()['visited'],0)
    def test_non_grid_refused(self):
        self.ledger.start(5);self.transport.mode='chat';self.transport.render()
        with self.assertRaises(BridgeError):self.r.begin_profile(self.sha(),120,200)
    def test_boolean_and_outside_tile_coordinates_refused(self):
        self.ledger.start(5)
        for x,y in [(True,100),(900,100),(20,1268),(20,50)]:
            with self.subTest(x=x,y=y),self.assertRaises(BridgeError):self.r.begin_profile(self.sha(),x,y)
    def test_new_chat_check_requires_matching_invitation(self):
        self.ledger.start(1);self.authorize_online();self.r.begin_profile(self.sha(),120,200);self.r.open_profile_chat(profile_guard(self.transport.frame)['profile_sha256'])
        self.transport.mode='sent';self.transport.render()
        self.assertFalse(self.r.check_new_chat(self.sha())['eligible'])
        self.assertFalse(any(e[0]=='greeting' for e in self.transport.events))
    def test_existing_draft_skipped_without_overwrite(self):
        self.ledger.start(1);self.authorize_online();self.r.begin_profile(self.sha(),120,200);self.r.open_profile_chat(profile_guard(self.transport.frame)['profile_sha256'])
        self.transport.native='Existing draft';self.transport.render()
        self.assertFalse(self.r.check_new_chat(self.sha())['eligible'])
        self.assertEqual(self.transport.native,'Existing draft')
    def test_cannot_send_with_plus_button(self):
        self.ledger.start(5);self.draft()
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
        self.assertEqual(self.ledger.status()['send_attempts'],0)
    def test_generic_send_blocked(self):
        self.ledger.start(5);self.finish()
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),825,1515)
        self.assertEqual(self.ledger.status()['send_attempts'],0)
    def test_exact_text_required_before_send(self):
        self.ledger.start(5);self.finish();self.transport.native='Other text';self.transport.render()
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
        self.assertEqual(self.ledger.status()['send_attempts'],0)
    def test_changed_recipient_blocks_send(self):
        self.ledger.start(5);self.finish();self.transport.person=2;self.transport.render()
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
    def test_changed_button_blocks_send(self):
        self.ledger.start(5);self.finish()
        im=Image.open(BytesIO(self.transport.frame));im.putpixel((820,1515),(0,0,0));b=BytesIO();im.save(b,format='PNG');self.transport.frame=b.getvalue()
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
    def test_focused_editor_blocks_send(self):
        self.ledger.start(5);self.finish();self.transport.focused=True
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
    def test_send_one_shot_even_before_review(self):
        self.ledger.start(5);self.finish();self.r.send_prepared(self.sha())
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
        self.assertEqual(self.ledger.status()['send_attempts'],1)
    def test_no_claim_of_send_while_draft_still_visible(self):
        self.ledger.start(5);self.finish();self.r.send_prepared(self.sha());self.transport.mode='finished';self.transport.native='Привет';self.transport.render()
        with self.assertRaises(BridgeError):self.r.review_visit(self.sha(),'sent_observed')
        self.assertEqual(self.ledger.status()['sent_observed_by_agent'],0)
    def test_unknown_send_persists_stop(self):
        self.ledger.start(5);self.finish();self.transport.fail=True
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
        self.assertTrue(self.ledger.status()['manual_review_required'])
        with self.assertRaises(SessionError):self.ledger.start(5)
    def test_unknown_input_persists_stop(self):
        self.ledger.start(5);self.enter();self.r.navigate('tap',self.sha(),400,1515);self.transport.fail=True
        with self.assertRaises(BridgeError):self.r.prepare_greeting(input_context_sha256(self.transport.frame),0)
        self.assertTrue(self.ledger.status()['manual_review_required'])
    def test_wrong_finish_variant_refused(self):
        self.ledger.start(5);self.draft()
        with self.assertRaises(BridgeError):self.r.finish_greeting_input(input_context_sha256(self.transport.frame),1)
    def test_no_legacy_leave_shortcut(self):
        with self.assertRaises(BridgeError):self.r.leave_profile('0'*64)
    def test_skipped_return_counts_without_input(self):
        self.ledger.start(1);self.enter();self.r.review_visit(self.sha(),'skipped');self.r.return_to_grid(self.sha())
        self.assertEqual((self.ledger.status()['skipped'],self.ledger.status()['visited']),(1,1))
    def test_action_budget_refusal_before_send_reservation(self):
        self.ledger.start(5);self.finish();self.transport.reader.action_attempts=50
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
        self.assertEqual(self.ledger.status()['send_attempts'],0)
        self.assertFalse(self.ledger.status()['manual_review_required'])
    def test_session_safe_resume_after_connection_action_budget(self):
        self.ledger.start(5);self.finish();self.transport.reader.action_attempts=50
        with self.assertRaises(BridgeError):self.r.send_prepared(self.sha())
        self.transport.reader.action_attempts=0 # Represents a new transport, NOT a new test.
        self.r.send_prepared(self.sha())
        self.assertEqual(self.ledger.status()['visited'],1)
    def test_filter_navigation_only_permitted_static_controls(self):
        self.ledger.start(5);self.r.navigate('tap',self.sha(),815,1514)
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),400,500)
        self.transport.switch_fixture='offline';self.transport.render()
        self.r.navigate('tap',self.sha(),809,1013)
    def test_no_false_automatic_identity_claim(self):
        self.ledger.start(1);result=self.enter()
        self.assertFalse(result['identity_verified']);self.assertFalse(result['full_history_automatically_verified'])

    def test_profiles_blocked_without_online_filter_confirmation(self):
        self.ledger.start(5)
        with self.assertRaises(BridgeError):self.r.begin_profile(self.sha(),120,200)
        self.assertEqual(self.ledger.status()['visited'],0)
    def test_filter_cannot_confirm_offline_switch(self):
        self.ledger.start(5)
        self.r.navigate('tap',self.sha(),815,1514)
        im=Image.open(BytesIO(self.transport.frame));im.paste('white',(756,981,858,1044));b=BytesIO();im.save(b,format='PNG');self.transport.frame=b.getvalue()
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),808,1515)
        self.assertFalse(self.r.online_confirmed)
    def test_current_live_on_fixture_can_confirm_without_toggling(self):
        from filter_state import SWITCH_BOX, online_filter_state
        self.assertEqual(SWITCH_BOX,(756,981,858,1044))
        self.ledger.start(4)
        self.authorize_online()
        self.assertTrue(self.r.online_confirmed)
        self.assertEqual(self.transport.events,[('tap',815,1514),('tap',808,1515)])
        self.assertEqual(self.ledger.status()['visited'],0)
        self.assertEqual(self.ledger.status()['send_attempts'],0)

    def test_corrupted_core_pixel_refuses_confirm_before_injection(self):
        self.ledger.start(4)
        self.r.navigate('tap',self.sha(),815,1514)
        im=Image.open(BytesIO(self.transport.frame)).convert('RGB')
        im.putpixel((827,1012),(255,0,255))
        b=BytesIO();im.save(b,format='PNG');self.transport.frame=b.getvalue()
        before=list(self.transport.events)
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),808,1515)
        self.assertEqual(self.transport.events,before)
        self.assertFalse(self.r.online_confirmed)
        self.assertEqual(self.ledger.status()['visited'],0)

    def test_previous_on_crop_passes_structural_check(self):
        self.ledger.start(4)
        self.r.navigate('tap',self.sha(),815,1514)
        self.transport.switch_fixture='online_v140_rejected';self.transport.render()
        self.r.navigate('tap',self.sha(),808,1515)
        self.assertTrue(self.r.online_confirmed)

    def test_valid_off_cannot_confirm_until_toggled_and_reread(self):
        self.ledger.start(4)
        self.transport.switch_fixture='offline'
        self.r.navigate('tap',self.sha(),815,1514)
        before=list(self.transport.events)
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),808,1515)
        self.assertEqual(self.transport.events,before)
        self.r.navigate('tap',self.sha(),809,1013)
        self.assertFalse(self.r.online_confirmed)
        self.r.navigate('tap',self.sha(),808,1515)
        self.assertTrue(self.r.online_confirmed)
        self.assertEqual(self.ledger.status()['visited'],0)

    def test_on_switch_cannot_be_disabled_through_agent(self):
        self.ledger.start(4)
        self.r.navigate('tap',self.sha(),815,1514)
        before=list(self.transport.events)
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),809,1013)
        self.assertEqual(self.transport.events,before)

    def test_unknown_switch_cannot_toggle_or_confirm(self):
        self.ledger.start(4);self.r.navigate('tap',self.sha(),815,1514)
        im=Image.open(BytesIO(self.transport.frame));im.paste('white',(756,981,858,1044))
        b=BytesIO();im.save(b,format='PNG');self.transport.frame=b.getvalue()
        before=list(self.transport.events)
        for x,y in [(809,1013),(808,1515)]:
            with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha(),x,y)
        self.assertEqual(self.transport.events,before)
        self.assertEqual(self.ledger.status()['visited'],0)

    def test_reopening_settings_invalidates_previous_filter_check(self):
        self.ledger.start(5);self.authorize_online();self.assertTrue(self.r.online_confirmed)
        self.r.navigate('tap',self.sha(),815,1514)
        self.assertFalse(self.r.online_confirmed)

    def test_all_ten_variants_can_be_selected_without_expanding_visit_target(self):
        for variant in range(10):
            with self.subTest(variant=variant):
                self.ledger.start(1)
                self.r.online_confirmed=False
                if self.transport.reader.action_attempts>35:self.transport.reader.action_attempts=0
                self.assertTrue(self.enter(variant+1)['eligible'])
                self.r.navigate('tap',self.sha(),400,1515)
                self.r.prepare_greeting(input_context_sha256(self.transport.frame),variant)
                self.assertEqual(self.transport.native,GREETINGS[variant])
                self.r.finish_greeting_input(input_context_sha256(self.transport.frame),variant)
                self.r.send_prepared(self.sha());self.r.review_visit(self.sha(),'sent_observed');self.r.return_to_grid(self.sha())
                self.assertEqual(self.ledger.status()['visited'],1)
    def test_unknown_screen_after_back_gets_no_second_blind_back(self):
        self.ledger.start(1);self.enter();self.r.review_visit(self.sha(),'skipped')
        original=self.transport.instrument
        def unexpected(op,*args):
            result=original(op,*args)
            if op=='back':
                self.transport.mode='sent';self.transport.render()
            return result
        self.transport.reader._instrument=unexpected
        before=len(self.transport.events)
        with self.assertRaises(BridgeError):self.r.return_to_grid(self.sha())
        self.assertEqual(len(self.transport.events)-before,1)
        self.assertTrue(self.ledger.status()['manual_review_required'])

if __name__=='__main__':unittest.main()
