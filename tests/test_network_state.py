from aie.context.network_state import NetworkInterfaceStateTracker
from aie.contracts import AIEEvent, EntityRef


def snapshot(name="Ethernet", *, is_up=True, speed=1000, mtu=1500, sent=10):
    return AIEEvent(
        host_id="host-test",
        source="windows.network",
        event_type="network.interface.snapshot",
        entity=EntityRef(type="network_interface", name=name),
        data={
            "is_up": is_up,
            "speed_mbps": speed,
            "mtu": mtu,
            "bytes_sent": sent,
        },
    )


def test_first_snapshot_establishes_baseline_without_change_event():
    tracker = NetworkInterfaceStateTracker()
    assert tracker.observe([snapshot()]) == []


def test_emits_one_derived_event_for_state_change_and_links_evidence():
    tracker = NetworkInterfaceStateTracker()
    tracker.observe([snapshot()])
    evidence = snapshot(is_up=False, sent=900)

    changes = tracker.observe([evidence])

    assert len(changes) == 1
    event = changes[0]
    assert event.event_type == "network.interface.state_changed"
    assert event.evidence_kind == "derived"
    assert event.correlation_id == evidence.event_id
    assert event.data["evidence_event_id"] == evidence.event_id
    assert event.data["changed_fields"] == {
        "is_up": {"before": True, "after": False}
    }
    assert event.data["traffic_counters_used"] is False
    assert event.data["causality_inferred"] is False


def test_traffic_counter_changes_do_not_create_state_change():
    tracker = NetworkInterfaceStateTracker()
    tracker.observe([snapshot(sent=1)])
    assert tracker.observe([snapshot(sent=999999)]) == []


def test_new_baseline_after_change_prevents_duplicate_events():
    tracker = NetworkInterfaceStateTracker()
    tracker.observe([snapshot()])
    assert len(tracker.observe([snapshot(speed=100)])) == 1
    assert tracker.observe([snapshot(speed=100)]) == []


def test_unrelated_events_are_ignored_and_interface_count_is_bounded():
    tracker = NetworkInterfaceStateTracker(max_interfaces=1)
    unrelated = AIEEvent(
        host_id="host-test",
        source="windows.network",
        event_type="network.dns_probe",
        entity=EntityRef(type="dns_target", name="example.test"),
    )
    tracker.observe([unrelated, snapshot()])
    tracker.observe([snapshot("Wi-Fi", is_up=False)])
    assert tracker.observe([snapshot("Wi-Fi", is_up=True)]) == []


def test_max_interfaces_validation():
    import pytest

    with pytest.raises(ValueError):
        NetworkInterfaceStateTracker(max_interfaces=0)
