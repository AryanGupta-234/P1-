from apex.windows.app_catalog import AppDiscovery, AppRecord

def test_app_resolution_prefers_exact_alias_match():
    records = [
        AppRecord("Brave", r"C:\Program Files\Brave\brave.exe", ("Brave", "browser"), "Brave", "1", "app_paths", available=True),
        AppRecord("Brave Beta", r"C:\Program Files\Brave Beta\brave.exe", ("Brave Beta",), "Brave", "2", "app_paths", available=True),
    ]
    result = AppDiscovery.resolve(records, "browser")
    assert len(result) == 1
    assert result[0].display_name == "Brave"


def test_app_scan_rejects_unbounded_duration():
    discovery = AppDiscovery()
    try:
        list(discovery.scan_volume("C:\\", max_seconds=999))
    except (OSError, ValueError):
        pass
    else:
        raise AssertionError("scan duration must be bounded")
