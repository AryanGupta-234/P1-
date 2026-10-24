"""Focused tests for the local Windows documentation index."""
import tempfile
from pathlib import Path

import pytest

from sentinel.windows_knowledge import WindowsKnowledgeStore, _TextExtractor


def make_store():
    temp = tempfile.TemporaryDirectory()
    return temp, WindowsKnowledgeStore(Path(temp.name) / "knowledge.db")


def test_official_source_registration_chunks_and_version_filtered_retrieval():
    temp, store = make_store()
    try:
        source = store.register_source(
            "https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/",
            "Windows driver diagnostics", component="drivers", min_build=22000, max_build=26000,
            windows_edition="pro", architecture="x64", api_version="WDK-10",
            licence="Microsoft documentation",
        )
        body = ("Driver verification and device diagnostics.\n\n"
                "Inspect provider, version and hardware applicability. SFC and DISM are separate servicing tools. "
                "Confirm the exact hardware identifier before selecting a driver package.")
        indexed = store.ingest_text(source["source_id"], body)
        assert indexed["inserted"] is True and indexed["chunks"] >= 1
        assert store.ingest_text(source["source_id"], body)["inserted"] is False
        result = store.search("hardware identifier driver package", windows_build=22631,
                              windows_edition="pro", architecture="x64")
        assert result["result_count"] >= 1
        item = result["results"][0]
        assert item["source"]["publisher"] == "Microsoft"
        assert item["source"]["url"] == source["url"]
        assert item["document"]["sha256"] == indexed["content_sha256"]
        assert item["citation"].startswith("sentinel-kb:")
        assert item["windows_build"]["compatibility"] == "matched"
        assert item["windows_edition"]["required"] == "pro"
        assert item["architecture"]["required"] == "x64"
        assert store.search("hardware identifier", windows_build=26100,
                            windows_edition="pro", architecture="x64")["result_count"] == 0
        assert store.search("hardware identifier", windows_build=22631,
                            windows_edition="home", architecture="x64")["result_count"] == 0
        assert store.search("hardware identifier", windows_build=22631,
                            windows_edition="pro", architecture="arm64")["result_count"] == 0
    finally:
        temp.cleanup()


def test_source_allowlist_rejects_non_https_and_untrusted_hosts():
    temp, store = make_store()
    try:
        with pytest.raises(ValueError, match="HTTPS"):
            store.register_source("http://learn.microsoft.com/windows", "not secure")
        with pytest.raises(ValueError, match="allowlist"):
            store.register_source("https://example.com/windows", "untrusted")
        with pytest.raises(ValueError, match="allowlist"):
            store.register_source("https://learn.microsoft.com.evil.example/docs", "suffix spoof")
    finally:
        temp.cleanup()


def test_inactive_source_is_excluded_but_document_history_is_retained():
    temp, store = make_store()
    try:
        source = store.register_source("https://support.microsoft.com/windows", "Support article",
                                       component="windows")
        store.ingest_text(source["source_id"], "Windows network adapter troubleshooting and DNS resolver checks.")
        store.set_source_status(source["source_id"], "inactive")
        assert store.search("network adapter DNS")["result_count"] == 0
        status = store.status()
        assert status["sources"] == 0 and status["documents"] == 1
    finally:
        temp.cleanup()


def test_html_extractor_omits_script_and_navigation_payloads():
    parser = _TextExtractor()
    parser.feed("<html><nav>menu</nav><main><h1>Windows repair</h1><p>Use SFC safely.</p><script>bad()</script></main></html>")
    content = parser.text()
    assert "Windows repair" in content and "Use SFC safely" in content
    assert "bad()" not in content and "menu" not in content
