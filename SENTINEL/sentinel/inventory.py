"""Windows system inventory with explicit source health and fail-visible queries.

A missing API, inaccessible PowerShell executable, or denied CIM namespace is shown as
UNKNOWN instead of being silently rendered as an empty inventory or a healthy posture.
"""
from __future__ import annotations

import json
import os
import platform
import time
from typing import Any

import psutil

from .core import IS_WIN, STATE, insight, log, heartbeat, prof, off
from .winutil import powershell

INV: dict[str, Any] = {"ts": 0, "health": {}}
_posted: set[str] = set()

# Only used by --demo / non-Windows runs. Every source is explicitly labelled
# synthetic so this catalog can exercise the UI without masquerading as host facts.
DEMO_INVENTORY = {
    "apps": [
        {"name": "Brave Browser", "version": "demo", "publisher": "Brave Software"},
        {"name": "Discord", "version": "demo", "publisher": "Discord Inc."},
        {"name": "Steam", "version": "demo", "publisher": "Valve"},
        {"name": "Visual Studio Code", "version": "demo", "publisher": "Microsoft"},
    ],
    "tasks": [
        {"name": "SentinelAgent-Demo", "state": "Ready", "path": "\\Sentinel"},
        {"name": "VendorUpdate-Demo", "state": "Ready", "path": "\\Vendor"},
    ],
    "drivers": [
        {"name": "demo_gpu_driver", "display": "Synthetic GPU display driver", "state": "Running", "start": "Boot"},
        {"name": "demo_audio_driver", "display": "Synthetic audio driver", "state": "Running", "start": "System"},
    ],
    "services": [
        {"name": "vgc", "display": "Riot Vanguard Client", "state": "running", "start": "auto", "pid": 4200},
        {"name": "vgk", "display": "Riot Vanguard Kernel Driver", "state": "running", "start": "system", "pid": 4},
        {"name": "wuauserv", "display": "Windows Update", "state": "stopped", "start": "manual", "pid": 0},
    ],
    "startup": [
        {"name": "Demo launcher", "where": "HKCU\\Run (synthetic)", "cmd": "<synthetic demo entry>"},
    ],
    "platform": {},
    "security": {
        "defender_rt": True, "signature_age_days": 1,
        "firewall": [{"name": "Domain", "on": True}, {"name": "Private", "on": True}, {"name": "Public", "on": True}],
        "secure_boot": True, "bitlocker": [],
    },
    "physical": [{"name": "Demo NVMe SSD", "gb": 1024, "type": "SSD", "bus": "NVMe", "health": "Healthy"}],
}


def _ps(script: str, timeout: float = 60):
    """Run PowerShell via an absolute executable path and preserve useful diagnostics."""
    health = INV.setdefault("health", {})
    try:
        result = powershell(script, timeout=timeout)
        out = (result.stdout or "").strip().lstrip("\ufeff")
        if result.returncode != 0:
            health["powershell"] = {"ok": False, "error": (result.stderr or out or f"exit code {result.returncode}")[-700:]}
            log("inventory", f"PowerShell inventory query exited {result.returncode}: {(result.stderr or out)[:180]}", "warn")
        else:
            health["powershell"] = {"ok": True, "error": ""}
        if not out:
            return None
        payload = json.loads(out)
        if not isinstance(payload, dict):
            raise ValueError("inventory response was not a JSON object")
        return payload
    except Exception as exc:
        health["powershell"] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        log("inventory", f"PowerShell inventory unavailable: {type(exc).__name__}: {str(exc)[:180]}", "error")
        return None


def _list(value):
    return value if isinstance(value, list) else ([value] if value is not None else [])


