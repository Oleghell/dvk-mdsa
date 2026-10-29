"""1.0 «Старт»: unread chain chats + new profiles. Synthetic only, no device."""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import assistant_inbox as inbox
import assistant_profiles as profiles
import assistant_run as run
from assistant_guided_chain import GuidedChain
from assistant_settings import Settings, load, save
from assistant_store import Store, StateError
from conversation_engine import QUESTIONS, CONTACT_TEXT
from test_assistant_dialogs import nav_result as plain_nav

WHO = dict(account='100', peer='200', chat='300')
OTHER = dict(account='100', peer='201', chat='301')
GREETING = 'Привет 🙂'


def nav(state, who=None, unread=True):
    value = plain_nav(state, who)
    value['diagnostic'].update(reply_filter_applied=state in ('opened','exhausted'),
                               reply_needed_verified=state=='opened', waiting_rows_skipped=0, handled_rows_skipped=0)
    if unread:
        value['diagnostic'].update(unread_filter_applied=state in ('opened', 'exhausted'),
                                   unread_verified=state == 'opened')
    return value


def msg(i, text, own=False, who=WHO):
    return dict(id=str(i), sender=who['account'] if own else who['peer'], text=text)


def snap(*messages, who=WHO, name=None):
    value = dict(identity=dict(who), messages=[msg(1001, GREETING, True, who), *messages])
    if name:
        value['peer_name'] = name
    return value


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'assistant.sqlite3', Path(self.tmp.name) / 'old')
        self.stop = threading.Event()
        self.settings = Settings()
        self.approve = MagicMock(return_value=True)
        self.sent = []
        self.notifier = MagicMock(return_value=True)

    def journal(self, who=WHO, chat='-1'):
        action = self.store.reserve(dict(attempt=1, account=who['account'], peer=who['peer'],
                                         chat=chat, variant=0), GREETING, approved=True)
        self.store.finish(action, dict(send_attempted=True, send_handler_returned=True))

    def chain(self):
        return inbox.InboxChain(self.store, choose=lambda: 0, seal=lambda v: v, unseal=lambda v: v)

    def sender(self, adb, folder, snapshot, cancelled, *, text):
        self.sent.append(text)
        return dict(attempted=True, handler_returned=True)

    def walk(self, navigations, reads, **kwargs):
        self.nav = MagicMock(side_effect=navigations)
        from test_guided_chain import stable_snapshots
        self.reader = MagicMock(side_effect=stable_snapshots(reads))
        return inbox.walk(self.settings, self.stop, self.approve, lambda _: None,
                          kwargs.pop('chain', None) or self.chain(), navigator=self.nav,
                          reader=self.reader, sender=kwargs.pop('sender', self.sender),
                          notifier=kwargs.pop('notifier', self.notifier),
                          greetings=(GREETING,), pause=lambda _: False, **kwargs)


