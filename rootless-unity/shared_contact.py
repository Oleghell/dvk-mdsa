"""Conservative detection of explicitly self-shared contacts, not profile scraping.

A stand-alone contact requires a contact request or explicit messenger
invitation in the verified new peer packet. Otherwise ownership is required.
Unknown/third-party/quoted/negative cases never trigger forwarding.
"""
import re
from conversation_engine import contacts, HANDLE, TGLINK, PHONE, REFUSAL, normalized

OTHER = re.compile(r'\b(?:подруг\w*|друг[а-я]*|брат\w*|сестр\w*|мам\w*|пап\w*|коллег\w*|знаком\w*|чуж\w*|е[её]|его|их|твой|ваш|пример\w*|например|переслан\w*|forwarded|код\w*|парол\w*|заказ\w*|карт\w*|кошел\w*|сч[её]т\w*|банк\w*|бот\w*|канал\w*|групп\w*)\b', re.I)
OWNER = re.compile(r'\b(?:мой|моя|мо[её]|меня|пиши(?:те)?\s+мне|свяжись\s+со\s+мной)\b', re.I)
LABELS = re.compile(r'\b(?:телеграм\w*|телег[аеу]|тг|telegram|whatsapp|ватсап\w*|ватцап\w*|вацап\w*|макс(?:е|ом)?|max|телефон|номер|контакт|вот|держи|это|в|на|да|ага|можно)\b', re.I)
PUNCTUATION = re.compile(r'^[\s:;,!.()—\-🙂😊👍]*$')


def contact_items(text, *, allow_unformatted=False):
    """Only a contextual direct contact response may retain bare digits as supplied.

    Do not guess country codes or call such a candidate a validated phone number.
    Generic extraction/masking policy in conversation_engine remains unchanged.
    """
    found=contacts(text)
    if allow_unformatted:
        for m in PHONE.finditer(text):
            raw=m.group()
            if re.fullmatch(r'[0-9]{10,15}',raw) and not contacts(raw) and raw not in found:
                found.append(raw)
    return found[:4]


TG_LABEL = r'(?:тг|телеграм(?:м)?(?:е|у|ом)?|телег[аеу]|telegram)'
TG_HANDLE = r'@?([A-Za-z][A-Za-z0-9_]{4,31})'
TG_SEPARATOR = r'(?:\s*[:;,!.—-]\s*|\s+)'
BARE_TG = re.compile(r'^(?:'+TG_LABEL+TG_SEPARATOR+TG_HANDLE+r'|'+TG_HANDLE+TG_SEPARATOR+TG_LABEL+r')[.! ]*$',re.I)

def labelled_telegram(text):
    # Require a separate label AND handle. A messenger name alone (Telegram)
    # is not a contact, nor is an arbitrary Latin word/profile display name.
    match=BARE_TG.fullmatch(text.strip().replace('\\_', '_'))
    return ['@'+(match.group(1) or match.group(2))] if match else []

def voluntary_batch(messages):
    """An explicit messenger invitation makes standalone contacts self-shared.

    No ordering assumption. Refusals/third-party context apply to the entire NEW
    peer packet; it does not prove ANY outgoing action was sent or delivered.
    """
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str)]
    value=' / '.join(texts)
    if not value or REFUSAL.search(value) or OTHER.search(value):return False
    if any(c in value for c in ('\"','«','»','“','”','>','\x00')):return False
    if re.search(r'не\s+(?:мой|моя|мне|передавай|пересылай|делись)|никому',value,re.I):return False
    from assistant_contact_clarify import PLATFORM, CHOICE, NEGATIVE
    return bool(PLATFORM.search(value) and CHOICE.search(value) and not NEGATIVE.search(value))

def self_shared(text, *, requested=False):
    if not isinstance(text, str) or not text.strip() or len(text) > 2048:
        return []
    n = normalized(text)
    if (re.search(r'\b(?:не\s+(?:мой|моя|мо[её]|мне|я|пересылай|передавай|делись)|никому)\b', n) or REFUSAL.search(n) or OTHER.search(n) or '?' in n or '？' in n
            or any(c in n for c in ('"', '«', '»', '“', '”', '>', '\x00'))):
        return []
    explicit_owner = OWNER.search(n) and re.search(r'\b(?:мой|моя|мо[её])\s+(?:номер|телефон|контакт)\b', n)
    found = contact_items(text, allow_unformatted=requested is True or bool(explicit_owner))
    labelled = labelled_telegram(text) if requested is True else []
    if labelled and not found:
        return labelled
    if not found:
        return []
    # A handle/phone alone after the explicit request is a self-sharing action.
    remainder = PHONE.sub(lambda m: '' if contact_items(m.group(), allow_unformatted=requested is True or bool(explicit_owner)) else m.group(), HANDLE.sub('', TGLINK.sub('', text)))
    remainder = LABELS.sub('', normalized(remainder))
    if OWNER.search(n):
        own_remainder = OWNER.sub('', remainder)
        own_remainder = re.sub(r'\b(?:пиши(?:те)?|мне|найди|найти|для|связи|я|здесь|тут)\b', '', own_remainder)
        explicit = re.search(r'\b(?:мой|моя|мо[её])\s+(?:номер|телефон|контакт|тг|телеграм\w*|ватсап\w*|ватцап\w*|whatsapp)\b', n)
        return found if explicit or PUNCTUATION.fullmatch(own_remainder) else []
    return found if requested is True and PUNCTUATION.fullmatch(remainder) else []


def display_name(name):
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 128
            or any(ord(c) < 32 or 127 <= ord(c) < 160 or c in '\u2028\u2029' for c in name)):
        raise ValueError('Unverified display name')
    return name.strip()


def payload(name, items):
    name = display_name(name)
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 128
            or any(ord(c) < 32 or 127 <= ord(c) < 160 or c in '\u2028\u2029' for c in name)
            or not isinstance(items, list) or not 1 <= len(items) <= 4
            or any(not isinstance(c, str) or not 1 <= len(c) <= 64 for c in items)):
        raise ValueError('Unverified contact/name')
    # Only normalized forms produced by the detector, never arbitrary payloads.
    if any(contact_items(c, allow_unformatted=True) != [c] for c in items):
        raise ValueError('Invalid contact')
    return dict(name=name.strip(), contacts=items)
