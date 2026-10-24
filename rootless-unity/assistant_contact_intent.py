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
    other_available=any(re.search(r'\b(?:вацап|ватсап|ватцап|whatsapp|телеграм\w*|тг)\s+есть\b',words(visible(m.get('text')))) for m in messages)
    for m in messages:
        text=visible(m.get('text'))
        if not APP.search(text):continue
        for clause in re.split(r'[,;.!\n]+',text):
            if not APP.search(clause):continue
            value=words(clause).replace("друг вокруг","другвокруг")
            # Neither a quoted question nor a person named Max chooses an app.
            if '?' in clause or '？' in clause or PERSON.search(value) or re.search(r'\bс\s+'+MAX+r'\b',value):continue
            deny=(re.search(r'\b(?:нет|нету|не установлен\w*)\s+(?:у меня\s+)?'+MAX+r'\b',value)
                or re.search(r'\bне\s+(?:хочу|могу|буду|пользуюсь|работает)\s+(?:в\s+|через\s+)?'+MAX+r'\b',value)
                or re.search(r'\b'+MAX+r'\s+(?:у меня\s+)?(?:нет|нету|не\s+(?:работает|пользуюсь|буду|хочу|установлен\w*))\b',value))
            if deny:return False
            bare=re.fullmatch(r'(?:давай(?:те)?\s+)?(?:в\s+)?'+MAX,value)
            before=re.search(r'\b(?:есть|только|пользуюсь|сижу|общаюсь|переписываюсь|работает|установлен\w*|давай(?:те)?|можно|лучше|удобнее|предпочитаю)\b(?:\s+\w+){0,4}\s+'+MAX+r'\b',value)
            after=re.search(r'\b'+MAX+r'\s+(?:(?:у меня|мне|тоже|сейчас|пока|только|можешь)\s+){0,3}(?:есть|работает|установлен\w*|можно|удобнее|только|скача\w*)\b',value)
            owner=re.fullmatch(r'(?:ну\s+)?у меня\s+(?:есть\s+)?'+MAX,value)
            positive |= bool((bare and not other_available) or before or after or owner)
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
    if re.search(r'\b(?:номер|ник|контакт|телеграм\w*|тг|ватсап\w*|whatsapp|'+MAX+r')\b',value):return False
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
