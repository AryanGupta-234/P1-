"""Local Power Automate-style workflow engine for SENTINEL.

Flows are declarative records, not executable scripts. Triggers and actions are
closed allowlists; workflow data can never supply a command, path or Python code.
The first release supports event, schedule and sustained-metric triggers with
read-only/agent actions. Any maintenance write still uses the existing approval
and safeguard path and is intentionally not a workflow action in this module.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from . import core

_STARTED = False
_STOP = threading.Event()
_LOCK = threading.RLock()

TRIGGERS = frozenset({"event", "schedule", "metric"})
ACTIONS = frozenset({"local_ai_review", "read_only_diagnostics", "storage_scan", "notify_user"})
EVENT_CATEGORIES = frozenset({
    "application_crash", "hardware_error", "driver_error", "disk_error", "windows_update",
})
METRICS = {
    "cpu": (0.0, 100.0, "%"),
    "mem": (0.0, 100.0, "%"),
    "dlat": (0.0, 10000.0, "ms"),
    "ping": (0.0, 2000.0, "ms"),
    "gputemp": (0.0, 120.0, "°C"),
    "loss": (0.0, 100.0, "%"),
}
SCHEDULE_HOURS = frozenset({6, 12, 24, 48, 168})


def ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS automation_flows(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        trigger_type TEXT NOT NULL,
        trigger_json TEXT NOT NULL,
        action_type TEXT NOT NULL,
        action_json TEXT NOT NULL,
        cooldown_seconds INTEGER NOT NULL DEFAULT 1800,
        last_fired_at REAL NOT NULL DEFAULT 0,
        last_event_id INTEGER NOT NULL DEFAULT 0,
        consecutive_count INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS automation_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        flow_id INTEGER NOT NULL,
        trigger_at REAL NOT NULL,
        completed_at REAL NOT NULL,
        state TEXT NOT NULL,
        trigger_evidence_json TEXT NOT NULL,
        result_json TEXT NOT NULL)""")
    core.db("CREATE INDEX IF NOT EXISTS ix_automation_runs_flow ON automation_runs(flow_id,id DESC)")
    core.db("CREATE INDEX IF NOT EXISTS ix_automation_runs_time ON automation_runs(completed_at)")


ensure_schema()


def _json_object(raw: Any, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be an object")
    return raw


def _validate_trigger(kind: str, raw: Any) -> dict[str, Any]:
    data = _json_object(raw, "trigger")
    if kind == "event":
        if set(data) != {"category"} or data.get("category") not in EVENT_CATEGORIES:
            raise ValueError("event trigger category must be a supported Windows fault category")
        return {"category": data["category"]}
    if kind == "schedule":
        if set(data) != {"interval_hours"}:
            raise ValueError("schedule trigger requires interval_hours only")
        hours = data.get("interval_hours")
        if isinstance(hours, bool) or not isinstance(hours, int) or hours not in SCHEDULE_HOURS:
            raise ValueError("schedule interval must be 6, 12, 24, 48 or 168 hours")
        return {"interval_hours": hours}
    if kind == "metric":
        if set(data) != {"metric", "operator", "threshold", "consecutive_samples"}:
            raise ValueError("metric trigger requires metric, operator, threshold and consecutive_samples")
        metric = data.get("metric")
        if metric not in METRICS or data.get("operator") != "above":
            raise ValueError("metric trigger supports an allowlisted metric and the above operator")
        low, high, _unit = METRICS[metric]
        threshold = data.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not low < float(threshold) <= high:
            raise ValueError(f"threshold for {metric} must be greater than {low} and at most {high}")
        samples = data.get("consecutive_samples")
        if isinstance(samples, bool) or not isinstance(samples, int) or not 2 <= samples <= 20:
            raise ValueError("consecutive_samples must be an integer from 2 to 20")
        return {"metric": metric, "operator": "above", "threshold": float(threshold),
                "consecutive_samples": samples}
    raise ValueError("unsupported trigger type")


def _validate_action(kind: str, raw: Any) -> dict[str, Any]:
    data = _json_object(raw, "action")
    if kind in {"local_ai_review", "read_only_diagnostics", "storage_scan"}:
        if data:
            raise ValueError(f"{kind} takes no parameters")
        return {}
    if kind == "notify_user":
        if set(data) != {"message"}:
            raise ValueError("notify_user requires a message only")
        message = str(data.get("message") or "").strip()
        if not message or len(message) > 180:
            raise ValueError("notification message must contain 1 to 180 characters")
        return {"message": message}
    raise ValueError("unsupported action; arbitrary commands and scripts are not accepted")


def create_flow(payload: dict[str, Any]) -> dict[str, Any]:
    data = _json_object(payload, "flow")
    allowed = {"name", "enabled", "trigger_type", "trigger", "action_type", "action", "cooldown_minutes"}
    if set(data) - allowed:
        raise ValueError("flow contains unsupported fields")
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 80:
        raise ValueError("flow name must contain 1 to 80 characters")
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    trigger_type, action_type = data.get("trigger_type"), data.get("action_type")
    if trigger_type not in TRIGGERS:
        raise ValueError("unsupported trigger type")
    if action_type not in ACTIONS:
        raise ValueError("unsupported action type")
    trigger = _validate_trigger(trigger_type, data.get("trigger"))
    action = _validate_action(action_type, data.get("action", {}))
    cooldown = data.get("cooldown_minutes", 30)
    if isinstance(cooldown, bool) or not isinstance(cooldown, int) or not 5 <= cooldown <= 1440:
        raise ValueError("cooldown_minutes must be an integer from 5 to 1440")
    count = int(core.db("SELECT COUNT(*) FROM automation_flows")[0][0])
    if count >= 20:
        raise ValueError("at most 20 local workflows can be active or saved")
    now = time.time()
    latest_event = int(core.db("SELECT COALESCE(MAX(id),0) FROM events")[0][0]) if trigger_type == "event" else 0
    with _LOCK:
        flow_id = core.insert_id(
            "INSERT INTO automation_flows(name,enabled,trigger_type,trigger_json,action_type,action_json,"
            "cooldown_seconds,last_event_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (name, int(enabled), trigger_type, json.dumps(trigger, separators=(",", ":")),
             action_type, json.dumps(action, separators=(",", ":")), cooldown * 60, latest_event, now, now),
        )
    core.log("automation", "local workflow created", "info", flow_id=flow_id,
             trigger=trigger_type, action=action_type)
    return get_flow(flow_id)


