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
        # v1.3.81: the wording is port-agnostic - the endpoint is whatever this
        # worker's configured MuMu port is, not the legacy "#4 / 5563".
        if args not in (['version'], ['connect', TARGET]) and args[:2] != ['-s', TARGET]:
            raise TestError('Разрешено только подключение к порту этого MuMu.')
        super().validate(args)


def preflight(adb):
    if type(adb) is not TargetOnlyAdb:
        raise TestError('Для режима одной копии нужен ограниченный тестовый ADB.')
    adb.run(['version'])
    # Only ordinary preflight may avoid reconnect when the exact endpoint is
    # freshly device-ready. Explicit recovery connect must still run the CLI.
    adb._dvk_preflight_connect_probe=True
    try:adb.run(['connect',TARGET])
    finally:adb._dvk_preflight_connect_probe=False
    if adb.run(['-s', TARGET, 'get-state']) != 'device':
        raise TestError('MuMu на этом порту не подключается. Запусти инстанс MuMu с этим ADB-портом и разреши его обычный ADB.')
    identity = boot_id(adb, TARGET)
    if adb.run(['-s', TARGET, 'shell', 'getprop', 'sys.boot_completed']) != '1':
        raise TestError('Android этого MuMu ещё не загрузился.')
    if not package_present(adb):
        raise TestError('В этом MuMu нет приложения. Автоустановки и переключения устройства нет.')
    return identity


def recheck(adb, identity):
    if type(adb) is not TargetOnlyAdb or boot_id(adb, TARGET) != identity:
        raise TestError('MuMu этого порта изменился во время проверки. Операция остановлена.')
