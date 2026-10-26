"""Agent-owned proactive diagnosis and durable follow-up.

The worker consumes SENTINEL's existing event/insight stream. It creates bounded,
evidence-linked questions and suggestions; it never executes a repair. Notifications
are persisted before delivery so the HUD is only a viewer/configuration surface.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from typing import Any

from . import core

_STARTED = False
_STOP = __import__("threading").Event()

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "ask_follow_up_questions": True,
    "agent_notifications": True,
    "suppress_during_games": True,
    "max_notifications_per_hour": 4,
    "dedupe_cooldown_minutes": 60,
}


def ensure_schema() -> None:
    core.db("""CREATE TABLE IF NOT EXISTS agent_assist_settings(
        setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at REAL NOT NULL)""")
    core.db("""CREATE TABLE IF NOT EXISTS agent_notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
        category TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
        explanation TEXT NOT NULL, question TEXT NOT NULL, suggested_fix TEXT NOT NULL,
        evidence_json TEXT NOT NULL, dedupe_key TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open',
        user_response TEXT NOT NULL DEFAULT '', delivered_at REAL, resolved_at REAL)""")
    core.db("CREATE INDEX IF NOT EXISTS ix_agent_notifications_created ON agent_notifications(created_at)")
    core.db("CREATE INDEX IF NOT EXISTS ix_agent_notifications_dedupe ON agent_notifications(dedupe_key,created_at)")
    core.db("""CREATE TABLE IF NOT EXISTS agent_assist_cursors(
        cursor_key TEXT PRIMARY KEY, last_id INTEGER NOT NULL DEFAULT 0)""")
    core.db("""CREATE TABLE IF NOT EXISTS agent_assist_feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT, notification_id INTEGER NOT NULL,
        created_at REAL NOT NULL, response TEXT NOT NULL)""")


ensure_schema()


def settings() -> dict[str, Any]:
    values = dict(DEFAULTS)
    for key, raw in core.db("SELECT setting_key,value_json FROM agent_assist_settings"):
        if key in DEFAULTS:
            try:
                values[key] = json.loads(raw)
            except (TypeError, ValueError):
                continue
    return values


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("settings payload must be an object")
    current = settings()
    updated = dict(current)
    for key, value in payload.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown agent-assist setting: {key}")
        if key in ("enabled", "ask_follow_up_questions", "agent_notifications", "suppress_during_games"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        elif key == "max_notifications_per_hour":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
                raise ValueError("max_notifications_per_hour must be an integer from 1 to 12")
        elif key == "dedupe_cooldown_minutes":
            if isinstance(value, bool) or not isinstance(value, int) or not 10 <= value <= 1440:
                raise ValueError("dedupe_cooldown_minutes must be an integer from 10 to 1440")
        updated[key] = value
    now = time.time()
    for key, value in updated.items():
        if current.get(key) != value or core.db(
            "SELECT 1 FROM agent_assist_settings WHERE setting_key=?", (key,)
        ) == []:
            core.db(
                "INSERT INTO agent_assist_settings(setting_key,value_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, json.dumps(value, separators=(",", ":")), now),
            )
    core.log("agent-assist", "persistent proactive-agent settings updated", "info",
             changed_keys=sorted(payload.keys()))
    return settings()


def _clean(value: Any, limit: int = 360) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit]


def _classify(source: str, message: str, severity: str) -> dict[str, str]:
    text = (source + " " + message).casefold()
    if any(word in text for word in ("code 10", "cm_prob_failed_start", "device cannot start", "driver failed", "driver error", "driver start")):
        return {
            "category": "driver",
            "title": "Device or driver start failure",
            "explanation": "Windows reported that a device or driver did not start correctly. The event is a diagnostic signal, not proof that the driver itself is the only cause.",
            "question": "Which device is affected, and did this begin after a Windows or driver update?",
            "fix": "Check the exact Device Manager problem code, device instance, driver provider and version. Prefer the device manufacturer's signed driver; do not remove the current driver until a recovery path is available.",
        }
    if any(word in text for word in ("no internet", "network disconnected", "wifi", "wi-fi", "dns", "winsock", "network adapter", "network interface")):
        return {
            "category": "network",
            "title": "Network connectivity needs diagnosis",
            "explanation": "A network-related warning or failure was recorded. The next step is to distinguish adapter, DHCP, DNS and application-level failure.",
            "question": "Is the network missing entirely, connected with no internet, or failing only in one application?",
            "fix": "Compare adapter state, IP configuration, default gateway and DNS resolution first. Keep the adapter and network stack unchanged until the failing layer is identified.",
        }
    if any(word in text for word in ("disk full", "low disk", "storage pressure", "space available", "free space")):
        return {
            "category": "storage",
            "title": "Storage capacity pressure detected",
            "explanation": "The available evidence points to low free space. A usage-aware scan can identify large package caches, build outputs, downloads and hidden files for review.",
            "question": "Which drive is affected, and should the review focus on developer caches, downloads or general large files?",
            "fix": "Review the largest paths and their age/usage signals first. SENTINEL will suggest candidates only; it will not delete files or uninstall packages automatically.",
        }
    if any(word in text for word in ("service failed", "service start", "scm", "service error")):
        return {
            "category": "service",
            "title": "Windows service reported a problem",
            "explanation": "A service-related event was observed. A failed dependency, disabled startup type or service-account issue may be involved.",
            "question": "Which application or device stopped working when this service warning appeared?",
            "fix": "Inspect the service state, startup type, dependency chain and matching Service Control Manager events. Do not disable or force-stop related services as a first response.",
        }
    if any(word in text for word in ("readonly database", "read-only database", "database is locked", "sqlite", "permission denied")):
        return {
            "category": "agent-storage",
            "title": "Agent persistence or file-access warning",
            "explanation": "A component reported a database or file-access problem. The database path and Windows account permissions should be checked before any data is moved.",
            "question": "Did this happen after moving the installation, changing Windows permissions or running another Sentinel instance?",
            "fix": "Verify the active SENTINEL_HOME/ProgramData path, file owner and directory write permission. Keep the database and WAL files together; do not delete SQLite sidecar files while the agent is running.",
        }
    if any(word in text for word in ("ollama", "model unavailable", "inference", "llm", "embedding")):
        return {
            "category": "ai-runtime",
            "title": "Local AI runtime needs attention",
            "explanation": "The local inference or model path reported a problem. This does not affect deterministic monitoring and safeguards.",
            "question": "Is the local model service stopped, or is only one model unavailable?",
            "fix": "Check the local inference service, model inventory and available memory. Let the adaptive runtime defer deep inference under load; do not pull or switch models automatically.",
        }
    if any(word in text for word in ("sensor endpoint", "hardware provider", "librehardwaremonitor", "sensor unavailable")):
        return {
            "category": "hardware-sensors",
            "title": "Hardware sensor provider is unavailable",
            "explanation": "A hardware-sensor endpoint or provider did not return the expected data. Missing sensor readings are kept as unknown rather than fabricated.",
            "question": "Is the sensor provider application open, and does its local endpoint respond?",
            "fix": "Check the provider process, configured loopback port and sensor permissions. Keep core telemetry active; the agent will not install drivers or alter firmware to recover sensors.",
        }
    if any(word in text for word in ("crash", "unhandled exception", "access violation", "application fault", "terminated unexpectedly")):
        return {
            "category": "application",
            "title": "Application failure signal observed",
            "explanation": "The event resembles an application crash or unexpected termination. The faulting module and event timestamp are needed to separate app, driver and dependency causes.",
            "question": "Which application stopped, and what were you doing immediately before it failed?",
            "fix": "Capture the matching Application Error / Windows Error Reporting entry and faulting module. Check for a recent app or driver update before reinstalling anything.",
        }
    return {
        "category": "system",
        "title": "New system issue needs one detail",
        "explanation": "SENTINEL observed a warning or error without enough evidence to identify a reliable root cause. The event is retained so the next diagnostic can correlate it with process, network, service and hardware state.",
        "question": "What did you notice at that moment: a freeze, an app failure, a network problem, a device issue or something else?",
        "fix": "Check the event timestamp against the live process, service and hardware inventory. Avoid broad cleanup, driver replacement or service changes until the symptom is narrowed down.",
    }


def _runtime_suppressed(config: dict[str, Any]) -> bool:
    if not config.get("suppress_during_games", True):
        return False
    try:
        from . import runtime_engine
        return runtime_engine.snapshot().get("mode") in ("game_optimized", "valorant_guarded")
    except Exception:
        return False


def _agent_toast(title: str, body: str) -> bool:
    """Deliver a lightweight native tray balloon from the agent on Windows.

    The durable queue remains authoritative if PowerShell/WinForms is unavailable.
    """
    if os.name != "nt":
        return False
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n=New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
        f"$n.BalloonTipTitle='{title.replace(chr(39), chr(39)*2)}'; "
        f"$n.BalloonTipText='{body.replace(chr(39), chr(39)*2)}'; "
        "$n.ShowBalloonTip(5000); Start-Sleep -Seconds 6; $n.Dispose()"
    )
    try:
        encoded = __import__("base64").b64encode(script.encode("utf-16le")).decode("ascii")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
        return True
    except Exception:
        return False


def create_notification(source: str, message: str, severity: str = "warn",
                        evidence: dict[str, Any] | None = None) -> int | None:
    config = settings()
    if not config.get("enabled") or not config.get("agent_notifications"):
        return None
    source_text, message_text = _clean(source, 80), _clean(message, 360)
    diagnosis = _classify(source_text, message_text, severity)
    normalized = " ".join((diagnosis["category"] + " " + message_text).casefold().split())[:180]
    dedupe_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    cooldown = max(600, int(config.get("dedupe_cooldown_minutes", 60)) * 60)
    previous = core.db(
        "SELECT id FROM agent_notifications WHERE dedupe_key=? AND created_at>=? ORDER BY id DESC LIMIT 1",
        (dedupe_key, time.time() - cooldown),
    )
    if previous:
        return None
    sent = core.db("SELECT COUNT(*) FROM agent_notifications WHERE created_at>=?",
                   (time.time() - 3600,))[0][0]
    if int(sent) >= int(config.get("max_notifications_per_hour", 4)):
        return None
    question = diagnosis["question"] if config.get("ask_follow_up_questions") else ""
    safe_evidence = evidence if isinstance(evidence, dict) else {}
    safe_evidence = {str(k)[:40]: _clean(v, 180) for k, v in list(safe_evidence.items())[:8]}
    now = time.time()
    notification_id = core.insert_id(
        "INSERT INTO agent_notifications(created_at,category,severity,title,explanation,question,suggested_fix,"
        "evidence_json,dedupe_key,state) VALUES(?,?,?,?,?,?,?,?,?,'open')",
        (now, diagnosis["category"], "high" if str(severity).casefold() == "error" else "normal",
         diagnosis["title"], diagnosis["explanation"], question, diagnosis["fix"],
         json.dumps(safe_evidence, ensure_ascii=False), dedupe_key),
    )
    row = {"id": notification_id, "created_at": now, **diagnosis,
           "severity": "high" if str(severity).casefold() == "error" else "normal",
           "question": question, "evidence": safe_evidence}
    core.publish("agent_notification", row)
    if not _runtime_suppressed(config):
        delivered = _agent_toast(row["title"], row["question"] or row["suggested_fix"][:180])
        if delivered:
            core.db("UPDATE agent_notifications SET delivered_at=? WHERE id=?", (time.time(), notification_id))
    return notification_id


def notifications(limit: int = 20) -> list[dict[str, Any]]:
    limit = min(100, max(1, int(limit)))
    rows = core.db(
        "SELECT id,created_at,category,severity,title,explanation,question,suggested_fix,evidence_json,state,user_response,delivered_at "
        "FROM agent_notifications WHERE state='open' ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for row in rows:
        try:
            evidence = json.loads(row[8] or "{}")
        except ValueError:
            evidence = {}
        out.append(dict(zip(("id","created_at","category","severity","title","explanation","question",
                             "suggested_fix","_evidence","state","user_response","delivered_at"), row)) |
                   {"evidence": evidence})
    return out


def respond(notification_id: int, answer: str, dismiss: bool = False) -> dict[str, Any]:
    if isinstance(notification_id, bool) or int(notification_id) <= 0:
        raise ValueError("notification_id must be a positive integer")
    answer = _clean(answer, 1200)
    if not dismiss and not answer:
        raise ValueError("enter a short answer or dismiss the question")
    state = "dismissed" if dismiss else "answered"
    now = time.time()
    rows = core.db("SELECT id FROM agent_notifications WHERE id=? AND state='open'", (int(notification_id),))
    if not rows:
        raise ValueError("notification is no longer open")
    core.db("UPDATE agent_notifications SET state=?,user_response=?,resolved_at=? WHERE id=?",
            (state, answer, now, int(notification_id)))
    if answer:
        core.db("INSERT INTO agent_assist_feedback(notification_id,created_at,response) VALUES(?,?,?)",
                (int(notification_id), now, answer))
    core.publish("agent_notification_resolved", {"id": int(notification_id), "state": state})
    return {"ok": True, "id": int(notification_id), "state": state}


def status() -> dict[str, Any]:
    open_count = int(core.db("SELECT COUNT(*) FROM agent_notifications WHERE state='open'")[0][0])
    answered_count = int(core.db("SELECT COUNT(*) FROM agent_assist_feedback")[0][0])
    latest = core.db("SELECT MAX(created_at) FROM agent_notifications")[0][0]
    return {"settings": settings(), "open_notifications": open_count,
            "answered_questions": answered_count, "last_trigger_at": latest,
            "engine": "agent-owned", "repairs_executed": 0}


def _advance_cursor(key: str, value: int) -> None:
    core.db("INSERT INTO agent_assist_cursors(cursor_key,last_id) VALUES(?,?) "
            "ON CONFLICT(cursor_key) DO UPDATE SET last_id=MAX(last_id,excluded.last_id)",
            (key, int(value)))


def _process_new_events() -> None:
    config = settings()
    if not config.get("enabled"):
        return
    for key, table, fields in (
        ("events", "events", "id,ts,level,src,msg,data"),
        ("insights", "insights", "id,ts,sev,key,title,detail,culprit"),
    ):
        cursor_rows = core.db("SELECT last_id FROM agent_assist_cursors WHERE cursor_key=?", (key,))
        if not cursor_rows:
            latest = core.db(f"SELECT COALESCE(MAX(id),0) FROM {table}")[0][0]
            _advance_cursor(key, int(latest or 0))
            continue
        last_id = int(cursor_rows[0][0])
        rows = core.db(f"SELECT {fields} FROM {table} WHERE id>? ORDER BY id ASC LIMIT 100", (last_id,))
        if not rows:
            continue
        max_id = last_id
        for row in rows:
            row_id = int(row[0])
            max_id = max(max_id, row_id)
            if key == "events":
                _, ts, level, source, message, raw_data = row
                severity = str(level or "info").casefold()
                evidence = {"event_id": row_id, "timestamp": ts, "source": source, "level": severity}
                if severity not in ("warn", "warning", "error", "critical"):
                    continue
                if str(source or "").casefold() in ("agent-assist", "storage-intelligence"):
                    continue
                create_notification(str(source or "system"), str(message or ""), severity, evidence)
            else:
                _, ts, severity, key_name, title, detail, culprit = row
                level = "error" if str(severity).casefold() in ("high", "critical", "error") else "warn"
                evidence = {"insight_id": row_id, "timestamp": ts, "insight_key": key_name,
                            "culprit": culprit, "detail": _clean(detail, 180)}
                create_notification(str(key_name or "insight"), str(title or "") + " " + str(detail or ""), level, evidence)
        _advance_cursor(key, max_id)


def _loop() -> None:
    while not _STOP.is_set():
        try:
            _process_new_events()
            core.heartbeat("proactive agent assistant", 15, f"{status()['open_notifications']} open review item(s)")
            # Keep SQLite history bounded without discarding unresolved or answered context.
            core.db("DELETE FROM agent_notifications WHERE state IN ('dismissed','answered') AND created_at<?",
                    (time.time() - 90 * 86400,))
            core.db("DELETE FROM agent_assist_feedback WHERE created_at<?", (time.time() - 365 * 86400,))
        except Exception as exc:
            core.log("agent-assist", f"proactive diagnosis cycle failed: {type(exc).__name__}: {_clean(exc,160)}", "warn")
        _STOP.wait(15)


def start() -> None:
    global _STARTED
    if _STARTED:
        return
    ensure_schema()
    _STOP.clear()
    _STARTED = True
    core.thread(_loop, "proactive-agent-assistant")


def shutdown() -> None:
    _STOP.set()
