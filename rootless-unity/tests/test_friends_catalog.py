import hashlib,json,struct,sys,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import friends_catalog as c

def metadata_fixture():
    defs=[('DV.dll','DV.Models','User',[('get_Statistics',0,False),('get_ActualFriendAmount',0,False),('set_Example',1,False)]),
          ('DV.Profile.dll','DV.Profiles','ProfileViewController',[('get_Header',0,False),('get_Details',0,False)]),
          ('DV.Friends.dll','DV.Friends','FriendsHeader',[('get_Amount',0,False),('Refresh',1,False)]),
          ('Other.dll','Other','Example',[('get_Friends',0,False)])]
    strings=bytearray(b'\0');indexes={}
    def si(text):
        if text not in indexes:indexes[text]=len(strings);strings.extend(text.encode()+b'\0')
        return indexes[text]
    methods=[];types=[];images=[];fields=[]
    for ti,(image,ns,name,entries) in enumerate(defs):
        si(image);si(ns);si(name);first=len(methods)
        for mn,arity,static in entries:methods.append(struct.pack('<IiiiiiI4H',si(mn),ti,0,0,0,-1,0x06000001,16 if static else 0,0,0,arity))
        fields.append(struct.pack('<IiI',si('_RealFriendTotal' if name=='User' else '_amount'),0,0x04000001))
        t=[0]*26;t[0]=si(name);t[1]=si(ns);t[8]=ti;t[18]=1;t[9]=first;t[16]=len(entries);types.append(struct.pack('<II14i8HII',*t))
        images.append(struct.pack('<IiiIiIiIiI',si(image),0,ti,1,-1,0,-1,1,0,0))
    h=[0]*64;h[:2]=[0xFAB11BAF,31];h[6:8]=[256,len(strings)]
    off=256+len(strings);h[24:26]=[off,len(fields)*12];off+=len(fields)*12;h[12:14]=[off,len(methods)*36];off+=len(methods)*36
    h[40:42]=[off,len(types)*88];off+=len(types)*88;h[42:44]=[off,len(images)*40]
    return struct.pack('<64I',*h)+strings+b''.join(fields)+b''.join(methods)+b''.join(types)+b''.join(images)+b'PRIVATE-CHAT-TOKEN-DO-NOT-EXPORT'

def bundle(folder,data=None,both=False):
    expected={}
    for filename in ('base.apk','split-001.apk'):
        with zipfile.ZipFile(folder/filename,'w') as z:
            if filename=='base.apk' or both:z.writestr('assets/bin/Data/Managed/Metadata/global-metadata.dat',metadata_fixture() if data is None else data)
            z.writestr('private-chat.txt','PRIVATE-CHAT-TOKEN-DO-NOT-EXPORT')
        expected[filename]=hashlib.sha256((folder/filename).read_bytes()).hexdigest()
    return expected

class FriendsCatalog(unittest.TestCase):
    def test_real_metadata_reader_finds_actual_not_guessed_names(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);hashes=bundle(folder)
            result=c.inspect_bundle(folder,expected_hashes=hashes)
        self.assertEqual(result['status'],'catalog-ready')
        cat=result['catalog'];self.assertEqual(cat['user_getters']['total'],2)
        names=[d['method'] for d in cat['friend_methods']['definitions']]
        self.assertIn('get_ActualFriendAmount',names);self.assertIn('get_Amount',names)
        self.assertNotIn('get_Friends',names)
        self.assertIn('_RealFriendTotal',[d['field'] for d in cat['friend_fields']['definitions']])
        self.assertNotIn('PRIVATE-CHAT',json.dumps(result));self.assertFalse(result['ui_actions_attempted']);self.assertFalse(result['method_values_read'])
    def test_untrusted_hash_or_unsupported_version_is_closed(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);hashes=bundle(folder)
            wrong={**hashes,'base.apk':'0'*64}
            self.assertEqual(c.inspect_bundle(folder,expected_hashes=wrong)['reason'],'apk-hash-mismatch')
            invalid=bytearray(metadata_fixture());struct.pack_into('<I',invalid,4,29)
            hashes=bundle(folder,bytes(invalid))
            self.assertEqual(c.inspect_bundle(folder,expected_hashes=hashes)['reason'],'metadata-unsupported-or-invalid')
    def test_ambiguity_missing_size_and_cancellation(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);hashes=bundle(folder,both=True)
            self.assertEqual(c.inspect_bundle(folder,expected_hashes=hashes)['reason'],'metadata-ambiguous')
            self.assertEqual(c.inspect_bundle(folder,lambda:True,hashes)['reason'],'cancelled')
            for filename in hashes:
                with zipfile.ZipFile(folder/filename,'w') as z:z.writestr('no-metadata.txt','none')
            hashes={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in hashes}
            self.assertEqual(c.inspect_bundle(folder,expected_hashes=hashes)['reason'],'metadata-missing')
            hashes=bundle(folder,b'0'*255)
            self.assertEqual(c.inspect_bundle(folder,expected_hashes=hashes)['reason'],'metadata-size')
    def test_limit_and_name_filter_no_unbounded_export(self):
        methods=[{'name':'get_Friend_'+str(i),'parameter_count':0,'static':False} for i in range(c.LIMIT+3)]
        methods.append({'name':'PRIVATE\nTEXT','parameter_count':0,'static':False})
        m=SimpleNamespace(types=[{'image':'DV.dll','namespace':'DV.Models','name':'User','method_start':0,'method_count':len(methods)}],methods=methods)
        with patch.object(c,'definition_fields',return_value=[]):result=c.collect(m)
        self.assertTrue(result['friend_methods']['truncated']);self.assertEqual(result['friend_methods']['total'],c.LIMIT+3)
        self.assertEqual(len(result['friend_methods']['definitions']),c.LIMIT)
        self.assertNotIn('PRIVATE',json.dumps(result))
    def test_report_is_local_and_exceptions_do_not_export_paths(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'test-apks';folder.mkdir();hashes=bundle(folder)
            with patch.object(c,'HASHES',hashes):report,path=c.write_report(folder)
            self.assertEqual(path.name,'rootless-friends-metadata-0.3.9.json');self.assertEqual(json.loads(path.read_text()),report)
            self.assertNotIn(td,json.dumps(report))
        self.assertEqual(c.inspect_bundle('/missing/PRIVATE/PATH',expected_hashes={'base.apk':'0'*64})['reason'],'apk-missing-or-too-large')

    def test_field_layout_is_validated_before_export(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            for damage in ('overlap','owner'):
                data=bytearray(metadata_fixture())
                if damage=='overlap':struct.pack_into('<I',data,24*4,256)
                else:
                    off=struct.unpack_from('<I',data,40*4)[0];struct.pack_into('<i',data,off+8*4,999999)
                hashes=bundle(folder,bytes(data))
                result=c.inspect_bundle(folder,expected_hashes=hashes)
                self.assertEqual(result['reason'],'metadata-unsupported-or-invalid')
                self.assertIsNone(result['catalog'])
