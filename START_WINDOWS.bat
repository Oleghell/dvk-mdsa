@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "config.json" copy /y "config.example.json" "config.json" >nul
where py >nul 2>nul
if not errorlevel 1 (
    py -3 diagnose.py
    goto done
)
where python >nul 2>nul
if not errorlevel 1 (
    python diagnose.py
    goto done
)
echo Python 3.10+ is required. See README.md for installation.
echo https://www.python.org/downloads/windows/
:done
if exist "reports\diagnostic.json" start "" notepad.exe "reports\diagnostic.json"
echo.
pause
endlocal
