@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -STA -File "%~dp0mumu-connect.ps1"
if errorlevel 1 (
  echo Script did not start. Do not disable Windows security policies.
  pause
)
endlocal
