import os
import threading
from types import SimpleNamespace

import pytest

from senti.windows import uninstall as u

GUID = "{11111111-2222-3333-4444-555555555555}"
GUID2 = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"


class FakeKey:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200

    def __init__(self, tree):
        # tree: {(hive, view): {key_name: {value: data}}}
        self.tree = tree
        self.opened = []

    def _view(self, hive, access):
        if hive == "HKCU":
            return ""
        return "32" if access & self.KEY_WOW64_32KEY else "64"

    def OpenKey(self, parent, sub, reserved=0, access=0):
        if isinstance(parent, FakeKey):
            hive, view, _ = parent.path
            if sub not in self.tree.get((hive, view), {}):
                raise OSError("missing")
            return FakeKey((hive, view, sub))
        view = self._view(parent, access)
        self.opened.append((parent, view, sub))
        if sub == u.UNINSTALL_KEY:
            if (parent, view) not in self.tree:
                raise OSError("missing root")
            return FakeKey((parent, view, None))
        prefix = u.UNINSTALL_KEY + "\\"
        if sub.startswith(prefix) and sub[len(prefix):] in self.tree.get((parent, view), {}):
            return FakeKey((parent, view, sub[len(prefix):]))
        raise OSError("missing")

    def QueryInfoKey(self, key):
        hive, view, _ = key.path
        return (len(self.tree[(hive, view)]), 0, 0)

    def EnumKey(self, key, index):
        hive, view, _ = key.path
        return list(self.tree[(hive, view)])[index]

    def QueryValueEx(self, key, name):
        hive, view, sub = key.path
        values = self.tree[(hive, view)][sub]
        if name not in values:
            raise OSError("no value")
        return values[name], 1


def _tree():
    return {
        ("HKLM", "64"): {
            GUID: {"DisplayName": "Contoso Suite", "Publisher": "Contoso", "DisplayVersion": "2.0",
                   "WindowsInstaller": 1, "UninstallString": f"MsiExec.exe /I{GUID}", "EstimatedSize": 2048},
            "ContosoTool": {"DisplayName": "Contoso Tool", "Publisher": "Contoso",
                            "UninstallString": r'"C:\Program Files\Contoso Tool\uninst.exe" /x'},
            "Hidden": {"DisplayName": "Hidden runtime", "SystemComponent": 1, "UninstallString": "x.exe"},
            "KB500123": {"DisplayName": "Security Update for Thing", "UninstallString": "x.exe"},
            "Patch": {"DisplayName": "Thing Update 1", "ReleaseType": "Update", "UninstallString": "x.exe"},
            "Child": {"DisplayName": "Thing Child", "ParentKeyName": "Thing", "UninstallString": "x.exe"},
            "NoCommand": {"DisplayName": "No command app"},
            "NoRemove": {"DisplayName": "Locked app", "NoRemove": 1, "UninstallString": "x.exe"},
            "Nameless": {"UninstallString": "x.exe"},
        },
        ("HKLM", "32"): {
            GUID: {"DisplayName": "Contoso Suite", "WindowsInstaller": 1, "UninstallString": f"MsiExec.exe /X{GUID}"},
            "Legacy": {"DisplayName": "Legacy Viewer", "UninstallString": r"C:\Program Files (x86)\Legacy\unins000.exe"},
        },
        ("HKCU", ""): {
            "UserApp": {"DisplayName": "User Notes", "Publisher": "Fabrikam",
                        "UninstallString": r'"C:\Users\me\AppData\Local\Notes\Update.exe" --uninstall',
                        "QuietUninstallString": r'"C:\Users\me\AppData\Local\Notes\Update.exe" --uninstall -s'},
        },
    }


def test_registry_enumeration_filters_components_updates_and_missing_commands():
    entries = u.registry_entries(FakeWinreg(_tree()))
    names = sorted(e.display_name for e in entries)
    assert names == ["Contoso Suite", "Contoso Tool", "Legacy Viewer", "User Notes"]
    suite = next(e for e in entries if e.display_name == "Contoso Suite")
    assert suite.kind == "msi" and suite.product_code == GUID and suite.size_kb == 2048
    assert suite.needs_elevation and suite.scope == "machine"
    user = next(e for e in entries if e.display_name == "User Notes")
    assert user.kind == "exe" and not user.needs_elevation and user.entry_id == "reg:HKCU::UserApp"


def test_registry_presence_check_uses_hive_and_view():
    reg = FakeWinreg(_tree())
    legacy = next(e for e in u.registry_entries(reg) if e.display_name == "Legacy Viewer")
    assert legacy.view == "32"
    assert u.registry_entry_present(legacy, reg)
    del reg.tree[("HKLM", "32")]["Legacy"]
    assert not u.registry_entry_present(legacy, reg)


