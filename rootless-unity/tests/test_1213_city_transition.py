"""Returned, slow UI transitions are verified next frame, never repeated."""
import copy, unittest
from pathlib import Path
import search_city as city
import search_online as online
from test_search_city import ready_city

class CityTransitions(unittest.TestCase):
 def test_only_terminal_city_ui_transitions_receive_special_rule(self):
  source=city.build('Псков')
  for text in ('cityTransition(s.open,current);n.open_completed=true;',
   'cityTransition(s.cityOpen,people);n.city_open_completed=true;',
   'cityTransition(s.citySearch,current);n.city_query_completed=true;',
   'cityTransition(s.citySelect,current,cityArgs([cell,record]));n.city_select_completed=true;',
   'cityTransition(s.apply,current);n.apply_completed=true;'):
   self.assertIn(text,source)
  self.assertIn('cityTransition(s.cityTextSet,input,cityArgs([text]));state.cityTextCommitted=true;n.city_query_text_completed=true;n.city_query_text_returns++;return;',source)
  for name in ('distanceSet','onlineSet','refreshForm','geoGet','windowRoot'):
   self.assertNotIn('cityTransition(s.'+name+',',source)
 def test_slow_read_still_stops_and_pre_call_deadline_unchanged(self):
  source=city.build('Псков')
  self.assertIn("if(Date.now()>deadline)fail('frame-budget');if(n.managed_calls>=6000)",source)
  self.assertIn("if(entry!==cityTransitionEntry)fail('frame-budget');",source)
  self.assertIn("if(phases.get(entry)!==n.phase)fail('signature-mismatch');",source)
  self.assertIn('finally{cityTransitionEntry=null;}',source)
  self.assertIn('const deadline=Date.now()+100;',source)
 def test_exception_and_cancel_are_checked_before_accepting_return(self):
  source=city.build('Псков')
  self.assertIn("if(!ex.readPointer().isNull())fail('managed-exception');if(fixedCancellationRequested)fail('cancelled');if(Date.now()>deadline)",source)
  self.assertIn("if(e==='frame-budget'&&!cityFrameMutated&&((n.phase==='search'&&!n.open_completed)||(n.phase==='query-city'&&state.cityTextCommitted)||(n.phase==='scan-city'&&!n.city_select_attempted)||(n.phase==='wait-city-return'&&n.city_select_completed&&!n.apply_attempted)||(n.phase==='confirm-filters'&&n.city_form_verified&&!n.apply_attempted)||(n.phase==='wait-return'&&n.apply_completed&&n.city_select_completed&&n.city_form_verified))&&n.city_read_budget_retries<4)",source)
 def test_destination_still_verified_on_fresh_frame(self):
  source=city.build('Псков')
  self.assertIn("if(!current.equals(target(state.origin)))fail('identity-changed');",source)
  self.assertIn("if(k!=='filters'||!current.equals(target(state.card)))fail('identity-changed');",source)
  self.assertIn('if(!checkView(current))return;',source)
  self.assertIn("n.city_verified=true;n.city_checkpoint='complete'",source)
 def test_timeouts_and_other_workflows_not_relaxed(self):
  source=city.build('Псков');self.assertIn('},30000);',source);self.assertIn('r.navigation.frames>=900',source)
  self.assertNotIn('cityTransition',online.FUNCTION)
  self.assertNotIn('city_transition_overruns',online.DEFAULTS)
 def test_counter_bounded_and_not_boolean(self):
  for value in (-1,True,7,'1'):
   sample=ready_city();sample['navigation']['city_transition_overruns']=value
   with self.subTest(value=value),self.assertRaises(ValueError):city.validate(sample)
  for value in range(7):
   sample=ready_city();sample['navigation']['city_transition_overruns']=value;city.validate(sample)
 def test_counter_cannot_claim_returned_transition_before_open(self):
  sample=ready_city();sample['navigation']['open_completed']=False;sample['navigation']['city_transition_overruns']=1
  with self.assertRaises(ValueError):city.validate(sample)
 def test_report_preserves_action_evidence_without_private_values(self):
  source=(Path(__file__).resolve().parents[1]/'assistant_profiles.py').read_text(encoding='utf-8')
  for key in ('city_transition_overruns','city_open_attempted','city_open_completed','open_completed','settings_checkpoint','apply_completed'):
   self.assertIn("'"+key+"'",source)
