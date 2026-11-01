#!/usr/bin/env python3
"""Готовый воркфлоу обслуживания базы Supabase проекта DvkAssistant (dvk-spam).

Работает через Management API (только HTTPS, без зависимостей). Токен
читается по приоритету:
    1) переменная окружения SUPABASE_ACCESS_TOKEN;
    2) файл config/supabase-management.token рядом с репозиторием
       (добавлен в .gitignore — токен никогда не попадает в коммит);
    3) путь, переданный аргументом --token-file.

Команды:
    status   (по умолчанию) — размер базы, группы таблиц, топ-20 таблиц,
               замороженные m<порт>__ таблицы, фантомные строки каталога
               _dvk_schema, защитные реестры, здоровье;
    clean    — удалить ТОЛЬКО замороженные старые таблицы m<порт>__
               (журналы до миграции 1.3.53; приложение с 1.3.53 пишет только
               в таблицы пространств установок i<20hex>_m<порт>__), удалить
               их фантомные строки из каталога _dvk_schema (иначе старт
               ассистента умирает как cloud-schema-missing — v1.3.111),
               затем VACUUM ANALYZE; до/после по размеру;
    vacuum   — только VACUUM ANALYZE (сбор статистики, безопасно при
               работающем ассистенте);
    report   — status + запись JSON-отчёта в reports/db-maintenance-*.json.

Реестры защиты от повторных приветствий/отправок (mumu_greeting_claims,
mumu_peer_blocks, mumu_manual_silences, global_peer_city, global_greeting_statistics,
mumu_city_claims) и таблицы пространств установок НИКОГДА не удаляются.

Примеры:
    python tools/supabase_maintenance.py status
    python tools/supabase_maintenance.py clean
    DB_MAINTENANCE.bat report
"""
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = 'gkmyipjiodjlxnsjvkxs'          # dvk-spam, eu-west-1
REGION = 'eu-west-1'
URL = f'https://api.supabase.com/v1/projects/{PROJECT}/database/query'
LIMIT_BYTES = 500 * 1024 * 1024            # free-план
FROZEN = re.compile(r'^m[0-9]{4,5}__')     # старые журналы до 1.3.53
CTX = ssl.create_default_context()


def load_token():
    token = os.environ.get('SUPABASE_ACCESS_TOKEN')
    if token:
        return token.strip()
    for candidate in (Path(__file__).resolve().parents[1] / 'config' / 'supabase-management.token',
                      Path.home() / '.supabase' / 'management.token'):
        if candidate.is_file():
            return candidate.read_text(encoding='utf-8').strip()
    sys.exit('Токен Management API не найден.\n'
             'Положи его в config/supabase-management.token (файл в .gitignore)\n'
             'или задай переменную окружения SUPABASE_ACCESS_TOKEN.')


def query(token, sql):
    body = json.dumps({'query': sql}).encode()
    request = urllib.request.Request(URL, data=body, method='POST')
    request.add_header('Authorization', f'Bearer {token}')
    request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request, context=CTX, timeout=180) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode()[:400]
        raise RuntimeError(f'HTTP {error.code}: {detail}') from None


def megabytes(size_bytes):
    return float(size_bytes) / (1024 * 1024)


# v1.3.111 (отчёт dropmefiles NwkXSU2V): чистка 1.3.110 удаляла физические
# таблицы m<порт>__, но оставляла их строки в каталоге _dvk_schema —
# приложение видело фантомные имена через свой sqlite_master и каждый порт
# умирал на старте как cloud-schema-missing (relation chain_dialogs).
# Чистка теперь удаляет и строки каталога; заодно лечит фантомы от любого
# другого ручного удаления таблиц.
PHANTOM_COUNT = ("SELECT count(*) AS n FROM dvk_private._dvk_schema s"
                 " WHERE NOT EXISTS (SELECT 1 FROM pg_class c"
                 " JOIN pg_namespace n ON n.oid=c.relnamespace"
                 " WHERE n.nspname='dvk_private' AND c.relname=s.name"
                 " AND c.relkind='r')")
PHANTOM_DELETE = ("DELETE FROM dvk_private._dvk_schema s"
                  " WHERE NOT EXISTS (SELECT 1 FROM pg_class c"
                  " JOIN pg_namespace n ON n.oid=c.relnamespace"
                  " WHERE n.nspname='dvk_private' AND c.relname=s.name"
                  " AND c.relkind='r')")
SAFE_ROLE = re.compile(r'^[a-z][a-z0-9_]{0,62}$')


def drop_sql(names):
    """DROP-блок замороженных таблиц (одна транзакция, IF EXISTS)."""
    return '\n'.join(f'DROP TABLE IF EXISTS dvk_private."{name}";' for name in names)


