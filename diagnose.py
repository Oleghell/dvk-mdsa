"""Read-only MoreLogin diagnostics. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
MAX_RESPONSE = 2 * 1024 * 1024
STATUS = {0: 'new', 1: 'creation_failed', 2: 'powered_off', 3: 'booting',
          4: 'powered_on', 5: 'resetting', 6: 'restarting', 7: 'recreating'}


class DiagnosticError(Exception):
    """Safe, user-facing error with no remote response body."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise DiagnosticError('Не удалось прочитать config.json. Проверьте формат JSON.') from None
    if not isinstance(config, dict):
        raise DiagnosticError('Конфигурация должна быть объектом JSON.')
    base = config.get('api_base', '')
    if not isinstance(base, str):
        raise DiagnosticError('api_base должен быть строкой.')
    try:
        u = urlsplit(base)
        port = u.port
    except ValueError:
        raise DiagnosticError('Некорректный адрес Local API.') from None
    if (u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost', '::1')
            or not port or u.username is not None or u.password is not None
            or u.path not in ('', '/') or u.query or u.fragment):
        raise DiagnosticError('Разрешён только локальный HTTP-адрес с портом, например http://127.0.0.1:8001.')
    ids = config.get('phone_ids')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 200
            or any(not isinstance(x, str) or not x.isascii() or not x.isdigit() for x in ids)
            or len(set(ids)) != len(ids)):
        raise DiagnosticError('phone_ids: от 1 до 200 уникальных ID в кавычках, только цифры.')
    return {'api_base': base.rstrip('/'), 'phone_ids': ids}


def fetch_adb_info(config: dict) -> list[dict]:
    # Do not use system proxies or follow redirects with private device IDs.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(
        config['api_base'] + '/api/cloudphone/batchAdbInfo',
        data=json.dumps({'envIds': config['phone_ids']}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
        method='POST',
    )
    try:
        with opener.open(request, timeout=25) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise DiagnosticError('Local API требует авторизацию. Не выключайте защиту: нужна настройка авторизации клиента. Ключи в чат не отправляйте.') from None
        raise DiagnosticError(f'Local API вернул HTTP {exc.code}. Проверьте версию MoreLogin и адрес API.') from None
    except (URLError, TimeoutError, OSError):
        raise DiagnosticError('Нет ответа от Local API. Запустите MoreLogin на этом же компьютере и проверьте адрес/порт.') from None
    if len(raw) > MAX_RESPONSE:
        raise DiagnosticError('Ответ Local API слишком большой; обработка остановлена.')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DiagnosticError('Local API вернул не JSON. Проверьте порт API.') from None
    if not isinstance(payload, dict):
        raise DiagnosticError('Неожиданный формат ответа Local API.')
    code = payload.get('code')
    if type(code) is not int:
        raise DiagnosticError('В ответе нет корректного кода результата.')
    if code != 0:
        # Never echo arbitrary API messages: they can contain credentials.
        raise DiagnosticError(f'Ошибка MoreLogin, код {code}. Проверьте права команды, состояние телефонов и настройки API.')
    data = payload.get('data')
    if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
        raise DiagnosticError('Неожиданный формат списка телефонов.')
    return data


def flag(value):
    if value is True or type(value) is int and value == 1:
        return True
    if value is False or type(value) is int and value == 0:
        return False
    return None


def safe_phone_report(ids: list[str], entries: list[dict]) -> list[dict]:
    """Allowlist only: never copy passwords, commands, endpoints or remarks."""
    result = []
    for phone_id in ids:
        matches = [x for x in entries if str(x.get('id', '')) == phone_id]
        if len(matches) != 1:
            result.append({'phone_id': phone_id, 'ready': False,
                           'issues': ['missing_result' if not matches else 'duplicate_result']})
            continue
        entry = matches[0]
        supported, enabled = flag(entry.get('supportAdb')), flag(entry.get('enableAdb'))
        status = entry.get('envStatus')
        powered_on = type(status) is int and status == 4
        direct = bool(entry.get('adbIp') and entry.get('adbPort'))
        tunnel = bool(entry.get('command'))
        issues = []
        if supported is not True:
            issues.append('adb_unsupported' if supported is False else 'adb_support_unknown')
        if enabled is not True:
            issues.append('adb_disabled' if enabled is False else 'adb_switch_unknown')
        if not powered_on:
            issues.append('phone_not_powered_on')
        if not (direct or tunnel):
            issues.append('connection_details_missing')
        if entry.get('remark'):
            issues.append('service_remark_present')
        result.append({
            'phone_id': phone_id,
            'ready': not issues,
            'state': STATUS.get(status, 'unknown') if type(status) is int else 'unknown',
            'adb_supported': supported,
            'adb_enabled': enabled,
            'connection_mode': 'ssh_tunnel' if tunnel else 'direct' if direct else 'unavailable',
            'authentication_present': bool(entry.get('adbPassword')),
            'issues': issues,
        })
    return result


def check_adb() -> dict:
    # Check installation only. No device connection, shell command or auth.
    executable = shutil.which('adb')
    if not executable:
        return {'installed': False, 'version_check': 'not_installed'}
    try:
        completed = subprocess.run([executable, 'version'], capture_output=True, timeout=10)
        return {'installed': True, 'version_check': 'ok' if completed.returncode == 0 else 'failed'}
    except (OSError, subprocess.TimeoutExpired):
        return {'installed': True, 'version_check': 'failed'}


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Безопасная проверка четырёх телефонов MoreLogin. Не отправляет сообщения.')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--report', type=Path, default=ROOT / 'reports' / 'diagnostic.json')
    args = parser.parse_args(argv)
    report = {'stage': 'read_only_diagnostics', 'chat_automation_implemented': False,
              'created_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        config = load_config(args.config)
        data = fetch_adb_info(config)
        report['local_api'] = 'ok'
        report['phones'] = safe_phone_report(config['phone_ids'], data)
        del data  # Credentials are never persisted or printed.
        report['adb'] = check_adb()
        all_ready = all(phone['ready'] for phone in report['phones'])
        report['connection_parameters_available'] = all_ready
        print('Local API отвечает. Результаты:')
        for phone in report['phones']:
            state = 'параметры доступны' if phone['ready'] else ', '.join(phone['issues'])
            print(f"  {phone['phone_id']}: {state}")
        print('ADB установлен.' if report['adb']['installed'] else 'ADB пока не установлен. На этом этапе это не мешает проверке API.')
        print('Подключение к Android НЕ проверялось. Сообщения НЕ отправлялись.')
        exit_code = 0 if all_ready else 2
    except DiagnosticError as exc:
        report['local_api'] = 'failed'
        report['error'] = str(exc)
        print(str(exc))
        exit_code = 1
    try:
        write_report(args.report, report)
        print('Отчёт без адресов подключения, паролей и ключей: reports/diagnostic.json')
    except OSError:
        print('Не удалось записать отчёт. Переместите проект в папку с правом записи.')
        return 1
    return exit_code


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
