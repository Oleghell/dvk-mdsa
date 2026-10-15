@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "openapi.config.json" copy /y "openapi.config.example.json" "openapi.config.json" >nul
if not exist "openapi.config.json" (
    echo Cannot create configuration. Extract ZIP to your writable local folder.
    goto done
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -File "%~dp0openapi.ps1" -CheckFirstAdb
if errorlevel 1 echo See the latest report or error above. Do not disable security controls.
if exist "reports\adb-diagnostic.json" start "" notepad.exe "reports\adb-diagnostic.json"
:done
echo.
pause
endlocal
