@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "config.json" copy /y "config.example.json" "config.json" >nul
if not exist "config.json" (
    echo Cannot create config.json. Extract ZIP to a writable folder first.
    goto done
)
rem No elevation, installation or ExecutionPolicy override.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -File "%~dp0diagnose.ps1"
set "RUN_CODE=%errorlevel%"
if "%RUN_CODE%"=="0" goto report
if "%RUN_CODE%"=="2" goto report
echo.
echo If PowerShell says scripts are disabled or blocked by policy,
echo contact your administrator. Do not disable security controls.
echo If diagnostics did not start, an existing report may be from a previous run.
:report
if exist "reports\diagnostic.json" start "" notepad.exe "reports\diagnostic.json"
:done
echo.
pause
endlocal
