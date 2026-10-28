"""Privacy-preserving startup and scheduled-task provenance.

The collector resolves exact executable targets in memory, then persists only
hashed component identities, executable basenames, Authenticode metadata and
relationship edges. Raw command lines, arguments, executable paths, user names
and task action payloads are never written to SQLite.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import core

_MAX_ITEMS = 800
_MAX_BINARIES = 240
_MAX_UI_STARTUP = 36
_MAX_UI_TASKS = 48


def ensure_schema() -> None:
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


def _ci():
    # Lazy import avoids a module cycle: component_intelligence calls refresh()
    # only after its own module has finished importing.
    from . import component_intelligence
    return component_intelligence


def _normal_path(value: Any) -> str:
    return _ci()._normal_path(value)


def _clean(value: Any, limit: int = 120) -> str:
    return _ci()._clean(value, limit)


def _identity_hash(kind: str, value: str) -> str:
    return _ci()._identity_hash(kind, value)


def _service_component_id(name: Any) -> str | None:
    return _ci().service_component_id(name)


def _is_windows_binary(path: str) -> bool:
    return _ci()._is_windows_binary(path)


def _protected_process(name: str, path: str) -> bool:
    from . import safeguard
    return safeguard.is_protected_process(name, path)


def binary_component_id(executable: Any) -> str | None:
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
    if not name_text or len(name_text) > 180:
        return None
    identity = "\0".join((
        name_text.casefold(),
        str(publisher or "").strip().casefold(),
        str(version or "").strip().casefold(),
    ))
    return "app:" + _identity_hash("app", identity)


def _extract_launch_target(command: Any) -> dict[str, Any]:
    """Resolve the executable token only; discard arguments and command tail."""
    raw = str(command or "").strip()
    if not raw or len(raw) > 4096:
        return {"binary_path": "", "binary_name": "", "launch_kind": "unresolved", "has_arguments": False}
    expanded = os.path.expandvars(raw)
    expanded = re.sub(r"%([^%]+)%", lambda match: os.environ.get(match.group(1), match.group(0)), expanded)
    match = re.match(r'^\s*"([^"]+?\.exe)"(?=\s|$)', expanded, re.IGNORECASE)
    if not match:
        match = re.match(r"^\s*(.+?\.exe)(?=\s|$)", expanded, re.IGNORECASE)
    if not match:
        return {"binary_path": "", "binary_name": "", "launch_kind": "unresolved", "has_arguments": False}
    path = _normal_path(match.group(1).strip())
    if not path or not re.match(r"^[a-zA-Z]:[\\/]", path):
        return {"binary_path": "", "binary_name": "", "launch_kind": "unresolved", "has_arguments": False}
    name = path.replace("/", "\\").rsplit("\\", 1)[-1]
    wrappers = {
        "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
        "rundll32.exe", "regsvr32.exe", "mshta.exe", "dllhost.exe", "svchost.exe",
        "taskhostw.exe", "java.exe", "javaw.exe", "python.exe", "pythonw.exe", "conhost.exe",
    }
    return {
        "binary_path": path,
        "binary_name": _clean(name, 120),
        "launch_kind": "command_host" if name.casefold() in wrappers else "direct_executable",
        "has_arguments": bool(expanded[match.end():].strip()),
    }


def _launch_inventory_query() -> dict[str, Any]:
    """Windows-only query. Neither raw commands nor task action arguments leave PowerShell."""
    from .winutil import powershell

    script = r"""
