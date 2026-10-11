import json
import re

from typer.testing import CliRunner

from aie import cli
from aie.policy.ledger import PolicyLedger
from aie.policy.models import CapabilityManifest


def runner_with_paths(tmp_path, monkeypatch):
    manifest_dir = tmp_path / "capabilities"
    manifest_dir.mkdir()
    audit_path = tmp_path / "policy-audit.sqlite3"
    monkeypatch.setattr(cli, "capability_manifest_dir", lambda: manifest_dir)
    monkeypatch.setattr(cli, "policy_audit_database_path", lambda: audit_path)
    return CliRunner(), manifest_dir, audit_path


def test_propose_and_approve_cli_records_user_review_without_execution(tmp_path, monkeypatch):
    runner, manifest_dir, audit_path = runner_with_paths(tmp_path, monkeypatch)
    manifest = CapabilityManifest(
        capability_id="windows.open_settings",
        description="Open a named Windows Settings page.",
        risk_tier="low",
        enabled=True,
        approval_required=True,
        allowed_parameters=frozenset({"settings_page"}),
    )
    (manifest_dir / "open-settings.json").write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )

    proposed = runner.invoke(
        cli.app,
        [
            "propose",
            "windows.open_settings",
            "Open display settings",
            "--parameters",
            '{"settings_page":"display"}',
        ],
    )
    assert proposed.exit_code == 0, proposed.output
    assert "pending_review" in proposed.output
    match = re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,}", proposed.output)
    assert match is not None
    proposal_id = match.group(0)

    listed = runner.invoke(cli.app, ["proposals"])
    assert listed.exit_code == 0, listed.output
    assert proposal_id in listed.output

    approved = runner.invoke(cli.app, ["approve-proposal", proposal_id])
    assert approved.exit_code == 0, approved.output
    assert "approved" in approved.output
    assert "no action was performed" in approved.output.lower()

    ledger = PolicyLedger(audit_path)
    snapshot = ledger.get(proposal_id)
    assert snapshot is not None
    assert snapshot.status == "approved"
    assert snapshot.action_executed is False
    assert len(ledger.audit_trail(proposal_id)) == 2


def test_unknown_capability_cli_proposal_is_blocked(tmp_path, monkeypatch):
    runner, _, audit_path = runner_with_paths(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app,
        ["propose", "unknown.capability", "Unknown requested action"],
    )

    assert result.exit_code == 0, result.output
    assert "blocked" in result.output
    assert "default deny" in result.output.lower()
    assert PolicyLedger(audit_path).list(status="blocked")


def test_remote_memory_context_requires_a_second_egress_confirmation():
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "ask",
            "Explain this request",
            "--provider",
            "cloud",
            "--allow-cloud-egress",
            "--with-memory",
        ],
    )

    assert result.exit_code == 2
    assert "--confirm-memory-egress" in result.output


def test_sensitive_memory_context_is_never_sent_to_remote_provider():
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "ask",
            "Explain this request",
            "--provider",
            "cloud",
            "--allow-cloud-egress",
            "--with-memory",
            "--include-sensitive-memory",
            "--confirm-memory-egress",
        ],
    )

    assert result.exit_code == 2
    assert "Sensitive memories cannot be attached" in result.output
