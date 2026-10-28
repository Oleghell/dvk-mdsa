"""Synthetic only: exact legacy anchors, native latest pointer, isolated journals."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock
import assistant_inbox as inbox
import assistant_legacy_recovery as recovery
import assistant_reply_audit as audit
import mumu_controller
from mumu_store import SharedStore
import one_chat_probe as probe
from test_inbox_profiles import Base, WHO, GREETING, msg, snap, nav
from test_one_chat import rpc
from assistant_chain import text_hash

class Recovery(Base):
 def model_chain(self):
  return inbox.InboxChain(self.store,choose=lambda:0,responder=MagicMock(return_value=dict(decision='reply',text='У меня тоже хорошо. Если удобно, можем пообщаться в телеграме?')),seal=lambda v:v,unseal=lambda v:v)
 def history(self):
  s=snap(msg(1002,'Здравствуйте'),msg(1003,'Как дела?)',True),msg(1004,'Спасибо хорошо'))
  s['latest_message_id']='1004';return s
 def notice(self,s,reason='greeting-not-verified'):
  excerpts=[m['text'] if isinstance(m['text'],str) else '[нет текста]' for m in s['messages'] if m['sender']==WHO['peer']]
  batch=hashlib.sha256(json.dumps(excerpts,ensure_ascii=True).encode()).hexdigest()
  signature=hashlib.sha256(json.dumps([reason,None,[],batch],ensure_ascii=True).encode()).hexdigest()
  with self.store.connection() as db:
   db.execute('CREATE TABLE IF NOT EXISTS chain_exit_notices(chat TEXT,signature TEXT,status TEXT NOT NULL,PRIMARY KEY(chat,signature))')
   db.execute("INSERT INTO chain_exit_notices VALUES(?,?,'accepted')",(WHO['chat'],signature))
 def test_recovers_observed_question_and_only_latest_peer_without_sending(self):
  self.journal();chain=self.model_chain();s=self.history();chain.bind(s,(GREETING,),approved=True)
  self.assertTrue(chain.last_legacy_recovered)
  with self.store.connection() as db:
   self.assertEqual(db.execute('SELECT stage,greeting FROM chain_dialogs').fetchone(),('wait-mood','1001'))
   self.assertEqual(db.execute('SELECT kind,trigger,status FROM chain_actions').fetchone(),('question',None,'outgoing-observed'))
   self.assertEqual({r[0] for r in db.execute('SELECT message FROM chain_seen')},{'1001','1002','1003'})
   self.assertEqual(db.execute('SELECT basis FROM chain_recovered_anchors').fetchone()[0],'native-last-peer-exact-templates')
  self.assertFalse(self.sent)
  plain={k:s[k] for k in ('identity','messages')};stage,action=chain.proposal(plain)
  self.assertEqual(action['kind'],'contact');self.assertEqual(chain.responder.call_args.args[1]['_reply_ids'],['1004'])
  self.assertEqual(audit.pending(chain,WHO),['1004'])
  self.assertFalse(recovery.recover(chain,s))
 def test_complete_walk_answers_screenshot_once_then_leaves(self):
  self.journal();chain=self.model_chain();s=self.history();after=copy.deepcopy(s)
  text=chain.responder.return_value['text'];after['messages'].append(msg(1005,text,True));after['latest_message_id']='1005'
  route=lambda:[nav('opened',WHO),nav('returned',WHO),nav('search-ready')]
  out=self.walk(route(),[s,s,after],chain=chain)
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(self.sent,[text])
  self.assertEqual(audit.pending(chain,WHO),[])
  out=self.walk(route(),[after],chain=chain)
  self.assertEqual(out['submission_calls'],0);self.assertEqual(self.sent,[text]);self.assertEqual(chain.responder.call_count,1)
 def test_previously_read_old_placeholder_is_recovered_in_read_group(self):
  self.journal();chain=self.model_chain();s=self.history();chain.mark_review(WHO);self.notice(s)
  after=copy.deepcopy(s);text=chain.responder.return_value['text'];after['messages'].append(msg(1005,text,True));after['latest_message_id']='1005'
  out=self.walk([nav('exhausted'),nav('opened',WHO,unread=False),nav('returned',WHO),nav('search-ready')],[s,s,after],chain=chain)
  self.assertEqual(out['status'],'inbox-completed');self.assertEqual(out['read_dialogs_checked'],1)
  self.assertEqual(self.sent,[text]);self.assertTrue(out['last_chat_diagnostics']['legacy_stage_recovered'])
  self.assertEqual(out['last_chat_diagnostics']['legacy_recovery_reason'],'recovered')
  self.assertFalse(recovery.candidates(self.store))
 def test_old_null_placeholder_recovers_only_matching_failure_notice(self):
  self.journal();chain=self.model_chain();s=self.history();chain.mark_review(WHO);self.notice(s)
  self.assertIn(tuple(WHO.values()),recovery.candidates(self.store))
  self.assertTrue(recovery.recover(chain,s))
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_exit_notices').fetchone()[0],1)
 def test_different_review_notice_never_reopens_placeholder(self):
  self.journal();chain=self.model_chain();s=self.history();chain.mark_review(WHO);self.notice(s,'send-outcome-unknown')
  self.assertFalse(recovery.recover(chain,s))
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT greeting,stage FROM chain_dialogs').fetchone(),(None,'manual-review'))
 def test_old_placeholder_inspection_is_one_shot_even_when_proof_missing(self):
  self.journal();chain=self.model_chain();s=self.history();chain.mark_review(WHO);self.notice(s)
  self.assertTrue(recovery.reserve_probe(chain,WHO));self.assertFalse(recovery.reserve_probe(chain,WHO))
  s.pop('latest_message_id');self.assertFalse(recovery.recover(chain,s))
  self.assertNotIn(tuple(WHO.values()),recovery.candidates(self.store))
  self.assertNotIn(WHO,inbox.inbox_targets(chain)[1])
 def test_reserved_placeholder_probe_can_recover_in_same_inspection(self):
  self.journal();chain=self.model_chain();s=self.history();chain.mark_review(WHO);self.notice(s)
  self.assertTrue(recovery.reserve_probe(chain,WHO));self.assertTrue(recovery.recover(chain,s))
 def test_ai_disabled_does_not_reopen_old_placeholders(self):
  self.journal();chain=self.chain();s=self.history();chain.mark_review(WHO);self.notice(s)
  self.assertEqual(inbox.inbox_targets(chain),([],[]));self.assertFalse(recovery.reserve_probe(chain,WHO))
 def test_changed_incoming_batch_never_guesses_old_notice(self):
  self.journal();chain=self.model_chain();s=self.history();chain.mark_review(WHO);self.notice(s)
  s['messages'][-1]['text']='новое';self.assertFalse(recovery.recover(chain,s))
 def test_latest_missing_own_foreign_or_unjournalled_question_never_recovers(self):
  self.journal();chain=self.model_chain()
  mutations=[lambda s:s.pop('latest_message_id'),lambda s:s.update(latest_message_id='1003'),lambda s:s.update(latest_message_id='9999'),lambda s:s['messages'][2].update(text='Что-нибудь еще?'),lambda s:s['messages'][0].update(text='Другое приветствие'),lambda s:s['messages'].append(msg(1005,'Третий исходящий',True))]
  for mutate in mutations:
   s=self.history();mutate(s);self.assertFalse(recovery.recover(chain,s))
  with self.store.connection() as db:self.assertIsNone(db.execute('SELECT 1 FROM chain_dialogs').fetchone())
 def test_unknown_greeting_is_not_recovered(self):
  self.journal();chain=self.model_chain()
  with self.store.connection() as db:db.execute("UPDATE manual_actions SET status='reserved-unknown'")
  self.assertFalse(recovery.recover(chain,self.history()))
 def test_existing_unknown_action_is_preserved(self):
  self.journal();chain=self.model_chain();s=self.history()
  with self.store.connection() as db:db.execute("INSERT INTO chain_actions VALUES(?,'question','1002',?,'reserved-unknown')",(WHO['chat'],text_hash('Как дела?)')))
  self.assertFalse(recovery.recover(chain,s))
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM chain_actions').fetchone()[0],'reserved-unknown')
 def test_no_ai_and_no_journal_never_recovers(self):
  chain=self.model_chain();self.assertFalse(recovery.recover(chain,self.history()))
  self.journal();self.assertFalse(recovery.recover(self.chain(),self.history()))
 def test_order_and_numeric_ids_are_not_chronology(self):
  self.journal();s=self.history();s['messages'].reverse();s['messages'][0]['id']='2';s['latest_message_id']='2'
  self.assertTrue(recovery.recover(self.model_chain(),s))

class NativeLatestSchema(unittest.TestCase):
 def test_private_marker_requires_bound_optin_and_membership(self):
  value=rpc();value['navigation']['last_message_present']=True;value['navigation']['private_result']['latest_message_id']='1001'
  self.assertEqual(probe.private_snapshot(copy.deepcopy(value),WHO,read_latest=True)['latest_message_id'],'1001')
  with self.assertRaises(ValueError):probe.private_snapshot(copy.deepcopy(value),WHO)
  for marker in ('999',True,3):
   bad=copy.deepcopy(value);bad['navigation']['private_result']['latest_message_id']=marker
   with self.assertRaises(ValueError):probe.private_snapshot(bad,WHO,read_latest=True)
  absent=copy.deepcopy(value);absent['navigation']['private_result']['latest_message_id']=None
  self.assertIsNone(probe.private_snapshot(absent,WHO,read_latest=True)['latest_message_id'])
  absent=copy.deepcopy(value);absent['navigation']['last_message_present']=False
  with self.assertRaises(ValueError):probe.private_snapshot(absent,WHO,read_latest=True)
  with self.assertRaises(ValueError):probe.build(read_latest=True)
 def test_marker_compares_native_pointer_headers_and_both_samples(self):
  s=probe.build(WHO,read_latest=True)
  for needle in ('row.pointer===lastMessage.toString()','JSON.stringify(latestRow.bits)!==JSON.stringify(latestBits)','latest_message_id:latestId','JSON.stringify(state.sample)!==JSON.stringify(sample)'):
   self.assertIn(needle,s)

class Isolation(unittest.TestCase):
 def test_same_chat_receipts_archives_and_recovered_anchors_are_per_phone(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'shared.sqlite3'
   stores=[SharedStore(path,Path(tmp)/'old',device_port=p) for p in (5563,5557)]
   for i,store in enumerate(stores):
    with store.connection() as db:
     audit.initialize(db);db.execute('INSERT INTO chain_reply_receipts VALUES(?,?,?,?,?)',('300','1004','salt'+str(i),'pending',None))
     db.execute('CREATE TABLE IF NOT EXISTS chain_followup_archive(chat TEXT,trigger TEXT,text_hash TEXT,status TEXT,inputs TEXT,PRIMARY KEY(chat,trigger))')
     db.execute('INSERT INTO chain_followup_archive VALUES(?,?,?,?,?)',('300','1004','hash'+str(i),'outgoing-observed','[]'))
     db.execute('CREATE TABLE IF NOT EXISTS chain_recovered_anchors(chat TEXT PRIMARY KEY,greeting TEXT,question TEXT,latest_peer TEXT,basis TEXT NOT NULL)')
     db.execute('INSERT INTO chain_recovered_anchors VALUES(?,?,?,?,?)',('300','1','2','3','basis'+str(i)))
   for i,store in enumerate(stores):
    with store.connection() as db:
     self.assertEqual(db.execute('SELECT fingerprint FROM chain_reply_receipts').fetchall(),[('salt'+str(i),)])
     self.assertEqual(db.execute('SELECT text_hash FROM chain_followup_archive').fetchall(),[('hash'+str(i),)])
     self.assertEqual(db.execute('SELECT basis FROM chain_recovered_anchors').fetchall(),[('basis'+str(i),)])
 def test_migration_requires_salted_observation_not_matching_chat_id(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'shared.sqlite3';old=Path(tmp)/'old'
   root=SharedStore(path,old,device_port=5563);other=SharedStore(path,old,device_port=5557)
   with root.connection() as db:
    audit.initialize(db)
    for mid,fp in [('1','match'),('2','wrong'),('3','absent')]:db.execute('INSERT INTO chain_reply_receipts VALUES(?,?,?,?,?)',('300',mid,fp,'pending',None))
   # Initialize chain schemas before adding verified observations.
   inbox.InboxChain(other)
   with other.connection() as db:
    db.execute('INSERT INTO chain_seen VALUES(?,?,?)',('300','1','match'));db.execute('INSERT INTO chain_seen VALUES(?,?,?)',('300','2','different'))
   migrated=SharedStore(path,old,device_port=5557)
   with migrated.connection() as db:self.assertEqual(db.execute('SELECT message FROM chain_reply_receipts').fetchall(),[('1',)])
   with root.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chain_reply_receipts').fetchone()[0],3)
 def test_slow_first_worker_does_not_block_second_worker_progress(self):
  release=threading.Event();first=threading.Event();second=threading.Event();progress=MagicMock();out=[]
  def worker(port,*args):
   if port==5563:first.set();release.wait(5)
   else:
    first.wait(2);progress(port,'Продолжаю');second.set()
   return 'ok'
  thread=threading.Thread(target=lambda:out.append(mumu_controller.run_many([5563,5557],None,'full',False,threading.Event(),progress,worker=worker,spacing=0)))
  thread.start()
  try:self.assertTrue(second.wait(2));self.assertTrue(thread.is_alive());progress.assert_called_once_with(5557,'Продолжаю')
  finally:release.set();thread.join(5)
  self.assertEqual(out,[{5557:'ok',5563:'ok'}])
