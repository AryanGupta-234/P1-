@echo off
setlocal EnableExtensions
title SENTINEL - Install / Upgrade

rem Elevate once. The elevated copy keeps the original source directory.
net session >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator permission...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
  if errorlevel 1 (
    echo.
    echo ERROR: Administrator permission was not granted.
    pause
    exit /b 1
  )
  exit /b 0
)

for %%I in ("%~dp0.") do set "SRC=%%~fI"
set "DEST=%ProgramFiles%\Sentinel"

echo.
echo ============================================================
echo  SENTINEL Windows Installer
echo  Install / in-place upgrade
echo ============================================================
echo Source : "%SRC%"
echo Target : "%DEST%"
echo.
echo Your settings, SQLite history, traces and run records are
echo stored separately in %ProgramData%\Sentinel and are preserved.
echo.

call :findPython
if not defined PY (
  echo Python 3 was not found. Installing Python 3.12 with winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo ERROR: winget is unavailable. Install Python 3.11 or 3.12 and rerun install.bat.
    goto :fail
  )
  winget install -e --id Python.Python.3.12 --scope machine --silent --accept-package-agreements --accept-source-agreements
  call :findPython
)
if not defined PY (
  echo ERROR: Python installation could not be detected.
  echo Close this window, confirm Python 3.12 is installed, and rerun install.bat.
  goto :fail
)

if exist "%DEST%\agent.py" (
  echo [1/5] Gracefully stopping the existing agent and logon task...
  %PY% "%SRC%\agent.py" stop
  if errorlevel 1 (
    echo ERROR: The existing agent did not stop safely.
    echo No application files have been replaced. Close the SENTINEL task and rerun this installer.
    goto :fail
  )
) else (
  echo [1/5] No previous SENTINEL installation found.
)

echo [2/5] Updating Python dependencies...
%PY% -m pip install --upgrade --disable-pip-version-check --retries 3 --timeout 30 -r "%SRC%\requirements.txt"
if errorlevel 1 (
  echo ERROR: Python dependency installation failed.
  echo The existing application files and ProgramData history were not replaced.
  if exist "%DEST%\agent.py" powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'SentinelAgent' -ErrorAction SilentlyContinue"
  goto :fail
)

if /I "%SRC%"=="%DEST%" (
  echo [3/5] Source is already the install directory - skipping file copy.
) else (
  echo [3/5] Updating application files in place...
  if not exist "%DEST%" mkdir "%DEST%"
  if errorlevel 1 (
    echo ERROR: Could not create "%DEST%".
    goto :fail
  )
  robocopy "%SRC%" "%DEST%" /MIR /R:2 /W:2 /COPY:DAT /DCOPY:DAT /NP /NFL /NDL /NJH /NJS /XD ".git" ".venv" "__pycache__" ".pytest_cache" /XF "*.pyc"
  rem Robocopy codes 0-7 are success / copy results; 8+ means failure.
  if errorlevel 8 (
    echo ERROR: Application file update failed (Robocopy returned a failure code).
    echo Your ProgramData settings/history have not been deleted.
    powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'SentinelAgent' -ErrorAction SilentlyContinue"
    goto :fail
  )
)

cd /d "%DEST%"
if errorlevel 1 (
  echo ERROR: Could not enter "%DEST%".
  goto :fail
)

echo [4/5] Registering the interactive agent and app launchers...
%PY% "%DEST%\agent.py" install
if errorlevel 1 (
  echo ERROR: Agent task registration or desktop app launch failed.
  echo Check Task Scheduler ^> SentinelAgent and %ProgramData%\Sentinel.
  goto :fail
)

echo.
echo [5/5] Installation / upgrade completed.
echo.
echo SENTINEL is running. Its app window should now be open.
echo Launch it later from:
echo   - Desktop: SENTINEL
echo   - Start Menu: SENTINEL ^> SENTINEL
echo.
echo Agent auto-starts at interactive user logon and restarts after failure.
echo Existing settings, history, traces and run records were preserved.
echo.
pause
exit /b 0

:findPython
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 --version >nul 2>&1
  if not errorlevel 1 set "PY=py -3.12"
  if not defined PY (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
  )
)
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 set "PY=python"
  )
)
exit /b 0

:fail
echo.
echo SENTINEL installation did not finish.
echo No ProgramData history/configuration was intentionally removed.
pause
exit /b 1
