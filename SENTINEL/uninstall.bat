@echo off
setlocal EnableExtensions
title SENTINEL - Uninstall

net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
  exit /b 0
)

set "DEST=%ProgramFiles%\Sentinel"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo ERROR: Python 3 is not available; cannot cleanly remove the agent task.
  echo Do not delete the application directory until the task has been removed.
  pause
  exit /b 1
)

if exist "%DEST%\agent.py" (
  %PY% "%DEST%\agent.py" uninstall
  if errorlevel 1 (
    echo ERROR: SENTINEL agent/task removal failed.
    pause
    exit /b 1
  )
  rd /s /q "%DEST%"
  if exist "%DEST%" (
    echo ERROR: Could not remove all application files from "%DEST%".
    pause
    exit /b 1
  )
)

echo.
echo SENTINEL application files, logon task and shortcuts have been removed.
echo Settings, SQLite history and traces are preserved in %ProgramData%\Sentinel.
echo Delete that folder manually only if you also want to erase all local history.
echo.
pause
exit /b 0
