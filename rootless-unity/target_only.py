"""Read-only contract diagnostics on the fixed test endpoint, never working #0.

The address is an explicit endpoint, not proof of a MuMu instance number. A
private pinned APK bundle and its authenticated Gadget are still required.
Boot identity is checked in memory for this session, never exported or saved.
This policy is NOT available to installers, enrollment or sending modes.
"""
from diagnose_device import DiagnosticAdb
from test_device import TestError, TARGET, boot_id, package_present


class TargetOnlyAdb(DiagnosticAdb):
    def validate(self, args):
        # Apply this guard BEFORE the inherited allowlist, including read-only
        # commands. No devices enumeration, implicit target or alternate endpoint.
        if args not in (['version'], ['connect', TARGET]) and args[:2] != ['-s', TARGET]:
            raise TestError('Разрешено только тестовое подключение #4 / 5563.')
        super().validate(args)


def preflight(adb):
    if type(adb) is not TargetOnlyAdb:
        raise TestError('Для режима одной копии нужен ограниченный тестовый ADB.')
    adb.run(['version'])
    adb.run(['connect', TARGET])
    if adb.run(['-s', TARGET, 'get-state']) != 'device':
        raise TestError('Запусти только тестовый MuMu #4 и разреши его обычный ADB.')
    identity = boot_id(adb, TARGET)
    if adb.run(['-s', TARGET, 'shell', 'getprop', 'sys.boot_completed']) != '1':
        raise TestError('Тестовый Android ещё не загрузился.')
    if not package_present(adb):
        raise TestError('На тестовом устройстве нет приложения. Автоустановки и переключения устройства нет.')
    return identity


def recheck(adb, identity):
    if type(adb) is not TargetOnlyAdb or boot_id(adb, TARGET) != identity:
        raise TestError('Тестовое устройство изменилось во время проверки. Операция остановлена.')
