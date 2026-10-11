from aie.policy.execution_control import (
    ExecutionBlocked,
    ExecutionBudget,
    ExecutionControl,
)


def test_execution_control_fails_closed_by_default(tmp_path):
    control = ExecutionControl(
        enabled_path=tmp_path / "execution.enabled",
        kill_switch_path=tmp_path / "execution.kill",
    )

    status = control.status()
    assert status.enabled is False
    assert status.kill_switch_active is False
    assert status.mutation_allowed is False

    try:
        control.require_mutation_allowed()
    except ExecutionBlocked as exc:
        assert "disabled by default" in str(exc)
    else:
        raise AssertionError("expected fail-closed execution gate")


def test_kill_switch_overrides_enablement(tmp_path):
    control = ExecutionControl(
        enabled_path=tmp_path / "execution.enabled",
        kill_switch_path=tmp_path / "execution.kill",
    )
    control.set_enabled(True)
    control.set_kill_switch(True)

    assert control.status().mutation_allowed is False
    try:
        control.require_mutation_allowed()
    except ExecutionBlocked as exc:
        assert "kill switch" in str(exc)
    else:
        raise AssertionError("expected kill switch to block mutation")

    control.set_kill_switch(False)
    assert control.status().mutation_allowed is True


def test_execution_budget_rejects_privileged_or_unbounded_values():
    budget = ExecutionBudget(max_seconds=5, max_output_bytes=65_536, max_processes=2)
    assert budget.network_allowed is False
    assert budget.filesystem_write_allowed is False

    for kwargs in (
        {"max_seconds": 0.01},
        {"max_output_bytes": 9 * 1024 * 1024},
        {"max_processes": 17},
        {"privileged": True},
    ):
        try:
            ExecutionBudget(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid execution budget to be rejected")


def test_enable_marker_must_be_a_regular_file(tmp_path):
    enabled = tmp_path / "execution.enabled"
    kill = tmp_path / "execution.kill"
    enabled.mkdir()
    control = ExecutionControl(enabled_path=enabled, kill_switch_path=kill)

    assert control.status().enabled is False
    assert control.status().mutation_allowed is False
    try:
        control.require_mutation_allowed()
    except ExecutionBlocked as exc:
        assert "disabled by default" in str(exc)
    else:
        raise AssertionError("a directory must not enable execution")


def test_symlink_enable_marker_fails_closed_when_supported(tmp_path):
    enabled = tmp_path / "execution.enabled"
    kill = tmp_path / "execution.kill"
    target = tmp_path / "unrelated-file"
    target.write_text("not an execution marker", encoding="utf-8")
    try:
        enabled.symlink_to(target)
    except (OSError, NotImplementedError):
        import pytest

        pytest.skip("symlink creation is unavailable on this Windows runner")
    control = ExecutionControl(enabled_path=enabled, kill_switch_path=kill)

    assert control.status().enabled is False
    assert control.status().mutation_allowed is False


def test_any_kill_switch_file_type_blocks_mutation(tmp_path):
    enabled = tmp_path / "execution.enabled"
    kill = tmp_path / "execution.kill"
    control = ExecutionControl(enabled_path=enabled, kill_switch_path=kill)
    control.set_enabled(True)
    kill.mkdir()

    assert control.status().enabled is True
    assert control.status().kill_switch_active is True
    assert control.status().mutation_allowed is False
    try:
        control.require_mutation_allowed()
    except ExecutionBlocked as exc:
        assert "kill switch" in str(exc)
    else:
        raise AssertionError("a non-file kill-switch object must block mutation")