class Inbox(Base):
    def test_empty_journal_touches_nothing(self):
        # The empty-inbox zero-device-work contract is unchanged (v1.3.84 kept
        # it): operator-led dialogs are adopted only inside passes that already
        # have tracked targets, never by sweeping an empty inbox.
        out = self.walk([], [])
        self.assertEqual(out['status'], 'inbox-empty')
        self.nav.assert_not_called()
        self.reader.assert_not_called()

    def test_journal_greeting_reply_gets_one_confirmed_question_then_leaves(self):
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertTrue(out['return_verified'])
        self.assertEqual(self.sent, [QUESTIONS[0]])
        self.assertEqual(self.approve.call_count, 1)
        self.assertEqual(out['outcomes'], {'chain-waiting:wait-mood': 1})
        self.assertEqual(out['submission_calls'], 1)
        self.assertEqual(out['handler_returns'], 1)
        self.assertEqual(out['outgoing_observed'], 1)
        self.assertFalse(out['delivery_confirmed'])
        self.assertEqual([c.args[0] for c in self.nav.call_args_list], ['open', 'back', 'return'])
        self.assertTrue(self.nav.call_args_list[0].kwargs['unread_only'])

    def test_vzaimno_after_run_authorization_sends_one_question_without_prompt(self):
        from assistant_authorization import RunAuthorization
        self.journal()
        self.approve = RunAuthorization(self.stop, wait=lambda _: False)
        hello = msg(1002, 'Взаимно')
        q = msg(1003, QUESTIONS[0], True)
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, q)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(self.sent, [QUESTIONS[0]])
        self.assertEqual(out['confirmations'], 0)
        self.assertEqual(out['automatic_authorizations'], 1)
        self.assertTrue(out['automatic_send'])
        self.assertFalse(out['per_message_confirmation'])

    def test_read_failure_details_survive_inbox_report(self):
        from one_chat_device import ReadStopped
        self.journal()
        out = self.walk([nav('opened', WHO)], [ReadStopped('nonpositive-message-id',
            dict(read_checkpoint='recheck', wait_reason='none', private_text='PRIVATE'))])
        self.assertEqual(out['reason'], 'chat-bound-chat-read-failed')
        self.assertEqual(out['last_chat_diagnostics']['last_read_failure']['error'], 'nonpositive-message-id')
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.assertFalse(self.sent)

    def test_whole_chain_over_three_starts_sends_each_message_once(self):
        self.journal()
        hello, q = msg(1002, 'Здарова'), msg(1003, QUESTIONS[0], True)
        mood, c = msg(1004, 'Рабочее нормальное'), msg(1005, CONTACT_TEXT, True)
        contact = msg(1006, '@alex_test')
        cycle = lambda: [nav('opened', WHO), nav('returned', WHO), nav('search-ready')]
        self.walk(cycle(), [snap(hello), snap(hello), snap(hello, q)])
        self.walk(cycle(), [snap(hello, q, mood), snap(hello, q, mood), snap(hello, q, mood, c)])
        out = self.walk(cycle(), [snap(hello, q, mood, c, contact),
                                  snap(hello, q, mood, c, contact, name='Александр')])
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])
        self.notifier.assert_called_once_with({'name': 'Александр', 'contacts': ['@alex_test']})
        self.assertEqual(out['contacts_forwarded'], 1)
        # A fourth Start has nothing left: the chain is finished.
        attention, unread = inbox.inbox_targets(self.chain())
        self.assertEqual((attention, unread), ([], []))

    def test_guided_binding_is_also_processed(self):
        chain = self.chain()
        chain.bind(dict(identity=dict(WHO), messages=[msg(1001, GREETING, True)]), (GREETING,), approved=True)
        hello = msg(1002, 'ку')
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, msg(1003, QUESTIONS[0], True))], chain=chain)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(self.sent, [QUESTIONS[0]])

    def test_declined_draft_is_offered_again_without_unread_filter(self):
        self.journal()
        hello = msg(1002, 'Привет')
        self.approve.return_value = False
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')], [snap(hello)])
        self.assertEqual(out['outcomes'], {'message-not-approved': 1})
        self.assertEqual(self.sent, [])
        attention, unread = inbox.inbox_targets(self.chain())
        self.assertEqual([x['peer'] for x in attention], ['200'])
        self.approve.return_value = True
        out = self.walk([nav('opened', WHO, unread=False), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello), snap(hello, msg(1003, QUESTIONS[0], True))])
        self.assertFalse(self.nav.call_args_list[0].kwargs['unread_only'])
        self.assertEqual(self.sent, [QUESTIONS[0]])

    def test_monitor_pass_stays_in_dialogs_and_never_returns_to_search(self):
        self.journal()
        out = self.walk([nav('exhausted'), nav('exhausted', unread=False)], [], entry='dialogs', return_to='dialogs')
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertTrue(out['dialogs_verified'])
        self.assertFalse(out['return_verified'])
        self.assertEqual(self.nav.call_count, 2)
        self.assertTrue(all(c.kwargs['entry'] == 'dialogs' for c in self.nav.call_args_list))
        self.assertEqual(self.nav.call_args.args[0], 'open')

    def test_observed_outgoing_is_counted_once_across_passes(self):
        self.journal()
        hello = msg(1002, 'Привет')
        question = msg(1003, QUESTIONS[0], True)
        route = lambda: [nav('opened', WHO), nav('returned', WHO), nav('search-ready')]
        first = self.walk(route(), [snap(hello), snap(hello), snap(hello, question)])
        second = self.walk(route(), [snap(hello, question)])
        self.assertEqual((first['outgoing_observed'], second['outgoing_observed']), (1, 0))
        self.assertEqual((second['submission_calls'], second['handler_returns']), (0, 0))

    def test_invalid_monitor_screen_is_rejected(self):
        for kwargs in ({'entry': 'chat'}, {'return_to': 'chat'}):
            with self.assertRaises(ValueError):
                self.walk([], [], **kwargs)

    def test_declining_approval_does_not_open_the_next_dialog(self):
        self.journal()
        self.journal(OTHER)
        self.approve.return_value = False
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(msg(1002, 'Привет'))])
        self.assertEqual(out['dialogs_opened'], 1)
        self.assertEqual(out['reason'], 'needs-review')
        self.assertEqual(self.approve.call_count, 1)
        self.assertEqual(self.sent, [])

    def test_unknown_send_isolates_chat_and_never_retries(self):
        self.journal()
        hello = msg(1002, 'Привет')
        sender = MagicMock(side_effect=RuntimeError('PRIVATE'))
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(hello), snap(hello)], sender=sender)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['isolated_dialogs'], 1)
        self.assertEqual(out['outcomes'], {'isolated:send-outcome-unknown': 1})
        self.assertEqual(out['last_chat_diagnostics']['failure_point'], 'send-adapter-exception')
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.assertEqual(inbox.inbox_targets(self.chain()), ([], []))
        self.assertEqual(self.walk([], [])['status'], 'inbox-empty')
        self.assertEqual(sender.call_count, 1)

    def test_native_identity_error_and_device_failure_remain_global_stops(self):
        from one_chat_device import ReadStopped
        self.journal()
        hello=msg(1002,'Привет')
        out=self.walk([nav('opened',WHO)], [snap(hello),snap(hello)],
                      sender=MagicMock(return_value=dict(attempted=False,handler_returned=False,
                           native_check=dict(error='identity-not-bound'))))
        self.assertEqual(out['status'],'inbox-stopped')
        self.assertEqual(out['reason'],'chat-send-native-check-failed')
        self.assertEqual(out['isolated_dialogs'],0)
        self.assertEqual(self.nav.call_count,1)
        self.assertEqual(out['last_chat_diagnostics']['last_send_failure'],'identity-not-bound')

    def test_device_failure_is_not_disguised_as_unknown_send(self):
        from one_chat_device import ReadStopped
        self.journal(); hello=msg(1002,'Привет')
        out=self.walk([nav('opened',WHO)], [snap(hello),snap(hello)],
                      sender=MagicMock(side_effect=ReadStopped('unsupported-runtime')))
        self.assertEqual(out['reason'],'chat-send-device-check-failed')
        self.assertEqual(out['isolated_dialogs'],0)
        self.assertEqual(self.nav.call_count,1)

    def test_old_unknown_reservation_is_isolated_without_sender_invocation(self):
        self.journal()
        chain=self.chain(); hello=msg(1002,'Привет')
        _, action=chain.proposal(snap(hello))
        chain.reserve_confirmed(WHO, action); chain.finish(WHO, action, False)
        sender=MagicMock()
        out=self.walk([nav('opened',WHO),nav('returned',WHO),nav('search-ready')],
                      [snap(hello)],chain=chain,sender=sender)
        self.assertEqual(out['status'],'inbox-completed')
        self.assertEqual(out['isolated_dialogs'],1)
        sender.assert_not_called()
        self.assertEqual(inbox.inbox_targets(self.chain()),([],[]))

    def test_unknown_send_back_failure_still_stops_and_never_retries(self):
        self.journal()
        hello = msg(1002, 'Привет')
        sender = MagicMock(side_effect=RuntimeError('PRIVATE'))
        out = self.walk([nav('opened', WHO), nav('returned', OTHER)],
                        [snap(hello), snap(hello)], sender=sender)
        self.assertEqual(out['status'], 'inbox-stopped')
        self.assertEqual(out['reason'], 'changed-dialog')
        self.assertEqual(inbox.inbox_targets(self.chain()), ([], []))
        self.assertEqual(sender.call_count, 1)

    def test_unknown_send_does_not_starve_another_chat(self):
        self.journal(); self.journal(OTHER)
        hello = msg(1002, 'Привет')
        out = self.walk([nav('opened', WHO), nav('returned', WHO),
                         nav('opened', OTHER), nav('returned', OTHER), nav('search-ready')],
                        [snap(hello), snap(hello), snap(who=OTHER)],
                        sender=MagicMock(side_effect=RuntimeError('PRIVATE')))
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['dialogs_processed'], 2)
        self.assertEqual(out['isolated_dialogs'], 1)
        self.assertEqual([x['peer'] for x in inbox.inbox_targets(self.chain())[1]], ['201'])

    def test_refusal_is_terminal_and_excluded(self):
        self.journal()
        out = self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                        [snap(msg(1002, 'не пиши мне'))])
        self.assertEqual(out['outcomes'], {'declined': 1})
        self.assertEqual(inbox.inbox_targets(self.chain()), ([], []))

    def test_no_visible_unread_or_read_tracked_dialog_returns_to_search(self):
        self.journal()
        out = self.walk([nav('exhausted'), nav('exhausted', unread=False), nav('search-ready')], [])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['reason'], 'visible-exhausted')
        self.reader.assert_not_called()

    def test_read_reply_without_badge_continues_once_and_never_resends(self):
        self.journal()
        hello, question = msg(1002, 'Взаимно'), msg(1003, QUESTIONS[0], True)
        route = lambda: [nav('exhausted'), nav('opened', WHO, unread=False),
                         nav('returned', WHO), nav('search-ready')]
        first = self.walk(route(), [snap(hello), snap(hello), snap(hello, question)])
        self.assertEqual(first['status'], 'inbox-completed')
        self.assertEqual(first['read_dialogs_checked'], 1)
        self.assertEqual([c.kwargs['unread_only'] for c in self.nav.call_args_list if c.args[0]=='open'], [True, False])
        second = self.walk(route(), [snap(hello, question)])
        self.assertEqual(second['submission_calls'], 0)
        self.assertEqual(self.sent, [QUESTIONS[0]])

    def test_read_mood_without_badge_continues_contact_step(self):
        self.journal()
        hello, question = msg(1002, 'Привет'), msg(1003, QUESTIONS[0], True)
        mood, contact = msg(1004, 'Хорошо'), msg(1005, CONTACT_TEXT, True)
        self.walk([nav('opened', WHO), nav('returned', WHO), nav('search-ready')],
                  [snap(hello), snap(hello), snap(hello, question)])
        out = self.walk([nav('exhausted'), nav('opened', WHO, unread=False),
                         nav('returned', WHO), nav('search-ready')],
                        [snap(hello, question, mood), snap(hello, question, mood),
                         snap(hello, question, mood, contact)])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['read_dialogs_checked'], 1)
        self.assertEqual(self.sent, [QUESTIONS[0], CONTACT_TEXT])

    def test_manually_answered_read_chat_is_not_answered_again(self):
        self.journal()
        hello, manual = msg(1002, 'Привет'), msg(1003, 'Это мой ручной ответ', True)
        chain=self.chain(); chain.consume(snap())
        out = self.walk([nav('exhausted'), nav('opened', WHO, unread=False),
                         nav('returned', WHO), nav('search-ready')], [snap(hello, manual)], chain=chain)
        self.assertEqual(out['outcomes'], {'isolated:manual-review': 1})
        self.assertEqual(out['submission_calls'], 0)
        self.assertFalse(self.sent)

    def test_read_round_rotates_across_bounded_passes_and_restarts(self):
        chain = self.chain()
        active = [dict(account='100', peer=str(200+i), chat=str(300+i)) for i in range(25)]
        self.assertEqual(inbox.read_round(chain, active), active)
        for who in active[:10]: inbox.record_checked(chain, who)
        self.assertEqual(inbox.read_round(chain, active), active[10:])
        for who in active[10:20]: inbox.record_checked(chain, who)
        self.assertEqual(inbox.read_round(chain, active), active[20:])
        for who in active[20:]: inbox.record_checked(chain, who)
        self.assertEqual(inbox.read_round(chain, active), active)
        inbox.record_checked(chain, active[0]); inbox.reset_read_round(chain)
        self.assertEqual(inbox.read_round(chain, active), active)

    def test_foreign_chat_is_probed_readonly_and_never_answered(self):
        # v1.3.84: an untracked chat the operator never answered is probed
        # read-only (structure check), rejected with a durable skip marker and
        # left via verified Back; no reply, no draft, no notification. The old
        # contract (never even read) hid operator-led dialogs and their contacts.
        self.journal()
        stranger = dict(identity=dict(OTHER), messages=[msg(1002, 'Привет', who=OTHER)],
                        latest_message_id='1002')
        out = self.walk([nav('opened', OTHER), nav('returned', OTHER), nav('exhausted'),
                         nav('exhausted'), nav('search-ready')], [stranger])
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['operator_probed'], 1)
        self.assertEqual(out['operator_rejected'], 1)
        self.assertEqual(out['operator_adopted'], 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.approve.call_count, 0)
        self.assertEqual(self.reader.call_count, 1)  # the read-only probe only
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT last_message,reason FROM operator_rejects').fetchall(),
                             [('1002', 'no-own-messages')])
            self.assertEqual(db.execute('SELECT 1 FROM operator_bindings').fetchall(), [])
            self.assertEqual(db.execute("SELECT 1 FROM chain_dialogs WHERE peer=?", (OTHER['peer'],)).fetchall(), [])

    def test_operator_led_dialog_is_adopted_and_answered_by_structure(self):
        # v1.3.84: the operator started and led this chat himself; during a
        # normal (non-empty) pass the native scan opens its row, the probe
        # adopts it and the normal chain flow answers the peer's latest message
        # with the standard question in the SAME cycle.
        self.journal()
        own = msg(1001, 'Привет, я Игорь, давай пообщаемся', True, OTHER)
        peer = msg(1002, 'Привет, тоже рада', False, OTHER)
        question = msg(1003, QUESTIONS[0], True, OTHER)
        reads = [dict(identity=dict(OTHER), messages=[own, peer], latest_message_id='1002'),
                 dict(identity=dict(OTHER), messages=[own, peer]),
                 dict(identity=dict(OTHER), messages=[own, peer]),
                 dict(identity=dict(OTHER), messages=[own, peer, question])]
        out = self.walk([nav('opened', OTHER), nav('returned', OTHER), nav('exhausted'),
                         nav('exhausted'), nav('search-ready')], reads)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['operator_adopted'], 1)
        self.assertEqual(out['operator_rejected'], 0)
        self.assertEqual(self.sent, [QUESTIONS[0]])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT anchor_hash FROM operator_bindings').fetchall() and True, True)
            self.assertEqual(db.execute('SELECT stage FROM chain_dialogs WHERE peer=?', (OTHER['peer'],)).fetchall(),
                             [('wait-mood',)])
            self.assertEqual(db.execute('SELECT 1 FROM operator_rejects').fetchall(), [])
        self.assertIn('chain-waiting:wait-mood', out['outcomes'])

    def test_unread_evidence_is_required(self):
        self.journal()
        out = self.walk([nav('opened', WHO, unread=False)], [])
        self.assertEqual(out['reason'], 'unread-selection-not-verified')
        self.reader.assert_not_called()


