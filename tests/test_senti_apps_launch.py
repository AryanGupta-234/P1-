from pathlib import Path

import pytest

from senti.windows import launch
from senti.windows.app_catalog import AppDiscovery, AppRecord, name_score, pick_unambiguous, rank_candidates

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CODE = r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code\Code.exe"


@pytest.fixture(autouse=True)
def fake_files(monkeypatch):
    monkeypatch.setattr(launch, "_is_file", lambda p: p in {CHROME, CODE})
    monkeypatch.setattr(launch, "_check_executable", lambda p: Path(p))


def _records(_tmp_path=None):
    chrome, code = CHROME, CODE
    return [
        AppRecord("Google Chrome", str(chrome), ("Google Chrome", "chrome"), "Google LLC", None,
                  "start_menu_shortcut", available=True),
        AppRecord("chrome", str(chrome), ("chrome", "chrome.exe"), None, None, "app_paths", available=True),
        AppRecord("Visual Studio Code", str(code), ("Visual Studio Code", "Code"), None, None,
                  "start_menu_shortcut", available=True),
        AppRecord("Calculator", None, ("Calculator",), None, None, "shell_apps_folder", "package", True,
                  "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"),
        AppRecord("calc", r"C:\Windows\System32\calc_missing.exe", ("calc",), None, None, "app_paths"),
        AppRecord("Microsoft Teams", None, ("Microsoft Teams",), None, None, "shell_apps_folder", "package", True, "MSTeams_x!App"),
        AppRecord("Microsoft Teams (personal)", None, ("Microsoft Teams (personal)",), None, None, "shell_apps_folder", "package", True,
                  "Teams_y!App"),
        AppRecord("Notepad", None, ("Notepad",), None, None, "shell_apps_folder", "package", True,
                  "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"),
        AppRecord("notepad", str(chrome), ("notepad",), None, None, "app_paths", available=True),
    ]


def test_scoring_signals_are_dynamic():
    assert name_score("vs code", "Visual Studio Code") > 0.85  # initials + token
    assert name_score("vscode", "VS Code") >= 0.97  # compact equality
    assert name_score("chorme", "Google Chrome", "Google LLC") > 0.6  # transposition typo
    assert name_score("chrome", "Microsoft Office Home and Student") < 0.55
    assert name_score("7zip", "7-Zip 23.01 (x64)") >= 0.97  # version text ignored


def test_rank_and_pick_ambiguity():
    items = ["Microsoft Teams", "Microsoft Teams (personal)", "Steam"]
    ranked = rank_candidates("teams", items, names=lambda x: [x])
    assert pick_unambiguous(ranked) is None and ranked[0].score >= ranked[1].score
    assert pick_unambiguous(rank_candidates("steam", items, names=lambda x: [x])).item == "Steam"


def test_legacy_resolve_prefers_exact_alias():
    records = [AppRecord("Brave", r"C:\b\brave.exe", ("Brave", "browser"), "Brave", "1", "app_paths", available=True),
               AppRecord("Brave Beta", r"C:\bb\brave.exe", ("Brave Beta",), "Brave", "2", "app_paths", available=True)]
    assert [r.display_name for r in AppDiscovery.resolve(records, "browser")] == ["Brave"]


def test_resolution_collapses_duplicate_targets_and_includes_aumids(tmp_path):
    records = _records(tmp_path)
    winner, _ = launch.resolve_launch("chrome", records=records)
    assert winner.item.display_name == "Google Chrome"
    winner, _ = launch.resolve_launch("vs code", records=records)
    assert winner.item.display_name == "Visual Studio Code"
    winner, _ = launch.resolve_launch("calculator", records=records)
    assert launch._target(winner.item) == ("aumid", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")
    winner, _ = launch.resolve_launch("notepad", records=records)  # user-facing AUMID beats App Paths alias
    assert winner.item.source == "shell_apps_folder"
    _, ranked = launch.resolve_launch("calc", records=records)
    assert all(c.item.executable_path != r"C:\Windows\System32\calc_missing.exe" for c in ranked)


def test_ambiguous_launch_returns_candidates_and_does_not_launch(tmp_path):
    out = launch.launch_application("teams", records=_records(tmp_path),
                                    launcher=lambda *a, **k: pytest.fail("guessed"),
                                    probe=lambda kind, target: lambda: {"pids": [], "windows": []})
    assert out["status"] == "ambiguous" and out["verified"] is False
    assert {c["display_name"] for c in out["candidates"][:2]} == {"Microsoft Teams", "Microsoft Teams (personal)"}
    assert all("score" in c for c in out["candidates"])
    with pytest.raises(ValueError, match="ambiguous"):
        launch.simulate_launch({"application": "teams"}, records=_records(tmp_path))


def test_simulate_launch_reports_running_state_without_launching(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "shell_execute", lambda *a, **k: pytest.fail("simulate launched"))
    preview = launch.simulate_launch({"application": "chrome"}, records=_records(tmp_path),
                                     probe=lambda kind, target: lambda: {"pids": [10, 11], "windows": []})
    assert preview["kind"] == "exe" and preview["already_running"] is True
    assert preview["target"].endswith("chrome.exe") and preview["publisher"] == "Google LLC"
    assert preview["executes"] is False


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def test_launch_verification_requires_new_process_or_window(tmp_path):
    records = _records(tmp_path)
    states = iter([{"pids": [], "windows": []}, {"pids": [], "windows": []}, {"pids": [77], "windows": []}])
    calls = []
    clock = Clock()
    out = launch.launch_application("vs code", records=records,
                                    launcher=lambda f, p, **k: calls.append(f) or 77,
                                    probe=lambda kind, target: lambda: next(states), clock=clock, sleep=clock.sleep)
    assert out["verified"] is True and out["pids"] == [77] and calls[0].endswith("Code.exe")
    clock = Clock()
    out = launch.launch_application("calculator", records=records, launcher=lambda f, p, **k: None,
                                    probe=lambda kind, target: lambda: {"pids": [], "windows": []},
                                    verify_seconds=3, clock=clock, sleep=clock.sleep)
    assert out["verified"] is False and out["aumid"].endswith("!App")
    clock = Clock()
    window_states = iter([{"pids": [], "windows": []}, {"pids": [], "windows": [1234]}])
    out = launch.launch_application("calculator", records=records, launcher=lambda f, p, **k: None,
                                    probe=lambda kind, target: lambda: next(window_states),
                                    clock=clock, sleep=clock.sleep)
    assert out["verified"] is True and "window" in out["verification"]


def test_blocked_launch_paths(tmp_path, monkeypatch):
    monkeypatch.undo()  # use the real file checks
    bad = tmp_path / "Downloads" / "tool.exe"
    bad.parent.mkdir()
    bad.write_bytes(b"MZ")
    records = [AppRecord("Tool", str(bad), ("Tool",), None, None, "volume_scan", available=True)]
    with pytest.raises(PermissionError):
        launch.launch_application("tool", records=records, launcher=lambda *a, **k: pytest.fail("launched"),
                                  probe=lambda kind, target: lambda: {"pids": [], "windows": []})
