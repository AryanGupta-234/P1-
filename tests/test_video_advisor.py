from datetime import datetime, timezone
import json

import pytest

from aie.contracts import AIEEvent, EntityRef
from aie.diagnostics.video_advisor import VideoAdvisorError, generate_video_advice
from aie.models.base import ModelResponse
from aie.store import EventStore


def _store_with_stall(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.append(AIEEvent(
        event_id="evidence-playback-1",
        timestamp=datetime.now(timezone.utc),
        host_id="advisor-test-host",
        source="browser.extension",
        event_type="browser.video.snapshot",
        entity=EntityRef(type="browser_video", name="video_playback"),
        data={
            "playback_state": "waiting",
            "stall_count": 3,
            "observation_window_seconds": 60,
            "buffered_ahead_seconds": 0.3,
            "playback_progress_delta_seconds": 0.0,
        },
        sensitivity="internal",
        confidence=1.0,
        evidence_kind="observed",
    ))
    return store


class FakeLocalOllama:
    def __init__(self, *, cite_unknown=False):
        self.cite_unknown = cite_unknown

    def list_models(self):
        return ["qwen2.5:3b-instruct"]

    def chat(self, request, *, model, installed_models=None):
        facts = json.loads(request.messages[-1].content.split("\n", 1)[1])
        evidence_id = "invented-id" if self.cite_unknown else facts["evidence_event_ids"][0]
        response = {
            "summary": "The player is stalled with very little buffered media.",
            "observations": [{
                "statement": "Only 0.30 seconds of media is buffered ahead.",
                "evidence_event_ids": [evidence_id],
            }],
            "next_steps": [{
                "priority": "medium",
                "title": "Compare connectivity measurements",
                "rationale": "Compare separately measured network evidence before changing settings.",
                "evidence_event_ids": [evidence_id],
                "mode": "compare",
            }],
            "unknowns": ["The active streaming CDN path has not been measured directly."],
        }
        return ModelResponse(
            model=model,
            content=json.dumps(response),
            elapsed_seconds=0.01,
            prompt_tokens=100,
            completion_tokens=80,
            local_inference=True,
            provider="ollama",
        )


def test_video_advisor_uses_local_model_and_cites_real_evidence(tmp_path):
    result = generate_video_advice(
        _store_with_stall(tmp_path),
        tier="routine",
        client=FakeLocalOllama(),
    )

    assert result["provider"] == "ollama"
    assert result["model"] == "qwen2.5:3b-instruct"
    assert result["local_inference"] is True
    assert result["safety"]["remote_egress"] is False
    assert result["safety"]["actions_executed"] is False
    assert result["observations"][0]["evidence_event_ids"] == ["evidence-playback-1"]


def test_video_advisor_rejects_model_citations_outside_evidence(tmp_path):
    with pytest.raises(VideoAdvisorError, match="outside the supplied evidence"):
        generate_video_advice(
            _store_with_stall(tmp_path),
            client=FakeLocalOllama(cite_unknown=True),
        )


def test_video_advisor_refuses_to_invent_diagnosis_without_fresh_playback(tmp_path):
    store = EventStore(tmp_path / "empty.sqlite3")
    with pytest.raises(VideoAdvisorError, match="No fresh playback context"):
        generate_video_advice(store, client=FakeLocalOllama())
