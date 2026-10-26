"""Fewer full reads for a received contact; synthetic snapshots, no live device."""
import copy,itertools,unittest
from unittest.mock import MagicMock,patch
import one_chat_probe as probe
import one_chat_device as device
from test_compact_assistant import rpc
import test_inbox_reactivity as reactivity
from test_inbox_profiles import WHO,msg,snap,nav

class OptionalName(unittest.TestCase):
    def test_optional_name_requires_fixed_bound_name_reader(self):
        for flag in (True,1,'yes'):
            with self.assertRaises(ValueError):probe.build(WHO,read_name_optional=flag)
        with self.assertRaises(ValueError):probe.build(read_name=True,read_name_optional=True)
        with self.assertRaises(ValueError):device.capture('unused','unused',expected=WHO,read_name_optional=True)

    def test_missing_name_only_is_omitted_and_other_checks_still_fail_closed(self):
        value=rpc();value['navigation']['private_result']['peer_name']=None
        result=probe.private_snapshot(value,WHO,read_name=True,read_name_optional=True)
        self.assertNotIn('peer_name',result)
        with self.assertRaises(ValueError):probe.private_snapshot(value,WHO,read_name=True)
        for name in ('',42,'x'*129,'name\nPRIVATE'):
            bad=copy.deepcopy(value);bad['navigation']['private_result']['peer_name']=name
            with self.assertRaises(ValueError):probe.private_snapshot(bad,WHO,read_name=True,read_name_optional=True)
        wrong=dict(WHO,peer='201')
        with self.assertRaises(ValueError):probe.private_snapshot(value,wrong,read_name=True,read_name_optional=True)
        bad=copy.deepcopy(value);bad['navigation']['private_result']['messages'][0]['sender']='999'
        with self.assertRaises(ValueError):probe.private_snapshot(bad,WHO,read_name=True,read_name_optional=True)

    def test_combined_source_keeps_every_full_history_and_binding_check(self):
        for latest,inputs in itertools.product((False,True),repeat=2):
            source=probe.build(WHO,read_name=True,read_name_optional=True,read_latest=latest,read_input=inputs,scoped_traversal=True)
            for text in ('sample_interval_ms:1000','JSON.stringify(state.sample)!==JSON.stringify(sample)',
                         'peer_name:peerName','const chunkSize=8;','n.managed_calls>=60000','verifyWho();'):
                self.assertIn(text,source)
            self.assertNotIn("catch(nameMetadataUnavailable){fail",source)

class ContactLatency(reactivity.ContactFlow):
    def test_named_contact_uses_one_history_read_without_ai_send_or_sleep(self):
        chain,messages=self.waiting();chain.responder=MagicMock(side_effect=AssertionError('AI not needed'))
        candidate=dict(snap(*messages,msg(1006,'123 456 78 90')),peer_name='Тест')
        progress=[]
        import assistant_guided_chain as guide
        original=guide.walk
        def walk(*a,**kw):kw['progress']=progress.append;return original(*a,**kw)
        with patch('assistant_inbox.walk_chat',side_effect=walk):
            out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],[candidate],chain=chain)
        self.assertEqual(out['contacts_forwarded'],1)
        self.assertEqual(self.reader.call_count,1)
        self.assertEqual(out['last_chat_diagnostics']['read_calls'],1)
        self.assertFalse(self.sent);chain.responder.assert_not_called()
        self.assertTrue(any('Контакт получен' in p for p in progress))
        self.assertEqual(self.notifier.call_args.args[0]['contacts'],['1234567890'])

# Do not rerun the parent's complete regression suite through inheritance.
for name in dir(reactivity.ContactFlow):
    if name.startswith('test_') and name not in ContactLatency.__dict__:setattr(ContactLatency,name,None)

class ProductionAdapter(unittest.TestCase):
    def test_default_inbox_reader_combines_only_enabled_contact_metadata(self):
        import tempfile,threading
        from pathlib import Path
        import assistant_inbox as inbox
        from assistant_settings import Settings
        from assistant_store import Store
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db')
            for enabled in (True,False):
                with patch.object(inbox,'walk',return_value=inbox.report()) as walk,patch('assistant_ai.responder',return_value=None):
                    inbox.run(Settings(contacts_enabled=enabled,errors_enabled=False),threading.Event(),MagicMock(),
                        store=store,navigator=MagicMock(),sender=MagicMock(),notifier=MagicMock(),
                        exit_notifier=MagicMock(),contact_photo=MagicMock(),greetings=('Привет',))
                adapter=walk.call_args.kwargs['reader']
                self.assertIs(adapter.func,device.capture)
                self.assertEqual(adapter.keywords,dict(read_latest=True,read_input=True,
                    read_name=enabled,read_name_optional=enabled))

class ContactRouting(reactivity.ContactFlow):
    def test_contact_routes_directly_to_full_consume_before_clarification_lookup(self):
        chain,messages=self.waiting()
        candidate=dict(snap(*messages,msg(1006,'123 456 78 90')),peer_name='Тест')
        original=chain.consume;consuming=[]
        def consume(value):
            consuming.append(True)
            return original(value)
        # consume has its own independent, unchanged context lookup. Routing
        # must not do another one before entering that authoritative validation.
        import assistant_contact_clarify as clarify
        selected=clarify.selected_alternative_text
        def lookup(*a,**kw):
            self.assertTrue(consuming,'Unnecessary pre-consume clarification lookup')
            return selected(*a,**kw)
        with patch.object(chain,'consume',side_effect=consume),patch.object(clarify,'selected_alternative_text',side_effect=lookup):
            self.assertEqual(chain.proposal(candidate),('done',None))
        self.assertEqual(len(consuming),1)
        self.assertFalse(self.sent)

    def test_phone_in_packet_does_not_override_current_refusal(self):
        chain,messages=self.waiting()
        candidate=dict(snap(*messages,msg(1006,'123 456 78 90'),msg(1007,'Не пиши мне')),peer_name='Тест')
        self.assertEqual(chain.proposal(candidate),('declined',None))
        with self.store.read_connection() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM chain_contact_outbox').fetchone())
        self.assertFalse(self.sent);self.notifier.assert_not_called()

    def test_read_routing_uses_one_snapshot_without_global_writer_lock(self):
        from contextlib import contextmanager
        chain,messages=self.waiting()
        candidate=dict(snap(*messages,msg(1006,'123 456 78 90')),peer_name='Тест')
        original_read=self.store.read_connection;groups=[]
        @contextmanager
        def read():
            sql=[];groups.append(sql)
            with original_read() as db:
                class Proxy:
                    def __getattr__(self,key):return getattr(db,key)
                    def execute(self,statement,*a,**kw):sql.append(statement);return db.execute(statement,*a,**kw)
                yield Proxy()
        with patch.object(self.store,'read_connection',read):
            self.assertEqual(chain.proposal(candidate),('done',None))
        routing=[group for group in groups if any('SELECT stage FROM chain_dialogs' in q for q in group)]
        self.assertEqual(len(routing),1)
        self.assertEqual(len(routing[0]),3)
        self.assertTrue(all(q.startswith('SELECT ') for q in routing[0]))

for name in dir(reactivity.ContactFlow):
    if name.startswith('test_') and name not in ContactRouting.__dict__:setattr(ContactRouting,name,None)
