"""Regression tests for the native messaging bridge handshake."""
from __future__ import annotations

import io
import json
import struct

from aie.browser.native_host import run_host


def _frame(payload: dict) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def _responses(raw: bytes) -> list[dict]:
    responses = []
    offset = 0
    while offset < len(raw):
        size = struct.unpack("<I", raw[offset : offset + 4])[0]
        offset += 4
        responses.append(json.loads(raw[offset : offset + size].decode("utf-8")))
        offset += size
    return responses


class RecordingStore:
    def __init__(self) -> None:
        self.events = []

    def append(self, event) -> None:
        self.events.append(event)


def test_bridge_ping_returns_pong_without_persisting_event() -> None:
    store = RecordingStore()
    output = io.BytesIO()

    accepted = run_host(
        io.BytesIO(_frame({"kind": "bridge_ping"})),
        output,
        store,  # type: ignore[arg-type]
    )

    assert accepted == 0
    assert _responses(output.getvalue()) == [{"ok": True, "kind": "bridge_pong"}]
    assert store.events == []


def test_bridge_ping_requires_exact_message_shape() -> None:
    output = io.BytesIO()

    accepted = run_host(
        io.BytesIO(_frame({"kind": "bridge_ping", "command": "anything"})),
        output,
        RecordingStore(),  # type: ignore[arg-type]
    )

    assert accepted == 0
    assert _responses(output.getvalue()) == [
        {"ok": False, "error": "unsupported browser telemetry fields"}
    ]