def cycle_result(**extra):
    n = dict(stage='navigation-ready', error='none', open_attempted=True, send_attempted=False,
             send_handler_returned=False, friends_eligible=True, return_verified=True)
    n.update(extra)
    return dict(navigation=n, declined=False)


class Config:
    cities = ('Псков', 'Орск')
    greetings = (GREETING,)

    def greeting(self):
        return GREETING


class Profiles(Base):
    def go(self, results, cities=None, **kwargs):
        self.cycle = MagicMock(side_effect=results)
        self.city = MagicMock(side_effect=cities or [])
        with unittest.mock.patch('search_city.validate_next', side_effect=lambda value, c: value), \
             unittest.mock.patch('assistant_rotation.History.record'):
            return profiles.walk(self.settings, self.stop, self.approve, lambda _: None, self.store,
                                 cycle=self.cycle, city_next=self.city, config=Config(), **kwargs)

    def city_value(self, name='Псков'):
        from test_search_city import ready_city
        value=ready_city()
        value['navigation'].update(city_selected_name=name,city_previous_name=None,city_round_reset=False)
        return value

    def budget_result(self, **changes):
        return cycle_result(stage='navigation-stopped', error='call-limit', phase='search',
            **dict(dict(search_verified=True, open_attempted=False, open_completed=False,
                chat_open_attempted=False, chat_open_completed=False, cleanup_failed=False,
                frames=85, managed_calls=6000), **changes))

    def test_read_only_search_budget_rotates_city_and_continues(self):
        profiles.Session(self.store).set('city', 'Псков')
        limited=self.budget_result();limited['navigation']['private_text']='PRIVATE'
        greeted=cycle_result(send_attempted=True,send_handler_returned=True)
        out=self.go([limited,greeted], cities=[self.city_value('Орск')], limit=1)
        self.assertEqual(out['status'],'profiles-completed')
        self.assertEqual(out['search_budget_rotations'],1)
        self.assertEqual(out['search_cycles'],2)
        self.assertEqual(out['profiles_checked'],1)
        self.assertEqual(out['send_attempts'],1)
        self.assertNotIn('PRIVATE',json.dumps(out))
        self.approve.assert_not_called()

    def test_read_only_search_frame_budget_rotates_without_any_open_or_send(self):
        profiles.Session(self.store).set('city','Псков')
        limited=self.budget_result();limited['navigation']['error']='frame-budget'
        out=self.go([limited,cycle_result(send_attempted=True,send_handler_returned=True)],cities=[self.city_value('Орск')],limit=1)
        self.assertEqual(out['status'],'profiles-completed')
        self.assertEqual(out['search_budget_rotations'],1)
        self.assertEqual(out['send_attempts'],1)

    def test_post_open_budget_and_cleanup_failure_never_rotate(self):
        profiles.Session(self.store).set('city','Псков')
        for changes in (dict(open_attempted=True), dict(open_completed=True),
                dict(chat_open_attempted=True),dict(chat_open_completed=True),
                dict(cleanup_failed=True),dict(search_verified=False),dict(phase='check-chat'),
                dict(send_attempted=True),dict(send_attempted=True,send_handler_returned=True,return_verified=False)):
            with self.subTest(changes=changes):
                value=self.budget_result();value['navigation'].update(changes)
                out=self.go([value],limit=1)
                self.assertEqual(out['status'],'profiles-stopped')
                self.assertEqual(out['search_budget_rotations'],0)
                self.city.assert_not_called();self.cycle.assert_called_once()

    def test_search_budget_recovery_is_bounded_and_city_failure_stops(self):
        profiles.Session(self.store).set('city','Псков')
        self.cycle=MagicMock(return_value=self.budget_result())
        with unittest.mock.patch.object(profiles,'MAX_SEARCH_CYCLES',2), \
             unittest.mock.patch.object(profiles,'change_city',return_value='Орск') as city:
            out=profiles.walk(self.settings,self.stop,self.approve,lambda _:None,self.store,
                cycle=self.cycle,config=Config(),limit=1)
        self.assertEqual(out['reason'],'search-cycle-limit')
        self.assertEqual(self.cycle.call_count,2);self.assertEqual(city.call_count,2)
        self.assertEqual(out['send_attempts'],0)
        with unittest.mock.patch.object(profiles,'change_city',side_effect=StateError('city-not-verified')):
            out=profiles.walk(self.settings,self.stop,self.approve,lambda _:None,self.store,
                cycle=MagicMock(return_value=self.budget_result()),config=Config(),limit=1)
        self.assertEqual(out['reason'],'city-not-verified')
        self.assertEqual(out['send_attempts'],0)

    def test_approved_or_unknown_cycle_is_not_search_recovery(self):
        profiles.Session(self.store).set('city','Псков')
        def offered(adb,folder,text,ask,cancelled,store):
            ask({},text,cancelled)
            return self.budget_result()
        self.city=MagicMock()
        out=profiles.walk(self.settings,self.stop,self.approve,lambda _:None,self.store,
            cycle=offered,city_next=self.city,config=Config(),limit=1)
        self.assertEqual(out['reason'],'profile-check-stopped')
        self.assertEqual(out['last_profile_diagnostics']['managed_calls'],6000)
        self.city.assert_not_called()

    def test_first_run_sets_city_then_counts_each_outcome(self):
        def greeted(adb, folder, text, ask, cancelled, store):
            self.assertTrue(ask(dict(), text, cancelled))
            return cycle_result(send_attempted=True, send_handler_returned=True)
        results = [greeted, cycle_result(friends_eligible=False), cycle_result(), greeted, greeted]
        values = iter(results)
        def cycle(*args, **kwargs):
            value = next(values)
            return value(*args, **kwargs) if callable(value) else value
        with unittest.mock.patch('search_city.validate_next', side_effect=lambda value, c: value), \
             unittest.mock.patch('assistant_rotation.History.record'):
            out = profiles.walk(self.settings, self.stop, self.approve, lambda _: None, self.store,
                                cycle=cycle, city_next=MagicMock(return_value=self.city_value()),
                                config=Config(), limit=3, fresh_session=True)
        self.assertEqual(out['status'], 'profiles-completed')
        self.assertEqual((out['send_attempts'], out['handlers_returned'], out['skipped_friends'], out['skipped_existing_chat']), (3, 3, 1, 1))
        self.assertIsNone(out['greetings_sent'])
        self.assertIsNone(out['outgoing_observed'])
        self.assertFalse(out['delivery_confirmed'])
        self.assertEqual(out['current_city'], 'Псков')
        self.assertTrue(out['online_verified'])
        self.assertEqual(self.approve.call_count, 3)
        self.assertEqual(out["qualified_profiles"], 3)
        self.assertEqual(out["profiles_checked"], 5)
        self.assertEqual(self.approve.call_args.args[:2], ('greeting', GREETING))
        self.assertEqual(profiles.Session(self.store).get('city'), 'Псков')

    def test_exhausted_list_changes_city_and_continues(self):
        exhausted = cycle_result(stage='navigation-stopped', error='selection-unavailable', open_attempted=False)
        out = self.go([exhausted, cycle_result(send_attempted=True, send_handler_returned=True)],
                       [self.city_value('Псков'), self.city_value('Орск')], limit=1)
        self.assertEqual(out['status'], 'profiles-completed')
        self.assertEqual(out['city_changes'], 2)  # initial (no saved city) + exhaustion
        self.assertEqual(out['current_city'], 'Орск')

    def test_city_failure_keeps_safe_diagnostics_and_does_not_open_profiles(self):
        value = self.city_value()
        value['navigation'].update(stage='navigation-stopped', error='city-results-incomplete',
                                   phase='scan-city', city_checkpoint='results',city_select_attempted=False,
                                   city_visible_rows=10, city_total_rows=30,
                                   private_geo_id='PRIVATE-ID', private_text='PRIVATE-TEXT')
        out = self.go([], [value], limit=1)
        self.assertEqual(out['reason'], 'city-not-verified')
        self.assertEqual(out['last_error'], 'city-results-incomplete')
        self.assertEqual(out['last_city_navigation']['city_checkpoint'], 'results')
        self.assertEqual(out['last_city_navigation']['city_total_rows'], 30)
        self.assertFalse(out['last_city_navigation']['city_select_attempted'])
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.cycle.assert_not_called()

    def test_saved_city_is_kept_between_runs(self):
        profiles.Session(self.store).set('city', 'Псков')
        out = self.go([cycle_result(friends_eligible=False), cycle_result(send_attempted=True, send_handler_returned=True)], limit=1)
        self.assertEqual(out['status'], 'profiles-completed')
        self.assertEqual(out['qualified_profiles'], 1)
        self.assertEqual(out['profiles_checked'], 2)
        self.assertEqual(out['city_changes'], 0)
        self.city.assert_not_called()

    def test_nonqualifying_profiles_are_replaced_but_scan_is_bounded(self):
        profiles.Session(self.store).set('city', 'Псков')
        with unittest.mock.patch.object(profiles, 'MAX_SCANNED', 3):
            out = self.go([cycle_result(friends_eligible=False)] * 3, limit=1)
        self.assertEqual(out['reason'], 'profile-scan-limit')
        self.assertEqual(out['qualified_profiles'], 0)
        self.assertEqual(out['profiles_checked'], 3)
        self.assertEqual(out['skipped_friends'], 3)
        self.assertEqual(self.cycle.call_count, 3)

    def test_declined_greeting_pauses(self):
        profiles.Session(self.store).set('city', 'Псков')
        out = self.go([dict(cycle_result(), declined=True)], limit=3)
        self.assertEqual((out['status'], out['reason']), ('profiles-paused', 'greeting-not-approved'))
        self.assertEqual(self.cycle.call_count, 1)

    def test_unknown_greeting_send_stops(self):
        profiles.Session(self.store).set('city', 'Псков')
        out = self.go([cycle_result(send_attempted=True)], limit=3)
        self.assertEqual(out['reason'], 'send-outcome-unknown')
        self.assertEqual(out['send_attempts'], 1)
        self.assertEqual(out['handlers_returned'], 0)
        self.assertIsNone(out['greetings_sent'])

    def test_unreadable_profile_stops(self):
        profiles.Session(self.store).set('city', 'Псков')
        out = self.go([cycle_result(stage='navigation-stopped', error='screen-not-ready')], limit=3)
        self.assertEqual(out['reason'], 'profile-check-stopped')
        self.assertEqual(out['last_error'], 'screen-not-ready')

    def test_more_than_three_city_changes_continue_until_target(self):
        exhausted = cycle_result(stage='navigation-stopped', error='selection-unavailable', open_attempted=False)
        profiles.Session(self.store).set('city', 'Псков')
        cities = [self.city_value(name) for name in ('Орск','Псков','Орск','Псков','Орск')]
        out = self.go([exhausted] * 5 + [cycle_result(send_attempted=True, send_handler_returned=True)],
                      cities, limit=1)
        self.assertEqual(out['status'], 'profiles-completed')
        self.assertEqual(out['reason'], 'profile-limit')
        self.assertEqual(out['city_changes'], 5)
        self.assertEqual(out['qualified_profiles'], 1)
        self.assertEqual(out['profiles_checked'], 1)
        self.assertEqual(out['search_cycles'], 6)
        self.assertEqual(self.city.call_count, 5)

    def test_empty_cities_do_not_spin_forever_or_change_unused_city(self):
        exhausted = cycle_result(stage='navigation-stopped', error='selection-unavailable', open_attempted=False)
        profiles.Session(self.store).set('city', 'Псков')
        with unittest.mock.patch.object(profiles, 'MAX_SEARCH_CYCLES', 4):
            out = self.go([exhausted] * 4,
                          [self.city_value(n) for n in ('Орск','Псков','Орск')], limit=1)
        self.assertEqual(out['reason'], 'search-cycle-limit')
        self.assertEqual(out['search_cycles'], 4)
        self.assertEqual(out['profiles_checked'], 0)
        self.assertEqual(out['qualified_profiles'], 0)
        self.assertEqual(out['city_changes'], 3)
        self.assertEqual(self.city.call_count, 3)
        self.assertEqual(self.cycle.call_count, 4)

    def test_stop_prevents_next_city_selection(self):
        profiles.Session(self.store).set('city', 'Псков')
        def exhausted(*args, **kwargs):
            self.stop.set()
            return cycle_result(stage='navigation-stopped', error='selection-unavailable', open_attempted=False)
        self.cycle = MagicMock(side_effect=exhausted)
        city = MagicMock()
        out = profiles.walk(self.settings, self.stop, self.approve, lambda _: None, self.store,
                            cycle=self.cycle, city_next=city, config=Config(), limit=1)
        self.assertEqual(out['status'], 'profiles-cancelled')
        city.assert_not_called()

    def test_interrupted_native_cycle_does_not_claim_zero_sends(self):
        profiles.Session(self.store).set('city', 'Псков')
        out = self.go([RuntimeError('PRIVATE transport')], limit=1)
        self.assertEqual(out['status'], 'profiles-stopped')
        self.assertTrue(out['send_attempts_unknown'])
        self.assertIsNone(out['greetings_sent'])
        self.assertNotIn('PRIVATE', json.dumps(out))

    def test_limit_validation(self):
        for limit in (0, 21, '5'):
            with self.assertRaises(ValueError):
                self.go([], limit=limit)

    def test_clear_history_keeps_send_journal(self):
        self.journal()
        with self.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS profile_visits(peer TEXT PRIMARY KEY, friends_count INTEGER, history_status TEXT NOT NULL, checked_at TEXT)')
            db.execute("INSERT INTO profile_visits VALUES('5','10','empty','now')")
        profiles.Session(self.store).set('city', 'Псков')
        profiles.clear_history(self.store)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM profile_visits').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM manual_actions').fetchone()[0], 1)
        self.assertIsNone(profiles.Session(self.store).get('city'))


