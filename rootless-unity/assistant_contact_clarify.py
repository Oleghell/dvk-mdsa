"""One optional clarification after a peer explicitly chooses a messenger."""
import re
from assistant_contact_intent import TG, WA, MAX
TEXT = 'Хорошо, напиши номер для WhatsApp или ник в Telegram, если тебе удобно.'
PLATFORM = re.compile(r'\b(?:'+TG+'|'+WA+r')\b', re.I)
CHOICE = re.compile(r'\b(?:давай(?:те)?|лучше|удобн\w*|предпочитаю|соглас\w*|напиши|пиши|найди|хочу|можно|есть|установлен[ао]?|пользуюсь)\b', re.I)
NEGATIVE = re.compile(r'не\s+(?:хочу|надо|могу|пользуюсь|работает)|не\s*пиши|не\s*да[мю]', re.I)
# Reports 9104352d port 5571 (v1.3.104): the clause-level app list. A clause
# that is EXACTLY app names joined by «или»/«и»/comma («Мах или вотсап»,
# «вотсап, телега») is a terse choice in EITHER order; the MAX spellings
# (мах/мак) join the list so the mirrored order stays a choice too. The
# whole-message fullmatch below keeps its former semantics verbatim.
APPS = r'(?:'+MAX+r'|'+TG+r'|whats\s?app|'+WA+r')'
APP_LIST = re.compile(r'(?:\s*,?\s*(?:или|и)\s+'+APPS+r')*', re.I)
# A clause that only reports a platform ABSENCE («Телеги нет, стёрла»,
# «телегу удалила», «ватсапа нет») may precede the terse choice; it names
# the app plus an absence verb and never contains a question.
ABSENT = re.compile(r'\b(?:нет|нету|не\s+пользуюсь|не\s+установлен\w*|ст[её]рл\w*|ст[её]рла|удалил\w*|удал[её]н\w*|сломал\w*|не\s+работает)\b', re.I)

def chosen(messages):
    if max_selected(messages):return True
    from assistant_contact_intent import available_alternative
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str)]
    value=' / '.join(texts)
    from shared_contact import contact_items
    if any(contact_items(text,allow_unformatted=True) for text in texts):
        return False  # Do not ask for a contact already present but not safely self-attributed.
    if available_alternative(messages):return True
    if indifferent(messages):return True
    # A terse list is an explicit choice in this already-requested-contact stage.
    # Do not treat questions/objections mentioning an app as agreement.
    # Reports y8zZxWkA (v1.3.73): «Макс ватцап» names two apps without any verb;
    # the juxtaposition in EITHER order is a choice, so one clarification asks
    # for the number/nick instead of closing the chain.
    # Reports aPYyN7weMm (v1.3.78): the WhatsApp spelling family is shared with
    # assistant_contact_intent.WA so «вотсап»/«вотапп»-style replies behave the
    # same as «ватсап» here.
    from assistant_contact_intent import WA as _WA
    apps=r'(?:тг|телег[а-яё]*|telegram|whats\s?app|'+_WA+')'
    tail=(r'(?:[\s,/]+(?:или\s+)?(?:(?:макс|max|мах|мак)|'+apps+r'))*')
    short = (re.fullmatch(r'\s*'+apps+tail+r'[.!)]*\s*', value, re.I)
             or re.fullmatch(r'\s*(?:макс|max|мах|мак)'+tail+r'[.!)]*\s*', value, re.I))
    # v1.3.104: the terse list may be ONE CLAUSE of a longer reply whose other
    # clauses only report platform absence («Телеги нет, стёрла. Мах или
    # вотсап»). Every non-list clause must be such an absence clause (an app
    # plus an absence verb, no question, no negated consent) for the message
    # to stay a choice; any off-topic clause keeps the old closed behavior.
    if not short:
        clauses=[clause.strip() for clause in re.split(r'[,;.!\n]+', value) if clause.strip()]
        lists=[clause for clause in clauses
               if re.fullmatch(r'\s*(?:'+APPS+r')'+APP_LIST.pattern+r'[.!)]*\s*', clause, re.I)]
        rest=[clause for clause in clauses if clause not in lists]
        short=bool(lists) and all(
            re.search(r'\b(?:'+APPS+r'|номер|контакт|мессенджер)\b', clause, re.I)
            and ABSENT.search(clause) and not re.search(r'[?？]', clause)
            for clause in rest)
    return bool(PLATFORM.search(value) and (CHOICE.search(value) or short) and not NEGATIVE.search(value))

MAX_TEXT = 'По какому номеру могу найти тебя в MAX, если тебе удобно?'
def max_selected(messages):
    from assistant_contact_intent import max_selected as detect
    return detect(messages)


NUMBER_TEXT = 'Тогда по какому номеру могу тебя найти в Telegram или WhatsApp?'
INDIFFERENT = re.compile(r'^(?:(?:да|мне)\s+)?(?:без\s+разницы|вс[её]\s+равно|не\s*важно|любой(?:\s+мессенджер)?|как\s+тебе\s+удобнее)[.!…,)\s]*$',re.I)


def indifferent(messages):
    from conversation_engine import normalized
    return any(INDIFFERENT.fullmatch(normalized(' '.join(line for line in m['text'].splitlines()
        if not line.lstrip().startswith('>')))) for m in messages if isinstance(m.get('text'),str))


def indifferent_selected(db, snapshot, new_ids=()):
    """Only new or exact durable contact-stage inputs, never old generic consent."""
    chat=snapshot['identity']['chat'];ids=set(new_ids)
    ids.update(r[0] for r in db.execute("SELECT trigger FROM chain_actions WHERE chat=? AND kind IN ('clarify','followup')",(chat,)))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_draft_inputs'").fetchone():
        ids.update(r[0] for r in db.execute("SELECT message FROM ai_draft_inputs WHERE chat=? AND kind IN ('clarify','followup')",(chat,)))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chain_followup_archive'").fetchone():
        import json
        for trigger,inputs in db.execute("SELECT trigger,inputs FROM chain_followup_archive WHERE chat=?",(chat,)):
            ids.add(trigger);values=json.loads(inputs)
            if type(values) is list:ids.update(x for x in values if type(x) is str)
    return indifferent([m for m in snapshot['messages'] if m['sender']==snapshot['identity']['peer'] and m['id'] in ids])

WHATSAPP_TEXT = 'По какому номеру могу найти тебя в WhatsApp, если тебе удобно?'
TELEGRAM_TEXT = 'Какой у тебя ник в Telegram, если тебе удобно поделиться?'

def alternative_text(messages):
    from assistant_contact_intent import available_alternative
    return {'whatsapp':WHATSAPP_TEXT,'telegram':TELEGRAM_TEXT}.get(available_alternative(messages))


def selected_alternative_text(db,snapshot,new_ids=()):
    """Current or exact journal-recorded contact inputs, not arbitrary old consent."""
    who=snapshot['identity'];ids=set(new_ids)
    ids.update(r[0] for r in db.execute("SELECT trigger FROM chain_actions WHERE chat=? AND kind IN ('clarify','followup')",(who['chat'],)))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_draft_inputs'").fetchone():
        ids.update(r[0] for r in db.execute("SELECT message FROM ai_draft_inputs WHERE chat=? AND kind IN ('clarify','followup')",(who['chat'],)))
    return alternative_text([m for m in snapshot['messages'] if m['sender']==who['peer'] and m['id'] in ids])
