@echo off
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs" & exit /b)
cd /d "%ProgramFiles%\Sentinel" && (py -3 agent.py uninstall || python agent.py uninstall)
echo Removed. History stays in %ProgramData%\Sentinel - delete that folder to wipe it.
pause