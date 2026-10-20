"""One external, validated source for cities and editable greeting templates."""
from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import sys


class ConfigError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError('Повторяющийся ключ в настройках.')
        result[key] = value
    return result


def config_directory():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'config'
    return Path(__file__).resolve().parents[1] / 'config'


def entries(folder, key, limit):
    path = Path(folder) / (key + '.json')
    try:
        if path.stat().st_size > 65536:
            raise ConfigError('Слишком большой файл настроек.')
        value = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ConfigError('Не удалось прочитать config/' + key + '.json.') from None
    if not isinstance(value, dict) or set(value) != {key}:
        raise ConfigError('Неверная структура config/' + key + '.json.')
    items = value[key]
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ConfigError('В списке настроек должно быть от 1 до 100 строк.')
    if any(not isinstance(s, str) or s != s.strip() or not 1 <= len(s) <= limit
           or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in s) for s in items):
        raise ConfigError('В настройках есть пустая, длинная или недопустимая строка.')
    if len(set(items)) != len(items):
        raise ConfigError('Повторяющиеся строки в настройках.')
    return tuple(items)


@dataclass(frozen=True)
class Config:
    cities: tuple
    greetings: tuple

    def city(self):
        return secrets.choice(self.cities)

    def greeting(self):
        return secrets.choice(self.greetings)


def load(folder=None):
    folder = config_directory() if folder is None else folder
    return Config(entries(folder, 'cities', 80), entries(folder, 'greetings', 256))


def check_text(text):
    if (not isinstance(text, str) or not 1 <= len(text) <= 256 or text != text.strip()
            or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in text)):
        raise ConfigError('Недопустимый текст приветствия.')
    return text
