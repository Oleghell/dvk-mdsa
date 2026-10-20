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
    reply_interval: int = 120

    def check(self):
        if any(not isinstance(x, str) or not 1 <= len(x) <= 4096 or x != x.strip()
               or any(ord(c) < 32 for c in x) for x in (self.adb, self.folder)):
            raise StateError('Укажи корректные пути ADB и test-apks.')
        if type(self.contacts_enabled) is not bool or type(self.reply_interval) is not int or not 30 <= self.reply_interval <= 3600:
            raise StateError('Интервал проверки: от 30 до 3600 секунд.')
        return self


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
        config = dict(contacts_enabled=False, reply_interval=120)
        if options.exists():
            if options.stat().st_size > 8192:
                raise ValueError()
            config = json.loads(options.read_text(encoding='utf-8'))
            if set(config) != {'contacts_enabled', 'reply_interval'}:
                raise ValueError()
        return Settings(saved['adb'], saved['test_apks'], **config).check()
    except Exception:
        raise StateError('Не удалось прочитать настройки. Проверь их в окне «Настройки».') from None


def save(settings, directory=None):
    settings.check()
    directory = data_directory() if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    values = {'settings.json': dict(adb=settings.adb, test_apks=settings.folder),
              'workflow-settings.json': dict(contacts_enabled=settings.contacts_enabled, reply_interval=settings.reply_interval)}
    for filename, value in values.items():
        path = directory / filename
        temp = path.with_suffix('.tmp')
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