$ErrorActionPreference='Stop'
function Resolve-LaunchExe([string]$raw) {
  $value=[Environment]::ExpandEnvironmentVariables([string]$raw)
  if($value -match '^\s*"(?<p>[^"]+?\.exe)"(?=\s|$)') { return [string]$matches['p'] }
  if($value -match '^\s*(?<p>.+?\.exe)(?=\s|$)') { return [string]$matches['p'] }
  return ''
}
$startup=@(); $tasks=@(); $startupOk=$true; $tasksOk=$true
$taskTotal=0
try {
  foreach($item in @(Get-CimInstance Win32_StartupCommand -ErrorAction Stop)) {
    $command=[string]$item.Command
    $exe=Resolve-LaunchExe $command
    $tail=''
    if($command -match '^\s*"(?<p>[^"]+?\.exe)"(?<tail>.*)$') { $tail=[string]$matches['tail'] }
    elseif($command -match '^\s*(?<p>.+?\.exe)(?<tail>\s.*)?$') { $tail=[string]$matches['tail'] }
    $source='Windows startup'
    if($item.Location -match '(?i)HKLM|HKEY_LOCAL_MACHINE') { $source='Registry · All users' }
    elseif($item.Location -match '(?i)HKCU|HKEY_CURRENT_USER') { $source='Registry · Current user' }
    elseif($item.Location -match '(?i)Startup') { $source='Startup folder' }
    $startup+=@{
      name=[string]$item.Name; source=$source; binary_path=$exe
      has_arguments=([string]$tail).Trim().Length -gt 0; enabled=$true
    }
  }
} catch { $startupOk=$false }
try {
  $allTasks=@(Get-ScheduledTask -ErrorAction Stop)
  $taskTotal=$allTasks.Count
  for($i=0;$i -lt [Math]::Min($taskTotal,800);$i++) {
    $task=$allTasks[$i]; $actions=@()
    foreach($action in @($task.Actions)) {
      $raw=[string]$action.Execute
      $exe=Resolve-LaunchExe $raw
      $kind='Unknown'
      if($raw) { $kind='Exec' } elseif($action.ClassId) { $kind='ComHandler' }
      $actions+=@{
        binary_path=$exe; action_kind=$kind
        has_arguments=[bool]([string]$action.Arguments)
      }
    }
    $tasks+=@{
      name=[string]$task.TaskName; task_path=[string]$task.TaskPath
      state=[string]$task.State; enabled=[bool]$task.Settings.Enabled
      run_level=[string]$task.Principal.RunLevel
      logon_type=[string]$task.Principal.LogonType
      actions=@($actions)
    }
  }
} catch { $tasksOk=$false }
@{
  startup=$startup; tasks=$tasks; task_total=$taskTotal
  startup_complete=$startupOk
  tasks_complete=($tasksOk -and $taskTotal -le 800)
  task_truncated=($tasksOk -and $taskTotal -gt 800)
  source_health=@{
    startup=@{ok=$startupOk}
    tasks=@{ok=$tasksOk;count=$taskTotal}
  }
} | ConvertTo-Json -Depth 7 -Compress
"""
    result = powershell(script, timeout=60)
    if result.returncode != 0:
        raise RuntimeError("Windows startup/task inventory command failed.")
    payload = json.loads((result.stdout or "").strip().lstrip("\ufeff"))
    if not isinstance(payload, dict):
        raise RuntimeError("Windows startup/task inventory returned an invalid object.")
    startup, tasks = payload.get("startup", []), payload.get("tasks", [])
    if isinstance(startup, dict):
        startup = [startup]
    if isinstance(tasks, dict):
        tasks = [tasks]
    if not isinstance(startup, list) or not isinstance(tasks, list):
        raise RuntimeError("Windows startup/task inventory lists were incomplete.")
    return {
        "startup": [row for row in startup if isinstance(row, dict)][: _MAX_ITEMS],
        "tasks": [row for row in tasks if isinstance(row, dict)][: _MAX_ITEMS],
        "task_total": int(payload.get("task_total") or 0),
        "startup_complete": payload.get("startup_complete") is True,
        "tasks_complete": payload.get("tasks_complete") is True,
        "task_truncated": payload.get("task_truncated") is True,
        # Persist only availability flags. Provider exception messages can contain paths.
        "source_health": {
            key: {"ok": value.get("ok") is True}
            for key, value in (payload.get("source_health") or {}).items()
            if isinstance(value, dict)
        },
        "captured_at": time.time(),
    }


def _catalog_row(component_id: str, kind: str, name: str, now: float, *,
                 binary_name: str = "", publisher: str = "", version: str = "",
                 protected: bool = False, source: str = "", start_mode: str = "",
                 state: str = "") -> tuple:
    return (
        component_id, kind, component_id.split(":", 1)[1], _clean(name, 140),
        _clean(binary_name, 120), _clean(publisher, 140),
        _clean(name if kind == "app" else "", 140), _clean(version, 80),
        "Unknown", "", int(bool(protected)), _clean(source, 120), "[]", "[]",
        _clean(start_mode, 40), _clean(state, 40), now, now, 0.0,
    )


def _path_under(path: str, root: str) -> bool:
    try:
        return bool(path and root and os.path.commonpath((path, root)) == root and path != root)
    except (OSError, ValueError):
        return False


def _build_graph(snapshot: dict[str, Any], service_rows: list[dict[str, Any]],
                 apps: list[dict[str, Any]], now: float | None = None) -> dict[str, Any]:
    ci = _ci()
    timestamp = float(now or time.time())
    catalog: dict[str, tuple] = {}
    metadata_rows = []
    edges: dict[tuple[str, str, str], tuple] = {}
    binary_paths: dict[str, str] = {}
    startup_ids, task_ids = [], []

    def add_binary(raw_path: str) -> str | None:
        path = _normal_path(raw_path)
        cid = binary_component_id(path)
        if not cid or (cid not in binary_paths and len(binary_paths) >= _MAX_BINARIES):
            return None
        binary_paths[cid] = path
        name = path.replace("/", "\\").rsplit("\\", 1)[-1]
        protected = _is_windows_binary(path) or _protected_process(name, path)
        catalog[cid] = _catalog_row(cid, "binary", name, timestamp, binary_name=name,
                                    protected=protected, source="Startup/task executable provenance")
        return cid

    def add_edge(source: str, target: str, relation: str, confidence: str, evidence: dict[str, Any]):
        key = (source, target, relation)
        edges[key] = (
            source, target, relation, confidence,
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")), timestamp,
        )

    protected_tokens = ("sentinel", "riot", "vanguard", "valorant", "windows security", "defender")
    for raw in (snapshot.get("startup") or [])[:_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"), 120)
        source = _clean(raw.get("source") or "Windows startup", 70)
        cid = startup_component_id(source, name)
        if not cid:
            continue
        target = _extract_launch_target(raw.get("binary_path") or raw.get("command"))
        bid = add_binary(target["binary_path"]) if target.get("binary_path") else None
        binary_name = target.get("binary_name") or ""
        protected = bool(
            (bid and _is_windows_binary(target["binary_path"]))
            or (binary_name and _protected_process(binary_name, target.get("binary_path", "")))
            or any(token in (name + " " + source).casefold() for token in protected_tokens)
        )
        catalog[cid] = _catalog_row(
            cid, "startup", name, timestamp, binary_name=binary_name, protected=protected,
            source=source, start_mode=target.get("launch_kind") or "unresolved", state="present",
        )
        has_args = bool(raw.get("has_arguments") or target.get("has_arguments"))
        meta = {"source": source, "launch_kind": target.get("launch_kind", "unresolved"),
                "has_arguments": has_args, "target_resolved": bool(bid),
                "enabled": bool(raw.get("enabled", True))}
        metadata_rows.append((cid, json.dumps(meta, separators=(",", ":")), timestamp))
        startup_ids.append(cid)
        if bid:
            add_edge(cid, bid, "launches_binary", "path_resolved",
                     {"launch_kind": meta["launch_kind"], "has_arguments": has_args})

    for raw in (snapshot.get("tasks") or [])[:_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"), 120)
        task_path = str(raw.get("task_path") or "\\").strip()
        cid = task_component_id(task_path, name)
        if not cid:
            continue
        microsoft = task_path.casefold().startswith("\\microsoft\\")
        protected_task = microsoft or any(token in (task_path + " " + name).casefold()
                                          for token in protected_tokens)
        actions = raw.get("actions") if isinstance(raw.get("actions"), list) else []
        targets = []
        for index, action in enumerate(actions[:16]):
            if not isinstance(action, dict):
                continue
            target = _extract_launch_target(action.get("binary_path") or action.get("execute"))
            bid = add_binary(target["binary_path"]) if target.get("binary_path") else None
            if bid:
                targets.append({
                    "binary_id": bid, "binary_name": target.get("binary_name") or "",
                    "action_index": index, "action_kind": _clean(action.get("action_kind") or "Exec", 30),
                    "has_arguments": bool(action.get("has_arguments") or target.get("has_arguments")),
                })
        protected = protected_task or any(
            _protected_process(row["binary_name"], binary_paths[row["binary_id"]])
            or _is_windows_binary(binary_paths[row["binary_id"]])
            for row in targets
        )
        enabled = bool(raw.get("enabled"))
        state = _clean(raw.get("state") or "unknown", 24)
        catalog[cid] = _catalog_row(
            cid, "task", name, timestamp,
            binary_name=targets[0]["binary_name"] if targets else "",
            protected=protected, source="Task Scheduler · " + ("Built-in" if protected_task else "Third-party"),
            start_mode=_clean(raw.get("run_level") or "unknown", 24),
            state=state if enabled else "disabled",
        )
        meta = {
            "task_folder_depth": max(0, len([part for part in task_path.split(chr(92)) if part])),
            "microsoft_namespace": microsoft, "enabled": enabled,
            "run_level": _clean(raw.get("run_level"), 24),
            "logon_type": _clean(raw.get("logon_type"), 32),
            "action_count": len(actions), "resolved_executable_actions": len(targets),
            "unresolved_action_count": max(0, len(actions) - len(targets)),
            "launch_kind": "multi_action" if len(targets) > 1 else (
                targets[0]["action_kind"] if targets else "opaque_or_unresolved"),
        }
        metadata_rows.append((cid, json.dumps(meta, separators=(",", ":")), timestamp))
        task_ids.append(cid)
        for target in targets:
            add_edge(cid, target["binary_id"], "launches_binary", "path_resolved", {
                "action_index": target["action_index"], "action_kind": target["action_kind"],
                "has_arguments": target["has_arguments"],
            })

    app_roots = []
    if snapshot.get("apps_complete") is True:
        for app in (apps or [])[:600]:
            if not isinstance(app, dict):
                continue
            root = _normal_path(app.get("location") or app.get("install_location"))
            app_id = app_component_id(app.get("name"), app.get("publisher"), app.get("version"))
            if root and app_id:
                app_roots.append((root, app_id, app))
    for binary_id, executable in binary_paths.items():
        matches = [(len(root), app_id, app) for root, app_id, app in app_roots
                   if _path_under(executable, root)]
        if matches:
            longest = max(match[0] for match in matches)
            best = [match for match in matches if match[0] == longest]
            if len(best) == 1:
                _length, app_id, app = best[0]
                catalog[app_id] = _catalog_row(
                    app_id, "app", _clean(app.get("name"), 140), timestamp,
                    publisher=app.get("publisher") or "", version=app.get("version") or "",
                    source="Installed application inventory",
                )
                add_edge(binary_id, app_id, "installed_under_app",
                         "unique_install_location_prefix", {"path_stored": False})

    if snapshot.get("service_graph_complete") is True:
        service_paths: dict[str, set[str]] = {}
        for service in (service_rows or [])[:_MAX_ITEMS]:
            if not isinstance(service, dict):
                continue
            path = _normal_path(service.get("binary_path"))
            service_id = _service_component_id(service.get("name"))
            if path and service_id:
                service_paths.setdefault(path, set()).add(service_id)
        for binary_id, executable in binary_paths.items():
            for service_id in sorted(service_paths.get(executable, set()))[:8]:
                add_edge(binary_id, service_id, "same_executable_as_service",
                         "exact_executable_path", {"path_stored": False})

    return {
        "catalog_rows": list(catalog.values()), "metadata_rows": metadata_rows,
        "relationships": list(edges.values()), "binary_paths": binary_paths,
        "startup_ids": startup_ids, "task_ids": task_ids,
        "startup_complete": snapshot.get("startup_complete") is True,
        "tasks_complete": snapshot.get("tasks_complete") is True,
        "apps_complete": snapshot.get("apps_complete") is True,
        "service_graph_complete": snapshot.get("service_graph_complete") is True,
        "source_health": snapshot.get("source_health") if isinstance(snapshot.get("source_health"), dict) else {},
        "captured_at": timestamp,
    }


def _persist_graph(graph: dict[str, Any]) -> None:
    ci = _ci()
    ci._bulk_catalog(graph.get("catalog_rows") if isinstance(graph.get("catalog_rows"), list) else [])
    for cid, metadata_json, captured_at in graph.get("metadata_rows") or []:
        core.db(
            "INSERT INTO component_launch_metadata(component_id,metadata_json,captured_at) VALUES(?,?,?) "
            "ON CONFLICT(component_id) DO UPDATE SET metadata_json=excluded.metadata_json,captured_at=excluded.captured_at",
            (cid, metadata_json, captured_at),
        )
    for kind, complete, ids in (
        ("startup", graph.get("startup_complete") is True, graph.get("startup_ids") or []),
        ("task", graph.get("tasks_complete") is True, graph.get("task_ids") or []),
    ):
        if not complete:
            continue
        existing = core.db("SELECT component_id FROM component_catalog WHERE component_type=?", (kind,))
        seen = {str(value) for value in ids}
        stale = [str(row[0]) for row in existing if str(row[0]) not in seen]
        for offset in range(0, len(stale), 300):
            batch = stale[offset:offset + 300]
            marks = ",".join("?" for _ in batch)
            core.db(f"UPDATE component_catalog SET service_state='not_present' WHERE component_id IN ({marks})", tuple(batch))
            core.db(f"DELETE FROM component_relationships WHERE source_component_id IN ({marks})", tuple(batch))
        core.db(
            "DELETE FROM component_relationships WHERE relation_type='launches_binary' "
            "AND source_component_id IN (SELECT component_id FROM component_catalog WHERE component_type=?)",
            (kind,),
        )
    if graph.get("apps_complete") is True:
        core.db("DELETE FROM component_relationships WHERE relation_type='installed_under_app'")
    if graph.get("service_graph_complete") is True:
        core.db("DELETE FROM component_relationships WHERE relation_type='same_executable_as_service'")
    for batch in ci._chunks(graph.get("relationships") or [], 100):
        sql = (
            "INSERT INTO component_relationships(source_component_id,target_component_id,relation_type,confidence,evidence_json,observed_at) VALUES "
            + ",".join("(?,?,?,?,?,?)" for _ in batch)
            + " ON CONFLICT(source_component_id,target_component_id,relation_type) DO UPDATE SET "
            "confidence=excluded.confidence,evidence_json=excluded.evidence_json,observed_at=excluded.observed_at"
        )
        core.db(sql, tuple(value for row in batch for value in row))
    ci._save_state("launch_inventory", {
        "captured_at": float(graph.get("captured_at") or time.time()),
        "startup_count": len(graph.get("startup_ids") or []),
        "task_count": len(graph.get("task_ids") or []),
        "binary_count": len(graph.get("binary_paths") or {}),
        "startup_complete": bool(graph.get("startup_complete")),
        "tasks_complete": bool(graph.get("tasks_complete")),
        "apps_complete": bool(graph.get("apps_complete")),
        "service_graph_complete": bool(graph.get("service_graph_complete")),
        "task_truncated": bool(graph.get("task_truncated")),
        "source_health": graph.get("source_health") or {},
    })


def _component_rows(component_type: str, since: float, limit: int) -> list[dict[str, Any]]:
    rows = core.db(
        "SELECT component_id,name,binary_name,protected,source,start_mode,service_state,last_seen "
        "FROM component_catalog WHERE component_type=? AND last_seen>=? AND service_state<>'not_present' "
        "ORDER BY name COLLATE NOCASE LIMIT ?",
        (component_type, since, max(1, min(100, int(limit)))),
    )
    output = []
    for row in rows:
        cid = str(row[0])
        meta_rows = core.db("SELECT metadata_json FROM component_launch_metadata WHERE component_id=?", (cid,))
        try:
            metadata = json.loads(meta_rows[0][0] or "{}") if meta_rows else {}
        except (TypeError, ValueError):
            metadata = {}
        links = core.db(
            "SELECT r.target_component_id,r.relation_type,r.confidence,t.component_type,t.name,t.binary_name,"
            "t.publisher,t.product_name,t.file_version,t.signature_status,t.signer,t.protected "
            "FROM component_relationships r LEFT JOIN component_catalog t ON t.component_id=r.target_component_id "
            "WHERE r.source_component_id=? AND r.relation_type='launches_binary'",
            (cid,),
        )
        targets = []
        for link in links:
            binary_id = str(link[0])
            relations = core.db(
                "SELECT r.relation_type,r.confidence,t.component_type,t.name,t.publisher,t.signature_status,t.service_state,t.protected "
                "FROM component_relationships r LEFT JOIN component_catalog t ON t.component_id=r.target_component_id "
                "WHERE r.source_component_id=?",
                (binary_id,),
            )
            apps, services = [], []
            for rel in relations:
                detail = {"name": _clean(rel[3], 90), "publisher": _clean(rel[4], 90),
                          "confidence": str(rel[1]), "signature_status": _clean(rel[5], 24),
                          "state": _clean(rel[6], 24), "protected": bool(rel[7])}
                if rel[0] == "installed_under_app" and rel[2] == "app":
                    apps.append(detail)
                elif rel[0] == "same_executable_as_service" and rel[2] == "service":
                    services.append(detail)
            targets.append({
                "binary_name": _clean(link[5], 90), "publisher": _clean(link[6], 100),
                "product_name": _clean(link[7], 100), "file_version": _clean(link[8], 70),
                "signature_status": _clean(link[9], 24), "signer": _clean(link[10], 120),
                "protected": bool(link[11]), "confidence": str(link[2]),
                "application_matches": apps[:4], "service_matches": services[:8],
            })
        pref = core.db("SELECT preference,note,updated_at FROM component_preferences WHERE component_id=?", (cid,))
        preference = str(pref[0][0]) if pref else "unreviewed"
        note = _clean(pref[0][1], 140) if pref else ""
        updated = float(pref[0][2] or 0) if pref else 0.0
        if preference in ("keep", "not_needed"):
            continue
        if preference == "review_later" and time.time() - updated < 7 * 86400:
            continue
        output.append({
            "id": cid, "component_type": component_type, "name": _clean(row[1], 110),
            "binary_name": _clean(row[2], 90), "protected": bool(row[3]),
            "source": _clean(row[4], 80),
            "launch_kind": _clean(metadata.get("launch_kind") or row[5], 36),
            "state": _clean(row[6], 32), "last_seen": float(row[7] or 0),
            "metadata": metadata, "binary_targets": targets,
            "preference": preference, "operator_note": note,
            "requires_user_intent": True,
            "provenance_status": "verified_target" if any(t.get("signature_status") == "Valid" for t in targets)
                else ("target_resolved" if targets else "unresolved_target"),
            "recommendation": "Configured launch provenance only; it does not prove use, need or permission to disable.",
        })
    return output


def refresh(*, service_graph_ok: bool, service_rows: list[dict[str, Any]],
            inventory_data: dict[str, Any]) -> dict[str, Any]:
    """Collect, persist and return only a bounded transient signature path map."""
    ensure_schema()
    try:
        snapshot = _launch_inventory_query()
    except Exception as exc:
        return {"complete": False, "deferred": True,
                "reason": f"Startup/task query unavailable: {type(exc).__name__}",
                "summary": {}, "signature_paths": {}}
    health = inventory_data.get("health") if isinstance(inventory_data.get("health"), dict) else {}
    apps_health = health.get("apps") if isinstance(health.get("apps"), dict) else {}
    inv_ts = float(inventory_data.get("ts") or 0)
    snapshot["apps_complete"] = apps_health.get("ok") is True and inv_ts > 0 and time.time() - inv_ts <= 6 * 3600
    snapshot["service_graph_complete"] = bool(service_graph_ok)
    graph = _build_graph(
        snapshot, service_rows,
        inventory_data.get("apps") if isinstance(inventory_data.get("apps"), list) else [],
    )
    graph["task_truncated"] = bool(snapshot.get("task_truncated"))
    _persist_graph(graph)
    signature_paths = {}
    catalog_by_id = {row[0]: row for row in graph.get("catalog_rows", [])}
    for cid, executable in graph.get("binary_paths", {}).items():
        record = catalog_by_id.get(cid)
        if not record or bool(record[10]) or _is_windows_binary(executable):
            continue
        signature_paths[cid] = executable
    complete = all(graph.get(key) is True for key in (
        "startup_complete", "tasks_complete", "apps_complete", "service_graph_complete",
    ))
    summary = {
        "captured_at": graph.get("captured_at"),
        "startup_count": len(graph.get("startup_ids") or []),
        "task_count": len(graph.get("task_ids") or []),
        "binary_count": len(graph.get("binary_paths") or {}),
        "startup_complete": bool(graph.get("startup_complete")),
        "tasks_complete": bool(graph.get("tasks_complete")),
        "apps_complete": bool(graph.get("apps_complete")),
        "service_graph_complete": bool(graph.get("service_graph_complete")),
        "task_truncated": bool(snapshot.get("task_truncated")),
        "source_health": graph.get("source_health") or {},
    }
    return {
        "complete": complete, "deferred": not complete,
        "reason": "" if complete else "One or more startup/task/app/service provenance sources are incomplete; prior verified edges were retained.",
        "summary": summary, "signature_paths": signature_paths,
    }


def report(since: float) -> dict[str, Any]:
    ensure_schema()
    ci = _ci()
    state = ci._load_state("launch_inventory")
    return {
        "startup": _component_rows("startup", since, _MAX_UI_STARTUP),
        "tasks": _component_rows("task", since, _MAX_UI_TASKS),
        "coverage": {
            "captured_at": state.get("captured_at"),
            "startup_count": int(state.get("startup_count") or 0),
            "task_count": int(state.get("task_count") or 0),
            "binary_count": int(state.get("binary_count") or 0),
            "startup_complete": bool(state.get("startup_complete")),
            "tasks_complete": bool(state.get("tasks_complete")),
            "apps_complete": bool(state.get("apps_complete")),
            "service_graph_complete": bool(state.get("service_graph_complete")),
            "task_truncated": bool(state.get("task_truncated")),
            "source_health": state.get("source_health") if isinstance(state.get("source_health"), dict) else {},
        },
    }


def ai_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    ids, rows = [], []
    for key, prefix, limit in (
        ("startup_provenance", "component-startup.", 10),
        ("scheduled_task_provenance", "component-task.", 14),
    ):
        for index, item in enumerate(payload.get(key, [])[:limit]):
            evidence_id = prefix + str(index + 1)
            ids.append(evidence_id)
            binary_targets = []
            for target in (item.get("binary_targets") or [])[:3]:
                binary_targets.append({
                    "binary_name": _clean(target.get("binary_name"), 80),
                    "signature": _clean(target.get("signature_status"), 24),
                    "publisher": _clean(target.get("publisher"), 90),
                    "confidence": _clean(target.get("confidence"), 40),
                    "application_matches": [
                        {"name": _clean(match.get("name"), 80), "publisher": _clean(match.get("publisher"), 80),
                         "confidence": _clean(match.get("confidence"), 40)}
                        for match in (target.get("application_matches") or [])[:2]
                    ],
                    "service_matches": [
                        {"name": _clean(match.get("name"), 80), "publisher": _clean(match.get("publisher"), 80),
                         "signature": _clean(match.get("signature_status"), 24),
                         "state": _clean(match.get("state"), 24), "confidence": _clean(match.get("confidence"), 40)}
                        for match in (target.get("service_matches") or [])[:2]
                    ],
                })
            rows.append({
                "id": evidence_id, "component_type": _clean(item.get("component_type"), 16),
                "name": _clean(item.get("name"), 90), "source": _clean(item.get("source"), 70),
                "state": _clean(item.get("state"), 24),
                "enabled": bool((item.get("metadata") or {}).get("enabled")),
                "launch_kind": _clean(item.get("launch_kind") or "unresolved", 32),
                "run_level": _clean((item.get("metadata") or {}).get("run_level"), 20),
                "logon_type": _clean((item.get("metadata") or {}).get("logon_type"), 24),
                "action_count": int((item.get("metadata") or {}).get("action_count") or 0),
                "has_arguments": bool((item.get("metadata") or {}).get("has_arguments")),
                "provenance_status": _clean(item.get("provenance_status"), 28),
                "protected": bool(item.get("protected")),
                "operator_intent": _clean(item.get("preference"), 24),
                "operator_note": _clean(item.get("operator_note"), 100),
                "binary_targets": binary_targets,
            })
    return {"startup_and_task_provenance": rows, "component_evidence_ids": ids}


def select_signature_batch(paths_by_id: dict[str, str], maximum: int) -> list[tuple[str, str]]:
    """Rotate an Authenticode budget across process, service and startup/task binaries."""
    ci = _ci()
    maximum = max(1, min(64, int(maximum)))
    groups = {
        "process": sorted((key, value) for key, value in paths_by_id.items() if key.startswith("process:")),
        "service": sorted((key, value) for key, value in paths_by_id.items() if key.startswith("service:")),
        "binary": sorted((key, value) for key, value in paths_by_id.items() if key.startswith("binary:")),
    }
    state = ci._load_state("signature_rotation")
    quotas = {"process": maximum * 4 // 10, "service": maximum * 3 // 10}
    quotas["binary"] = maximum - quotas["process"] - quotas["service"]
    selected, used, offsets = [], set(), {}
    for kind in ("process", "service", "binary"):
        rows = groups[kind]
        if not rows:
            offsets[kind] = 0
            continue
        offset = int(state.get(kind) or 0) % len(rows)
        count = min(quotas[kind], len(rows))
        for step in range(count):
            item = rows[(offset + step) % len(rows)]
            selected.append(item); used.add(item[0])
        offsets[kind] = (offset + count) % len(rows)
    spare = max(0, maximum - len(selected))
    while spare:
        progressed = False
        for kind in ("process", "service", "binary"):
            rows = groups[kind]
            if not rows:
                continue
            offset = int(offsets.get(kind) or 0) % len(rows)
            for step in range(len(rows)):
                pos = (offset + step) % len(rows)
                item = rows[pos]
                if item[0] in used:
                    continue
                selected.append(item); used.add(item[0])
                offsets[kind] = (pos + 1) % len(rows)
                spare -= 1; progressed = True
                break
            if spare <= 0:
                break
        if not progressed:
            break
    ci._save_state("signature_rotation", {**offsets, "captured_at": time.time()})
    return selected[:maximum]
