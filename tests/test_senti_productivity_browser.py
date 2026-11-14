import io
import zipfile

import pytest

from senti.store import UnifiedDataStore
from senti.tools import browser_tools
from senti.tools.browser_tools import fetch_page, register_browser_tools, validate_url
from senti.tools.productivity_tools import Productivity, register_productivity_tools
from senti.tools.registry import CapabilityRegistry


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setenv("SENTI_ALLOWED_FILE_ROOTS", str(docs))
    return docs


def test_notes_save_and_search(tmp_path):
    p = Productivity(UnifiedDataStore(tmp_path / "s.sqlite3"))
    p.save_note("Router password location", "It is on the sticker under the router", ["home"])
    p.save_note("Groceries", "milk, eggs")
    assert [n["title"] for n in p.search_notes("router")] == ["Router password location"]
    assert len(p.search_notes("")) == 2


def test_reminders_fire_once_when_due(tmp_path):
    p = Productivity(UnifiedDataStore(tmp_path / "s.sqlite3"))
    past = p.set_reminder("Stand up and stretch", "2020-01-01T09:00:00+05:30")
    p.set_reminder("Future thing", "2099-01-01T09:00:00+00:00")
    assert past["in_the_past"] is True
    due = p.due_reminders()
    assert [d["detail"] for d in due] == ["Stand up and stretch"]
    assert p.due_reminders() == []
    assert [r["text"] for r in p.list_reminders()] == ["Future thing"]
    with pytest.raises(ValueError):
        p.set_reminder("x", "next tuesday")


def test_documents_read_txt_and_docx_and_create_without_overwrite(tmp_path, roots):
    p = Productivity(UnifiedDataStore(tmp_path / "s.sqlite3"))
    (roots / "plan.md").write_text("# Plan\nFix Wi-Fi", encoding="utf-8")
    assert "Fix Wi-Fi" in p.read_document(str(roots / "plan.md"))["text"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml",
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         "<w:body><w:p><w:r><w:t>Hello SENTI</w:t></w:r></w:p></w:body></w:document>")
    (roots / "letter.docx").write_bytes(buffer.getvalue())
    assert p.read_document(str(roots / "letter.docx"))["text"] == "Hello SENTI"
    created = p.create_document(str(roots / "notes.md"), "hello")
    assert created["verified"] is True and (roots / "notes.md").read_text(encoding="utf-8") == "hello"
    with pytest.raises(ValueError, match="never overwrites"):
        p.create_document(str(roots / "notes.md"), "again")
    with pytest.raises(ValueError):
        p.create_document(str(roots / "evil.exe"), "x")
    with pytest.raises(ValueError):
        p.read_document(str(tmp_path / "outside.txt"))


def test_productivity_tools_simulate_and_require_approval(tmp_path, roots):
    registry = CapabilityRegistry()
    register_productivity_tools(registry, UnifiedDataStore(tmp_path / "s.sqlite3"))
    preview = registry.simulate("senti_create_document", {"path": str(roots / "a.txt"), "text": "hi"})
    assert preview["simulation"] == "provider" and not (roots / "a.txt").exists()
    assert registry.dispatch("senti_save_note", {"title": "t", "body": "b"}).status == "approval_required"


def test_url_validation():
    assert validate_url("https://example.com/a") == "https://example.com/a"
    for bad in ("file:///C:/Windows", "javascript:alert(1)", "https://user:pw@example.com", "ftp://x.org"):
        with pytest.raises(ValueError):
            validate_url(bad)
    with pytest.raises(ValueError):
        validate_url("http://example.com", allow_http=False)


class FakeResponse:
    def __init__(self, body, content_type="text/html; charset=utf-8"):
        self.body, self.headers = body, {"Content-Type": content_type}

    def read(self, n):
        return self.body[:n]

    def geturl(self):
        return "https://example.com/"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_page_extracts_text_and_blocks_private_hosts(monkeypatch):
    monkeypatch.setattr(browser_tools, "_public_host", lambda host: True)
    html = b"<html><head><title>Demo</title><script>evil()</script></head><body><p>Hello</p><p>World</p></body></html>"
    result = fetch_page("https://example.com/", opener=lambda req, timeout: FakeResponse(html))
    assert result["title"] == "Demo" and result["text"] == "Hello\nWorld" and "evil" not in result["text"]
    monkeypatch.setattr(browser_tools, "_public_host", lambda host: False)
    with pytest.raises(ValueError, match="private"):
        fetch_page("https://intranet.local/", opener=lambda req, timeout: FakeResponse(html))
    assert browser_tools._public_host.__name__  # patched helper exists


def test_loopback_is_never_public():
    assert browser_tools.__dict__["_public_host"]("localhost") is False


def test_browser_tools_are_approval_gated_and_fetch_needs_controlled_approval():
    registry = CapabilityRegistry()
    register_browser_tools(registry)
    assert registry.tool("senti_fetch_web_page").risk == "controlled"
    assert registry.dispatch("senti_open_url", {"url": "https://example.com"}).status in {"approval_required",
                                                                                           "unavailable"}
    preview = registry.simulate("senti_web_search", {"query": "qwen3.5 benchmarks"})
    assert preview["intended_state"]["engine"] == "bing"