def _pkg(name, *, framework=False, resource=False, signature=3, display=None):
    ident = SimpleNamespace(full_name=f"{name}_1.0.0.0_x64__abc", family_name=f"{name}_abc", name=name,
                            publisher="CN=Pub", version=SimpleNamespace(major=1, minor=0, build=0, revision=0))
    return SimpleNamespace(id=ident, is_framework=framework, is_resource_package=resource, is_optional=False,
                           signature_kind=signature, display_name=display or name,
                           publisher_display_name="Pub", installed_path=rf"C:\Program Files\WindowsApps\{name}",
                           installed_date=None)


class FakePackageManager:
    def __init__(self, packages):
        self.packages = packages
        self.removed = []

    def find_packages_for_user(self, sid):
        return list(self.packages)

    def find_package_for_user(self, sid, full_name):
        return next((p for p in self.packages if p.id.full_name == full_name), None)


def test_msix_enumeration_skips_framework_resource_and_system_packages():
    manager = FakePackageManager([_pkg("Fabrikam.Paint", display="Fabrikam Paint"),
                                  _pkg("VCLibs", framework=True), _pkg("Lang", resource=True),
                                  _pkg("Shell", signature=4), _pkg("Resourceful", display="ms-resource:x")])
    entries = u.msix_entries(manager)
    assert sorted(e.display_name for e in entries) == ["Fabrikam Paint", "Resourceful"]
    paint = next(e for e in entries if e.display_name == "Fabrikam Paint")
    assert paint.kind == "msix" and paint.entry_id.startswith("msix:") and not paint.needs_elevation
    assert u.msix_entry_present(paint, manager)


def test_missing_winrt_reports_provider_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("PyWinRT Windows.Management.Deployment projection is not installed")
    monkeypatch.setattr(u, "_package_manager", unavailable)
    entries, providers = u.enumerate_software(reg=FakeWinreg(_tree()))
    assert providers["msix"].startswith("unavailable")
    assert providers["registry"] == "available" and len(entries) == 4
    listing = u.list_installed_software(entries=entries, providers=providers, kind="msi")
    assert listing["count"] == 1 and listing["counts_by_kind"] == {"msi": 1, "exe": 3}


def _entry(name, **kw):
    defaults = {"entry_id": f"reg:HKCU::{name}", "display_name": name, "kind": "exe", "hive": "HKCU",
                "view": "", "key_name": name, "uninstall_string": r'"C:\Program Files\X\u.exe"'}
    defaults.update(kw)
    return u.UninstallEntry(**defaults)


def test_ranked_resolution_picks_clear_winner_and_returns_candidates_on_ambiguity():
    entries = [_entry("Google Chrome", publisher="Google LLC"),
               _entry("Chrome Remote Desktop Host", publisher="Google LLC"),
               _entry("Microsoft Teams", publisher="Microsoft Corporation"),
               _entry("Microsoft Teams (personal)", publisher="Microsoft Corporation"),
               _entry("Visual Studio Code", publisher="Microsoft Corporation")]
    clear = u.resolve_uninstall({"application": "chrome"}, entries)
    assert clear.entry.display_name == "Google Chrome"
    assert u.resolve_uninstall({"application": "chorme"}, entries).candidates[0].item.display_name == "Google Chrome"
    assert u.resolve_uninstall({"application": "vs code"}, entries).entry.display_name == "Visual Studio Code"
    ambiguous = u.resolve_uninstall({"application": "teams"}, entries)
    assert ambiguous.entry is None and ambiguous.ambiguous
    assert {c.item.display_name for c in ambiguous.candidates[:2]} == {"Microsoft Teams", "Microsoft Teams (personal)"}
    assert all(0 < c.score <= 1 for c in ambiguous.candidates)
    with pytest.raises(ValueError, match="ambiguous"):
        u.simulate_uninstall({"application": "teams"}, entries)
    exact = u.resolve_uninstall({"entry_id": "reg:HKCU::Microsoft Teams"}, entries)
    assert exact.entry.display_name == "Microsoft Teams"


def test_same_msi_product_in_both_views_is_not_ambiguous():
    a = _entry("Contoso Suite", kind="msi", product_code=GUID, hive="HKLM", view="64", entry_id="reg:HKLM:64:" + GUID)
    b = _entry("Contoso Suite", kind="msi", product_code=GUID, hive="HKLM", view="32", entry_id="reg:HKLM:32:" + GUID)
    assert u.resolve_uninstall({"application": "contoso suite"}, [a, b]).entry is not None


@pytest.mark.parametrize("line", [
    r'"C:\Program Files\A B\u.exe" /S "--dir=C:\x y"',
    r'C:\a\b.exe "quoted arg" plain \"esc\" trailing\\',
    r'"C:\x.exe" a\\\"b "c d" e""f',
])
def test_python_argv_matches_command_line_to_argv(line):
    assert u._argv_python(line) == (u._argv_ctypes(line) if os.name == "nt" else u._argv_python(line))


