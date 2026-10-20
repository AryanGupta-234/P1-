@echo off
title SENTINEL installer
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs" & exit /b)
set "DEST=%ProgramFiles%\Sentinel"
echo Installing SENTINEL to "%DEST%" ...
xcopy /E /I /Y /Q "%~dp0*" "%DEST%\" >nul
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python not found - installing Python 3.12 with winget ...
  winget install -e --id Python.Python.3.12 --scope machine --silent --accept-package-agreements --accept-source-agreements
  echo.
  echo Python installed. Close this window and run install.bat again.
  pause & exit /b
)
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
cd /d "%DEST%"
%PY% agent.py install
echo.
echo Done. SENTINEL starts at interactive user logon, restarts after failure, and the SENTINEL shortcut is on your desktop.
pause