def _volumes():
    out, errors = [], []
    for part in psutil.disk_partitions(all=False):
        if "ro" in part.opts.split(",") or part.fstype in ("", "squashfs", "overlay", "tmpfs", "iso9660", "cdrom"):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            if usage.total < 2**30:
                continue
            out.append({"mount": part.mountpoint, "fs": part.fstype,
                "total_gb": round(usage.total / 2**30, 1), "free_gb": round(usage.free / 2**30, 1),
                "free_pct": round(100 - usage.percent, 1)})
        except (OSError, PermissionError) as exc:
            errors.append({"mount": part.mountpoint, "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
    INV.setdefault("health", {})["volumes"] = {"ok": bool(out), "count": len(out), "errors": errors[:12]}
    return out


def _ifaces():
    stats, addresses, out, errors = psutil.net_if_stats(), psutil.net_if_addrs(), [], []
    for name, stat in stats.items():
        try:
            # No MAC addresses are collected. IPv4 is retained for the existing local adapter view.
            ip = next((a.address for a in addresses.get(name, []) if a.family == getattr(__import__("socket"), "AF_INET")), "")
            out.append({"name": name, "up": stat.isup, "mbps": stat.speed, "ip": ip})
        except Exception as exc:
            errors.append({"interface": name, "error": type(exc).__name__})
    INV.setdefault("health", {})["interfaces"] = {"ok": bool(out), "count": len(out), "errors": errors}
    return out


def _services():
    """Reuse the isolated SCM collector so inventory and live service views agree."""
    if not IS_WIN:
        INV.setdefault("health", {})["services"] = {"ok": True, "count": 0, "errors": [], "mode": "non-Windows demo"}
        return []
    try:
        from .collectors import _read_services
        records, errors = _read_services()
        INV.setdefault("health", {})["services"] = {
            "ok": not any(not item.get("recovered") for item in errors), "count": len(records), "errors": errors[:30],
            "mode": "psutil SCM with Win32_Service CIM recovery", "empty_is_valid": True,
        }
        return records
    except Exception as exc:
        INV.setdefault("health", {})["services"] = {
            "ok": False, "count": 0, "errors": [{"service": "<collector>", "error": f"{type(exc).__name__}: {str(exc)[:180]}"}],
            "mode": "SCM source unavailable",
        }
        return []


def _startup():
    # A real empty list is meaningful. Never substitute demo entries on Windows.
    return list(STATE.get("startup") or [])


WIN_SCRIPT = r"""
$ErrorActionPreference='Stop'
$o=@{}; $h=@{}
try {
  $o.apps=@(Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*','HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName} | Select-Object @{n='name';e={$_.DisplayName}},@{n='version';e={$_.DisplayVersion}},@{n='publisher';e={$_.Publisher}},@{n='install_date';e={$_.InstallDate}},@{n='location';e={$_.InstallLocation}})
  $h.apps=@{ok=$true;count=$o.apps.Count}
} catch {$o.apps=@();$h.apps=@{ok=$false;error=$_.Exception.Message}}
try {
  $o.tasks=@(Get-ScheduledTask -ErrorAction Stop | ForEach-Object {
    $actions=@()
    foreach($action in @($_.Actions)){
      $execute=[string]$action.Execute
      $binary=''
      if($execute){try{$binary=[IO.Path]::GetFileName($execute.Trim([char]34))}catch{$binary=''}}
      if($binary){$actions += $binary}
    }
    [pscustomobject]@{
      name=$_.TaskName;state=[string]$_.State;path=$_.TaskPath;author=$_.Author
      action_binaries=@($actions | Sort-Object -Unique | Select-Object -First 6)
      action_count=@($_.Actions).Count
    }
  })
  $h.tasks=@{ok=$true;count=$o.tasks.Count}
} catch {$o.tasks=@();$h.tasks=@{ok=$false;error=$_.Exception.Message}}
try {
  $o.drivers=@(Get-CimInstance Win32_SystemDriver -ErrorAction Stop | Select-Object @{n='name';e={$_.Name}},@{n='state';e={$_.State}},@{n='start';e={$_.StartMode}},@{n='display';e={$_.DisplayName}},@{n='path';e={$_.PathName}},@{n='service_type';e={$_.ServiceType}})
  $h.drivers=@{ok=$true;count=$o.drivers.Count}
} catch {$o.drivers=@();$h.drivers=@{ok=$false;error=$_.Exception.Message}}
try {
  $b=Get-CimInstance Win32_BIOS -ErrorAction Stop
  $c=Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
  $os=Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  $o.platform=@{os=$os.Caption;build=$os.BuildNumber;version=$os.Version;architecture=$os.OSArchitecture;cpu=$c.Name;bios=$b.SMBIOSBIOSVersion;bios_date="$($b.ReleaseDate)";install_date="$($os.InstallDate)";last_boot="$($os.LastBootUpTime)"}
  $h.platform=@{ok=$true}
} catch {$o.platform=@{};$h.platform=@{ok=$false;error=$_.Exception.Message}}
$sec=@{}
try {$m=Get-MpComputerStatus -ErrorAction Stop;$sec.defender_rt=[bool]$m.RealTimeProtectionEnabled;$sec.signature_age_days=$m.AntivirusSignatureAge;$sec.antivirus_enabled=[bool]$m.AntivirusEnabled;$h.defender=@{ok=$true}} catch {$h.defender=@{ok=$false;error=$_.Exception.Message}}
try {$sec.firewall=@(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object {@{name="$($_.Name)";on=[bool]$_.Enabled}});$h.firewall=@{ok=$true;count=$sec.firewall.Count}} catch {$h.firewall=@{ok=$false;error=$_.Exception.Message}}
try {$sec.secure_boot=[bool](Confirm-SecureBootUEFI -ErrorAction Stop);$h.secure_boot=@{ok=$true}} catch {$h.secure_boot=@{ok=$false;error=$_.Exception.Message}}
try {$sec.bitlocker=@(Get-BitLockerVolume -ErrorAction Stop | ForEach-Object {@{mount="$($_.MountPoint)";status="$($_.ProtectionStatus)";volume_status="$($_.VolumeStatus)";encryption="$($_.EncryptionPercentage)"}});$h.bitlocker=@{ok=$true;count=$sec.bitlocker.Count}} catch {$h.bitlocker=@{ok=$false;error=$_.Exception.Message}}
$o.security=$sec
try {$o.physical=@(Get-PhysicalDisk -ErrorAction Stop | Select-Object @{n='name';e={$_.FriendlyName}},@{n='health';e={"$($_.HealthStatus)"}},@{n='gb';e={[math]::Round($_.Size/1GB,1)}},@{n='type';e={"$($_.MediaType)"}},@{n='bus';e={"$($_.BusType)"}},@{n='operational';e={($_.OperationalStatus -join ',')}});$h.physical=@{ok=$true;count=$o.physical.Count}} catch {$o.physical=@();$h.physical=@{ok=$false;error=$_.Exception.Message}}
$o.health=$h
$o | ConvertTo-Json -Depth 7 -Compress
"""


def _posture(inv):
    security = inv.get("security") or {}
    out = []
    if security.get("defender_rt") is False:
        out.append(("high", "posture-defender", "Defender real-time protection is OFF", "Windows Security > Virus & threat protection"))
    for firewall in security.get("firewall") or []:
        if firewall.get("on") is False and firewall.get("name") != "Private":
            out.append(("warn", "posture-fw-" + str(firewall.get("name")), f"Firewall off on {firewall.get('name')} profile", "Review Windows Firewall profile settings"))
    if security.get("secure_boot") is False:
        out.append(("warn", "posture-secureboot", "Secure Boot is disabled", "Review UEFI Secure Boot configuration"))
    for volume in inv.get("volumes", []):
        if volume.get("free_pct", 100) < prof("thresholds", "disk_free_pct"):
            out.append(("warn", "posture-disk-" + volume["mount"], f"Low disk space on {volume['mount']}: {volume['free_pct']}% free", "Free space before large updates or game installs"))
    battery = STATE.get("system", {}).get("battery")
    if battery and battery.get("pct", 100) < prof("thresholds", "battery_pct") and not battery.get("plugged"):
        out.append(("warn", "posture-battery", f"Battery low: {battery['pct']}% and unplugged", "Connect power or reduce workload"))
    active = {item[1] for item in out}
    _posted.intersection_update(active)
    inv["posture"] = [{"sev": sev, "key": key, "title": title, "detail": detail} for sev, key, title, detail in out]
    for sev, key, title, detail in out:
        if key not in _posted:
            _posted.add(key)
            insight(sev, key, title, detail, "posture")
    source_health = inv.get("health", {})
    critical_sources = ("platform", "defender", "firewall", "secure_boot", "physical")
    unknown = [name for name in critical_sources if not source_health.get(name, {}).get("ok", False)]
    inv["posture_summary"] = {
        "count": len(out), "high": sum(1 for row in out if row[0] == "high"),
        "status": "findings" if out else ("incomplete" if unknown else "clear"),
        "unknown_sources": unknown,
    }


def scan():
    started = time.time()
    health = {}
    volumes = _volumes()
    interfaces = _ifaces()
    services = _services()
    processes = list(STATE.get("procs") or [])
    if IS_WIN:
        extra = _ps(WIN_SCRIPT, timeout=60) or {}
        for name in ("apps", "tasks", "drivers", "platform", "security", "defender", "firewall", "secure_boot", "bitlocker", "physical"):
            health[name] = (extra.get("health") or {}).get(name, {"ok": False, "error": "query did not return source health"})
        health["powershell"] = INV.get("health", {}).get("powershell", {"ok": False, "error": "not queried"})
        apps, tasks, drivers = _list(extra.get("apps")), _list(extra.get("tasks")), _list(extra.get("drivers"))
        plat, security, physical = extra.get("platform") or {}, extra.get("security") or {}, _list(extra.get("physical"))
    else:
        extra = DEMO_INVENTORY
        services = _list(extra.get("services"))
        apps, tasks, drivers = _list(extra.get("apps")), _list(extra.get("tasks")), _list(extra.get("drivers"))
        plat, security, physical = dict(extra.get("platform") or {}), dict(extra.get("security") or {}), _list(extra.get("physical"))
        health = {key: {"ok": True, "mode": "synthetic demo data"} for key in (
            "apps", "tasks", "drivers", "platform", "security", "defender",
            "firewall", "secure_boot", "bitlocker", "physical", "powershell", "services") }
    plat.setdefault("host", platform.node())
    plat.setdefault("os", platform.platform())
    plat.setdefault("architecture", platform.machine())
    plat["cpus"] = f"{psutil.cpu_count(logical=False)}C/{psutil.cpu_count()}T"
    plat["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    plat["ram_available_gb"] = round(psutil.virtual_memory().available / 2**30, 2)
    inv = {
        "ts": time.time(), "duration_s": round(time.time() - started, 3),
        "volumes": volumes, "interfaces": interfaces, "services": services,
        "startup": list(extra.get("startup", [])) if not IS_WIN else _startup(), "processes": processes,
        "apps": apps, "tasks": tasks, "drivers": drivers,
        "platform": plat, "security": security, "physical": physical,
        "health": {**health, "services": INV.get("health", {}).get("services", {}),
                   "volumes": INV.get("health", {}).get("volumes", {}),
                   "interfaces": INV.get("health", {}).get("interfaces", {})},
    }
    _posture(inv)
    INV.clear(); INV.update(inv)
    # Persist a compact, integrity-stamped snapshot to the same permanent SQLite
    # database as settings and intelligence. Keep volatile per-second process rows
    # out of this copy; the dedicated process snapshot has its own refresh cadence.
    try:
        from .core import persist_snapshot
        durable = {k: v for k, v in inv.items() if k != "processes"}
        persist_snapshot("inventory.latest", durable)
    except Exception as exc:
        log("storage", f"inventory snapshot persistence failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")
    return inv


def summary():
    data = INV
    count_keys = ("processes", "apps", "drivers", "services", "tasks", "interfaces", "volumes", "startup")
    counts = {key: len(data.get(key) or []) for key in count_keys}
    return {"ts": data.get("ts", 0), "duration_s": data.get("duration_s"), "counts": counts,
        **{key: data.get(key) for key in ("platform", "security", "volumes", "physical", "posture", "posture_summary", "health")}}


def catalog(kind, q="", limit=120):
    rows = INV.get(kind, []) or []
    q = str(q or "").casefold()
    hit = [row for row in rows if not q or q in json.dumps(row, ensure_ascii=False, default=str).casefold()]
    return {"kind": kind, "total": len(rows), "matched": len(hit), "rows": hit[:max(1, min(2000, int(limit)))]}


def loop():
    while True:
        t0 = time.time()
        if off("inventory"):
            heartbeat("system inventory", 600, "disabled in Feature Control"); time.sleep(30); continue
        try:
            scan()
            counts = INV.get("health", {})
            failed = [key for key, value in counts.items() if isinstance(value, dict) and value.get("ok") is False]
            heartbeat("system inventory", 600,
                f"{len(INV.get('apps', []))} apps, {len(INV.get('drivers', []))} drivers; {len(failed)} source issues",
                err=(counts[failed[0]].get("error", "source unavailable") if failed else ""))
        except Exception as exc:
            heartbeat("system inventory", 600, err=f"{type(exc).__name__}: {str(exc)[:200]}")
            log("inventory", f"inventory scan failed: {type(exc).__name__}: {str(exc)[:200]}", "error")
        delay = max(5, prof("intervals", "inventory_min") * 60 - (time.time() - t0))
        try:
            from . import runtime_engine
            delay = runtime_engine.inventory_delay(delay)
        except Exception:
            pass
        time.sleep(delay),''))}catch{$binary=''}}
      if($binary){$actions+= $binary}
    }
    [pscustomobject]@{
      name=$_.TaskName;state=[string]$_.State;path=$_.TaskPath;author=$_.Author
      action_binaries=@($actions | Sort-Object -Unique | Select-Object -First 6)
      action_count=@($_.Actions).Count
    }
  })
  $h.tasks=@{ok=$true;count=$o.tasks.Count}
} catch {$o.tasks=@();$h.tasks=@{ok=$false;error=$_.Exception.Message}}
try {
  $o.drivers=@(Get-CimInstance Win32_SystemDriver -ErrorAction Stop | Select-Object @{n='name';e={$_.Name}},@{n='state';e={$_.State}},@{n='start';e={$_.StartMode}},@{n='display';e={$_.DisplayName}},@{n='path';e={$_.PathName}},@{n='service_type';e={$_.ServiceType}})
  $h.drivers=@{ok=$true;count=$o.drivers.Count}
} catch {$o.drivers=@();$h.drivers=@{ok=$false;error=$_.Exception.Message}}
try {
  $b=Get-CimInstance Win32_BIOS -ErrorAction Stop
  $c=Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
  $os=Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  $o.platform=@{os=$os.Caption;build=$os.BuildNumber;version=$os.Version;architecture=$os.OSArchitecture;cpu=$c.Name;bios=$b.SMBIOSBIOSVersion;bios_date="$($b.ReleaseDate)";install_date="$($os.InstallDate)";last_boot="$($os.LastBootUpTime)"}
  $h.platform=@{ok=$true}
} catch {$o.platform=@{};$h.platform=@{ok=$false;error=$_.Exception.Message}}
$sec=@{}
try {$m=Get-MpComputerStatus -ErrorAction Stop;$sec.defender_rt=[bool]$m.RealTimeProtectionEnabled;$sec.signature_age_days=$m.AntivirusSignatureAge;$sec.antivirus_enabled=[bool]$m.AntivirusEnabled;$h.defender=@{ok=$true}} catch {$h.defender=@{ok=$false;error=$_.Exception.Message}}
try {$sec.firewall=@(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object {@{name="$($_.Name)";on=[bool]$_.Enabled}});$h.firewall=@{ok=$true;count=$sec.firewall.Count}} catch {$h.firewall=@{ok=$false;error=$_.Exception.Message}}
try {$sec.secure_boot=[bool](Confirm-SecureBootUEFI -ErrorAction Stop);$h.secure_boot=@{ok=$true}} catch {$h.secure_boot=@{ok=$false;error=$_.Exception.Message}}
try {$sec.bitlocker=@(Get-BitLockerVolume -ErrorAction Stop | ForEach-Object {@{mount="$($_.MountPoint)";status="$($_.ProtectionStatus)";volume_status="$($_.VolumeStatus)";encryption="$($_.EncryptionPercentage)"}});$h.bitlocker=@{ok=$true;count=$sec.bitlocker.Count}} catch {$h.bitlocker=@{ok=$false;error=$_.Exception.Message}}
$o.security=$sec
try {$o.physical=@(Get-PhysicalDisk -ErrorAction Stop | Select-Object @{n='name';e={$_.FriendlyName}},@{n='health';e={"$($_.HealthStatus)"}},@{n='gb';e={[math]::Round($_.Size/1GB,1)}},@{n='type';e={"$($_.MediaType)"}},@{n='bus';e={"$($_.BusType)"}},@{n='operational';e={($_.OperationalStatus -join ',')}});$h.physical=@{ok=$true;count=$o.physical.Count}} catch {$o.physical=@();$h.physical=@{ok=$false;error=$_.Exception.Message}}
$o.health=$h
$o | ConvertTo-Json -Depth 7 -Compress
"""


def _posture(inv):
    security = inv.get("security") or {}
    out = []
    if security.get("defender_rt") is False:
        out.append(("high", "posture-defender", "Defender real-time protection is OFF", "Windows Security > Virus & threat protection"))
    for firewall in security.get("firewall") or []:
        if firewall.get("on") is False and firewall.get("name") != "Private":
            out.append(("warn", "posture-fw-" + str(firewall.get("name")), f"Firewall off on {firewall.get('name')} profile", "Review Windows Firewall profile settings"))
    if security.get("secure_boot") is False:
        out.append(("warn", "posture-secureboot", "Secure Boot is disabled", "Review UEFI Secure Boot configuration"))
    for volume in inv.get("volumes", []):
        if volume.get("free_pct", 100) < prof("thresholds", "disk_free_pct"):
            out.append(("warn", "posture-disk-" + volume["mount"], f"Low disk space on {volume['mount']}: {volume['free_pct']}% free", "Free space before large updates or game installs"))
    battery = STATE.get("system", {}).get("battery")
    if battery and battery.get("pct", 100) < prof("thresholds", "battery_pct") and not battery.get("plugged"):
        out.append(("warn", "posture-battery", f"Battery low: {battery['pct']}% and unplugged", "Connect power or reduce workload"))
    active = {item[1] for item in out}
    _posted.intersection_update(active)
    inv["posture"] = [{"sev": sev, "key": key, "title": title, "detail": detail} for sev, key, title, detail in out]
    for sev, key, title, detail in out:
        if key not in _posted:
            _posted.add(key)
            insight(sev, key, title, detail, "posture")
    source_health = inv.get("health", {})
    critical_sources = ("platform", "defender", "firewall", "secure_boot", "physical")
    unknown = [name for name in critical_sources if not source_health.get(name, {}).get("ok", False)]
    inv["posture_summary"] = {
        "count": len(out), "high": sum(1 for row in out if row[0] == "high"),
        "status": "findings" if out else ("incomplete" if unknown else "clear"),
        "unknown_sources": unknown,
    }


def scan():
    started = time.time()
    health = {}
    volumes = _volumes()
    interfaces = _ifaces()
    services = _services()
    processes = list(STATE.get("procs") or [])
    if IS_WIN:
        extra = _ps(WIN_SCRIPT, timeout=60) or {}
        for name in ("apps", "tasks", "drivers", "platform", "security", "defender", "firewall", "secure_boot", "bitlocker", "physical"):
            health[name] = (extra.get("health") or {}).get(name, {"ok": False, "error": "query did not return source health"})
        health["powershell"] = INV.get("health", {}).get("powershell", {"ok": False, "error": "not queried"})
        apps, tasks, drivers = _list(extra.get("apps")), _list(extra.get("tasks")), _list(extra.get("drivers"))
        plat, security, physical = extra.get("platform") or {}, extra.get("security") or {}, _list(extra.get("physical"))
    else:
        extra = DEMO_INVENTORY
        services = _list(extra.get("services"))
        apps, tasks, drivers = _list(extra.get("apps")), _list(extra.get("tasks")), _list(extra.get("drivers"))
        plat, security, physical = dict(extra.get("platform") or {}), dict(extra.get("security") or {}), _list(extra.get("physical"))
        health = {key: {"ok": True, "mode": "synthetic demo data"} for key in (
            "apps", "tasks", "drivers", "platform", "security", "defender",
            "firewall", "secure_boot", "bitlocker", "physical", "powershell", "services") }
    plat.setdefault("host", platform.node())
    plat.setdefault("os", platform.platform())
    plat.setdefault("architecture", platform.machine())
    plat["cpus"] = f"{psutil.cpu_count(logical=False)}C/{psutil.cpu_count()}T"
    plat["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    plat["ram_available_gb"] = round(psutil.virtual_memory().available / 2**30, 2)
    inv = {
        "ts": time.time(), "duration_s": round(time.time() - started, 3),
        "volumes": volumes, "interfaces": interfaces, "services": services,
        "startup": list(extra.get("startup", [])) if not IS_WIN else _startup(), "processes": processes,
        "apps": apps, "tasks": tasks, "drivers": drivers,
        "platform": plat, "security": security, "physical": physical,
        "health": {**health, "services": INV.get("health", {}).get("services", {}),
                   "volumes": INV.get("health", {}).get("volumes", {}),
                   "interfaces": INV.get("health", {}).get("interfaces", {})},
    }
    _posture(inv)
    INV.clear(); INV.update(inv)
    # Persist a compact, integrity-stamped snapshot to the same permanent SQLite
    # database as settings and intelligence. Keep volatile per-second process rows
    # out of this copy; the dedicated process snapshot has its own refresh cadence.
    try:
        from .core import persist_snapshot
        durable = {k: v for k, v in inv.items() if k != "processes"}
        persist_snapshot("inventory.latest", durable)
    except Exception as exc:
        log("storage", f"inventory snapshot persistence failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")
    return inv


def summary():
    data = INV
    count_keys = ("processes", "apps", "drivers", "services", "tasks", "interfaces", "volumes", "startup")
    counts = {key: len(data.get(key) or []) for key in count_keys}
    return {"ts": data.get("ts", 0), "duration_s": data.get("duration_s"), "counts": counts,
        **{key: data.get(key) for key in ("platform", "security", "volumes", "physical", "posture", "posture_summary", "health")}}


def catalog(kind, q="", limit=120):
    rows = INV.get(kind, []) or []
    q = str(q or "").casefold()
    hit = [row for row in rows if not q or q in json.dumps(row, ensure_ascii=False, default=str).casefold()]
    return {"kind": kind, "total": len(rows), "matched": len(hit), "rows": hit[:max(1, min(2000, int(limit)))]}


def loop():
    while True:
        t0 = time.time()
        if off("inventory"):
            heartbeat("system inventory", 600, "disabled in Feature Control"); time.sleep(30); continue
        try:
            scan()
            counts = INV.get("health", {})
            failed = [key for key, value in counts.items() if isinstance(value, dict) and value.get("ok") is False]
            heartbeat("system inventory", 600,
                f"{len(INV.get('apps', []))} apps, {len(INV.get('drivers', []))} drivers; {len(failed)} source issues",
                err=(counts[failed[0]].get("error", "source unavailable") if failed else ""))
        except Exception as exc:
            heartbeat("system inventory", 600, err=f"{type(exc).__name__}: {str(exc)[:200]}")
            log("inventory", f"inventory scan failed: {type(exc).__name__}: {str(exc)[:200]}", "error")
        delay = max(5, prof("intervals", "inventory_min") * 60 - (time.time() - t0))
        try:
            from . import runtime_engine
            delay = runtime_engine.inventory_delay(delay)
        except Exception:
            pass
        time.sleep(delay)