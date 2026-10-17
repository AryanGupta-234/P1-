"""Local catalogue and importer for Windows ms-settings: deep links.

This module stores navigation metadata only. It never launches Settings or changes
Windows configuration. Imported catalogue rows are treated as untrusted data.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 10000
MAX_FIELD = 2000
_URI_RE = re.compile(r"^ms-settings:[a-z0-9][a-z0-9._:/?&=%+@!#$'()*,-]*$", re.I)
_BUILD_RE = re.compile(r"^[0-9]{1,8}$")


@dataclass(frozen=True)
class SettingsEntry:
    uri: str
    title: str
    category: str = "Other"
    description: str = ""
    source: str = "user-import"
    validation_status: str = "unverified"
    min_build: int | None = None
    max_build: int | None = None
    source_url: str = ""
    version_notes: str = ""
    requirements: str = ""


def validate_entry(raw: dict[str, Any]) -> SettingsEntry:
    if not isinstance(raw, dict):
        raise ValueError("each catalogue record must be an object")
    uri = raw.get("uri")
    title = raw.get("title")
    if not isinstance(uri, str) or len(uri) > 512:
        raise ValueError("uri must be a string of at most 512 characters")
    uri = uri.strip()
    if not _URI_RE.fullmatch(uri):
        raise ValueError(f"invalid ms-settings URI: {uri[:80]!r}")
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_FIELD:
        raise ValueError("title must be a non-empty string of at most 2000 characters")

    def field(name: str, default: str) -> str:
        value = raw.get(name, default)
        if not isinstance(value, str) or len(value) > MAX_FIELD:
            raise ValueError(f"{name} must be a string of at most 2000 characters")
        return value.strip()

    status = field("validation_status", "unverified")
    if status not in {"unverified", "documented", "verified-on-host", "unsupported"}:
        raise ValueError("validation_status must be unverified, documented, verified-on-host, or unsupported")

    def build(name: str) -> int | None:
        value = raw.get(name)
        if value in (None, ""):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"{name} must be an integer")
        text = str(value)
        if not _BUILD_RE.fullmatch(text):
            raise ValueError(f"{name} must be a positive Windows build number")
        return int(text)

    minimum, maximum = build("min_build"), build("max_build")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("min_build cannot exceed max_build")
    return SettingsEntry(
        uri=uri,
        title=title.strip(),
        category=field("category", "Other") or "Other",
        description=field("description", ""),
        source=field("source", "user-import") or "user-import",
        validation_status=status,
        min_build=minimum,
        max_build=maximum,
        source_url=field("source_url", ""),
        version_notes=field("version_notes", ""),
        requirements=field("requirements", ""),
    )


def load_catalog(path: Path) -> list[SettingsEntry]:
    size = path.stat().st_size
    if size > MAX_IMPORT_BYTES:
        raise ValueError(f"catalogue exceeds {MAX_IMPORT_BYTES} bytes")
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise ValueError(f"catalogue must contain a list of at most {MAX_RECORDS} records")
    entries: dict[str, SettingsEntry] = {}
    for row in rows:
        entry = validate_entry(row)
        entries[entry.uri.casefold()] = entry
    return sorted(entries.values(), key=lambda item: (item.category.casefold(), item.uri.casefold()))


def search_catalog(entries: list[SettingsEntry], query: str, limit: int = 50) -> list[SettingsEntry]:
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError("query must be a string of at most 500 characters")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    terms = [part.casefold() for part in query.split() if part]
    if not terms:
        return sorted(entries, key=lambda item: item.uri.casefold())[:limit]

    def score(entry: SettingsEntry) -> tuple[int, str]:
        fields = (entry.uri, entry.title, entry.category, entry.description)
        haystack = " ".join(fields).casefold()
        matched = sum(1 for term in terms if term in haystack)
        exact_uri = 10 if entry.uri.casefold() == query.casefold() else 0
        title_hits = sum(1 for term in terms if term in entry.title.casefold())
        return (exact_uri + matched + title_hits, entry.uri.casefold())

    matches = [entry for entry in entries if all(term in " ".join(
        (entry.uri, entry.title, entry.category, entry.description)
    ).casefold() for term in terms)]
    return sorted(matches, key=lambda item: (-score(item)[0], item.uri.casefold()))[:limit]


def merge_catalog(existing: list[SettingsEntry], incoming: list[SettingsEntry]) -> list[SettingsEntry]:
    merged = {entry.uri.casefold(): entry for entry in existing}
    merged.update({entry.uri.casefold(): entry for entry in incoming})
    return sorted(merged.values(), key=lambda item: (item.category.casefold(), item.uri.casefold()))


def save_catalog(path: Path, entries: list[SettingsEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "items": [asdict(item) for item in entries]}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


# Conservative starter set of commonly used destinations. These are deliberately
# marked unverified: support can vary by Windows build, edition and device policy.
STARTER_ENTRIES = [
    ("ms-settings:display", "Display", "System"),
    ("ms-settings:sound", "Sound", "System"),
    ("ms-settings:notifications", "Notifications", "System"),
    ("ms-settings:power", "Power", "System"),
    ("ms-settings:batterysaver", "Battery saver", "System"),
    ("ms-settings:storagesense", "Storage", "System"),
    ("ms-settings:about", "About this PC", "System"),
    ("ms-settings:recovery", "Recovery", "System"),
    ("ms-settings:troubleshoot", "Troubleshoot", "System"),
    ("ms-settings:optionalfeatures", "Optional features", "System"),
    ("ms-settings:developers", "For developers", "System"),
    ("ms-settings:bluetooth", "Bluetooth and devices", "Devices"),
    ("ms-settings:printers", "Printers and scanners", "Devices"),
    ("ms-settings:connecteddevices", "Connected devices", "Devices"),
    ("ms-settings:network", "Network and internet", "Network"),
    ("ms-settings:network-wifi", "Wi-Fi", "Network"),
    ("ms-settings:network-ethernet", "Ethernet", "Network"),
    ("ms-settings:network-vpn", "VPN", "Network"),
    ("ms-settings:network-proxy", "Proxy", "Network"),
    ("ms-settings:personalization", "Personalization", "Personalization"),
    ("ms-settings:personalization-background", "Background", "Personalization"),
    ("ms-settings:personalization-colors", "Colors", "Personalization"),
    ("ms-settings:personalization-start", "Start", "Personalization"),
    ("ms-settings:taskbar", "Taskbar", "Personalization"),
    ("ms-settings:themes", "Themes", "Personalization"),
    ("ms-settings:appsfeatures", "Installed apps", "Apps"),
    ("ms-settings:defaultapps", "Default apps", "Apps"),
    ("ms-settings:startupapps", "Startup apps", "Apps"),
    ("ms-settings:accounts", "Accounts", "Accounts"),
    ("ms-settings:yourinfo", "Your info", "Accounts"),
    ("ms-settings:signinoptions", "Sign-in options", "Accounts"),
    ("ms-settings:workplace", "Access work or school", "Accounts"),
    ("ms-settings:windowsupdate", "Windows Update", "Update and security"),
    ("ms-settings:windowsupdate-history", "Update history", "Update and security"),
    ("ms-settings:activation", "Activation", "Update and security"),
    ("ms-settings:privacy", "Privacy and security", "Privacy"),
    ("ms-settings:privacy-location", "Location privacy", "Privacy"),
    ("ms-settings:privacy-microphone", "Microphone privacy", "Privacy"),
    ("ms-settings:privacy-webcam", "Camera privacy", "Privacy"),
    ("ms-settings:privacy-notifications", "Notifications privacy", "Privacy"),
    ("ms-settings:easeofaccess-display", "Accessibility display", "Accessibility"),
    ("ms-settings:easeofaccess-magnifier", "Magnifier", "Accessibility"),
    ("ms-settings:easeofaccess-narrator", "Narrator", "Accessibility"),
    ("ms-settings:gaming-gamemode", "Game Mode", "Gaming"),
    ("ms-settings:gaming-captures", "Game captures", "Gaming"),
    ("ms-settings:dateandtime", "Date and time", "Time and language"),
    ("ms-settings:regionlanguage", "Region and language", "Time and language"),
    ("ms-settings:language", "Language", "Time and language"),
]


def starter_catalog() -> list[SettingsEntry]:
    return [
        SettingsEntry(uri, title, category, source="aie-starter-set", validation_status="unverified")
        for uri, title, category in STARTER_ENTRIES
    ]
