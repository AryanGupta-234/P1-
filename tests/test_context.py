from datetime import datetime, timezone

import pytest

from aie.context import build_environment_context
from aie.state_model import EnvironmentProjection, EntityState, ProcessInstance


def sample_projection():
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    processes = {
        ("host", pid, float(pid)): ProcessInstance(
            "host", pid, float(pid), f"proc-{pid}.exe", "running",
            when, when, ["evidence-" + str(pid)],
        )
        for pid in range(1, 4)
    }
    entities = {
        ("host", "services", "Spooler"): EntityState(
            "host", "services", "Spooler", "service", "Spooler",
            "present", {"status": "running"}, when, when, ["service-event"],
        )
    }
    return EnvironmentProjection(processes, entities, {"services": "partial"}, 2)


def test_context_packet_is_bounded_and_keeps_provenance():
    packet = build_environment_context(sample_projection(), max_processes=2, max_entities=1)
    assert [item["pid"] for item in packet["processes"]] == [1, 2]
    assert packet["limits"]["processes_omitted"] == 1
    assert packet["entities"][0]["evidence_ids"] == ["service-event"]
    assert packet["semantics"]["inference_performed"] is False
    assert packet["semantics"]["absence_means_removal"] is False


@pytest.mark.parametrize(
    "kwargs",
    [{"max_processes": 0}, {"max_processes": 501}, {"max_entities": 0}],
)
def test_context_packet_rejects_unbounded_limits(kwargs):
    with pytest.raises(ValueError):
        build_environment_context(sample_projection(), **kwargs)



def test_context_exposes_evidence_reference_truncation():
    projection = sample_projection()
    process = projection.processes[("host", 1, 1.0)]
    process.evidence_ids = [f"event-{index}" for index in range(64)]
    process.evidence_truncated = True
    packet = build_environment_context(projection, max_processes=1)
    assert packet["processes"][0]["evidence_truncated"] is True
