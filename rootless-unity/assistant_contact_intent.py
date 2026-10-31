"""Contact-stage lexical intents, not exact sentence templates or an AI verdict.

Only peer text supplied by the verified chain is eligible. No ordering is
inferred from collection positions. Explicit contradictory MAX denial wins.
"""
import re
from conversation_engine import normalized

MAX = r'(?:макс(?:а|е|ом)?|мак(?:а|е|ом)?|мах(?:а|е|ом)?|max)'
APP = re.compile(r'\b'+MAX+r'\b',re.I)
PERSON = re.compile(r'\b(?:зовут|имя|брат|друг|сын|муж|парень|коллега|сказал|сказала|знакомый|кошк\w*|кот)\b',re.I)


def visible(text):
    if not isinstance(text,str):return ''
    return normalized(' '.join(line for line in text.splitlines() if not line.lstrip().startswith('>')))


def words(text):
    # Emoji/punctuation separate words rather than gluing messenger + clause.
    return ' '.join(re.findall(r'[a-zа-яё0-9]+',text.lower().replace('ё','е')))


def max_selected(messages):
    positive=False
    other_available=any(re.search(r'\b(?:'+WA+r'|телеграм\w*|тг)\s+есть\b',words(visible(m.get('text')))) for m in messages)
    for m in messages:
        text=visible(m.get('text'))
        if not APP.search(text):continue
        for clause in re.split(r'[,;.!\n]+',text):
            if not APP.search(clause):continue
            value=words(clause).replace("друг вокруг","другвокруг")
            # Neither a quoted question nor a person named Max chooses an app.
            if '?' in clause or '？' in clause:
                option=re.fullmatch(r'(?:а\s+)?(?:(?:в\s+)?'+MAX+r'(?:\s+(?:нет|есть|можно))?|(?:можно\s+в|у тебя есть)\s+'+MAX+r')',value)
                if option:positive=True
                continue
            if PERSON.search(value) or re.search(r'\bс\s+'+MAX+r'\b',value):continue
            deny=(re.search(r'\b(?:нет|нету|не установлен\w*)\s+(?:у меня\s+)?'+MAX+r'\b',value)
                or re.search(r'\bне\s+(?:хочу|могу|буду|пользуюсь|работает|сижу|общаюсь|переписываюсь)\s+(?:в\s+|на\s+|через\s+)?'+MAX+r'\b',value)
                or re.search(r'\b'+MAX+r'\s+(?:у меня\s+)?(?:нет|нету|не\s+(?:работает|пользуюсь|буду|хочу|установлен\w*|сижу|общаюсь|переписываюсь))\b',value))
            if deny:return False
            bare=re.fullmatch(r'(?:давай(?:те)?\s+)?(?:в\s+)?'+MAX,value)
            before=re.search(r'\b(?:есть|(?:тольк[оа]|тока)|пользуюсь|сижу|общаюсь|переписываюсь|работает|установлен\w*|давай(?:те)?|можно|лучше|удобнее|предпочитаю)\b(?:\s+\w+){0,4}\s+'+MAX+r'\b',value)
            # Reports 70ce6153 port 5563 (v1.3.84): «Я в Максе сижу» inverted the
            # verb/app order, and the after-side verb list lacked сижу/общаюсь/
            # переписываюсь/пользуюсь/давай/лучше/предпочитаю. The choice was not
            # recognized, so the contact-only policy closed the live chain as
            # declined. The after list now mirrors the before list: the same
            # verbs accept the app in EITHER position. Deny patterns above still
            # run first, so «Макс не работает»-style refusals stay refusals.
            after=re.search(r'\b'+MAX+r'\s+(?:(?:у меня|мне|тоже|сейчас|пока|тольк[оа]|тока|можешь)\s+){0,3}'
                +r'(?:есть|работает|установлен\w*|можно|удобнее|лучше|предпочитаю|пользуюсь|сижу|общаюсь|переписываюсь|давай(?:те)?|тольк[оа]|тока|скача\w*)\b',value)
            owner=re.fullmatch(r'(?:ну\s+)?у меня\s+(?:есть\s+)?'+MAX,value)
            # Reports 9104352d ports 5557(2)/5563(1) (v1.3.99): «вацапа нет /
            # а макс» and «У меня Макс и вацап.» left the MAX choice
            # unrecognized - the conjunction «а/но/зато макс» never matched the
            # bare/owner fullmatches, and the ownership tail («и вацап»)
            # broke the owner fullmatch - so the live chain closed declined.
            # Both are search forms appended AFTER the deny gates above, so
            # «а макс не работает»/«У меня нет MAX» still return False.
            conjunction=re.search(r'\b(?:а|но|зато)\s+(?:у\s+меня\s+)?(?:есть\s+)?(?:в\s+)?'+MAX+r'\b',value)
            owner_list=re.search(r'\bу\s+меня\s+(?:есть\s+)?(?:тольк[оа]\s+|тока\s+)?(?:в\s+)?'+MAX+r'\b',value)
            positive |= bool((bare and not other_available) or before or after or owner or conjunction or owner_list)
    return positive


