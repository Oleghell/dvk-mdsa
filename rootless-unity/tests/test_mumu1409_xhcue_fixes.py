"""Reports dropmefiles xhcUe (monitors 695-703): the port-killing fixes.

Synthetic only. Three families pinned here:
  700/701/702 - the city picker's query-city frame-budget deaths (the retry
                arm now covers the uncommitted-text observation and the
                pre-invoke-rejected text setter; the bookkeeping rides after
                the invoke so a rejected invoke is not a started query);
  703         - a transient cloud READ refusal defers the chat instead of
                stopping the whole inbox pass as journal-error;
  695/696/698 - a cancelled script load is a transport-class death and the
                supervisor recovers it from the recorded error_type.
"""
import unittest
from unittest.mock import MagicMock

import cloud_database
import search_city as city
import assistant_guided_chain as guided
from assistant_failure import category
from mumu_recovery import NATIVE_ERROR_CLASSES, recoverable
from test_search_city import ready_city
from test_inbox_profiles import Base, nav, msg, snap
import test_guided_chain as guide


def transient(code='cloud-database-unavailable', operation='read'):
    error = cloud_database.CloudDatabaseError(code)
    error.operation = operation
    return error


class CityQueryBudget(unittest.TestCase):
    def test_retry_arm_covers_the_whole_query_city_phase(self):
        source = city.build('Псков')
        # The committed-only clause is gone: the monitors 700/701/702 shapes
        # (cityTextCommitted false, setter never invoked) retried nothing.
        self.assertIn("(n.phase==='query-city')", source)
        self.assertNotIn("(n.phase==='query-city'&&state.cityTextCommitted)", source)
        # The mutation doctrine is untouched: the guard still refuses any tick
        # whose mutating invoke actually ran.
        self.assertIn("if(e==='frame-budget'&&!cityFrameMutated&&(", source)
        self.assertIn("&&n.city_read_budget_retries<4)", source)

    def test_setter_bookkeeping_rides_after_the_invoke(self):
        source = city.build('Псков')
        line = "if(!state.cityTextCommitted){cityTransition(s.cityTextSet,input,cityArgs([text]));n.city_query_attempted=true;n.city_queries_started++;state.cityTextCommitted=true;n.city_query_text_completed=true;n.city_query_text_returns++;return;}"
        self.assertIn(line, source)
        # The old form counted a pre-invoke-rejected setter as a started query,
        # which made every retry trip 'Unreturned city query was repeated'.
        self.assertNotIn("{n.city_query_attempted=true;n.city_queries_started++;cityTransition(", source)

    def test_bounded_death_with_zero_setter_invocations_is_a_valid_report(self):
        # The mode-354 stop shape: four observation retries burned, the text
        # setter never invoked, nothing mutated, checkpoint still 'query'.
        sample = ready_city()
        n = sample['navigation']
        n.update(stage='navigation-stopped', error='frame-budget', phase='query-city',
                 city_checkpoint='query', city_verified=False, city_result_verified=False,
                 city_select_attempted=False, city_select_completed=False, city_form_verified=False,
                 city_query_attempted=False, city_query_text_completed=False, city_query_completed=False,
                 city_queries_started=0, city_query_text_returns=0, city_query_returns=0,
                 city_scan_samples=0, city_matches=0, city_visible_rows=0, city_total_rows=0,
                 city_read_budget_retries=4, city_selected_name=None, online_verified=False,
                 return_verified=False, ui_text_read=False, open_completed=True,
                 apply_attempted=False, apply_completed=False, cancel_attempted=False, cancel_completed=False)
        city.validate(sample)
        # One retry short of the bound rides instead - the monitors' shape.
        n['city_read_budget_retries'] = 1
        city.validate(sample)


class TransientJournalDeferral(unittest.TestCase):
    def test_predicate_only_defers_transient_read_side_failures(self):
        self.assertEqual(guided.transient_journal_deferral(transient(), {}),
                         dict(code='cloud-database-unavailable', operation='read', automatic_retry=False))
        self.assertEqual(guided.transient_journal_deferral(transient('cloud-database-capacity', 'catalog'), {}),
                         dict(code='cloud-database-capacity', operation='catalog', automatic_retry=False))
        for bad in (transient(operation='write'), transient(operation='commit'),
                    transient(operation='lock'), transient(operation='connect'),
                    transient(code='cloud-database-lock-timeout'),
                    transient(code='cloud-database-permission'),
                    RuntimeError('PRIVATE'), ValueError('Invalid journal targets')):
            self.assertIsNone(guided.transient_journal_deferral(bad, {}), bad)

    def test_no_send_in_flight_is_required_for_the_deferral(self):
        error = transient()
        for diagnostics in ({'submission_attempted': True},
                            {'submission_returned': True},
                            {'submission_attempted': True, 'submission_returned': False}):
            self.assertIsNone(guided.transient_journal_deferral(error, diagnostics), diagnostics)
        self.assertIsNotNone(guided.transient_journal_deferral(error, {'submission_attempted': False}))
        self.assertIsNotNone(guided.transient_journal_deferral(error, {}))


