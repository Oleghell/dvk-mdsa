"""One optional clarification after a peer explicitly chooses a messenger."""
import re
from assistant_contact_intent import TG, WA
TEXT = 'Хорошо, напиши номер для WhatsApp или ник в Telegram, если тебе удобно.'
PLATFORM = re.compile(r'\b(?:'+TG+'|'+WA+r')\b', re.I)
CHOICE = re.compile(r'\b(?:давай(?:те)?|лучше|удобн\w*|предпочитаю|соглас\w*|напиши|пиши|найди|хочу|можно|есть|установлен[ао]?|пользуюсь)\b', re.I)
NEGATIVE = re.compile(r'не\s+(?:хочу|надо|могу|пользуюсь|работает)|не\s*пиши|не\s*да[мю]', re.I)

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
    short = re.fullmatch(r'\s*(?:тг|телеграм(?:м)?|телега|telegram|whats\s?app|ватсап|вацап|ватцап|вотсап)(?:[\s,/]+(?:или\s+)?(?:макс|max|тг|телеграм|whatsapp|ватсап|вацап))*[.!)]*\s*', value, re.I)
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
