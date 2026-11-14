import pytest

from senti.windows import settings_catalog, settings_discovery as discovery

NS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\ControlPanel\NameSpace"
FD = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderDescriptions"
DEVICE_MANAGER = "{74246BFC-4C96-11D0-ABEF-0020AF6B0B7A}"
CUSTOM_ITEM = "{11111111-2222-3333-4444-555555555555}"
NAMELESS_ITEM = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
EVIL_ITEM = "{99999999-9999-9999-9999-999999999999}"
USER_ITEM = "{12345678-1234-1234-1234-123456789ABC}"


class FakeWinreg:
    """Minimal read-only winreg stand-in: keys are backslash paths, values are dicts."""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"
    HKEY_CLASSES_ROOT = "HKCR"
    KEY_READ = 0x20019

    def __init__(self, tree):
        self.tree = {key.lower(): (key, values) for key, values in tree.items()}
        self.opened = []

    def OpenKey(self, key, sub_key, reserved=0, access=0):  # noqa: N802 - mirrors winreg
        path = f"{key}\\{sub_key}" if sub_key else key
        if path.lower() not in self.tree:
            raise OSError(path)
        self.opened.append(path)
        return path

    def EnumKey(self, key, index):  # noqa: N802
        prefix = key.lower() + "\\"
        children = sorted({original[len(prefix):].split("\\")[0]
                           for lowered, (original, _values) in self.tree.items()
                           if lowered.startswith(prefix)})
        if index >= len(children):
            raise OSError("no more")
        return children[index]

    def QueryValueEx(self, key, name):  # noqa: N802
        values = self.tree[key.lower()][1]
        if name not in values:
            raise OSError(name)
        return values[name], 1

    def CloseKey(self, key):  # noqa: N802
        pass


def _tree():
    return {
        f"HKLM\\{NS}": {},
        f"HKLM\\{NS}\\{DEVICE_MANAGER}": {},
        f"HKLM\\{NS}\\{CUSTOM_ITEM}": {"": "Vendor Panel"},
        f"HKLM\\{NS}\\{NAMELESS_ITEM}": {},
        f"HKLM\\{NS}\\{EVIL_ITEM}": {},
        f"HKLM\\{NS}\\DelegateFolders": {},
        f"HKCU\\{NS}": {},
        f"HKCU\\{NS}\\{USER_ITEM}": {},
        f"HKCR\\CLSID\\{DEVICE_MANAGER}": {"System.ApplicationName": "Microsoft.DeviceManager",
                                           "LocalizedString": "Device Manager"},
        f"HKCR\\CLSID\\{CUSTOM_ITEM}": {"System.ApplicationName": "Vendor.AudioPanel",
                                        "LocalizedString": "Vendor Audio Console", "InfoTip": "Tune audio"},
        f"HKCR\\CLSID\\{NAMELESS_ITEM}": {"": "Mail (Microsoft Outlook)"},
        f"HKCR\\CLSID\\{EVIL_ITEM}": {"System.ApplicationName": "calc & whoami", "": "Evil"},
        f"HKCR\\CLSID\\{USER_ITEM}": {"System.ApplicationName": "Contoso.UserTool", "LocalizedString": "Contoso Tool"},
        "HKCR\\CLSID\\{ED7BA470-8E54-465E-825C-99712043E01C}": {},
        f"HKLM\\{FD}": {},
        f"HKLM\\{FD}\\{{374DE290-123F-4565-9164-39C4925E467B}}": {"Name": "Downloads"},
        f"HKLM\\{FD}\\{{00000000-0000-0000-0000-000000000001}}": {"Name": "Vendor Stuff", "LocalizedName": "Vendor stuff"},
        f"HKLM\\{FD}\\{{00000000-0000-0000-0000-000000000002}}": {"Name": "..\\..\\escape"},
        f"HKLM\\{FD}\\{{00000000-0000-0000-0000-000000000003}}": {},
    }


@pytest.fixture()
def windows_root(tmp_path):
    system32 = tmp_path / "System32"
    system32.mkdir()
    for name in ("devmgmt.msc", "services.msc", "vendor.msc", "ncpa.cpl", "sysdm.cpl", "vendor.cpl",
                 "bad name!.msc", "notes.txt", "msconfig.exe", "rundll32.exe"):
        (system32 / name).write_text("x")
    (tmp_path / "regedit.exe").write_text("x")
    return str(tmp_path)


def _discover(windows_root, tree=None):
    return discovery.discover(winreg_module=FakeWinreg(tree or _tree()), windows_root=windows_root, use_cache=False)


