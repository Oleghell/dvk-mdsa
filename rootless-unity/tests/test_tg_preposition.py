import unittest
from assistant_contact_intent import available_alternative
from assistant_contact_clarify import chosen,TELEGRAM_TEXT
import test_inbox_reactivity as flow
from test_inbox_profiles import snap,msg
class Choice(unittest.TestCase):
    def test_short_preposition_selects_only_named_app(self):
        for text in ('В тг','в телеграм','в Telegram','В ватс ап'):
            self.assertEqual(available_alternative([dict(text=text)]),'whatsapp' if 'ватс' in text else 'telegram')
            self.assertTrue(chosen([dict(text=text)]))
        for text in ('В тг?','Не хочу в тг','Не пиши в тг','> В тг','Нет тг','В тг не работает'):
            self.assertIsNone(available_alternative([dict(text=text)]),text)
class TelegramFlow(flow.ContactFlow):
    def test_wait_contact_v_tg_prepares_one_specific_clarification_without_ai(self):
        chain,messages=self.waiting()
        from assistant_contact_policy import enable
        enable(self.store)
        stage,action=chain.proposal(snap(*messages,msg(1006,'В тг')))
        self.assertEqual((stage,action),('pending-clarify',dict(kind='clarify',text=TELEGRAM_TEXT)))
for name in dir(flow.ContactFlow):
    if name.startswith('test_') and name not in TelegramFlow.__dict__:setattr(TelegramFlow,name,None)

class OldSelection(flow.ContactFlow):
    def closed(self,text='В тг'):
        import assistant_selection_recovery as fix
        from assistant_chain import fingerprint
        from assistant_reply_audit import initialize
        chain,messages=self.waiting();current=snap(*messages,msg(1006,text));current['latest_message_id']='1006'
        fix.enable(chain)
        # Reproduce old ambiguous policy closure, not a genuine global refusal.
        with self.store.connection() as db:
            salt=db.execute('SELECT salt FROM chain_dialogs').fetchone()[0]
            db.execute("UPDATE chain_dialogs SET stage='declined'")
            for m in current['messages']:db.execute('INSERT OR IGNORE INTO chain_seen VALUES(?,?,?)',(current['identity']['chat'],m['id'],fingerprint(m,salt)))
            initialize(db)
            db.execute("INSERT OR REPLACE INTO chain_reply_receipts VALUES(?,?,?,'declined',NULL)",(current['identity']['chat'],'1006',fingerprint(current['messages'][-1],salt)))
        return fix,chain,current
    def test_exact_old_selection_restores_only_latest_input_and_clarification(self):
        from test_inbox_profiles import WHO
        from assistant_inbox import inbox_targets,with_seen_ids
        fix,chain,current=self.closed()
        self.assertIn(WHO,inbox_targets(chain)[1]);self.assertEqual(with_seen_ids(chain,[WHO])[0]['seen_ids'],[])
        self.assertTrue(fix.reserve(chain,WHO));self.assertFalse(fix.reserve(chain,WHO))
        self.assertTrue(fix.recover(chain,current,current));self.assertFalse(fix.recover(chain,current,current))
        current.pop('latest_message_id');self.assertEqual(chain.proposal(current),('pending-clarify',dict(kind='clarify',text=TELEGRAM_TEXT)))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT status,original_stage,original_receipt FROM chain_selection_recovery').fetchone(),('recovered','declined','declined'))
            self.assertEqual(db.execute("SELECT status FROM chain_actions WHERE kind='contact'").fetchone(),('outgoing-observed',))
    def test_full_inbox_pass_reopens_old_selection_once_then_observes_clarification(self):
        from test_inbox_profiles import WHO,nav
        fix,chain,current=self.closed()
        after=snap(*current['messages'][1:],msg(1007,TELEGRAM_TEXT,True))
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
            [current,current,current,after],chain=chain)
        self.assertEqual(out['status'],'inbox-completed',out)
        self.assertEqual(self.sent,[TELEGRAM_TEXT]);self.assertEqual(out['submission_calls'],1)
        self.assertEqual(fix.targets(chain),set())

    def test_real_refusal_question_or_other_closure_is_not_reopened(self):
        from test_inbox_profiles import WHO
        fix,chain,current=self.closed()
        from assistant_chain import fingerprint
        for text in ('Не пиши в тг','В тг?','Никуда не пойду','В ватсап'):
            current['messages'][-1]['text']=text
            with self.store.connection() as db:
                db.execute('DELETE FROM chain_selection_recovery')
                salt=db.execute('SELECT salt FROM chain_dialogs').fetchone()[0]
                digest=fingerprint(current['messages'][-1],salt)
                db.execute('UPDATE chain_seen SET fingerprint=? WHERE message=?',(digest,'1006'))
                db.execute('UPDATE chain_reply_receipts SET fingerprint=? WHERE message=?',(digest,'1006'))
            self.assertTrue(fix.reserve(chain,WHO));self.assertFalse(fix.recover(chain,current,current),text)
    def test_missing_latest_marker_changed_history_and_budget_stay_closed(self):
        from test_inbox_profiles import WHO
        import copy
        fix,chain,current=self.closed();self.assertTrue(fix.reserve(chain,WHO))
        without=dict(current);without.pop('latest_message_id')
        self.assertFalse(fix.recover(chain,without,without))
        changed=copy.deepcopy(current);changed['messages'][0]['text']='Другой текст'
        self.assertFalse(fix.recover(chain,changed,changed))
        with self.store.connection() as db:db.execute("INSERT INTO chain_actions VALUES(?,'clarify','x','outgoing-observed','x')",(WHO['chat'],))
        self.assertFalse(fix.recover(chain,current,current))
for name in dir(flow.ContactFlow):
    if name.startswith('test_') and name not in OldSelection.__dict__:setattr(OldSelection,name,None)