def test_quote_argument_round_trips():
    args = ["plain", "with space", 'quote"inside', "trail\\", "C:\\dir with\\", ""]
    line = "x " + " ".join(u.quote_argument(a) for a in args)
    assert u.split_command_line(line)[1:] == args


def test_parse_quoted_and_unquoted_paths_with_spaces(monkeypatch):
    exe = r"C:\Program Files\Contoso Tool\uninst.exe"
    monkeypatch.setattr(u, "_is_file", lambda p: p == exe)
    quoted = u.parse_uninstall_command(f'"{exe}" /x "C:\\Data Dir"')
    assert quoted.executable == exe and quoted.arguments == ["/x", "C:\\Data Dir"]
    unquoted = u.parse_uninstall_command(f"{exe} /S")
    assert unquoted.executable == exe and unquoted.arguments == ["/S"] and unquoted.raw_arguments == "/S"


def test_msiexec_install_switch_is_normalized_to_remove(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    entry = _entry("Odd MSI", uninstall_string=f"MsiExec.exe /I{GUID2}", hive="HKLM", view="64")
    plan = u.build_plan(entry)
    assert plan.kind == "msi" and plan.parameters == f"/x {GUID2}"
    assert plan.executable.casefold() == r"c:\windows\system32\msiexec.exe"
    assert u.build_plan(entry, quiet=True).parameters == f"/x {GUID2} /passive"
    registry_entry = u.entry_from_values("HKLM", "64", "Odd", {"DisplayName": "Odd",
                                                               "UninstallString": f"MsiExec.exe /I{GUID2}"})
    assert registry_entry.kind == "msi" and registry_entry.product_code == GUID2


@pytest.mark.parametrize("command,reason", [
    (r'"C:\Windows\System32\cmd.exe" /c del x', "shell or script host"),
    (r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -File u.ps1", "shell or script host"),
    (r"C:\Program Files\PowerShell\7\pwsh.exe -c x", "shell or script host"),
    (r"C:\Windows\System32\mshta.exe http://x", "shell or script host"),
    (r"C:\Windows\System32\wscript.exe u.vbs", "shell or script host"),
    (r"C:\Windows\System32\rundll32.exe C:\Windows\System32\url.dll,OpenURL x", "rundll32"),
    (r"C:\Users\me\AppData\Local\Temp\setup\uninst.exe /x", "temporary folder"),
    (r"uninst.exe /x", "absolute"),
])
def test_dangerous_launchers_are_refused(monkeypatch, command, reason):
    monkeypatch.setattr(u, "_is_file", lambda p: PureWin(p).is_absolute() and p.lower().endswith((".exe", ".dll")))
    entry = _entry("Bad", uninstall_string=command)
    plan = u.build_plan(entry)
    assert plan.refused and reason in plan.refused
    with pytest.raises(ValueError, match="ms-settings:appsfeatures"):
        u.simulate_uninstall({"application": "Bad"}, [entry])
    result = u.uninstall({"application": "Bad"}, entries=[entry],
                         launcher=lambda p: pytest.fail("refused plan must not launch"))
    assert result["status"] == "refused" and result["verified"] is False


def PureWin(p):
    from pathlib import PureWindowsPath
    return PureWindowsPath(p)


def test_rundll32_with_dll_in_install_location_is_allowed(monkeypatch):
    monkeypatch.setattr(u, "_is_file", lambda p: True)
    entry = _entry("Old", install_location=r"C:\Apps\Old",
                   uninstall_string=r"C:\Windows\System32\rundll32.exe C:\Apps\Old\setup.dll,Uninstall")
    assert u.build_plan(entry).refused is None


def test_simulate_never_executes_and_reports_preview(monkeypatch):
    monkeypatch.setattr(u, "_is_file", lambda p: True)
    import senti.windows.launch as launch
    monkeypatch.setattr(launch, "shell_execute", lambda *a, **k: pytest.fail("simulate executed"))
    monkeypatch.setattr(u, "_remove_package", lambda *a, **k: pytest.fail("simulate removed"))
    machine = _entry("Contoso Tool", hive="HKLM", view="64", entry_id="reg:HKLM:64:ContosoTool",
                     publisher="Contoso", version="3.1", size_kb=10240, install_location=r"C:\Program Files\Contoso Tool",
                     uninstall_string=r'"C:\Program Files\Contoso Tool\uninst.exe" /x',
                     quiet_uninstall_string=r'"C:\Program Files\Contoso Tool\uninst.exe" /x /quiet')
    preview = u.simulate_uninstall({"application": "contoso tool", "quiet": True}, [machine])
    assert preview["kind"] == "exe" and preview["needs_elevation"] is True
    assert preview["command"] == r'"C:\Program Files\Contoso Tool\uninst.exe" /x /quiet'
    assert preview["quiet_available"] and preview["size_mb"] == 10.0
    assert preview["recovery"] == "reinstall required; not automatically reversible"
    assert preview["executes"] is False
    msix = _entry("Fabrikam Paint", kind="msix", hive=None, view=None, entry_id="msix:Paint_1_x64__abc",
                  package_full_name="Paint_1_x64__abc", uninstall_string=None)
    assert u.simulate_uninstall({"application": "fabrikam paint"}, [msix])["needs_elevation"] is False


def test_elevation_verb_only_for_per_machine_entries(monkeypatch):
    calls = []
    import senti.windows.launch as launch
    monkeypatch.setattr(launch, "shell_execute", lambda f, p, verb=None, directory=None: calls.append((f, p, verb)) or 42)
    monkeypatch.setattr(u, "_is_file", lambda p: True)
    machine = _entry("M", hive="HKLM", view="64", uninstall_string=r'"C:\Program Files\M\u.exe" /S')
    user = _entry("U", uninstall_string=r'"C:\Users\me\AppData\Local\U\u.exe" /S')
    assert u._launch(u.build_plan(machine)) == 42
    u._launch(u.build_plan(user))
    assert calls == [(r"C:\Program Files\M\u.exe", "/S", "runas"), (r"C:\Users\me\AppData\Local\U\u.exe", "/S", None)]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_wait_for_removal_states():
    clock = FakeClock()
    polls = iter([True, True, False])
    assert u.wait_for_removal(lambda: next(polls), timeout=60, clock=clock, sleep=clock.sleep)[0] == "removed"
    clock = FakeClock()
    assert u.wait_for_removal(lambda: True, timeout=60, clock=clock, sleep=clock.sleep) == ("in_progress", 60.0)
    clock = FakeClock()
    status, waited = u.wait_for_removal(lambda: True, timeout=600, activity=lambda: False, exit_grace=15,
                                        clock=clock, sleep=clock.sleep)
    assert status == "still_installed" and waited < 30
    cancel = threading.Event()
    cancel.set()
    assert u.wait_for_removal(lambda: True, timeout=60, cancel=cancel)[0] == "cancelled"
    assert u.wait_for_removal(lambda: 1 / 0, timeout=0)[0] == "in_progress"  # errors are not proof of removal


def test_uninstall_reports_verified_only_when_entry_disappears(monkeypatch):
    monkeypatch.setattr(u, "_is_file", lambda p: True)
    entry = _entry("Gone App", uninstall_string=r'"C:\Apps\Gone\u.exe"')
    state = {"present": True}

    def launcher(plan):
        state["present"] = False
        return None

    clock = FakeClock()
    done = u.uninstall({"application": "gone app"}, entries=[entry], launcher=launcher,
                       present=lambda e: state["present"], clock=clock, sleep=clock.sleep)
    assert done["status"] == "removed" and done["verified"] is True
    clock = FakeClock()
    pending = u.uninstall({"application": "gone app", "wait_seconds": 30}, entries=[entry],
                          launcher=lambda plan: None, present=lambda e: True, clock=clock, sleep=clock.sleep)
    assert pending["status"] == "in_progress" and pending["verified"] is False


def test_uac_decline_and_msix_removal(monkeypatch):
    monkeypatch.setattr(u, "_is_file", lambda p: True)
    entry = _entry("Admin App", hive="HKLM", view="64", uninstall_string=r'"C:\Program Files\A\u.exe"')

    def declined(plan):
        error = OSError("cancelled")
        error.winerror = 1223
        raise error

    result = u.uninstall({"application": "admin app"}, entries=[entry], launcher=declined)
    assert result["status"] == "cancelled" and result["verified"] is False
    removed = []
    msix = _entry("Fabrikam Paint", kind="msix", hive=None, view=None, entry_id="msix:Paint_1_x64__abc",
                  package_full_name="Paint_1_x64__abc", uninstall_string=None)
    clock = FakeClock()
    out = u.uninstall({"entry_id": "msix:Paint_1_x64__abc"}, entries=[msix],
                      remover=lambda e, t: removed.append(e.package_full_name),
                      present=lambda e: not removed, clock=clock, sleep=clock.sleep)
    assert removed == ["Paint_1_x64__abc"] and out["verified"] is True and out["kind"] == "msix"


def test_uninstall_ambiguity_returns_candidates_without_launching():
    entries = [_entry("Microsoft Teams"), _entry("Microsoft Teams (personal)")]
    out = u.uninstall({"application": "teams"}, entries=entries, launcher=lambda p: pytest.fail("guessed"))
    assert out["status"] == "ambiguous" and len(out["candidates"]) == 2 and out["verified"] is False