def catalog_heal_script(owner):
    """Транзакция удаления фантомных строк каталога от имени роли-владельца.

    Management API работает от postgres: он АДМИНИСТРАТОР роли-владельца
    каталога (обычно dvk_app_*), но без права SET. Внутри одной транзакции:
    выдать себе SET, переключиться на владельца, удалить фантомы, вернуть
    роль и исходные опции членства. Любая ошибка откатывает всё целиком.
    Возвращает None, если имя роли выглядит подозрительно.
    """
    if not owner or not SAFE_ROLE.fullmatch(owner):
        return None
    return (f'BEGIN;\n'
            f'GRANT {owner} TO postgres WITH SET TRUE;\n'
            f'SET ROLE {owner};\n'
            f'{PHANTOM_DELETE};\n'
            f'RESET ROLE;\n'
            f'GRANT {owner} TO postgres WITH SET FALSE;\n'
            f'COMMIT;')


def heal_catalog(token, reason='чистка'):
    """Удаляет фантомные строки _dvk_schema; печатает результат.

    Роль-владелец выясняется динамически. Если прав на переключение нет —
    печатает предупреждение: фантомы уберёт первый запуск ассистента
    1.3.111+ (self-heal при старте), но до этого старые версии могут падать.
    """
    phantoms = query(token, PHANTOM_COUNT)[0]['n']
    if phantoms == 0:
        print(f'Строк каталога без физических таблиц нет ({reason}).')
        return
    owner = query(token, "SELECT tableowner AS owner FROM pg_tables"
                         " WHERE schemaname='dvk_private' AND tablename='_dvk_schema'")[0]['owner']
    script = catalog_heal_script(owner)
    if script is None:
        print(f'!! Не удалось построить безопасный скрипт для роли {owner!r} — фантомы ({phantoms}) не удалены.')
        print('   Их удалит первый запуск ассистента 1.3.111+ (self-heal каталога при старте).')
        return
    try:
        query(token, script)
        left = query(token, PHANTOM_COUNT)[0]['n']
        print(f'Удалено фантомных строк каталога: {phantoms - left} из {phantoms} ({reason}); осталось {left}.')
    except RuntimeError as error:
        print(f'!! Не удалось удалить фантомные строки каталога ({phantoms}): {error}')
        print('   Их удалит первый запуск ассистента 1.3.111+ (self-heal каталога при старте),')
        print('   но версии 1.3.110 и старше на фантомах могут не стартовать.')


def collect(token):
    """Одним пакетом read-only запросов собирает полное состояние базы."""
    data = {}
    data['size'] = query(token, "SELECT pg_size_pretty(pg_database_size(current_database())) AS pretty,"
                                " pg_database_size(current_database()) AS bytes")[0]
    data['groups'] = query(token, """
        SELECT CASE
                 WHEN table_name ~ '^i[a-f0-9]{20}_m[0-9]{4,5}__' THEN 'installation-spaces'
                 WHEN table_name ~ '^m[0-9]{4,5}__' THEN 'frozen-legacy'
                 WHEN table_name LIKE 'mumu_%' OR table_name LIKE 'global_%' THEN 'registries'
                 ELSE 'shared-tables'
               END AS grp,
               count(*) AS tables, pg_size_pretty(sum(pg_total_relation_size(quote_ident(table_schema)||'.'||quote_ident(table_name))))::text AS pretty,
               sum(pg_total_relation_size(quote_ident(table_schema)||'.'||quote_ident(table_name))) AS bytes
        FROM information_schema.tables
        WHERE table_schema='dvk_private' AND table_type='BASE TABLE'
        GROUP BY 1 ORDER BY 4 DESC""")
    data['top'] = query(token, """
        SELECT table_name, pg_total_relation_size(quote_ident(table_schema)||'.'||quote_ident(table_name)) AS bytes
        FROM information_schema.tables
        WHERE table_schema='dvk_private' AND table_type='BASE TABLE'
        ORDER BY 2 DESC LIMIT 20""")
    data['frozen'] = query(token, """
        SELECT table_name, pg_total_relation_size(quote_ident(table_schema)||'.'||quote_ident(table_name)) AS bytes
        FROM information_schema.tables
        WHERE table_schema='dvk_private' AND table_type='BASE TABLE'
          AND table_name ~ '^m[0-9]{4,5}__' ORDER BY 2 DESC""")
    data['registries'] = query(token, """
        SELECT (SELECT count(*) FROM dvk_private.mumu_greeting_claims) AS greeting_claims,
               (SELECT count(*) FROM dvk_private.mumu_peer_blocks) AS peer_blocks,
               (SELECT count(*) FROM dvk_private.global_peer_city) AS peer_city,
               (SELECT count(*) FROM dvk_private.global_greeting_statistics) AS greeting_statistics""")
    data['health'] = query(token, """
        SELECT (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()) AS connections,
               (SELECT setting::bigint FROM pg_settings WHERE name='max_connections') AS max_connections""")
    data['phantoms'] = query(token, PHANTOM_COUNT)
    return data


