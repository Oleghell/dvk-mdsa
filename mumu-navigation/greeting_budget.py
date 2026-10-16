"""Persistent five-attempt safety budget. No text, screenshots or secrets stored."""
from pathlib import Path
import sqlite3

class BudgetError(RuntimeError):
    pass

class GreetingBudget:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path),isolation_level=None,check_same_thread=False)
        self.db.execute('PRAGMA busy_timeout=3000')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS attempts (fingerprint TEXT PRIMARY KEY, state TEXT NOT NULL)')
    def reserve(self, fingerprint):
        import re
        if not isinstance(fingerprint,str) or not re.fullmatch('[0-9a-f]{64}',fingerprint):raise BudgetError('Invalid visual fingerprint')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute("SELECT 1 FROM attempts WHERE state IN ('reserved','unknown')").fetchone():
                raise BudgetError('Previous input outcome is unknown; no new input or retry')
            if self.db.execute('SELECT 1 FROM attempts WHERE fingerprint=?',(fingerprint,)).fetchone():
                raise BudgetError('This visual header already consumed an attempt; no repeat')
            if self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]>=5:
                raise BudgetError('Five input attempts used; restarting does not reset the budget')
            self.db.execute('INSERT INTO attempts VALUES (?,?)',(fingerprint,'reserved'))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise
    def finish(self,fingerprint,state):
        if state not in ('draft_verified','refused','unknown'):raise BudgetError('Invalid input state')
        c=self.db.execute("UPDATE attempts SET state=? WHERE fingerprint=? AND state='reserved'",(state,fingerprint))
        if c.rowcount!=1:raise BudgetError('No matching reserved input')
    def used(self):return self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
    def close(self):self.db.close()
