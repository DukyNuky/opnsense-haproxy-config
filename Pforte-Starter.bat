@echo off
setlocal
chcp 65001 >nul 2>&1
title Pforte
cd /d "%~dp0"

if not exist "pforte.py" goto :missing

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :found
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :found
goto :nopython

:found
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 goto :oldpython
%PY% pforte.py %*
if errorlevel 1 pause
exit /b 0

:missing
echo.
echo   pforte.py fehlt. Diese Datei muss im selben Ordner liegen.
echo.
pause
exit /b 1

:nopython
echo.
echo   Python wurde nicht gefunden.
echo   Bitte Python 3 installieren: https://www.python.org/downloads/
echo   Wichtig: beim Setup "Add python.exe to PATH" ankreuzen.
echo.
pause
exit /b 1

:oldpython
echo.
echo   Python ist zu alt - gebraucht wird 3.9 oder neuer.
echo.
pause
exit /b 1
