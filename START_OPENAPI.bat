@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "openapi.config.json" copy /y "openapi.config.example.json" "openapi.config.json" >nul
if not exist "openapi.config.json" (
    echo Cannot create configuration. Extract ZIP to a writable folder first.
    goto done
)
rem Run only on your own authorized laptop. No elevation or policy override.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -File "%~dp0openapi.ps1"
set "RUN_CODE=%errorlevel%"
if "%RUN_CODE%"=="0" goto report
if "%RUN_CODE%"=="2" goto report
echo.
echo If PowerShell is blocked by policy, stop and ask the device owner.
echo Do not disable security controls. An existing report may be from an old run.
:report
if exist "reports\openapi-diagnostic.json" start "" notepad.exe "reports\openapi-diagnostic.json"
:done
echo.
pause
endlocal
