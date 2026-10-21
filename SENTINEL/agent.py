"""SENTINEL Windows agent and desktop application launcher.

Commands:
  python agent.py                 run the local agent in the foreground
  python agent.py --demo           run isolated synthetic telemetry
  python agent.py install          register the interactive logon task and app shortcuts
  python agent.py uninstall        remove the task and shortcuts (keeps ProgramData)
  python agent.py open             open the desktop HUD; starts the agent if needed
  python agent.py stop              gracefully stop the serving agent for upgrades
"""
import atexit
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


# Establish the Windows identity before importing SENTINEL modules that touch
# ProgramData or initialize the runtime database.
IS_WIN = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))


def _admin_error(message):
    """Report an elevation failure even when launched through pythonw.exe."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    elif IS_WIN:
        try:
            ctypes.windll.user32.MessageBoxW(
                None, message, "SENTINEL - Administrator permission required", 0x10
            )
        except Exception:
            pass


def _ensure_admin():
    """Require an elevated Windows token before any SENTINEL CLI action runs.

    Returns None when already elevated, 0 after successfully handing off to an
    elevated process, or 1 when elevation cannot be verified/requested.
    """
    if not IS_WIN:
        return None
    try:
        if bool(ctypes.windll.shell32.IsUserAnAdmin()):
            return None
    except Exception as exc:
        _admin_error(
            "SENTINEL could not verify administrator permissions. "
            f"It will not start without elevation ({type(exc).__name__}: {exc})."
        )
        return 1

    parameters = subprocess.list2cmdline(
        [os.path.abspath(__file__), *sys.argv[1:]]
    )
    try:
        shell_execute = ctypes.windll.shell32.ShellExecuteW
        # ShellExecuteW returns an HINSTANCE (pointer-sized on 64-bit Windows).
        shell_execute.restype = ctypes.c_void_p
        result = shell_execute(
            None, "runas", sys.executable, parameters, HERE, 1
        )
        if result and int(result) > 32:
            return 0
        _admin_error(
            "SENTINEL requires administrator permissions. "
            "Approve the Windows UAC prompt to continue; the current process was not started."
        )
        return 1
    except Exception as exc:
        _admin_error(
            "SENTINEL could not request administrator permissions. "
            f"It will not start without elevation ({type(exc).__name__}: {exc})."
        )
        return 1


if __name__ == "__main__":
    _elevation_result = _ensure_admin()
    if _elevation_result is not None:
        raise SystemExit(_elevation_result)


# Demo telemetry must never touch the installed production database.
if "--demo" in sys.argv[1:]:
    _demo_root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    os.environ.setdefault("SENTINEL_HOME", os.path.join(_demo_root, "SentinelDemo"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sentinel import core
from sentinel.core import CFG, IS_WIN, log

TASK = "SentinelAgent"
HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Sentinel")
VERSIONS_DIR = os.path.join(PROGRAM_DIR, "versions")


def _read_app_version():
    try:
        with open(os.path.join(HERE, "VERSION"), "r", encoding="utf-8") as handle:
            value = handle.read().strip()
        if value and all(part.isdigit() for part in value.split(".")) and len(value.split(".")) == 3:
            return value
    except OSError:
        pass
    return "0.0.0-dev"


APP_VERSION = _read_app_version()
APP_VERSION_DIR = os.path.join(VERSIONS_DIR, APP_VERSION)
os.environ.setdefault("SENTINEL_VERSION", APP_VERSION)
NO_WIN = 0x08000000 if IS_WIN else 0


def base_url():
    return f"http://127.0.0.1:{int(CFG['port'])}"


def url():
    query = urllib.parse.urlencode({"t": CFG["token"]})
    return f"{base_url()}/?{query}"


def _wait_for_agent(timeout=25):
    """Wait for the authenticated local API, not just an open TCP port."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    endpoint = f"{base_url()}/api/status?{urllib.parse.urlencode({'t': CFG['token']})}"
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(endpoint, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=1.5) as response:
                if response.status == 200:
                    payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
                    if isinstance(payload, dict) and payload.get("pid"):
                        return True
        except (OSError, ValueError, urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.35)
    return False


