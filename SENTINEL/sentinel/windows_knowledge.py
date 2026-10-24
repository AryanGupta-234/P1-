"""Local, provenance-aware Windows documentation registry and retrieval.

This module never executes retrieved instructions. URL ingestion is user-triggered,
HTTPS-only, limited to explicitly approved vendor documentation domains, bounded
in size/time, and rendered to plain text before local indexing.
"""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from pathlib import Path
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .core import DB_PATH

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_CHARS = 1_500_000
MAX_CHUNKS = 1536
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 140
ALLOWED_HOSTS = (
    "learn.microsoft.com", "support.microsoft.com", "techcommunity.microsoft.com",
    "blogs.windows.com", "asus.com", "lenovo.com", "dell.com", "hp.com",
    "msi.com", "acer.com", "intel.com", "nvidia.com", "amd.com",
)
COMPONENTS = frozenset({
    "windows", "kernel", "scheduler", "process", "memory", "storage", "network",
    "power", "pnp", "drivers", "servicing", "reliability", "security",
    "performance", "wpr-etw", "sysinternals", "oem", "other",
})
_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "when", "where",
    "what", "how", "why", "are", "was", "were", "can", "could", "should",
    "would", "your", "you", "into", "only", "not", "than", "then", "have",
    "has", "had", "does", "did", "will", "shall", "use", "using", "windows",
})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _TextExtractor(HTMLParser):
    """Extract readable HTML text; scripts, styles, navigation and forms are ignored."""
    _SKIP = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "header", "form"}
    _BLOCK = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "li", "pre", "br", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag in self._SKIP:
            self._skip_depth += 1
        if not self._skip_depth and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        if not self._skip_depth and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            value = data.strip()
            if value:
                self.parts.append(value + " ")

    def text(self):
        value = html.unescape(" ".join(self.parts))
        value = re.sub(r"[ \t\xa0]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def _validated_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Source URL must be a valid HTTPS documentation URL.")
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (parsed.scheme.casefold() != "https" or not host or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.query or parsed.fragment):
        raise ValueError("Only clean HTTPS URLs without credentials, query strings or fragments are accepted.")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS):
        raise ValueError("Source host is not on the official Windows/OEM documentation allowlist.")
    if not parsed.path.startswith("/") or "\\" in parsed.path or len(parsed.path) > 1800:
        raise ValueError("Source URL path is invalid.")
    return urlunparse(("https", host, parsed.path.rstrip("/") or "/", "", "", ""))


def _publisher_for(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host.endswith("microsoft.com") or host.endswith("windows.com"):
        return "Microsoft"
    return {
        "asus.com": "ASUS", "lenovo.com": "Lenovo", "dell.com": "Dell",
        "hp.com": "HP", "msi.com": "MSI", "acer.com": "Acer",
        "intel.com": "Intel", "nvidia.com": "NVIDIA", "amd.com": "AMD",
    }.get(next((domain for domain in ALLOWED_HOSTS if host == domain or host.endswith("." + domain)), ""), "Official vendor")


def _build_context() -> dict:
    import platform
    import sys
    info = {"os": platform.system(), "release": platform.release(), "version": platform.version(),
            "architecture": platform.machine(), "build": None}
    info["architecture"] = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(
        str(info["architecture"]).casefold(), str(info["architecture"]).casefold())
    info["edition"] = None
    if sys.platform == "win32":
        try:
            info["build"] = int(sys.getwindowsversion().build)
        except (AttributeError, OSError, TypeError, ValueError):
            match = re.search(r"\.(\d+)\.", info["version"])
            if match:
                info["build"] = int(match.group(1))
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                                0, winreg.KEY_READ) as key:
                product = str(winreg.QueryValueEx(key, "EditionID")[0] or "").casefold()
                if "enterprise" in product:
                    info["edition"] = "enterprise"
                elif "education" in product:
                    info["edition"] = "education"
                elif "server" in product:
                    info["edition"] = "server"
                elif "professional" in product or product == "pro":
                    info["edition"] = "pro"
                elif "core" in product or "home" in product:
                    info["edition"] = "home"
        except (ImportError, OSError, ValueError):
            pass
    return info


