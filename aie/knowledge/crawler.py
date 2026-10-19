"""Curated Microsoft Learn and Microsoft-owned GitHub knowledge crawler.

All network requests are outbound GETs to a strict allowlist. Queries are fixed
Windows-platform topics, sources are validated after redirects, downloads are
size-bounded, and indexed content stays in the local AIE profile.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


LEARN_HOST = "learn.microsoft.com"
GITHUB_API_HOST = "api.github.com"
GITHUB_RAW_HOST = "raw.githubusercontent.com"
_ALLOWED_HOSTS = {LEARN_HOST, GITHUB_API_HOST, GITHUB_RAW_HOST}
_USER_AGENT = "AIE-Sentinel-Microsoft-Knowledge/1.0"
MAX_DOCUMENT_BYTES = 320_000
MAX_DOCUMENT_CHARS = 90_000
DEFAULT_LEARN_QUERIES = (
    "Windows Event Tracing ETW kernel process thread registry",
    "Windows registry functions RegNotifyChangeKeyValue service configuration",
    "Windows driver inventory Win32_SystemDriver PnP signed drivers",
    "Windows services WMI Win32_Service startup configuration",
    "Windows performance counters PDH disk memory processor",
    "Windows Defender Get-MpComputerStatus firewall profiles",
    "Windows system diagnostics boot event logs crash dump",
    "Windows device enumeration Plug and Play driver APIs",
)
GITHUB_SOURCES = (
    ("MicrosoftDocs", "win32", "docs"),
    ("MicrosoftDocs", "windows-driver-docs", "staging"),
    ("microsoft", "Windows-classic-samples", "main"),
)
_PATH_TERMS = {
    "windows": 2, "driver": 5, "kernel": 6, "etw": 7, "registry": 7,
    "service": 4, "performance": 5, "device": 4, "pnp": 5, "cim": 5,
    "wmi": 5, "process": 3, "memory": 3, "event": 3, "system": 2,
    "security": 2, "power": 1, "network": 2,
}
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.+-]{1,48}", re.IGNORECASE)


def _validate_url(url: str, *, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    allowed = _ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    if parsed.scheme != "https" or parsed.hostname not in allowed:
        raise ValueError("Knowledge crawler rejected a URL outside its HTTPS allowlist.")
    if parsed.username or parsed.password:
        raise ValueError("Knowledge crawler rejected URL user information.")
    return url


def _fetch_bytes(url: str, *, max_bytes: int, timeout: float = 20.0) -> bytes:
    _validate_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json, text/markdown, text/html;q=0.9, */*;q=0.5",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            _validate_url(final_url)
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ValueError("Knowledge response exceeded its byte budget.")
                except ValueError as exc:
                    if "byte budget" in str(exc):
                        raise
            body = response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Knowledge source request failed: {type(exc).__name__}") from exc
    if len(body) > max_bytes:
        raise ValueError("Knowledge response exceeded its byte budget.")
    return body


class _MainTextExtractor(HTMLParser):
    """Small stdlib HTML-to-text extractor limited to the document main/article area."""

    _BLOCKS = {
        "p", "div", "section", "article", "main", "h1", "h2", "h3", "h4", "h5",
        "li", "pre", "blockquote", "tr", "dt", "dd", "table",
    }
    _IGNORED = {"script", "style", "svg", "noscript", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main_depth = 0
        self.found_main = False
        self.ignored_depth = 0
        self.total_chars = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "main" or tag == "article":
            self.main_depth += 1
            self.found_main = True
        if self.main_depth <= 0:
            return
        if tag in self._IGNORED:
            self.ignored_depth += 1
        elif self.ignored_depth == 0 and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.main_depth <= 0:
            return
        if tag in self._IGNORED and self.ignored_depth:
            self.ignored_depth -= 1
        if self.ignored_depth == 0 and tag in self._BLOCKS:
            self.parts.append("\n")
        if tag == "main" or tag == "article":
            self.main_depth = max(0, self.main_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.main_depth <= 0 or self.ignored_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.total_chars += len(text)
        if self.total_chars <= MAX_DOCUMENT_CHARS:
            self.parts.append(text)

    def text(self) -> str:
        value = "\n".join(self.parts)
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()[:MAX_DOCUMENT_CHARS]


def _extract_html(body: bytes) -> str:
    parser = _MainTextExtractor()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.text()


def _tokens(value: str) -> list[str]:
    return [item.casefold() for item in _TOKEN.findall(value) if len(item) >= 3][:64]


@dataclass(frozen=True, slots=True)
class CrawlResult:
    started_at: str
    completed_at: str
    learn_queries: int
    learn_documents: int
    github_repositories: int
    github_documents: int
    documents_added: int
    documents_updated: int
    unchanged: int
    failures: int
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeStore:
    """Local SQLite document store with title-weighted lexical retrieval."""

    def __init__(self, path: str | Any) -> None:
        from pathlib import Path

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source_owner TEXT,
                    source_repo TEXT,
                    source_path TEXT,
                    revision TEXT,
                    updated_on TEXT,
                    content_sha256 TEXT NOT NULL,
                    content TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_source ON documents(source)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_fetched ON documents(fetched_at)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def upsert(
        self,
        *,
        source: str,
        title: str,
        url: str,
        content: str,
        source_owner: str | None = None,
        source_repo: str | None = None,
        source_path: str | None = None,
        revision: str | None = None,
        updated_on: str | None = None,
    ) -> str:
        _validate_url(url)
        clean_title = " ".join(title.split())[:300]
        clean_content = content[:MAX_DOCUMENT_CHARS]
        if not clean_title or not clean_content.strip():
            raise ValueError("Knowledge documents require a title and non-empty text.")
        digest = hashlib.sha256(clean_content.encode("utf-8")).hexdigest()
        document_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            existing = db.execute(
                "SELECT content_sha256 FROM documents WHERE url = ?",
                (url,),
            ).fetchone()
            if existing and existing[0] == digest:
                db.execute(
                    "UPDATE documents SET title = ?, revision = ?, updated_on = ?, fetched_at = ? WHERE url = ?",
                    (clean_title, revision, updated_on, now, url),
                )
                return "unchanged"
            db.execute(
                """
                INSERT INTO documents (
                    document_id, source, title, url, source_owner, source_repo,
                    source_path, revision, updated_on, content_sha256, content, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    source=excluded.source,
                    title=excluded.title,
                    source_owner=excluded.source_owner,
                    source_repo=excluded.source_repo,
                    source_path=excluded.source_path,
                    revision=excluded.revision,
                    updated_on=excluded.updated_on,
                    content_sha256=excluded.content_sha256,
                    content=excluded.content,
                    fetched_at=excluded.fetched_at
                """,
                (
                    document_id, source, clean_title, url, source_owner, source_repo,
                    source_path, revision, updated_on, digest, clean_content, now,
                ),
            )
            return "added" if existing is None else "updated"

    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            total = int(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            sources = {
                str(source): int(count)
                for source, count in db.execute(
                    "SELECT source, COUNT(*) FROM documents GROUP BY source"
                ).fetchall()
            }
            latest = db.execute(
                "SELECT MAX(fetched_at) FROM documents"
            ).fetchone()[0]
        return {"documents": total, "sources": sources, "last_fetched_at": latest}

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("Search query must not be empty.")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")
        terms = list(dict.fromkeys(_tokens(query)))
        if not terms:
            raise ValueError("Search query did not contain searchable terms.")
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT source, title, url, source_owner, source_repo,
                       source_path, updated_on, content
                FROM documents
                """
            ).fetchall()
        query_phrase = " ".join(query.casefold().split())
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            source, title, url, owner, repo, source_path, updated, content = row
            title_text = str(title).casefold()
            body_text = str(content).casefold()
            title_score = sum(5.0 for term in terms if term in title_text)
            body_score = sum(min(body_text.count(term), 20) for term in terms)
            phrase_score = 8.0 if query_phrase and query_phrase in body_text else 0.0
            if title_score + body_score + phrase_score <= 0:
                continue
            score = title_score + body_score + phrase_score
            excerpt = ""
            best_position = min(
                (body_text.find(term) for term in terms if body_text.find(term) >= 0),
                default=0,
            )
            start = max(0, best_position - 180)
            excerpt = " ".join(str(content)[start:start + 420].split())
            ranked.append((score, {
                "source": source,
                "title": title,
                "url": url,
                "source_owner": owner,
                "source_repo": repo,
                "source_path": source_path,
                "updated_on": updated,
                "score": round(score, 2),
                "excerpt": excerpt,
            }))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["title"]).casefold()))
        return [item[1] for item in ranked[:limit]]


