"""Report 351: startup inbox pass must not die on a scope without exit notices.

resume()/enqueue() read chain_exit_notices; only chain_exit_payloads was ever
ensured there. A device scope where no exit notification had fired yet (or whose
notices table was lost) aborted the whole run-inbox preparation: cloud 42P01
cloud-schema-missing / SQLite no-such-table. Synthetic only.
"""
import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock

import assistant_exit_queue as queue
from mumu_store import SharedStore
import assistant_guided_chain as guided
import test_guided_chain as f


def fresh_chain(folder, port=5565):
    store=SharedStore(Path(folder)/'db',Path(folder)/'old',device_port=port)
    chain=guided.GuidedChain(store,seal=lambda v:b'ENC'+v,unseal=lambda v:v[3:])
    chain.notification_dispatcher=Mock()
    chain.notification_dispatcher.exit_hint=Mock()
    return store,chain


class StartupResume(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def payloads_only(self,store):
        """Reproduce the shipped state of the broken ports: payloads, no notices."""
        store.ensure_tables(queue.DDL)
        with store.read_connection() as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(store.prefix+'chain_exit_payloads',)).fetchone())
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(store.prefix+'chain_exit_notices',)).fetchone())

    def test_resume_creates_missing_notices_table_instead_of_failing(self):
        store,chain=fresh_chain(self.temp.name)
        self.payloads_only(store)
        sender=Mock(return_value=True)
        queue.resume(chain,sender,None,lambda:False)  # must not raise
        with store.read_connection() as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(store.prefix+'chain_exit_notices',)).fetchone())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM '+store.prefix+'chain_exit_notices').fetchone()[0],0)
        chain.notification_dispatcher.exit_hint.assert_not_called()

    def test_resume_on_completely_fresh_scope_needs_no_prior_table(self):
        store,chain=fresh_chain(self.temp.name,port=5567)
        sender=Mock(return_value=True)
        queue.resume(chain,sender,None,lambda:False)  # must not raise
        with store.read_connection() as db:
            for table in ('chain_exit_payloads','chain_exit_notices'):
                self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(store.prefix+table,)).fetchone(),table)

    def test_enqueue_after_healed_resume_still_delivers_once(self):
        store,chain=fresh_chain(self.temp.name)
        self.payloads_only(store)
        sender=Mock(return_value=True)
        queue.resume(chain,sender,None,lambda:False)
        from assistant_exit_notify import notify_exit
        result=notify_exit(chain,f.WHO,dict(reason='send-outcome-unknown'),sender=sender)
        self.assertEqual(result['notification'],'queued');sender.assert_not_called()
        with store.read_connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_exit_notices').fetchone(),('queued',))

    def test_resume_still_replays_a_queued_row(self):
        store,chain=fresh_chain(self.temp.name)
        self.payloads_only(store)
        from assistant_exit_notify import notify_exit
        notify_exit(chain,f.WHO,dict(reason='send-outcome-unknown'),sender=Mock(return_value=True))
        chain.notification_dispatcher.exit_hint.reset_mock()
        sender=Mock(return_value=True)
        queue.resume(chain,sender,None,lambda:False)
        self.assertEqual(chain.notification_dispatcher.exit_hint.call_count,1)


if __name__=='__main__':unittest.main()