def _terms(value: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9_+#.-]{2,}", value.casefold())
    return list(dict.fromkeys(term for term in terms if term not in _STOP_WORDS))[:20]


def _chunk_text(content: str) -> list[str]:
    text = re.sub(r"\r\n?", "\n", content).strip()
    if not text:
        return []
    chunks, start, complete = [], 0, False
    while start < len(text) and len(chunks) < MAX_CHUNKS:
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            boundary = max(text.rfind("\n", start + CHUNK_CHARS // 2, end),
                           text.rfind(". ", start + CHUNK_CHARS // 2, end))
            if boundary > start:
                end = boundary + (1 if text[boundary] == "\n" else 2)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            complete = True
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    if not complete:
        raise ValueError("Document exceeded the complete-index chunk budget; no partial document was stored.")
    return chunks


class WindowsKnowledgeStore:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS win_knowledge_sources(
              source_id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
              publisher TEXT NOT NULL, licence TEXT NOT NULL, component TEXT NOT NULL,
              min_build INTEGER, max_build INTEGER, windows_edition TEXT,
              architecture TEXT, api_version TEXT,
              status TEXT NOT NULL DEFAULT 'active',
              created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_win_knowledge_sources_component
              ON win_knowledge_sources(component,status);
            CREATE TABLE IF NOT EXISTS win_knowledge_documents(
              document_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
              content_sha256 TEXT NOT NULL, content_chars INTEGER NOT NULL,
              ingested_at REAL NOT NULL, UNIQUE(source_id,content_sha256));
            CREATE INDEX IF NOT EXISTS ix_win_knowledge_documents_source
              ON win_knowledge_documents(source_id,ingested_at DESC);
            CREATE TABLE IF NOT EXISTS win_knowledge_chunks(
              chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
              content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
              UNIQUE(document_id,ordinal));
            CREATE INDEX IF NOT EXISTS ix_win_knowledge_chunks_document
              ON win_knowledge_chunks(document_id,ordinal);
            """)
            # Additive migration for any preview deployment that created v1 tables.
            columns = {row[1] for row in db.execute("PRAGMA table_info(win_knowledge_sources)")}
            for name, sql_type in (("windows_edition", "TEXT"), ("architecture", "TEXT"), ("api_version", "TEXT")):
                if name not in columns:
                    db.execute(f"ALTER TABLE win_knowledge_sources ADD COLUMN {name} {sql_type}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=12)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=12000")
            db.execute("PRAGMA journal_mode=WAL")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _source(row):
        return {key: row[key] for key in (
            "source_id", "url", "title", "publisher", "licence", "component",
            "min_build", "max_build", "windows_edition", "architecture", "api_version",
            "status", "created_at", "updated_at"
        )}

    def register_source(self, url: str, title: str, *, component="other",
                        licence="not_recorded", min_build=None, max_build=None,
                        windows_edition=None, architecture=None, api_version=None) -> dict:
        canonical = _validated_url(url)
        title = str(title or "").strip()
        if not title or len(title) > 240:
            raise ValueError("Source title must contain 1–240 characters.")
        component = str(component or "other").casefold()
        if component not in COMPONENTS:
            raise ValueError("Unsupported Windows knowledge component.")
        licence = str(licence or "not_recorded").strip()[:120]
        edition = str(windows_edition or "").casefold().strip() or None
        if edition not in (None, "any", "home", "pro", "enterprise", "education", "server"):
            raise ValueError("Windows edition must be any, home, pro, enterprise, education or server.")
        arch = str(architecture or "").casefold().strip() or None
        if arch == "amd64":
            arch = "x64"
        if arch not in (None, "any", "x64", "x86", "arm64"):
            raise ValueError("Architecture must be any, x64, x86 or arm64.")
        api_version = str(api_version or "").strip()[:80] or None
        if min_build is not None:
            min_build = int(min_build)
            if not 7600 <= min_build <= 99999:
                raise ValueError("Minimum Windows build is outside the supported range.")
        if max_build is not None:
            max_build = int(max_build)
            if not 7600 <= max_build <= 99999:
                raise ValueError("Maximum Windows build is outside the supported range.")
        if min_build is not None and max_build is not None and min_build > max_build:
            raise ValueError("Minimum build cannot exceed maximum build.")
        now, publisher = time.time(), _publisher_for(canonical)
        with self.connect() as db:
            existing = db.execute("SELECT source_id FROM win_knowledge_sources WHERE url=?", (canonical,)).fetchone()
            if existing:
                source_id = existing["source_id"]
                db.execute("""UPDATE win_knowledge_sources SET title=?,publisher=?,licence=?,
                           component=?,min_build=?,max_build=?,windows_edition=?,architecture=?,api_version=?,
                           status='active',updated_at=? WHERE source_id=?""",
                           (title, publisher, licence, component, min_build, max_build,
                            edition, arch, api_version, now, source_id))
            else:
                source_id = uuid.uuid4().hex
                db.execute("""INSERT INTO win_knowledge_sources
                           (source_id,url,title,publisher,licence,component,min_build,max_build,
                            windows_edition,architecture,api_version,status,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (source_id, canonical, title, publisher, licence, component,
                            min_build, max_build, edition, arch, api_version, "active", now, now))
            row = db.execute("SELECT * FROM win_knowledge_sources WHERE source_id=?", (source_id,)).fetchone()
        return self._source(row)

    def list_sources(self, limit=100) -> list[dict]:
        limit = min(200, max(1, int(limit)))
        with self.connect() as db:
            rows = db.execute("""SELECT s.*,COUNT(DISTINCT d.document_id) AS document_count,
                              COUNT(c.chunk_id) AS chunk_count
                              FROM win_knowledge_sources s
                              LEFT JOIN win_knowledge_documents d ON d.source_id=s.source_id
                              LEFT JOIN win_knowledge_chunks c ON c.document_id=d.document_id
                              GROUP BY s.source_id ORDER BY s.updated_at DESC LIMIT ?""", (limit,)).fetchall()
        result = []
        for row in rows:
            item = self._source(row)
            item.update(document_count=int(row["document_count"]), chunk_count=int(row["chunk_count"]))
            result.append(item)
        return result

    def set_source_status(self, source_id: str, status: str) -> dict:
        if status not in ("active", "inactive"):
            raise ValueError("Source status must be active or inactive.")
        with self.connect() as db:
            cur = db.execute("UPDATE win_knowledge_sources SET status=?,updated_at=? WHERE source_id=?",
                             (status, time.time(), str(source_id)))
            if cur.rowcount != 1:
                raise ValueError("Knowledge source was not found.")
            row = db.execute("SELECT * FROM win_knowledge_sources WHERE source_id=?", (source_id,)).fetchone()
        return self._source(row)

    def ingest_text(self, source_id: str, content: str, *, title=None) -> dict:
        if not isinstance(content, str):
            raise ValueError("Knowledge content must be UTF-8 text.")
        content = unicodedata.normalize("NFC", content).replace("\x00", "")
        content = content.strip()
        if not content or len(content) > MAX_DOCUMENT_CHARS:
            raise ValueError("Document must contain 1–1,500,000 characters.")
        chunks = _chunk_text(content)
        if not chunks or len(chunks) > MAX_CHUNKS:
            raise ValueError("Document exceeded the bounded chunk count.")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        now, document_id = time.time(), uuid.uuid4().hex
        with self.connect() as db:
            source = db.execute("SELECT title,status FROM win_knowledge_sources WHERE source_id=?",
                                (str(source_id),)).fetchone()
            if not source or source["status"] != "active":
                raise ValueError("Knowledge source is missing or inactive.")
            existing = db.execute("SELECT document_id FROM win_knowledge_documents WHERE source_id=? AND content_sha256=?",
                                  (str(source_id), digest)).fetchone()
            if existing:
                doc_id, inserted = existing["document_id"], False
            else:
                db.execute("""INSERT INTO win_knowledge_documents
                           (document_id,source_id,title,content_sha256,content_chars,ingested_at)
                           VALUES(?,?,?,?,?,?)""",
                           (document_id, str(source_id), str(title or source["title"])[:240], digest, len(content), now))
                for ordinal, chunk in enumerate(chunks):
                    chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                    db.execute("""INSERT INTO win_knowledge_chunks
                               (chunk_id,document_id,ordinal,content,content_sha256)
                               VALUES(?,?,?,?,?)""",
                               (uuid.uuid4().hex, document_id, ordinal, chunk, chunk_hash))
                doc_id, inserted = document_id, True
        return {"document_id": doc_id, "source_id": str(source_id), "content_sha256": digest,
                "content_chars": len(content), "chunks": len(chunks), "inserted": inserted,
                "ingested_at": now}

    def ingest_url(self, source_id: str, *, timeout=12) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM win_knowledge_sources WHERE source_id=? AND status='active'",
                             (str(source_id),)).fetchone()
        if not row:
            raise ValueError("Active knowledge source was not found.")
        url = _validated_url(row["url"])
        headers = {"User-Agent": "SENTINEL-WindowsKnowledge/1.0", "Accept": "text/html,text/plain;q=0.9"}
        opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler())
        request = Request(url, headers=headers, method="GET")
        try:
            response = opener.open(request, timeout=max(3, min(20, int(timeout))))
        except HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                location = error.headers.get("Location", "")
                redirect_url = _validated_url(urljoin(url, location))
                if urlparse(redirect_url).hostname != urlparse(url).hostname:
                    raise ValueError("Documentation redirects to a different host; ingestion stopped.")
                response = opener.open(Request(redirect_url, headers=headers, method="GET"),
                                       timeout=max(3, min(20, int(timeout))))
            else:
                raise RuntimeError(f"Documentation server returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"Official documentation could not be reached: {type(error).__name__}.") from error
        with response:
            status = int(getattr(response, "status", 200) or 200)
            if status != 200:
                raise RuntimeError(f"Documentation server returned HTTP {status}.")
            content_type = str(response.headers.get("Content-Type", "")).casefold()
            if not any(kind in content_type for kind in ("text/html", "text/plain", "application/xhtml")):
                raise ValueError("Only HTML or plain-text documentation pages can be indexed.")
            raw = response.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ValueError("Documentation response exceeded the 2 MiB ingestion limit.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                source_text = raw.decode(encoding, errors="replace")
            except LookupError:
                source_text = raw.decode("utf-8", errors="replace")
        if "html" in content_type or "xhtml" in content_type:
            parser = _TextExtractor()
            parser.feed(source_text[:MAX_DOCUMENT_CHARS])
            text = parser.text()
        else:
            text = source_text
        if not text.strip():
            raise ValueError("Documentation page contained no readable text.")
        return self.ingest_text(source_id, text, title=row["title"])

    def search(self, query: str, *, windows_build=None, windows_edition=None,
               architecture=None, components=None, limit=8) -> dict:
        query = str(query or "").strip()
        if not query or len(query) > 240:
            raise ValueError("Search query must contain 1–240 characters.")
        terms = _terms(query)
        if not terms:
            raise ValueError("Search query did not contain searchable terms.")
        limit = min(20, max(1, int(limit)))
        if windows_build is None:
            windows_build = _build_context().get("build")
        try:
            build = int(windows_build) if windows_build is not None else None
        except (TypeError, ValueError):
            build = None
        current = _build_context()
        edition = str(windows_edition or current.get("edition") or "").casefold().strip()
        arch = str(architecture or current.get("architecture") or "").casefold().strip()
        if arch == "amd64":
            arch = "x64"
        selected = set()
        if components:
            selected = {str(item).casefold() for item in components if str(item).casefold() in COMPONENTS}
        sql = """SELECT c.chunk_id,c.ordinal,c.content,d.document_id,d.title AS document_title,
                        d.content_sha256,d.ingested_at,s.source_id,s.url,s.title AS source_title,
                        s.publisher,s.licence,s.component,s.min_build,s.max_build,
                        s.windows_edition,s.architecture,s.api_version
                 FROM win_knowledge_chunks c
                 JOIN win_knowledge_documents d ON d.document_id=c.document_id
                 JOIN win_knowledge_sources s ON s.source_id=d.source_id
                 WHERE s.status='active'"""
        args = []
        if build is not None:
            sql += " AND (s.min_build IS NULL OR s.min_build<=?) AND (s.max_build IS NULL OR s.max_build>=?)"
            args.extend([build, build])
        if edition:
            sql += " AND (s.windows_edition IS NULL OR s.windows_edition='any' OR s.windows_edition=?)"
            args.append(edition)
        if arch:
            sql += " AND (s.architecture IS NULL OR s.architecture='any' OR s.architecture=?)"
            args.append(arch)
        if selected:
            sql += " AND s.component IN (" + ",".join("?" for _ in selected) + ")"
            args.extend(sorted(selected))
        sql += " ORDER BY d.ingested_at DESC LIMIT 5000"
        with self.connect() as db:
            rows = db.execute(sql, args).fetchall()
        ranked = []
        phrase = query.casefold()
        for row in rows:
            body = row["content"].casefold()
            counts = {term: len(re.findall(re.escape(term), body)) for term in terms}
            matched = [term for term, count in counts.items() if count]
            if not matched:
                continue
            coverage = len(matched) / len(terms)
            frequency = sum(min(5, counts[term]) for term in matched)
            score = coverage * 0.7 + min(0.25, frequency / max(1, len(terms) * 20))
            if phrase in body:
                score += 0.2
            pos = min((body.find(term) for term in matched), default=0)
            begin = max(0, pos - 180)
            snippet = row["content"][begin:begin + 620].strip()
            if begin:
                snippet = "…" + snippet
            if len(row["content"]) > begin + 620:
                snippet += "…"
            min_build, max_build = row["min_build"], row["max_build"]
            compatibility = "matched" if build is not None and (min_build is not None or max_build is not None) else (
                "unspecified" if min_build is None and max_build is None else "build_unknown")
            ranked.append({
                "score": round(min(1.0, score), 4), "matched_terms": matched, "snippet": snippet,
                "citation": f"sentinel-kb:{row['document_id']}:{row['ordinal']}",
                "source": {"source_id": row["source_id"], "url": row["url"],
                           "title": row["source_title"], "publisher": row["publisher"],
                           "licence": row["licence"], "component": row["component"]},
                "document": {"id": row["document_id"], "title": row["document_title"],
                             "sha256": row["content_sha256"], "ingested_at": row["ingested_at"]},
                "windows_build": {"current": build, "minimum": min_build, "maximum": max_build,
                                  "compatibility": compatibility},
                "windows_edition": {"current": edition or None, "required": row["windows_edition"]},
                "architecture": {"current": arch or None, "required": row["architecture"]},
                "api_version": row["api_version"],
            })
        ranked.sort(key=lambda item: (-item["score"], -float(item["document"]["ingested_at"])))
        return {"query": query, "windows": _build_context(), "indexed_chunks": len(rows),
                "result_count": min(limit, len(ranked)), "results": ranked[:limit],
                "retrieval": "local_lexical_v1", "external_model_used": False}

    def status(self) -> dict:
        with self.connect() as db:
            sources = int(db.execute("SELECT COUNT(*) FROM win_knowledge_sources WHERE status='active'").fetchone()[0])
            docs = int(db.execute("SELECT COUNT(*) FROM win_knowledge_documents").fetchone()[0])
            chunks = int(db.execute("SELECT COUNT(*) FROM win_knowledge_chunks").fetchone()[0])
            latest = db.execute("SELECT MAX(ingested_at) FROM win_knowledge_documents").fetchone()[0]
        return {"engine": "sentinel-windows-knowledge-v1", "mode": "local_only",
                "sources": sources, "documents": docs, "chunks": chunks, "last_ingested_at": latest,
                "source_allowlist": list(ALLOWED_HOSTS), "max_document_bytes": MAX_DOCUMENT_BYTES,
                "execution_enabled": False, "external_model_used": False, "windows": _build_context()}


STORE = WindowsKnowledgeStore()
