"""One durable manual-send reservation. Unknown outcome never permits resending."""
import json
from one_chat_preview import CODE, QUESTION
from one_chat_send import checked,checked_diagnostic

STATES = {'reserved-unknown','not-invoked','handler-returned','attempted-unknown','outgoing-observed'}


class Actions:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS test_manual_send(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),status TEXT NOT NULL,baseline TEXT NOT NULL)''')

        self.db.execute('CREATE TABLE IF NOT EXISTS test_manual_send_diagnostic(singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload TEXT NOT NULL)')

    def diagnostic(self):
        row=self.db.execute('SELECT payload FROM test_manual_send_diagnostic WHERE singleton=1').fetchone()
        return checked_diagnostic(json.loads(row[0])) if row else None

    def state(self):
        row = self.db.execute('SELECT status FROM test_manual_send WHERE singleton=1').fetchone()
        if row is not None and row[0] not in STATES:
            raise ValueError('Invalid manual-send state')
        return row[0] if row else 'not-reserved'

    def records(self, snapshot):
        if snapshot['identity'] != self.store.bound():
            raise ValueError('Different owned chat')
        return {self.store._hash(m['id']):self.store._hash(m) for m in snapshot['messages']}

    def reserve(self, before):
        before = checked(before)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.state() != 'not-reserved':
                raise ValueError('One test-send limit already reserved; never reset or retry')
            records = self.records(before)
            old = dict(self.db.execute('SELECT message_key,fingerprint FROM test_seen'))
            preview = self.db.execute('SELECT code,snapshot_key FROM test_preview WHERE singleton=1').fetchone()
            digest = self.store._hash(sorted(records.items()))
            if records != old or preview != (CODE,digest):
                raise ValueError('No current authorized test draft')
            self.db.execute('INSERT INTO test_manual_send VALUES(1,?,?)',
                            ('reserved-unknown',json.dumps(records,sort_keys=True)))
            self.db.execute('DELETE FROM test_preview')
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def finish(self, result):
        if set(result) not in ({'attempted','handler_returned'},{'attempted','handler_returned','native_check'}) or any(type(result[k]) is not bool for k in ('attempted','handler_returned')) or (result['handler_returned'] and not result['attempted']):
            raise ValueError('Invalid manual submission result')
        diagnostic=checked_diagnostic(result['native_check']) if 'native_check' in result else None
        if diagnostic is not None:
            self.db.execute('INSERT OR REPLACE INTO test_manual_send_diagnostic VALUES(1,?)',(json.dumps(diagnostic,sort_keys=True),))
        state = 'handler-returned' if result['handler_returned'] else 'attempted-unknown' if result['attempted'] else 'not-invoked'
        self.db.execute('UPDATE test_manual_send SET status=? WHERE singleton=1 AND status=?',(state,'reserved-unknown'))
        return self.state()

    def observe(self, snapshot):
        state = self.state()
        if state in ('not-reserved','not-invoked','outgoing-observed'):
            return state
        records = self.records(snapshot)
        row = self.db.execute('SELECT baseline FROM test_manual_send WHERE singleton=1').fetchone()
        old = json.loads(row[0])
        if not isinstance(old,dict) or not old.keys() <= records.keys() or any(records[k] != v for k,v in old.items()):
            raise ValueError('Submission baseline changed')
        delta = [m for m in snapshot['messages'] if self.store._hash(m['id']) not in old]
        if len(delta)==1 and delta[0]['sender']==snapshot['identity']['account'] and delta[0]['text']==QUESTION:
            self.db.execute("UPDATE test_manual_send SET status='outgoing-observed' WHERE singleton=1")
            return 'outgoing-observed'
        return state


def report_fields(state):
    if state not in STATES | {'not-reserved'}:
        raise ValueError('Invalid manual-send report')
    # This is local outgoing observation, never proof the recipient received/read it.
    return dict(manual_send_state=state,manual_send_limit=1,
                send_reserved=state!='not-reserved',retry_allowed=False,
                outgoing_observed=state=='outgoing-observed',delivery_confirmed=False,
                messages_sent=0 if state in {'not-reserved','not-invoked'} else None,
                ui_actions_attempted=state not in {'not-reserved','not-invoked'},
                automatic_replies_available=False)
