"""The user's exact approved greetings. No generated or arbitrary text."""
import secrets

GREETINGS = (
    'Привет 🙂',
    'Приветствую 👋',
    'Здравствуйте 😊',
    'Привет, красотка 😉',
    'Рад знакомству 🤝',
    'Приветик 🌸',
    'Здравствуй ✨',
    'Привет, красавица 💫',
    'Приветствую Вас 🙏',
    'Привет, милая 💐',
    'Доброго знакомства 😌',
    'Здравствуйте 🌷',
    'Приветствую 🤍',
    'Привет 🖐',
    'Привет, красотка 🌹',
    'Здравствуй 😉',
    'Очарован знакомством 🤝',
    'Приветик 🍃',
    'Привет, красавица 💭',
    'Здравствуйте, милая 🌼',
    'Приветствую Вас 👋',
    'Приветик ✨',
    'Привет 💬',
    'Рад знакомству ✨',
    'Здравствуй, красавица 🌻',
    'Приветик, милая 🦋',
    'Привет 🌞',
    'Здравствуйте 🙂',
    'Приветствую 😊',
    'Здравствуй 💐',
)

def get_greeting(index):
    if type(index) is not int or not 0<=index<len(GREETINGS):
        raise ValueError('Unknown greeting variant')
    return GREETINGS[index]

def choose_index():
    # Fresh independent uniform selection. Repeated variants are allowed.
    return secrets.randbelow(len(GREETINGS))