def set_enabled(flow_id: int, enabled: bool) -> dict[str, Any]:
    if isinstance(flow_id, bool) or int(flow_id) <= 0 or not isinstance(enabled, bool):
        raise ValueError("flow id and enabled state are invalid")
    rows = core.db("SELECT id FROM automation_flows WHERE id=?", (int(flow_id),))
    if not rows:
        raise ValueError("workflow not found")
    now = time.time()
    if enabled:
        latest_event = int(core.db("SELECT COALESCE(MAX(id),0) FROM events")[0][0])
        core.db("UPDATE automation_flows SET enabled=1,last_event_id=?,last_fired_at=?,consecutive_count=0,updated_at=? WHERE id=?",
                (latest_event, now, now, int(flow_id)))
    else:
        core.db("UPDATE automation_flows SET enabled=0,consecutive_count=0,updated_at=? WHERE id=?",
                (now, int(flow_id)))
    return get_flow(int(flow_id))


def delete_flow(flow_id: int) -> dict[str, Any]:
    if isinstance(flow_id, bool) or int(flow_id) <= 0:
        raise ValueError("flow id must be positive")
    rows = core.db("SELECT id FROM automation_flows WHERE id=?", (int(flow_id),))
    if not rows:
        raise ValueError("workflow not found")
    core.db("DELETE FROM automation_flows WHERE id=?", (int(flow_id),))
    core.db("DELETE FROM automation_runs WHERE flow_id=?", (int(flow_id),))
    core.log("automation", "local workflow deleted", "info", flow_id=int(flow_id))
    return {"ok": True, "id": int(flow_id)}


def _decode_flow(row: tuple) -> dict[str, Any]:
    return {
        "id": int(row[0]), "name": str(row[1]), "enabled": bool(row[2]),
        "trigger_type": row[3], "trigger": json.loads(row[4] or "{}"),
        "action_type": row[5], "action": json.loads(row[6] or "{}"),
        "cooldown_minutes": int(row[7]) // 60, "last_fired_at": float(row[8] or 0),
        "last_event_id": int(row[9] or 0), "consecutive_count": int(row[10] or 0),
        "created_at": float(row[11] or 0), "updated_at": float(row[12] or 0),
    }


def get_flow(flow_id: int) -> dict[str, Any]:
    rows = core.db(
        "SELECT id,name,enabled,trigger_type,trigger_json,action_type,action_json,cooldown_seconds,"
        "last_fired_at,last_event_id,consecutive_count,created_at,updated_at "
        "FROM automation_flows WHERE id=?", (int(flow_id),)
    )
    if not rows:
        raise ValueError("workflow not found")
    result = _decode_flow(rows[0])
    result["latest_run"] = _latest_run(int(flow_id))
    return result


