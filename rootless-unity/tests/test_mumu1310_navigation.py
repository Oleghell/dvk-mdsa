"""1.3.9 reported search failures: no live accounts or send replays."""
import copy
import unittest
from unittest.mock import patch
import assistant_pass
import assistant_profile_read as read
import search_city
from test_chat_batch import cycle
from test_search_city import ready_city


class ProfileFrames(unittest.TestCase):
    def result(self):
        value=cycle();value['navigation'].update(cycle_timeout_ms=90000,
            profile_read_budget_retries=0,greeting_frame_splits=1)
        return value

    def test_sample_finishes_before_authorization_and_send(self):
        s=assistant_pass.build('Привет')
        a=s.index("if(n.phase==='check-chat')");b=s.index("if(n.phase==='prepare-greeting')");c=s.index("if(n.phase==='submit-greeting')")
        self.assertNotIn('cohortPending=reservation',s[a:b])
        self.assertNotIn('call(s.send,current,args)',s[a:c])
        for guard in ('integer(s.count,cm)!==0','!call(s.last,chat).isNull()',"!call(s.opponent,chat).equals(user)"):
            self.assertIn(guard,s[b:c]);self.assertIn(guard,s[c:])
        self.assertIn("if(cohortApproved!==reservationKey)fail('identity-changed');",s[c:])
        self.assertIn('const deadline=Date.now()+100;',s)
        self.assertIn('n.managed_calls>=6000',s)

    def test_read_retry_is_bounded_and_never_after_published_authorization(self):
        s=assistant_pass.build('Привет')
        for guard in ("n.phase==='check-chat'",'n.profile_read_budget_retries<4',
                      '!n.send_attempted&&!n.send_handler_returned',
                      'cohortPending===null&&cohortApproved===null',
                      "state.sample=null;n.samples=0;n.message_count=null;"):
            self.assertIn(guard,s)
        self.assertNotIn("e==='managed-exception'&&",s)

    def test_validator_preserves_original_and_rejects_forged_evidence(self):
        v=self.result();old=copy.deepcopy(v);self.assertIs(assistant_pass.validate(v),v);self.assertEqual(v,old)
        for key,bad in [('profile_read_budget_retries',True),('profile_read_budget_retries',5),
                        ('greeting_frame_splits',0),('greeting_frame_splits',2),('samples',1),
                        ('history_fully_loaded',False),('message_count',1)]:
            x=copy.deepcopy(v);x['navigation'][key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):assistant_pass.validate(x)

    def test_shared_claim_skip_still_exists_before_send(self):
        with patch.dict('os.environ',DVK_MUMU_MULTI='1'):s=assistant_pass.build('Привет')
        self.assertEqual(s.count('if(cohortRejected===reservationKey)'),1)
        self.assertLess(s.index('cohortRejected===reservationKey'),s.index('batchSent.add(batchCandidateKey)'))


class CityCandidates(unittest.TestCase):
    def test_first_result_policy_and_no_uncertain_mutation_replay(self):
        s=search_city.build_next(['OldCity','Missing','Pskov'])
        for guard in ('const scan=1;',"n.city_query_returns<6",'state.cityRemaining.shift()',
                      'state.cityRemaining=(fresh.length?fresh:alternatives).slice(0,6)',
                      "if(k!=='city'||!current.equals(target(state.cityFinder)))cityId('query-controller')",
                      "city_select_attempted||n.apply_attempted",'!cityFrameMutated',
                      "if(n.phase==='scan-city'){state.cityFingerprint=null;n.city_scan_samples=0;}"):
            self.assertIn(guard,s)
        self.assertEqual(s.count('cityTransition(s.cityTextSet,input,'),1)
        self.assertEqual(s.count('cityTransition(s.citySearch,current)'),1)
        self.assertIn('},30000);',s);self.assertIn('r.navigation.frames>=900',s)

    def test_multiple_queries_need_complete_distinct_candidate_evidence(self):
        v=ready_city();n=v['navigation'];n.update(city_queries_started=2,city_query_text_returns=2,
            city_query_returns=2,city_candidates_skipped=1,city_transition_overruns=8)
        self.assertIs(search_city.validate(v),v)
        for key,bad in [('city_queries_started',True),('city_queries_started',7),
                        ('city_query_text_returns',0),('city_query_returns',3),
                        ('city_candidates_skipped',0),('city_candidates_skipped',3),
                        ('city_transition_overruns',9)]:
            x=copy.deepcopy(v);x['navigation'][key]=bad
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):search_city.validate(x)
