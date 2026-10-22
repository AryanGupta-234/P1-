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
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.7"
