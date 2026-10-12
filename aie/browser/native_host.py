"""Chrome/Edge/Brave Native Messaging host for privacy-minimized playback events.

The host accepts a strict video telemetry schema and a minimal bridge health-check.
It never accepts page text, URLs, cookies, credentials, arbitrary commands or actions.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import BinaryIO

from aie.config import database_path
from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id
from aie.store import EventStore

MAX_MESSAGE_BYTES = 1024 * 1024
_ALLOWED_STATES = {"playing", "waiting", "stalled", "paused", "ended"}
_ALLOWED_FIELDS = {
    "kind",
    "media_session_id",
    "playback_state",
    "stall_count",
    "observation_window_seconds",
    "buffered_ahead_seconds",
    "playback_progress_delta_seconds",
    "dropped_frames_pct",
}
_BRIDGE_PING = {"kind": "bridge_ping"}
_BRIDGE_PONG = {"ok": True, "kind": "bridge_pong"}


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    """Read exactly size bytes; None means clean EOF before any bytes were read."""
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks:
                return None
            raise EOFError("unexpected EOF in native messaging frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def iter_native_messages(stream: BinaryIO) -> Iterator[dict]:
    """Decode Chrome's 4-byte little-endian length-prefixed JSON frames."""
    while True:
        header = _read_exact(stream, 4)
        if header is None:
            return
        size = struct.unpack("<I", header)[0]
        if size == 0 or size > MAX_MESSAGE_BYTES:
            raise ValueError("invalid native messaging frame size")
        raw = _read_exact(stream, size)
        if raw is None:
            raise EOFError("missing native messaging payload")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("native messaging payload must be a JSON object")
        yield payload


def write_native_message(stream: BinaryIO, payload: dict) -> None:
    """Write one native messaging response without emitting plain stdout text."""
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("native messaging response exceeds size limit")
    stream.write(struct.pack("<I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def _optional_number(payload: dict, key: str, *, minimum: float, maximum: float) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{key} is outside the accepted range")
    return number


def event_from_browser_payload(payload: dict) -> AIEEvent:
    """Validate a strict extension message and convert it into a normalized event."""
    extra = set(payload) - _ALLOWED_FIELDS
    if extra:
        raise ValueError("unsupported browser telemetry fields")
    if payload.get("kind") != "video_snapshot":
        raise ValueError("unsupported browser telemetry message kind")

    media_session_id = payload.get("media_session_id")
    if not isinstance(media_session_id, str):
        raise ValueError("media_session_id is required")
    try:
        session_id = str(uuid.UUID(media_session_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("media_session_id must be a UUID") from exc

    state = payload.get("playback_state")
    if not isinstance(state, str) or state not in _ALLOWED_STATES:
        raise ValueError("invalid playback_state")

    stall_count = payload.get("stall_count")
    if isinstance(stall_count, bool) or not isinstance(stall_count, int) or not 0 <= stall_count <= 10000:
        raise ValueError("stall_count must be an integer from 0 to 10000")

    window = payload.get("observation_window_seconds")
    if isinstance(window, bool) or not isinstance(window, (int, float)):
        raise ValueError("observation_window_seconds must be numeric")
    window = float(window)
    if not math.isfinite(window) or not 1 <= window <= 300:
        raise ValueError("observation_window_seconds must be between 1 and 300")

    data = {
        "playback_state": state,
        "stall_count": stall_count,
        "observation_window_seconds": window,
    }
    ranges = {
        "buffered_ahead_seconds": (0.0, 3600.0),
        "playback_progress_delta_seconds": (0.0, 300.0),
        "dropped_frames_pct": (0.0, 100.0),
    }
    for key, (minimum, maximum) in ranges.items():
        value = _optional_number(payload, key, minimum=minimum, maximum=maximum)
        if value is not None:
            data[key] = value

    return AIEEvent(
        timestamp=datetime.now(timezone.utc),
        host_id=host_id(),
        source="browser.extension",
        event_type="browser.video.snapshot",
        entity=EntityRef(
            type="browser_video",
            name="video_playback",
            stable_id=session_id,
        ),
        data=data,
        sensitivity="internal",
        confidence=1.0,
        evidence_kind="observed",
    )


def run_host(input_stream: BinaryIO, output_stream: BinaryIO, store: EventStore) -> int:
    """Respond to health checks and persist valid telemetry events."""
    accepted = 0
    for payload in iter_native_messages(input_stream):
        if payload == _BRIDGE_PING:
            write_native_message(output_stream, _BRIDGE_PONG)
            continue
        try:
            event = event_from_browser_payload(payload)
            store.append(event)
            write_native_message(output_stream, {"ok": True, "event_id": event.event_id})
            accepted += 1
        except (TypeError, ValueError) as exc:
            write_native_message(output_stream, {"ok": False, "error": str(exc)})
    return accepted


def main() -> int:
    """Native host entry point; stdout is exclusively the binary protocol channel."""
    if os.name != "nt":
        sys.stderr.write("AIE browser native host supports Windows only.\\n")
        return 2
    try:
        run_host(sys.stdin.buffer, sys.stdout.buffer, EventStore(database_path()))
    except (EOFError, OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"AIE browser native host stopped: {type(exc).__name__}\\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