def port_busy():
    import socket
    sock = socket.socket()
    sock.settimeout(0.4)
    try:
        return sock.connect_ex(("127.0.0.1", int(CFG["port"]))) == 0
    finally:
        sock.close()


def pw(command):
    """Run PowerShell through SENTINEL's PATH-independent Windows helper."""
    from sentinel.winutil import powershell
    return powershell(command, timeout=60)


def _ps_quote(value):
    """Quote a value for a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _request_graceful_stop(timeout=18):
    endpoint = f"{base_url()}/api/agent/shutdown?{urllib.parse.urlencode({'t': CFG['token']})}"
    body = json.dumps({"confirmed": True}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
            accepted = response.status in (200, 202) and payload.get("ok") is True
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        return False
    if not accepted:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_busy():
            return True
        time.sleep(0.25)
    return not port_busy()


def _stop_legacy_agent():
    """Fallback for pre-shutdown-endpoint installations during an upgrade.

    Stop the known task first. If it was launched manually, use the active SQLite
    run row plus PID creation time and an agent.py command-line check before
    terminating that exact process. Never kill a process based on port ownership.
    """
    task_result = pw(
        f"$ErrorActionPreference='Stop'; "
        f"$task = Get-ScheduledTask -TaskName {_ps_quote(TASK)} -ErrorAction SilentlyContinue; "
        f"if ($task -and $task.State -notin @('Ready','Disabled')) {{ "
        f"Stop-ScheduledTask -TaskName {_ps_quote(TASK)} -ErrorAction Stop; "
        f"$deadline = (Get-Date).AddSeconds(5); "
        f"do {{ Start-Sleep -Milliseconds 200; $task = Get-ScheduledTask -TaskName {_ps_quote(TASK)} -ErrorAction SilentlyContinue }} "
        f"while ($task -and $task.State -notin @('Ready','Disabled') -and (Get-Date) -lt $deadline); "
        f"if ($task -and $task.State -notin @('Ready','Disabled')) {{ throw 'SentinelAgent task is still active' }} "
        f"}}; Write-Output 'Scheduled task is stopped or absent'"
    )
    if task_result.returncode != 0:
        print("Could not stop the SentinelAgent scheduled task: " + (task_result.stderr or task_result.stdout or "PowerShell failed")[:240])
        return False
    try:
        import psutil
        rows = core.db(
            "SELECT pid,started_at,executable FROM agent_runs "
            "WHERE stopped_at IS NULL ORDER BY id DESC LIMIT 1"
        )
        if rows:
            pid, started_at, executable = rows[0]
            try:
                process = psutil.Process(int(pid))
                created = float(process.create_time())
                command_line = process.cmdline()
                accepted_scripts = {
                    os.path.normcase(os.path.abspath(os.path.join(HERE, "agent.py"))),
                    os.path.normcase(os.path.abspath(os.path.join(PROGRAM_DIR, "agent.py"))),
                }
                versions_root = os.path.join(PROGRAM_DIR, "versions")
                try:
                    for version_name in os.listdir(versions_root):
                        version_script = os.path.join(versions_root, version_name, "agent.py")
                        if os.path.isfile(version_script):
                            accepted_scripts.add(os.path.normcase(os.path.abspath(version_script)))
                except OSError:
                    pass
                exact_agent = any(
                    os.path.basename(str(part).strip('"')).casefold() == "agent.py"
                    and os.path.normcase(os.path.abspath(str(part).strip('"'))) in accepted_scripts
                    for part in command_line
                )
                same_process = (
                    abs(created - float(started_at)) <= 30.0
                    and os.path.normcase(process.exe()) == os.path.normcase(str(executable))
                    and exact_agent
                    and process.pid != os.getpid()
                )
                if same_process:
                    process.terminate()
                    try:
                        process.wait(timeout=6)
                    except psutil.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=4)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
                pass
    except Exception:
        pass
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not port_busy():
            return True
        time.sleep(0.25)
    # A listener may be another application; do not terminate it.
    return not port_busy()


def stop_agent():
    """Stop the logon task and serving process, including one that is still starting."""
    was_listening = port_busy()
    if was_listening and _request_graceful_stop():
        print("SENTINEL stopped gracefully; session rollback and run-close hooks completed.")
        return 0
    # Always stop the registered task, even when it has not opened the local
    # listener yet. The legacy fallback only terminates a PID corroborated by
    # agent_runs, executable identity, creation time and agent.py command line.
    if _stop_legacy_agent():
        if was_listening:
            print("SENTINEL legacy process/task stopped. Any interrupted game session will be recovered from its journal on next start.")
        else:
            print("SENTINEL scheduled task is stopped; no agent listener remains.")
        return 0
    print("Could not stop the existing SENTINEL listener safely. No unrelated process was terminated.")
    return 1


def _launch_hud():
    """Open an app-window in an installed browser, or the default browser."""
    if IS_WIN:
        for exe in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ):
            if os.path.isfile(exe):
                subprocess.Popen(
                    [exe, f"--app={url()}", "--window-size=1480,920"],
                    cwd=HERE, creationflags=NO_WIN,
                )
                return True
    return bool(webbrowser.open(url()))


def _start_agent_background():
    """Start one detached agent process when neither the logon task nor server is up."""
    interpreter = sys.executable
    if IS_WIN:
        candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if os.path.isfile(candidate):
            interpreter = candidate
    flags = 0
    if IS_WIN:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [interpreter, os.path.join(HERE, "agent.py")],
        cwd=HERE,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )


def _running_agent_is_elevated():
    """Read the authenticated runtime integrity flag for an already-running agent."""
    endpoint = f"{base_url()}/api/agent?{urllib.parse.urlencode({'t': CFG['token']})}"
    try:
        request = urllib.request.Request(endpoint, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        runtime = payload.get("runtime") if isinstance(payload, dict) else None
        if isinstance(runtime, dict):
            return runtime.get("is_elevated")
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        pass
    return None


def open_app():
    """Normal user-facing opener: ensure the agent is up, then launch the HUD."""
    agent_ready = _wait_for_agent(1.5)
    if IS_WIN and agent_ready and _running_agent_is_elevated() is not True:
        print("The existing SENTINEL agent is not confirmed elevated; restarting it with administrator permissions.")
        if stop_agent() != 0:
            print("The previous agent could not be stopped safely; refusing to open a non-elevated session.")
            return 1
        agent_ready = False

    if not agent_ready:
        started_by_task = False
        if IS_WIN:
            result = pw(
                f"$ErrorActionPreference='SilentlyContinue'; "
                f"Start-ScheduledTask -TaskName {_ps_quote(TASK)} -ErrorAction SilentlyContinue; "
                f"if ($?) {{ 'TASK_START_REQUESTED' }}"
            )
            started_by_task = bool(result.returncode == 0)
        if not started_by_task or not _wait_for_agent(3):
            try:
                _start_agent_background()
            except Exception as exc:
                print(f"Could not launch the SENTINEL agent: {type(exc).__name__}: {exc}")
                return 1
        if not _wait_for_agent(30):
            print("SENTINEL did not become ready. Check the Windows task and %ProgramData%\\Sentinel logs.")
            return 1
    if not _launch_hud():
        print("SENTINEL is running, but no browser window could be opened.")
        return 1
    return 0


def install():
    """Register this immutable version, create verified launchers and start its agent."""
    if not IS_WIN:
        print("install is Windows-only")
        return 1

    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        print(f"pythonw.exe was not found next to {sys.executable}")
        return 1

    script = os.path.abspath(__file__)
    store = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Sentinel")
    values = {
        "SENTINEL_TASK": TASK,
        "SENTINEL_PYTHONW": pythonw,
        "SENTINEL_SCRIPT": script,
        "SENTINEL_WORKDIR": HERE,
        "SENTINEL_STORE": store,
        "SENTINEL_VERSION": APP_VERSION,
    }
    os.environ.update(values)
    ps = r"""
