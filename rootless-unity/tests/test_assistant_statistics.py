"""Local aggregate events and authorized Telegram queries, no network."""
from datetime import datetime,timezone
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import assistant_statistics as stats
import telegram_statistics as bot
from assistant_store import Store
try:from morelogin_store import SharedStore
except ImportError:SharedStore=None

class Statistics(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'shared.sqlite3';self.store=Store(self.path)
 def test_atomic_idempotent_no_contact_or_names_stored(self):
  with self.store.connection() as db:
   stats.received(db,'100','200','300',['+79991234567','@example'],datetime(2026,10,22,tzinfo=timezone.utc))
   stats.received(db,'100','200','300',['+79991234567'],datetime(2026,10,22,tzinfo=timezone.utc))
   row=db.execute('SELECT * FROM global_contact_statistics').fetchone()
  self.assertEqual(row[2:5],('Неизвестен',1,1));self.assertNotIn('79991234567',str(row));self.assertNotIn('example',str(row))
  text=stats.render('/today',self.path,datetime(2026,10,22,12,tzinfo=timezone.utc))
  self.assertIn('Контакт дали: 1',text)
 def test_real_chain_records_contact_once(self):
  import test_guided_chain as fixture
  case=fixture.WholeChain(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
  result=case.walk()
  self.assertEqual(result['status'],'chain-completed')
  with case.store.connection() as db:
   self.assertEqual(db.execute('SELECT phone_count,handle_count,telegram FROM global_contact_statistics').fetchall(),[(0,1,'accepted')])
  self.assertNotIn(fixture.CONTACT,stats.render('/today',case.path))
  case.chain.proposal(fixture.sequence()[-1])
  with case.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM global_contact_statistics').fetchone()[0],1)
 def test_transaction_rollback(self):
  with self.assertRaises(RuntimeError):
   with self.store.connection() as db:
    stats.received(db,'100','200','300',['123456789']);raise RuntimeError()
  with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM global_contact_statistics').fetchone()[0],0)
 def test_city_is_greeting_city_not_later_current_city(self):
  with self.store.connection() as db:
   db.execute('CREATE TABLE search_session(key TEXT PRIMARY KEY,value TEXT)');db.execute("INSERT INTO search_session VALUES('city','Киев')")
   stats.remember_city(db,'100','200');db.execute("UPDATE search_session SET value='Одесса'")
   stats.received(db,'100','200','300',['123456789'])
  self.assertIn('Киев — 1',stats.render('/city',self.path));self.assertNotIn('Одесса',stats.render('/city',self.path))
 def test_nickname_only_not_counted_as_phone_city(self):
  with self.store.connection() as db:stats.received(db,'100','200','300',['@example'])
  self.assertIn('С номером: 0',stats.render('/city',self.path))
 def test_read_connection_is_closed(self):
  real=sqlite3.connect;opened=[]
  def connect(*args,**kwargs):
   value=real(*args,**kwargs);opened.append(value);return value
  with patch('assistant_statistics.sqlite3.connect',side_effect=connect):stats.render('/today',self.path)
  self.assertEqual(len(opened),2)
  for connection in opened:
   with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
 def test_old_database_is_not_backfilled(self):
  old=Path(self.temp.name)/'old.sqlite3'
  sqlite3.connect(old).close()
  self.assertIn('Старые контакты',stats.render('/today',old))
 def test_periods_and_exclusive_midnight(self):
  with self.store.connection() as db:
   for i,date in enumerate((21,22,23)):stats.received(db,'100',str(i),'300',['123456789'],datetime(2026,10,date,tzinfo=timezone.utc))
  now=datetime(2026,10,22,18,tzinfo=timezone.utc)
  self.assertIn('Контакт дали: 1',stats.render('/today',self.path,now));self.assertIn('Контакт дали: 1',stats.render('/yesterday',self.path,now))
  self.assertIn('Контакт дали: 2',stats.render('/week',self.path,now));self.assertIn('Контакт дали: 2',stats.render('/month',self.path,now))
 def test_timezone_daylight_saving(self):
  from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
  try:zone=ZoneInfo('Europe/Kyiv')
  except ZoneInfoNotFoundError:self.skipTest('OS timezone database unavailable')
  first,last=stats.bounds('/today',datetime(2026,10,25,12,tzinfo=zone))
  self.assertEqual((datetime.fromisoformat(last)-datetime.fromisoformat(first)).total_seconds(),25*3600)
 @unittest.skipIf(SharedStore is None,'MoreLogin adapter not in MuMu')
 def test_shared_store_two_phones_one_event_table(self):
  a=SharedStore(self.path,cloud_id='101');b=SharedStore(self.path,cloud_id='102')
  for store,peer in ((a,'200'),(b,'201')):
   with store.connection() as db:stats.received(db,'100',peer,'300',['123456789'])
  with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM global_contact_statistics').fetchone()[0],2)
 def test_accepted_status_not_delivery_promise(self):
  with self.store.connection() as db:
   stats.received(db,'100','200','300',['123456789']);stats.notified(db,'100','200','300','accepted')
  self.assertIn('Telegram принял: 1',stats.render('/month',self.path));self.assertNotIn('доставлен',stats.render('/month',self.path))

class Bot(unittest.TestCase):
 def update(self,i=1,chat=123,text='/today'):
  return dict(update_id=i,message=dict(chat=dict(id=chat),text=text))
 def test_only_configured_chat_and_finite_commands(self):
  for text in stats.COMMANDS:self.assertEqual(bot.command(self.update(text=text),'123'),text)
  for value in (self.update(chat=124),self.update(chat=True),self.update(text='/start'),self.update(text='/today private'),dict(update_id=2,edited_message=dict(chat=dict(id=123),text='/today'))):self.assertIsNone(bot.command(value,'123'))
 def test_commit_before_send_and_no_retry_unknown(self):
  calls=[]
  def commit(n):calls.append(('commit',n))
  def send(*args):calls.append(('send',));raise OSError('Unknown')
  fetcher=lambda *args:[self.update()]
  value=bot.cycle('TOKEN','123',0,commit,fetcher=fetcher,sender=send,renderer=lambda _: 'SAFE')
  self.assertEqual(value,2);self.assertEqual(calls,[('commit',2),('send',)])
  bot.cycle('TOKEN','123',value,commit,fetcher=fetcher,sender=send);self.assertEqual(len(calls),2)
 def test_unauthorized_updates_advance_offset_without_reply(self):
  send=MagicMock();render=MagicMock()
  self.assertEqual(bot.cycle('TOKEN','123',0,MagicMock(),fetcher=lambda *args:[self.update(chat=124)],sender=send,renderer=render),2)
  send.assert_not_called();render.assert_not_called()
 def test_offset_save_failure_no_send(self):
  send=MagicMock()
  with self.assertRaises(OSError):bot.cycle('TOKEN','123',0,MagicMock(side_effect=OSError()),fetcher=lambda *args:[self.update()],sender=send)
  send.assert_not_called()
 def test_render_exception_body_not_exported(self):
  send=MagicMock()
  bot.cycle('TOKEN','123',0,MagicMock(),fetcher=lambda *args:[self.update()],sender=send,renderer=MagicMock(side_effect=RuntimeError('PRIVATE')))
  self.assertNotIn('PRIVATE',str(send.call_args))

class SharedScan(unittest.TestCase):
 def test_yields_before_action_only_and_bounded(self):
  import dialog_models
  source=dialog_models.build()
  self.assertIn('batch<4',source);self.assertIn('Date.now()<deadline-40',source);self.assertIn('!n.action_attempted&&!n.action_completed',source)
  self.assertIn('state.rowBudgetYields<3',source);self.assertIn('budget_yields<12',source)
  self.assertIn('state.countedIndex!==state.scanIndex',source)
 def test_invalid_private_budget_not_accepted(self):
  import dialog_models
  for value in (True,-1,13,'1'):
   with self.assertRaises(ValueError):dialog_models.validate(dict(navigation=dict(private_model_scan=dict(next=None,count=0,skipped_headers=0,budget_yields=value))))
