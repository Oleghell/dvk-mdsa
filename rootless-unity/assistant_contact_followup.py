"""One contextual response while waiting for contact; never assume consent."""
import re

WAIT = re.compile(r'\b(?:потом\s+напишу|позже\s+напишу|сейчас\s+(?:найду|пришлю|напишу)|подожди|погоди|минутку)\b', re.I)

TEXT = 'Можем пока пообщаться здесь, если тебе так удобнее.'

def eligible(messages):
    # Media-only or blank arrivals are not enough to fabricate a contextual reply.
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str) and m['text'].strip()]
    return bool(texts) and not WAIT.search(' / '.join(texts))

# Explicit replies to a contact proposal. Questions about its purpose are NOT
# refusals; historical peer messages and quoted lines are never scanned here.
STAY = re.compile(r'^(?:(?:пиши(?:те)?|напиши(?:те)?|давай(?:те)?|лучше|можно|может(?:\s+и)?)\s+(?:(?:пока|просто)\s+)?(?:тут|здесь)(?:\s+(?:пообщаемся|общаться|общаемся|пообщаться))?|(?:пообщаемся|общаемся)\s+(?:тут|здесь))[.!?,)\s]*$',re.I)
NO_APPS = re.compile(r'^(?:(?:нет|нету)(?:\s+у\s+меня)?\s+(?:ни\s+того\s*,?\s+ни\s+другого|ничего)|ни\s+того\s*,?\s+ни\s+другого(?:\s+(?:нет|нету))?|(?:у\s+меня\s+)?(?:нет|нету|не\s+пользуюсь)(?:\s+ни)?\s+(?:телеграм\w*|telegram|тг|ватсап\w*|вацап\w*|whatsapp)(?:\s*(?:,|и|ни|или)\s*(?:телеграм\w*|telegram|тг|ватсап\w*|вацап\w*|whatsapp))*)[.!?,)\s]*$',re.I)


def refused(messages, *, requested=False):
    from conversation_engine import normalized
    for m in messages:
        if not isinstance(m.get('text'),str):continue
        text=normalized(' '.join(line for line in m['text'].splitlines() if not line.lstrip().startswith('>')))
        if NO_APPS.fullmatch(text) or (requested and (STAY.fullmatch(text) or re.fullmatch(r'(?:нет|нету|не хочу|не надо)[.!?,)\s]*',text))):
            return True
    return False
