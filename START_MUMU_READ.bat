@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -File "%~dp0mumu-read.ps1" -Port 5555
if errorlevel 1 (
  echo Read stopped. See reports/mumu-read-diagnostic.json. No messages were sent.
)
pause
endlocal
