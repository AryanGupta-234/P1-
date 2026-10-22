@echo off
setlocal EnableExtensions DisableDelayedExpansion
title SENTINEL - Versioned Uninstaller
set "SENTINEL_UNINSTALLER=%~f0"

powershell -NoLogo -NoProfile -NonInteractive -Command "$id=[Security.Principal.WindowsIdentity]::GetCurrent(); $p=[Security.Principal.WindowsPrincipal]::new($id); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 goto :elevate
goto :admin_ok

:elevate
echo Requesting Windows administrator permission...
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath $env:SENTINEL_UNINSTALLER -Verb RunAs -Wait -PassThru; exit [int]$p.ExitCode"
if errorlevel 1 goto :elevation_failed
exit /b 0

:elevation_failed
echo.
echo ERROR: The elevated uninstaller did not complete successfully.
pause
exit /b 1

:admin_ok
set "ROOT=%ProgramFiles%\Sentinel"
set "AGENT="
set "PYTHON="
set "VERSION="

if exist "%ROOT%\active-version.txt" set /p "VERSION="<"%ROOT%\active-version.txt"
if defined VERSION (
  echo(%VERSION%| findstr /R /X "[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*" >nul
  if errorlevel 1 (
    echo WARNING: The active version marker is invalid. Falling back to legacy detection.
    set "VERSION="
  )
)
if defined VERSION (
  set "AGENT=%ROOT%\versions\%VERSION%\agent.py"
  set "PYTHON=%ROOT%\versions\%VERSION%\.venv\Scripts\python.exe"
)

if defined VERSION if exist "%AGENT%" if exist "%PYTHON%" goto :run_uninstaller

rem Backward compatibility for the pre-versioned installation layout.
if exist "%ROOT%\agent.py" (
  set "AGENT=%ROOT%\agent.py"
  set "PYTHON="
)
if defined AGENT goto :run_uninstaller

echo ERROR: No installed SENTINEL agent entry point was found at "%ROOT%".
echo The application folder has not been deleted.
pause
exit /b 1

:run_uninstaller
echo.
echo ============================================================
echo  SENTINEL - Uninstall
echo ============================================================
if defined VERSION echo Installed release: %VERSION%
echo Removing scheduled task, Desktop shortcut and all Start Menu shortcuts...
if defined PYTHON goto :run_versioned_python
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo ERROR: Python 3 was not found. The installation was not removed.
  pause
  exit /b 1
)
%PY% "%AGENT%" uninstall
goto :uninstall_result

:run_versioned_python
"%PYTHON%" "%AGENT%" uninstall

:uninstall_result
if errorlevel 1 goto :uninstall_failed

echo Removing installed version folders...
rd /s /q "%ROOT%"
if exist "%ROOT%" (
  echo ERROR: Could not remove all application version folders.
  echo ProgramData history remains untouched.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  SENTINEL UNINSTALLED SUCCESSFULLY
echo ============================================================
echo Application versions, task and shortcuts have been removed.
echo Settings, SQLite history and traces remain in %ProgramData%\Sentinel.
echo Delete that folder manually only if you intentionally want to erase local data.
echo.
pause
exit /b 0

:uninstall_failed
echo ERROR: Task/shortcut removal failed. Application files were preserved.
pause
exit /b 1
