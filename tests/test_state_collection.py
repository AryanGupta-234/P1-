from aie.delta import SnapshotDeltaTracker
from aie.providers.windows import WindowsProvider


def make_provider(monkeypatch):
    provider = WindowsProvider.__new__(WindowsProvider)
    provider._state_deltas = SnapshotDeltaTracker()
    monkeypatch.setattr(
        WindowsProvider, "_services",
        staticmethod(lambda: [{"name": "Spooler", "status": "running"}]),
    )
    monkeypatch.setattr(
        WindowsProvider, "_network_interfaces",
        staticmethod(lambda: [{"name": "Wi-Fi", "is_up": True, "mtu": 1500}]),
    )
    monkeypatch.setattr(
        WindowsProvider, "_scheduled_tasks",
        staticmethod(lambda: {
            "available": True,
            "tasks": [{"task_name": r"\AIE\Daily", "status": "Ready"}],
        }),
    )
    monkeypatch.setattr(
        WindowsProvider, "_installed_applications",
        staticmethod(lambda: [
            {"name": "Example App", "version": "1.0", "publisher": "Example Inc."}
        ]),
    )
    return provider


def test_state_collection_establishes_four_inventory_baselines(monkeypatch):
    provider = make_provider(monkeypatch)

    events = list(provider.collect_state_deltas())

    assert sum(event.event_type.endswith(".baseline") for event in events) == 4
    assert sum(event.event_type.endswith(".present_observed") for event in events) == 4
    observed_names = {
        event.entity.name for event in events
        if event.event_type.endswith(".present_observed")
    }
    assert observed_names == {
        "Spooler", "Wi-Fi", r"\AIE\Daily", "Example App|1.0",
    }


def test_state_collection_emits_changes_on_later_samples(monkeypatch):
    provider = make_provider(monkeypatch)
    list(provider.collect_state_deltas())

    monkeypatch.setattr(
        WindowsProvider, "_services",
        staticmethod(lambda: [{"name": "Spooler", "status": "stopped"}]),
    )
    events = list(provider.collect_state_deltas())

    service_changes = [
        event for event in events
        if event.event_type == "inventory.services.changed"
    ]
    assert len(service_changes) == 1
    assert service_changes[0].data["previous"]["status"] == "running"
    assert service_changes[0].data["current"]["status"] == "stopped"