$ErrorActionPreference = 'Stop'
try {
    $taskName = $env:SENTINEL_TASK
    $pythonw = $env:SENTINEL_PYTHONW
    $script = $env:SENTINEL_SCRIPT
    $workdir = $env:SENTINEL_WORKDIR
    $store = $env:SENTINEL_STORE
    $version = $env:SENTINEL_VERSION

    if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw "Python windowed executable not found: $pythonw" }
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw "Agent script not found: $script" }
    if (-not (Test-Path -LiteralPath (Join-Path $workdir 'ui\index.html') -PathType Leaf)) { throw "Dashboard files are missing from $workdir" }

    $loggedOn = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
    if (-not $loggedOn) {
        throw "Windows did not report an interactive signed-in user. Sign in to the target Windows account and rerun install.bat."
    }
    $userSid = ([System.Security.Principal.NTAccount]::new($loggedOn)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    $userProfile = Get-CimInstance Win32_UserProfile -Filter ("SID='{0}'" -f $userSid) -ErrorAction Stop
    if (-not $userProfile -or -not $userProfile.LocalPath) { throw "Profile path unavailable for interactive user $loggedOn" }
    $userRoot = $userProfile.LocalPath

    # Honour Desktop redirection (including OneDrive) from the actual user's
    # loaded profile instead of assuming C:\Users\name\Desktop.
    $desktop = $null
    $usersHive = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::Users,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $shellFolders = $usersHive.OpenSubKey("$userSid\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        if ($shellFolders) {
            try {
                $desktopValue = $shellFolders.GetValue(
                    'Desktop', $null,
                    [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                )
                if ($desktopValue) {
                    $desktopValue = $desktopValue.Replace('%USERPROFILE%', $userRoot)
                    $desktop = [Environment]::ExpandEnvironmentVariables($desktopValue)
                }
            } finally { $shellFolders.Dispose() }
        }
    } finally { $usersHive.Dispose() }
    if (-not $desktop -or $desktop -match '%[^%]+%') { $desktop = Join-Path $userRoot 'Desktop' }

    $userStartMenu = Join-Path $userRoot 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\SENTINEL'
    $commonStartMenu = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\SENTINEL'
    New-Item -ItemType Directory -Force -Path $desktop, $userStartMenu, $commonStartMenu | Out-Null

    New-Item -ItemType Directory -Force -Path $store | Out-Null
    & icacls.exe $store /inheritance:r | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set SENTINEL data-directory inheritance (icacls $LASTEXITCODE)" }
    & icacls.exe $store /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "$($loggedOn):(OI)(CI)M" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not secure SENTINEL data directory ACL (icacls $LASTEXITCODE)" }

    $action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"{0}"' -f $script) -WorkingDirectory $workdir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $loggedOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $loggedOn -LogonType Interactive -RunLevel Highest

    $oldTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($oldTask) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "SENTINEL $version interactive Windows agent" | Out-Null

    $registered = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if ($registered.Principal.RunLevel.ToString() -ne 'Highest') { throw "Scheduled task $taskName was not registered with highest privileges" }
    if ($registered.Actions[0].Execute -ne $pythonw -or $registered.Actions[0].Arguments -ne ('"{0}"' -f $script)) {
        throw "Scheduled task action does not point to SENTINEL $version"
    }

    $wsh = New-Object -ComObject WScript.Shell
    $shortcutArgs = ('"{0}" open' -f $script)
    $shortcutTargets = @(
        @{ Path = (Join-Path $desktop 'SENTINEL.lnk'); Kind = 'Desktop' },
        @{ Path = (Join-Path $userStartMenu 'SENTINEL.lnk'); Kind = 'User Start Menu' },
        @{ Path = (Join-Path $commonStartMenu 'SENTINEL.lnk'); Kind = 'All Users Start Menu' }
    )
    foreach ($item in $shortcutTargets) {
        $link = $wsh.CreateShortcut($item.Path)
        $link.TargetPath = $pythonw
        $link.Arguments = $shortcutArgs
        $link.WorkingDirectory = $workdir
        $link.Description = "SENTINEL $version - performance and agent dashboard"
        $link.Save()
        if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
            throw "$($item.Kind) shortcut was not created: $($item.Path)"
        }
        $check = $wsh.CreateShortcut($item.Path)
        if ($check.TargetPath -ne $pythonw -or $check.Arguments -ne $shortcutArgs) {
            throw "$($item.Kind) shortcut points to an unexpected target: $($item.Path)"
        }
    }

    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Write-Output "INSTALL_VERSION=$version"
    Write-Output "INSTALL_USER=$loggedOn"
    Write-Output "INSTALL_TASK=$taskName"
    Write-Output "INSTALL_DESKTOP=$((Join-Path $desktop 'SENTINEL.lnk'))"
    Write-Output "INSTALL_START_MENU=$((Join-Path $commonStartMenu 'SENTINEL.lnk'))"
    Write-Output "INSTALL_USER_START_MENU=$((Join-Path $userStartMenu 'SENTINEL.lnk'))"
    Write-Output "INSTALL_DATA=$store"
    exit 0
} catch {
    [Console]::Error.WriteLine("SENTINEL installation integration failed: " + $_.Exception.Message)
    exit 1
}
"""
    try:
        result = pw(ps)
    except Exception as exc:
        print(f"Could not run the Windows installation checks: {type(exc).__name__}: {exc}")
        return 1

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        print("SENTINEL task or shortcut verification failed. The version files and ProgramData history were left untouched.")
        return 1

    print(f"Waiting for SENTINEL {APP_VERSION} to become ready...")
    if not _wait_for_agent(35):
        diagnostic = pw(
            f"$task = Get-ScheduledTask -TaskName {_ps_quote(TASK)} -ErrorAction SilentlyContinue; "
            f"if ($task) {{ $info = Get-ScheduledTaskInfo -TaskName {_ps_quote(TASK)}; "
            f"Write-Output ('TaskState=' + $task.State + '; LastTaskResult=' + $info.LastTaskResult) }} "
            f"else {{ Write-Output 'ScheduledTaskMissing' }}"
        )
        print("The shortcuts and task were registered, but the authenticated agent API did not become ready.")
        print(diagnostic.stdout or diagnostic.stderr or "No Task Scheduler diagnostics were returned.")
        return 1

    if _running_agent_is_elevated() is not True:
        print("The agent API is responding, but administrator elevation could not be verified. Installation is not marked complete.")
        return 1

    print(f"SENTINEL {APP_VERSION} installed and verified at {HERE}.")
    print("Desktop and Start Menu shortcuts were checked on disk; the elevated agent is running.")
    if not _launch_hud():
        print("WARNING: The agent is running, but Windows could not open the dashboard window. Use the SENTINEL shortcut to open it.")
    return 0


def uninstall():
    """Remove launch integration, never remove user configuration/history."""
    if stop_agent() != 0:
        print("Agent could not be stopped; uninstall was not completed.")
        return 1

    ps = r"""
