"""New runtime: native-first, no screenshots on success, no mutating retries."""
import base64,csv,hashlib,json,logging
from io import BytesIO,StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from PIL import Image
from ui_model import *
from ui_runtime import AndroidUI,Element
from ui_protocol import valid_native,valid_tool,tools
from ui_ocr import TesseractFallback,parse_tsv,frame_hash

SHA='a'*64

def node(index=0,parent=-1,**kwargs):
    n=dict(index=index,parent=parent,package='drug.vokrug',bounds=[10,20,180,80],resource_id='',description='',text='',class_name='android.widget.TextView',visible=True,password=False)
    n.update({k:False for k in BOOL_KEYS});n['enabled']=True;n.update(kwargs);return n

def tree(nodes=None,width=900,height=1600,**kwargs):
    d=dict(nodes=nodes or [node()],package='drug.vokrug',width=width,height=height,rotation=0,density_dpi=240,truncated=False,tree_sha256=SHA)
    d.update(kwargs);return Tree.parse(d)

class SelectorTests(unittest.TestCase):
    def test_attributes_and_conjunction(self):
        t=tree([node(text='Написать',resource_id='drug.vokrug:id/observed',clickable=True)])
        for q in ({'resource_id':'drug.vokrug:id/observed'},{'text':'Написать','clickable':True},{'text_contains':'писа'},{'class_name':'android.widget.TextView','enabled':True}):self.assertEqual(t.find(q)['index'],0)
        with self.assertRaises(ElementNotFound):t.find({'resource_id':'drug.vokrug:id/observed','text':'Other'})
    def test_no_silent_first_of_duplicates(self):
        t=tree([node(text='Написать'),node(1,text='Написать')])
        with self.assertRaises(AmbiguousElement):t.find({'text':'Написать'})
    def test_parent_ancestor_and_child(self):
        t=tree([node(class_name='android.widget.Button',clickable=True),node(1,0,text='Написать')])
        self.assertEqual(t.find({'text':'Написать','parent':{'clickable':True}})['index'],1)
        self.assertEqual(t.find({'text':'Написать','ancestor':{'clickable':True}})['index'],1)
        self.assertEqual(t.find({'clickable':True,'child':{'text':'Написать'}})['index'],0)
    def test_strict_shapes_no_xpath_eval_or_coordinates(self):
        for q in ({},{'x':1},{'xpath':'//*'},{'clickable':True},{'text':''},{'text':True},{'enabled':1,'text':'x'},{'class_name':'x\n'}):
            with self.assertRaises(UIError):selector(q)
    def test_password_and_incomplete_trees(self):
        with self.assertRaises(IncompleteHierarchy):tree(truncated=True)
        with self.assertRaises(UIError):tree([node(password=True,text='SECRET')])
        t=tree([node(password=True,text='')])
        with self.assertRaises(ElementNotFound):t.find({'class_name':'android.widget.TextView'})
    def test_invalid_foreign_structure_and_bounds(self):
        for changes in ({'package':'other'},{'tree_sha256':'bad'},{'width':True},{'width':5000}):
            with self.assertRaises(UIError):tree(**changes)
        with self.assertRaises(UIError):tree([node(parent=0)])
        t=tree([node(text='x',bounds=[-1,0,50,50])])
        with self.assertRaises(UnsupportedUI):t.find({'text':'x'})
    def test_native_geometry_not_portrait_or_dpi_locked(self):
        for w,h,rotation,dpi in ((450,800,0,160),(1080,2400,0,480),(1600,900,1,240),(2560,1440,3,640)):
            t=tree([node(text='x')],width=w,height=h,rotation=rotation,density_dpi=dpi)
            self.assertEqual(t.find({'text':'x'})['text'],'x')
    def test_generic_editor_is_not_empty_chat(self):
        t=tree([node(class_name='android.widget.EditText',editable=True)])
        d=detect_screen(t);self.assertEqual(d['state'],'message_editor');self.assertFalse(d['empty_chat_verified'])
    def test_state_ambiguous_is_explicit(self):
        t=tree([node(text='Поиск города'),node(1,class_name='android.widget.EditText',editable=True),node(2,text='Только онлайн',checkable=True)])
        self.assertEqual(detect_screen(t)['state'],'ambiguous')

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.backend=Mock();self.backend.snapshot.return_value=tree([node(text='Написать',clickable=True)])
        self.ocr=Mock();self.cv=Mock();self.clock=[0]
        def pause(s):self.clock[0]+=s
        self.ui=AndroidUI(self.backend,ocr=self.ocr,vision=self.cv,clock=lambda:self.clock[0],pause=pause)
    def test_native_lookup_never_captures_or_ocr(self):
        e=self.ui.find_element(text='Написать');self.assertEqual(e.method,'hierarchy');self.ocr.find.assert_not_called();self.cv.find.assert_not_called()
    def test_ordered_strategy_prefers_resource_id(self):
        self.backend.snapshot.return_value=tree([node(resource_id='id',text='x'),node(1,description='desc')])
        e=self.ui.find_element(alternatives=[{'description':'desc'},{'resource_id':'id'}]);self.assertEqual(e.node['index'],0)
    def test_wait_is_bounded_condition_poll_not_blind_sleep(self):
        self.backend.snapshot.side_effect=[tree(),tree(),tree([node(text='target')])]
        e=self.ui.wait_for_element(text='target',timeout=1);self.assertEqual(e.node['text'],'target');self.assertLess(self.clock[0],1)
    def test_fallback_only_after_deadline(self):
        self.ocr.find.return_value='found';self.assertEqual(self.ui.wait_for_element(text='missing',timeout=.3,allow_fallback=True),'found')
        self.assertAlmostEqual(self.clock[0],.3);self.ocr.find.assert_called_once();self.cv.find.assert_not_called()
    def test_no_ocr_on_ambiguity_or_incomplete(self):
        self.backend.snapshot.return_value=tree([node(text='x'),node(1,text='x')])
        with self.assertRaises(AmbiguousElement):self.ui.find_element(text='x',allow_fallback=True)
        self.ocr.find.assert_not_called()
        self.backend.snapshot.side_effect=IncompleteHierarchy('truncated')
        with self.assertRaises(IncompleteHierarchy):self.ui.find_element(text='missing',allow_fallback=True)
        self.ocr.find.assert_not_called()
    def test_missing_ocr_does_not_prevent_last_cv_fallback(self):
        self.ocr.find.side_effect=UnsupportedUI('not installed');self.cv.find.return_value='vision'
        self.assertEqual(self.ui.find_element(text='missing',allow_fallback=True),'vision')
    def test_no_action_without_policy(self):
        e=self.ui.find_element(text='Написать')
        with self.assertRaises(UnsupportedUI):e.click(action_id='b'*32,purpose='open_chat')
        self.backend.perform.assert_not_called()
    def test_no_action_retry_or_fallback_after_failure(self):
        policy=Mock(side_effect=UIError('unknown'));self.ui.mutation=policy;e=self.ui.find_element(text='Написать')
        with self.assertRaises(UIError):e.click(action_id='b'*32,purpose='open_chat')
        policy.assert_called_once();self.ocr.find.assert_not_called()
    def test_text_requires_real_editable_node(self):
        e=self.ui.find_element(text='Написать')
        with self.assertRaises(UnsupportedUI):e.set_text('hello',action_id='b'*32,purpose='input_city')
    def test_logs_never_include_selector_or_text(self):
        self.backend.snapshot.return_value=tree([node(text='PRIVATE RECIPIENT')])
        with self.assertLogs('dvk.ui',level='INFO') as logs:self.ui.find_element(text='PRIVATE RECIPIENT')
        self.assertNotIn('PRIVATE',str(logs.output));self.assertIn('[UI]',str(logs.output))
    def test_unknown_screen_times_out_without_action(self):
        with self.assertRaises(ElementNotFound):self.ui.wait_for_screen('profile',timeout=.3)
        self.backend.perform.assert_not_called()

