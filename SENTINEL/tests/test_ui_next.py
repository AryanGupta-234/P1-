"""Contracts for the React/Vite "Nocturne" UI build served from ui/next."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT = ROOT / "ui" / "next"


def test_next_build_is_committed_and_relative():
    html = (NEXT / "index.html").read_text(encoding="utf-8")
    assert 'id="root"' in html
    # Relative asset URLs: the agent serves the build from /next/, not from the site root.
    assert 'src="./assets/' in html and 'href="./assets/' in html
    # Critical splash must paint before JS (no inline <script>: CSP is script-src 'self').
    assert "splash0" in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert list((NEXT / "assets").glob("index-*.js")) and list((NEXT / "assets").glob("*.css"))


def test_next_ui_uses_the_requested_palette_and_no_remote_assets():
    css = next((NEXT / "assets").glob("*.css")).read_text(encoding="utf-8").lower()
    for colour in ("#171717", "#06110c", "#a31c1b"):
        assert colour in css
    assert "fonts.googleapis" not in css and "http://" not in css and "https://" not in css


def test_boot_is_gated_on_one_request_only():
    src = (ROOT / "ui-next" / "src" / "useSentinel.js").read_text(encoding="utf-8")
    gate = src[src.index('first = await api("/api/snapshot"'):src.index("absorb(first); setPhase")]
    assert gate.count("/api/") == 2  # snapshot + its single retry; nothing else blocks first paint
    assert 'setPhase("ready")' in src


def test_server_serves_next_by_default_and_keeps_classic():
    server = (ROOT / "sentinel" / "server.py").read_text(encoding="utf-8")
    assert '"classic"' in server and "/next/" in server
    assert "immutable" in server and "next/assets/" in server
    assert (ROOT / "ui" / "index.html").is_file()  # classic dashboard remains reachable
