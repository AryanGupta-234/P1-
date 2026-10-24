from sentinel.approval_engine import evaluate


def test_dangerous_actions_are_never_auto_approved():
    result = evaluate(
        "flush_dns",
        tier="dangerous",
        preview={"supported": True, "warnings": []},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
    )
    assert result["decision"] == "blocked"
    assert result["risk_score"] == 100
    assert result["auto_approved"] is False


def test_reversible_medium_action_can_auto_approve_with_all_gates():
    result = evaluate(
        "timer_resolution",
        tier="medium",
        preview={"supported": True, "warnings": ["process-scoped request"]},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
        measured_streak=5,
    )
    assert result["decision"] == "auto_approved"
    assert result["risk_score"] <= 25
    assert result["confidence"] >= 0.92


def test_global_automation_switch_is_required():
    result = evaluate(
        "game_profile_apply",
        tier="medium",
        preview={"supported": True, "warnings": []},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=False,
        reversible=True,
    )
    assert result["decision"] == "manual_approval"


def test_unknown_or_unsupported_proposals_fail_closed():
    result = evaluate(
        "power_plan",
        tier="medium",
        preview={"supported": False, "warnings": ["power plan unavailable"]},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
    )
    assert result["decision"] == "blocked"
    assert result["risk_score"] == 100


def test_safeguard_denial_cannot_be_overridden_by_approval_policy():
    result = evaluate(
        "wifi_max_performance",
        tier="medium",
        preview={"supported": True, "warnings": []},
        safeguard={"allowed": False, "reason": "protected session"},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
    )
    assert result["decision"] == "blocked"
    assert result["auto_approved"] is False


def test_non_allowlisted_medium_action_stays_manual():
    result = evaluate(
        "pause_updater_service",
        tier="medium",
        preview={"supported": True, "warnings": []},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
    )
    assert result["decision"] == "manual_approval"


def test_medium_auto_approval_requires_five_same_game_measured_wins():
    common = dict(
        kind="timer_resolution",
        tier="medium",
        preview={"supported": True, "warnings": ["process-scoped request"]},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
    )
    four = evaluate(**common, measured_streak=4)
    five = evaluate(**common, measured_streak=5)
    assert four["decision"] == "manual_approval"
    assert "4/5" in four["reason"]
    assert five["decision"] == "auto_approved"


def test_non_allowlisted_medium_action_never_auto_approves_even_with_streak():
    result = evaluate(
        "pause_updater_service",
        tier="medium",
        preview={"supported": True, "warnings": []},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
        measured_streak=10,
    )
    assert result["decision"] == "manual_approval"


def test_missing_learning_history_keeps_medium_action_manual():
    result = evaluate(
        "game_profile_apply",
        tier="medium",
        preview={"supported": True, "warnings": []},
        safeguard={"allowed": True},
        auto_medium_enabled=True,
        automation_enabled=True,
        reversible=True,
        measured_streak=0,
    )
    assert result["decision"] == "manual_approval"
    assert "0/5" in result["reason"]
