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
    r'|(?:я\s+)?(?:общаюсь|переписываюсь)\s+(?:пока\s+)?(?:только\s+)?(?:тут|здесь|сдесь)'
    r'|(?:удобнее|удобно|комфортнее|комфортно)\s+мне\s+(?:тут|здесь|сдесь)(?:\s*\.\s*до\s+тех\s+пор\s+пока\s+не\s+сложит(?:ься|ся)\s+нормальное\s+общение\s*[-—]\s*я\s+соц\s*\.?\s*сети\s+не\s+раздаю)?'
    r'|мне\s+(?:удобнее|удобно|комфортнее|комфортно|лучше)\s+(?:(?:пока|только)\s+)?(?:тут|здесь|сдесь)(?:\s+(?:общаться|переписываться))?'
    r'|мне\s+(?:тут|здесь|сдесь)\s+(?:удобнее|удобно|комфортнее|комфортно|лучше)(?:\s+(?:общаться|переписываться))?'
    r'|(?:давай(?:те)?\s+)?будем\s+(?:пока\s+)?(?:общаться|переписываться)\s+(?:тут|здесь|сдесь)'
    r'|(?:давай(?:те)?\s+)?(?:пока\s+)?(?:общаться|переписываться)\s+будем\s+(?:тут|здесь|сдесь))'
    r'(?:\s*,?\s*(?:пока\s+не\s+увижу\s+(?:человека|тебя)\s+(?:в\s*живую|лично)'
    r'|а\s+потом\s+(?:будет|будем)\s+видно))?[.!…\s,)]*$',re.I)

BOTH_UNAVAILABLE = re.compile(r'^(?:и\s+то\s+и\s+то|оба(?:\s+мессенджера)?)\s+(?:не\s+работа(?:ет|ют)|работа(?:ет|ют)\s+не\s+очень)(?:[.!…\s]*(?:даже\s+с\s+впн))?[.!…\s]*$',re.I)

# Pronouns are meaningful only after an observed contact proposal.
NO_APPS_CONTEXT = re.compile(
    r'^(?:(?:нет|нету)\s+у\s+меня\s+их|у\s+меня\s+(?:их\s+)?(?:нет|нету)'
    r'|(?:у\s+меня\s+)?(?:ничего|ни\s+чего|не\s+чего)\s+из\s+этого\s+не\s+работает)'
    r'[.!…,)\s]*$', re.I)

# Reports aPYyN7weMm (v1.3.78): the WhatsApp spelling family is shared with
# assistant_contact_intent.WA so «вотсап»/«вотапп»-style unavailability and
# absence lists behave the same as «ватсап» here.
from assistant_contact_intent import WA as _WA_SPELLINGS
NO_APPS = re.compile(r'^(?:(?:нет|нету)(?:\s+у\s+меня)?\s+(?:ни\s+того\s*,?\s+ни\s+другого|ничего)|ни\s+того\s*,?\s+ни\s+другого(?:\s+(?:нет|нету))?|(?:у\s+меня\s+)?(?:нет|нету|не\s+пользуюсь)(?:\s+ни)?\s+(?:телеграм\w*|telegram|тг|'+_WA_SPELLINGS+r'|whatsapp)(?:\s*(?:,|и|ни|или)\s*(?:телеграм\w*|telegram|тг|'+_WA_SPELLINGS+r'|whatsapp))*)[.!?,)\s]*$',re.I)

# App-specific unavailability is not refusal of a DIFFERENT supplied contact.
APP = r'(?:телеграм\w*|telegram|тг|'+_WA_SPELLINGS+r'|whats\s?app)'
APP_UNAVAILABLE = re.compile(r'^(?:(?:у\s+меня\s+)?(?:нет|нету|не\s+пользуюсь)\s+'+APP+r'|'+APP+r'\s+(?:нет|нету|не\s+пользуюсь))[.!?,)\s]*$',re.I)


def refused(messages, *, requested=False, contact_shared=False, alternative_selected=False):
    from conversation_engine import normalized
    from assistant_contact_intent import stay_here,private_refusal,unavailable
    for m in messages:
        if not isinstance(m.get('text'),str):continue
        text=normalized(' '.join(line for line in m['text'].splitlines() if not line.lstrip().startswith('>')))
        if requested and (stay_here(text) or private_refusal(text) or (unavailable(text) and not (alternative_selected or contact_shared))):
            return True
        absence = NO_APPS.fullmatch(text) or (requested and (NO_APPS_CONTEXT.fullmatch(text) or BOTH_UNAVAILABLE.fullmatch(text)))
        preference = requested and (BARE_STAY.fullmatch(text) or STAY.fullmatch(text) or EXTENDED_STAY.fullmatch(text)
            or re.fullmatch(r'(?:ни\s*где|нигде)[.!?,)\s]*',text)
            or re.fullmatch(r'(?:нет|нету|не хочу|не надо)[.!?,)\s]*',text))
        if (absence and not (contact_shared or alternative_selected)) or preference:
            return True
    return False


def scoped_messages(db, snapshot, new_ids, *, requested):
    """Do not reinterpret earlier contextual answers as later contact refusals.

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
        # A pre-proposal 'нет', 'тут' or unavailable-app answer is not a
        # refusal to THIS request. Only current or durably recorded contact-stage
        # inputs may supply that context. Unambiguous stop/privacy preferences
        # remain eligible; existing terminal states and global bans never reset.
        contextual = (BARE_STAY.fullmatch(text) or NO_APPS_CONTEXT.fullmatch(text)
            or NO_APPS.fullmatch(text) or BOTH_UNAVAILABLE.fullmatch(text)
            or re.fullmatch(r'(?:нет|нету|не хочу|не надо|ни\s*где|нигде)[.!?,)\s]*',text))
        if not contextual or m['id'] in eligible:result.append(m)
    return result
