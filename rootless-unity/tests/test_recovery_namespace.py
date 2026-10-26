"""Recovery ledgers are scoped by the existing device/installation adapter."""
from contextlib import closing
import sqlite3,tempfile,unittest
from pathlib import Path
from mumu_store import SharedStore
import assistant_unknown_reply as unknown
import assistant_selection_recovery as selection

class Scope(unittest.TestCase):
    def test_same_chat_on_two_devices_cannot_share_retry_or_recovery_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'assistant.sqlite3'
            a=SharedStore(path,Path(folder)/'old',device_port=5557)
            b=SharedStore(path,Path(folder)/'old',device_port=5559)
            for store in (a,b):store.ensure_tables(unknown.DDL,selection.DDL)
            with a.connection() as db:
                db.execute("INSERT INTO chain_unknown_reply_retries VALUES('300','contact','hash','unknown','trigger','reserved')")
                db.execute("INSERT INTO chain_selection_recovery(chat,status) VALUES('300','read-attempted')")
            with b.read_connection() as db:
                self.assertEqual(db.execute('SELECT chat FROM chain_unknown_reply_retries').fetchall(),[])
                self.assertEqual(db.execute('SELECT chat FROM chain_selection_recovery').fetchall(),[])
            with closing(sqlite3.connect(path)) as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn('m5557__chain_unknown_reply_retries',names)
            self.assertNotIn('chain_unknown_reply_retries',names)
