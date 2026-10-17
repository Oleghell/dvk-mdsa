"""Resolution-independent target API: no arbitrary XY or implicit sends."""
import base64,json,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from semantic_profile import SemanticProfile,TOOLS,valid_call
from mumu_bridge import BridgeError
from control_protocol import args_allowed,COMPONENT,SERIAL

SHA='a'*64
ID='b'*32

def report(**kw):
    return dict(width=900,height=1600,bounds=[302,1496,344,1538],target='profile_chat',context_sha256=SHA,method='visual_profile_panel',identity_verified=False,**kw)
def output(d):
    return 'INSTRUMENTATION_RESULT: report_b64='+base64.b64encode(json.dumps(d).encode()).decode()+'\n'

class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.ledger=Mock()
        self.supervised=SimpleNamespace(inner=Mock(),ledger=self.ledger,_run_ready=Mock())
        self.subject=SemanticProfile(self.supervised)
    def test_no_caller_coordinates_or_text(self):
        self.assertTrue(valid_call('mumu_find_profile_chat',{}))
        self.assertFalse(valid_call('mumu_find_profile_chat',{'x':321}))
        self.assertTrue(valid_call('mumu_click_profile_chat',{'action_id':ID,'expected_target_sha256':SHA}))
        for extra in ('x','y','mask','text','reset'):
            self.assertFalse(valid_call('mumu_click_profile_chat',{'action_id':ID,'expected_target_sha256':SHA,extra:1}))
        self.assertEqual(len(TOOLS),2)
    def test_parser_supports_actual_portrait_dimensions(self):
        for w,h in ((450,800),(720,1280),(900,1600),(1080,1920),(1080,2400),(1440,2560)):
            d=report();d.update(width=w,height=h,bounds=[w//3,h*9//10,w//2,h*19//20])
            self.assertEqual(self.subject.report(output(d))['width'],w)
    def test_malformed_and_false_identity_reports_rejected(self):
        for k,v in (('width',True),('width',2500),('height',500),('bounds',[0,0,20,20]),('bounds',[0,1500,1000,1600]),('context_sha256','bad'),('identity_verified',True),('method','tap')):
            d=report();d[k]=v
            with self.assertRaises(BridgeError):self.subject.report(output(d))
        with self.assertRaises(BridgeError):self.subject.report(output(report())*2)
    def test_requires_existing_counted_visit(self):
        self.ledger._visit.side_effect=BridgeError('No active visit')
        self.subject.control.ready=Mock();self.subject.control.instrument=Mock()
        with self.assertRaises(BridgeError):self.subject.click({'action_id':ID,'expected_target_sha256':SHA})
        self.subject.control.instrument.assert_not_called()
    def test_no_reopen_after_chat_verified(self):
        self.ledger._visit.return_value={'fingerprint':'verified','id':3,'state':'opening'}
        self.subject.control.ready=Mock();self.subject.control.instrument=Mock()
        with self.assertRaises(BridgeError):self.subject.click({'action_id':ID,'expected_target_sha256':SHA})
        self.subject.control.instrument.assert_not_called()
    def test_transport_only_named_operations_with_optin(self):
        for req in ({'op':'find_profile_chat'},{'op':'click_profile_chat','expected_target_sha256':SHA}):
            a=['-s',SERIAL,'shell','am','instrument','-w','-r','-e','request_b64',base64.b64encode(json.dumps(req).encode()).decode(),COMPONENT]
            self.assertTrue(args_allowed(a,True));self.assertFalse(args_allowed(a,False))

class LocatorRasterTests(unittest.TestCase):
    def test_pure_java_matrix_and_negative_controls(self):
        import shutil,subprocess,tempfile
        from pathlib import Path
        from PIL import Image,ImageDraw
        if not shutil.which('javac') or not shutil.which('java'):self.skipTest('JDK needed')
        root=Path(__file__).resolve().parents[1]
        shapes=json.loads((root/'tests/semantic-icon-fixtures.json').read_text(encoding='utf-8'))
        base=Image.new('RGB',(900,1600),(40,43,47))
        for name,cx,color in [('close',76,(0,190,200)),('chat',322,(0,190,235)),('gift',578,(255,0,140))]:
            d=ImageDraw.Draw(base)
            for y,row in enumerate(shapes[name]):
                for x in range(16):
                    if row&(1<<x):d.rectangle((cx-24+x*3,1490+y*3,cx-22+x*3,1492+y*3),fill=color)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);cases=[]
            for w,h in ((450,800),(720,1280),(900,1600),(1080,1920),(1080,2400),(1440,2560)):
                name=p/f'size-{w}-{h}.png';base.resize((w,h),Image.Resampling.BILINEAR).save(name);cases.append((name,True))
            for label,box in [('no-chat',(290,1480,360,1550)),('no-close',(40,1480,110,1550)),('no-gift',(540,1480,620,1550))]:
                im=base.copy();ImageDraw.Draw(im).rectangle(box,fill=(40,43,47));name=p/(label+'.png');im.save(name);cases.append((name,False))
            # Two valid panels must be rejected, not arbitrarily disambiguated.
            im=base.copy();im.paste(base.crop((0,1480,900,1550)),(0,1250));name=p/'duplicate.png';im.save(name);cases.append((name,False))
            name=p/'blank.png';Image.new('RGB',(900,1600),'white').save(name);cases.append((name,False))
            source=p/'Probe.java';source.write_text('''import com.dvk.control.ProfileChatLocator;import javax.imageio.ImageIO;import java.io.File;import java.awt.image.BufferedImage;
public class Probe {public static void main(String[] args)throws Exception{for(String path:args){BufferedImage im=ImageIO.read(new File(path));int w=im.getWidth(),h=im.getHeight();ProfileChatLocator.Box b=ProfileChatLocator.locate(im.getRGB(0,0,w,h,null,0,w),w,h);System.out.println(b==null?"no":"yes");}}}''',encoding='utf-8')
            c=subprocess.run(['javac','-d',str(p),str(root/'control-android-v2/src/com/dvk/control/ProfileChatLocator.java'),str(source)],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            result=subprocess.run(['java','-cp',str(p),'Probe',*[str(n) for n,_ in cases]],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.splitlines(),['yes' if yes else 'no' for _,yes in cases])

class SemanticJournalTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from test_session import TestSession
        from mumu_bridge import AdbReader
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'adb.exe').touch()
        self.reader=AdbReader(self.root/'adb.exe');self.reader.control_enabled=True
        self.ledger=TestSession(self.root/'run.sqlite');self.ledger.start(5);self.ledger.begin_visit()
        supervised=SimpleNamespace(inner=self.reader,ledger=self.ledger,_run_ready=lambda:None)
        self.subject=SemanticProfile(supervised);self.calls=[];self.state='input_injected'
        def instrument(req):
            self.calls.append(req)
            self.assertEqual(self.ledger.db.execute('SELECT state FROM control_actions WHERE id=?',(req.get('action_id',ID),)).fetchone()[0],'reserved')
            if self.state=='timeout':raise BridgeError('timeout')
            return self.state,output(report())
        self.subject.control.instrument=instrument
    def tearDown(self):self.ledger.close();self.tmp.cleanup()
    def click(self,ident=ID,sha=SHA):
        return self.subject.click({'action_id':ident,'expected_target_sha256':sha})
    def test_success_reserves_before_injection_no_send_and_no_retry(self):
        result=self.click();self.assertFalse(result['message_sent']);self.assertFalse(result['result_screen_verified'])
        self.assertEqual(self.calls,[{'op':'click_profile_chat','expected_target_sha256':SHA}])
        self.assertEqual(self.ledger.status()['visited'],1)
        for ident in (ID,'c'*32):
            with self.assertRaises(BridgeError):self.click(ident)
        self.assertEqual(len(self.calls),1)
    def test_known_refusal_records_once_without_global_hold(self):
        self.state='denied_screen_changed'
        with self.assertRaises(BridgeError):self.click()
        self.assertFalse(self.reader.action_uncertain);self.assertFalse(self.ledger.status()['manual_review_required'])
        self.assertEqual(self.ledger.db.execute('SELECT state FROM control_actions').fetchone()[0],'refused')
        with self.assertRaises(BridgeError):self.click('c'*32,'d'*64)
        self.assertEqual(len(self.calls),1)
    def test_unknown_outcome_stops_persistently(self):
        from test_session import TestSession
        self.state='timeout'
        with self.assertRaises(BridgeError):self.click()
        self.assertTrue(self.reader.action_uncertain);self.assertEqual(self.ledger.status()['state'],'stopped')
        self.ledger.close();self.ledger=TestSession(self.root/'run.sqlite')
        self.assertTrue(self.ledger.status()['manual_review_required'])
    def test_skipped_visit_cannot_reopen(self):
        self.ledger.skip()
        with self.assertRaises(Exception):self.click()
        self.assertEqual(self.calls,[])
    def test_shared_action_budget_is_not_reset(self):
        self.reader.action_attempts=50
        with self.assertRaises(BridgeError):self.click()
        self.assertEqual(self.calls,[])
