import json

import pytest

from aie.policy.permissions import CapabilityPermissionError, set_capability_enabled


def manifest(
    *,
    capability_id="windows.settings.open",
    enabled=False,
    approval_required=True,
    allow_autonomous=False,
):
    return {
        "capability_id": capability_id,
        "description": "Open a fixed Settings page.",
        "risk_tier": "low",
        "enabled": enabled,
        "allow_autonomous": allow_autonomous,
        "approval_required": approval_required,
        "allowed_parameters": ["setting"],
        "max_invocations_per_minute": 3,
        "max_execution_seconds": 5,
    }


def test_permission_enable_changes_only_enabled_field(tmp_path):
    path = tmp_path / "windows-settings-open.json"
    original = manifest()
    path.write_text(json.dumps(original), encoding="utf-8")

    updated = set_capability_enabled(
        tmp_path,
        "windows.settings.open",
        enabled=True,
        registered_capability_ids={"windows.settings.open"},
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert updated.enabled is True
    assert saved["enabled"] is True
    assert {key: value for key, value in saved.items() if key != "enabled"} == {
        key: value for key, value in original.items() if key != "enabled"
    }
    assert not (tmp_path / "windows-settings-open.json.tmp").exists()


def test_enable_requires_registered_adapter_and_approval_gates(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")

    with pytest.raises(CapabilityPermissionError, match="no application-registered"):
        set_capability_enabled(
            tmp_path,
            "windows.settings.open",
            enabled=True,
            registered_capability_ids=set(),
        )

    path.write_text(
        json.dumps(manifest(approval_required=False)),
        encoding="utf-8",
    )
    with pytest.raises(CapabilityPermissionError, match="approval_required"):
        set_capability_enabled(
            tmp_path,
            "windows.settings.open",
            enabled=True,
            registered_capability_ids={"windows.settings.open"},
        )

    path.write_text(
        json.dumps(manifest(allow_autonomous=True, approval_required=False)),
        encoding="utf-8",
    )
    with pytest.raises(CapabilityPermissionError, match="allow_autonomous=false"):
        set_capability_enabled(
            tmp_path,
            "windows.settings.open",
            enabled=True,
            registered_capability_ids={"windows.settings.open"},
        )


def test_permission_disable_does_not_need_registered_adapter(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(manifest(capability_id="future.capability", enabled=True)),
        encoding="utf-8",
    )
    updated = set_capability_enabled(
        tmp_path,
        "future.capability",
        enabled=False,
        registered_capability_ids=set(),
    )
    assert updated.enabled is False


def test_permission_change_rejects_duplicate_ids_and_symlinks(tmp_path):
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps(manifest()), encoding="utf-8")
    path_b.write_text(json.dumps(manifest()), encoding="utf-8")
    with pytest.raises(CapabilityPermissionError, match="duplicate capability ID"):
        set_capability_enabled(
            tmp_path,
            "windows.settings.open",
            enabled=False,
            registered_capability_ids=set(),
        )

    directory = tmp_path / "linked"
    try:
        directory.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(CapabilityPermissionError, match="directory cannot be a symlink"):
        set_capability_enabled(
            directory,
            "windows.settings.open",
            enabled=False,
            registered_capability_ids=set(),
        )
