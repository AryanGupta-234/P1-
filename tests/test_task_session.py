from datetime import datetime, timedelta, timezone

import pytest

from aie.context.task_session.context import build_task_session_prompt_context
from aie.context.task_session.models import new_task_session
from aie.context.task_session.store import TaskSessionStore


def test_start_replaces_previous_active_session(tmp_path):
    store = TaskSessionStore(tmp_path / "sessions.sqlite3")
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    first = store.start("  Build   ETW observer  ", now=now)
    second = store.start("Validate CI", now=now + timedelta(minutes=20))

    assert first.label == "Build ETW observer"
    assert store.current().session_id == second.session_id
    sessions = store.list()
    assert sessions[0].session_id == second.session_id
    assert sessions[0].active is True
    assert sessions[1].session_id == first.session_id
    assert sessions[1].status == "ended"


def test_end_marks_current_session_ended(tmp_path):
    store = TaskSessionStore(tmp_path / "sessions.sqlite3")
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store.start("Debug runtime", now=now)

    ended = store.end(now=now + timedelta(minutes=5))
    assert ended is not None
    assert ended.status == "ended"
    assert ended.ended_at == now + timedelta(minutes=5)
    assert store.current() is None


def test_session_label_is_bounded():
    now = datetime.now(timezone.utc)
    assert new_task_session("Build ETW observer", now=now).label == "Build ETW observer"
    with pytest.raises(ValueError):
        new_task_session("x" * 121, now=now)


def test_session_prompt_context_contains_only_explicit_metadata(tmp_path):
    store = TaskSessionStore(tmp_path / "sessions.sqlite3")
    store.start("Review private project", now=datetime.now(timezone.utc))

    context = build_task_session_prompt_context(store)

    assert context.session_id
    assert "Review private project" in context.content
    assert "intent" in context.content
    assert "authorize actions" in context.content


def test_task_session_types_are_exposed_from_context_root():
    from aie.context import TaskSession, TaskSessionPromptContext, TaskSessionStore, build_task_session_prompt_context, new_task_session

    assert TaskSession is not None
    assert TaskSessionPromptContext is not None
    assert TaskSessionStore is not None
    assert build_task_session_prompt_context is not None
    assert new_task_session is not None