def stay_here(text):
    """Positive local preference, including contextual rhetorical objections."""
    text=visible(text);value=words(text)
    if not re.search(r'\b(?:здесь|сдесь|тут)\b',value):return False
    # These exact rhetorical meanings are objections, not location questions.
    if re.fullmatch(r'(?:я\s+)?(?:здесь|тут)\s+почему\s+(?:ты\s+)?не\s+хочешь',value):return True
    if re.fullmatch(r'(?:а\s+)?(?:здесь|тут)\s+что\s+не\s+так',value):return True
    if '?' in text or '？' in text:return False
    if re.search(r'\bне\s+(?:хочу|удобно|удобнее|комфортно|буду|будем|общаюсь|общаться|пообщаемся|переписываюсь|нормально)|\bне\s+\w+\s+(?:здесь|тут)\b',value):return False
    # App contact instructions are not a wish to remain in the current app.
    if re.search(r'\b(?:номер|ник|контакт|телеграм\w*|тг|'+WA+r'|'+MAX+r')\b',value):return False
    local=r'(?:здесь|сдесь|тут)'
    comfort=r'(?:удобнее|удобно|комфортнее|комфортно|нормально|лучше)'
    if re.search(r'\b'+comfort+r'(?:\s+\w+){0,2}\s+'+local+r'\b|\b'+local+r'(?:\s+\w+){0,2}\s+'+comfort+r'\b',value):return True
    if re.search(r'\b(?:остаться|останемся|общаться|пообщаемся|общаюсь|переписываюсь|пообщаться)(?:\s+\w+){0,2}\s+'+local+r'\b|\b'+local+r'\s+(?:остаться|пообщаемся|общаться)\b',value):return True
    return bool(re.fullmatch(r'(?:ну\s+|да\s+|а\s+)?(?:пока|для начала|первое время)\s+'+local,value))


def private_refusal(text):
    text=visible(text)
    if '?' in text or '？' in text:return False
    value=words(text)
    return bool(re.search(r'\b(?:не\s+(?:раздаю|даю|дам|отправляю|сообщаю)|не\s+сторонница\s+давать)\s+(?:свой\s+)?(?:номер|телефон|контакт|соц\s*сети)\b',value)
        or re.search(r'\b(?:номер|телефон|контакт)\s+(?:никому\s+)?не\s+(?:дам|даю|раздаю|отправлю)\b',value)
        or re.fullmatch(r'(?:я\s+)?замужем',value)
        or re.search(r'\bне\s+интересуют\s+разовые\s+встречи\b',value))


def unavailable(text):
    """General unavailable/preference packet; MAX alternative is checked by caller."""
    text=visible(text);value=words(text)
    if '?' in text or '？' in text:return False
    return bool(re.search(r'\bни\s*где\b|\bнигде\b',value) and re.search(r'\b(?:нет|не\s+сижу|не\s+хочу|не\s+охота)\b',value)
        or re.fullmatch(r'не работает',value)
        or re.search(r'\bнет\s+ни\s+того\s+ни\s+другого\b',value)
        or re.search(r'\b(?:ни\s+того\s+ни\s+другого)\b',value))


