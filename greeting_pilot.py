"""Bounded greeting controller. No ADB, credentials, OCR or implicit device access.

An adapter must positively verify identity, loaded history and input/send state.
The existing fixed-draft MuMu bridge is deliberately NOT such an adapter.
"""
from dataclasses import dataclass
from pathlib import Path
import sqlite3

GREETINGS = (
    'Привет', 'Привет)', 'Привет))', 'Привет!', 'Привет 🙂',
    'Привет 😊', 'Привет 👋', 'Привет! 🙂', 'Приветик)', 'Привет-привет)',
)
PROFILE_LIMIT = 5


class StopPilot(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatEvidence:
    profile_id: str
    identity_verified: bool = False
    history_loaded: bool = False
    explicit_empty_conversation: bool = False
    has_messages: bool = True
    draft_empty: bool = False

    def permits_greeting(self, expected):
        return (self.profile_id == expected and self.identity_verified
                and self.history_loaded and self.explicit_empty_conversation
                and not self.has_messages and self.draft_empty)


@dataclass(frozen=True)
class PreparedDraft:
    profile_id: str
    text: str
    identity_verified: bool = False
    input_verified: bool = False
    send_control_verified: bool = False
    history_still_empty: bool = False

    def permits_send(self, profile_id, text):
        return (self.profile_id == profile_id and self.text == text
                and self.identity_verified and self.input_verified
                and self.send_control_verified and self.history_still_empty)


class Ledger:
    """One persistent five-profile pilot per file. No built-in reset or eviction.

    An attempted send is committed BEFORE dispatch. Unknown outcomes halt even
    after restart. Names, screenshots, messages and access tokens are not stored.
    """
    def __init__(self, path):
        self.db = sqlite3.connect(str(Path(path)), isolation_level=None)
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS visits ('
                        'identity TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL, '
                        'state TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def claim(self, identity):
        # Require opaque stable adapter-provided IDs; never substitute OCR names.
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise StopPilot('Unverified profile identifier')
        import hashlib
        key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute("SELECT 1 FROM meta WHERE key='stopped'").fetchone():
                raise StopPilot('Pilot stopped; inspect the outcome before further work')
            if self.db.execute("SELECT 1 FROM visits WHERE state='attempted'").fetchone():
                raise StopPilot('Uncertain previous send; no automatic retry')
            if self.db.execute('SELECT 1 FROM visits WHERE identity=?', (key,)).fetchone():
                self.db.execute('COMMIT')
                return None
            n = self.db.execute('SELECT COUNT(*) FROM visits').fetchone()[0]
            if n >= PROFILE_LIMIT:
                raise StopPilot('Five-profile limit reached, including skipped profiles')
            self.db.execute('INSERT INTO visits VALUES (?, ?, ?)', (key, n, 'visited'))
            self.db.execute('COMMIT')
            return key, n
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def transition(self, key, before, after):
        result = self.db.execute('UPDATE visits SET state=? WHERE identity=? AND state=?',
                                 (after, key, before))
        if result.rowcount != 1:
            raise StopPilot('Invalid or already consumed action')

    def stop(self):
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('stopped', '1')")

    def remaining(self):
        return max(0, PROFILE_LIMIT - self.db.execute('SELECT COUNT(*) FROM visits').fetchone()[0])

    def close(self):
        self.db.close()


def run_pilot(adapter, ledger):
    """Run only on an explicitly authorized, supported adapter.

    Adapter contract is in docs/GREETING_PILOT.md. No retries, timers, random
    delays, account switching, CAPTCHA bypass or background mass-send loop.
    """
    if getattr(adapter, 'authorized_five_profile_send', False) is not True:
        raise StopPilot('A live, explicitly authorized sending adapter is required')
    if ledger.remaining() == 0:
        return {'visited': 0, 'sent_verified': 0, 'skipped': 0, 'status': 'limit_reached'}
    report = {'visited': 0, 'sent_verified': 0, 'skipped': 0, 'status': 'completed'}
    try:
        adapter.open_search_from_home()  # Must preserve any unrelated draft.
        adapter.open_search_settings()
        if adapter.online_only_state() is False:
            adapter.set_online_only()
        if adapter.online_only_state() is not True:
            raise StopPilot('Online-only setting was not positively confirmed')
        adapter.confirm_search_settings()
        # Must return a finite snapshot, not an unbounded profile generator.
        profiles = adapter.visible_profile_ids()
        if not isinstance(profiles, (list, tuple)) or len(profiles) > 100:
            raise StopPilot('Expected a bounded visible profile snapshot')
        for profile_id in profiles:
            if ledger.remaining() == 0:
                break
            claimed = ledger.claim(profile_id)
            if claimed is None:
                continue
            key, ordinal = claimed
            report['visited'] += 1
            adapter.open_profile(profile_id)
            adapter.open_message_dialog()
            evidence = adapter.inspect_chat()
            if not isinstance(evidence, ChatEvidence) or not evidence.permits_greeting(profile_id):
                ledger.transition(key, 'visited', 'skipped')
                report['skipped'] += 1
                adapter.return_to_grid_preserving_draft()
                continue
            text = GREETINGS[ordinal % len(GREETINGS)]
            prepared = adapter.prepare_greeting_if_still_empty(profile_id, text)
            if not isinstance(prepared, PreparedDraft) or not prepared.permits_send(profile_id, text):
                raise StopPilot('Prepared draft/send target not verified; leave draft intact')
            ledger.transition(key, 'visited', 'attempted')
            # Contract: recheck recipient, history and exact draft atomically as
            # close to dispatch as the platform permits. Return True only after
            # an outgoing bubble with this text is observed for this recipient.
            if adapter.send_once_and_verify(profile_id, text) is not True:
                raise StopPilot('Send outcome unknown; no retry')
            ledger.transition(key, 'attempted', 'sent_verified')
            report['sent_verified'] += 1
            adapter.return_to_grid_preserving_draft()
    except BaseException:
        ledger.stop()
        raise
    return report
