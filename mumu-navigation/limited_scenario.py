"""Requested five-profile policy and lists; NOT an autonomous device controller.

The live v1.4.3 Android helper still accepts only its original ten greetings.
This module does not change that allowlist or enable city selection, replies,
typing, collection of contacts, or notification delivery.
"""
from dataclasses import dataclass
import secrets

DEFAULT_NEW_PROFILE_LIMIT = 5
FRIENDS_EXCLUSIVE_LIMIT = 50
TYPING_WORDS_PER_MINUTE = 35
# Conventional pacing calculation: one word is five characters. No random
# evasion jitter, Enter actions, keyboard events or automatic sending.
SECONDS_PER_CHARACTER = 60 / (TYPING_WORDS_PER_MINUTE * 5)

CITIES = (
    'Нальчик', 'Таганрог', 'Нижнекамск', 'Благовещенск',
    'Комсомольск-на-Амуре', 'Петрозаводск', 'Сыктывкар', 'Королёв',
    'Братск', 'Шахты', 'Люберцы', 'Дзержинск', 'Ангарск', 'Старый Оскол',
    'Орск', 'Псков', 'Бийск', 'Энгельс', 'Южно-Сахалинск', 'Прокопьевск',
    'Балаково', 'Армавир', 'Северодвинск', 'Абакан',
    'Петропавловск-Камчатский', 'Норильск', 'Рыбинск', 'Сызрань',
    'Новочеркасск', 'Каменск-Уральский',
)

REQUESTED_GREETINGS = (
    'Привет 🙂', 'Приветствую 👋', 'Здравствуйте 😊', 'Привет, красотка 😉',
    'Рад знакомству 🤝', 'Приветик 🌸', 'Здравствуй ✨', 'Привет, красавица 💫',
    'Приветствую Вас 🙏', 'Привет, милая 💐', 'Доброго знакомства 😌',
    'Здравствуйте 🌷', 'Приветствую 🤍', 'Привет 🖐', 'Привет, красотка 🌹',
    'Здравствуй 😉', 'Очарован знакомством 🤝', 'Приветик 🍃',
    'Привет, красавица 💭', 'Здравствуйте, милая 🌼', 'Приветствую Вас 👋',
    'Приветик ✨', 'Привет 💬', 'Рад знакомству ✨',
    'Здравствуй, красавица 🌻', 'Приветик, милая 🦋', 'Привет 🌞',
    'Здравствуйте 🙂', 'Приветствую 😊', 'Здравствуй 💐',
)
FIRST_REPLY_CANDIDATES = ('Как дела?)', 'Как настроение?)')
# A candidate only; never send a positive assertion without checking the reply.
POSITIVE_REPLY_CONTACT_QUESTION = (
    'Супер, у меня тоже. Ты есть в телеграме или ватцапе? '
    'А то я тут не часто бываю 😅'
)
TELEGRAM_NOTIFICATION_TITLE = '🔥НОВЫЙ НОМЕР'

@dataclass(frozen=True)
class LimitedPolicy:
    max_visited_profiles: int = DEFAULT_NEW_PROFILE_LIMIT
    automatic_restart: bool = False
    stop_after_limit: bool = True

    def __post_init__(self):
        if type(self.max_visited_profiles) is not int or self.max_visited_profiles != 5:
            raise ValueError('This requested policy is exactly five visited profiles, including skips.')
        if self.automatic_restart is not False or self.stop_after_limit is not True:
            raise ValueError('Automatic restart and continuation past the limit are disabled.')

    def friends_eligible(self, count):
        # bool, OCR guesses, unknown/negative values never authorize opening chat.
        return type(count) is int and 0 <= count < FRIENDS_EXCLUSIVE_LIMIT

    def can_open_next(self, visited, *, active, previous_visit_returned, uncertain):
        if any(type(v) is not bool for v in (active, previous_visit_returned, uncertain)):
            return False
        return (type(visited) is int and 0 <= visited < self.max_visited_profiles
                and active and previous_visit_returned and not uncertain)


def choose_city(*, current=None, excluded=()):
    excluded = set(excluded)
    candidates = tuple(city for city in CITIES if city != current and city not in excluded)
    if not candidates:
        raise ValueError('No untried city remains; stop rather than restart an unbounded loop.')
    return secrets.choice(candidates)


def choose_requested_greeting():
    """Select configuration text only. NOT accepted by the current native helper."""
    return secrets.choice(REQUESTED_GREETINGS)
