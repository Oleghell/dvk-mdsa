"""Conservative detection of explicitly self-shared contacts, not profile scraping.

A stand-alone contact requires a contact request or explicit messenger
invitation in the verified new peer packet. Otherwise ownership is required.
Unknown/third-party/quoted/negative cases never trigger forwarding.
"""
import re
from conversation_engine import contacts, HANDLE, TGLINK, PHONE, REFUSAL, normalized

OTHER = re.compile(r'\b(?:подруг\w*|друг[а-я]*|брат\w*|сестр\w*|мам\w*|пап\w*|коллег\w*|знаком\w*|чуж\w*|е[её]|его|их|твой|ваш|пример\w*|например|переслан\w*|forwarded|код\w*|парол\w*|заказ\w*|карт\w*|кошел\w*|сч[её]т\w*|банк\w*|бот\w*|канал\w*|групп\w*)\b', re.I)
OWNER = re.compile(r'\b(?:мой|моя|мо[её]|меня|пиши(?:те)?\s+мне|свяжись\s+со\s+мной)\b', re.I)
# Reports y8zZxWkA (v1.3.73): «У меня ватсап: 8964 697 47 28» was refused
# because the ownership remainder kept the preposition «у» of «у меня»;
# the detected phone then fell through to a premature chain closure. «у» and
# «есть» are pure filler words in this contact context and join the labels.
# Reports aPYyN7weMm (v1.3.78): «89116863602 вотсап», «8999614 7273 Ватсапп
# или Макс» and «Давай вотапп 89523991160» all left un-stripped remainder
# (a WhatsApp misspelling outside the old ватсап/ватцап/вацап list, the «или»
# conjunction joining two messenger names, and the «давай» consent filler)
# and the peer's own phone number was refused, closing the chain. The whole
# spelling family в[ао](тс|тц|ц|с|т|сс)ап* (вотсап, вотапп, ватапп, вассап,
# воцап, plus case endings) joins the labels, and «давай(те)»/«или» are
# stripped only AFTER a contact item was already found in the message.
# Reports 9104352d port 5567 (v1.3.91): «Вайцап» - the colloquial spelling
# with «й» - was outside the family too, so the peer's messenger CHOICE was
# unrecognized and the chain closed declined. The optional «й» after в[ао]
# now covers вайцап/войцап/вайсап exactly like the rest of the family.
WHATSAPP_FAMILY = r'в[ао]й?(?:тс|тц|ц|с|т|сс)?ап\w*'
LABELS = re.compile(r'\b(?:телеграм\w*|телег[аеу]|тг|telegram|whatsapp|'+WHATSAPP_FAMILY+r'|макс(?:е|ом)?|мак(?:е|ом)?|мах(?:е|ом)?|max|телефон|номер|контакт|вот|держи|это|в|на|да|ага|можно|у|есть|давай(?:те)?|или)\b', re.I)
PUNCTUATION = re.compile(r'^[\s:;,!.()—\-🙂😊👍]*$')


def contact_items(text, *, allow_unformatted=False):
    """Only a contextual direct response may accept digits with phone separators.

    Strip separators only; never guess a country code or claim phone validation.
    Generic extraction/masking policy in conversation_engine remains unchanged.
    """
    found=contacts(text)
    if allow_unformatted:
        for m in PHONE.finditer(text):
            raw=m.group()
            digits=re.sub(r'[ ()\-]', '', raw)
            if (re.fullmatch(r'[0-9]{10,15}',digits) and not contacts(raw)
                    and digits not in found):
                found.append(digits)
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

# Reports y8zZxWkA (v1.3.73): peers answer the contact request with a bare
# Latin word («Ptaha3112») meaning their Telegram name. A single Latin token
# as the WHOLE message is accepted only in a requested contact stage and only
# outside a closed stoplist of app names and ordinary English/romanized reply
# words; everything else keeps requiring an @, a t.me link or an app label.
BARE_HANDLE=re.compile(r'[A-Za-z][A-Za-z0-9_]{4,31}')
HANDLE_STOPWORDS=frozenset({
    'telegram','whatsapp','viber','skype','discord','instagram','facebook','snapchat','signal',
    'hello','thanks','sorry','please','maybe','never','later','photo','video','voice','phone',
    'friend','friends','welcome','goodbye','great','again','today','tonight','answer','question',
    'privet','spasibo','horosho','normalno','poka','kakdela'})

def bare_telegram_handle(text):
    """One Latin token as the entire message: the peer's Telegram username."""
    if not isinstance(text,str):return []
    token=text.strip().strip('.,!;:()').replace('\\_','_')
    if not BARE_HANDLE.fullmatch(token) or token.lower() in HANDLE_STOPWORDS:return []
    return ['@'+token]

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

def messenger_consent(n):
    """One clause names a messenger AND consents to it: the peer's own context.

    Reports 9104352d port 5567 (v1.3.91): «Ватсап можно 89241810009 толком
    без пошлости прошу вас» - the peer chose the messenger and attached her
    number with a polite condition. The leftover remainder («толком без
    пошлости прошу вас») refused her own number, so the chain closed declined
    with the contact lost. This is the single-text form of voluntary_batch:
    a clause carrying BOTH the platform and a consent word (never a negation
    anywhere in the message) attributes the digits found in the same message
    to the peer herself - the condition tail is her request about the future
    exchange, not a third-party marker. Refusals, third-party context, quotes
    and questions were already refused by self_shared's gates above; a
    negated platform («нет у меня ватсапа…») can never consent.
    """
    from assistant_contact_clarify import PLATFORM, CHOICE, NEGATIVE
    if NEGATIVE.search(n):
        return False
    return any(PLATFORM.search(clause) and CHOICE.search(clause)
               for clause in re.split(r'[,;.\n]+', n))


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
    if not labelled and requested is True:
        # «Ptaha3112» alone answers an explicit request: the peer's Telegram name.
        labelled = bare_telegram_handle(text)
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
        explicit = re.search(r'\b(?:мой|моя|мо[её])\s+(?:номер|телефон|контакт|тг|телеграм\w*|'+WHATSAPP_FAMILY+r'|whatsapp)\b', n)
        return found if explicit or PUNCTUATION.fullmatch(own_remainder) else []
    # v1.3.91: a bare handle/phone after the explicit request is a self-sharing
    # action, and so is a number attached to an explicit messenger consent in
    # the same message («Ватсап можно 89241810009 толком без пошлости прошу
    # вас») - the polite remainder is not a third-party attribution.
    return found if requested is True and (PUNCTUATION.fullmatch(remainder) or messenger_consent(n)) else []


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