$ErrorActionPreference = 'Stop'
try {
    $taskName = 'SentinelAgent'
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

    $loggedOn = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).UserName
    $desktop = $null
    $userStartMenu = $null
    if ($loggedOn) {
        $userSid = ([System.Security.Principal.NTAccount]::new($loggedOn)).Translate([System.Security.Principal.SecurityIdentifier]).Value
        $userProfile = Get-CimInstance Win32_UserProfile -Filter ("SID='{0}'" -f $userSid) -ErrorAction Stop
        if ($userProfile -and $userProfile.LocalPath) {
            $userRoot = $userProfile.LocalPath
            $desktop = Join-Path $userRoot 'Desktop'
            $usersHive = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
                [Microsoft.Win32.RegistryHive]::Users,
                [Microsoft.Win32.RegistryView]::Default
            )
            try {
                $shellFolders = $usersHive.OpenSubKey("$userSid\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
                if ($shellFolders) {
                    try {
                        $desktopValue = $shellFolders.GetValue(
                            'Desktop', $null,
                            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                        )
                        if ($desktopValue) {
                            $desktopValue = $desktopValue.Replace('%USERPROFILE%', $userRoot)
                            $desktop = [Environment]::ExpandEnvironmentVariables($desktopValue)
                        }
                    } finally { $shellFolders.Dispose() }
                }
            } finally { $usersHive.Dispose() }
            if (-not $desktop -or $desktop -match '%[^%]+%') { $desktop = Join-Path $userRoot 'Desktop' }
            $userStartMenu = Join-Path $userRoot 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\SENTINEL'
        }
    }
    if ($desktop) { Remove-Item (Join-Path $desktop 'SENTINEL.lnk') -Force -ErrorAction SilentlyContinue }
    if ($userStartMenu) { Remove-Item $userStartMenu -Recurse -Force -ErrorAction SilentlyContinue }
    $commonStartMenu = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs\SENTINEL'
    Remove-Item $commonStartMenu -Recurse -Force -ErrorAction SilentlyContinue

    $remainingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($remainingTask) { throw "Scheduled task $taskName still exists after removal" }
    if ($desktop -and (Test-Path (Join-Path $desktop 'SENTINEL.lnk'))) {
        throw "Desktop shortcut still exists: $(Join-Path $desktop 'SENTINEL.lnk')"
    }
    if (Test-Path $commonStartMenu) { throw "Common Start Menu shortcut folder still exists: $commonStartMenu" }
    Write-Output 'SENTINEL task and verified shortcut locations removed. ProgramData data was kept.'
    exit 0
} catch {
    [Console]::Error.WriteLine("SENTINEL uninstall integration failed: " + $_.Exception.Message)
    exit 1
}
"""
    result = pw(ps)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        print("Could not fully remove the task/shortcuts.")
        return 1
    print(f"SENTINEL {APP_VERSION} launch integration removed; application files remain in {PROGRAM_DIR}.")
    print(f"Settings, SQLite history and traces remain in {core.HOME}.")
    return 0


def main():
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "install":
        return install()
    if arguments and arguments[0] == "uninstall":
        return uninstall()
    if arguments and arguments[0] in ("stop", "upgrade-stop"):
        return stop_agent()
    if arguments and arguments[0] == "open":
        return open_app()
    if port_busy():
        if _wait_for_agent(2):
            return 0 if _launch_hud() else 1
        print(f"Port {CFG['port']} is already in use by another local process; SENTINEL was not started.")
        return 1

    from sentinel import collectors, brain, ai, intel, server, advanced
    from sentinel import runtime_engine, memory_engine, security_engine, ai_engine
    try:
        core.STATE["traces"] = [
            {"file": row[0], "ts": row[1], "mb": round(row[2] / 1048576, 1), "source": row[3], "exists": os.path.isfile(row[0])}
            for row in core.db("SELECT file_path,ts,size_bytes,source FROM trace_archive ORDER BY ts DESC LIMIT 200")
        ]
    except Exception as exc:
        log("storage", f"ETW trace catalog restore failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")

    db = core.db
    db(
        "UPDATE agent_runs SET stopped_at=?,exit_reason=? WHERE stopped_at IS NULL",
        (time.time(), "previous process ended without final shutdown acknowledgement"),
    )
    db(
        "INSERT INTO agent_runs(started_at,pid,executable,run_mode) VALUES(?,?,?,?)",
        (time.time(), os.getpid(), sys.executable,
         "windows-interactive" if IS_WIN else ("synthetic-demo" if "--demo" in arguments else "non-windows-demo")),
    )
    run_id = db("SELECT MAX(id) FROM agent_runs")[0][0]

    def close_run():
        db(
            "UPDATE agent_runs SET stopped_at=?,exit_reason=? WHERE id=? AND stopped_at IS NULL",
            (time.time(), "normal process shutdown", run_id),
        )

    atexit.register(close_run)
    log("core", f"SENTINEL starting (pid {os.getpid()}, {'Windows' if IS_WIN else 'demo'}, run {run_id})", "ok")
    advanced.start()
    atexit.register(advanced.shutdown)
    runtime_engine.start()
    memory_engine.start()
    security_engine.start()
    collectors.start_all(demo="--demo" in arguments)
    ai_engine.start()
    core.thread(brain.brain_loop, "brain")
    core.thread(intel.watch_loop, "intel")
    if "--demo" in arguments or not IS_WIN:
        print("HUD:", url())
    try:
        server.serve()
    finally:
        advanced.shutdown()
        close_run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