def show(data):
    size = data['size']
    percent = 100.0 * size['bytes'] / LIMIT_BYTES
    print(f"База: {size['pretty']} ({megabytes(size['bytes']):.1f} МБ) — {percent:.0f}% лимита 500 МБ")
    print('\nГруппы таблиц (dvk_private):')
    for group in data['groups']:
        print(f"  {group['grp']:<22} {group['tables']:>4} таблиц  {megabytes(group['bytes']):>7.1f} МБ")
    print('\nТоп-20 таблиц:')
    for table in data['top']:
        print(f"  {table['table_name']:<48} {megabytes(table['bytes']):>8.1f} МБ")
    if data['frozen']:
        frozen_bytes = sum(float(table['bytes']) for table in data['frozen'])
        print(f"\nЗамороженных старых таблиц m<порт>__: {len(data['frozen'])} шт., "
              f"{megabytes(frozen_bytes):.1f} МБ — можно освободить командой clean")
    else:
        print('\nЗамороженных старых таблиц нет — чистить нечего.')
    registries = data['registries'][0]
    print(f"\nЗащитные реестры (не удаляются): приветствия {registries['greeting_claims']}, "
          f"запреты {registries['peer_blocks']}, города {registries['peer_city']}, "
          f"статистика {registries['greeting_statistics']}")
    health = data['health'][0]
    print(f"Соединений: {health['connections']} из {health['max_connections']}")
    phantoms = data['phantoms'][0]['n'] if data.get('phantoms') else 0
    if phantoms:
        print(f"\n!! Строк каталога _dvk_schema без физических таблиц: {phantoms}.")
        print('   Это ломает старт ассистента 1.3.110 и старше (cloud-schema-missing);')
        print('   лечится командой clean или первым запуском ассистента 1.3.111+.')
    else:
        print('\nКаталог _dvk_schema синхронен с физическими таблицами.')
    return percent


def clean(token):
    frozen = query(token, "SELECT table_name FROM information_schema.tables"
                          " WHERE table_schema='dvk_private' AND table_type='BASE TABLE'"
                          " AND table_name ~ '^m[0-9]{4,5}__' ORDER BY table_name")
    if not frozen:
        print('Замороженных таблиц нет — чистить нечего.')
        return
    names = [row['table_name'] for row in frozen]
    if len(names) > 500:
        sys.exit(f'Подозрительно много «замороженных» таблиц ({len(names)}) — остановка из безопасности.')
    before = query(token, "SELECT pg_database_size(current_database()) AS bytes")[0]['bytes']
    drops = drop_sql(names)
    query(token, f'BEGIN;\n{drops}\nCOMMIT;')
    print(f'Удалено {len(names)} замороженных таблиц m<порт>__.')
    # Строки каталога для удалённых таблиц становятся фантомами — убираем сразу,
    # иначе старт ассистента умирает на journal-initialization (v1.3.111).
    heal_catalog(token, reason='после удаления таблиц')
    query(token, 'VACUUM ANALYZE;')
    print('VACUUM ANALYZE завершён.')
    after = query(token, "SELECT pg_database_size(current_database()) AS bytes")[0]['bytes']
    print(f'Размер базы: {megabytes(before):.1f} МБ → {megabytes(after):.1f} МБ '
          f'(освобождено {megabytes(before - after):.1f} МБ)')


def write_report(data, percent):
    directory = Path(__file__).resolve().parents[1] / 'reports'
    directory.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    payload = dict(stamp=stamp, project=PROJECT, region=REGION,
                   percent_of_limit=round(percent, 1), **data)
    path = directory / f'db-maintenance-{stamp}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'\nОтчёт сохранён: {path}')


def main():
    command = next((arg for arg in sys.argv[1:] if not arg.startswith('-')), 'status')
    if command not in ('status', 'clean', 'vacuum', 'report'):
        sys.exit(f'Неизвестная команда: {command}\nДоступно: status | clean | vacuum | report')
    token = load_token()
    if command == 'clean':
        clean(token)
        return
    if command == 'vacuum':
        query(token, 'VACUUM ANALYZE;')
        print('VACUUM ANALYZE завершён.')
        return
    data = collect(token)
    percent = show(data)
    if command == 'report':
        write_report(data, percent)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        message = str(error)
        if 'QUERY-DENIED' in message or 'permission' in message.lower():
            sys.exit(f'Доступ к SQL-эндпоинту отклонён:\n{message}')
        raise
