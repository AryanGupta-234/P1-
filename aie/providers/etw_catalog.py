"""Read-only ETW provider catalog discovery via the built-in logman utility."""
from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass


_PROVIDER_LINE = re.compile(
    r"^\s*(?P<name>.+?)\s+\{(?P<guid>[0-9A-Fa-f-]{36})\}\s*$"
)


@dataclass(frozen=True)
class ETWProvider:
    name: str
    guid: str


def parse_provider_catalog(output: str) -> list[ETWProvider]:
    """Parse provider name/GUID rows from logman output; tolerate localized headers."""
    providers: dict[str, ETWProvider] = {}
    for line in output.splitlines():
        match = _PROVIDER_LINE.match(line)
        if not match:
            continue
        name = match.group("name").strip()
        guid = match.group("guid").lower()
        if name:
            providers[name.casefold()] = ETWProvider(name=name, guid=guid)
    return sorted(providers.values(), key=lambda item: item.name.casefold())


def discover_etw_providers(timeout: float = 20.0) -> list[ETWProvider]:
    """List registered providers. This does not start or enable an ETW session."""
    try:
        result = subprocess.run(
            ["logman.exe", "query", "providers"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ETW provider catalog unavailable: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise RuntimeError("logman provider query failed")
    return parse_provider_catalog(result.stdout)


def filter_providers(providers: list[ETWProvider], contains: str) -> list[dict]:
    needle = contains.casefold().strip()
    selected = providers if not needle else [
        provider for provider in providers if needle in provider.name.casefold()
    ]
    return [asdict(provider) for provider in selected]
