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
    if not core.IS_WIN or core.off("processes") or core.STATE.get("game"):
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
        "AVG(s.running),c.metadata_checked_at,"
        "AVG(CASE WHEN s.visible_windows>0 THEN 1.0 ELSE 0.0 END),"
        "AVG(CASE WHEN s.onscreen_windows>0 THEN 1.0 ELSE 0.0 END) "
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


def _certificate_organization(subject: Any) -> str:
    """Prefer the organization identity in the signing certificate over file metadata."""
    text = str(subject or "")
    fields = {}
    for part in re.split(r"(?<!\\),", text):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip().casefold()] = value.strip().replace(r"\,", ",")
    return _clean(fields.get("o") or fields.get("cn") or "", 140)


def _publisher_consistency(file_company: Any, signer_subject: Any) -> str:
    """Compare mutable PE company metadata with the signed certificate identity."""
    company = str(file_company or "").strip()
    organization = _certificate_organization(signer_subject)
    if not company or not organization:
        return "unknown"
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", str(value).casefold())
    left, right = normalize(company), normalize(organization)
    if left and right and (left == right or left in right or right in left):
        return "consistent"
    return "different"


def _baseline_confidence(samples: Any, active_days: Any, span_hours: Any,
                         signature_status: str, publisher_consistency: str = "unknown") -> float:
    """Measurement coverage score, not a probability that a component is unnecessary."""
    sample_coverage = min(1.0, max(0.0, float(samples or 0) / 500.0))
    day_coverage = min(1.0, max(0.0, float(active_days or 0) / 14.0))
    span_coverage = min(1.0, max(0.0, float(span_hours or 0) / (14.0 * 24.0)))
    signature_coverage = 1.0 if signature_status == "Valid" else 0.0
    score = 30.0 * sample_coverage + 25.0 * day_coverage + 25.0 * span_coverage + 20.0 * signature_coverage
    if publisher_consistency == "different":
        score -= 8.0
    elif publisher_consistency != "consistent":
        score -= 3.0
    return round(min(100.0, max(0.0, score)), 1)


def _evidence_strength(score: float) -> str:
    if score >= 80.0:
        return "high"
    if score >= 60.0:
        return "medium"
    return "low"


