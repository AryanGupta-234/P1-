"""Opt-in, privacy-minimizing native notification preferences and event polling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from aie.store import EventStore


class NotificationPreferences(BaseModel):
    """User-owned preferences; disabled by default and quiet hours enabled by default."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    quiet_start: str = Field(default="22:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="07:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    def is_quiet(self, now: datetime | None = None) -> bool:
        current = (now or datetime.now().astimezone()).astimezone()
        minute = (current.hour * 60) + current.minute
        start_hour, start_minute = (int(value) for value in self.quiet_start.split(":"))
        end_hour, end_minute = (int(value) for value in self.quiet_end.split(":"))
        start = (start_hour * 60) + start_minute
        end = (end_hour * 60) + end_minute
        if start == end:
            return False
        if start < end:
            return start <= minute < end
        return minute >= start or minute < end


class NotificationPreferencesStore:
    """Read/write a small local JSON preference file without following symlinks."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> NotificationPreferences:
        if self.path.is_symlink():
            raise ValueError("notification preference path cannot be a symlink")
        if not self.path.exists():
            return NotificationPreferences()
        if not self.path.is_file() or self.path.stat().st_size > 4096:
            raise ValueError("notification preferences must be a regular file under 4 KiB")
        try:
            return NotificationPreferences.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(
                f"notification preference file is invalid ({type(exc).__name__})"
            ) from exc

    def save(self, preferences: NotificationPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("notification preference path cannot be a symlink")
        temporary = self.path.with_name(self.path.name + ".tmp")
        if temporary.is_symlink():
            raise ValueError("notification temporary path cannot be a symlink")
        payload = preferences.model_dump_json(indent=2)
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True, slots=True)
class NativeNotification:
    title: str
    message: str


class DiagnosticNotificationPoller:
    """Emit only generic local diagnostic notices, never event details or app identity."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        preferences: NotificationPreferencesStore,
        is_paused: Callable[[], bool],
        max_per_poll: int = 2,
    ) -> None:
        if not 1 <= max_per_poll <= 5:
            raise ValueError("max_per_poll must be between 1 and 5")
        self.event_store = event_store
        self.preferences = preferences
        self.is_paused = is_paused
        self.max_per_poll = max_per_poll
        self._seen_ids: set[str] = {
            item.event_id for item in self.event_store.recent(500)
        }

    def _remember(self, event_id: str) -> None:
        self._seen_ids.add(event_id)
        if len(self._seen_ids) > 1000:
            # IDs are only a bounded in-process cursor, not persistent history.
            self._seen_ids = set(list(self._seen_ids)[-500:])

    def poll(self, *, now: datetime | None = None) -> list[NativeNotification]:
        events = self.event_store.recent(100)
        fresh = [event for event in reversed(events) if event.event_id not in self._seen_ids]
        for event in fresh:
            self._remember(event.event_id)

        preferences = self.preferences.load()
        if (
            not preferences.enabled
            or self.is_paused()
            or preferences.is_quiet(now)
        ):
            return []

        notifications: list[NativeNotification] = []
        for event in fresh:
            if event.event_type != "diagnostic.video_finding":
                continue
            notifications.append(
                NativeNotification(
                    title="P1- diagnostic finding",
                    message=(
                        "A possible playback issue was detected. "
                        "Run 'aie events' locally to inspect the evidence."
                    ),
                )
            )
            if len(notifications) >= self.max_per_poll:
                break
        return notifications