class Start(unittest.TestCase):
    def go(self, inbox_status='inbox-completed', profiles_status='profiles-completed', mode='full'):
        self.inbox = MagicMock(return_value=dict(inbox.report(), status=inbox_status))
        self.profiles = MagicMock(return_value=dict(profiles.report(5), status=profiles_status))
        self.written = []
        return run.start(Settings(), threading.Event(), MagicMock(), mode=mode,
                         inbox=self.inbox, profiles=self.profiles,
                         lock=unittest.mock.MagicMock(), write=lambda v: self.written.append(v) or 'last-run.json')

    def test_full_runs_replies_then_profiles(self):
        out = self.go()
        self.assertEqual(out['status'], 'completed')
        self.inbox.assert_called_once()
        self.assertEqual(self.profiles.call_args.kwargs['limit'], 5)
        self.assertIn('Готово', run.summary(out))

    def test_profiles_never_start_after_stopped_replies(self):
        out = self.go(inbox_status='inbox-stopped')
        self.assertEqual(out['reason'], 'inbox-not-finished')
        self.profiles.assert_not_called()
        self.assertIn('Проверь экран', run.summary(out))

    def test_declined_inbox_approval_prevents_new_profiles(self):
        reply = dict(inbox.report(), status='inbox-completed', outcomes={'message-not-approved': 1})
        new_profiles = MagicMock()
        result = run.start(Settings(), threading.Event(), MagicMock(),
                           inbox=MagicMock(return_value=reply), profiles=new_profiles,
                           lock=MagicMock(), write=lambda value: 'last-run.json')
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(result['reason'], 'inbox-needs-review')
        new_profiles.assert_not_called()

    def test_modes(self):
        self.go(mode='inbox')
        self.profiles.assert_not_called()
        self.go(mode='profiles')
        self.inbox.assert_not_called()
        with self.assertRaises(ValueError):
            self.go(mode='other')


class SettingsLimit(unittest.TestCase):
    def test_old_workflow_file_still_loads_and_limit_is_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'workflow-settings.json').write_text(
                json.dumps(dict(contacts_enabled=True, reply_interval=120)), encoding='utf-8')
            self.assertEqual(load(folder).profile_limit, 5)
            save(Settings(profile_limit=12), folder)
            self.assertEqual(load(folder).profile_limit, 12)
        for bad in (0, 21):
            with self.assertRaises(Exception):
                Settings(profile_limit=bad).check()


if __name__ == '__main__':
    unittest.main()
