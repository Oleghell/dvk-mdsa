"""Small settings, with bot credentials kept separately in Windows DPAPI."""
from dataclasses import dataclass
import json
from pathlib import Path
from assistant_store import data_directory, StateError

DEFAULT_ADB = 'C:/Users/XXX/Desktop/platform-tools/adb.exe'
DEFAULT_TEST_APKS = 'C:/Users/XXX/Desktop/spam-dvk-main/test-apks'


@dataclass(frozen=True)
class Settings:
    adb: str = DEFAULT_ADB
    folder: str = DEFAULT_TEST_APKS
    contacts_enabled: bool = False
    reply_interval: int = 5
    profile_limit: int = 5
    groq_enabled: bool = False
    groq_model: str = 'qwen/qwen3.8-27b'
    errors_enabled: bool = True
    ai_provider: str = 'groq'
    openrouter_model: str = 'dots-studio/dots-3-note-preview:free'
    profile_interval: int = 300
    gemini_model: str = 'gemini-3.1-flash-lite'
    zai_model: str = 'glm-4.5-flash'
    typing_words_per_minute: int = 35
    typing_delay_enabled: bool = False

    def check(self):
        from assistant_authorization import check_words_per_minute
        try:
            check_words_per_minute(self.typing_words_per_minute)
        except ValueError as error:
            raise StateError(str(error)) from None
        if any(not isinstance(x, str) or not 1 <= len(x) <= 4096 or x != x.strip()
               or any(ord(c) < 32 for c in x) for x in (self.adb, self.folder)):
            raise StateError('Укажи корректные пути ADB и test-apks.')
        if type(self.contacts_enabled) is not bool or type(self.reply_interval) is not int or not 5 <= self.reply_interval <= 3600:
            raise StateError('Интервал проверки: от 5 до 3600 секунд.')
        if type(self.profile_limit) is not int or not 1 <= self.profile_limit <= 20:
            raise StateError('Анкет за одну порцию: от 1 до 20.')
        if type(self.profile_interval) is not int or not 30 <= self.profile_interval <= 86400:
            raise StateError('Отдых перед новой порцией: от 30 до 86400 секунд.')
        if type(self.typing_delay_enabled) is not bool:raise StateError('Проверь переключатель задержки печати.')
        import re
        if type(self.groq_enabled) is not bool or type(self.errors_enabled) is not bool:
            raise StateError('Проверь переключатели ИИ и уведомлений об ошибках.')
        if not isinstance(self.groq_model, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,100}', self.groq_model):
            raise StateError('Укажи корректный ID модели Groq.')
        if self.ai_provider not in ('groq', 'openrouter', 'gemini', 'zai'):
            raise StateError('Выбери Groq, OpenRouter, Gemini или Z.AI.')
        if (not isinstance(self.openrouter_model, str) or
                len(self.openrouter_model) > 150 or
                not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:free', self.openrouter_model)):
            raise StateError('OpenRouter: разрешены только ID моделей с суффиксом :free.')
        if not isinstance(self.gemini_model, str) or not re.fullmatch(r'gemini-[A-Za-z0-9.-]{1,100}', self.gemini_model):
            raise StateError('Укажи корректный ID модели Gemini.')
        if self.zai_model != 'glm-4.5-flash':
            raise StateError('Z.AI: разрешена только glm-4.5-flash, без платной замены.')
        return self

    @property
    def ai_model(self):
        return {'groq': self.groq_model, 'openrouter': self.openrouter_model, 'gemini': self.gemini_model, 'zai': self.zai_model}[self.ai_provider]


def load(directory=None):
    directory = data_directory() if directory is None else Path(directory)
    try:
        paths = directory / 'settings.json'
        options = directory / 'workflow-settings.json'
        saved = dict(adb=DEFAULT_ADB, test_apks=DEFAULT_TEST_APKS)
        if paths.exists():
            if paths.stat().st_size > 32768:
                raise ValueError()
            old = json.loads(paths.read_text(encoding='utf-8'))
            if set(old) != {'adb', 'test_apks'}:
                raise ValueError()
            for key in saved:
                if old[key]:
                    saved[key] = old[key]
        config = dict(contacts_enabled=False, reply_interval=5)
        if options.exists():
            if options.stat().st_size > 8192:
                raise ValueError()
            config = json.loads(options.read_text(encoding='utf-8'))
            schema = config.pop('settings_version', 1)
            if type(schema) is not int or schema not in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                raise ValueError()
            legacy_interval = config.get('reply_interval')
            if type(legacy_interval) is not int or not 5 <= legacy_interval <= 3600:
                raise ValueError()
            if schema == 1 and type(config.get('reply_interval')) is int and config['reply_interval'] == 120:
                config['reply_interval'] = 30
            if schema < 5 and config.get('reply_interval') == 30:
                config['reply_interval'] = 5
            # 0.4.x files have no profile_limit; keep reading them.
            required = {'contacts_enabled', 'reply_interval'}
            if schema >= 8:
                required.add('typing_words_per_minute')
            if schema>=9:required.add('typing_delay_enabled')
            allowed = required | {'profile_limit'} | ({'groq_enabled', 'groq_model', 'errors_enabled'} if schema >= 3 else set()) | ({'ai_provider', 'openrouter_model'} if schema >= 4 else set()) | ({'profile_interval'} if schema >= 6 else set()) | ({'gemini_model','zai_model'} if schema >= 7 else set())
            if schema < 4 and config.get('groq_model') == 'llama-3.3-70b-versatile':
                config['groq_model'] = 'qwen/qwen3.8-27b'
            if not required <= set(config) or not set(config) <= allowed:
                raise ValueError()
            if schema < 6:
                # Old UI used one ambiguous interval. Keep the user's long rest
                # value as profile rest, not as a multi-minute inbox blind spot.
                config['profile_interval'] = legacy_interval if type(legacy_interval) is int and legacy_interval > 30 and not (schema == 1 and legacy_interval == 120) else 300
                config['reply_interval'] = 5
        if config.get('openrouter_model')=='minimax/minimax-m3.1-flash:free':
            config['openrouter_model']='dots-studio/dots-3-note-preview:free'
        return Settings(saved['adb'], saved['test_apks'], **config).check()
    except Exception:
        raise StateError('Не удалось прочитать настройки. Проверь их в окне «Настройки».') from None


def save(settings, directory=None):
    settings.check()
    directory = data_directory() if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    values = {'settings.json': dict(adb=settings.adb, test_apks=settings.folder),
              'workflow-settings.json': dict(settings_version=9, typing_delay_enabled=settings.typing_delay_enabled, typing_words_per_minute=settings.typing_words_per_minute, profile_interval=settings.profile_interval, contacts_enabled=settings.contacts_enabled, reply_interval=settings.reply_interval,
                                            profile_limit=settings.profile_limit, groq_enabled=settings.groq_enabled,
                                            groq_model=settings.groq_model, errors_enabled=settings.errors_enabled,
                                            ai_provider=settings.ai_provider, openrouter_model=settings.openrouter_model, gemini_model=settings.gemini_model, zai_model=settings.zai_model)}
    for filename, value in values.items():
        path = directory / filename
        temp = path.with_suffix('.tmp')
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
