from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_install_creates_desktop_and_searchable_start_menu_shortcuts():
    source = (ROOT / "agent.py").read_text(encoding="utf-8")
    assert "Join-Path $desktop 'SENTINEL.lnk'" in source
    assert "Join-Path $userPrograms 'SENTINEL.lnk'" in source
    assert "Join-Path $commonPrograms 'SENTINEL.lnk'" in source
    assert "User Start Menu (searchable)" in source
    assert "All Users Start Menu (searchable)" in source


def test_every_shortcut_is_verified_against_release_python_and_entrypoint():
    source = (ROOT / "agent.py").read_text(encoding="utf-8")
    assert "$link.TargetPath = $pythonw" in source
    assert "$link.Arguments = $shortcutArgs" in source
    assert "$link.WorkingDirectory = $workdir" in source
    assert "$check.TargetPath -ne $pythonw" in source
    assert "$check.Arguments -ne $shortcutArgs" in source
    assert "SHORTCUT_OK=" in source
    assert "-RunLevel Limited" in source
    assert "standard-user interactive Windows agent" in source
    assert "execute_privileged_job" in source


def test_uninstaller_removes_direct_user_and_all_users_start_shortcuts():
    source = (ROOT / "agent.py").read_text(encoding="utf-8")
    assert "Remove-Item (Join-Path $userPrograms 'SENTINEL.lnk')" in source
    assert "Remove-Item (Join-Path $commonPrograms 'SENTINEL.lnk')" in source
    assert "User Start Menu shortcut still exists" in source
    assert "All Users Start Menu shortcut still exists" in source


def test_installer_reports_top_level_start_menu_entry():
    source = (ROOT / "install.bat").read_text(encoding="utf-8")
    assert "searchable directly from Start" in source
    assert "Desktop or Start Menu shortcut" in source


def test_release_version_was_bumped_for_immutable_installer_layout():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.2.26"



def test_installer_verifies_standard_user_interactive_agent_instead_of_admin_observer():
    source = (ROOT / "agent.py").read_text(encoding="utf-8")
    assert "def _running_agent_runtime()" in source
    assert "def _runtime_validation_problem(" in source
    assert 'runtime.get("is_elevated") is not False' in source
    assert 'runtime.get("desktop_access_expected") is not True' in source
    assert "expected_session_id" in source
    assert "expected_username=logged_on" in source
    assert "expected_executable=pythonw" in source
    assert "standard-user interactive agent failed identity verification" in source
    assert "_running_agent_is_elevated() is not True" not in source
    assert "administrator elevation could not be verified" not in source


def test_normal_opener_never_restarts_standard_user_agent_to_elevate_it():
    source = (ROOT / "agent.py").read_text(encoding="utf-8")
    start = source.index("def open_app():")
    end = source.index("def install():", start)
    opener = source[start:end]
    assert "_runtime_validation_problem(" in opener
    assert "Replacing it with the standard-user interactive task" in opener
    assert "restarting it with administrator permissions" not in opener
    assert "standard-user runtime verification" in opener
