"""One contextual response while waiting for contact; never assume consent."""
import re

WAIT = re.compile(r'\b(?:потом\s+напишу|позже\s+напишу|сейчас\s+(?:найду|пришлю|напишу)|подожди|погоди|минутку)\b', re.I)

TEXT = 'Можем пока пообщаться здесь, если тебе так удобнее.'

def eligible(messages):
    # Media-only or blank arrivals are not enough to fabricate a contextual reply.
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str) and m['text'].strip()]
    return bool(texts) and not WAIT.search(' / '.join(texts))
