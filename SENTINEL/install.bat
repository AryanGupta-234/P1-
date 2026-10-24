@echo off
setlocal EnableExtensions DisableDelayedExpansion
title SENTINEL - Versioned Installer

set "SENTINEL_INSTALLER=%~f0"
rem Detect an elevated token explicitly; net session is not a reliable UAC test.
powershell -NoLogo -NoProfile -NonInteractive -Command "$id=[Security.Principal.WindowsIdentity]::GetCurrent(); $p=[Security.Principal.WindowsPrincipal]::new($id); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 (
  echo Requesting Windows administrator permission...
  powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath $env:SENTINEL_INSTALLER -Verb RunAs -Wait -PassThru; exit [int]$p.ExitCode"
  if errorlevel 1 goto :elevation_failed
  exit /b 0
)
goto :admin_ok

:elevation_failed
echo.
echo ERROR: The elevated installer did not complete successfully.
echo Review the elevated installer window for its diagnostic message.
pause
exit /b 1

:admin_ok

for %%I in ("%~dp0.") do set "SRC=%%~fI"
set "ROOT=%ProgramFiles%\Sentinel"
set "VERSIONS=%ROOT%\versions"
set "VERSION_FILE=%SRC%\VERSION"

echo.
echo ============================================================
echo  SENTINEL - Versioned Windows Installer
echo ============================================================
echo Source : "%SRC%"
echo Root   : "%ROOT%"
echo.

if not exist "%VERSION_FILE%" (
  echo ERROR: Release VERSION file is missing: "%VERSION_FILE%"
  goto :fail
)
set /p "VERSION="<"%VERSION_FILE%"
if not defined VERSION (
  echo ERROR: VERSION file is empty.
  goto :fail
)
echo(%VERSION%| findstr /R /X "[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*" >nul
if errorlevel 1 (
  echo ERROR: Invalid release version "%VERSION%". Expected MAJOR.MINOR.PATCH, for example 1.0.1.
  goto :fail
)
set "VERSION_DIR=%VERSIONS%\%VERSION%"
set "STAGING_DIR=%VERSIONS%\.staging-%VERSION%"

echo Release version : %VERSION%
echo Version folder  : "%VERSION_DIR%"
echo.
echo Existing version folders are immutable. A new release installs into
echo a new version folder; previous versions are retained for rollback.
echo User settings, SQLite history and traces stay in %ProgramData%\Sentinel.
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
  if errorlevel 1 (
    echo ERROR: Python installation failed.
    goto :fail
  )
  call :findPython
)
if not defined PY (
  echo ERROR: Python installation could not be detected.
  echo Install Python 3.11 or 3.12 and rerun install.bat.
  goto :fail
)

echo [1/6] Stopping any currently registered SENTINEL agent...
%PY% "%SRC%\agent.py" stop
if errorlevel 1 (
  echo ERROR: The previous SENTINEL agent could not be stopped safely.
  echo No installed version files have been changed.
  goto :fail
)

if not exist "%VERSIONS%" mkdir "%VERSIONS%"
if errorlevel 1 (
  echo ERROR: Could not create the versions directory.
  goto :fail
)

set "FRESH_VERSION=0"
if exist "%VERSION_DIR%" (
  echo [2/6] Release %VERSION% already exists - verifying without overwriting it...
  if not exist "%VERSION_DIR%\VERSION" (
    echo ERROR: The existing version folder has no VERSION marker.
    echo It has been left untouched. Choose a new release version.
    goto :fail
  )
  findstr /R /X /C:"%VERSION%" "%VERSION_DIR%\VERSION" >nul
  if errorlevel 1 (
    echo ERROR: Existing folder version mismatch. Nothing was overwritten.
    goto :fail
  )
  if not exist "%VERSION_DIR%\agent.py" goto :incomplete
  if not exist "%VERSION_DIR%\sentinel\core.py" goto :incomplete
  if not exist "%VERSION_DIR%\sentinel\maintenance.py" goto :incomplete
  if not exist "%VERSION_DIR%\sentinel\approval_engine.py" goto :incomplete
  if not exist "%VERSION_DIR%\ui\index.html" goto :incomplete
  if not exist "%VERSION_DIR%\requirements.txt" goto :incomplete
  if not exist "%VERSION_DIR%\.venv\Scripts\python.exe" goto :incomplete
  echo Immutable version files and Python environment verified. Reusing this version folder.
) else (
  set "FRESH_VERSION=1"
  echo [2/6] Preparing fresh version %VERSION% in a staging folder...
  if exist "%STAGING_DIR%" rmdir /s /q "%STAGING_DIR%"
  mkdir "%STAGING_DIR%"
  if errorlevel 1 (
    echo ERROR: Could not create the version staging folder.
    goto :fail
  )
  robocopy "%SRC%" "%STAGING_DIR%" /E /R:2 /W:2 /COPY:DAT /DCOPY:DAT /NP /NFL /NDL /NJH /NJS /XD ".git" ".venv" "__pycache__" ".pytest_cache" /XF "*.pyc"
  rem Robocopy codes 0-7 mean success; 8 or above means failure.
  if errorlevel 8 (
    echo ERROR: Release file copy failed. The incomplete staging folder will be removed.
    goto :fail
  )
  if not exist "%STAGING_DIR%\VERSION" (
    echo ERROR: VERSION marker was not copied into the staging folder.
    goto :fail
  )
  if not exist "%STAGING_DIR%\agent.py" (
    echo ERROR: Agent entry point is missing from the staged release.
    goto :fail
  )
  if not exist "%STAGING_DIR%\sentinel\maintenance.py" (
    echo ERROR: SENTINEL maintenance engine is missing from the staged release.
    goto :fail
  )
  if not exist "%STAGING_DIR%\sentinel\approval_engine.py" (
    echo ERROR: SENTINEL approval engine is missing from the staged release.
    goto :fail
  )
  if not exist "%STAGING_DIR%\sentinel\core.py" (
    echo ERROR: SENTINEL runtime files are incomplete.
    goto :fail
  )
  if not exist "%STAGING_DIR%\ui\index.html" (
    echo ERROR: Dashboard files are missing from the staged release.
    goto :fail
  )
  move "%STAGING_DIR%" "%VERSION_DIR%" >nul
  if errorlevel 1 (
    echo ERROR: Could not finalize the new release application files.
    if exist "%VERSION_DIR%" rmdir /s /q "%VERSION_DIR%"
    goto :fail
  )
  echo Fresh application files published. The release-specific environment is created in place next.
)

