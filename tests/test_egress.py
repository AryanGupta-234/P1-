from aie.egress import (
    RemoteEgressAuditStore,
    RemoteEgressContext,
    RemoteEgressDenied,
    RemoteEgressGateway,
)
from aie.models.base import ChatMessage, ModelRequest


def request(text: str) -> ModelRequest:
    return ModelRequest(
        messages=[ChatMessage(role="user", content=text)],
        max_output_tokens=128,
    )


def test_gateway_requires_explicit_remote_consent(tmp_path):
    gateway = RemoteEgressGateway(RemoteEgressAuditStore(tmp_path / "egress.sqlite3"))

    try:
        gateway.prepare(
            request("hello"),
            RemoteEgressContext(channel="cloud", allow_egress=False),
        )
    except RemoteEgressDenied as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("expected remote egress to be denied")


def test_gateway_redacts_credentials_and_audits_without_content(tmp_path):
    db_path = tmp_path / "egress.sqlite3"
    gateway = RemoteEgressGateway(RemoteEgressAuditStore(db_path))

    secret_text = (
        "use Bearer abcdefghijklmnop to authenticate; "
        "api_key=super-secret-value"
    )
    decision = gateway.prepare(
        request(secret_text),
        RemoteEgressContext(channel="cloud", allow_egress=True),
    )

    assert decision.redactions == 2
    assert "[REDACTED]" in decision.request.messages[0].content
    assert "super-secret-value" not in decision.request.messages[0].content

    import sqlite3

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT outcome, redactions FROM egress_audit WHERE request_id = ?",
            (decision.request_id,),
        ).fetchone()
    assert row == ("allowed", 2)
    assert secret_text.encode() not in db_path.read_bytes()


def test_gateway_requires_context_confirmation_and_blocks_sensitive_memory(tmp_path):
    gateway = RemoteEgressGateway(RemoteEgressAuditStore(tmp_path / "egress.sqlite3"))

    contexts = (
        RemoteEgressContext(
            channel="cloud",
            allow_egress=True,
            activity_attached=True,
        ),
        RemoteEgressContext(
            channel="cloud",
            allow_egress=True,
            memory_attached=True,
        ),
        RemoteEgressContext(
            channel="cloud",
            allow_egress=True,
            session_attached=True,
        ),
        RemoteEgressContext(
            channel="cloud",
            allow_egress=True,
            sensitive_memory=True,
        ),
    )
    for context in contexts:
        try:
            gateway.prepare(request("hello"), context)
        except RemoteEgressDenied:
            continue
        raise AssertionError("expected egress to be denied")


def test_gateway_enforces_payload_budget(tmp_path):
    gateway = RemoteEgressGateway(RemoteEgressAuditStore(tmp_path / "egress.sqlite3"))
    oversized = request("x" * 20_000).model_copy(
        update={
            "messages": [
                ChatMessage(role="user", content="x" * 20_000),
                ChatMessage(role="system", content="y" * 20_000),
            ]
        }
    )
    try:
        gateway.prepare(
            oversized,
            RemoteEgressContext(channel="cloud", allow_egress=True),
        )
    except RemoteEgressDenied as exc:
        assert "payload budget" in str(exc)
    else:
        raise AssertionError("expected oversized request to be denied")
