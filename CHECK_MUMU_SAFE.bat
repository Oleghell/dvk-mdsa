@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo MuMu safe check - read-only preflight
echo ============================================
where py >nul 2>&1
if errorlevel 1 (
  echo Python Launcher (py) not found. Install Python 3.11+ and try again.
  goto done
)
set "PYTHONPATH=%CD%\mumu-navigation;%PYTHONPATH%"
echo.
echo [1/2] Running local unit tests...
py -3 -m unittest discover -s mumu-navigation\tests -v
if errorlevel 1 (
  echo.
  echo Some tests failed. Do not treat the build as production-ready.
  goto done
)
echo.
echo [2/2] Checking ADB and MuMu connection (read-only)...
py -3 mumu-navigation\production_readiness.py --pretty
if errorlevel 1 (
  echo.
  echo The ADB/device check did not pass. This check does not change device state.
)
:done
echo.
pause
endlocal
