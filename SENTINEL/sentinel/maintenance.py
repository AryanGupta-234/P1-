"""Guarded Windows maintenance and autonomous diagnostic engine.

Every mutation is preview-bound, explicitly confirmed, budgeted, audited and
re-checked against Sentinel's safety boundary immediately before execution.
The background scheduler is read-only: it never changes Windows unattended.
"""
from __future__ import annotations
import base64, ctypes, hashlib, ipaddress, json, os, platform, re, subprocess
import threading, time, uuid
from pathlib import Path
from typing import Any

import psutil
try:
    import winreg
except ImportError:  # Non-Windows demo/test environments.
    winreg = None

from . import core, safeguard

IS_WIN = bool(os.name == "nt" and core.IS_WIN)
PREVIEW_TTL = 180
MAX_ACTIONS_PER_HOUR = 3
MAX_ACTIONS_PER_DAY = 8
CLEANUP_MAX_FILES = 200
CLEANUP_MAX_BYTES = 250 * 1024 * 1024
CLEANUP_AGE_SECONDS = 7 * 86400
UPDATE_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
SERVICE_ALLOWLIST = frozenset({"audiosrv", "bthserv", "wuauserv", "bits", "spooler", "dhcp", "dnscache"})
POWER_SCHEMES = {
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "battery": "a1841308-3541-4fab-bc81-f71556f20b4a",
}
VIRTUAL_ADAPTER_WORDS = ("tailscale", "wireguard", "openvpn", "tap-windows", "wan miniport",
                         "hyper-v", "virtualbox", "vmware", "loopback", "npcap", "bluetooth")
PROTECTED_STARTUP_WORDS = ("defender", "securityhealth", "windows security", "sentinel",
                            "vanguard", "riot", "vgc", "vgk", "explorer", "userinit")
_STARTED = False
_STOP = threading.Event()
_DIAG_LOCK = threading.Lock()
_DIAG_CACHE: dict[str, Any] = {"at": 0.0, "payload": None, "refreshing": False}
_PREVIEW_LOCK = threading.Lock()
_JOB_LOCK = threading.Lock()


def ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS maintenance_previews(
        token TEXT PRIMARY KEY, action TEXT NOT NULL, args_json TEXT NOT NULL,
        snapshot_json TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
        consumed INTEGER NOT NULL DEFAULT 0)""")
    core.db("""CREATE TABLE IF NOT EXISTS maintenance_jobs(
        job_id TEXT PRIMARY KEY, action TEXT NOT NULL, state TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, result TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '', journal_id INTEGER)""")
    core.db("""CREATE TABLE IF NOT EXISTS maintenance_journal(
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, created_at REAL NOT NULL,
        before_json TEXT NOT NULL, after_json TEXT NOT NULL, undo_json TEXT NOT NULL,
        undo_available INTEGER NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS maintenance_samples(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,
        value REAL, detail_json TEXT NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS maintenance_policy(
        id INTEGER PRIMARY KEY CHECK(id=1), kill_switch INTEGER NOT NULL DEFAULT 1,
        scheduler_enabled INTEGER NOT NULL DEFAULT 0, idle_minutes INTEGER NOT NULL DEFAULT 15,
        weekly_diagnostics INTEGER NOT NULL DEFAULT 1, last_idle_run REAL NOT NULL DEFAULT 0,
        last_weekly_run REAL NOT NULL DEFAULT 0)""")
    core.db("INSERT OR IGNORE INTO maintenance_policy(id) VALUES(1)")


ensure_schema()


def _q(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell(script: str, timeout: int = 30) -> str:
    if not IS_WIN:
        raise RuntimeError("This operation is available only on Windows.")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, creationflags=0x08000000)
    output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    if result.returncode != 0:
        raise RuntimeError(output[:1200] or f"PowerShell exited with code {result.returncode}")
    return output


def _ps_json(script: str, timeout: int = 30) -> Any:
    output = _powershell(script, timeout)
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Windows returned an unexpected diagnostics payload.") from exc


def _run_command(args: list[str], timeout: int = 30) -> str:
    if not IS_WIN:
        raise RuntimeError("This operation is available only on Windows.")
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, creationflags=0x08000000)
    output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    if result.returncode != 0:
        raise RuntimeError(output[:1200] or f"{args[0]} exited with code {result.returncode}")
    return output


def _is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _require_admin() -> None:
    if not _is_admin():
        raise PermissionError("Run SENTINEL as administrator for this operation. No automatic elevation is attempted.")


def _require_safeguard(kind: str, args: dict) -> dict:
    state = safeguard.check_action(kind, args)
    if not state.get("allowed"):
        raise PermissionError("SENTINEL safeguard blocked this operation: " + str(state.get("reason") or "policy denied"))
    return state


def _policy() -> dict:
    rows = core.db("SELECT kill_switch,scheduler_enabled,idle_minutes,weekly_diagnostics,last_idle_run,last_weekly_run FROM maintenance_policy WHERE id=1")
    if not rows:
        return {"kill_switch": True, "scheduler_enabled": False, "idle_minutes": 15,
                "weekly_diagnostics": True, "last_idle_run": 0, "last_weekly_run": 0}
    row = rows[0]
    return {"kill_switch": bool(row[0]), "scheduler_enabled": bool(row[1]),
            "idle_minutes": int(row[2]), "weekly_diagnostics": bool(row[3]),
            "last_idle_run": float(row[4]), "last_weekly_run": float(row[5])}


def update_policy(body: dict) -> dict:
    policy = _policy()
    kill = body.get("kill_switch", policy["kill_switch"])
    enabled = body.get("scheduler_enabled", policy["scheduler_enabled"])
    weekly = body.get("weekly_diagnostics", policy["weekly_diagnostics"])
    idle = body.get("idle_minutes", policy["idle_minutes"])
    if not all(isinstance(x, bool) for x in (kill, enabled, weekly)):
        raise ValueError("kill_switch, scheduler_enabled and weekly_diagnostics must be booleans")
    if isinstance(idle, bool) or not isinstance(idle, int) or not 5 <= idle <= 180:
        raise ValueError("idle_minutes must be an integer between 5 and 180")
    if policy["kill_switch"] and not kill and body.get("confirmed") is not True:
        raise ValueError("explicit confirmation is required to release the maintenance kill switch")
    core.db("UPDATE maintenance_policy SET kill_switch=?,scheduler_enabled=?,idle_minutes=?,weekly_diagnostics=? WHERE id=1",
            (int(kill), int(enabled), idle, int(weekly)))
    core.log("maintenance", "maintenance policy updated", "warn" if kill else "info",
             kill_switch=kill, scheduler_enabled=enabled, idle_minutes=idle, weekly_diagnostics=weekly)
    return _policy()


def _budget_state() -> dict:
    now = time.time()
    hour = core.db("SELECT COUNT(*) FROM maintenance_jobs WHERE created_at>=?", (now - 3600,))[0][0]
    day = core.db("SELECT COUNT(*) FROM maintenance_jobs WHERE created_at>=?", (now - 86400,))[0][0]
    return {"hour": int(hour), "day": int(day), "hour_limit": MAX_ACTIONS_PER_HOUR,
            "day_limit": MAX_ACTIONS_PER_DAY, "available_hour": max(0, MAX_ACTIONS_PER_HOUR - int(hour)),
            "available_day": max(0, MAX_ACTIONS_PER_DAY - int(day))}


def _assert_budget() -> None:
    budget = _budget_state()
    if budget["hour"] >= MAX_ACTIONS_PER_HOUR or budget["day"] >= MAX_ACTIONS_PER_DAY:
        raise PermissionError("SENTINEL maintenance action budget reached. Wait for the rolling budget window to recover.")


def _run_restore_point(description: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9 _.-]", "", description)[:60]
    return _powershell(
        f"try {{ Checkpoint-Computer -Description {_q('SENTINEL ' + safe)} -RestorePointType MODIFY_SETTINGS -ErrorAction Stop; 'RESTORE_POINT_CREATED' }} "
        "catch { Write-Error $_; exit 2 }", timeout=90)


def _get_adapters() -> list[dict]:
    if not IS_WIN:
        return []
    value = _ps_json("""$ErrorActionPreference='Stop'
    Get-NetAdapter -Physical -ErrorAction Stop | Select-Object Name,InterfaceDescription,Status,LinkSpeed,MacAddress,InterfaceGuid,HardwareInterface,Virtual |
    ConvertTo-Json -Depth 4 -Compress""", 20)
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def _get_dns() -> list[dict]:
    if not IS_WIN:
        return []
    value = _ps_json("""$ErrorActionPreference='Stop'
    Get-DnsClientServerAddress -ErrorAction Stop | Where-Object {$_.ServerAddresses.Count -gt 0} |
    Select-Object InterfaceAlias,InterfaceIndex,AddressFamily,ServerAddresses |
    ConvertTo-Json -Depth 4 -Compress""", 20)
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def _get_drivers() -> list[dict]:
    if not IS_WIN:
        return []
    value = _ps_json("""$ErrorActionPreference='Stop'
    Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceName} |
    Select-Object DeviceName,DriverVersion,DriverDate,InfName,DeviceID,Manufacturer,DeviceClass |
    ConvertTo-Json -Depth 4 -Compress""", 35)
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def _get_driver_updates() -> list[dict]:
    if not IS_WIN:
        return []
    script = r"""$ErrorActionPreference='Stop'
    $session=New-Object -ComObject Microsoft.Update.Session
    $searcher=$session.CreateUpdateSearcher()
    $result=$searcher.Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
    $items=@()
    for($i=0;$i -lt $result.Updates.Count;$i++){
      $u=$result.Updates.Item($i)
      $ids=@()
      try{$ids=@($u.DriverHardwareID)}catch{}
      $items+=@{title=$u.Title;update_id=$u.Identity.UpdateID;revision=[int]$u.Identity.RevisionNumber;
        hardware_ids=$ids;reboot_required=[bool]$u.RebootRequired}
    }
    ConvertTo-Json -InputObject $items -Depth 5 -Compress"""
    value = _ps_json(script, 90)
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def _startup_inventory() -> list[dict]:
    if not IS_WIN or winreg is None:
        return []
    results = []
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            count = winreg.QueryInfoKey(key)[1]
            for index in range(count):
                name, value, value_type = winreg.EnumValue(key, index)
                protected = any(token in name.casefold() or token in str(value).casefold()
                                for token in PROTECTED_STARTUP_WORDS)
                results.append({"name": name, "command": str(value), "registry_type": int(value_type),
                                "protected": protected, "scope": "current_user"})
    except FileNotFoundError:
        pass
    return results


def _cleanup_roots(scope: str) -> list[str]:
    roots = []
    if scope in ("temp", "all"):
        roots.extend([os.environ.get("TEMP"), os.environ.get("TMP")])
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(os.path.join(local, "Temp"))
    if scope in ("shader", "all"):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.extend([os.path.join(local, "D3DSCache"), os.path.join(local, "NVIDIA", "DXCache"),
                          os.path.join(local, "NVIDIA", "GLCache"), os.path.join(local, "AMD", "DxCache")])
    safe, seen = [], set()
    for item in roots:
        if not item:
            continue
        path = os.path.abspath(os.path.expandvars(item))
        norm = os.path.normcase(path)
        if norm not in seen and os.path.isdir(path):
            seen.add(norm)
            safe.append(path)
    return safe


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _cleanup_manifest(scope: str) -> list[dict]:
    cutoff = time.time() - CLEANUP_AGE_SECONDS
    manifest, total = [], 0
    for root in _cleanup_roots(scope):
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name.casefold() not in {"sentinel-quarantine", "system volume information"}]
            for name in files:
                path = os.path.abspath(os.path.join(current, name))
                try:
                    info = os.stat(path, follow_symlinks=False)
                    if os.path.islink(path) or not os.path.isfile(path) or info.st_mtime >= cutoff:
                        continue
                    if info.st_size > CLEANUP_MAX_BYTES - total:
                        continue
                    manifest.append({"path": path, "size": int(info.st_size), "mtime": float(info.st_mtime),
                                     "sha256": _hash_file(path)})
                    total += int(info.st_size)
                except (OSError, ValueError):
                    continue
                if len(manifest) >= CLEANUP_MAX_FILES:
                    return manifest
    return manifest


def _dns_record(interface: str, family: str) -> list[str]:
    matches = [row for row in _get_dns() if str(row.get("InterfaceAlias") or "").casefold() == interface.casefold()
               and str(row.get("AddressFamily") or "").casefold() == family.casefold()]
    if not matches:
        return []
    values = matches[0].get("ServerAddresses") or []
    return [str(x) for x in (values if isinstance(values, list) else [values])]


def _active_scheme() -> str:
    output = _run_command(["powercfg.exe", "/getactivescheme"], 10)
    match = re.search(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})", output)
    if not match:
        raise RuntimeError("Windows did not return the active power scheme GUID.")
    return match.group(1).lower()


def _device_driver(device_id: str) -> dict:
    target = str(device_id).casefold()
    for driver in _get_drivers():
        if str(driver.get("DeviceID") or "").casefold() == target:
            return driver
    raise ValueError("The selected device is no longer present in the current driver inventory.")


def _network_backup() -> dict:
    return {"ipv4_dump": _run_command(["netsh.exe", "interface", "ipv4", "dump"], 20),
            "ipv6_dump": _run_command(["netsh.exe", "interface", "ipv6", "dump"], 20),
            "ipconfig": _run_command(["ipconfig.exe", "/all"], 20), "captured_at": time.time()}


def _process_identity(args: dict) -> tuple[psutil.Process, dict]:
    try:
        pid = int(args.get("pid", 0))
        created = float(args.get("create_time", 0))
        exe = os.path.normcase(os.path.abspath(str(args.get("exe") or "")))
        process = psutil.Process(pid)
        with process.oneshot():
            current = {"pid": pid, "create_time": process.create_time(),
                       "exe": os.path.normcase(os.path.abspath(process.exe() or "")),
                       "name": process.name(), "priority": process.nice(), "affinity": process.cpu_affinity()}
        if abs(current["create_time"] - created) > 0.02 or current["exe"] != exe:
            raise ValueError("Process identity changed after preview. Refresh the process list.")
        if safeguard.is_protected_process(current["name"], current["exe"]):
            raise PermissionError("Protected Windows/Riot/Vanguard processes cannot be tuned.")
        return process, current
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        raise ValueError(f"Process is unavailable or inaccessible: {exc}") from exc


def _snapshot_for(action: str, args: dict) -> dict:
    if action == "startup_disable":
        if winreg is None:
            raise RuntimeError("Windows registry is unavailable.")
        name = str(args.get("name") or "")[:180]
        if not name or any(x in name.casefold() for x in PROTECTED_STARTUP_WORDS):
            raise ValueError("Startup entry is empty or protected.")
        item = next((row for row in _startup_inventory() if row["name"].casefold() == name.casefold()), None)
        if not item or item["protected"]:
            raise ValueError("Startup entry is absent or protected.")
        return item
    if action == "cleanup":
        scope = str(args.get("scope") or "temp")
        if scope not in ("temp", "shader", "all"):
            raise ValueError("Cleanup scope must be temp, shader or all.")
        files = _cleanup_manifest(scope)
        return {"scope": scope, "files": files, "count": len(files), "bytes": sum(item["size"] for item in files)}
    if action in ("dns_set", "adapter_restart"):
        interface = str(args.get("interface") or "")[:128]
        adapter = next((row for row in _get_adapters() if str(row.get("Name") or "").casefold() == interface.casefold()), None)
        if not adapter:
            raise ValueError("The requested network interface is not present.")
        description = str(adapter.get("InterfaceDescription") or "").casefold()
        if any(word in description for word in VIRTUAL_ADAPTER_WORDS):
            raise PermissionError("Virtual, VPN, or tunnel adapters are excluded from Sentinel network actions.")
        if action == "dns_set":
            family = str(args.get("family") or "IPv4")
            if family not in ("IPv4", "IPv6"):
                raise ValueError("Address family must be IPv4 or IPv6.")
            servers = [str(ipaddress.ip_address(x)) for x in args.get("servers", [])]
            if not 1 <= len(servers) <= 4:
                raise ValueError("Provide between one and four DNS server IP addresses.")
            if (family == "IPv4" and any(":" in x for x in servers)) or (family == "IPv6" and any(":" not in x for x in servers)):
                raise ValueError("DNS servers do not match the selected address family.")
            return {"interface": interface, "family": family, "servers": _dns_record(interface, family), "adapter": adapter}
        if str(adapter.get("Status") or "").casefold() != "up":
            raise ValueError("Only a currently connected physical adapter can be restarted.")
        return {"interface": interface, "adapter": adapter}
    if action == "winsock_reset":
        return _network_backup()
    if action == "driver_install":
        update_id = str(args.get("update_id") or "")
        if not UPDATE_ID_RE.fullmatch(update_id):
            raise ValueError("A valid Windows Update driver ID is required.")
        device_id = str(args.get("device_id") or "")
        driver = _device_driver(device_id)
        updates = _get_driver_updates()
        update = next((item for item in updates if str(item.get("update_id")) == update_id), None)
        if not update:
            raise ValueError("The exact driver update is no longer offered. Scan Windows Update again.")
        hardware_ids = update.get("hardware_ids") or []
        normalized_device = device_id.strip().casefold()
        matched_hardware_id = any(
            normalized_device == str(value).strip().casefold()
            or normalized_device.startswith(str(value).strip().casefold() + "\\")
            for value in hardware_ids
            if str(value).strip()
        )
        if not matched_hardware_id:
            raise ValueError("Windows did not expose an exact hardware-ID or instance-prefix match for this driver update.")
        return {"update": update, "device": driver, "device_id": device_id}
    if action == "driver_rollback":
        journal_id = int(args.get("journal_id", 0))
        rows = core.db("SELECT action,undo_json,status FROM maintenance_journal WHERE id=?", (journal_id,))
        if not rows or rows[0][0] != "driver_install" or rows[0][2] != "done":
            raise ValueError("A completed Sentinel driver-install journal entry is required.")
        undo = json.loads(rows[0][1] or "{}")
        if not undo.get("backup_inf") or not os.path.isfile(undo["backup_inf"]):
            raise ValueError("The exported prior driver package is not available.")
        return {"journal_id": journal_id, "undo": undo}
    if action == "windows_repair":
        target = str(args.get("target") or "sfc")
        if target not in ("sfc", "dism", "both"):
            raise ValueError("Repair target must be sfc, dism or both.")
        return {"target": target, "os_build": platform.version()}
    if action == "service_restart":
        service = str(args.get("service") or "").casefold()
        if service not in SERVICE_ALLOWLIST or service in safeguard.VANGUARD_SERVICES:
            raise ValueError("Service is not on the explicit safe restart allowlist.")
        state = _ps_json(f"Get-Service -Name {_q(service)} | Select-Object Name,Status | ConvertTo-Json -Compress")
        return {"service": service, "state": state}
    if action == "power_mode":
        mode = str(args.get("mode") or "").casefold()
        if mode not in POWER_SCHEMES:
            raise ValueError("Power mode must be balanced, performance or battery.")
        return {"scheme": _active_scheme(), "mode": mode, "applied_scheme": POWER_SCHEMES[mode]}
    if action == "trim_volume":
        drive = str(args.get("drive") or "").rstrip(":").upper()
        if not re.fullmatch(r"[A-Z]", drive):
            raise ValueError("Drive must be a single volume letter.")
        volume = _ps_json(f"Get-Volume -DriveLetter {_q(drive)} | Select-Object DriveLetter,FileSystem,DriveType,Size,SizeRemaining | ConvertTo-Json -Compress", 15)
        if not volume or str(volume.get("FileSystem") or "").casefold() != "ntfs":
            raise ValueError("Only an available NTFS volume is supported.")
        return {"drive": drive, "volume": volume}
    if action == "process_tune":
        process, current = _process_identity(args)
        priority = str(args.get("priority") or "normal").casefold()
        if priority not in ("below_normal", "normal", "above_normal"):
            raise ValueError("Priority must be below_normal, normal or above_normal. High and realtime are never allowed.")
        affinity = args.get("affinity")
        if affinity is not None:
            if not isinstance(affinity, list) or not affinity or any(isinstance(x, bool) or not isinstance(x, int) for x in affinity):
                raise ValueError("CPU affinity must be a non-empty list of logical CPU indices.")
            if any(x < 0 or x >= psutil.cpu_count() for x in affinity):
                raise ValueError("CPU affinity contains an out-of-range logical CPU index.")
        return {"process": current, "priority": priority, "affinity": affinity}
    raise ValueError("Unsupported maintenance action.")


def _action_policy(action: str) -> dict:
    dangerous = {"cleanup", "winsock_reset", "driver_install", "driver_rollback", "windows_repair", "trim_volume"}
    admin = {"dns_set", "adapter_restart", "winsock_reset", "driver_install", "driver_rollback",
             "windows_repair", "service_restart", "trim_volume", "process_tune"}
    restore = {"winsock_reset", "driver_install", "driver_rollback", "windows_repair"}
    return {"risk": "dangerous" if action in dangerous else "medium", "administrator_required": action in admin,
            "restore_point_required": action in restore, "automatic_allowed": False,
            "manual_confirmation_required": True}


def _change_summary(action: str, args: dict, snapshot: dict) -> list[str]:
    if action == "startup_disable":
        return [f"Remove current-user startup entry: {snapshot['name']}", "Save exact command and registry type for restoration."]
    if action == "cleanup":
        return [f"Delete {snapshot['count']} old TEMP/cache files ({snapshot['bytes'] / 1048576:.1f} MiB).",
                "Only the displayed, allowlisted temporary or DirectX shader-cache manifest is eligible."]
    if action == "dns_set":
        return [f"Set DNS on {snapshot['interface']} ({snapshot['family']}) to {', '.join(args['servers'])}.",
                "Previous DNS settings are journaled for conditional restoration."]
    if action == "adapter_restart":
        return [f"Restart physical network adapter {snapshot['interface']}.", "Network access will briefly disconnect."]
    if action == "winsock_reset":
        return ["Reset Winsock and TCP/IP configuration.", "A restore point and network configuration snapshot are required; reboot may be needed."]
    if action == "driver_install":
        return [f"Install exact Windows Update driver: {snapshot['update'].get('title')}.",
                f"Export current driver package {snapshot['device'].get('InfName')} before installation."]
    if action == "driver_rollback":
        return [f"Reinstall exported previous driver for {snapshot['undo'].get('device_name')}.", "A restore point is required."]
    if action == "windows_repair":
        return [f"Run Windows {snapshot['target'].upper()} repair.", "SFC/DISM run only after explicit confirmation and restore-point success."]
    if action == "service_restart":
        return [f"Restart allowlisted Windows service {snapshot['service']}.", "Connected devices may briefly reconnect."]
    if action == "power_mode":
        return [f"Switch Windows power plan to {snapshot['mode']}.", "Previous active scheme is available for conditional Undo."]
    if action == "trim_volume":
        return [f"Run SSD retrim on volume {snapshot['drive']}:.", "This operation is manual-only."]
    if action == "process_tune":
        return [f"Set {snapshot['process']['name']} priority to {snapshot['priority']}.", "High and realtime priority are permanently unavailable."]
    return ["Reviewed action."]


def _warnings(action: str) -> list[str]:
    base = ["Never runs from the background scheduler or AI alone.",
            "VALORANT/Vanguard safeguard is checked at preview, queue and execution."]
    extra = {
        "cleanup": ["Permanent deletion has no automatic undo. Review each displayed file and size."],
        "winsock_reset": ["VPN, static IP, custom DNS, routes and corporate network settings may be affected. No automatic rollback exists for Winsock itself."],
        "driver_install": ["May require a reboot. Rollback is offered only if the previous package was exported successfully."],
        "driver_rollback": ["May require a reboot. Do not interrupt power during installation."],
        "windows_repair": ["Can take a long time. Do not power off while SFC/DISM is running."],
        "adapter_restart": ["Active downloads and remote network sessions can disconnect."],
        "process_tune": ["The selected process may behave differently. Revert is conditional on no later external change."],
    }
    return base + extra.get(action, [])


def preview_action(action: str, args: dict | None = None) -> dict:
    ensure_schema()
    allowed = {"startup_disable", "cleanup", "dns_set", "adapter_restart", "winsock_reset",
               "driver_install", "driver_rollback", "windows_repair", "service_restart",
               "power_mode", "trim_volume", "process_tune"}
    if action not in allowed:
        raise ValueError("Action is not allowlisted.")
    args = args if isinstance(args, dict) else {}
    if not IS_WIN:
        raise RuntimeError("Windows maintenance is available only on Windows.")
    policy = _action_policy(action)
    guard = _require_safeguard("maint_" + action, args)
    snapshot = _snapshot_for(action, args)
    token, now = uuid.uuid4().hex, time.time()
    core.db("INSERT INTO maintenance_previews(token,action,args_json,snapshot_json,created_at,expires_at,consumed) VALUES(?,?,?,?,?,?,0)",
            (token, action, json.dumps(args, sort_keys=True), json.dumps(snapshot, sort_keys=True, default=str), now, now + PREVIEW_TTL))
    public = dict(snapshot)
    if action == "cleanup":
        public["files"] = [{"path": x["path"], "size": x["size"], "modified_at": x["mtime"]} for x in snapshot["files"][:30]]
    elif action == "driver_install":
        public = {"device": snapshot["device"].get("DeviceName"), "current_version": snapshot["device"].get("DriverVersion"),
                  "offered_title": snapshot["update"].get("title"), "update_id": snapshot["update"].get("update_id")}
    elif action == "driver_rollback":
        public = {"journal_id": snapshot["journal_id"], "device": snapshot["undo"].get("device_name"),
                  "previous_version": snapshot["undo"].get("driver_version")}
    elif action == "winsock_reset":
        public = {"captured_at": snapshot["captured_at"], "note": "Network settings will be backed up. Reboot may be required; reset itself has no automatic undo."}
    return {"supported": True, "preview_token": token, "expires_in_seconds": PREVIEW_TTL,
            "action": action, **policy, "snapshot": public, "safeguard": guard,
            "changes": _change_summary(action, args, snapshot), "warnings": _warnings(action)}


def _current_snapshot_matches(action: str, args: dict, original: dict) -> bool:
    try:
        current = _snapshot_for(action, args)
        if action == "cleanup":
            return hashlib.sha256(json.dumps(current["files"], sort_keys=True).encode()).hexdigest() == hashlib.sha256(json.dumps(original["files"], sort_keys=True).encode()).hexdigest()
        if action == "dns_set":
            return (current["interface"] == original["interface"] and current["family"] == original["family"]
                    and current["servers"] == original["servers"]
                    and current["adapter"].get("InterfaceGuid") == original["adapter"].get("InterfaceGuid"))
        if action == "adapter_restart":
            return (current["interface"] == original["interface"]
                    and current["adapter"].get("InterfaceGuid") == original["adapter"].get("InterfaceGuid")
                    and current["adapter"].get("Status") == original["adapter"].get("Status"))
        if action == "startup_disable":
            return (current.get("command") == original.get("command")
                    and current.get("registry_type") == original.get("registry_type"))
        if action == "power_mode":
            return current["scheme"] == original["scheme"]
        if action == "driver_install":
            return current["update"]["update_id"] == original["update"]["update_id"] and current["device"]["DriverVersion"] == original["device"]["DriverVersion"]
        if action == "winsock_reset":
            return current["ipv4_dump"] == original["ipv4_dump"] and current["ipv6_dump"] == original["ipv6_dump"]
        return current == original
    except Exception:
        return False


def execute_preview(token: str, *, confirmed: bool = False) -> dict:
    ensure_schema()
    if confirmed is not True:
        raise PermissionError("Explicit user confirmation is required.")
    with _PREVIEW_LOCK:
        rows = core.db("SELECT action,args_json,snapshot_json,created_at,expires_at,consumed FROM maintenance_previews WHERE token=?", (str(token),))
        if not rows:
            raise ValueError("Preview was not found or has expired.")
        action, args_json, snapshot_json, created, expires, consumed = rows[0]
        if consumed:
            raise ValueError("Preview token has already been used.")
        if time.time() > float(expires):
            raise ValueError("Preview expired. Generate a fresh preview.")
        args, before = json.loads(args_json), json.loads(snapshot_json)
        if _policy()["kill_switch"]:
            raise PermissionError("Maintenance kill switch is enabled.")
        if _action_policy(action)["administrator_required"]:
            _require_admin()
        _require_safeguard("maint_" + action, args)
        _assert_budget()
        if not _current_snapshot_matches(action, args, before):
            raise RuntimeError("System state changed after preview. No action was run; generate a new preview.")
        core.db("UPDATE maintenance_previews SET consumed=1 WHERE token=? AND consumed=0", (str(token),))
        job_id, now = uuid.uuid4().hex, time.time()
        core.db("INSERT INTO maintenance_jobs(job_id,action,state,created_at,updated_at) VALUES(?,?,?,?,?)",
                (job_id, action, "queued", now, now))
    worker = threading.Thread(target=_job_worker, args=(job_id, action, args, before), name="maintenance-" + action, daemon=True)
    worker.start()
    return {"ok": True, "job_id": job_id, "state": "queued", "action": action}


def _job_worker(job_id: str, action: str, args: dict, before: dict) -> None:
    core.db("UPDATE maintenance_jobs SET state='running',updated_at=? WHERE job_id=?", (time.time(), job_id))
    try:
        _require_safeguard("maint_" + action, args)
        if _policy()["kill_switch"]:
            raise PermissionError("Maintenance kill switch was enabled after approval; queued action cancelled.")
        if _action_policy(action)["administrator_required"]:
            _require_admin()
        if not _current_snapshot_matches(action, args, before):
            raise RuntimeError("System state changed while queued; action stopped before mutation.")
        if _action_policy(action)["restore_point_required"]:
            _run_restore_point(action)
        result, after, undo, can_undo = _apply_action(action, args, before)
        core.db("INSERT INTO maintenance_journal(action,created_at,before_json,after_json,undo_json,undo_available,status,result) VALUES(?,?,?,?,?,?,?,?)",
                (action, time.time(), json.dumps(before, default=str), json.dumps(after, default=str),
                 json.dumps(undo, default=str), int(can_undo), "done", result))
        journal_id = core.db("SELECT MAX(id) FROM maintenance_journal")[0][0]
        core.db("UPDATE maintenance_jobs SET state='done',updated_at=?,result=?,journal_id=? WHERE job_id=?",
                (time.time(), str(result)[:1800], int(journal_id), job_id))
        core.log("maintenance", f"{action} completed: {str(result)[:300]}", "ok", journal_id=journal_id)
        core.publish("maintenance_job", {"job_id": job_id, "state": "done", "result": str(result)[:800], "journal_id": journal_id})
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:900]}"
        core.db("UPDATE maintenance_jobs SET state='failed',updated_at=?,error=? WHERE job_id=?",
                (time.time(), error, job_id))
        core.log("maintenance", f"{action} failed safely: {error[:300]}", "warn")
        core.publish("maintenance_job", {"job_id": job_id, "state": "failed", "error": error[:500]})


def _apply_action(action: str, args: dict, before: dict) -> tuple[str, dict, dict, bool]:
    if action == "startup_disable":
        name, key_path = before["name"], r"Software\Microsoft\Windows\CurrentVersion\Run"
        if winreg is None:
            raise RuntimeError("Windows registry is unavailable.")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            value, value_type = winreg.QueryValueEx(key, name)
            if str(value) != before["command"] or int(value_type) != int(before["registry_type"]):
                raise RuntimeError("Startup value changed after preview.")
            winreg.DeleteValue(key, name)
        undo = {"kind": "startup_restore", "name": name, "command": before["command"], "registry_type": int(before["registry_type"])}
        return f"Disabled current-user startup entry {name}. Original command and registry type are journaled.", {"removed": name}, undo, True
    if action == "cleanup":
        deleted = skipped = freed = 0
        for item in before["files"]:
            try:
                path = item["path"]
                info = os.stat(path, follow_symlinks=False)
                if os.path.islink(path) or info.st_size != item["size"] or info.st_mtime != item["mtime"] or _hash_file(path) != item["sha256"]:
                    skipped += 1
                    continue
                os.remove(path)
                deleted += 1
                freed += int(item["size"])
            except OSError:
                skipped += 1
        return f"Removed {deleted} reviewed file(s), freed {freed} bytes; {skipped} changed or locked files skipped. No undo.", {"deleted": deleted, "bytes": freed, "skipped": skipped}, {}, False
    if action == "dns_set":
        servers = [str(ipaddress.ip_address(x)) for x in args.get("servers", [])]
        interface, family = before["interface"], before["family"]
        _powershell(f"Set-DnsClientServerAddress -InterfaceAlias {_q(interface)} -ServerAddresses @({','.join(_q(x) for x in servers)}) -ErrorAction Stop")
        undo = {"kind": "dns_restore", "interface": interface, "family": family,
                "original": before["servers"], "applied": servers}
        return f"DNS updated for {interface} ({family}); original resolver settings are journaled.", {"interface": interface, "family": family, "servers": servers}, undo, True
    if action == "adapter_restart":
        name = before["interface"]
        try:
            _powershell(f"Restart-NetAdapter -Name {_q(name)} -Confirm:$false -ErrorAction Stop; Start-Sleep -Seconds 2; (Get-NetAdapter -Name {_q(name)}).Status", 45)
        except Exception:
            try:
                _powershell(f"Enable-NetAdapter -Name {_q(name)} -Confirm:$false -ErrorAction Stop", 20)
            except Exception:
                pass
            raise
        return f"Restarted physical adapter {name}. Verify connectivity after it reconnects.", {"interface": name, "status": "restarted"}, {}, False
    if action == "winsock_reset":
        backup_dir = os.path.join(core.HOME, "maintenance", "network-backups", str(int(time.time())))
        os.makedirs(backup_dir, exist_ok=True)
        for name, content in (("ipv4.txt", before["ipv4_dump"]), ("ipv6.txt", before["ipv6_dump"]), ("ipconfig.txt", before["ipconfig"])):
            Path(os.path.join(backup_dir, name)).write_text(content, encoding="utf-8")
        winsock = _run_command(["netsh.exe", "winsock", "reset"], 45)
        tcpip = _run_command(["netsh.exe", "int", "ip", "reset"], 45)
        return "Winsock and TCP/IP reset requested. Reboot Windows to complete recovery. Snapshot saved at " + backup_dir, {"backup_dir": backup_dir, "winsock": winsock[-500:], "tcpip": tcpip[-500:]}, {}, False
    if action == "driver_install":
        device, update = before["device"], before["update"]
        backup = os.path.join(core.HOME, "maintenance", "driver-backups", uuid.uuid4().hex)
        os.makedirs(backup, exist_ok=True)
        inf = str(device.get("InfName") or "")
        if not re.fullmatch(r"oem\d+\.inf", inf, flags=re.IGNORECASE):
            raise RuntimeError("Current driver is not an exportable third-party OEM INF; install cancelled.")
        _run_command(["pnputil.exe", "/export-driver", inf, backup], 60)
        exported = next((str(p) for p in Path(backup).rglob("*.inf")), "")
        if not exported:
            raise RuntimeError("Windows did not export the previous driver package; update cancelled.")
        script = r"""$ErrorActionPreference='Stop'
        $session=New-Object -ComObject Microsoft.Update.Session
        $searcher=$session.CreateUpdateSearcher()
        $found=$searcher.Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
        $selected=$null
        for($i=0;$i -lt $found.Updates.Count;$i++){
          $candidate=$found.Updates.Item($i)
          if($candidate.Identity.UpdateID -eq UPDATE_ID -and $candidate.Identity.RevisionNumber -eq REVISION){$selected=$candidate;break}
        }
        if(-not $selected){throw 'Exact Windows Update driver is no longer offered'}
        $selected.AcceptEula()
        $collection=New-Object -ComObject Microsoft.Update.UpdateColl
        [void]$collection.Add($selected)
        $downloader=$session.CreateUpdateDownloader();$downloader.Updates=$collection
        $download=$downloader.Download()
        if($download.ResultCode -notin 2,3){throw ('Driver download failed: '+$download.ResultCode)}
        $installer=$session.CreateUpdateInstaller();$installer.Updates=$collection
        $install=$installer.Install()
        [pscustomobject]@{result_code=$install.ResultCode;reboot_required=$install.RebootRequired;title=$selected.Title} | ConvertTo-Json -Compress
        """.replace("UPDATE_ID", _q(update["update_id"])).replace("REVISION", str(int(update["revision"])))
        result = _ps_json(script, 900)
        if isinstance(result, list):
            result = result[0] if result else {}
        undo = {"kind": "driver_restore", "backup_inf": exported, "backup_dir": backup,
                "device_id": before["device_id"], "device_name": device.get("DeviceName"),
                "driver_version": device.get("DriverVersion"), "inf": inf}
        return f"Installed reviewed driver update for {device.get('DeviceName')}. Reboot required: {bool(result.get('reboot_required'))}. Prior package exported for rollback.", result, undo, True
    if action == "driver_rollback":
        undo = before["undo"]
        _run_command(["pnputil.exe", "/add-driver", undo["backup_inf"], "/install"], 180)
        return f"Reinstalled exported driver package for {undo.get('device_name')}. Reboot may be required.", {"device_id": undo["device_id"]}, {}, False
    if action == "windows_repair":
        target = before["target"]
        outputs = {}
        if target in ("sfc", "both"):
            outputs["sfc"] = _run_command(["sfc.exe", "/scannow"], 1800)
        if target in ("dism", "both"):
            outputs["dism"] = _run_command(["DISM.exe", "/Online", "/Cleanup-Image", "/RestoreHealth"], 1800)
        return "Windows repair commands completed. Review Windows servicing logs for detail.", outputs, {}, False
    if action == "service_restart":
        service = before["service"]
        _powershell(f"Restart-Service -Name {_q(service)} -Force -ErrorAction Stop; (Get-Service -Name {_q(service)}).Status", 90)
        return f"Restarted allowlisted service {service}.", {"service": service, "status": "restarted"}, {}, False
    if action == "power_mode":
        previous, applied = before["scheme"], before["applied_scheme"]
        _run_command(["powercfg.exe", "/setactive", applied], 15)
        return f"Power scheme changed to {before['mode']}. Previous scheme is available for conditional Undo.", {"scheme": applied}, {"kind": "power_restore", "before": previous, "applied": applied}, True
    if action == "trim_volume":
        drive = before["drive"]
        output = _powershell(f"Optimize-Volume -DriveLetter {_q(drive)} -ReTrim -Verbose; 'RETRIM_COMPLETE'", 600)
        return f"SSD retrim completed for {drive}:. {output[-500:]}", {"drive": drive}, {}, False
    if action == "process_tune":
        process, current = _process_identity(args)
        priority_value = {"below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
                          "normal": psutil.NORMAL_PRIORITY_CLASS,
                          "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS}[before["priority"]]
        process.nice(priority_value)
        try:
            if before["affinity"] is not None:
                process.cpu_affinity(before["affinity"])
        except Exception as tune_error:
            rollback_errors = []
            try:
                process.nice(current["priority"])
            except Exception as rollback_error:
                rollback_errors.append(f"priority restore: {rollback_error}")
            try:
                process.cpu_affinity(current["affinity"])
            except Exception as rollback_error:
                rollback_errors.append(f"affinity restore: {rollback_error}")
            detail = f"Process affinity change failed: {tune_error}"
            if rollback_errors:
                detail += "; compensation incomplete: " + "; ".join(rollback_errors)
                core.log("maintenance", detail[:500], "error")
            raise RuntimeError(detail) from tune_error
        undo = {"kind": "process_restore", "pid": current["pid"], "create_time": current["create_time"],
                "exe": current["exe"], "priority": current["priority"], "affinity": current["affinity"],
                "applied_priority": priority_value, "applied_affinity": before["affinity"]}
        return f"Updated reviewed process {current['name']} with non-realtime priority.", {"pid": current["pid"]}, undo, True
    raise ValueError("Action is not implemented.")


def job(job_id: str) -> dict:
    rows = core.db("SELECT job_id,action,state,created_at,updated_at,result,error,journal_id FROM maintenance_jobs WHERE job_id=?", (str(job_id),))
    if not rows:
        raise ValueError("Maintenance job was not found.")
    row = rows[0]
    return {"job_id": row[0], "action": row[1], "state": row[2], "created_at": row[3],
            "updated_at": row[4], "result": row[5], "error": row[6], "journal_id": row[7]}


def undo(journal_id: int, *, confirmed: bool = False) -> dict:
    if confirmed is not True:
        raise PermissionError("Explicit confirmation is required to undo a maintenance change.")
    rows = core.db("SELECT action,before_json,after_json,undo_json,undo_available,status FROM maintenance_journal WHERE id=?", (int(journal_id),))
    if not rows:
        raise ValueError("Maintenance journal entry was not found.")
    action, before_json, after_json, undo_json, can_undo, status = rows[0]
    if not can_undo or status != "done":
        raise PermissionError("This operation has no automatic undo. Use the guided recovery instructions.")
    policy = _action_policy(action)
    if policy["administrator_required"]:
        _require_admin()
    _require_safeguard("maint_" + action, {})
    detail = json.loads(undo_json)
    if detail.get("kind") == "startup_restore":
        if winreg is None:
            raise RuntimeError("Windows registry is unavailable.")
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            try:
                winreg.QueryValueEx(key, detail["name"])
                raise RuntimeError("A startup value with this name now exists; Sentinel will not overwrite it.")
            except FileNotFoundError:
                winreg.SetValueEx(key, detail["name"], 0, int(detail["registry_type"]), detail["command"])
    elif detail.get("kind") == "dns_restore":
        current = _dns_record(detail["interface"], detail["family"])
        if current != detail["applied"]:
            raise RuntimeError("Current DNS settings no longer match Sentinel's change; preserving the user's change.")
        family = detail["family"]
        if detail["original"]:
            _powershell(f"Set-DnsClientServerAddress -InterfaceAlias {_q(detail['interface'])} -ServerAddresses @({','.join(_q(x) for x in detail['original'])})")
        else:
            _powershell(f"Set-DnsClientServerAddress -InterfaceAlias {_q(detail['interface'])} -ResetServerAddresses")
    elif detail.get("kind") == "power_restore":
        if _active_scheme() != detail["applied"]:
            raise RuntimeError("Power scheme changed outside Sentinel; preserving that user change.")
        _run_command(["powercfg.exe", "/setactive", detail["before"]], 15)
    elif detail.get("kind") == "driver_restore":
        backup_inf = str(detail.get("backup_inf") or "")
        if not backup_inf or not os.path.isfile(backup_inf):
            raise FileNotFoundError("The exported prior driver INF is unavailable; SENTINEL cannot perform automatic driver Undo.")
        _run_restore_point("driver rollback")
        _run_command(["pnputil.exe", "/add-driver", backup_inf, "/install"], 180)
    elif detail.get("kind") == "process_restore":
        process, _ = _process_identity({"pid": detail["pid"], "create_time": detail["create_time"], "exe": detail["exe"]})
        if process.nice() != detail["applied_priority"]:
            raise RuntimeError("Process priority changed since Sentinel applied it; preserving external state.")
        process.nice(detail["priority"])
        if detail["applied_affinity"] is not None:
            if process.cpu_affinity() != detail["applied_affinity"]:
                raise RuntimeError("Process affinity changed since Sentinel applied it; preserving external state.")
            process.cpu_affinity(detail["affinity"])
    else:
        raise PermissionError("This journal entry requires guided recovery, not automatic Undo.")
    core.db("UPDATE maintenance_journal SET status='reverted',undo_available=0 WHERE id=?", (int(journal_id),))
    core.log("maintenance", f"Undid {action} journal entry {journal_id}", "ok")
    return {"ok": True, "journal_id": int(journal_id), "result": "change restored"}


def journal(limit: int = 50) -> list[dict]:
    rows = core.db("SELECT id,action,created_at,undo_available,status,result FROM maintenance_journal ORDER BY id DESC LIMIT ?",
                   (min(200, max(1, int(limit))),))
    return [{"id": r[0], "action": r[1], "created_at": r[2], "undo_available": bool(r[3]),
             "status": r[4], "result": r[5]} for r in rows]




def test_dns_servers(servers: list[str], name: str = "www.microsoft.com") -> dict:
    if not IS_WIN:
        raise RuntimeError("DNS resolver testing is available only on Windows.")
    if not isinstance(servers, list) or not 1 <= len(servers) <= 4:
        raise ValueError("Provide between one and four DNS server addresses.")
    normalized = []
    for server in servers:
        address = str(ipaddress.ip_address(server))
        if address not in normalized:
            normalized.append(address)
    query_name = str(name or "www.microsoft.com").strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", query_name) or ".." in query_name:
        raise ValueError("DNS test name is invalid.")
    script = f"""$ErrorActionPreference='Stop'
    $servers=@({','.join(_q(x) for x in normalized)})
    $results=@()
    foreach($server in $servers) {{
      $times=@()
      $errorText=''
      for($i=0;$i -lt 3;$i++) {{
        $watch=[Diagnostics.Stopwatch]::StartNew()
        try {{
          Resolve-DnsName -Name {_q(query_name)} -Server $server -DnsOnly -ErrorAction Stop | Out-Null
          $watch.Stop()
          $times += [math]::Round($watch.Elapsed.TotalMilliseconds,2)
        }} catch {{
          $watch.Stop()
          $errorText=$_.Exception.Message
        }}
      }}
      $avg=$null
      if($times.Count -gt 0){{$avg=[math]::Round((($times | Measure-Object -Average).Average),2)}}
      $results += [pscustomobject]@{{server=$server;successful=$times.Count;average_ms=$avg;error=$errorText}}
    }}
    ConvertTo-Json -InputObject $results -Depth 4 -Compress"""
    result = _ps_json(script, 45)
    rows = [result] if isinstance(result, dict) else result if isinstance(result, list) else []
    rows.sort(key=lambda row: float(row.get("average_ms") or 1e9) if int(row.get("successful") or 0) else 1e9)
    return {"query": query_name, "results": rows,
            "recommended": next((row["server"] for row in rows if int(row.get("successful") or 0)), None),
            "note": "Three read-only lookups per resolver. No DNS settings were changed."}




def revert_all(*, confirmed: bool = False) -> dict:
    if confirmed is not True:
        raise PermissionError("Explicit confirmation is required to revert all reversible maintenance changes.")
    rows = core.db("SELECT id,action,undo_available,status FROM maintenance_journal ORDER BY id DESC LIMIT 200")
    reverted, skipped, failed = [], [], []
    for journal_id, action, can_undo, state in rows:
        if not can_undo or state != "done":
            skipped.append({"journal_id": int(journal_id), "action": action, "reason": "no safe automatic undo"})
            continue
        try:
            reverted.append(undo(int(journal_id), confirmed=True))
        except Exception as exc:
            failed.append({"journal_id": int(journal_id), "action": action,
                           "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    return {"ok": not failed, "reverted": reverted, "skipped": skipped, "failed": failed}

def _idle_seconds() -> float:
    if not IS_WIN:
        return 0.0
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)
    except Exception:
        return 0.0


def _predictive_scan() -> list[dict]:
    now, findings = time.time(), []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            key = "disk_free:" + part.mountpoint
            latest = core.db("SELECT ts FROM maintenance_samples WHERE kind=? ORDER BY ts DESC LIMIT 1", (key,))
            if not latest or now - float(latest[0][0]) >= 900:
                core.db("INSERT INTO maintenance_samples(ts,kind,value,detail_json) VALUES(?,?,?,?)",
                        (now, key, float(usage.free), json.dumps({"total": usage.total})))
            history = core.db("SELECT ts,value FROM maintenance_samples WHERE kind=? AND ts>=? ORDER BY ts DESC LIMIT 24",
                              (key, now - 7 * 86400))
            if len(history) >= 3:
                ordered = list(reversed(history))
                elapsed = max(1.0, ordered[-1][0] - ordered[0][0])
                rate = (ordered[0][1] - ordered[-1][1]) / elapsed
                days = usage.free / rate / 86400 if rate > 0 else None
                if usage.free < 5 * 1024**3 or (days is not None and days < 7):
                    findings.append({"kind": "disk_capacity", "mountpoint": part.mountpoint,
                                     "free_gib": round(usage.free / 1024**3, 1),
                                     "projected_days_to_full": round(days, 1) if days is not None else None,
                                     "note": "Predictive alert only; cleanup is never triggered automatically."})
        except OSError:
            continue
    sensors = core.STATE.get("hardware_sensors") or {}
    for sensor in sensors.get("sensors", []) if isinstance(sensors, dict) else []:
        if not isinstance(sensor, dict) or sensor.get("value") is None:
            continue
        if "temp" not in str(sensor.get("type", "")).casefold():
            continue
        try:
            value = float(sensor["value"])
            if not -20.0 <= value <= 150.0:
                continue
            name = str(sensor.get("name") or "temperature")[:100]
            key = "thermal:" + name
            latest = core.db("SELECT ts FROM maintenance_samples WHERE kind=? ORDER BY ts DESC LIMIT 1", (key,))
            if not latest or now - float(latest[0][0]) >= 30:
                core.db("INSERT INTO maintenance_samples(ts,kind,value,detail_json) VALUES(?,?,?,?)",
                        (now, key, value, json.dumps({"sensor_type": sensor.get("type")})))
            history = core.db("SELECT ts,value FROM maintenance_samples WHERE kind=? AND ts>=? ORDER BY ts DESC LIMIT 20",
                              (key, now - 600))
            minutes = None
            if len(history) >= 3:
                ordered = list(reversed(history))
                elapsed_minutes = max(0.1, (ordered[-1][0] - ordered[0][0]) / 60.0)
                rise = (ordered[-1][1] - ordered[0][1]) / elapsed_minutes
                if rise > 0 and value < 88.0:
                    minutes = max(0.0, (88.0 - value) / rise)
            if value >= 88.0 or (minutes is not None and minutes <= 15.0):
                findings.append({"kind": "thermal_warning", "sensor": name, "celsius": round(value, 1),
                                 "minutes_to_threshold": round(minutes, 1) if minutes is not None else None,
                                 "note": "Alert only; no automatic fan, power, or process action."})
        except (TypeError, ValueError):
            continue
    return findings




_OEM_ALIASES = {
    "asus": ("myasus", "armoury crate", "asus system control interface", "asus optimization"),
    "lenovo": ("lenovo vantage", "lenovo utility"),
    "dell": ("dell power manager", "mydell", "dell optimizer", "alienware command center"),
    "hp": ("omen gaming hub", "hp command center", "myhp"),
    "msi": ("msi center", "dragon center"),
    "acer": ("nitrosense", "predatorsense", "acersense"),
}
_OEM_FAN_TOOLS = {
    "asus": ("MyASUS", "Armoury Crate"), "lenovo": ("Lenovo Vantage",),
    "dell": ("Dell Power Manager", "Alienware Command Center"),
    "hp": ("OMEN Gaming Hub", "HP Command Center"), "msi": ("MSI Center",),
    "acer": ("NitroSense", "PredatorSense", "AcerSense"),
}


def _system_identity() -> dict:
    result = {"manufacturer": "", "model": "", "system_sku": "", "baseboard_manufacturer": ""}
    if not IS_WIN or winreg is None:
        return result
    try:
        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS", 0, access) as key:
            mapping = {"SystemManufacturer":"manufacturer", "SystemProductName":"model",
                       "SystemSKU":"system_sku", "BaseBoardManufacturer":"baseboard_manufacturer"}
            for source, target in mapping.items():
                try:
                    result[target] = str(winreg.QueryValueEx(key, source)[0] or "").strip()[:180]
                except OSError:
                    pass
    except OSError:
        pass
    return result


def _oem_control_inventory(running_names: set[str] | None = None) -> dict:
    identity = _system_identity()
    vendor = next((key for key in _OEM_ALIASES if key in identity["manufacturer"].casefold()), "")
    aliases = _OEM_ALIASES.get(vendor, ())
    running_names = {str(name).casefold() for name in (running_names or set())}
    matches = {}
    if IS_WIN and winreg is not None and aliases:
        paths = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", getattr(winreg, "KEY_WOW64_64KEY", 0)),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", getattr(winreg, "KEY_WOW64_32KEY", 0)),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
        )
        for hive, path, view in paths:
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as root:
                    for index in range(min(1500, winreg.QueryInfoKey(root)[0])):
                        try:
                            subkey = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as app:
                                name = str(winreg.QueryValueEx(app, "DisplayName")[0] or "").strip()
                                if not name or not any(alias in name.casefold() for alias in aliases):
                                    continue
                                def field(key: str, limit: int = 160) -> str:
                                    try:
                                        return str(winreg.QueryValueEx(app, key)[0] or "").strip()[:limit]
                                    except OSError:
                                        return ""
                                matches[name.casefold()] = {
                                    "name": name[:160], "version": field("DisplayVersion", 60),
                                    "publisher": field("Publisher", 120),
                                    "install_location": field("InstallLocation", 350),
                                    "running": any(alias.replace(" ", "") in proc.replace(" ", "")
                                                   for alias in aliases for proc in running_names),
                                }
                        except OSError:
                            continue
            except OSError:
                continue
    utilities = sorted(matches.values(), key=lambda row: row["name"].casefold())
    fan_tools = _OEM_FAN_TOOLS.get(vendor, ())
    installed = next((item for item in utilities
                      if any(tool.casefold() in item["name"].casefold() for tool in fan_tools)), None)
    if installed:
        state = "installed"
        message = installed["name"] + " is installed. Use its supported Windows UI for OEM thermal/fan profiles."
    elif fan_tools:
        state = "not_detected"
        message = "No supported OEM fan-profile utility was detected in installed applications. Check the OEM's official tools: " + ", ".join(fan_tools) + "."
    else:
        state = "unsupported_vendor"
        message = "No vendor-specific thermal utility was identified; use only a signed manufacturer utility."
    return {**identity, "vendor_key": vendor, "utilities": utilities,
            "suggested_profile_tools": list(fan_tools), "status": state,
            "control_mode": "guided_only", "message": message, "firmware_writes_enabled": False}


def _steam_roots() -> list[str]:
    candidates = [os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam"),
                  os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Steam")]
    if IS_WIN and winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", 0, winreg.KEY_READ) as key:
                for field in ("SteamPath", "InstallPath"):
                    try:
                        value = str(winreg.QueryValueEx(key, field)[0] or "").strip()
                        if value:
                            candidates.append(value)
                    except OSError:
                        pass
        except OSError:
            pass
    roots, seen = [], set()
    for candidate in candidates:
        path = os.path.abspath(os.path.expandvars(candidate))
        if os.path.isdir(path) and os.path.normcase(path) not in seen:
            roots.append(path)
            seen.add(os.path.normcase(path))
    return roots


def _vdf_value(content: str, key: str) -> str:
    match = re.search(r'"' + re.escape(key) + r'"\s*"((?:[^"\\]|\\.)*)"', content, re.IGNORECASE)
    return match.group(1).replace("\\\\", "\\").replace('\\"', '"') if match else ""


def _game_library_inventory() -> list[dict]:
    if not IS_WIN:
        return []
    games, seen = [], set()
    for root in _steam_roots():
        libraries = [root]
        try:
            raw = Path(os.path.join(root, "steamapps", "libraryfolders.vdf")).read_text(
                encoding="utf-8", errors="replace")[:1024 * 1024]
            for match in re.finditer(r'"path"\s*"((?:[^"\\]|\\.)*)"', raw, re.IGNORECASE):
                library = os.path.abspath(os.path.expandvars(match.group(1).replace("\\\\", "\\")))
                if os.path.isdir(library) and os.path.normcase(library) not in {os.path.normcase(x) for x in libraries}:
                    libraries.append(library)
        except OSError:
            pass
        for library in libraries[:40]:
            app_dir = os.path.join(library, "steamapps")
            try:
                manifests = list(Path(app_dir).glob("appmanifest_*.acf"))[:500]
            except OSError:
                manifests = []
            for manifest in manifests:
                try:
                    raw = manifest.read_text(encoding="utf-8", errors="replace")[:256 * 1024]
                    app_id = re.search(r"appmanifest_(\d+)\.acf$", manifest.name, re.IGNORECASE)
                    name, install_dir = _vdf_value(raw, "name"), _vdf_value(raw, "installdir")
                    size = _vdf_value(raw, "SizeOnDisk")
                    if not app_id or not name or not install_dir:
                        continue
                    common = os.path.abspath(os.path.join(app_dir, "common"))
                    install_path = os.path.abspath(os.path.join(common, install_dir))
                    if os.path.commonpath([install_path, common]).casefold() != common.casefold() or not os.path.isdir(install_path):
                        continue
                    game_id = "steam:" + app_id.group(1)
                    if game_id in seen:
                        continue
                    seen.add(game_id)
                    games.append({"game_id": game_id, "launcher": "Steam", "name": name[:180],
                                  "install_path": install_path, "library_root": library,
                                  "size_bytes": int(size) if size.isdigit() else None,
                                  "relocation_mode": "launcher_native"})
                except (OSError, ValueError):
                    continue
    epic_root = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                             "Epic", "EpicGamesLauncher", "Data", "Manifests")
    try:
        items = list(Path(epic_root).glob("*.item"))[:1000]
    except OSError:
        items = []
    for path in items:
        try:
            item = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            app_id = str(item.get("AppName") or "").strip()
            name = str(item.get("DisplayName") or app_id).strip()
            install = os.path.abspath(os.path.expandvars(str(item.get("InstallLocation") or "")))
            if not app_id or not name or not os.path.isdir(install):
                continue
            try:
                size = int(item.get("InstallSize") or item.get("SizeOnDisk"))
            except (ValueError, TypeError):
                size = None
            game_id = "epic:" + app_id
            if game_id not in seen:
                seen.add(game_id)
                games.append({"game_id": game_id, "launcher": "Epic Games", "name": name[:180],
                              "install_path": install, "library_root": os.path.dirname(install),
                              "size_bytes": size, "relocation_mode": "launcher_guided"})
        except (OSError, ValueError, TypeError):
            continue
    return sorted(games, key=lambda row: (row["launcher"], row["name"].casefold()))[:500]


def game_relocation_plan(game_id: str, target_drive: str) -> dict:
    game = next((row for row in _game_library_inventory() if row["game_id"] == str(game_id)), None)
    if not game:
        raise ValueError("Installed game manifest was not found. Refresh game inventory.")
    drive = str(target_drive or "").rstrip(":\\\\").upper()
    if not re.fullmatch(r"[A-Z]", drive):
        raise ValueError("Target must be a single Windows drive letter.")
    source = os.path.splitdrive(game["install_path"])[0].rstrip(":\\\\").upper()
    partition = next((part for part in psutil.disk_partitions(all=False)
                      if os.path.splitdrive(part.mountpoint)[0].rstrip(":\\\\").upper() == drive), None)
    if not partition:
        raise ValueError("Target volume is not mounted.")
    usage = psutil.disk_usage(partition.mountpoint)
    if source == drive:
        raise ValueError("Game is already installed on this drive.")
    size = game.get("size_bytes")
    if size is None or size <= 0:
        raise ValueError("Launcher manifest has no trustworthy install size; SENTINEL will not guess.")
    required = int(size * 1.10)
    enough = int(usage.free) >= required
    steps = (["Open Steam → Settings → Storage and add/select a library on the target drive.",
              "Select the installed game → Move → choose the target Steam library.",
              "Allow Steam to complete the move; verify installed files if requested."]
             if game["launcher"] == "Steam" else
             ["Open Epic Games Launcher → Library and inspect its supported game-management options.",
              "Use a built-in Move option only if your installed launcher version provides it.",
              "Otherwise use the launcher's backup/reinstall/verification workflow; do not move folders behind manifests."])
    return {"game": game, "source_drive": source, "target_drive": drive,
            "size_bytes": int(size), "required_free_bytes": required,
            "available_free_bytes": int(usage.free), "enough_space": enough, "can_plan": enough,
            "files_will_be_moved_by_sentinel": False,
            "instructions": steps if enough else [
                "Target volume lacks manifest size plus 10% headroom.",
                "Choose a larger target before starting launcher-managed migration."],
            "safety_note": "Read-only plan. SENTINEL never moves launcher-owned files, edits manifests or touches save data."}


def _average_metric(key: str, seconds: int = 45) -> float | None:
    now = time.time()
    values = []
    for ts, value in core.HIST.get(key, []):
        try:
            if now - float(ts) <= seconds and value is not None:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    if len(values) >= 3:
        return sum(values) / len(values)
    try:
        value = core.LIVE.get(key)
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _system_health_report(payload: dict) -> dict:
    findings, coverage = [], {}
    cpu_avg = _average_metric("cpu")
    memory = psutil.virtual_memory()
    coverage.update(cpu=cpu_avg is not None, memory=True)
    if cpu_avg is not None and cpu_avg >= 82:
        procs = sorted(core.STATE.get("procs", []), key=lambda row: float(row.get("cpu") or 0), reverse=True)[:5]
        findings.append({"code":"cpu_pressure","severity":"high" if cpu_avg >= 95 else "warning",
            "title":"Sustained CPU utilization is elevated","confidence":0.88 if len(core.HIST.get("cpu",[]))>=10 else 0.66,
            "detail":"Recent collector samples show elevated CPU use; process rows are evidence, not instructions to terminate.",
            "evidence":{"average_cpu_percent":round(cpu_avg,1),"top_processes":[
                {"name":x.get("name"),"pid":x.get("pid"),"cpu_percent":x.get("cpu"),
                 "executable":x.get("exe"),"create_time":x.get("create_time")} for x in procs]},
            "recommended_actions":["Inspect sustained process consumers and active workloads before changing priority or affinity."],
            "allowed_actions":["process_tune"]})
    if memory.percent >= 88:
        top = sorted(payload.get("top_memory_processes",[]),key=lambda row:float(row.get("rss_mb") or 0),reverse=True)[:5]
        findings.append({"code":"memory_pressure","severity":"high" if memory.percent>=95 else "warning",
            "title":"Available physical memory is low","confidence":0.95,
            "detail":"Physical memory use is elevated. Inspect resident memory consumers before tuning.",
            "evidence":{"memory_percent":round(memory.percent,1),"available_gib":round(memory.available/1024**3,2),
                "top_processes":[{"name":x.get("name"),"pid":x.get("pid"),"rss_mb":x.get("rss_mb"),
                                 "executable":x.get("exe")} for x in top]},
            "recommended_actions":["Review applications you recognize; any process adjustment requires an exact identity preview."],
            "allowed_actions":["process_tune"]})
    volumes = payload.get("volumes",[])
    coverage["storage"] = bool(volumes)
    for row in volumes:
        try: free,used=float(row.get("free_gib") or 0),float(row.get("used_percent") or 0)
        except (TypeError,ValueError): continue
        if free<8 or used>=93:
            findings.append({"code":"disk_capacity","severity":"high" if free<3 or used>=98 else "warning",
                "title":"Storage headroom is low on "+str(row.get("mountpoint")),
                "confidence":0.96,"detail":"This volume is approaching its capacity threshold.",
                "evidence":{"mountpoint":row.get("mountpoint"),"free_gib":round(free,1),
                            "used_percent":round(used,1),"filesystem":row.get("filesystem")},
                "recommended_actions":["Review the bounded temporary/shader cleanup manifest before deleting anything.",
                    "Game folders, downloads, documents and Windows Update storage are not automatic cleanup targets."],
                "allowed_actions":["cleanup"]})
    sensor_data=payload.get("thermal") or {}
    temps=[]
    for sensor in sensor_data.get("sensors",[]) if isinstance(sensor_data,dict) else []:
        try:
            if "temp" in str(sensor.get("type","")).casefold():
                val=float(sensor.get("value"))
                if -20<=val<=150: temps.append({"name":str(sensor.get("name") or "temperature"),"celsius":round(val,1)})
        except (AttributeError,TypeError,ValueError): continue
    coverage["thermal"]=bool(temps)
    hottest=max(temps,key=lambda x:x["celsius"],default=None)
    if hottest and hottest["celsius"]>=85:
        findings.append({"code":"thermal_pressure","severity":"high" if hottest["celsius"]>=92 else "warning",
            "title":"Hardware temperature is elevated","confidence":0.82,
            "detail":"Correlate the sensor with sustained load and GPU throttling; sensor coverage varies by hardware.",
            "evidence":{"hottest_sensor":hottest,"sensor_count":len(temps),"gpu":core.STATE.get("gpu",{})},
            "recommended_actions":["Check airflow, dust and workload; use an OEM thermal-profile utility if detected.",
                "SENTINEL never writes undocumented fan firmware, EC or ACPI registers."],"allowed_actions":[]})
    gpu=core.STATE.get("gpu") or {}
    coverage["gpu"]=bool(gpu)
    if gpu.get("throttle"):
        findings.append({"code":"gpu_throttle","severity":"warning","title":"GPU reports a throttling condition",
            "confidence":0.86,"detail":"The graphics driver reports an active throttle reason.",
            "evidence":{"name":gpu.get("name"),"temperature":gpu.get("temp"),"utilization":gpu.get("util"),
                        "throttle_reasons":gpu.get("throttle")},
            "recommended_actions":["Compare temperature, power limit and workload in supported GPU/OEM software."],
            "allowed_actions":[]})
    ping,loss,jitter=_average_metric("ping"),_average_metric("loss"),_average_metric("jitter")
    coverage["network"]=ping is not None or loss is not None
    if (loss is not None and loss>0) or (ping is not None and ping>=120) or (jitter is not None and jitter>=40):
        findings.append({"code":"network_latency","severity":"warning","title":"Network latency or packet loss is elevated",
            "confidence":0.74 if ping is not None else 0.55,
            "detail":"A current probe shows degradation; one probe cannot identify Wi-Fi, router, ISP or remote-server cause.",
            "evidence":{"average_ping_ms":round(ping,1) if ping is not None else None,
                "packet_loss_percent":round(loss,1) if loss is not None else None,
                "average_jitter_ms":round(jitter,1) if jitter is not None else None,"probe_target":"1.1.1.1"},
            "recommended_actions":["Compare resolver latency and inspect adapter state before considering a reset."],
            "allowed_actions":["dns_set","adapter_restart"]})
    system=core.STATE.get("system") or {}
    coverage["platform"]=bool(system or payload.get("system_identity",{}).get("model"))
    if system.get("defender_rt") is False:
        findings.append({"code":"defender_realtime_off","severity":"high","title":"Windows Defender real-time protection reports OFF",
            "confidence":0.9,"detail":"Security-posture observation only. SENTINEL will not change Defender settings.",
            "evidence":{"defender_realtime":False},"recommended_actions":["Review Windows Security directly."],"allowed_actions":[]})
    severity_order={"critical":0,"high":1,"warning":2,"info":3}
    findings.sort(key=lambda x:(severity_order.get(x["severity"],4),-float(x["confidence"])))
    coverage_count=sum(bool(value) for value in coverage.values())
    score=max(0,100-sum({"critical":25,"high":16,"warning":8,"info":0}.get(x["severity"],0) for x in findings))
    state="insufficient_data" if coverage_count<3 else (
        "attention_required" if any(x["severity"] in ("critical","high") for x in findings) else
        "watch" if findings else "healthy_observed")
    return {"generated_at":time.time(),"engine":"local-evidence-correlator-v1",
        "health_score":score if coverage_count>=3 else None,"state":state,
        "coverage":coverage,"coverage_count":coverage_count,"findings":findings[:20],
        "note":"Heuristic evidence summary, not a diagnosis guarantee. Findings are limited to local measurements available to SENTINEL."}


def _read_only_diagnostics() -> dict:
    errors = {}
    results = {}
    resource_safe = False
    try:
        game_active = bool(core.STATE.get("game")) or bool(safeguard.snapshot().get("valorant_active"))
        available_gib = psutil.virtual_memory().available / (1024 ** 3)
        cpu_percent = psutil.cpu_percent(interval=0.1)
        resource_safe = not game_active and available_gib >= 3.0 and cpu_percent < 85.0
    except Exception:
        resource_safe = False
    scan_functions = [("adapters", _get_adapters), ("dns", _get_dns), ("startup", _startup_inventory)]
    if resource_safe:
        scan_functions.extend([("drivers", _get_drivers), ("driver_updates", _get_driver_updates)])
    else:
        results["drivers"] = []
        results["driver_updates"] = []
        errors["drivers"] = "Deferred during game session or resource pressure."
        errors["driver_updates"] = "Deferred during game session or resource pressure."
    for key, function in scan_functions:
        try:
            results[key] = function()
        except Exception as exc:
            results[key] = []
            errors[key] = f"{type(exc).__name__}: {str(exc)[:160]}"
    volumes = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            volumes.append({"device": part.device, "mountpoint": part.mountpoint, "filesystem": part.fstype,
                            "total_gib": round(usage.total / 1024**3, 1), "free_gib": round(usage.free / 1024**3, 1),
                            "used_percent": usage.percent})
        except OSError:
            continue
    processes = []
    running_names = set()
    for proc in psutil.process_iter(attrs=["pid", "name", "exe", "memory_info", "create_time"]):
        try:
            info = proc.info
            if info.get("name"):
                running_names.add(str(info["name"]))
            if info.get("memory_info"):
                processes.append({"pid": info["pid"], "name": info.get("name"), "exe": info.get("exe"),
                                  "rss_mb": round(info["memory_info"].rss / 1048576, 1),
                                  "create_time": info.get("create_time")})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda item: item["rss_mb"], reverse=True)
    policy = _policy()
    payload = {"updated_at": time.time(), "administrator": _is_admin(), "safeguard": safeguard.snapshot(),
            **results, "volumes": volumes, "top_memory_processes": processes[:15],
            "thermal": core.STATE.get("hardware_sensors") or {}, "scheduler": policy,
            "budget": _budget_state(), "kill_switch": policy["kill_switch"],
            "power_scheme": _active_scheme() if IS_WIN else None,
            "journal": journal(30), "predictive": _predictive_scan(),
            "system_identity": _system_identity(),
            "oem_control": _oem_control_inventory(running_names),
            "game_libraries": _game_library_inventory(),
            "guided_recovery": {
                "game_relocation": "Move games through Steam, Epic, Xbox or the game's own library manager so library manifests stay consistent.",
                "vendor_fan_control": "Use the supported laptop vendor utility. Sentinel will not write undocumented EC/ACPI fan registers.",
                "bios_secure_boot": "Read-only inspection and instructions only. Sentinel never edits BIOS/UEFI or Secure Boot.",
            }, "source_errors": errors}
    payload["system_health"] = _system_health_report(payload)
    return payload


def _placeholder_status() -> dict:
    policy = _policy()
    return {"updated_at": 0, "diagnostics_state": "collecting" if IS_WIN else "unsupported",
            "administrator": _is_admin(), "safeguard": safeguard.snapshot(),
            "adapters": [], "dns": [], "drivers": [], "driver_updates": [], "startup": [],
            "volumes": [], "top_memory_processes": [], "thermal": core.STATE.get("hardware_sensors") or {},
            "scheduler": policy, "budget": _budget_state(), "kill_switch": policy["kill_switch"],
            "power_scheme": None, "journal": journal(30), "predictive": [],
            "source_errors": {}, "guided_recovery": {
                "game_relocation": "Use the supported launcher library manager (Steam/Epic/Xbox); Sentinel does not move launcher-owned game folders directly.",
                "vendor_fan_control": "Use the OEM's supported profile utility. Sentinel does not write undocumented EC/ACPI fan registers.",
                "bios_secure_boot": "Read-only inspection and instructions only.",
            }}


def _refresh_diagnostics_worker() -> None:
    try:
        payload = _read_only_diagnostics()
        payload["diagnostics_state"] = "ready"
        with _DIAG_LOCK:
            _DIAG_CACHE.update(at=time.time(), payload=payload, refreshing=False)
        core.STATE["maintenance"] = payload
        core.publish("maintenance_status", {"state": "ready", "updated_at": payload.get("updated_at"),
                                             "source_errors": payload.get("source_errors", {})})
    except Exception as exc:
        with _DIAG_LOCK:
            cached = _DIAG_CACHE.get("payload") or _placeholder_status()
            cached["diagnostics_state"] = "degraded"
            cached.setdefault("source_errors", {})["maintenance"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            _DIAG_CACHE.update(at=time.time(), payload=cached, refreshing=False)
        core.log("maintenance", f"background diagnostics failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")


def queue_diagnostics(force: bool = False) -> dict:
    with _DIAG_LOCK:
        cached = _DIAG_CACHE.get("payload")
        fresh = cached and time.time() - float(_DIAG_CACHE.get("at") or 0) < 30
        if _DIAG_CACHE.get("refreshing"):
            return cached or _placeholder_status()
        if fresh and not force:
            return cached
        _DIAG_CACHE["refreshing"] = True
    threading.Thread(target=_refresh_diagnostics_worker, name="maintenance-diagnostics", daemon=True).start()
    payload = dict(cached or _placeholder_status())
    payload["diagnostics_state"] = "refreshing"
    return payload


def status(refresh: bool = False) -> dict:
    return queue_diagnostics(force=refresh)


def goal_plan(goal: str) -> dict:
    text = str(goal or "").strip().casefold()
    if not text or len(text) > 240:
        raise ValueError("Goal must contain between 1 and 240 characters.")
    payload = status()
    report = payload.get("system_health") or _system_health_report(payload)
    findings = report.get("findings", [])
    categories = {
        "performance": ("cpu_pressure", "memory_pressure", "gpu_throttle", "thermal_pressure"),
        "fast": ("cpu_pressure", "memory_pressure", "gpu_throttle", "disk_capacity"),
        "slow": ("cpu_pressure", "memory_pressure", "disk_capacity", "network_latency"),
        "lag": ("cpu_pressure", "memory_pressure", "gpu_throttle", "network_latency", "thermal_pressure"),
        "thermal": ("thermal_pressure", "gpu_throttle"),
        "heat": ("thermal_pressure", "gpu_throttle"),
        "cool": ("thermal_pressure", "gpu_throttle"),
        "fan": ("thermal_pressure",),
        "network": ("network_latency",),
        "wifi": ("network_latency",),
        "internet": ("network_latency",),
        "dns": ("network_latency",),
        "storage": ("disk_capacity",),
        "disk": ("disk_capacity",),
        "space": ("disk_capacity",),
        "memory": ("memory_pressure",),
        "ram": ("memory_pressure",),
        "gpu": ("gpu_throttle", "thermal_pressure"),
        "security": ("defender_realtime_off",),
    }
    relevant = {code for token, codes in categories.items() if token in text for code in codes}
    selected = [item for item in findings
                if item["code"] in relevant or item["severity"] in ("critical", "high")]
    if not relevant:
        selected = findings[:12]
    recommendations = []
    for item in selected:
        recommendations.extend(item.get("recommended_actions", []))
    if not selected:
        recommendations.append("No current threshold was crossed in measured CPU, memory, thermal, disk or network signals. Re-scan during the workload where the problem occurs.")
    if any(token in text for token in ("battery", "power", "portable")):
        recommendations.append("Review battery condition and the current Windows power plan; any plan change still requires a separate preview and confirmation.")
    if any(token in text for token in ("quiet", "silent", "noise")):
        vendor = payload.get("oem_control") or {}
        recommendations.append(vendor.get("message") or "Use the manufacturer's signed thermal-profile utility. Direct fan-register writes remain disabled.")
    if any(token in text for token in ("game", "move", "relocate", "library")):
        recommendations.append("Use the Game Library section to build a capacity-checked migration plan. SENTINEL will not move launcher-owned folders.")
    allowed = sorted({action for item in selected for action in item.get("allowed_actions", [])})
    return {
        "goal": goal, "generated_by": "local-evidence-correlator-v1",
        "health_score": report.get("health_score"), "health_state": report.get("state"),
        "coverage": report.get("coverage", {}),
        "findings": selected, "recommendations": list(dict.fromkeys(recommendations)),
        "allowed_actions": allowed, "automatic_execution": False,
        "needs_preview_and_confirmation": True,
        "safeguard": payload.get("safeguard"),
        "security_and_launcher_manifests_never_modified": True,
    }


def daily_digest() -> dict:
    done = core.db("SELECT COUNT(*) FROM maintenance_journal WHERE status='done' AND created_at>=?", (time.time() - 86400,))[0][0]
    blocked = core.db("SELECT COUNT(*) FROM events WHERE src='safeguard' AND ts>=?", (time.time() - 86400,))[0][0]
    pending = core.db("SELECT COUNT(*) FROM actions WHERE state='pending'")[0][0]
    failed = core.db("SELECT COUNT(*) FROM maintenance_jobs WHERE state='failed' AND created_at>=?", (time.time() - 86400,))[0][0]
    return {"day": time.strftime("%Y-%m-%d"), "completed": int(done), "blocked": int(blocked),
            "pending_approvals": int(pending), "failed": int(failed), "recent": journal(10)}


def _idle_seconds() -> float:
    if not IS_WIN:
        return 0.0
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)
    except Exception:
        return 0.0


def _scheduler_loop() -> None:
    while not _STOP.wait(60):
        policy = _policy()
        if not policy["scheduler_enabled"] or not IS_WIN:
            continue
        safe = safeguard.snapshot()
        if not safe.get("process_detection_complete") or safe.get("valorant_active"):
            continue
        now = time.time()
        idle = _idle_seconds()
        if idle >= policy["idle_minutes"] * 60 and now - policy["last_idle_run"] > 3600:
            try:
                data = _read_only_diagnostics()
                core.db("UPDATE maintenance_policy SET last_idle_run=? WHERE id=1", (now,))
                core.publish("maintenance_digest", {"type": "idle_diagnostics", "updated_at": now,
                                                     "predictive": data.get("predictive", [])})
            except Exception as exc:
                core.log("maintenance", f"idle diagnostics failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")
        if policy["weekly_diagnostics"] and now - policy["last_weekly_run"] > 7 * 86400 and idle >= policy["idle_minutes"] * 60:
            try:
                data = _read_only_diagnostics()
                core.db("UPDATE maintenance_policy SET last_weekly_run=? WHERE id=1", (now,))
                core.publish("maintenance_digest", {"type": "weekly_diagnostics", "updated_at": now,
                                                     "volume_count": len(data.get("volumes", [])),
                                                     "driver_update_count": len(data.get("driver_updates", []))})
            except Exception as exc:
                core.log("maintenance", f"weekly diagnostics failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")


def start() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    _STOP.clear()
    queue_diagnostics(force=True)
    core.thread(_scheduler_loop, "maintenance-scheduler")


def shutdown() -> None:
    _STOP.set()