TSV='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
def word(text='Написать',conf='96',line=1,x=10):return f'5\t1\t1\t1\t{line}\t1\t{x}\t20\t100\t30\t{conf}\t{text}\n'

class OcrTests(unittest.TestCase):
    def test_tsv_exact_phrase_bounds(self):
        rows=parse_tsv(TSV+word(),900,1600);self.assertEqual(rows[0]['bounds'],[10,20,110,50])
    def test_uncertain_words_not_dropped_to_forge_phrase(self):
        self.assertEqual(parse_tsv(TSV+word()+word('???','10',x=120),900,1600),[])
    def test_invalid_confidence_and_bounds(self):
        for row in (word(conf='NaN'),word(conf='101'),word(x=850)):
            with self.assertRaises(UIError):parse_tsv(TSV+row,900,1600)
    def test_lazy_capture_and_no_native_property_guess(self):
        capture=Mock();runner=Mock();ocr=TesseractFallback(capture,'tesseract',runner)
        with self.assertRaises(ElementNotFound):ocr.find(None,{'editable':True},tree())
        capture.assert_not_called();runner.assert_not_called()
    def test_ocr_unique_match_and_no_shell(self):
        im=Image.new('RGB',(900,1600),'white');b=BytesIO();im.save(b,format='PNG')
        runner=Mock(return_value=SimpleNamespace(returncode=0,stdout=(TSV+word()).encode()))
        ocr=TesseractFallback(lambda:b.getvalue(),'tesseract',runner)
        e=ocr.find(None,{'text':'Написать'},tree());self.assertEqual(e.method,'ocr');self.assertEqual(e.frame['sha256'],frame_hash(im))
        self.assertNotIn('shell',runner.call_args.kwargs)
        runner.return_value.stdout=(TSV+word()+word(line=2)).encode()
        with self.assertRaises(AmbiguousElement):ocr.find(None,{'text':'Написать'},tree())
    def test_no_ocr_text_editing(self):
        e=Element(None,{'text':'x'},{'bounds':[0,0,10,10]},SHA,'ocr',{})
        with self.assertRaises(UnsupportedUI):e.set_text('draft',action_id='b'*32,purpose='input_city')

