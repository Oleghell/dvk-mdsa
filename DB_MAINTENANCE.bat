@echo off
rem ============================================================
rem  Готовый воркфлоу обслуживания базы Supabase DvkAssistant.
rem  Токен Management API кладётся в config\supabase-management.token
rem  (одна строка; файл в .gitignore и не попадает в коммит)
rem  либо в переменную окружения SUPABASE_ACCESS_TOKEN.
rem
rem  Команды (запускать без аргументов = status):
rem    DB_MAINTENANCE.bat            - состояние базы
rem    DB_MAINTENANCE.bat clean      - чистка замороженных таблиц + вакуум
rem    DB_MAINTENANCE.bat vacuum     - только VACUUM ANALYZE
rem    DB_MAINTENANCE.bat report     - состояние + JSON-отчёт в reports\
rem ============================================================
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 tools\supabase_maintenance.py %*
) else (
    python tools\supabase_maintenance.py %*
)
pause
