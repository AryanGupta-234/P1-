from aie.config import observer_is_paused, observer_pause_path, set_observer_paused


def test_observer_pause_is_shared_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert observer_is_paused() is False
    set_observer_paused(True)
    assert observer_is_paused() is True
    assert observer_pause_path().exists()

    set_observer_paused(True)
    assert observer_is_paused() is True

    set_observer_paused(False)
    assert observer_is_paused() is False
    assert not observer_pause_path().exists()


def test_resuming_when_not_paused_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    set_observer_paused(False)

    assert observer_is_paused() is False
