from __future__ import annotations

import pytest

from aie.knowledge.crawler import (
    KnowledgeStore,
    MicrosoftKnowledgeCrawler,
    _MainTextExtractor,
    _validate_url,
)


def test_knowledge_store_add_update_and_unchanged(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    url = "https://github.com/MicrosoftDocs/win32/blob/docs/desktop/windows.md"

    assert store.upsert(
        source="microsoft_github",
        title="Windows desktop APIs",
        url=url,
        content="# Windows desktop APIs\n\nRegistry and ETW references.",
        source_owner="MicrosoftDocs",
        source_repo="win32",
        source_path="desktop/windows.md",
        revision="abc123",
    ) == "added"

    assert store.upsert(
        source="microsoft_github",
        title="Windows desktop APIs",
        url=url,
        content="# Windows desktop APIs\n\nRegistry and ETW references.",
        source_owner="MicrosoftDocs",
        source_repo="win32",
        source_path="desktop/windows.md",
        revision="abc123",
    ) == "unchanged"

    assert store.upsert(
        source="microsoft_github",
        title="Windows desktop APIs",
        url=url,
        content="# Windows desktop APIs\n\nUpdated ETW and registry references.",
        source_owner="MicrosoftDocs",
        source_repo="win32",
        source_path="desktop/windows.md",
        revision="def456",
    ) == "updated"

    stats = store.stats()
    assert stats["documents"] == 1
    assert stats["sources"] == {"microsoft_github": 1}
    results = store.search("registry ETW", limit=5)
    assert len(results) == 1
    assert results[0]["title"] == "Windows desktop APIs"
    assert results[0]["source_path"] == "desktop/windows.md"
    assert "Updated ETW" in results[0]["excerpt"]


def test_knowledge_store_rejects_unapproved_hosts(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    with pytest.raises(ValueError, match="allowlist"):
        store.upsert(
            source="unknown",
            title="Not Microsoft",
            url="https://example.org/page",
            content="Arbitrary source content",
        )


def test_learn_and_github_urls_are_allowed_but_http_is_not():
    assert _validate_url("https://learn.microsoft.com/en-us/windows/win32/etw/") .startswith("https://")
    assert _validate_url(
        "https://github.com/MicrosoftDocs/win32/blob/docs/desktop/windows.md"
    ).startswith("https://")
    with pytest.raises(ValueError, match="allowlist"):
        _validate_url("http://learn.microsoft.com/en-us/windows/")
    with pytest.raises(ValueError, match="allowlist"):
        _validate_url("https://example.com/windows/")


def test_html_extractor_uses_main_content_and_ignores_navigation():
    parser = _MainTextExtractor()
    parser.feed(
        "<html><body><nav>Navigation should not appear</nav>"
        "<main><h1>Windows registry</h1><p>ETW and registry diagnostics.</p>"
        "<script>secret_script_payload</script></main></body></html>"
    )
    extracted = parser.text()
    assert "Windows registry" in extracted
    assert "ETW and registry diagnostics" in extracted
    assert "Navigation should not appear" not in extracted
    assert "secret_script_payload" not in extracted


def test_crawler_only_selects_relevant_markdown_paths(tmp_path):
    crawler = MicrosoftKnowledgeCrawler(KnowledgeStore(tmp_path / "knowledge.sqlite3"))
    assert crawler._path_score("docs/windows/kernel/etw.md") > 0
    assert crawler._path_score("docs/images/kernel-diagram.md") == 0
    assert crawler._path_score("README.md") == 0
