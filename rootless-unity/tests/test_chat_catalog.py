import json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chat_catalog as c
from offline_metadata import Metadata31
from test_friends_catalog import metadata_fixture,bundle


def fixture():
    defs=[('DV.Profile.dll','DV.Profiles','ProfileViewController',[('get_Delegate',0,False,102),('OnChatPressed',1,False,109)]),
          ('DV.Profile.dll','DV.Profiles','ProfilesQueueViewController',[('OnCloseRequested',1,False,109)]),
          ('DV.Profile.dll','','IDelegate',[('OnChatRequested',2,False,109)]),
          ('DV.Messages.dll','DV.Messages','MessagesViewController',[('get_Chat',0,False,105),('get_IsHistoryLoaded',0,False,107),('get_Messages',0,False,106),('SendText',1,False,109)]),
          ('DV.Messages.dll','DV.Messages','ChatsViewController',[('ShowChat',1,False,109)]),
          ('DV.dll','DV.Models','Chat',[('get_Count',0,False,108)]),
          ('DV.dll','DV.CMs','MessagesCM',[('get_IsLoaded',0,False,107),('get_Count',0,False,108)]),
          ('mscorlib.dll','System','Boolean',[]),('mscorlib.dll','System','Int64',[]),('mscorlib.dll','System','Void',[])]
    data=bytearray(metadata_fixture(defs,{0:[('m_Chat',105)],3:[('m_Messages',106)],5:[('m_MessageCount',108)]}))
    h=struct.unpack_from('<64I',data);methods=Metadata31(bytes(data)).methods
    params=bytearray();cursor=0
    for index,m in enumerate(methods):
        struct.pack_into('<i',data,h[12]+index*36+16,cursor if m['parameter_count'] else -1)
        for _ in range(m['parameter_count']):params.extend(struct.pack('<IIi',0,0x08000001,105));cursor+=1
    struct.pack_into('<II',data,22*4,len(data),len(params));data.extend(params)
    return data


