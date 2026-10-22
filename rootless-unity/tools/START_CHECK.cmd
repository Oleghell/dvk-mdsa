@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-MoreLogin-Format.ps1"
if errorlevel 1 pause
