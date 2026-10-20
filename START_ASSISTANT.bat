@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "DvkAssistant.exe" (
  start "" "%~dp0DvkAssistant.exe"
) else (
  echo Запускайте DvkAssistant.exe из сборки DvkAssistant-windows-x64 в GitHub Actions.
  echo Исходный ZIP не содержит готового Windows-приложения.
  pause
)
