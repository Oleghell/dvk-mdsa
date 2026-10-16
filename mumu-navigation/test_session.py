"""Explicit finite test runs plus permanent, conservative visual duplicate history.

No device access, reset API, background jobs, names, messages or images. Legacy
attempts are imported read-only and are never reclassified as successful sends.
"""
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import uuid

class SessionError(RuntimeError):
    pass

TERMINAL_VISITS = ('returned_sent', 'returned_skipped')

class TestSession:
    __test__ = False

    def __init__(self, path, legacy_path=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, target INTEGER NOT NULL CHECK(target BETWEEN 1 AND 5),
            state TEXT NOT NULL CHECK(state IN ('active','completed','stopped')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
          CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(state) WHERE state='active';
          CREATE TABLE IF NOT EXISTS visits (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            ordinal INTEGER NOT NULL, state TEXT NOT NULL,
            fingerprint TEXT, variant INTEGER, input_attempted INTEGER NOT NULL DEFAULT 0,
            send_attempted INTEGER NOT NULL DEFAULT 0, observed_sent INTEGER NOT NULL DEFAULT 0,
            UNIQUE(run_id,ordinal));
          CREATE TABLE IF NOT EXISTS contacts (
            fingerprint TEXT PRIMARY KEY, source TEXT NOT NULL, state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS holds (reason TEXT PRIMARY KEY);
          CREATE TABLE IF NOT EXISTS control_actions (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL CHECK(state IN ('reserved','succeeded','refused','unknown')));
          CREATE TABLE IF NOT EXISTS control_config (key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS city_focus_actions (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            point_index INTEGER NOT NULL CHECK(point_index BETWEEN 0 AND 2),
            state TEXT NOT NULL CHECK(state IN ('reserved','injected','focused','no_focus','refused','unknown')),
            UNIQUE(run_id,point_index));
          CREATE TABLE IF NOT EXISTS city_actions (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            city_index INTEGER NOT NULL CHECK(city_index BETWEEN 0 AND 29),
            previous_index INTEGER NOT NULL CHECK(previous_index BETWEEN -1 AND 29),
            state TEXT NOT NULL CHECK(state IN ('reserved','verified','refused','unknown')),
            UNIQUE(run_id,city_index));
        ''')
        try:
            if legacy_path is not None and Path(legacy_path).exists():
                self._import_legacy(Path(legacy_path))
            with self.transaction():
                pending = self.db.execute("SELECT run_id FROM visits WHERE state IN ('input_reserved','finish_reserved','send_reserved','awaiting_send_review')").fetchall()
                pending += self.db.execute("SELECT run_id FROM city_actions WHERE state='reserved'").fetchall()
                pending += self.db.execute("SELECT run_id FROM city_focus_actions WHERE state='reserved'").fetchall()
                for row in pending:
                    self._hold(row['run_id'])
                if self.db.execute("SELECT 1 FROM control_actions WHERE state='reserved'").fetchone():
                    self.db.execute("INSERT OR IGNORE INTO holds VALUES ('unknown_device_action')")
                    self.db.execute("UPDATE runs SET state='stopped' WHERE state='active'")
        except BaseException:
            self.db.close()
            raise

    @staticmethod
    def fingerprint(value):
        if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
            raise SessionError('Invalid visual fingerprint')
        return value

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _import_legacy(self, path):
        # Do not create/modify a legacy file, its schema or its old budget.
        old = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            if old.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise SessionError('Legacy journal failed integrity check')
            rows = old.execute('SELECT fingerprint,state FROM attempts').fetchall()
        except sqlite3.Error:
            raise SessionError('Cannot safely read legacy journal; preserve it for review') from None
        finally:
            old.close()
        with self.transaction():
            for fingerprint, state in rows:
                self.fingerprint(fingerprint)
                if state not in ('reserved', 'unknown', 'draft_verified', 'refused'):
                    raise SessionError('Unknown legacy state; manual review required')
                self.db.execute('INSERT OR IGNORE INTO contacts VALUES (?,?,?)',
                                (fingerprint, 'legacy-v1', state))
                if state in ('reserved', 'unknown'):
                    self.db.execute("INSERT OR IGNORE INTO holds VALUES ('legacy_unknown')")

    def _active(self):
        run = self.db.execute("SELECT * FROM runs WHERE state='active'").fetchone()
        if run is None:
            raise SessionError('No active test. Start or resume it locally in the GUI.')
        return run

    def _no_hold(self):
        if self.db.execute('SELECT 1 FROM holds LIMIT 1').fetchone():
            raise SessionError('Unknown previous outcome. Test stopped; manual review required.')

    def current(self):
        run = self._active()
        return self.db.execute('SELECT * FROM visits WHERE run_id=? ORDER BY ordinal DESC LIMIT 1',
                               (run['id'],)).fetchone()

    def _visit(self, states):
        self._no_hold()
        visit = self.current()
        if visit is None or visit['state'] not in states:
            raise SessionError('Unsupported test step. Read status; do not repeat actions.')
        return visit

    def start(self, target):
        if type(target) is not int or not 1 <= target <= 5:
            raise SessionError('Test target must be between 1 and 5 visited profiles')
        with self.transaction():
            self._no_hold()
            if self.db.execute("SELECT 1 FROM runs WHERE state='active'").fetchone():
                raise SessionError('Resume the existing test; a restart does not reset it')
            ident = uuid.uuid4().hex
            self.db.execute('INSERT INTO runs(id,target,state) VALUES (?,?,?)', (ident, target, 'active'))
        return self.status()

    def begin_visit(self):
        # Commit BEFORE touching the device. Refused taps also consume a visit.
        with self.transaction():
            self._no_hold()
            run = self._active()
            previous = self.current()
            if previous is not None and previous['state'] not in TERMINAL_VISITS:
                raise SessionError('Finish the current profile before opening another')
            n = self.db.execute('SELECT COUNT(*) FROM visits WHERE run_id=?', (run['id'],)).fetchone()[0]
            if n >= run['target']:
                raise SessionError('Visited-profile limit reached')
            ident = uuid.uuid4().hex
            self.db.execute('INSERT INTO visits(id,run_id,ordinal,state) VALUES (?,?,?,?)',
                            (ident, run['id'], n + 1, 'opening'))
        return ident

    def transition(self, before, after):
        with self.transaction():
            visit = self._visit(before)
            self.db.execute('UPDATE visits SET state=? WHERE id=?', (after, visit['id']))

    def bind_empty_chat(self, fingerprint):
        self.fingerprint(fingerprint)
        with self.transaction():
            visit = self._visit(('chat_opening',))
            duplicate = self.db.execute('SELECT 1 FROM contacts WHERE fingerprint=?', (fingerprint,)).fetchone()
            # Historical visual matches are always skipped, even refused old input.
            state = 'skip_ready' if duplicate else 'empty_checked'
            self.db.execute('UPDATE visits SET fingerprint=?,state=? WHERE id=?',
                            (fingerprint, state, visit['id']))
        return not bool(duplicate)

    def reserve_input(self, fingerprint, variant):
        self.fingerprint(fingerprint)
        if type(variant) is not int or not 0 <= variant < 10:
            raise SessionError('Only the ten approved greeting variants are allowed')
        with self.transaction():
            visit = self._visit(('empty_checked',))
            if fingerprint != visit['fingerprint']:
                raise SessionError('Chat header changed')
            if self.db.execute('SELECT 1 FROM contacts WHERE fingerprint=?', (fingerprint,)).fetchone():
                raise SessionError('Visual duplicate: no repeated input')
            self.db.execute('INSERT INTO contacts VALUES (?,?,?)', (fingerprint, 'test-v2', 'input_reserved'))
            self.db.execute("UPDATE visits SET state='input_reserved',variant=?,input_attempted=1 WHERE id=?",
                            (variant, visit['id']))

    def finish_input(self, fingerprint, result):
        if result not in ('draft_verified', 'refused', 'unknown'):
            raise SessionError('Invalid input result')
        with self.transaction():
            visit = self._visit(('input_reserved',))
            if visit['fingerprint'] != fingerprint:
                raise SessionError('Input result belongs to another profile')
            state = {'draft_verified':'draft_native', 'refused':'skip_ready', 'unknown':'unknown'}[result]
            self.db.execute('UPDATE visits SET state=? WHERE id=?', (state, visit['id']))
            self.db.execute('UPDATE contacts SET state=? WHERE fingerprint=?', (state, fingerprint))
            if result == 'unknown':
                self._hold(visit['run_id'])

    def reserve_send(self):
        with self.transaction():
            visit = self._visit(('draft_finished',))
            self.db.execute("UPDATE visits SET state='send_reserved',send_attempted=1 WHERE id=?", (visit['id'],))
            self.db.execute("UPDATE contacts SET state='send_reserved' WHERE fingerprint=?", (visit['fingerprint'],))

    def send_injected(self):
        self.transition(('send_reserved',), 'awaiting_send_review')

    def observe_sent(self):
        # Explicit agent/operator observation, not autonomous semantic recognition.
        with self.transaction():
            visit = self._visit(('awaiting_send_review',))
            self.db.execute("UPDATE visits SET state='sent_observed',observed_sent=1 WHERE id=?", (visit['id'],))
            self.db.execute("UPDATE contacts SET state='sent_observed' WHERE fingerprint=?", (visit['fingerprint'],))

    def skip(self):
        self.transition(('opening', 'chat_opening', 'empty_checked', 'skip_ready'), 'skip_ready')

    def returned(self):
        with self.transaction():
            visit = self._visit(('sent_observed', 'skip_ready'))
            state = 'returned_sent' if visit['state'] == 'sent_observed' else 'returned_skipped'
            self.db.execute('UPDATE visits SET state=? WHERE id=?', (state, visit['id']))
            run = self._active()
            n = self.db.execute('SELECT COUNT(*) FROM visits WHERE run_id=?', (run['id'],)).fetchone()[0]
            if n >= run['target']:
                self.db.execute("UPDATE runs SET state='completed' WHERE id=?", (run['id'],))

    def _hold(self, run_id):
        self.db.execute("INSERT OR IGNORE INTO holds VALUES ('unknown_device_action')")
        self.db.execute("UPDATE runs SET state='stopped' WHERE id=?", (run_id,))

    def unknown(self):
        with self.transaction():
            run = self._active()
            visit = self.current()
            if visit:
                self.db.execute("UPDATE visits SET state='unknown' WHERE id=?", (visit['id'],))
            self._hold(run['id'])

    def status(self):
        run = self.db.execute('SELECT * FROM runs ORDER BY rowid DESC LIMIT 1').fetchone()
        held = bool(self.db.execute('SELECT 1 FROM holds LIMIT 1').fetchone())
        out = {'run_id': None, 'state':'not_started', 'target':None, 'visited':0,
               'input_attempts':0, 'send_attempts':0, 'sent_observed_by_agent':0,
               'skipped':0, 'remaining':0, 'current_step':None, 'manual_review_required':held,
               'identity_guard':'visual fingerprint only; not a stable account ID',
               'automatic_sender':False}
        if run is not None:
            rows = self.db.execute('SELECT * FROM visits WHERE run_id=? ORDER BY ordinal', (run['id'],)).fetchall()
            out.update(run_id=run['id'], state=run['state'], target=run['target'], visited=len(rows),
                       remaining=max(0, run['target']-len(rows)),
                       input_attempts=sum(r['input_attempted'] for r in rows),
                       send_attempts=sum(r['send_attempted'] for r in rows),
                       sent_observed_by_agent=sum(r['observed_sent'] for r in rows),
                       skipped=sum(r['state']=='returned_skipped' for r in rows),
                       current_step=rows[-1]['state'] if rows else None)
        return out

    def check_city_focus_ready(self):
        self._no_hold();run=self._active();visit=self.current()
        if visit is not None and visit['state'] not in TERMINAL_VISITS:
            raise SessionError('City focus only between visits')
        for table in ('city_actions','city_focus_actions'):
            if self.db.execute("SELECT 1 FROM "+table+" WHERE run_id=? AND state='reserved'",(run['id'],)).fetchone():
                raise SessionError('A city action is pending; no second dispatch')
        return run

    def city_focus_points_used(self):
        run=self.check_city_focus_ready()
        return [r[0] for r in self.db.execute('SELECT point_index FROM city_focus_actions WHERE run_id=?',(run['id'],))]

    def reserve_city_focus(self,point_index):
        if type(point_index) is not int or not 0<=point_index<3:raise SessionError('Only three compiled focus points')
        with self.transaction():
            run=self.check_city_focus_ready()
            if self.db.execute("SELECT 1 FROM city_focus_actions WHERE run_id=? AND state='refused'",(run['id'],)).fetchone():
                raise SessionError('A focus tap was refused; no fallback in this run')
            if self.db.execute('SELECT 1 FROM city_focus_actions WHERE run_id=? AND point_index=?',(run['id'],point_index)).fetchone():
                raise SessionError('Focus point already attempted; no repeat')
            action=uuid.uuid4().hex
            self.db.execute('INSERT INTO city_focus_actions VALUES (?,?,?,?)',(action,run['id'],point_index,'reserved'))
            return action

    def finish_city_focus(self,action,outcome):
        if outcome not in ('injected','focused','no_focus','refused','unknown'):raise SessionError('Invalid focus outcome')
        with self.transaction():
            row=self.db.execute("SELECT * FROM city_focus_actions WHERE id=? AND state='reserved'",(action,)).fetchone()
            if row is None:raise SessionError('No pending focus action; no replay')
            self.db.execute('UPDATE city_focus_actions SET state=? WHERE id=?',(outcome,action))
            if outcome=='unknown':self._hold(row['run_id'])

    def reserve_city_input(self, city_index, previous_index):
        if (type(city_index) is not int or not 0 <= city_index < 30
                or type(previous_index) is not int or not -1 <= previous_index < 30
                or city_index == previous_index):
            raise SessionError('Invalid city-v1 catalog indices')
        with self.transaction():
            self._no_hold();run=self._active();visit=self.current()
            if visit is not None and visit['state'] not in TERMINAL_VISITS:
                raise SessionError('City input only between visits')
            if self.db.execute("SELECT 1 FROM city_actions WHERE run_id=? AND state='reserved'",(run['id'],)).fetchone():
                raise SessionError('A city input is pending; no second dispatch')
            if self.db.execute("SELECT 1 FROM city_focus_actions WHERE run_id=? AND state='reserved'",(run['id'],)).fetchone():
                raise SessionError('A focus action is pending; no city input')
            n=self.db.execute('SELECT COUNT(*) FROM city_actions WHERE run_id=?',(run['id'],)).fetchone()[0]
            if n>=5:raise SessionError('Five city input attempts already used; do not reset')
            if self.db.execute('SELECT 1 FROM city_actions WHERE run_id=? AND city_index=?',(run['id'],city_index)).fetchone():
                raise SessionError('This city already attempted in this run; no retry')
            action=uuid.uuid4().hex
            self.db.execute('INSERT INTO city_actions VALUES (?,?,?,?,?)',(action,run['id'],city_index,previous_index,'reserved'))
            return action

    def finish_city_input(self, action, outcome):
        if outcome not in ('verified','refused','unknown'):raise SessionError('Invalid city outcome')
        with self.transaction():
            row=self.db.execute("SELECT * FROM city_actions WHERE id=? AND state='reserved'",(action,)).fetchone()
            if row is None:raise SessionError('No pending city input; do not replay')
            self.db.execute('UPDATE city_actions SET state=? WHERE id=?',(outcome,action))
            if outcome=='unknown':self._hold(row['run_id'])

    def used(self):
        return self.status()['input_attempts']

    def close(self):
        self.db.close()