def test_discovery_reads_namespace_files_and_known_folders(windows_root):
    found = _discover(windows_root)
    assert found["status"]["control_panel"] == "ok"
    names = {item["canonical_name"] for item in found["control_panel"]}
    assert {"Microsoft.DeviceManager", "Vendor.AudioPanel", "Contoso.UserTool"}.issubset(names)
    assert None in names  # nameless CLSID item kept as a shell namespace
    assert all(item["canonical_name"] != "calc & whoami" for item in found["control_panel"])
    files = {item["file"] for item in found["files"]}
    assert files == {"devmgmt.msc", "services.msc", "vendor.msc", "ncpa.cpl", "sysdm.cpl", "vendor.cpl"}
    folders = {item["name"] for item in found["known_folders"]}
    assert folders == {"Downloads", "Vendor Stuff"}
    assert found["utilities"]["regedit.exe"].endswith("regedit.exe")
    assert found["utilities"]["dxdiag.exe"] is None


def test_merge_dedupes_and_marks_source_and_presence(windows_root):
    merged = discovery.merge(settings_catalog.STATIC_SURFACES, _discover(windows_root))
    by_id = {item["id"]: item for item in merged}
    assert len(by_id) == len(merged)

    assert by_id["cp_device_manager"]["source"] == "both" and by_id["cp_device_manager"]["present"] is True
    assert by_id["msc_devmgmt"]["source"] == "both" and by_id["msc_devmgmt"]["path"].endswith("devmgmt.msc")
    assert by_id["msc_gpedit"]["present"] is False  # file scan completed and did not find it
    assert by_id["cpl_sysdm_advanced"]["present"] is True  # tabbed applets share the base file
    assert by_id["shell_downloads"]["source"] == "both"
    assert by_id["shell_startup"]["present"] is False
    assert by_id["clsid_god_mode"]["present"] is True
    assert by_id["clsid_this_pc"]["present"] is False
    assert by_id["util_regedit"]["present"] is True
    assert by_id["util_dxdiag"]["present"] is False
    assert by_id["bluetooth"]["present"] == "unknown"  # ms-settings pages cannot be probed

    discovered = {item["id"]: item for item in merged if item["source"] == "discovered"}
    assert discovered["cp_vendor_audiopanel"]["target"] == "Vendor.AudioPanel"
    assert discovered["cp_contoso_usertool"]["kind"] == "control_name"
    assert discovered["msc_vendor"]["risk"] == "controlled"
    assert discovered["cpl_vendor"]["risk"] == "low"
    assert discovered["shell_vendor_stuff"]["target"] == "shell:Vendor Stuff"
    assert any(item["kind"] == "shell_clsid" and item["title"] == "Mail (Microsoft Outlook)"
               for item in discovered.values())
    # Nothing discovered duplicates a static entry.
    assert "msc_devmgmt_2" not in by_id and "cp_devicemanager" not in by_id
    for item in discovered.values():
        settings_catalog.validate_entry(item)
        assert item["present"] is True


def test_discovery_without_winreg_degrades_to_static(tmp_path):
    found = discovery.discover(winreg_module=None, windows_root=str(tmp_path), use_cache=False)
    assert found["status"]["control_panel"] == "unavailable"
    assert found["status"]["system32_files"] == "unavailable"
    merged = discovery.merge(settings_catalog.STATIC_SURFACES, found)
    assert len(merged) == len(settings_catalog.STATIC_SURFACES)
    assert all(item["source"] == "static" for item in merged)


def test_discovery_survives_a_broken_registry(windows_root):
    class Broken(FakeWinreg):
        def EnumKey(self, key, index):  # noqa: N802
            raise RuntimeError("registry exploded")

    found = discovery.discover(winreg_module=Broken(_tree()), windows_root=windows_root, use_cache=False)
    assert found["status"]["control_panel"].startswith("error")
    assert found["files"]  # other sources still work


def test_discovery_is_bounded(windows_root, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_NAMESPACE_ITEMS", 2)
    monkeypatch.setattr(discovery, "MAX_FOLDERS", 1)
    found = _discover(windows_root)
    assert found["status"]["control_panel"] == "truncated"
    assert found["status"]["known_folders"] == "truncated"
    assert len(found["known_folders"]) <= 1


def test_discovery_is_cached(windows_root, monkeypatch):
    fake = FakeWinreg(_tree())
    monkeypatch.setattr(discovery, "_winreg", fake)
    monkeypatch.setattr(discovery, "windows_directory", lambda: windows_root)
    discovery.clear_cache()
    try:
        first = discovery.discover()
        opened = len(fake.opened)
        assert discovery.discover() is first
        assert len(fake.opened) == opened
        merged = discovery.merged_catalog()
        assert discovery.merged_catalog() is merged
        assert discovery.discover(force=True) is not first
    finally:
        discovery.clear_cache()


def test_summary_counts_sources(windows_root):
    found = _discover(windows_root)
    report = discovery.summary(found)
    assert report["discovered"]["system32_msc"] == 3
    assert report["discovered"]["system32_cpl"] == 3
    assert report["by_source"]["both"] > 0 and report["by_source"]["discovered"] > 0