class ChainDeferral(guide.WholeChain):
    def test_transient_read_defers_the_chat_without_stopping_it(self):
        # Monitor 703's shape: the failure rides a journal read performed
        # while binding the freshly read chat (inside the guarded chain body,
        # after the screen read, before any send could exist).
        self.chain.bind = MagicMock(side_effect=transient())
        out = self.walk(until_waiting=True)
        self.assertEqual(out['status'], 'chain-waiting')
        self.assertEqual(out['reason'], 'cloud-journal-transient')
        self.assertEqual(out['diagnostics']['failure_point'], 'cloud-journal-transient')
        self.assertEqual(out['diagnostics']['database'],
                         dict(code='cloud-database-unavailable', operation='read', automatic_retry=False))
        self.assertFalse(self.sent)

    def test_write_side_failure_keeps_the_hard_stop(self):
        self.chain.bind = MagicMock(side_effect=transient(operation='write'))
        out = self.walk(until_waiting=True)
        self.assertEqual(out['status'], 'chain-stopped')
        self.assertEqual(out['reason'], 'binding-or-history-check-stopped')
        self.assertEqual(out['diagnostics']['host_failure'], 'journal-error')
        self.assertEqual(out['diagnostics']['database'],
                         dict(code='cloud-database-unavailable', operation='write', automatic_retry=False))
        self.assertFalse(self.sent)


class InboxDeferral(Base):
    def test_transient_cloud_read_defers_chat_and_pass_continues(self):
        self.journal()
        error = transient()
        chain = self.chain()
        # The failure rides a journal read performed while binding the chat -
        # after the screen read, before any send could exist.
        chain.bind = MagicMock(side_effect=error)
        out = self.walk([nav('opened', guide.WHO), nav('returned', guide.WHO), nav('search-ready')],
                        [snap(msg(1002, 'Привет'))], chain=chain)
        self.assertEqual(out['status'], 'inbox-completed')
        self.assertEqual(out['history_deferred'], 1)
        self.assertEqual(out['outcomes'], {'chain-waiting:cloud-journal-transient': 1})
        self.assertEqual(out['last_chat_diagnostics']['failure_point'], 'cloud-journal-transient')
        self.assertEqual(out['last_chat_diagnostics']['database'],
                         dict(code='cloud-database-unavailable', operation='read', automatic_retry=False))
        self.assertFalse(self.sent)


class StartupCancelledRecovery(unittest.TestCase):
    def navigation_failure(self, error_type):
        return dict(stage='script-load', error='startup-script-load-failed', error_type=error_type)

    def test_cancelled_script_load_is_recoverable(self):
        # The exact 695/696/698 report shape: three ports died dead at startup
        # because the raw stage code matched neither set.
        report = dict(status='stopped', reason='dialog-list-not-verified',
                      last_navigation_failure=self.navigation_failure('OperationCancelledError'))
        self.assertTrue(recoverable(report))

    def test_transport_classes_recover_and_others_stay_dead(self):
        for name in ('TransportError', 'ServerNotRunningError', 'ProtocolError',
                     'TimedOutError', 'OperationCancelledError', 'RPCException',
                     'ProcessNotFoundError', 'InvalidOperationError'):
            report = dict(status='stopped', reason='dialog-list-not-verified',
                          last_navigation_failure=self.navigation_failure(name))
            self.assertTrue(recoverable(report), name)
        for name in ('TestError', 'OtherError', 'CloudDatabaseError', 'StateError', 'ValueError'):
            report = dict(status='stopped', reason='dialog-list-not-verified',
                          last_navigation_failure=self.navigation_failure(name))
            self.assertFalse(recoverable(report), name)

    def test_journal_block_still_wins_over_transport_class_evidence(self):
        report = dict(status='stopped', reason='inbox-pass-stopped',
                      last_pass=dict(status='inbox-stopped', host_failure='journal-corrupt',
                                     last_navigation_failure=self.navigation_failure('OperationCancelledError')))
        self.assertFalse(recoverable(report))

    def test_mapping_is_pinned_to_the_failure_layer_table(self):
        for name, code in NATIVE_ERROR_CLASSES.items():
            error = type(name, (Exception,), {})('PRIVATE raw output')
            error._dvk_failure = self.navigation_failure(name)
            self.assertEqual(category(error), code, name)


if __name__ == '__main__':
    unittest.main()
