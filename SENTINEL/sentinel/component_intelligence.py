"""Longitudinal Windows component baselines and evidence-led review candidates.

This engine observes process/service metadata only. It does not close processes,
disable services, edit startup, install drivers, or change Windows configuration.
Executable paths are held only in memory for a bounded Authenticode query; SQLite
stores a one-way identity hash, file basename, publisher and signature metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any

from . import core, safeguard

_PROCESS_SAMPLE_SECONDS = 300
_SERVICE_SAMPLE_SECONDS = 900
_GRAPH_REFRESH_SECONDS = 6 * 3600
_SIGNATURE_REFRESH_SECONDS = 12 * 3600
_RETENTION_SECONDS = 30 * 86400
_BASELINE_MIN_DAYS = 7
_MAX_PROCESS_ROWS = 36
_MAX_SIGNATURE_PATHS = 28
_MAX_LAUNCH_ROWS = 800
_MAX_LAUNCH_BINARIES = 240

_STOP = threading.Event()
_LOCK = threading.RLock()
_STARTED = False
_THREAD: threading.Thread | None = None
_SERVICE_GRAPH_CACHE: dict[str, Any] = {}

_PROTECTED_SERVICES = frozenset({
    "vgc", "vgk", "windefend", "wscsvc", "mpssvc", "bfe", "sense",
    "wuauserv", "bits", "cryptsvc", "trustedinstaller", "rpcss",
    "dcomlaunch", "plugplay", "eventlog", "schedule", "samss", "lsass",
    "winmgmt", "nlasvc", "netprofm", "dhcp", "dnscache", "lanmanworkstation",
    "lanmanserver", "power", "audiosrv", "audioendpointbuilder", "hidserv",
    "textinputmanagementservice", "profsvc", "userManager".casefold(),
})
_PROTECTED_PROCESS_NAMES = frozenset({
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "svchost.exe", "winlogon.exe", "dwm.exe", "fontdrvhost.exe",
    "sihost.exe", "explorer.exe", "MsMpEng.exe".casefold(), "NisSrv.exe".casefold(),
})


def ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS component_catalog(
        component_id TEXT PRIMARY KEY,
        component_type TEXT NOT NULL,
        identity_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        binary_name TEXT NOT NULL DEFAULT '',
        publisher TEXT NOT NULL DEFAULT '',
        product_name TEXT NOT NULL DEFAULT '',
        file_version TEXT NOT NULL DEFAULT '',
        signature_status TEXT NOT NULL DEFAULT 'Unknown',
        signer TEXT NOT NULL DEFAULT '',
        protected INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT '',
        dependencies_json TEXT NOT NULL DEFAULT '[]',
        dependents_json TEXT NOT NULL DEFAULT '[]',
        start_mode TEXT NOT NULL DEFAULT '',
        service_state TEXT NOT NULL DEFAULT '',
        first_seen REAL NOT NULL,
        last_seen REAL NOT NULL,
        metadata_checked_at REAL NOT NULL DEFAULT 0)""")
    core.db("""CREATE TABLE IF NOT EXISTS component_samples(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component_id TEXT NOT NULL,
        ts REAL NOT NULL,
        state TEXT NOT NULL DEFAULT '',
        cpu_pct REAL,
        memory_mb REAL,
        io_mb_s REAL,
        foreground INTEGER,
        visible_windows INTEGER,
        onscreen_windows INTEGER,
        session_id INTEGER,
        running INTEGER,
        start_mode TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(component_id) REFERENCES component_catalog(component_id))""")
    core.db("""CREATE TABLE IF NOT EXISTS component_preferences(
        component_id TEXT PRIMARY KEY,
        preference TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS component_intelligence_state(
        state_key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS component_launch_metadata(
        component_id TEXT PRIMARY KEY,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        captured_at REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS component_relationships(
        source_component_id TEXT NOT NULL,
        target_component_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        confidence TEXT NOT NULL,
        evidence_json TEXT NOT NULL DEFAULT '{}',
        observed_at REAL NOT NULL,
        PRIMARY KEY(source_component_id,target_component_id,relation_type))""")
    core.db("CREATE INDEX IF NOT EXISTS ix_component_relationship_target ON component_relationships(target_component_id,relation_type)")
    core.db("CREATE INDEX IF NOT EXISTS ix_component_samples_component_ts ON component_samples(component_id,ts)")
    core.db("CREATE INDEX IF NOT EXISTS ix_component_samples_ts ON component_samples(ts)")
    core.db("CREATE INDEX IF NOT EXISTS ix_component_catalog_type ON component_catalog(component_type,last_seen)")