class ModernProtocolTests(unittest.TestCase):
    def test_named_operations_only_and_no_secret_shell(self):
        self.assertTrue(valid_native({'op':'ui_dump'}))
        base={'op':'ui_click','selector':{'text':'x'},'expected_tree_sha256':SHA,'allow_coordinate_fallback':False}
        self.assertTrue(valid_native(base))
        for extra in ('x','y','shell','mask','script'):self.assertFalse(valid_native(dict(base,**{extra:1})))
        self.assertFalse(valid_native(dict(base,selector={'xpath':'//*'})))
    def test_text_native_no_enter_password_or_unbounded_payload(self):
        base=dict(op='ui_set_text',selector={'editable':True},expected_tree_sha256=SHA,expected_text='',text='Нальчик 🙂')
        self.assertTrue(valid_native(base))
        for text in ('a\nb','\ud800','x'*129):self.assertFalse(valid_native(dict(base,text=text)))
    def test_tool_scope_no_send_generic_tap_or_auto_loop(self):
        a=dict(action='open_chat',action_id='b'*32,target='',city_index=-1,allow_fallback=True)
        self.assertTrue(valid_tool('mumu_ui_action',a))
        for action in ('send','purchase','tap','restart','like'):self.assertFalse(valid_tool('mumu_ui_action',dict(a,action=action)))
        self.assertEqual(len(tools()),4)
    def test_native_transport_respects_local_optin(self):
        from control_protocol import args_allowed,COMPONENT,SERIAL
        req={'op':'ui_dump'};payload=base64.b64encode(json.dumps(req).encode()).decode()
        a=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',payload,COMPONENT]
        self.assertTrue(args_allowed(a,True));self.assertFalse(args_allowed(a,False))

class FirstResultTests(unittest.TestCase):
    def test_first_result_below_native_input_without_fixed_xy(self):
        t=tree([node(text='Нальчик',editable=True,bounds=[20,100,400,160]),node(1,text='Нальчик',bounds=[20,250,400,300]),node(2,text='Нальчик',bounds=[20,180,400,230])])
        q={'text':'Нальчик','editable':False,'below':{'editable':True},'first':True}
        self.assertEqual(t.find(q)['index'],2)
    def test_first_is_optin_not_default(self):
        t=tree([node(text='x'),node(1,text='x')])
        with self.assertRaises(AmbiguousElement):t.find({'text':'x'})
        for q in ({'first':True},{'text':'x','first':False}):
            with self.assertRaises(UIError):selector(q)
    def test_ambiguous_anchor_does_not_choose(self):
        t=tree([node(editable=True),node(1,editable=True),node(2,text='x')])
        with self.assertRaises(AmbiguousElement):t.find({'text':'x','below':{'editable':True},'first':True})