def _latest_run(flow_id: int) -> dict[str, Any] | None:
    rows = core.db(
        "SELECT id,trigger_at,completed_at,state,trigger_evidence_json,result_json "
        "FROM automation_runs WHERE flow_id=? ORDER BY id DESC LIMIT 1", (flow_id,)
    )
    if not rows:
        return None
    row = rows[0]
    try:
        evidence, result = json.loads(row[4] or "{}"), json.loads(row[5] or "{}")
    except (TypeError, ValueError):
        evidence, result = {}, {}
    return {"id": int(row[0]), "triggered_at": float(row[1]), "completed_at": float(row[2]),
            "state": row[3], "evidence": evidence, "result": result}


def list_flows() -> dict[str, Any]:
    rows = core.db(
        "SELECT id,name,enabled,trigger_type,trigger_json,action_type,action_json,cooldown_seconds,"
        "last_fired_at,last_event_id,consecutive_count,created_at,updated_at "
        "FROM automation_flows ORDER BY id DESC LIMIT 100"
    )
    flows = []
    for row in rows:
        item = _decode_flow(row)
        item["latest_run"] = _latest_run(item["id"])
        flows.append(item)
    run_count = int(core.db("SELECT COUNT(*) FROM automation_runs WHERE completed_at>=?",
                            (time.time() - 7 * 86400,))[0][0])
    return {"flows": flows, "count": len(flows), "runs_7d": run_count,
            "available_triggers": sorted(TRIGGERS), "available_actions": sorted(ACTIONS),
            "execution_boundary": "fixed local actions only; maintenance mutations require separate preview and approval"}


def _event_category(source: str, message: str) -> str | None:
    text = (source + " " + message).casefold()
    if (any(token in text for token in ("application error", "application hang", "windows error reporting", "bugcheck", ".net runtime failure"))
            or re.search(r"\b(?:event\s*id|eventid)\s*[:=]?\s*(?:1000|1001|1002|1026)\b", text)):
        return "application_crash"
    if any(token in text for token in ("whea", "hardware error", "machine check", "kernel-power", "unexpected shutdown", "unexpected restart")):
        return "hardware_error"
    if any(token in text for token in ("kernel-pnp", "windowsupdateclient", "driver install", "device cannot start", "driver failure", "display driver", "nvlddmkm", "amdkmdag", "gpu driver reset", "tdr")):
        return "driver_error" if any(token in text for token in ("pnp", "driver", "device cannot start", "display", "nvlddmkm", "amdkmdag", "tdr")) else "windows_update"
    if any(token in text for token in ("disk error", "ntfs", "stornvme", "storahci", "microsoft-windows-disk", "disk/storage", "bad block")):
        return "disk_error"
    if "windowsupdateclient" in text or "windows update" in text:
        return "windows_update"
    return None


def _execute_action(action_type: str, action: dict[str, Any]) -> dict[str, Any]:
    if action_type == "local_ai_review":
        from . import agent_assist
        return agent_assist.request_system_review()
    if action_type == "read_only_diagnostics":
        from . import maintenance
        report = maintenance.status(refresh=True)
        return {"accepted": report.get("diagnostics_state") == "refreshing",
                "state": report.get("diagnostics_state"), "read_only": True}
    if action_type == "storage_scan":
        from . import storage_intelligence
        return storage_intelligence.request_scan()
    if action_type == "notify_user":
        from . import agent_assist
        notification_id = agent_assist.create_notification(
            "automation", action.get("message", "SENTINEL workflow notification"),
            severity="normal", evidence={"source": "user-configured local workflow"},
        )
        return {"accepted": notification_id is not None, "notification_id": notification_id}
    raise ValueError("unsupported workflow action")


def _record_run(flow_id: int, state: str, evidence: dict[str, Any], result: dict[str, Any]) -> None:
    now = time.time()
    core.db(
        "INSERT INTO automation_runs(flow_id,trigger_at,completed_at,state,trigger_evidence_json,result_json) "
        "VALUES(?,?,?,?,?,?)",
        (flow_id, now, now, state, json.dumps(evidence, ensure_ascii=False, default=str)[:4000],
         json.dumps(result, ensure_ascii=False, default=str)[:4000]),
    )
    core.db("DELETE FROM automation_runs WHERE flow_id=? AND id NOT IN "
            "(SELECT id FROM automation_runs WHERE flow_id=? ORDER BY id DESC LIMIT 100)",
            (flow_id, flow_id))


