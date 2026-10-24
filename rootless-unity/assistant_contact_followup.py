"""One contextual response while waiting for contact; never assume consent."""
import re

WAIT = re.compile(r'\b(?:потом\s+напишу|позже\s+напишу|сейчас\s+(?:найду|пришлю|напишу)|подожди|погоди|минутку)\b', re.I)

TEXT = 'Можем пока пообщаться здесь, если тебе так удобнее.'

def eligible(messages):
    # Media-only or blank arrivals are not enough to fabricate a contextual reply.
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str) and m['text'].strip()]
    return bool(texts) and not WAIT.search(' / '.join(texts))

# Explicit replies to a contact proposal. Questions about its purpose are NOT
# refusals. Bare location words require a verified contact-stage input below.
BARE_STAY = re.compile(r'^(?:тут|здесь|сдесь)[.!?,)\s]*$',re.I)

STAY = re.compile(r'^(?:(?:пиши(?:те)?|напиши(?:те)?|давай(?:те)?|лучше|можно|может(?:\s+и)?)\s+(?:(?:пока|просто)\s+)?(?:тут|здесь|сдесь)(?:\s+(?:пообщаемся|общаться|общаемся|пообщаться))?|(?:пообщаемся|общаемся)\s+(?:тут|здесь|сдесь))[.!?,)\s]*$',re.I)
# Explicit extended stay-here statements, not arbitrary mentions of "here".
# Keep the clause tails narrow: questions, negation and contact instructions
# must not become terminal preferences. Quoted lines are removed by refused().
EXTENDED_STAY = re.compile(
    r'^(?:(?:(?:первое\s+время|пока)\s+)?(?:хотелось\s+бы|хочу)\s+(?:пока\s+)?остаться\s+(?:тут|здесь|сдесь)'
    r'|мне\s+(?:удобнее|комфортнее|лучше)\s+(?:пока\s+)?(?:тут|здесь|сдесь)'
    r'|мне\s+(?:тут|здесь|сдесь)\s+(?:удобно|комфортно|лучше)\s+(?:общаться|переписываться)'
    r'|(?:давай(?:те)?\s+)?будем\s+(?:пока\s+)?(?:общаться|переписываться)\s+(?:тут|здесь|сдесь)'
    r'|(?:давай(?:те)?\s+)?(?:пока\s+)?(?:общаться|переписываться)\s+будем\s+(?:тут|здесь|сдесь))'
    r'(?:\s*,?\s*(?:пока\s+не\s+увижу\s+(?:человека|тебя)\s+(?:в\s*живую|лично)'
    r'|а\s+потом\s+(?:будет|будем)\s+видно))?[.!\s,)]*$',re.I)

NO_APPS = re.compile(r'^(?:(?:нет|нету)(?:\s+у\s+меня)?\s+(?:ни\s+того\s*,?\s+ни\s+другого|ничего)|ни\s+того\s*,?\s+ни\s+другого(?:\s+(?:нет|нету))?|(?:у\s+меня\s+)?(?:нет|нету|не\s+пользуюсь)(?:\s+ни)?\s+(?:телеграм\w*|telegram|тг|ватсап\w*|вацап\w*|whatsapp)(?:\s*(?:,|и|ни|или)\s*(?:телеграм\w*|telegram|тг|ватсап\w*|вацап\w*|whatsapp))*)[.!?,)\s]*$',re.I)

# App-specific unavailability is not refusal of a DIFFERENT supplied contact.
APP = r'(?:телеграм\w*|telegram|тг|ват\s?сап\w*|ватсап\w*|вацап\w*|whats\s?app)'
APP_UNAVAILABLE = re.compile(r'^(?:(?:у\s+меня\s+)?(?:нет|нету|не\s+пользуюсь)\s+'+APP+r'|'+APP+r'\s+(?:нет|нету|не\s+пользуюсь))[.!?,)\s]*$',re.I)


def refused(messages, *, requested=False, contact_shared=False, alternative_selected=False):
    from conversation_engine import normalized
    for m in messages:
        if not isinstance(m.get('text'),str):continue
        text=normalized(' '.join(line for line in m['text'].splitlines() if not line.lstrip().startswith('>')))
        if (NO_APPS.fullmatch(text) and not ((contact_shared or alternative_selected) and APP_UNAVAILABLE.fullmatch(text))) or (requested and (BARE_STAY.fullmatch(text) or STAY.fullmatch(text) or EXTENDED_STAY.fullmatch(text) or re.fullmatch(r'(?:ни\s*где|нигде)[.!?,)\s]*',text) or re.fullmatch(r'(?:нет|нету|не хочу|не надо)[.!?,)\s]*',text))):
            return True
    return False


def scoped_messages(db, snapshot, new_ids, *, requested):
    """Do not reinterpret an earlier bare 'here' as a later contact refusal.

    No chronology is inferred from native collection position or numeric IDs.
    Old bare preferences are eligible only when a durable contact-stage action
    or draft records that exact input; full history validation stays in consume.
    """
    from conversation_engine import normalized
    who=snapshot['identity']; eligible=set(new_ids)
    if requested:
        eligible.update(row[0] for row in db.execute(
            "SELECT trigger FROM chain_actions WHERE chat=? AND kind IN ('clarify','followup')",(who['chat'],)))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_draft_inputs'").fetchone():
            eligible.update(row[0] for row in db.execute(
                "SELECT message FROM ai_draft_inputs WHERE chat=? AND kind IN ('clarify','followup')",(who['chat'],)))
    if requested and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chain_followup_archive'").fetchone():
        import json
        for trigger,inputs in db.execute("SELECT trigger,inputs FROM chain_followup_archive WHERE chat=?",(who['chat'],)):
            eligible.add(trigger)
            values=json.loads(inputs)
            if type(values) is list:eligible.update(x for x in values if type(x) is str)
    result=[]
    for m in snapshot['messages']:
        if m['sender']!=who['peer']:continue
        text=normalized(' '.join(line for line in (m.get('text') or '').splitlines() if not line.lstrip().startswith('>')))
        if not BARE_STAY.fullmatch(text) or m['id'] in eligible:result.append(m)
    return result
