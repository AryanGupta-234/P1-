"""Load explicitly user-authored capability manifests from the local policy directory."""
from __future__ import annotations

import json
from pathlib import Path

from aie.policy.models import CapabilityManifest


class CapabilityManifestLoadError(RuntimeError):
    """Raised when the local capability directory contains invalid policy."""


def load_capability_manifests(directory: Path) -> list[CapabilityManifest]:
    """Load only regular JSON files from the explicit user-managed capability directory.

    The loader fails closed if any manifest is malformed or duplicated; it never
    grants capabilities by default or follows symlinks.
    """
    directory.mkdir(parents=True, exist_ok=True)
    manifests: list[CapabilityManifest] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.stat().st_size > 64 * 1024:
            raise CapabilityManifestLoadError(f"{path.name}: manifest exceeds 64 KiB")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            manifest = CapabilityManifest.model_validate(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise CapabilityManifestLoadError(
                f"{path.name}: invalid capability manifest ({type(exc).__name__})"
            ) from exc
        if manifest.capability_id in seen:
            raise CapabilityManifestLoadError(
                f"{path.name}: duplicate capability ID {manifest.capability_id!r}"
            )
        seen.add(manifest.capability_id)
        manifests.append(manifest)
    return manifests