def _current_interactive_instance(component_id: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return one unambiguous visible GUI process instance; never pick by PID alone."""
    matches = []
    for row in rows:
        if not isinstance(row, dict) or process_component_id(row.get("exe")) != component_id:
            continue
        if safeguard.is_protected_process(row.get("name"), row.get("exe")):
            continue
        try:
            valid = (
                int(row.get("pid") or 0) > 4
                and float(row.get("create_time") or 0) > 0
                and int(row.get("session_id") or 0) > 0
                and int(row.get("visible_windows") or 0) > 0
                and int(row.get("onscreen_windows") or 0) > 0
                and row.get("path_state") == "present"
            )
        except (TypeError, ValueError):
            valid = False
        if valid:
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _process_candidate(row: tuple, pref: dict[str, Any], current_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    (component_id, _kind, name, binary_name, publisher, product, version, signature, signer,
     protected, _deps, _dependents, _start, _state, first_seen, last_seen, samples, active_days,
     min_ts, max_ts, avg_cpu, max_cpu, avg_mem, max_mem, avg_io, foreground_ratio,
     visible_avg, onscreen_avg, _running_ratio, metadata_at, visible_sample_ratio, onscreen_sample_ratio) = row
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
    visible_ratio = float(visible_sample_ratio or 0)
    onscreen_ratio = float(onscreen_sample_ratio or 0)
    resource_reasons = []
    if cpu >= 0.35:
        resource_reasons.append(f"mean CPU {cpu:.2f}% while sampled")
    if memory >= 200:
        resource_reasons.append(f"mean working set {memory:.0f} MB")
    if io_rate >= 0.25:
        resource_reasons.append(f"mean process I/O {io_rate:.2f} MB/s")
    # Foreground AND historically visible-window samples are required to be low.
    # Minimized/behind-other-windows apps should not be mislabeled as headless helpers.
    if not resource_reasons or fg > 0.02 or visible_ratio > 0.05 or onscreen_ratio > 0.02:
        return None
    publisher_consistency = _publisher_consistency(publisher, signer)
    confidence_score = _baseline_confidence(samples, active_days, span_hours, signature, publisher_consistency)
    cpu_impact = min(100.0, max(0.0, cpu / 5.0 * 100.0))
    memory_impact = min(100.0, max(0.0, memory / 1024.0 * 100.0))
    io_impact = min(100.0, max(0.0, io_rate / 5.0 * 100.0))
    resource_impact_score = round(cpu_impact * 0.35 + memory_impact * 0.45 + io_impact * 0.20, 1)
    background_sample_pct = round(max(0.0, 1.0 - max(fg, visible_ratio, onscreen_ratio)) * 100.0, 1)
    review_priority_score = round((resource_impact_score * confidence_score) ** 0.5 * background_sample_pct / 100.0, 1)
    current = _current_interactive_instance(component_id, current_rows)
    candidate = {
        "id": component_id, "component_type": "process",
        "name": _clean(name, 100), "binary_name": _clean(binary_name, 100),
        "publisher": _clean(publisher, 140), "product_name": _clean(product, 120),
        "file_version": _clean(version, 80), "signature_status": signature, "signer": _clean(signer, 180),
        "certificate_organization": _certificate_organization(signer),
        "publisher_consistency": publisher_consistency,
        "evidence_confidence_score": confidence_score,
        "evidence_strength": _evidence_strength(confidence_score),
        "resource_impact_score": resource_impact_score,
        "background_sample_pct": background_sample_pct,
        "review_priority_score": review_priority_score,
        "sample_count": int(samples or 0), "active_days": int(active_days or 0),
        "baseline_span_hours": round(span_hours, 1),
        "average_cpu_pct": round(cpu, 3), "peak_cpu_pct": round(float(max_cpu or 0), 2),
        "average_memory_mb": round(memory, 1), "peak_memory_mb": round(float(max_mem or 0), 1),
        "average_io_mb_s": round(io_rate, 3),
        "foreground_sample_pct": round(fg * 100, 2),
        "visible_window_sample_pct": round(visible_ratio * 100.0, 2),
        "onscreen_window_sample_pct": round(onscreen_ratio * 100.0, 2),
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
     _avg_io, _foreground, _visible, _onscreen, running_ratio, metadata_at,
     _visible_sample_ratio, _onscreen_sample_ratio) = row
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
    publisher_consistency = _publisher_consistency(publisher, signer)
    confidence_score = _baseline_confidence(samples, active_days, span_hours, signature, publisher_consistency)
    return {
        "id": component_id, "component_type": "service",
        "name": _clean(name, 100), "binary_name": _clean(binary_name, 100),
        "publisher": _clean(publisher, 140), "product_name": _clean(product, 120),
        "file_version": _clean(version, 80), "signature_status": signature,
        "signer": _clean(signer, 180), "certificate_organization": _certificate_organization(signer),
        "publisher_consistency": publisher_consistency,
        "evidence_confidence_score": confidence_score, "evidence_strength": _evidence_strength(confidence_score),
        "ownership_review_score": confidence_score,
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
    state_graph = _load_state("service_graph")
    signature_state = _load_state("signature_refresh")
    graph_captured_at = float(state_graph.get("captured_at") or 0)
    graph_age_hours = (now - graph_captured_at) / 3600.0 if graph_captured_at else None
    graph_fresh = (bool(state_graph.get("count")) and graph_age_hours is not None
                   and 0.0 <= graph_age_hours <= 24.0)
    service_review_block_reason = "" if graph_fresh else (
        "Waiting for a complete service dependency graph newer than 24 hours; no service ownership candidates are shown."
    )
    current = core.STATE.get("procs") if isinstance(core.STATE.get("procs"), list) else []
    process_candidates = [
        item for row in process_rows
        if (item := _process_candidate(row, preferences.get(str(row[0]), {}), current)) is not None
    ]
    service_candidates = [
        item for row in service_rows
        if graph_fresh
        and (item := _service_candidate(row, preferences.get(str(row[0]), {}))) is not None
    ]
    process_candidates.sort(key=lambda item: item["review_priority_score"], reverse=True)
    # This is an ownership-review ordering score, not measured resource impact.
    service_candidates.sort(key=lambda item: item["ownership_review_score"], reverse=True)

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
        "score_semantics": {
            "evidence_confidence_score": "0-100 measurement-coverage heuristic: 30% sample count (500 cap), 25% observed days (14-day cap), 25% baseline span (14-day cap), 20% valid Authenticode signature; subtract 8 for PE-company/certificate-organization mismatch or 3 when unknown. It is not a probability of disuse.",
            "resource_impact_score": "0-100 process-only normalized average impact: CPU normalized to 5%, working set to 1024 MB and process I/O to 5 MB/s, weighted 35/45/20. This is a triage scale, not a benchmark or user-value score.",
            "review_priority_score": "Process sorting heuristic: square-root(resource impact × evidence confidence) scaled by the sampled background share. It does not infer that the app is unnecessary or authorize an action.",
            "ownership_review_score": "Evidence coverage for a signed auto-start service with no listed SCM dependents; no service resource-impact score is claimed.",
        },
        "coverage": {
            "process_components": len(process_rows), "service_components": len(service_rows),
            "process_max_observed_days": process_days, "service_max_observed_days": service_days,
            "process_last_sample_at": last_process or None, "service_last_sample_at": last_service or None,
            "service_dependency_graph_at": state_graph.get("captured_at"),
            "service_dependency_graph_count": int(state_graph.get("count") or 0),
            "service_dependency_graph_age_hours": round(graph_age_hours, 2) if graph_age_hours is not None else None,
            "service_dependency_graph_fresh": graph_fresh,
            "signature_refresh_at": signature_state.get("captured_at"),
            "signature_refresh_count": int(signature_state.get("count") or 0),
            "review_preferences_saved": preferences_count,
            "signed_process_components": sum(1 for row in process_rows if row[7] == "Valid"),
            "signed_services": sum(1 for row in service_rows if row[7] == "Valid"),
        },
        "process_candidates": process_candidates[:12],
        "service_candidates": service_candidates[:12],
        "service_review_block_reason": service_review_block_reason,
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
            "visible_window_sample_pct": item["visible_window_sample_pct"],
            "onscreen_window_sample_pct": item["onscreen_window_sample_pct"],
            "resource_impact_score": item["resource_impact_score"],
            "review_priority_score": item["review_priority_score"],
            "evidence_confidence_score": item["evidence_confidence_score"],
            "publisher_consistency": item["publisher_consistency"],
            "certificate_organization": item["certificate_organization"],
            "reasons": item["resource_reasons"],
            "evidence_strength": item["evidence_strength"], "operator_intent": item["preference"],
            "operator_note": item["operator_note"],
        })
    service_graph = []
    try:
        rows = core.db(
            "SELECT component_id,name,binary_name,publisher,signature_status,signer,protected,dependencies_json,dependents_json,start_mode,service_state "
            "FROM component_catalog WHERE component_type='service' ORDER BY name COLLATE NOCASE LIMIT 18"
        )
        for index, row in enumerate(rows):
            try:
                dependencies = json.loads(row[7] or "[]")
                dependents = json.loads(row[8] or "[]")
            except (TypeError, ValueError):
                dependencies, dependents = [], []
            evidence_id = "component-service-graph." + str(index + 1)
            ids.append(evidence_id)
            service_graph.append({
                "id": evidence_id, "name": _clean(row[1], 80), "binary_name": _clean(row[2], 80),
                "publisher": _clean(row[3], 100), "signature": _clean(row[4], 30),
                "signer": _clean(row[5], 180), "publisher_consistency": _publisher_consistency(row[3], row[5]),
                "protected": bool(row[6]), "dependencies": [_clean(value, 70) for value in dependencies[:12]],
                "dependents": [_clean(value, 70) for value in dependents[:12]],
                "start_mode": _clean(row[9], 24), "state": _clean(row[10], 24),
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
            "evidence_strength": item["evidence_strength"],
            "evidence_confidence_score": item["evidence_confidence_score"],
            "publisher_consistency": item["publisher_consistency"],
            "certificate_organization": item["certificate_organization"],
            "ownership_review_score": item["ownership_review_score"],
            "operator_intent": item["preference"], "operator_note": item["operator_note"],
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
        "component_score_semantics": payload["score_semantics"],
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
    current = _current_interactive_instance(component_id, current_rows)
    if not current:
        raise RuntimeError("A single, unambiguous visible GUI process instance is required. Refresh the process list and retry.")
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
