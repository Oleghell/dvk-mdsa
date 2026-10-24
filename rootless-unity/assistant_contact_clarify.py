"""One optional clarification after a peer explicitly chooses a messenger."""
import re
TEXT = 'Хорошо, напиши номер для WhatsApp или ник в Telegram, если тебе удобно.'
PLATFORM = re.compile(r'\b(?:тг|телеграм(?:м)?(?:е|ом)?|телег[аеу]|telegram|whats\s?app|ва(?:тс|тц|ц|с)ап(?:е|ом)?|вотсап(?:е|ом)?)\b', re.I)
CHOICE = re.compile(r'\b(?:давай(?:те)?|лучше|удобн\w*|предпочитаю|соглас\w*|напиши|пиши|найди|хочу|можно|есть|установлен[ао]?|пользуюсь)\b', re.I)
NEGATIVE = re.compile(r'не\s+(?:хочу|надо|могу|пользуюсь|работает)|не\s*пиши|не\s*да[мю]', re.I)

def chosen(messages):
    if max_selected(messages):return True
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str)]
    value=' / '.join(texts)
    from shared_contact import contact_items
    if any(contact_items(text,allow_unformatted=True) for text in texts):
        return False  # Do not ask for a contact already present but not safely self-attributed.
    if indifferent(messages):return True
    # A terse list is an explicit choice in this already-requested-contact stage.
    # Do not treat questions/objections mentioning an app as agreement.
    short = re.fullmatch(r'\s*(?:тг|телеграм(?:м)?|телега|telegram|whats\s?app|ватсап|вацап|ватцап|вотсап)(?:[\s,/]+(?:или\s+)?(?:макс|max|тг|телеграм|whatsapp|ватсап|вацап))*[.!)]*\s*', value, re.I)
    return bool(PLATFORM.search(value) and (CHOICE.search(value) or short) and not NEGATIVE.search(value))

MAX_TEXT = 'По какому номеру могу найти тебя в MAX, если тебе удобно?'
MAX_CHOICE = re.compile(r'^(?:(?:я\s+(?:сижу|общаюсь|переписываюсь|пользуюсь)\s+только\s+(?:в\s+)?(?:макс(?:е|ом)?|max))|(?:у\s+меня\s+)?(?:работает\s+)?только\s+макс|(?:у\s+меня\s+)?(?:работает\s+)?только\s+max|(?:давай(?:те)?\s+)?(?:в\s+)?(?:макс(?:е)?|max))[.!\s)]*$',re.I)

def max_selected(messages):
    # Only an explicit app choice, never a person named Max, quote or question.
    from conversation_engine import normalized
    texts=[normalized(' '.join(line for line in m['text'].splitlines() if not line.lstrip().startswith('>')))
           for m in messages if isinstance(m.get('text'),str)]
    return any(MAX_CHOICE.fullmatch(t) for t in texts) and not any(
        re.search(r'(?:не\s+(?:работает|пользуюсь|хочу)|нет)\s+(?:макс\w*|max)|(?:макс\w*|max)\s+не\s+работает',t,re.I) for t in texts)


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
