"""SENTINEL - always-on Windows gaming/performance guardian.
  python agent.py            run in foreground
  python agent.py --demo     synthetic telemetry (try the UI anywhere)
  python agent.py install    install an interactive-user logon task (auto-restart) + desktop shortcut
  python agent.py uninstall  remove task and shortcut
  python agent.py open       open the HUD window
"""
import atexit, os, subprocess, sys, time, webbrowser

# A demo run must never touch the installed production database in
# %ProgramData%\Sentinel. Select a per-user writable store before importing
# sentinel.core (which initializes SQLite at import time).
if "--demo" in sys.argv[1:]:
    _demo_root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    os.environ.setdefault("SENTINEL_HOME", os.path.join(_demo_root, "SentinelDemo"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import core
from sentinel.core import CFG, IS_WIN, log

TASK = "SentinelAgent"
NO_WIN = 0x08000000 if IS_WIN else 0
HERE = os.path.dirname(os.path.abspath(__file__))


def url():
    return f"http://127.0.0.1:{CFG['port']}/?t={CFG['token']}"


def open_hud():
    if IS_WIN:
        for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
            if os.path.exists(exe):
                subprocess.Popen([exe, f"--app={url()}", "--window-size=1480,920"]); return
    webbrowser.open(url())


def pw(cmd):
    # Resolve the real Windows PowerShell executable; PATH is often truncated in
    # elevated/scheduled-task contexts and a bare "powershell" can raise WinError 2.
    from sentinel.winutil import powershell
    return powershell(cmd, timeout=45)


def install():
    if not IS_WIN:
        print("install is Windows-only"); return
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{os.path.abspath(__file__)}" install', None, 1); return
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if pyw == sys.executable or not os.path.exists(pyw):
        pyw = sys.executable
    script = os.path.abspath(__file__)
    # UI Automation and Windows notifications require the signed-in user's
    # interactive desktop. A SYSTEM/AtStartup task runs in Session 0 and cannot
    # truthfully inspect or notify that desktop.
    ps = f"""
$ErrorActionPreference = 'Stop'
$loggedOn = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).UserName
if (-not $loggedOn) {{ $loggedOn = [Security.Principal.WindowsIdentity]::GetCurrent().Name }}
$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument '"{script}"' -WorkingDirectory '{HERE}'
$t = New-ScheduledTaskTrigger -AtLogOn -User $loggedOn
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$p = New-ScheduledTaskPrincipal -UserId $loggedOn -LogonType Interactive -RunLevel Highest
Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Principal $p -Description 'SENTINEL interactive Windows telemetry agent' | Out-Null
$store = Join-Path $env:ProgramData 'Sentinel'
New-Item -ItemType Directory -Force -Path $store | Out-Null
# Remove broad inherited read access to process/event/setting telemetry. The
# interactive user gets Modify; SYSTEM and local Administrators get Full Control.
icacls $store /inheritance:r | Out-Null
icacls $store /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "${{loggedOn}}:(OI)(CI)M" /T | Out-Null
if ($LASTEXITCODE -ne 0) {{ throw "Could not secure SENTINEL data directory ACL (icacls exit $LASTEXITCODE)" }}
Start-ScheduledTask -TaskName '{TASK}'
Write-Output "Task registered for $loggedOn (interactive logon); SQLite storage: $store (user/SYSTEM/Administrators only)"
"""
    r = pw(ps)
    print(r.stdout or r.stderr or "task registered")
    if r.returncode != 0:
        print("SENTINEL installation failed; see PowerShell error above.")
        return
    pw(f"""$w=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('CommonDesktopDirectory'); $shortcut=Join-Path $desktop 'SENTINEL.lnk'; $l=$w.CreateShortcut($shortcut);
$l.TargetPath='{pyw}'; $l.Arguments='"{script}" open'; $l.WorkingDirectory='{HERE}'; $l.Description='Open SENTINEL HUD'; $l.Save()""")
    time.sleep(2)
    print("SENTINEL installed for the signed-in desktop. It starts at user logon and restarts after process exit; it does not run in Session 0 before login.")
    open_hud()


def uninstall():
    pw(f"Stop-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false -ErrorAction SilentlyContinue;"
       "Remove-Item ([Environment]::GetFolderPath('CommonDesktopDirectory')+'\\SENTINEL.lnk') -ErrorAction SilentlyContinue")
    print("SENTINEL removed.")


def port_busy():
    import socket
    s = socket.socket(); s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", CFG["port"])) == 0
    finally:
        s.close()


def main():
    a = sys.argv[1:]
    if a and a[0] == "install": return install()
    if a and a[0] == "uninstall": return uninstall()
    if a and a[0] == "open": return open_hud()
    if port_busy():           # already running (task + manual start) - just open the HUD
        return open_hud()
    from sentinel import collectors, brain, ai, intel, server, advanced
    # Restore the trace catalog from durable SQLite metadata after agent restarts.
    try:
        core.STATE["traces"] = [
            {"file": row[0], "ts": row[1], "mb": round(row[2] / 1048576, 1), "source": row[3], "exists": os.path.isfile(row[0])}
            for row in core.db("SELECT file_path,ts,size_bytes,source FROM trace_archive ORDER BY ts DESC LIMIT 200")
        ]
    except Exception as exc:
        log("storage", f"ETW trace catalog restore failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")
    # A clean shutdown closes the run row; an unclosed row from an earlier process
    # is preserved as an interrupted run for diagnosis after crashes/power loss.
    db = core.db
    db("UPDATE agent_runs SET stopped_at=?,exit_reason=? WHERE stopped_at IS NULL",
       (time.time(), "previous process ended without final shutdown acknowledgement"))
    rows = db("INSERT INTO agent_runs(started_at,pid,executable,run_mode) VALUES(?,?,?,?)",
       (time.time(), os.getpid(), sys.executable, "windows-interactive" if IS_WIN else ("synthetic-demo" if "--demo" in a else "non-windows-demo")))
    run_id = db("SELECT MAX(id) FROM agent_runs")[0][0]
    def close_run():
        db("UPDATE agent_runs SET stopped_at=?,exit_reason=? WHERE id=? AND stopped_at IS NULL",
           (time.time(), "normal process shutdown", run_id))
    atexit.register(close_run)
    log("core", f"SENTINEL starting (pid {os.getpid()}, {'Windows' if IS_WIN else 'demo'}, run {run_id})", "ok")
    advanced.start()
    atexit.register(advanced.shutdown)
    collectors.start_all(demo="--demo" in a)
    core.thread(brain.brain_loop, "brain")
    core.thread(ai.ai_loop, "ai")
    core.thread(intel.watch_loop, "intel")
    if "--demo" in a or not IS_WIN:
        print("HUD:", url())
    try:
        server.serve()
    finally:
        advanced.shutdown()
        close_run()


if __name__ == "__main__":
    main()