class MicrosoftKnowledgeCrawler:
    """Fetch a bounded Microsoft Learn corpus and selected Microsoft GitHub Markdown."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def _learn_search(self, query: str, *, top: int) -> list[dict[str, Any]]:
        parameters = urlencode([
            ("search", query),
            ("locale", "en-us"),
            ("scoringprofile", "semantic-captions"),
            ("facet", "category"),
            ("$top", str(top)),
            ("$skip", "0"),
            ("partnerId", "LearnSite"),
        ])
        url = f"https://{LEARN_HOST}/api/search/?{parameters}"
        payload = json.loads(_fetch_bytes(url, max_bytes=2_000_000).decode("utf-8"))
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [item for item in results if isinstance(item, dict)]

    def _crawl_learn(self, queries: tuple[str, ...], *, top: int) -> tuple[int, int, int]:
        fetched = 0
        added = 0
        updated_or_unchanged = 0
        seen: set[str] = set()
        for query in queries:
            try:
                results = self._learn_search(query, top=top)
            except (RuntimeError, ValueError, json.JSONDecodeError):
                continue
            for item in results:
                url = item.get("url")
                title = item.get("title")
                if not isinstance(url, str) or not isinstance(title, str) or url in seen:
                    continue
                seen.add(url)
                try:
                    _validate_url(url, allowed_hosts={LEARN_HOST})
                    html = _fetch_bytes(url, max_bytes=MAX_DOCUMENT_BYTES, timeout=25.0)
                    text = _extract_html(html)
                    outcome = self.store.upsert(
                        source="microsoft_learn",
                        title=title,
                        url=url,
                        content=text,
                        updated_on=str(item.get("lastUpdatedDate") or "")[:48] or None,
                    )
                    fetched += 1
                    if outcome == "added":
                        added += 1
                    else:
                        updated_or_unchanged += 1
                except (RuntimeError, ValueError, OSError):
                    continue
        return fetched, added, updated_or_unchanged

    @staticmethod
    def _path_score(path: str) -> int:
        normalized = path.casefold()
        if not normalized.endswith(".md"):
            return 0
        if any(part in normalized for part in (
            "/images/", "/media/", "/assets/", "/includes/", "/toc.", "/404",
        )):
            return 0
        return sum(weight for term, weight in _PATH_TERMS.items() if term in normalized)

    def _crawl_repository(
        self,
        owner: str,
        repo: str,
        branch: str,
        *,
        max_files: int,
    ) -> tuple[int, int, int]:
        api_url = (
            f"https://{GITHUB_API_HOST}/repos/{owner}/{repo}/git/trees/"
            f"{quote(branch, safe='')}?recursive=1"
        )
        payload = json.loads(_fetch_bytes(api_url, max_bytes=8_000_000).decode("utf-8"))
        tree = payload.get("tree", []) if isinstance(payload, dict) else []
        revision = str(payload.get("sha") or "")[:64]
        candidates: list[tuple[int, str]] = []
        for entry in tree:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            score = self._path_score(path)
            if score >= 4:
                candidates.append((score, path))
        candidates.sort(key=lambda item: (-item[0], item[1].casefold()))
        fetched = added = updated_or_unchanged = 0
        for _score, path in candidates[:max_files]:
            raw_url = (
                f"https://{GITHUB_RAW_HOST}/{owner}/{repo}/"
                f"{quote(branch, safe='')}/{quote(path, safe='/')}"
            )
            try:
                content = _fetch_bytes(raw_url, max_bytes=MAX_DOCUMENT_BYTES, timeout=25.0)
                text = content.decode("utf-8", errors="replace").strip()
                title = PurePosixPath(path).stem.replace("-", " ").replace("_", " ").title()
                if text.startswith("---"):
                    heading = re.search(r"(?m)^title:\s*[\"']?(.+?)[\"']?\s*$", text[:4000])
                    if heading:
                        title = heading.group(1).strip()[:300]
                url = f"https://github.com/{owner}/{repo}/blob/{quote(branch, safe='')}/{quote(path, safe='/')}"
                outcome = self.store.upsert(
                    source="microsoft_github",
                    title=title,
                    url=url,
                    content=text,
                    source_owner=owner,
                    source_repo=repo,
                    source_path=path,
                    revision=revision,
                )
                fetched += 1
                if outcome == "added":
                    added += 1
                else:
                    updated_or_unchanged += 1
            except (RuntimeError, ValueError, OSError):
                continue
        return fetched, added, updated_or_unchanged

    def crawl(
        self,
        *,
        learn_queries: tuple[str, ...] = DEFAULT_LEARN_QUERIES,
        learn_top_per_query: int = 4,
        github_files_per_repo: int = 8,
    ) -> CrawlResult:
        if not 1 <= learn_top_per_query <= 10:
            raise ValueError("learn_top_per_query must be between 1 and 10.")
        if not 1 <= github_files_per_repo <= 20:
            raise ValueError("github_files_per_repo must be between 1 and 20.")
        started_clock = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        learn_fetched, learn_added, learn_other = self._crawl_learn(
            learn_queries,
            top=learn_top_per_query,
        )
        github_fetched = github_added = github_other = failures = 0
        repositories_processed = 0
        for owner, repo, branch in GITHUB_SOURCES:
            try:
                fetched, added, other = self._crawl_repository(
                    owner,
                    repo,
                    branch,
                    max_files=github_files_per_repo,
                )
                github_fetched += fetched
                github_added += added
                github_other += other
                repositories_processed += 1
            except (RuntimeError, ValueError, OSError, json.JSONDecodeError):
                failures += 1
        # Learn search failures are isolated per query; GitHub failures per repository.
        completed_at = datetime.now(timezone.utc).isoformat()
        return CrawlResult(
            started_at=started_at,
            completed_at=completed_at,
            learn_queries=len(learn_queries),
            learn_documents=learn_fetched,
            github_repositories=repositories_processed,
            github_documents=github_fetched,
            documents_added=learn_added + github_added,
            documents_updated=0,
            unchanged=learn_other + github_other,
            failures=failures,
            elapsed_seconds=round(time.monotonic() - started_clock, 2),
        )

    def crawl_default(self) -> CrawlResult:
        return self.crawl()