class ChatCatalog(unittest.TestCase):
    def test_resolves_route_parameters_and_loaded_history_types(self):
        out=c.collect(Metadata31(bytes(fixture())))
        self.assertTrue(all(r['status']=='found' for r in out['roots']))
        controller=next(t for t in out['types'] if t['type']=='ProfileViewController')
        route=next(m for m in controller['methods'] if m['method']=='OnChatPressed')
        self.assertEqual(route['parameters'][0]['target']['type'],'Chat')
        messages=next(t for t in out['types'] if t['type']=='MessagesViewController')
        self.assertIn('get_IsHistoryLoaded',[m['method'] for m in messages['methods']])
        cm=next(t for t in out['types'] if t['type']=='MessagesCM')
        self.assertEqual(next(m for m in cm['methods'] if m['method']=='get_Count')['return_type']['target']['type'],'Int64')
        self.assertFalse(out['truncated']);self.assertNotIn('PRIVATE',json.dumps(out))
    def test_read_only_bundle_report_and_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir();hashes=bundle(folder,bytes(fixture()))
            with patch('friends_catalog.HASHES',hashes):out,path=c.write_report(folder)
            self.assertEqual(path.name,'rootless-chat-metadata-0.3.20.json')
            self.assertEqual(json.loads(path.read_text()),out)
            for key in ('ui_actions_attempted','method_values_read','chat_opened','history_read','draft_prepared'):self.assertIs(out[key],False)
            self.assertEqual(out['messages_sent'],0);self.assertEqual(out['mode'],'offline-chat-catalog')
            self.assertEqual(out['status'],'catalog-ready');self.assertNotIn('PRIVATE',path.read_text());self.assertNotIn(temp,path.read_text())
    def test_parameter_layout_rejects_overlap_missing_owner_and_negative_type(self):
        for damage in ('overlap','missing','owner','negative','duplicate'):
            data=fixture();h=struct.unpack_from('<64I',data)
            if damage=='overlap':struct.pack_into('<I',data,22*4,h[6])
            elif damage=='missing':struct.pack_into('<I',data,23*4,0)
            elif damage=='owner':struct.pack_into('<i',data,h[12]+36+16,999999)
            elif damage=='negative':struct.pack_into('<i',data,h[22]+8,-1)
            else:struct.pack_into('<i',data,h[12]+2*36+16,0)
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);hashes=bundle(folder,bytes(data));out=c.inspect_bundle(folder,expected_hashes=hashes)
            self.assertEqual(out['status'],'catalog-stopped',damage);self.assertEqual(out['reason'],'metadata-unsupported-or-invalid',damage)
            self.assertIsNone(out['catalog'])
    def test_limit_and_duplicate_type_are_explicit(self):
        meta=Metadata31(bytes(fixture()))
        with patch.object(c,'MAX_TYPES',2):out=c.collect(meta)
        self.assertTrue(out['truncated']);self.assertEqual(len(out['types']),2)
        with patch.object(c,'MAX_METHODS',1):out=c.collect(meta)
        self.assertTrue(out['truncated'])
        meta.types[1]['name']='ProfileViewController';out=c.collect(meta)
        self.assertEqual(out['roots'][0]['status'],'ambiguous')
    def test_cancellation_and_hash_mismatch_are_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);hashes=bundle(folder,bytes(fixture()))
            self.assertEqual(c.inspect_bundle(folder,lambda:True,hashes)['reason'],'cancelled')
            hashes['base.apk']='0'*64
            self.assertEqual(c.inspect_bundle(folder,expected_hashes=hashes)['reason'],'apk-hash-mismatch')
    def test_parser_exposes_verified_v31_parameter_start(self):
        meta=Metadata31(bytes(fixture()))
        self.assertEqual(meta.methods[1]['parameter_start'],0)
        self.assertEqual(meta.methods[1]['parameter_count'],1)
        self.assertEqual(meta.methods[1]['method_flags'],0)

    def test_total_export_budgets_and_parameter_truncation(self):
        meta=Metadata31(bytes(fixture()))
        with patch.object(c,'MAX_TOTAL_METHODS',2),patch.object(c,'MAX_TOTAL_FIELDS',1):out=c.collect(meta)
        self.assertLessEqual(sum(len(t['methods']) for t in out['types']),2)
        self.assertLessEqual(sum(len(t['fields']) for t in out['types']),1)
        self.assertTrue(out['truncated'])
        with patch.object(c,'MAX_PARAMETERS',1):out=c.collect(meta)
        interface=next(t for t in out['types'] if t['type']=='IDelegate')
        method=next(m for m in interface['methods'] if m['method']=='OnChatRequested')
        self.assertEqual(method['arity'],2);self.assertEqual(len(method['parameters']),1)
        self.assertTrue(method['parameters_truncated']);self.assertTrue(out['truncated'])

    def test_route_owner_and_overlay_are_not_starved_by_public_models(self):
        defs=[('DV.Profile.dll','DV.Profiles','ProfileOverlayView',[('OnBlueButton',0,False,0)]),
              ('DV.dll','DV.Routing','UnusualRouter',[('ShowConversation',0,False,0)])]
        defs += [('DV.dll','DV.Models','PublicMessage'+str(i),[]) for i in range(65)]
        out=c.collect(Metadata31(metadata_fixture(defs)))
        names=[t['type'] for t in out['types']]
        self.assertIn('ProfileOverlayView',names);self.assertIn('UnusualRouter',names)
        self.assertTrue(out['candidates_truncated']);self.assertTrue(out['truncated'])
        route=next(d for d in out['discovery'] if d['category']=='route-owner')
        self.assertEqual(route['total'],2);self.assertFalse(route['truncated'])

    def test_generic_content_definitions_exported_without_guessing_binding(self):
        defs=[('DV.dll','DV.CMs','MessagesCM',[('get_Chat',0,False,0)]),
              ('Core.dll','DataKit','ContentList`1',[('get_Count',0,False,0),('get_IsLoaded',0,False,0)]),
              ('Core.dll','Unrelated','ContentList`1',[('get_Count',0,False,0)])]
        data=bytearray(metadata_fixture(defs));h=struct.unpack_from('<64I',data)
        struct.pack_into('<i',data,h[40]+4*4,90001) # constructed generic reference, not a definition index
        out=c.collect(Metadata31(bytes(data)))
        cm=next(t for t in out['types'] if t['type']=='MessagesCM')
        self.assertEqual(cm['parent'],{'type_index':90001,'status':'unresolved'})
        frameworks=[t for t in out['types'] if t['image']=='Core.dll']
        self.assertEqual(len(frameworks),1);self.assertEqual(frameworks[0]['namespace'],'DataKit')
        self.assertIn('get_IsLoaded',[m['method'] for m in frameworks[0]['methods']])

    def test_discovery_cap_is_explicit_and_routes_precede_candidates(self):
        defs=[('DV.dll','DV.Routing','Route'+str(i),[('OpenChat',0,False,0)]) for i in range(4)]
        defs += [('DV.dll','DV.Models','Chat',[])]
        with patch.object(c,'MAX_DISCOVERY_OWNERS',2):out=c.collect(Metadata31(metadata_fixture(defs)))
        route=next(d for d in out['discovery'] if d['category']=='route-owner')
        self.assertTrue(route['truncated']);self.assertEqual(route['total'],5)
        self.assertEqual(route['selected'],2);self.assertTrue(out['truncated'])
        self.assertEqual(out['types'][0]['type'],'Chat')

    def test_compact_report_round_trips_without_values(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'test-apks';folder.mkdir();hashes=bundle(folder,bytes(fixture()))
            with patch('friends_catalog.HASHES',hashes):out,path=c.write_report(folder)
            raw=path.read_text();self.assertEqual(raw.count('\n'),1)
            self.assertEqual(json.loads(raw),out);self.assertNotIn('PRIVATE',raw)

class ChatCatalogGUI(unittest.TestCase):
    def test_chat_button_is_offline_and_never_autostarts(self):
        from unittest.mock import MagicMock
        import navigate_profile_device as gui
        tk=MagicMock();ttk=MagicMock();tk.ttk=ttk
        tk.Tk.return_value.winfo_height.return_value=300;ttk.Frame.return_value.winfo_reqheight.return_value=260
        with patch.dict(sys.modules,{'tkinter':tk,'tkinter.ttk':ttk,'tkinter.filedialog':tk.filedialog,'tkinter.messagebox':tk.messagebox}),patch.object(gui.threading,'Thread') as thread:
            gui.launch_gui();thread.assert_not_called()
            commands={call.kwargs.get('text'):call.kwargs.get('command') for call in ttk.Button.call_args_list}
            commands['Метаданные чата']()
            self.assertEqual(thread.call_args.kwargs['target'].__name__,'catalog_worker')
            self.assertIs(thread.call_args.kwargs['args'][1],True)
            thread.return_value.start.assert_called_once()
            commands['Проверить 10']();thread.return_value.start.assert_called_once()
        self.assertIn('Метаданные чата готовы',gui.result_status({'mode':'offline-chat-catalog','status':'catalog-ready'}))
        tk.messagebox.showinfo.assert_not_called();ttk.Checkbutton.assert_not_called()
