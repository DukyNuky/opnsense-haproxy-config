@echo off
setlocal
chcp 65001 >nul 2>&1
title HAProxy - OPNsense
rem Startet die Oberflaeche. Liegt im selben Ordner wie die .py-Dateien.
cd /d "%~dp0"

if not exist "haproxy_gui.py" goto :missing
if not exist "opnsense_haproxy.py" goto :missing

rem Python suchen: erst der offizielle Launcher, dann python im PATH
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :found
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :found
goto :nopython

:found
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if errorlevel 1 goto :oldpython
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :notk

%PY% haproxy_gui.py %*
if errorlevel 1 goto :crashed
exit /b 0

:missing
echo.
echo   Die Programmdateien fehlen.
echo.
echo   Diese .bat muss im selben Ordner liegen wie haproxy_gui.py
echo   und opnsense_haproxy.py.
echo.
pause
exit /b 1

:nopython
echo.
echo   Python wurde nicht gefunden.
echo.
echo   Bitte Python 3 installieren: https://www.python.org/downloads/
echo   Wichtig: beim Setup "Add python.exe to PATH" ankreuzen.
echo.
pause
exit /b 1

:oldpython
echo.
echo   Das gefundene Python ist zu alt - gebraucht wird 3.8 oder neuer.
echo.
%PY% --version
echo.
echo   Neuere Version: https://www.python.org/downloads/
echo.
pause
exit /b 1

:notk
echo.
echo   Dem Python fehlt das Modul tkinter.
echo.
echo   Python neu installieren und dabei "tcl/tk and IDLE" ausgewaehlt
echo   lassen - das ist die Standardeinstellung des Installers.
echo.
pause
exit /b 1

:crashed
echo.
echo   Das Programm wurde mit einem Fehler beendet ^(siehe oben^).
echo.
pause
exit /b 1
