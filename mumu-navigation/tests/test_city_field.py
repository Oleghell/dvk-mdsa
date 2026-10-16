"""Fixed control crops only: no full private screens, profiles or messages."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from city_field import CITY_ANCHORS, CITY_EDITOR_BOUNDS, check_city_field
from mumu_bridge import BridgeError, content_pixel_sha256
from session_bridge import SupervisedReader
from test_session import TestSession
from test_session_bridge import SyntheticTransport

FIXTURES=json.loads((Path(__file__).parent/'city-control-fixtures.json').read_text())

def frame():
    im=Image.new('RGB',(900,1600),(24,28,33))
    for a in FIXTURES.values():
        im.paste(Image.open(BytesIO(base64.b64decode(a['png']))),tuple(a['box'][:2]))
    b=BytesIO();im.save(b,'PNG');return b.getvalue()

def layout(png,focused=False):
    return {'truncated':False,'content_sha256':content_pixel_sha256(png),
            'nodes':[{'editable':True,'enabled':True,'class':'android.widget.EditText',
                      'bounds':list(CITY_EDITOR_BOUNDS),'focused':focused,'text':'Нальчик'}]}

class CityFieldTests(unittest.TestCase):
    def setUp(self):self.png=frame();self.tree=layout(self.png);self.sha=content_pixel_sha256(self.png)
    def check(self):return check_city_field(self.png,self.tree,self.sha)
    def test_native_query_and_focus_without_result_claims(self):
        d=self.check();self.assertTrue(d['city_picker_verified']);self.assertEqual(d['query'],'Нальчик')
        for key in ('city_input_supported','city_selection_supported','result_rows_available','applied_city_verified'):
            self.assertIs(d[key],False)
    def test_static_crops_match_compiled_constants(self):
        self.assertEqual(tuple((tuple(v['box']),v['sha256']) for v in FIXTURES.values()),CITY_ANCHORS)
        self.assertTrue(self.check()['city_picker_verified'])
    def test_empty_query_supported(self):
        self.tree['nodes'][0]['text']='';self.assertEqual(self.check()['query'],'')
    def test_wrong_anchor_rejected(self):
        im=Image.open(BytesIO(self.png)).convert('RGB');im.putpixel((340,130),(255,0,0))
        b=BytesIO();im.save(b,'PNG');self.png=b.getvalue();self.tree=layout(self.png);self.sha=content_pixel_sha256(self.png)
        self.assertFalse(self.check()['city_picker_verified'])
    def test_stale_tree_rejected(self):
        self.tree['content_sha256']='a'*64;self.assertFalse(self.check()['city_picker_verified'])
    def test_untrusted_supplied_hash_recomputed(self):
        self.sha='a'*64;self.tree['content_sha256']=self.sha;self.assertFalse(self.check()['city_picker_verified'])
    def test_truncation_unknown_flags_rejected(self):
        for flag in (True,None,0,'false'):
            with self.subTest(flag=flag):
                self.tree['truncated']=flag;self.assertFalse(self.check()['city_picker_verified'])
    def test_extra_or_missing_editor_rejected(self):
        for nodes in ([],self.tree['nodes']*2):
            self.tree['nodes']=nodes;self.assertFalse(self.check()['city_picker_verified'])
    def test_message_field_bounds_rejected(self):
        self.tree['nodes'][0]['bounds']=[152,1488,748,1544];self.assertFalse(self.check()['city_picker_verified'])
    def test_malformed_editor_rejected(self):
        original=deepcopy(self.tree)
        for key,value in [('bounds',None),('bounds',[True,196,786,276]),('bounds',[118,196,786]),
                          ('bounds',[119,196,786,276]),('enabled',False),('enabled',1),
                          ('editable',1),('class','android.widget.TextView'),('focused',1),
                          ('password',True),('text',None),('text','x'*129)]:
            with self.subTest(key=key,value=value):
                self.tree=deepcopy(original);self.tree['nodes'][0][key]=value
                self.assertFalse(self.check()['city_picker_verified'])
    def test_unsupported_nodes_never_raise(self):
        for nodes in (None,'bad',[None],[{}]*201):
            self.tree['nodes']=nodes;self.assertFalse(self.check()['city_picker_verified'])
    def test_unsupported_frame_never_recognized(self):
        for data in (b'',b'PNG'):
            self.assertFalse(check_city_field(data,self.tree,self.sha)['city_picker_verified'])
        im=Image.new('RGB',(547,992));b=BytesIO();im.save(b,'PNG')
        self.assertFalse(check_city_field(b.getvalue(),self.tree,self.sha)['city_picker_verified'])

class CityFacadeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)
        self.t=SyntheticTransport(p);self.t.frame=frame();self.tree=layout(self.t.frame)
        self.t.reader.inspect_layout=lambda:deepcopy(self.tree)
        self.ledger=TestSession(p/'session.sqlite');self.r=SupervisedReader(self.t.reader,self.ledger)
        self.sha=content_pixel_sha256(self.t.frame)
        def instrument(op,sha='0'*64,x=0,y=0):
            self.t.events.append((op,x,y));self.tree['nodes'][0]['focused']=True
            return ('input_injected','')
        self.t.reader._instrument=instrument
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def test_read_diagnostic_without_active_run_does_not_mutate(self):
        before=self.ledger.status()
        self.assertTrue(self.r.check_city_search(self.sha)['city_picker_verified'])
        self.assertEqual(self.ledger.status(),before);self.assertEqual(self.t.events,[])
    def test_focus_requires_local_start(self):
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        self.assertEqual(self.t.events,[])
    def test_one_fixed_focus_no_visit_input_or_send_reservation(self):
        self.ledger.start(5);before=self.ledger.status()
        d=self.r.focus_city_search(self.sha)
        self.assertTrue(d['input_injected']);self.assertFalse(d['text_entered']);self.assertFalse(d['city_selected'])
        self.assertEqual(self.t.events,[('tap',400,236)]);self.assertEqual(self.ledger.status(),before)
        self.assertEqual(self.t.reader.action_attempts,1)
    def test_already_focused_no_action(self):
        self.ledger.start(5);self.tree['nodes'][0]['focused']=True
        self.assertTrue(self.r.focus_city_search(self.sha)['already_focused'])
        self.assertEqual(self.t.events,[]);self.assertEqual(self.t.reader.action_attempts,0)
    def test_active_visit_refuses(self):
        self.ledger.start(5);self.ledger.begin_visit()
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        self.assertEqual(self.t.events,[])
    def test_stale_screen_refuses_before_tap(self):
        self.ledger.start(5)
        with self.assertRaises(BridgeError):self.r.focus_city_search('a'*64)
        self.assertEqual(self.t.events,[])
    def test_stale_tree_or_wrong_field_refuses_before_tap(self):
        self.ledger.start(5)
        for key,value in [('content_sha256','b'*64),('nodes',[])]:
            old=self.tree[key];self.tree[key]=value
            with self.subTest(key=key),self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
            self.tree[key]=old
        self.assertEqual(self.t.events,[])
    def test_changed_screen_after_tree_read_refuses(self):
        self.ledger.start(5)
        def changed():
            d=deepcopy(self.tree)
            im=Image.open(BytesIO(self.t.frame)).convert('RGB');im.putpixel((400,500),(255,0,0))
            b=BytesIO();im.save(b,'PNG');self.t.frame=b.getvalue();return d
        self.t.reader.inspect_layout=changed
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        self.assertEqual(self.t.events,[])
    def test_action_cap_and_uncertainty_prevent_focus(self):
        self.ledger.start(5);self.t.reader.action_attempts=50
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        self.t.reader.action_attempts=0;self.t.reader.action_uncertain=True
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        self.assertEqual(self.t.events,[])
    def test_unknown_focus_stops_run_persistently_without_new_visit(self):
        self.ledger.start(5)
        def fail(*args):raise BridgeError('Synthetic timeout after dispatch')
        self.t.reader._instrument=fail
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        state=self.ledger.status()
        self.assertEqual(state['state'],'stopped');self.assertTrue(state['manual_review_required'])
        self.assertEqual(state['visited'],0);self.assertEqual(state['input_attempts'],0)
        self.assertEqual(state['send_attempts'],0);self.assertEqual(self.t.reader.action_attempts,1)
        self.ledger.close();self.ledger=TestSession(Path(self.tmp.name)/'session.sqlite')
        self.r=SupervisedReader(self.t.reader,self.ledger)
        self.assertTrue(self.ledger.status()['manual_review_required'])
        with self.assertRaises(BridgeError):self.r.focus_city_search(self.sha)
        self.assertEqual(self.t.reader.action_attempts,1)

    def test_generic_navigation_cannot_select_city_result(self):
        self.ledger.start(5)
        with self.assertRaises(BridgeError):self.r.navigate('tap',self.sha,400,330)
        self.assertEqual(self.t.events,[])

if __name__=='__main__':unittest.main()
