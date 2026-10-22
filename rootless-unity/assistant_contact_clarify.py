"""One optional clarification after a peer explicitly chooses a messenger."""
import re
TEXT = 'Хорошо, напиши номер для WhatsApp или ник в Telegram, если тебе удобно.'
PLATFORM = re.compile(r'\b(?:тг|телеграм(?:м)?(?:е|ом)?|telegram|whats\s?app|ват[сц]ап(?:е|ом)?|ва[тц]сап(?:е|ом)?|вотсап(?:е|ом)?)\b', re.I)
CHOICE = re.compile(r'\b(?:давай(?:те)?|лучше|удобн\w*|предпочитаю|соглас\w*|напиши|пиши|найди|хочу|можно)\b', re.I)
NEGATIVE = re.compile(r'не\s+(?:хочу|надо|могу|пользуюсь|работает)|не\s*пиши|не\s*да[мю]', re.I)

def chosen(messages):
    texts=[m['text'] for m in messages if isinstance(m.get('text'),str)]
    value=' / '.join(texts)
    from shared_contact import contact_items
    if any(contact_items(text,allow_unformatted=True) for text in texts):
        return False  # Do not ask for a contact already present but not safely self-attributed.
    return bool(PLATFORM.search(value) and CHOICE.search(value) and not NEGATIVE.search(value))
