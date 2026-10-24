"""Deterministic, explainable approval decisions for SENTINEL actions.

This engine never executes actions. It only classifies proposals; execution remains
behind safeguard checks, action snapshots, undo verification and rate limits.
"""
from __future__ import annotations

AUTO_MEDIUM_ALLOWLIST = frozenset({
    "game_profile_apply",
    "power_plan",
    "timer_resolution",
    "wifi_max_performance",
})

PRIORITY_BASE = {
    "etw_capture": 25, "wpr_trace": 25,
    "game_profile_apply": 55, "power_plan": 45,
    "timer_resolution": 35, "wifi_max_performance": 35,
    "pause_updater_service": 30,
    "flush_dns": 20, "trim_bg": 35, "bg_priority": 40,
    "terminate_process": 30,
}
MEDIUM_RISK_BASE = {
    "game_profile_apply": 35,
    "power_plan": 35,
    "timer_resolution": 30,
    "wifi_max_performance": 35,
    "pause_updater_service": 45,
}


def evaluate(
    kind: str,
    *,
    tier: str,
    preview: dict | None = None,
    safeguard: dict | None = None,
    auto_medium_enabled: bool = False,
    automation_enabled: bool = False,
    reversible: bool = False,
    measured_streak: int = 0,
) -> dict:
    """Return risk, priority, confidence and a policy-bound approval decision."""
    preview = preview if isinstance(preview, dict) else {}
    safeguard = safeguard if isinstance(safeguard, dict) else {"allowed": False}
    warnings = preview.get("warnings") if isinstance(preview.get("warnings"), list) else []
    supported = preview.get("supported") is True
    guard_ok = safeguard.get("allowed") is True

    if tier == "dangerous":
        risk = 100
    elif tier == "safe":
        risk = 8
    else:
        risk = MEDIUM_RISK_BASE.get(kind, 60)
        if reversible:
            risk -= 15
    risk = min(100, max(0, risk + min(20, len(warnings) * 4)))
    if not supported or not guard_ok:
        risk = 100

    confidence = 0.97 if supported and guard_ok else 0.0
    confidence = max(0.0, confidence - min(0.10, len(warnings) * 0.02))
    priority = PRIORITY_BASE.get(kind, 20)
    if any(word in " ".join(str(x) for x in warnings).casefold()
           for word in ("urgent", "critical", "degraded")):
        priority = min(100, priority + 20)

    blocked = tier == "dangerous" or not supported or not guard_ok
    eligible_medium = (
        tier == "medium"
        and kind in AUTO_MEDIUM_ALLOWLIST
        and reversible
        and auto_medium_enabled
        and automation_enabled
        and risk <= 25
        and confidence >= 0.92
        and int(measured_streak) >= 5
    )
    if blocked:
        decision, reason = "blocked", (
            "dangerous actions are permanently excluded from automatic approval"
            if tier == "dangerous" else
            "preview or safeguard checks did not pass; fail-closed"
        )
    elif tier == "medium" and eligible_medium:
        decision, reason = "auto_approved", "reversible allowlisted action passed the configured risk and confidence gates"
    elif tier == "safe":
        decision, reason = "policy_gated", "safe diagnostic action still requires its individual autopilot opt-in"
    else:
        decision = "manual_approval"
        if tier == "medium" and kind in AUTO_MEDIUM_ALLOWLIST and measured_streak < 5:
            reason = f"requires five consecutive measured improvements for this action and game ({max(0, int(measured_streak))}/5)"
        else:
            reason = "action requires explicit operator approval"

    return {
        "risk_score": int(risk),
        "priority_score": int(priority),
        "priority": "critical" if priority >= 80 else "high" if priority >= 60 else "normal" if priority >= 35 else "low",
        "confidence": round(confidence, 3),
        "decision": decision,
        "auto_approved": decision == "auto_approved",
        "reason": reason,
    }