def _run_flow(flow: dict[str, Any], evidence: dict[str, Any]) -> bool:
    now = time.time()
    if now - flow["last_fired_at"] < flow["cooldown_minutes"] * 60:
        return False
    try:
        result = _execute_action(flow["action_type"], flow["action"])
        accepted = result.get("accepted", result.get("queued", True)) is not False
        state = "complete" if accepted else "deferred"
        _record_run(flow["id"], state, evidence, result)
        core.db("UPDATE automation_flows SET last_fired_at=?,updated_at=? WHERE id=?",
                (now, now, flow["id"]))
        return accepted
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        _record_run(flow["id"], "failed", evidence, result)
        core.db("UPDATE automation_flows SET last_fired_at=?,updated_at=? WHERE id=?",
                (now, now, flow["id"]))
        core.log("automation", "workflow action failed", "warn", flow_id=flow["id"],
                 action=flow["action_type"], error=result["error"])
        return False


def _tick_flow(flow: dict[str, Any], now: float) -> bool:
    if not flow["enabled"]:
        return False
    trigger = flow["trigger"]
    if flow["trigger_type"] == "schedule":
        interval = int(trigger["interval_hours"]) * 3600
        if now - max(flow["last_fired_at"], flow["created_at"]) >= interval:
            return _run_flow(flow, {"trigger": "schedule", "interval_hours": trigger["interval_hours"]})
        return False
    if flow["trigger_type"] == "metric":
        metric = trigger["metric"]
        current = core.LIVE.get(metric)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            core.db("UPDATE automation_flows SET consecutive_count=0 WHERE id=?", (flow["id"],))
            return False
        count = min(int(trigger["consecutive_samples"]), flow["consecutive_count"] + 1) if float(current) > float(trigger["threshold"]) else 0
        core.db("UPDATE automation_flows SET consecutive_count=? WHERE id=?", (count, flow["id"]))
        if count >= int(trigger["consecutive_samples"]):
            accepted = _run_flow(flow, {"trigger": "metric", "metric": metric, "value": current,
                                        "threshold": trigger["threshold"], "samples": count})
            if accepted:
                core.db("UPDATE automation_flows SET consecutive_count=0 WHERE id=?", (flow["id"],))
            return accepted
        return False
    rows = core.db(
        "SELECT id,ts,level,src,msg FROM events WHERE id>? ORDER BY id ASC LIMIT 200",
        (flow["last_event_id"],)
    )
    if not rows:
        return False
    for row in rows:
        category = _event_category(str(row[3] or ""), str(row[4] or ""))
        if category == trigger["category"]:
            result = _run_flow(flow, {"trigger": "event", "category": category,
                                      "event_id": int(row[0]), "occurred_at": float(row[1]),
                                      "severity": str(row[2] or ""), "source": str(row[3] or "")[:80],
                                      "summary": str(row[4] or "")[:180]})
            if result:
                core.db("UPDATE automation_flows SET last_event_id=? WHERE id=?", (int(row[0]), flow["id"]))
            return result
    core.db("UPDATE automation_flows SET last_event_id=? WHERE id=?", (int(rows[-1][0]), flow["id"]))
    return False


def tick() -> int:
    """Evaluate each saved local flow using current state; process at most 20 flows."""
    now = time.time()
    rows = core.db(
        "SELECT id,name,enabled,trigger_type,trigger_json,action_type,action_json,cooldown_seconds,"
        "last_fired_at,last_event_id,consecutive_count,created_at,updated_at "
        "FROM automation_flows ORDER BY id ASC LIMIT 20"
    )
    started = 0
    for row in rows:
        try:
            flow = _decode_flow(row)
            if _tick_flow(flow, now):
                started += 1
        except Exception as exc:
            core.log("automation", f"workflow evaluation failed: {type(exc).__name__}: {str(exc)[:180]}",
                     "warn", flow_id=int(row[0]))
    core.heartbeat("local workflow automation", 30, f"{len(rows)} flows · {started} actions started")
    return started


def _loop() -> None:
    ensure_schema()
    while not _STOP.is_set():
        try:
            tick()
            core.db("DELETE FROM automation_runs WHERE completed_at<?", (time.time() - 90 * 86400,))
        except Exception as exc:
            core.log("automation", f"workflow cycle failed: {type(exc).__name__}: {str(exc)[:160]}", "warn")
        _STOP.wait(30)


_THREAD: threading.Thread | None = None


def start() -> None:
    global _STARTED, _THREAD
    if _STARTED:
        return
    ensure_schema()
    _STOP.clear()
    _STARTED = True
    _THREAD = threading.Thread(target=_loop, name="local-workflow-automation", daemon=True)
    _THREAD.start()


def shutdown() -> None:
    _STOP.set()
    if _THREAD and _THREAD.is_alive():
        _THREAD.join(timeout=3.0)
