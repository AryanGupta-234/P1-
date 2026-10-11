from aie.providers.etw_catalog import filter_providers, parse_provider_catalog


SAMPLE = """
Provider Name                              GUID
-------------------------------------------------------------------------------
Microsoft-Windows-Kernel-Process           {22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}
Microsoft-Windows-Kernel-Image              {2cb15d1d-5fc1-11d2-abe1-00a0c911f518}
"""


def test_parse_etw_provider_catalog():
    providers = parse_provider_catalog(SAMPLE)
    assert len(providers) == 2
    assert providers[0].name.startswith("Microsoft-Windows-Kernel-Image")


def test_filter_kernel_providers():
    providers = parse_provider_catalog(SAMPLE)
    selected = filter_providers(providers, "kernel-process")
    assert len(selected) == 1
    assert selected[0]["guid"] == "22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716"


def test_parser_ignores_headers_and_blank_lines():
    assert parse_provider_catalog("Provider Name GUID\n---\n\n") == []
