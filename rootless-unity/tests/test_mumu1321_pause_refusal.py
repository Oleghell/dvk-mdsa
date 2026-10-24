"""No external APIs/devices; refusal and cooperative-resume regression tests."""
import threading
import unittest
from unittest.mock import MagicMock
from assistant_pause import boundary,PortResumed
from mumu_pause import PauseGate
import assistant_contact_followup as follow
import test_mumu1311_context as fixtures
from test_guided_chain import snapshot

class Refusal(unittest.TestCase):
    chain=fixtures.Refusals.chain
    def test_actual_phrases_stop_before_ai_and_stay_terminal(self):
        for text in ('Нет у меня их )))','У меня не чего из этого не работает',
                     'У меня ничего из этого не работает','Ни чего из этого не работает'):
            with self.subTest(text=text):
                c,store,h=self.chain();c.responder=MagicMock(side_effect=AssertionError('No AI'))
                self.assertEqual(c.proposal(snapshot(*h,(text,False))),('declined',None))
                self.assertEqual(c.proposal(snapshot(*h,(text,False),('Ты откуда?',False))),('declined',None))
                c.responder.assert_not_called()
                self.assertFalse(follow.refused([dict(text=text)],requested=False))
    def test_quotes_questions_and_alternative_are_not_refusals(self):
        for text in ('> Нет у меня их )))\nЕсть MAX','Нет у меня их?',
                     'Нет у меня их, только Макс','У меня ничего из этого не работает?'):
            self.assertFalse(follow.refused([dict(text=text)],requested=True),text)

class Resume(unittest.TestCase):
    def test_clean_restart_not_error_alert_or_repair(self):
        import mumu_recovery as recovery
        from assistant_settings import Settings
        paused=threading.Event();gate=PauseGate(threading.Event(),lambda s:paused.set() if s=='paused' else None)
        gate.restart_on_resume=True
        calls=[];result=[];errors=[];recheck=MagicMock();alert=MagicMock();repair=MagicMock()
        def monitor(*a,**kw):
            calls.append(kw)
            if len(calls)==1:
                gate.command('pause');boundary(gate)
                raise AssertionError('stale pass continued')
            return dict(status='completed')
        def work():
            try:result.append(recovery.run(Settings(),gate,MagicMock(),monitor=monitor,
                recheck=recheck,json_alert=alert,repair=repair,write=MagicMock(),mode='new',fresh_session=True))
            except BaseException as e:errors.append(e)
        thread=threading.Thread(target=work);thread.start()
        try:
            self.assertTrue(paused.wait(3));self.assertEqual(len(calls),1)
            gate.command('resume');thread.join(3)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            self.assertEqual(result,[dict(status='completed')]);self.assertEqual(len(calls),2)
            self.assertEqual(calls[1]['mode'],'full');self.assertFalse(calls[1]['fresh_session'])
            recheck.assert_called_once();repair.assert_not_called();alert.assert_not_called()
        finally:gate.set();thread.join(3)
    def test_signal_bypasses_generic_failure_handlers(self):
        self.assertFalse(issubclass(PortResumed,Exception))

    def test_resume_recheck_failure_is_not_ignored(self):
        import mumu_recovery as recovery
        from assistant_settings import Settings
        gate=PauseGate(threading.Event());recheck=MagicMock(side_effect=RuntimeError('identity blocked'))
        monitor=MagicMock(side_effect=PortResumed())
        with self.assertRaises(RuntimeError):
            recovery.run(Settings(),gate,MagicMock(),monitor=monitor,recheck=recheck,repair=MagicMock(),write=MagicMock())
        monitor.assert_called_once();recheck.assert_called_once()
