"""Tests for the fixed per-action Windows elevation capability boundary."""
import os

import pytest

from sentinel import privilege_broker


def test_broker_has_finite_action_manifest_and_no_generic_executor():
    assert privilege_broker.ADMIN_ACTIONS == {
        "dns_set", "adapter_restart", "winsock_reset", "driver_install",
        "driver_rollback", "windows_repair", "service_restart", "trim_volume",
        "process_tune",
    }
    state = privilege_broker.status()
    assert state["execution_model"] == "per_action_uac"
    assert state["approval_required"] is True
    assert state["arbitrary_command_execution"] is False
    assert state["persistent_admin_token"] is False


def test_broker_rejects_invalid_job_ids_before_launch():
    if os.name != "nt":
        with pytest.raises(RuntimeError, match="Windows privilege broker"):
            privilege_broker.launch_privileged_job("not-a-job-id")
    else:
        with pytest.raises(ValueError, match="identifier"):
            privilege_broker.launch_privileged_job("not-a-job-id")