set "VENV_PY=%VERSION_DIR%\.venv\Scripts\python.exe"
if "%FRESH_VERSION%"=="1" (
  echo [3/6] Creating the isolated Python environment in the final release folder...
  %PY% -m venv "%VERSION_DIR%\.venv"
  if errorlevel 1 goto :fresh_environment_failed
  if not exist "%VENV_PY%" goto :fresh_environment_failed
  echo [4/6] Installing dependencies into the new release environment...
  "%VENV_PY%" -m pip install --disable-pip-version-check --retries 3 --timeout 30 -r "%VERSION_DIR%\requirements.txt"
  if errorlevel 1 goto :fresh_environment_failed
) else (
  echo [3/6] Reusing the immutable %VERSION% Python environment...
  echo [4/6] Dependency files are not modified for an existing release.
  if not exist "%VENV_PY%" goto :incomplete
)

echo [5/6] Registering and verifying task, shortcuts and administrator mode...
cd /d "%VERSION_DIR%"
if errorlevel 1 (
  echo ERROR: Could not enter the version directory.
  goto :fail
)
"%VENV_PY%" "%VERSION_DIR%\agent.py" install
if errorlevel 1 (
  echo ERROR: SENTINEL did not pass task/shortcut/agent verification.
  echo Review the diagnostic output above. Existing version folders were not overwritten.
  goto :fail
)

rem Update the stable active-version pointer only after the new version is verified.
>"%ROOT%\active-version.txt.tmp" echo %VERSION%
move /y "%ROOT%\active-version.txt.tmp" "%ROOT%\active-version.txt" >nul
if errorlevel 1 (
  echo ERROR: SENTINEL installed, but the active-version pointer could not be updated.
  echo The verified version remains at "%VERSION_DIR%".
  goto :fail
)

echo.
echo ============================================================
echo  SENTINEL %VERSION% - INSTALLATION COMPLETE
echo ============================================================
echo Status       : SUCCESS - task, shortcuts and elevated agent verified
echo Installed at: "%VERSION_DIR%"
echo Desktop      : SENTINEL shortcut
echo Start Menu   : SENTINEL (user + all users; searchable directly from Start)
echo Start Menu   : Programs ^> SENTINEL (organized shortcut group)
echo Agent        : Running with highest available privileges
echo Data         : "%ProgramData%\Sentinel" (preserved)
echo Previous versions were not overwritten or removed.
echo.
echo Open SENTINEL later from the Desktop or Start Menu shortcut.
echo.
pause
exit /b 0

:fresh_environment_failed
echo ERROR: The new SENTINEL %VERSION% Python environment or dependency setup failed.
echo Removing only this unpublished version folder. Previous releases remain untouched.
if exist "%VERSION_DIR%" rmdir /s /q "%VERSION_DIR%"
goto :fail

:incomplete
echo ERROR: The existing release folder is incomplete.
echo It was not overwritten or deleted. Bump VERSION to create a fresh release folder.
goto :fail

:findPython
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.12 --version >nul 2>&1
  if not errorlevel 1 set "PY=py -3.12"
  if not defined PY (
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 set "PY=py -3.11"
  )
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
if defined STAGING_DIR if exist "%STAGING_DIR%" rmdir /s /q "%STAGING_DIR%"
echo.
echo ============================================================
echo  SENTINEL INSTALLATION FAILED
echo ============================================================
echo Check the error above. No previous version folder or
echo ProgramData history was intentionally overwritten or removed.
echo.
pause
exit /b 1
