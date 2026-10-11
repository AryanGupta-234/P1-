import subprocess

import pytest

from aie.providers.etw_catalog import (
    discover_etw_providers,
    filter_providers,
    parse_provider_catalog,
)


SAMPLE_OUTPUT = """
Data Collector Set Provider List
--------------------------------
Microsoft-Windows-Kernel-Process {22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}
Microsoft-Windows-Kernel-Image {2cb15d1d-5fc1-11d2-abe1-00a0c911f518}
AIE-Test-Provider {aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}
"""


def test_parse_provider_catalog_ignores_headers_sorts_and_deduplicates():
    providers = parse_provider_catalog(
        SAMPLE_OUTPUT
        + "\nMicrosoft-Windows-Kernel-Process {22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}"
    )

    assert [provider.name for provider in providers] == [
        "AIE-Test-Provider",
        "Microsoft-Windows-Kernel-Image",
        "Microsoft-Windows-Kernel-Process",
    ]
    assert providers[-1].guid == "22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716"


def test_filter_provider_catalog_is_case_insensitive_and_json_safe():
    providers = parse_provider_catalog(SAMPLE_OUTPUT)
    selected = filter_providers(providers, "kErNeL-pRoCeSs")

    assert selected == [{
        "name": "Microsoft-Windows-Kernel-Process",
        "guid": "22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716",
    }]


def test_discover_catalog_uses_logman_read_only_query():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, SAMPLE_OUTPUT, "")

    providers = discover_etw_providers(runner=runner)

    assert len(providers) == 3
    assert calls[0][0] == ["logman.exe", "query", "providers"]
    assert calls[0][1]["timeout"] == 20.0


def test_discover_catalog_sanitizes_failed_command_output():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 5, "", "PRIVATE USER PATH SHOULD NOT ESCAPE"
        )

    with pytest.raises(RuntimeError) as raised:
        discover_etw_providers(runner=runner)

    assert "PRIVATE USER PATH" not in str(raised.value)
    assert "5" in str(raised.value)


def test_discover_catalog_reports_timeout_without_storing_command_output():
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=1, stderr="private output")

    with pytest.raises(RuntimeError) as raised:
        discover_etw_providers(runner=runner)

    assert "TimeoutExpired" in str(raised.value)
    assert "private output" not in str(raised.value)