def _clean(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    text = re.sub(r"(?i)(password|token|secret|credential|api[_ -]?key)\s*[:=]\s*\S+", "[REDACTED]", text)
    text = re.sub(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[EMAIL]", text)
    text = re.sub(r"(?i)([A-Z]:\\Users\\)[^\\\s]+", r"\1[USER]", text)
    text = re.sub(r"(?i)\b[A-Z0-9._-]+\\[A-Z0-9._-]+\b", "[ACCOUNT]", text)
    return text[:limit]


def _normal_path(path: Any) -> str:
    value = str(path or "").strip().strip('"')
    if not value or not os.path.isabs(value):
        return ""
    try:
        return os.path.normcase(os.path.abspath(value))
    except (OSError, ValueError):
        return ""


def _identity_hash(kind: str, value: str) -> str:
    digest = hashlib.sha256((kind + "\0" + value.casefold()).encode("utf-8", "replace")).hexdigest()
    return digest[:40]


def process_component_id(exe: Any) -> str | None:
    path = _normal_path(exe)
    # The baseline engine only signs locally-addressed executable files. It
    # does not make network shares or removable locations a background task.
    if not path or not re.match(r"^[a-zA-Z]:[\\/]", path):
        return None
    return "process:" + _identity_hash("process", path)


def service_component_id(name: Any) -> str | None:
    value = str(name or "").strip().casefold()
    if not value or len(value) > 256:
        return None
    return "service:" + _identity_hash("service", value)


def _is_windows_binary(path: str) -> bool:
    value = path.replace("/", "\\").casefold()
    return any(part in value for part in (
        "\\windows\\system32\\", "\\windows\\syswow64\\", "\\windows\\winsxs\\",
        "\\windows\\servicing\\", "\\windows\\systemapps\\",
    ))


def _protected_service(row: dict[str, Any], binary_path: str = "") -> bool:
    name = str(row.get("name") or "").casefold()
    binary = str(row.get("binary_name") or os.path.basename(binary_path)).casefold()
    return (
        name in _PROTECTED_SERVICES
        or binary in _PROTECTED_PROCESS_NAMES
        or _is_windows_binary(binary_path)
        or safeguard.is_protected_process(binary, binary_path)
    )


def _chunks(rows: list[tuple], size: int = 45):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def _bulk_catalog(rows: list[tuple]) -> None:
    if not rows:
        return
    columns = 19
    for batch in _chunks(rows, max(1, 900 // columns)):
        marks = "(" + ",".join("?" for _ in range(columns)) + ")"
        sql = (
            "INSERT INTO component_catalog(component_id,component_type,identity_hash,name,binary_name,"
            "publisher,product_name,file_version,signature_status,signer,protected,source,"
            "dependencies_json,dependents_json,start_mode,service_state,first_seen,last_seen,metadata_checked_at) "
            "VALUES " + ",".join(marks for _ in batch) +
            " ON CONFLICT(component_id) DO UPDATE SET "
            "name=excluded.name,binary_name=COALESCE(NULLIF(excluded.binary_name,''),component_catalog.binary_name),"
            "publisher=COALESCE(NULLIF(excluded.publisher,''),component_catalog.publisher),"
            "product_name=COALESCE(NULLIF(excluded.product_name,''),component_catalog.product_name),"
            "file_version=COALESCE(NULLIF(excluded.file_version,''),component_catalog.file_version),"
            "signature_status=CASE WHEN excluded.signature_status='Unknown' THEN component_catalog.signature_status ELSE excluded.signature_status END,"
            "signer=COALESCE(NULLIF(excluded.signer,''),component_catalog.signer),"
            "protected=MAX(component_catalog.protected,excluded.protected),"
            "source=excluded.source,dependencies_json=excluded.dependencies_json,"
            "dependents_json=excluded.dependents_json,start_mode=excluded.start_mode,"
            "service_state=excluded.service_state,last_seen=excluded.last_seen,"
            "metadata_checked_at=MAX(component_catalog.metadata_checked_at,excluded.metadata_checked_at)"
        )
        core.db(sql, tuple(value for row in batch for value in row))


def _bulk_samples(rows: list[tuple]) -> None:
    if not rows:
        return
    columns = 12
    for batch in _chunks(rows, max(1, 900 // columns)):
        marks = "(" + ",".join("?" for _ in range(columns)) + ")"
        # Keep the row shape explicit while using one SQLite commit per batch.
        sql = (
            "INSERT INTO component_samples(component_id,ts,state,cpu_pct,memory_mb,io_mb_s,"
            "foreground,visible_windows,onscreen_windows,session_id,running,start_mode) VALUES "
            + ",".join(marks for _ in batch)
        )
        core.db(sql, tuple(value for row in batch for value in row))


def _last_sample(component_type: str) -> float:
    rows = core.db(
        "SELECT MAX(s.ts) FROM component_samples s JOIN component_catalog c "
        "ON c.component_id=s.component_id WHERE c.component_type=?",
        (component_type,),
    )
    return float(rows[0][0] or 0) if rows else 0.0


def _process_rows() -> list[dict[str, Any]]:
    rows = core.STATE.get("procs") if isinstance(core.STATE.get("procs"), list) else []
    eligible = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        exe = _normal_path(row.get("exe"))
        if not exe or row.get("path_state") != "present":
            continue
        if safeguard.is_protected_process(row.get("name"), exe):
            continue
        if str(row.get("name") or "").casefold() in _PROTECTED_PROCESS_NAMES:
            continue
        eligible.append(row)
    eligible.sort(
        key=lambda row: (
            float(row.get("cpu") or 0) * 2.0
            + float(row.get("mem") or 0) / 180.0
            + float(row.get("io") or 0) * 3.0
            + (8.0 if row.get("foreground") else 0.0)
            + min(8.0, float(row.get("visible_windows") or 0)),
        ),
        reverse=True,
    )
    chosen: dict[str, dict[str, Any]] = {}
    # Keep resource-heavy instances and independently retain visible/foreground
    # apps so the sample is not biased only toward CPU/RAM usage.
    for row in eligible[:_MAX_PROCESS_ROWS]:
        component_id = process_component_id(row.get("exe"))
        if component_id:
            chosen[component_id] = row
    for row in eligible:
        if len(chosen) >= _MAX_PROCESS_ROWS + 12:
            break
        if row.get("foreground") or int(row.get("visible_windows") or 0) > 0:
            component_id = process_component_id(row.get("exe"))
            if component_id:
                chosen[component_id] = row
    return list(chosen.values())


def sample_processes(now: float | None = None) -> int:
    ensure_schema()
    if not core.IS_WIN or core.off("processes"):
        return 0
    rows = _process_rows()
    if not rows:
        return 0
    timestamp = float(now or time.time())
    catalog_rows, sample_rows = [], []
    for row in rows:
        component_id = process_component_id(row.get("exe"))
        if not component_id:
            continue
        identity_hash = component_id.split(":", 1)[1]
        binary_name = os.path.basename(str(row.get("exe") or ""))
        protected = int(safeguard.is_protected_process(row.get("name"), row.get("exe")))
        name = _clean(row.get("name") or binary_name, 100) or "Unknown process"
        catalog_rows.append((
            component_id, "process", identity_hash, name, _clean(binary_name, 120),
            "", "", "", "Unknown", "", protected, "psutil process observer",
            "[]", "[]", "", "", timestamp, timestamp, 0.0,
        ))
        cpu = row.get("cpu")
        memory = row.get("mem")
        io_rate = row.get("io")
        sample_rows.append((
            component_id, timestamp, _clean(row.get("status") or "running", 40),
            float(cpu) if isinstance(cpu, (int, float)) else None,
            float(memory) if isinstance(memory, (int, float)) else None,
            float(io_rate) if isinstance(io_rate, (int, float)) else None,
            int(bool(row.get("foreground"))), int(row.get("visible_windows") or 0),
            int(row.get("onscreen_windows") or 0),
            int(row["session_id"]) if isinstance(row.get("session_id"), int) else None,
            1, "", 
        ))
    _bulk_catalog(catalog_rows)
    _bulk_samples(sample_rows)
    return len(sample_rows)


def _service_graph_query() -> dict[str, Any]:
    """Read SCM dependency relationships and executable basenames through PowerShell."""
    from .winutil import powershell

    script = r"""
$ErrorActionPreference='Stop'
$controllers=@{}
Get-Service -ErrorAction Stop | ForEach-Object { $controllers[$_.Name]=$_ }
$items=@(Get-CimInstance Win32_Service -ErrorAction Stop | ForEach-Object {
  $ctl=$controllers[[string]$_.Name]
  $dependencies=@(); $dependents=@()
  if($ctl){
    $dependencies=@($ctl.ServicesDependedOn | ForEach-Object { $_.Name })
    $dependents=@($ctl.DependentServices | ForEach-Object { $_.Name })
  }
  $raw=[string]$_.PathName
  $binary=''
  if($raw -match '^\s*"([^"]+\.exe)"') { $binary=$matches[1] }
  elseif($raw -match '^\s*(.+?\.exe)(?:\s|$)') { $binary=$matches[1] }
  $binaryName=if($binary){[IO.Path]::GetFileName($binary)}else{''}
  [pscustomobject]@{
    name=[string]$_.Name; display=[string]$_.DisplayName
    state=[string]$_.State; start=[string]$_.StartMode
    pid=[int]$_.ProcessId; binary_name=$binaryName; binary_path=$binary
    dependencies=@($dependencies | Sort-Object -Unique)
    dependents=@($dependents | Sort-Object -Unique)
    description=[string]$_.Description
  }
})
@{services=$items;count=$items.Count} | ConvertTo-Json -Depth 6 -Compress
"""
    result = powershell(script, timeout=45)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "SCM dependency query failed")[:240])
    payload = json.loads((result.stdout or "").strip().lstrip("\ufeff"))
    services = payload.get("services", []) if isinstance(payload, dict) else []
    if isinstance(services, dict):
        services = [services]
    count = payload.get("count") if isinstance(payload, dict) else None
    if not isinstance(services, list) or not isinstance(count, int) or count != len(services):
        raise RuntimeError("SCM dependency query did not return a complete service list")
    return {"services": services, "count": count, "captured_at": time.time()}



def binary_component_id(executable: Any) -> str | None:
    """Stable local executable identity; the path itself is never a database key."""
    path = _normal_path(executable)
    if not path or not re.match(r"^[a-zA-Z]:[\\/]", path):
        return None
    return "binary:" + _identity_hash("binary", path)


def startup_component_id(source: Any, name: Any) -> str | None:
    source_text = str(source or "").strip().casefold()
    name_text = str(name or "").strip().casefold()
    if not source_text or not name_text or len(name_text) > 240:
        return None
    return "startup:" + _identity_hash("startup", source_text + "\0" + name_text)


def task_component_id(task_path: Any, name: Any) -> str | None:
    path_text = str(task_path or "\\").strip().casefold()
    name_text = str(name or "").strip().casefold()
    if not name_text or len(name_text) > 240 or len(path_text) > 500:
        return None
    return "task:" + _identity_hash("task", path_text + "\0" + name_text)


def app_component_id(name: Any, publisher: Any, version: Any = "") -> str | None:
    name_text = str(name or "").strip()
    publisher_text = str(publisher or "").strip()
    if not name_text or len(name_text) > 180:
        return None
    identity = "\0".join((name_text.casefold(), publisher_text.casefold(),
                          str(version or "").strip().casefold()))
    return "app:" + _identity_hash("app", identity)


def _extract_launch_target(command: Any) -> dict[str, Any]:
    """Resolve only the executable token; never retain or return the argument tail."""
    raw = str(command or "").strip()
    if not raw or len(raw) > 4096:
        return {"binary_path": "", "binary_name": "", "launch_kind": "unresolved",
                "has_arguments": False}
    expanded = os.path.expandvars(raw)
    expanded = re.sub(
        r"%([^%]+)%",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        expanded,
    )
    match = re.match(r'^\s*"([^"]+?\.exe)"(?=\s|$)', expanded, re.IGNORECASE)
    if not match:
        match = re.match(r"^\s*(.+?\.exe)(?=\s|$)", expanded, re.IGNORECASE)
    if not match:
        return {"binary_path": "", "binary_name": "", "launch_kind": "unresolved",
                "has_arguments": False}
    candidate = match.group(1).strip()
    path = _normal_path(candidate)
    if not path or not re.match(r"^[a-zA-Z]:[\\/]", path):
        return {"binary_path": "", "binary_name": "", "launch_kind": "unresolved",
                "has_arguments": False}
    binary_name = path.replace("/", "\\").rsplit("\\", 1)[-1]
    wrappers = {
        "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
        "rundll32.exe", "regsvr32.exe", "mshta.exe", "dllhost.exe",
        "svchost.exe", "taskhostw.exe", "java.exe", "javaw.exe", "python.exe",
        "pythonw.exe", "conhost.exe",
    }
    launch_kind = "command_host" if binary_name.casefold() in wrappers else "direct_executable"
    argument_tail = expanded[match.end():].strip()
    return {
        "binary_path": path,
        "binary_name": _clean(binary_name, 120),
        "launch_kind": launch_kind,
        "has_arguments": bool(argument_tail),
    }


def _launch_inventory_query() -> dict[str, Any]:
    """Return startup/task launch provenance with arguments and account names excluded."""
    from .winutil import powershell

    script = r"""
$ErrorActionPreference='Stop'
function Resolve-LaunchExe([string]$raw) {
  $value=[Environment]::ExpandEnvironmentVariables([string]$raw)
  $exe=''
  if($value -match '^\s*"(?<p>[^"]+?\.exe)"(?=\s|$)') { $exe=[string]$matches['p'] }
  elseif($value -match '^\s*(?<p>.+?\.exe)(?=\s|$)') { $exe=[string]$matches['p'] }
  if($exe -match '^[A-Za-z]:\\') { return $exe }
  return ''
}
$startup=@(); $tasks=@()
$startupOk=$true; $startupError=''
$tasksOk=$true; $tasksError=''; $taskTotal=0
try {
  foreach($item in @(Get-CimInstance Win32_StartupCommand -ErrorAction Stop)) {
    $location=[string]$item.Location
    $source='Windows startup'
    if($location -match '(?i)HKLM|HKEY_LOCAL_MACHINE') { $source='Registry · All users' }
    elseif($location -match '(?i)HKCU|HKEY_CURRENT_USER') { $source='Registry · Current user' }
    elseif($location -match '(?i)Startup') { $source='Startup folder' }
    $command=[string]$item.Command
    $exe=Resolve-LaunchExe $command
    $hasArgs=$false
    if($exe -and $command.Length -gt $exe.Length) { $hasArgs=$true }
    $startup+=@{
      name=[string]$item.Name; source=$source; binary_path=$exe
      has_arguments=[bool]$hasArgs; enabled=$true
    }
  }
} catch { $startupOk=$false; $startupError=$_.Exception.Message }
try {
  $allTasks=@(Get-ScheduledTask -ErrorAction Stop)
  $taskTotal=$allTasks.Count
  $limit=[Math]::Min($taskTotal,800)
  for($i=0;$i -lt $limit;$i++) {
    $task=$allTasks[$i]
    $actions=@()
    foreach($action in @($task.Actions)) {
      $rawExe=[string]$action.Execute
      $exe=Resolve-LaunchExe $rawExe
      $kind='Unknown'
      if($rawExe) { $kind='Exec' }
      elseif($action.ClassId) { $kind='ComHandler' }
      $actions+=@{
        binary_path=$exe; action_kind=$kind
        has_arguments=[bool]([string]$action.Arguments)
      }
    }
    $taskPath=[string]$task.TaskPath
    $tasks+=@{
      name=[string]$task.TaskName; task_path=$taskPath
      state=[string]$task.State; enabled=[bool]$task.Settings.Enabled
      run_level=[string]$task.Principal.RunLevel
      logon_type=[string]$task.Principal.LogonType
      actions=@($actions)
    }
  }
} catch { $tasksOk=$false; $tasksError=$_.Exception.Message }
@{
  startup=$startup; tasks=$tasks; task_total=$taskTotal
  startup_complete=$startupOk; tasks_complete=($tasksOk -and $taskTotal -le 800)
  task_truncated=($tasksOk -and $taskTotal -gt 800)
  source_health=@{
    startup=@{ok=$startupOk;error=$startupError}
    tasks=@{ok=$tasksOk;error=$tasksError;count=$taskTotal}
  }
} | ConvertTo-Json -Depth 7 -Compress
"""
    result = powershell(script, timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Startup/task inventory failed")[:220])
    payload = json.loads((result.stdout or "").strip().lstrip("\ufeff"))
    if not isinstance(payload, dict):
        raise RuntimeError("Startup/task inventory returned an invalid object")
    startup = payload.get("startup", [])
    tasks = payload.get("tasks", [])
    if isinstance(startup, dict):
        startup = [startup]
    if isinstance(tasks, dict):
        tasks = [tasks]
    if not isinstance(startup, list) or not isinstance(tasks, list):
        raise RuntimeError("Startup/task inventory lists were incomplete")
    return {
        "startup": [row for row in startup if isinstance(row, dict)][:800],
        "tasks": [row for row in tasks if isinstance(row, dict)][:800],
        "task_total": int(payload.get("task_total") or 0),
        "startup_complete": payload.get("startup_complete") is True,
        "tasks_complete": payload.get("tasks_complete") is True,
        "task_truncated": payload.get("task_truncated") is True,
        "source_health": payload.get("source_health") if isinstance(payload.get("source_health"), dict) else {},
        "captured_at": time.time(),
    }


def _catalog_tuple(component_id: str, component_type: str, name: str, *,
                   binary_name: str = "", publisher: str = "", product_name: str = "",
                   version: str = "", protected: bool = False, source: str = "",
                   start_mode: str = "", state: str = "", now: float) -> tuple:
    identity_hash = component_id.split(":", 1)[1]
    return (
        component_id, component_type, identity_hash, _clean(name, 140),
        _clean(binary_name, 120), _clean(publisher, 140), _clean(product_name, 140),
        _clean(version, 80), "Unknown", "", int(bool(protected)), _clean(source, 120),
        "[]", "[]", _clean(start_mode, 40), _clean(state, 40),
        now, now, 0.0,
    )


def _path_under(path: str, root: str) -> bool:
    try:
        return bool(path and root and os.path.commonpath((path, root)) == root and path != root)
    except (OSError, ValueError):
        return False


def _build_launch_graph(snapshot: dict[str, Any], service_rows: list[dict[str, Any]],
                        apps: list[dict[str, Any]], now: float | None = None) -> dict[str, Any]:
    """Build safe catalog rows and exact-path edges; raw paths stay in this return's memory map."""
    timestamp = float(now or time.time())
    catalog_rows: dict[str, tuple] = {}
    metadata_rows: dict[str, tuple] = {}
    relationships: dict[tuple[str, str, str], tuple] = {}
    binary_paths: dict[str, str] = {}
    startup_ids: list[str] = []
    task_ids: list[str] = []

    def add_binary(path: str) -> str | None:
        executable = _normal_path(path)
        component_id = binary_component_id(executable)
        if not component_id:
            return None
        if component_id not in binary_paths and len(binary_paths) >= _MAX_LAUNCH_BINARIES:
            return None
        binary_paths[component_id] = executable
        binary_name = executable.replace("/", "\\").rsplit("\\", 1)[-1]
        protected = _is_windows_binary(executable) or safeguard.is_protected_process(binary_name, executable)
        catalog_rows[component_id] = _catalog_tuple(
            component_id, "binary", binary_name, binary_name=binary_name,
            protected=protected, source="Startup/task/service executable provenance",
            now=timestamp,
        )
        return component_id

    def add_relationship(source_id: str, target_id: str, relation: str,
                         confidence: str, evidence: dict[str, Any]) -> None:
        key = (source_id, target_id, relation)
        relationships[key] = (
            source_id, target_id, relation, confidence,
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            timestamp,
        )

    for raw in (snapshot.get("startup") or [])[:800]:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"), 120)
        source = _clean(raw.get("source") or "Windows startup", 70)
        component_id = startup_component_id(source, name)
        if not component_id:
            continue
        target = _extract_launch_target(raw.get("binary_path") or raw.get("command"))
        binary_id = add_binary(target["binary_path"]) if target.get("binary_path") else None
        binary_name = target.get("binary_name") or ""
        protected = bool(
            binary_id and _is_windows_binary(target["binary_path"])
            or binary_name and safeguard.is_protected_process(binary_name, target.get("binary_path", ""))
            or any(token in (name + " " + source).casefold() for token in ("sentinel", "riot vanguard", "windows security"))
        )
        catalog_rows[component_id] = _catalog_tuple(
            component_id, "startup", name, binary_name=binary_name,
            protected=protected, source=source,
            start_mode=target.get("launch_kind") or "unresolved",
            state="present", now=timestamp,
        )
        metadata = {
            "source": source, "launch_kind": target.get("launch_kind", "unresolved"),
            "has_arguments": bool(raw.get("has_arguments") or target.get("has_arguments")),
            "target_resolved": bool(binary_id), "enabled": bool(raw.get("enabled", True)),
        }
        metadata_rows[component_id] = (
            component_id, json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), timestamp,
        )
        startup_ids.append(component_id)
        if binary_id:
            add_relationship(
                component_id, binary_id, "launches_binary", "path_resolved",
                {"launch_kind": target.get("launch_kind"), "has_arguments": metadata["has_arguments"]},
            )

    for raw in (snapshot.get("tasks") or [])[:800]:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"), 120)
        task_path = _clean(raw.get("task_path") or "\\", 140)
        component_id = task_component_id(task_path, name)
        if not component_id:
            continue
        protected_task = task_path.casefold().startswith("\\microsoft\\") or "sentinel" in name.casefold()
        actions = raw.get("actions") if isinstance(raw.get("actions"), list) else []
        action_targets = []
        for index, action in enumerate(actions[:16]):
            if not isinstance(action, dict):
                continue
            target = _extract_launch_target(action.get("binary_path") or action.get("execute"))
            if target.get("binary_path"):
                binary_id = add_binary(target["binary_path"])
                if binary_id:
                    action_targets.append({
                        "binary_id": binary_id, "binary_name": target.get("binary_name") or "",
                        "action_index": index, "action_kind": _clean(action.get("action_kind") or "Exec", 32),
                        "has_arguments": bool(action.get("has_arguments") or target.get("has_arguments")),
                    })
        first_binary = action_targets[0]["binary_name"] if action_targets else ""
        protected = protected_task or any(
            safeguard.is_protected_process(item["binary_name"], binary_paths[item["binary_id"]])
            or _is_windows_binary(binary_paths[item["binary_id"]])
            for item in action_targets
        )
        state = _clean(raw.get("state") or "unknown", 30)
        enabled = bool(raw.get("enabled"))
        catalog_rows[component_id] = _catalog_tuple(
            component_id, "task", name, binary_name=first_binary, protected=protected,
            source="Task Scheduler · " + task_path,
            start_mode=_clean(raw.get("run_level") or "unknown", 30),
            state=state if enabled else "disabled", now=timestamp,
        )
        metadata = {
            "task_path": task_path, "enabled": enabled, "run_level": _clean(raw.get("run_level"), 24),
            "logon_type": _clean(raw.get("logon_type"), 32),
            "action_count": len(actions), "resolved_executable_actions": len(action_targets),
            "unresolved_action_count": max(0, len(actions) - len(action_targets)),
            "launch_kind": "multi_action" if len(action_targets) > 1 else (
                action_targets[0]["action_kind"] if action_targets else "opaque_or_unresolved"
            ),
        }
        metadata_rows[component_id] = (
            component_id, json.dumps(metadata, ensure_ascii=False, separators=(",", ":")), timestamp,
        )
        task_ids.append(component_id)
        for item in action_targets:
            add_relationship(
                component_id, item["binary_id"], "launches_binary", "path_resolved",
                {"action_index": item["action_index"], "action_kind": item["action_kind"],
                 "has_arguments": item["has_arguments"]},
            )

    # An executable is associated with an installed application only when its
    # resolved path is under one unique registered install location.
    app_roots = []
    for app in ((apps or [])[:600] if snapshot.get("apps_complete") is True else []):
        if not isinstance(app, dict):
            continue
        root = _normal_path(app.get("location") or app.get("install_location"))
        app_id = app_component_id(app.get("name"), app.get("publisher"), app.get("version"))
        if not root or not app_id:
            continue
        app_roots.append((root, app_id, app))
    matched_app_ids: set[str] = set()
    for binary_id, executable in list(binary_paths.items())[:_MAX_LAUNCH_BINARIES]:
        matches = [(len(root), app_id, app) for root, app_id, app in app_roots if _path_under(executable, root)]
        if matches:
            longest = max(row[0] for row in matches)
            best = [row for row in matches if row[0] == longest]
            if len(best) == 1:
                _length, app_id, app = best[0]
                matched_app_ids.add(app_id)
                catalog_rows[app_id] = _catalog_tuple(
                    app_id, "app", _clean(app.get("name"), 140), publisher=app.get("publisher") or "",
                    product_name=app.get("name") or "", version=app.get("version") or "",
                    source="Installed application inventory", now=timestamp,
                )
                add_relationship(
                    binary_id, app_id, "installed_under_app", "unique_install_location_prefix",
                    {"path_stored": False, "match": "executable under one unique install location"},
                )

    service_paths = {}
    for service in ((service_rows or [])[:800] if snapshot.get("service_graph_complete") is True else []):
        if not isinstance(service, dict):
            continue
        path = _normal_path(service.get("binary_path"))
        service_id = service_component_id(service.get("name"))
        if path and service_id:
            service_paths[path] = service_id
    for binary_id, executable in list(binary_paths.items())[:_MAX_LAUNCH_BINARIES]:
        service_id = service_paths.get(executable)
        if service_id:
            add_relationship(
                binary_id, service_id, "same_executable_as_service", "exact_executable_path",
                {"match": "exact normalized executable path", "path_stored": False},
            )

    return {
        "catalog_rows": list(catalog_rows.values()),
        "metadata_rows": list(metadata_rows.values()),
        "relationships": list(relationships.values()),
        "binary_paths": dict(list(binary_paths.items())[:_MAX_LAUNCH_BINARIES]),
        "startup_ids": startup_ids, "task_ids": task_ids,
        "startup_complete": snapshot.get("startup_complete") is True,
        "tasks_complete": snapshot.get("tasks_complete") is True,
        "apps_complete": snapshot.get("apps_complete") is True,
        "service_graph_complete": snapshot.get("service_graph_complete") is True,
        "source_health": snapshot.get("source_health") if isinstance(snapshot.get("source_health"), dict) else {},
        "captured_at": timestamp,
    }


def _persist_launch_graph(graph: dict[str, Any]) -> None:
    catalog_rows = graph.get("catalog_rows") if isinstance(graph.get("catalog_rows"), list) else []
    _bulk_catalog(catalog_rows)
    metadata_rows = graph.get("metadata_rows") if isinstance(graph.get("metadata_rows"), list) else []
    for component_id, metadata_json, captured_at in metadata_rows:
        core.db(
            "INSERT INTO component_launch_metadata(component_id,metadata_json,captured_at) VALUES(?,?,?) "
            "ON CONFLICT(component_id) DO UPDATE SET metadata_json=excluded.metadata_json,captured_at=excluded.captured_at",
            (component_id, metadata_json, captured_at),
        )
    for component_type, complete, ids in (
        ("startup", graph.get("startup_complete") is True, graph.get("startup_ids") or []),
        ("task", graph.get("tasks_complete") is True, graph.get("task_ids") or []),
    ):
        if not complete:
            continue
        all_rows = core.db("SELECT component_id FROM component_catalog WHERE component_type=?", (component_type,))
        seen = set(str(value) for value in ids)
        stale = [str(row[0]) for row in all_rows if str(row[0]) not in seen]
        if stale:
            for start in range(0, len(stale), 300):
                batch = stale[start:start + 300]
                marks = ",".join("?" for _ in batch)
                core.db(
                    f"UPDATE component_catalog SET service_state='not_present' WHERE component_id IN ({marks})",
                    tuple(batch),
                )
                core.db(f"DELETE FROM component_relationships WHERE source_component_id IN ({marks})",
                        tuple(batch))
        core.db(
            "DELETE FROM component_relationships WHERE relation_type='launches_binary' "
            "AND source_component_id IN (SELECT component_id FROM component_catalog WHERE component_type=?)",
            (component_type,),
        )
    if graph.get("apps_complete") is True:
        core.db("DELETE FROM component_relationships WHERE relation_type='installed_under_app'")
    if graph.get("service_graph_complete") is True:
        core.db("DELETE FROM component_relationships WHERE relation_type='same_executable_as_service'")
    relationships = graph.get("relationships") if isinstance(graph.get("relationships"), list) else []
    for batch in _chunks(relationships, 100):
        marks = "(?,?,?,?,?,?)"
        sql = (
            "INSERT INTO component_relationships(source_component_id,target_component_id,relation_type,confidence,evidence_json,observed_at) VALUES "
            + ",".join(marks for _ in batch)
            + " ON CONFLICT(source_component_id,target_component_id,relation_type) DO UPDATE SET "
            "confidence=excluded.confidence,evidence_json=excluded.evidence_json,observed_at=excluded.observed_at"
        )
        core.db(sql, tuple(value for row in batch for value in row))
    _save_state("launch_inventory", {
        "captured_at": float(graph.get("captured_at") or time.time()),
        "startup_count": len(graph.get("startup_ids") or []),
        "task_count": len(graph.get("task_ids") or []),
        "binary_count": len(graph.get("binary_paths") or {}),
        "startup_complete": bool(graph.get("startup_complete")),
        "tasks_complete": bool(graph.get("tasks_complete")),
        "apps_complete": bool(graph.get("apps_complete")),
        "service_graph_complete": bool(graph.get("service_graph_complete")),
        "source_health": graph.get("source_health") or {},
    })


def _launch_component_rows(component_type: str, since: float, limit: int = 40) -> list[dict[str, Any]]:
    if component_type not in ("startup", "task"):
        return []
    rows = core.db(
        "SELECT component_id,name,binary_name,protected,source,start_mode,service_state,last_seen "
        "FROM component_catalog WHERE component_type=? AND last_seen>=? AND service_state<>'not_present' "
        "ORDER BY name COLLATE NOCASE LIMIT ?",
        (component_type, since, max(1, min(100, int(limit)))),
    )
    output = []
    for row in rows:
        component_id = str(row[0])
        meta_rows = core.db("SELECT metadata_json FROM component_launch_metadata WHERE component_id=?", (component_id,))
        try:
            metadata = json.loads(meta_rows[0][0] or "{}") if meta_rows else {}
        except (TypeError, ValueError):
            metadata = {}
        links = core.db(
            "SELECT r.target_component_id,r.relation_type,r.confidence,r.evidence_json,"
            "t.component_type,t.name,t.binary_name,t.publisher,t.product_name,t.file_version,"
            "t.signature_status,t.signer,t.start_mode,t.service_state,t.protected "
            "FROM component_relationships r LEFT JOIN component_catalog t ON t.component_id=r.target_component_id "
            "WHERE r.source_component_id=? ORDER BY r.relation_type,t.name COLLATE NOCASE",
            (component_id,),
        )
        binaries, apps, services = [], [], []
        for link in links:
            target = {
                "id": str(link[0]), "type": str(link[4] or ""), "name": _clean(link[5], 100),
                "binary_name": _clean(link[6], 100), "publisher": _clean(link[7], 120),
                "product_name": _clean(link[8], 100), "version": _clean(link[9], 70),
                "signature_status": _clean(link[10], 32), "signer": _clean(link[11], 140),
                "start_mode": _clean(link[12], 24), "state": _clean(link[13], 24),
                "protected": bool(link[14]), "relation": str(link[1]), "confidence": str(link[2]),
            }
            if link[1] == "launches_binary":
                binary_edges = core.db(
                    "SELECT r.target_component_id,r.relation_type,r.confidence,"
                    "t.component_type,t.name,t.publisher,t.signature_status,t.start_mode,t.service_state "
                    "FROM component_relationships r LEFT JOIN component_catalog t ON t.component_id=r.target_component_id "
                    "WHERE r.source_component_id=?",
                    (target["id"],),
                )
                target["application_matches"] = [
                    {"id": str(edge[0]), "name": _clean(edge[4], 100), "publisher": _clean(edge[5], 120),
                     "confidence": str(edge[2])}
                    for edge in binary_edges if edge[1] == "installed_under_app" and edge[3] == "app"
                ]
                target["service_matches"] = [
                    {"id": str(edge[0]), "name": _clean(edge[4], 100), "publisher": _clean(edge[5], 120),
                     "signature_status": _clean(edge[6], 32), "start_mode": _clean(edge[7], 24),
                     "state": _clean(edge[8], 24), "confidence": str(edge[2])}
                    for edge in binary_edges if edge[1] == "same_executable_as_service" and edge[3] == "service"
                ]
                binaries.append(target)
            elif link[1] == "installed_under_app":
                apps.append(target)
            elif link[1] == "same_executable_as_service":
                services.append(target)
        pref_rows = core.db(
            "SELECT preference,note,updated_at FROM component_preferences WHERE component_id=?",
            (component_id,),
        )
        preference = str(pref_rows[0][0]) if pref_rows else "unreviewed"
        note = _clean(pref_rows[0][1], 160) if pref_rows else ""
        output.append({
            "id": component_id, "component_id": component_id, "component_type": component_type,
            "name": _clean(row[1], 120), "binary_name": _clean(row[2], 100),
            "protected": bool(row[3]), "source": _clean(row[4], 120),
            "launch_kind": _clean(row[5], 40), "state": _clean(row[6], 40),
            "last_seen": float(row[7] or 0), "metadata": metadata,
            "binary_targets": binaries, "application_matches": apps, "service_matches": services,
            "preference": preference, "operator_note": note, "requires_user_intent": True,
            "provenance_status": "verified_target" if any(
                binary.get("signature_status") == "Valid" for binary in binaries
            ) else ("target_resolved" if binaries else "unresolved_target"),
            "recommendation": "Provenance and exact-path associations only. Presence in Startup or Task Scheduler does not prove this entry is unnecessary.",
        })
    return output

def _save_state(key: str, value: dict[str, Any]) -> None:
    core.db(
        "INSERT INTO component_intelligence_state(state_key,value_json,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(state_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str), time.time()),
    )


def _load_state(key: str) -> dict[str, Any]:
    rows = core.db("SELECT value_json FROM component_intelligence_state WHERE state_key=?", (key,))
    if not rows:
        return {}
    try:
        value = json.loads(rows[0][0] or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def refresh_service_graph(force: bool = False) -> dict[str, Any]:
    global _SERVICE_GRAPH_CACHE
    ensure_schema()
    if not core.IS_WIN:
        return {"ok": False, "reason": "Windows SCM is unavailable on this platform."}
    previous = _load_state("service_graph")
    last = float(previous.get("captured_at") or 0)
    cache_ready = bool(_SERVICE_GRAPH_CACHE.get("services"))
    if not force and cache_ready and time.time() - last < _GRAPH_REFRESH_SECONDS:
        return {"ok": True, "cached": True, "count": int(previous.get("count") or 0), "captured_at": last}
    try:
        from . import runtime_engine
        permitted, reason = runtime_engine.admit_optional_work(
            "service dependency inventory", min_available_gib=5.0, max_cpu_percent=40.0,
        )
        if not permitted:
            return {"ok": False, "deferred": True, "reason": reason}
        graph = _service_graph_query()
        _SERVICE_GRAPH_CACHE = graph
        # Raw executable paths are temporary inputs to Authenticode. Do not persist them.
        safe_graph = {
            "services": [{key: value for key, value in row.items() if key not in ("binary_path", "description")}
                         for row in graph["services"] if isinstance(row, dict)],
            "count": graph["count"], "captured_at": graph["captured_at"],
        }
        _save_state("service_graph", safe_graph)
        return {"ok": True, "cached": False, "count": graph["count"], "captured_at": graph["captured_at"]}
    except Exception as exc:
        core.log("component-intelligence", f"service dependency inventory unavailable: {type(exc).__name__}: {_clean(exc, 180)}", "warn")
        return {"ok": False, "reason": f"{type(exc).__name__}: {_clean(exc, 180)}"}


def sample_services(now: float | None = None) -> int:
    ensure_schema()
    if not core.IS_WIN or core.off("services"):
        return 0
    services = core.STATE.get("services_catalog")
    if not isinstance(services, list) or not services:
        return 0
    graph = _load_state("service_graph")
    graph_rows = graph.get("services") if isinstance(graph.get("services"), list) else []
    graph_by_name = {
        str(row.get("name") or "").casefold(): row
        for row in graph_rows if isinstance(row, dict) and row.get("name")
    }
    timestamp = float(now or time.time())
    catalog_rows, sample_rows = [], []
    for row in services[:800]:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        component_id = service_component_id(row.get("name"))
        if not component_id:
            continue
        graph_row = graph_by_name.get(str(row.get("name")).casefold(), {})
        binary_path = str(graph_row.get("binary_path") or row.get("binpath") or "")
        binary_name = str(graph_row.get("binary_name") or os.path.basename(binary_path))
        protected = int(_protected_service(row, binary_path))
        dependencies = graph_row.get("dependencies") if isinstance(graph_row.get("dependencies"), list) else []
        dependents = graph_row.get("dependents") if isinstance(graph_row.get("dependents"), list) else []
        name = _clean(row.get("name"), 120)
        state = _clean(row.get("state") or "unknown", 30).casefold()
        start_mode = _clean(row.get("start") or "unknown", 30).casefold()
        description = _clean(row.get("description"), 140)
        identity_hash = component_id.split(":", 1)[1]
        catalog_rows.append((
            component_id, "service", identity_hash, name, _clean(binary_name, 120),
            "", "", "", "Unknown", "", protected, "Windows Service Control Manager",
            json.dumps(sorted({_clean(x, 100) for x in dependencies if x}), ensure_ascii=False),
            json.dumps(sorted({_clean(x, 100) for x in dependents if x}), ensure_ascii=False),
            start_mode, state, timestamp, timestamp, 0.0,
        ))
        sample_rows.append((
            component_id, timestamp, state, None, None, None,
            None, None, None, None, int(state == "running"), start_mode,
        ))
    _bulk_catalog(catalog_rows)
    _bulk_samples(sample_rows)
    return len(sample_rows)


def _authenticode_query(paths: list[str]) -> list[dict[str, Any]]:
    """Get signature and version metadata without returning executable paths."""
    if not paths:
        return []
    from .winutil import powershell

    encoded = json.dumps(paths, ensure_ascii=False).replace("'", "''")
    script = r"""
$ErrorActionPreference='Continue'
$paths=ConvertFrom-Json -InputObject '__PATHS_JSON__'
$items=@()
for($i=0;$i -lt $paths.Count;$i++){
  $p=[string]$paths[$i]
  $status='Unavailable'; $signer=''; $company=''; $product=''; $version=''; $name=''
  try {
    $f=Get-Item -LiteralPath $p -ErrorAction Stop
    $name=[string]$f.Name
    $company=[string]$f.VersionInfo.CompanyName
    $product=[string]$f.VersionInfo.ProductName
    $version=[string]$f.VersionInfo.FileVersion
    $sig=Get-AuthenticodeSignature -FilePath $p -ErrorAction Stop
    $status=[string]$sig.Status
    if($sig.SignerCertificate){$signer=[string]$sig.SignerCertificate.Subject}
  } catch { $status='Unavailable' }
  $items+=@{index=$i;binary_name=$name;publisher=$company;product_name=$product;
    file_version=$version;signature_status=$status;signer=$signer}
}
@{items=$items;count=$items.Count} | ConvertTo-Json -Depth 5 -Compress
""".replace("__PATHS_JSON__", encoded)
    result = powershell(script, timeout=60)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Authenticode query failed")[:220])
    payload = json.loads((result.stdout or "").strip().lstrip("\ufeff"))
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise RuntimeError("Authenticode response was not a list")
    return [row for row in items if isinstance(row, dict)]


def refresh_signatures(force: bool = False) -> dict[str, Any]:
    """Refresh a small signature queue only when the runtime governor admits it."""
    ensure_schema()
    if not core.IS_WIN:
        return {"ok": False, "reason": "Authenticode is Windows-only."}
    last = _load_state("signature_refresh")
    captured_at = float(last.get("captured_at") or 0)
    if not force and time.time() - captured_at < _SIGNATURE_REFRESH_SECONDS:
        return {"ok": True, "cached": True, "count": int(last.get("count") or 0)}
    try:
        from . import runtime_engine
        permitted, reason = runtime_engine.admit_optional_work(
            "component publisher and signature verification", min_available_gib=5.0, max_cpu_percent=35.0,
        )
        if not permitted:
            return {"ok": False, "deferred": True, "reason": reason}
        now = time.time()
        paths_by_id: dict[str, str] = {}
        for row in _process_rows():
            path = _normal_path(row.get("exe"))
            component_id = process_component_id(path)
            if not component_id or safeguard.is_protected_process(row.get("name"), path):
                continue
            existing = core.db(
                "SELECT metadata_checked_at FROM component_catalog WHERE component_id=?",
                (component_id,),
            )
            if not existing or now - float(existing[0][0] or 0) >= _SIGNATURE_REFRESH_SECONDS:
                paths_by_id[component_id] = path
        graph = _load_state("service_graph")
        for row in (graph.get("services") or [])[:800]:
            if not isinstance(row, dict):
                continue
            path = _normal_path(row.get("binary_path"))
            component_id = service_component_id(row.get("name"))
            if not path or not component_id or _protected_service(row, path):
                continue
            if not _is_windows_binary(path):
                existing = core.db(
                    "SELECT metadata_checked_at FROM component_catalog WHERE component_id=?",
                    (component_id,),
                )
                if not existing or now - float(existing[0][0] or 0) >= _SIGNATURE_REFRESH_SECONDS:
                    paths_by_id[component_id] = path
        chosen = list(paths_by_id.items())[:_MAX_SIGNATURE_PATHS]
        if not chosen:
            _save_state("signature_refresh", {"captured_at": now, "count": 0})
            return {"ok": True, "count": 0, "reason": "No new local component files require verification."}
        metadata = _authenticode_query([path for _component_id, path in chosen])
        updated = 0
        for index, item in enumerate(metadata):
            if index >= len(chosen):
                break
            component_id, _path = chosen[index]
            core.db(
                "UPDATE component_catalog SET binary_name=?,publisher=?,product_name=?,file_version=?,"
                "signature_status=?,signer=?,metadata_checked_at=? WHERE component_id=?",
                (
                    _clean(item.get("binary_name"), 120), _clean(item.get("publisher"), 140),
                    _clean(item.get("product_name"), 140), _clean(item.get("file_version"), 80),
                    _clean(item.get("signature_status") or "Unavailable", 40),
                    _clean(item.get("signer"), 180), now, component_id,
                ),
            )
            updated += 1
        _save_state("signature_refresh", {"captured_at": now, "count": updated})
        return {"ok": True, "count": updated, "captured_at": now}
    except Exception as exc:
        core.log("component-intelligence", f"component signature refresh unavailable: {type(exc).__name__}: {_clean(exc, 180)}", "warn")
        return {"ok": False, "reason": f"{type(exc).__name__}: {_clean(exc, 180)}"}


def _aggregate_rows(component_type: str, since: float) -> list[tuple]:
    return core.db(
        "SELECT c.component_id,c.component_type,c.name,c.binary_name,c.publisher,c.product_name,"
        "c.file_version,c.signature_status,c.signer,c.protected,c.dependencies_json,c.dependents_json,"
        "c.start_mode,c.service_state,c.first_seen,c.last_seen,COUNT(s.id),"
        "COUNT(DISTINCT date(s.ts,'unixepoch')),MIN(s.ts),MAX(s.ts),"
        "AVG(s.cpu_pct),MAX(s.cpu_pct),AVG(s.memory_mb),MAX(s.memory_mb),AVG(s.io_mb_s),"
        "AVG(s.foreground),AVG(s.visible_windows),AVG(s.onscreen_windows),"
        "AVG(s.running),c.metadata_checked_at "
        "FROM component_catalog c JOIN component_samples s ON s.component_id=c.component_id "
        "WHERE c.component_type=? AND s.ts>=? GROUP BY c.component_id ORDER BY c.name COLLATE NOCASE",
        (component_type, since),
    )


def _preference_map() -> dict[str, dict[str, Any]]:
    rows = core.db("SELECT component_id,preference,note,updated_at FROM component_preferences")
    return {
        str(row[0]): {"preference": str(row[1]), "note": _clean(row[2], 160), "updated_at": float(row[3])}
        for row in rows
    }


def _process_candidate(row: tuple, pref: dict[str, Any], current_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    (component_id, _kind, name, binary_name, publisher, product, version, signature, signer,
     protected, _deps, _dependents, _start, _state, first_seen, last_seen, samples, active_days,
     min_ts, max_ts, avg_cpu, max_cpu, avg_mem, max_mem, avg_io, foreground_ratio,
     visible_avg, onscreen_avg, _running_ratio, metadata_at) = row
    if protected or pref.get("preference") in ("keep", "not_needed"):
        return None
    if pref.get("preference") == "review_later" and time.time() - float(pref.get("updated_at") or 0) < 7 * 86400:
        return None
    span_hours = max(0.0, (float(max_ts or 0) - float(min_ts or 0)) / 3600.0)
    if signature != "Valid" or not publisher:
        return None
    if int(samples or 0) < 120 or int(active_days or 0) < _BASELINE_MIN_DAYS or span_hours < _BASELINE_MIN_DAYS * 24:
        return None
    cpu = float(avg_cpu or 0)
    memory = float(avg_mem or 0)
    io_rate = float(avg_io or 0)
    fg = float(foreground_ratio or 0)
    visible = float(visible_avg or 0)
    resource_reasons = []
    if cpu >= 0.35:
        resource_reasons.append(f"mean CPU {cpu:.2f}% while sampled")
    if memory >= 200:
        resource_reasons.append(f"mean working set {memory:.0f} MB")
    if io_rate >= 0.25:
        resource_reasons.append(f"mean process I/O {io_rate:.2f} MB/s")
    if not resource_reasons or fg > 0.02:
        return None
    current = next((item for item in current_rows if process_component_id(item.get("exe")) == component_id), None)
    candidate = {
        "id": component_id, "component_type": "process",
        "name": _clean(name, 100), "binary_name": _clean(binary_name, 100),
        "publisher": _clean(publisher, 140), "product_name": _clean(product, 120),
        "file_version": _clean(version, 80), "signature_status": signature, "signer": _clean(signer, 180),
        "evidence_strength": "high" if int(active_days or 0) >= 10 and int(samples or 0) >= 500 else "medium",
        "sample_count": int(samples or 0), "active_days": int(active_days or 0),
        "baseline_span_hours": round(span_hours, 1),
        "average_cpu_pct": round(cpu, 3), "peak_cpu_pct": round(float(max_cpu or 0), 2),
        "average_memory_mb": round(memory, 1), "peak_memory_mb": round(float(max_mem or 0), 1),
        "average_io_mb_s": round(io_rate, 3),
        "foreground_sample_pct": round(fg * 100, 2),
        "average_visible_windows": round(visible, 2),
        "resource_reasons": resource_reasons,
        "requires_user_intent": True,
        "recommendation": "Background application/helper worth an intent check; no stop/disable action is implied.",
        "preference": pref.get("preference", "unreviewed"),
        "operator_note": _clean(pref.get("note"), 160),
        "current_instance": None,
    }
    if current and int(current.get("visible_windows") or 0) > 0 and int(current.get("onscreen_windows") or 0) > 0:
        candidate["current_instance"] = {
            "pid": int(current.get("pid") or 0),
            "create_time": float(current.get("create_time") or 0),
            "visible_windows": int(current.get("visible_windows") or 0),
            "onscreen_windows": int(current.get("onscreen_windows") or 0),
        }
    return candidate


def _service_candidate(row: tuple, pref: dict[str, Any]) -> dict[str, Any] | None:
    (component_id, _kind, name, binary_name, publisher, product, version, signature, signer,
     protected, dependencies_json, dependents_json, start_mode, service_state, first_seen,
     last_seen, samples, active_days, min_ts, max_ts, _avg_cpu, _max_cpu, _avg_mem, _max_mem,
     _avg_io, _foreground, _visible, _onscreen, running_ratio, metadata_at) = row
    if protected or pref.get("preference") in ("keep", "not_needed"):
        return None
    if pref.get("preference") == "review_later" and time.time() - float(pref.get("updated_at") or 0) < 7 * 86400:
        return None
    if start_mode not in ("auto", "automatic") or service_state != "running":
        return None
    if signature != "Valid" or not publisher:
        return None
    try:
        dependencies = json.loads(dependencies_json or "[]")
        dependents = json.loads(dependents_json or "[]")
    except (TypeError, ValueError):
        return None
    if not isinstance(dependencies, list) or not isinstance(dependents, list):
        return None
    if dependents:
        return None
    span_hours = max(0.0, (float(max_ts or 0) - float(min_ts or 0)) / 3600.0)
    if int(samples or 0) < 250 or int(active_days or 0) < _BASELINE_MIN_DAYS or span_hours < _BASELINE_MIN_DAYS * 24:
        return None
    return {
        "id": component_id, "component_type": "service",
        "name": _clean(name, 100), "binary_name": _clean(binary_name, 100),
        "publisher": _clean(publisher, 140), "product_name": _clean(product, 120),
        "file_version": _clean(version, 80), "signature_status": signature,
        "signer": _clean(signer, 180), "evidence_strength": "medium",
        "sample_count": int(samples or 0), "active_days": int(active_days or 0),
        "baseline_span_hours": round(span_hours, 1),
        "start_mode": start_mode, "service_state": service_state,
        "dependencies": [_clean(value, 80) for value in dependencies[:20]],
        "dependents": [_clean(value, 80) for value in dependents[:20]],
        "dependent_count": len(dependents), "running_sample_pct": round(float(running_ratio or 0) * 100, 1),
        "requires_user_intent": True,
        "recommendation": "Third-party auto-start service with no SCM dependents; application dependencies and user intent are not established. Review only.",
        "preference": pref.get("preference", "unreviewed"),
        "operator_note": _clean(pref.get("note"), 160),
    }


def report() -> dict[str, Any]:
    ensure_schema()
    now = time.time()
    since = now - _RETENTION_SECONDS
    preferences = _preference_map()
    process_rows = _aggregate_rows("process", since)
    service_rows = _aggregate_rows("service", since)
    current = core.STATE.get("procs") if isinstance(core.STATE.get("procs"), list) else []
    process_candidates = [
        item for row in process_rows
        if (item := _process_candidate(row, preferences.get(str(row[0]), {}), current)) is not None
    ]
    service_candidates = [
        item for row in service_rows
        if (item := _service_candidate(row, preferences.get(str(row[0]), {}))) is not None
    ]
    process_candidates.sort(
        key=lambda item: (
            item["average_cpu_pct"] * 2.0
            + item["average_memory_mb"] / 160.0
            + item["average_io_mb_s"] * 4.0
        ),
        reverse=True,
    )
    service_candidates.sort(key=lambda item: (item["active_days"], item["sample_count"]), reverse=True)

    state_graph = _load_state("service_graph")
    signature_state = _load_state("signature_refresh")
    last_process = _last_sample("process")
    last_service = _last_sample("service")
    process_days = max((int(row[17] or 0) for row in process_rows), default=0)
    service_days = max((int(row[17] or 0) for row in service_rows), default=0)
    preferences_count = len(preferences)
    return {
        "status": "ready" if process_rows or service_rows else "collecting",
        "generated_at": now,
        "retention_days": 30,
        "baseline_minimum_days": _BASELINE_MIN_DAYS,
        "sampling": {"process_seconds": _PROCESS_SAMPLE_SECONDS, "service_seconds": _SERVICE_SAMPLE_SECONDS},
        "coverage": {
            "process_components": len(process_rows), "service_components": len(service_rows),
            "process_max_observed_days": process_days, "service_max_observed_days": service_days,
            "process_last_sample_at": last_process or None, "service_last_sample_at": last_service or None,
            "service_dependency_graph_at": state_graph.get("captured_at"),
            "service_dependency_graph_count": int(state_graph.get("count") or 0),
            "signature_refresh_at": signature_state.get("captured_at"),
            "signature_refresh_count": int(signature_state.get("count") or 0),
            "review_preferences_saved": preferences_count,
            "signed_process_components": sum(1 for row in process_rows if row[7] == "Valid"),
            "signed_services": sum(1 for row in service_rows if row[7] == "Valid"),
        },
        "process_candidates": process_candidates[:12],
        "service_candidates": service_candidates[:12],
        "review_boundary": "Candidates are questions for the operator. Nothing is closed, disabled, removed, or changed automatically.",
    }


def ai_evidence() -> dict[str, Any]:
    """Compact source-backed baseline evidence for the local Windows specialist."""
    payload = report()
    ids = []
    processes = []
    for index, item in enumerate(payload["process_candidates"][:8]):
        evidence_id = "component-process." + str(index + 1)
        ids.append(evidence_id)
        processes.append({
            "id": evidence_id, "name": item["name"], "publisher": item["publisher"],
            "signature": item["signature_status"], "baseline_days": item["active_days"],
            "samples": item["sample_count"], "average_cpu_pct": item["average_cpu_pct"],
            "average_memory_mb": item["average_memory_mb"], "average_io_mb_s": item["average_io_mb_s"],
            "foreground_sample_pct": item["foreground_sample_pct"],
            "reasons": item["resource_reasons"],
            "evidence_strength": item["evidence_strength"], "operator_intent": item["preference"],
            "operator_note": item["operator_note"],
        })
    service_graph = []
    try:
        rows = core.db(
            "SELECT component_id,name,binary_name,publisher,signature_status,protected,dependencies_json,dependents_json,start_mode,service_state "
            "FROM component_catalog WHERE component_type='service' ORDER BY name COLLATE NOCASE LIMIT 18"
        )
        for index, row in enumerate(rows):
            try:
                dependencies = json.loads(row[6] or "[]")
                dependents = json.loads(row[7] or "[]")
            except (TypeError, ValueError):
                dependencies, dependents = [], []
            evidence_id = "component-service-graph." + str(index + 1)
            ids.append(evidence_id)
            service_graph.append({
                "id": evidence_id, "name": _clean(row[1], 80), "binary_name": _clean(row[2], 80),
                "publisher": _clean(row[3], 100), "signature": _clean(row[4], 30),
                "protected": bool(row[5]), "dependencies": [_clean(value, 70) for value in dependencies[:12]],
                "dependents": [_clean(value, 70) for value in dependents[:12]],
                "start_mode": _clean(row[8], 24), "state": _clean(row[9], 24),
            })
    except Exception:
        service_graph = []

    services = []
    for index, item in enumerate(payload["service_candidates"][:8]):
        evidence_id = "component-service." + str(index + 1)
        ids.append(evidence_id)
        services.append({
            "id": evidence_id, "name": item["name"], "publisher": item["publisher"],
            "signature": item["signature_status"], "start_mode": item["start_mode"],
            "baseline_days": item["active_days"], "samples": item["sample_count"],
            "dependencies": item["dependencies"], "dependents": item["dependents"],
            "evidence_strength": item["evidence_strength"], "operator_intent": item["preference"],
            "operator_note": item["operator_note"],
        })
    operator_preferences = []
    try:
        rows = core.db(
            "SELECT c.component_id,c.component_type,c.name,c.publisher,p.preference,p.note,p.updated_at "
            "FROM component_preferences p JOIN component_catalog c ON c.component_id=p.component_id "
            "ORDER BY p.updated_at DESC LIMIT 16"
        )
        for index, row in enumerate(rows):
            evidence_id = "component-preference." + str(index + 1)
            ids.append(evidence_id)
            operator_preferences.append({
                "id": evidence_id, "component_type": _clean(row[1], 20),
                "name": _clean(row[2], 80), "publisher": _clean(row[3], 80),
                "preference": _clean(row[4], 24), "operator_note": _clean(row[5], 140),
                "updated_at": float(row[6] or 0),
            })
    except Exception:
        operator_preferences = []

    return {
        "component_baseline_coverage": payload["coverage"],
        "background_process_review_candidates": processes,
        "third_party_service_review_candidates": services,
        "service_dependency_graph": service_graph,
        "operator_component_preferences": operator_preferences,
        "component_evidence_ids": ids,
        "component_baseline_retention_days": payload["retention_days"],
    }


def set_preference(component_id: str, preference: str, note: str = "") -> dict[str, Any]:
    ensure_schema()
    component_id = str(component_id or "").strip()
    preference = str(preference or "").strip().casefold()
    if not component_id or len(component_id) > 64 or preference not in ("keep", "not_needed", "review_later", "note_only", "clear"):
        raise ValueError("A known component ID and keep/not_needed/review_later/note_only/clear preference are required.")
    rows = core.db("SELECT component_type,name FROM component_catalog WHERE component_id=?", (component_id,))
    if not rows:
        raise ValueError("Component baseline was not found. Refresh component intelligence and try again.")
    if preference == "clear":
        core.db("DELETE FROM component_preferences WHERE component_id=?", (component_id,))
    else:
        core.db(
            "INSERT INTO component_preferences(component_id,preference,note,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(component_id) DO UPDATE SET preference=excluded.preference,note=excluded.note,updated_at=excluded.updated_at",
            (component_id, preference, _clean(note, 180), time.time()),
        )
    core.log("component-intelligence", "operator component preference saved", "info",
             component_type=str(rows[0][0]), component=_clean(rows[0][1], 90), preference=preference)
    return {"ok": True, "component_id": component_id, "preference": preference}


def propose_graceful_close(component_id: str) -> dict[str, Any]:
    """Create a normal pending action proposal for one exact visible GUI instance."""
    ensure_schema()
    if not str(component_id or "").startswith("process:"):
        raise ValueError("Only a process component can receive a graceful-close proposal.")
    if core.STATE.get("game"):
        raise RuntimeError("Process close proposals are deferred while a game session is active.")
    rows = core.db("SELECT protected,name FROM component_catalog WHERE component_id=?", (component_id,))
    if not rows or bool(rows[0][0]):
        raise ValueError("This component is protected or has no verified baseline.")
    current_rows = core.STATE.get("procs") if isinstance(core.STATE.get("procs"), list) else []
    current = next((row for row in current_rows if process_component_id(row.get("exe")) == component_id), None)
    if not current:
        raise RuntimeError("The observed process instance is no longer running; refresh the baseline.")
    if safeguard.is_protected_process(current.get("name"), current.get("exe")):
        raise PermissionError("Safeguard protects this process.")
    if int(current.get("visible_windows") or 0) <= 0 or int(current.get("onscreen_windows") or 0) <= 0:
        raise ValueError("Graceful close requires a currently visible on-screen GUI window.")
    if int(current.get("session_id") or 0) <= 0 or current.get("path_state") != "present":
        raise ValueError("Process identity or interactive session is not sufficiently verified.")
    from . import actions
    action_id = actions.propose(
        "terminate_process",
        {"pid": int(current["pid"]), "create_time": float(current["create_time"]), "exe": str(current["exe"])},
        origin="component-intelligence",
        reason="Operator requested a graceful close proposal after reviewing the 7-day component baseline.",
    )
    if action_id is None:
        raise RuntimeError("The action engine refused this graceful-close proposal.")
    return {"ok": True, "action_id": int(action_id), "requires_confirmation": True,
            "message": "A pending graceful-close proposal was created. The process remains open until you approve it in Actions."}


def _resource_gate() -> tuple[bool, str]:
    if not core.IS_WIN:
        return False, "Windows-only component intelligence."
    if core.STATE.get("game"):
        return False, "Optional component metadata work is paused during game sessions."
    try:
        from . import runtime_engine
        return runtime_engine.admit_optional_work(
            "component baseline enrichment", min_available_gib=5.0, max_cpu_percent=40.0,
        )
    except Exception as exc:
        return False, f"Runtime admission unavailable: {type(exc).__name__}"


def _process_signature_paths(force: bool = False) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in _process_rows():
        exe = _normal_path(row.get("exe"))
        component_id = process_component_id(exe)
        if not exe or not component_id or safeguard.is_protected_process(row.get("name"), exe):
            continue
        if _is_windows_binary(exe):
            continue
        existing = core.db("SELECT metadata_checked_at FROM component_catalog WHERE component_id=?", (component_id,))
        if force or not existing or time.time() - float(existing[0][0] or 0) >= _SIGNATURE_REFRESH_SECONDS:
            result[component_id] = exe
    return result


def _service_graph_rows() -> list[dict[str, Any]]:
    raw_rows = _SERVICE_GRAPH_CACHE.get("services")
    if isinstance(raw_rows, list) and raw_rows:
        return [row for row in raw_rows if isinstance(row, dict)]
    graph = _load_state("service_graph")
    rows = graph.get("services") if isinstance(graph.get("services"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _refresh_signatures_from_paths(paths_by_id: dict[str, str]) -> int:
    if not paths_by_id:
        return 0
    chosen = list(paths_by_id.items())[:_MAX_SIGNATURE_PATHS]
    metadata = _authenticode_query([path for _component_id, path in chosen])
    updated = 0
    for index, item in enumerate(metadata):
        if index >= len(chosen):
            break
        component_id, _path = chosen[index]
        core.db(
            "UPDATE component_catalog SET binary_name=?,publisher=?,product_name=?,file_version=?,"
            "signature_status=?,signer=?,metadata_checked_at=? WHERE component_id=?",
            (
                _clean(item.get("binary_name"), 120), _clean(item.get("publisher"), 140),
                _clean(item.get("product_name"), 140), _clean(item.get("file_version"), 80),
                _clean(item.get("signature_status") or "Unavailable", 40),
                _clean(item.get("signer"), 180), time.time(), component_id,
            ),
        )
        updated += 1
    return updated


def _refresh_enrichment(force: bool = False) -> dict[str, Any]:
    permitted, reason = _resource_gate()
    if not permitted:
        return {"ok": False, "deferred": True, "reason": reason}
    graph = refresh_service_graph(force=force)
    # Make sure identities exist before the signature result is written back.
    sample_processes()
    sample_services()
    # Service catalog rows are refreshed by the SCM collector; only query signatures
    # when the dependency map and process sample are available.
    paths = _process_signature_paths(force=force)
    for row in _service_graph_rows():
        path = _normal_path(row.get("binary_path"))
        component_id = service_component_id(row.get("name"))
        if not path or not component_id or _protected_service(row, path) or _is_windows_binary(path):
            continue
        existing = core.db("SELECT metadata_checked_at FROM component_catalog WHERE component_id=?", (component_id,))
        if force or not existing or time.time() - float(existing[0][0] or 0) >= _SIGNATURE_REFRESH_SECONDS:
            paths[component_id] = path
    updated = _refresh_signatures_from_paths(paths)
    return {"ok": bool(graph.get("ok")), "graph": graph, "signatures_updated": updated}



def refresh_now() -> dict[str, Any]:
    """Operator-triggered dependency/signature refresh; resource/game gates still apply."""
    result = _refresh_enrichment(force=True)
    if result.get("ok"):
        _save_state("enrichment", {"captured_at": time.time(),
                                    "signatures_updated": int(result.get("signatures_updated") or 0)})
    return result


def _loop() -> None:
    ensure_schema()
    last_process = _last_sample("process")
    last_service = _last_sample("service")
    enrichment = _load_state("enrichment")
    last_enrichment = float(enrichment.get("captured_at") or 0)
    last_enrichment_attempt = float(_load_state("enrichment_attempt").get("attempted_at") or 0)
    last_retention = 0.0
    last_report = 0.0
    cached_report: dict[str, Any] = {}
    while not _STOP.is_set():
        now = time.time()
        try:
            if now - last_process >= _PROCESS_SAMPLE_SECONDS and core.STATE.get("procs"):
                sample_processes(now)
                last_process = now
            if now - last_service >= _SERVICE_SAMPLE_SECONDS and core.STATE.get("services_catalog"):
                sample_services(now)
                last_service = now
            if (now - last_enrichment >= _GRAPH_REFRESH_SECONDS
                    and now - last_enrichment_attempt >= 900
                    and core.STATE.get("procs") and core.STATE.get("services_catalog")):
                last_enrichment_attempt = now
                result = _refresh_enrichment()
                _save_state("enrichment_attempt", {
                    "attempted_at": now, "ok": bool(result.get("ok")),
                    "deferred": bool(result.get("deferred")),
                    "reason": _clean(result.get("reason"), 160),
                })
                if result.get("ok"):
                    last_enrichment = now
                    _save_state("enrichment", {
                        "captured_at": now,
                        "signatures_updated": int(result.get("signatures_updated") or 0),
                    })
            if now - last_retention >= 3600:
                core.db("DELETE FROM component_samples WHERE ts<?", (now - _RETENTION_SECONDS,))
                core.db("DELETE FROM component_catalog WHERE last_seen<? AND component_id NOT IN "
                        "(SELECT component_id FROM component_preferences)", (now - _RETENTION_SECONDS,))
                last_retention = now
            # Aggregate the 30-day sample store at most once every five minutes;
            # do not run a full GROUP BY over hundreds of thousands of samples
            # on every 20-second sampler tick.
            if now - last_report >= 300:
                cached_report = report()
                core.persist_snapshot("components.latest", cached_report)
                last_report = now
            if cached_report:
                core.heartbeat(
                    "component baselines", 60,
                    f"{cached_report['coverage']['process_components']} process identities · "
                    f"{cached_report['coverage']['service_components']} services · "
                    f"{len(cached_report['process_candidates']) + len(cached_report['service_candidates'])} review candidates",
                )
        except Exception as exc:
            core.log("component-intelligence", f"baseline cycle failed: {type(exc).__name__}: {_clean(exc, 180)}", "warn")
            core.heartbeat("component baselines", 60, err=f"{type(exc).__name__}: {_clean(exc, 120)}")
        _STOP.wait(20)


def start() -> None:
    global _STARTED, _THREAD
    if _STARTED:
        return
    ensure_schema()
    _STOP.clear()
    _STARTED = True
    _THREAD = threading.Thread(target=_loop, name="component-intelligence", daemon=True)
    _THREAD.start()


def shutdown() -> None:
    _STOP.set()
    if _THREAD and _THREAD.is_alive():
        _THREAD.join(timeout=3.0)