TG = r'(?:телеграм(?:м)?(?:а|е|ом|у)?|telegram|тг|телег[аеу])'
# Reports aPYyN7weMm (v1.3.78): «вотсап»/«вотапп»/«ватапп» misspellings were
# outside the old WA list, so the peer's chosen messenger was not recognized
# in the contact stage either. One shared spelling family now covers
# ватсап/вотсап/ватцап/вацап/воцап/вассап/вотапп/ватапп with case endings
# and optional inner spacing, matching the detector in shared_contact.py.
# Reports 9104352d port 5567 (v1.3.91): «Вайцап» (colloquial «й» spelling)
# was outside the family as well - the choice was not recognized and the
# chain closed declined. The optional «й» after в[ао] joins the same family.
# Reports 9104352d ports 5567/5563 (v1.3.99): «В ват сап» (space INSIDE the
# consonant cluster) and «Вптсап» (the «п»-for-«о» keyboard typo, о/п are
# adjacent on ЙЦУКЕН) were still outside the family - both closed the live
# chain declined. The cluster now tolerates the internal space (т с/т ц) and
# the second letter accepts «п»; deny patterns run first, so «ватсап не
# работает» stays a negation.
WA = r'(?:в(?:[ао]й?|п)(?:т\s*[сц]|тс|тц|ц|с|т|сс)?\s*апп?(?:а|е|ом|у)?|whats\s?app)'
# Finite adjacent fillers only: do not cross another app, question or negation.
AVAIL_FILL = r'(?:(?:у меня|сейчас|пока|еще|все еще|вроде бы|вроде|только)\s+){0,3}'

def platform_signals(messages, app):
    positive=negative=False
    clauses=[]
    for message in messages:
        raw=message.get('text')
        if not isinstance(raw,str):continue
        for line in raw.splitlines():
            if line.lstrip().startswith('>'):continue
            clauses.extend(re.split(r'[,;.!]+',visible(line)))
    for text in clauses:
        if '?' in text or '？' in text:continue
        value=words(text)
        if not re.search(r'\b'+app+r'\b',value):continue
        negative |= bool(re.search(r'\b'+app+r'\s+'+AVAIL_FILL+r'(?:не\s+(?:очень\s+)?работает|нет|нету|не пользуюсь)\b',value)
            or re.search(r'\b(?:нет|нету|не\s+(?:очень\s+)?работает|не пользуюсь)\s+'+AVAIL_FILL+app+r'\b',value)
            or re.search(r'\b'+app+r'\s+'+AVAIL_FILL+r'работает\s+не\s+очень\b',value))
        # Reports 9104352d port 5567 (v1.3.91): «Ватсап можно 89241810009…»
        # and «Вайцапе сижу» put the verb AFTER the app name. The app-first
        # positive list lacked можно/сижу/общаюсь/переписываюсь/пользуюсь/
        # давай - the same word-order hole 1.3.84 closed for MAX - so such a
        # reply was not an available alternative and the app-specific number
        # question was never asked. Both lists now mirror each other; the
        # negative patterns above still run first, so «ватсап не работает»
        # stays a negation.
        # Reports 9104352d port 5559 (v1.3.99): «У меня только ватсап» carries
        # NO verb at all - plain ownership («у меня (есть/только) ватсап») was
        # never a positive availability signal, so the WhatsApp choice stayed
        # unrecognized and the chain closed declined. The ownership search
        # joins the positives; the negation patterns above still win, so
        # «у меня нет ватсапа» stays unavailable.
        ownership=re.search(r'\bу\s+меня\s+(?:есть\s+)?(?:тольк[оа]\s+|тока\s+)?(?:в\s+)?'+app+r'\b',value)
        positive |= bool(re.search(r'\b'+app+r'\s+'+AVAIL_FILL+r'(?:есть|работает|живой|жива|жив|живое|лучше|удобнее|удобно|можно|пользуюсь|сижу|общаюсь|переписываюсь|давай(?:те)?)\b',value)
            or re.search(r'\b(?:есть|пользуюсь|давай(?:те)?|можно|лучше|удобнее|удобно|сижу|общаюсь|переписываюсь)\s+(?:в\s+)?'+app+r'\b',value)
            or re.search(r'\bработает\s+'+AVAIL_FILL+app+r'\b',value)
            or ownership
            or re.fullmatch(r'(?:я\s+)?(?:в\s+)?'+app,value))
    return positive and not negative, negative


def available_alternative(messages):
    """Scope absence to its app; never veto an explicitly available other app."""
    # App availability cannot override an explicit refusal to communicate.
    if any(re.search(r'\bне\s*(?:пиши|пишите|хочу общаться|хочу переходить|надо писать)\b',visible(m.get('text'))) for m in messages):return None
    tg,tg_no=platform_signals(messages,TG);wa,wa_no=platform_signals(messages,WA)
    if wa and not tg:return 'whatsapp'
    if tg and not wa:return 'telegram'
    return None
