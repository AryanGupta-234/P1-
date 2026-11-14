import threading
import time

import pytest

from senti.ui.approvals import ApprovalAlreadyDecided, ApprovalBroker, UnknownApproval


class Recorder:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, event):
        with self.lock:
            self.events.append(event)

    def wait_for(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                for event in self.events:
                    if predicate(event):
                        return event
            time.sleep(0.01)
        raise AssertionError("event not observed")


def _ask(broker, results, preview=None):
    results.append(broker.handler("senti_set_volume", {"level": 30}, "controlled",
                                  preview or {"current_state": "70%", "intended_state": "30%"}))


def _start(broker, results):
    worker = threading.Thread(target=_ask, args=(broker, results), daemon=True)
    worker.start()
    return worker


def test_approve_unblocks_worker_with_true():
    sink = Recorder()
    broker = ApprovalBroker(sink, timeout=5)
    results = []
    worker = _start(broker, results)
    pending = sink.wait_for(lambda e: e["type"] == "approval" and e["status"] == "pending")
    assert pending["tool"] == "senti_set_volume"
    assert pending["risk"] == "controlled"
    assert pending["preview"]["intended_state"] == "30%"
    assert pending["arguments"] == {"level": 30}
    assert 0 < pending["expires_in"] <= 5
    assert [p["approval_id"] for p in broker.pending()] == [pending["approval_id"]]
    decided = broker.decide(pending["approval_id"], "approve")
    worker.join(2)
    assert results == [True]
    assert decided["status"] == "approved"
    assert broker.pending() == []
    sink.wait_for(lambda e: e.get("status") == "approved")


def test_deny_returns_false():
    sink = Recorder()
    broker = ApprovalBroker(sink, timeout=5)
    results = []
    worker = _start(broker, results)
    pending = sink.wait_for(lambda e: e.get("status") == "pending")
    broker.decide(pending["approval_id"], "deny")
    worker.join(2)
    assert results == [False]


def test_timeout_expires_as_denial():
    sink = Recorder()
    broker = ApprovalBroker(sink, timeout=0.2)
    results = []
    worker = _start(broker, results)
    worker.join(3)
    assert results == [False]
    expired = sink.wait_for(lambda e: e.get("status") == "expired")
    with pytest.raises(ApprovalAlreadyDecided) as info:
        broker.decide(expired["approval_id"], "approve")
    assert info.value.status == "expired"


def test_decision_is_only_accepted_once():
    sink = Recorder()
    broker = ApprovalBroker(sink, timeout=5)
    results = []
    worker = _start(broker, results)
    pending = sink.wait_for(lambda e: e.get("status") == "pending")
    broker.decide(pending["approval_id"], "deny")
    with pytest.raises(ApprovalAlreadyDecided):
        broker.decide(pending["approval_id"], "approve")
    worker.join(2)
    assert results == [False]
    assert sum(1 for e in sink.events if e.get("status") in {"approved", "denied"}) == 1


def test_unknown_and_invalid_decisions_are_rejected():
    broker = ApprovalBroker(timeout=5)
    with pytest.raises(UnknownApproval):
        broker.decide("nope", "approve")
    with pytest.raises(ValueError):
        broker.decide("nope", "maybe")


def test_deny_all_releases_every_waiter():
    sink = Recorder()
    broker = ApprovalBroker(sink, timeout=5)
    results = []
    workers = [_start(broker, results) for _ in range(3)]
    deadline = time.monotonic() + 3
    while len(broker.pending()) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert broker.deny_all("emergency_stop") == 3
    for worker in workers:
        worker.join(2)
    assert results == [False, False, False]


def test_handler_signature_receives_preview_from_registry():
    """The registry passes the preview only to 4-positional callbacks."""
    from senti.tools.registry import CapabilityRegistry

    broker = ApprovalBroker(timeout=5)
    captured = {}

    def sink(event):
        if event.get("status") == "pending":
            captured.update(event)
            threading.Thread(target=broker.decide, args=(event["approval_id"], "approve"),
                             daemon=True).start()

    broker.event_sink = sink
    assert CapabilityRegistry._ask_approval(broker.handler, "t", {}, "low", {"effect": "x"}) is True
    assert captured["preview"] == {"effect": "x"}


def test_unserialisable_arguments_are_made_json_safe():
    broker = ApprovalBroker(timeout=0.05)
    assert broker.handler("t", {"obj": object()}, "low", {"blob": b"x"}) is False
