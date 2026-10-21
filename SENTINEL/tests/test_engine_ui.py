from pathlib import Path


def test_engine_deck_exposes_review_actions_and_safe_close_request():
    root = Path(__file__).resolve().parents[1]
    js = (root / "ui" / "app.js").read_text(encoding="utf-8")
    assert "VERIFY SIGNATURE" in js
    assert "SHA-256" in js
    assert "OPEN LOCATION" in js
    assert "REQUEST CLOSE" in js
    assert 'kind: "terminate_process"' in js
    assert "No force-termination fallback exists." in js
