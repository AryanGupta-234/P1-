"""Safe edits to user-managed capability manifests."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationError

from aie.policy.models import CapabilityManifest


class CapabilityPermissionError(ValueError):
    """Raised when a manifest permission change would exceed supported policy."""


def set_capability_enabled(
    directory: Path,
    capability_id: str,
    *,
    enabled: bool,
    registered_capability_ids: set[str] | frozenset[str],
) -> CapabilityManifest:
    """Change only the enabled flag on one trusted, registered capability manifest.

    Enabling is rejected for unknown/unregistered adapters, approval-free manifests
    and manifests that permit autonomous use. Other risk/parameter/budget fields are
    preserved exactly. Writes are atomic and the manifest directory and target file
    may not be symlinks.
    """
    if not isinstance(capability_id, str) or not capability_id.strip():
        raise CapabilityPermissionError("capability_id is required")
    if not isinstance(enabled, bool):
        raise CapabilityPermissionError("enabled must be a boolean")
    if directory.is_symlink():
        raise CapabilityPermissionError("capability directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)

    matches: list[tuple[Path, CapabilityManifest, bytes]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.stat().st_size > 64 * 1024:
            raise CapabilityPermissionError(f"{path.name}: manifest exceeds 64 KiB")
        try:
            original_bytes = path.read_bytes()
            manifest = CapabilityManifest.model_validate_json(original_bytes)
        except OSError as exc:
            raise CapabilityPermissionError(
                f"{path.name}: unable to read manifest ({type(exc).__name__})"
            ) from exc
        except ValidationError as exc:
            messages = " ".join(error.get("msg", "") for error in exc.errors())
            if "Autonomous capabilities cannot also require per-action approval" in messages:
                raise CapabilityPermissionError(
                    "allow_autonomous=true requires approval_required=false; "
                    "autonomous execution is not eligible for this enable operation"
                ) from exc
            raise CapabilityPermissionError(
                f"{path.name}: invalid manifest ({type(exc).__name__})"
            ) from exc
        except ValueError as exc:
            raise CapabilityPermissionError(
                f"{path.name}: invalid manifest ({type(exc).__name__})"
            ) from exc
        if manifest.capability_id in seen:
            raise CapabilityPermissionError(f"duplicate capability ID: {manifest.capability_id}")
        seen.add(manifest.capability_id)
        if manifest.capability_id == capability_id:
            matches.append((path, manifest, original_bytes))

    if len(matches) != 1:
        raise CapabilityPermissionError("exactly one matching capability manifest must exist")
    path, manifest, _original_bytes = matches[0]
    if enabled:
        if capability_id not in registered_capability_ids:
            raise CapabilityPermissionError(
                "capability has no application-registered trusted adapter"
            )
        if not manifest.approval_required or manifest.allow_autonomous:
            raise CapabilityPermissionError(
                "execution requires approval_required=true and allow_autonomous=false"
            )

    updated = manifest.model_copy(update={"enabled": enabled})
    temporary = path.with_name(path.name + ".tmp")
    if temporary.is_symlink():
        raise CapabilityPermissionError("manifest temporary path cannot be a symlink")
    payload = updated.model_dump_json(indent=2)
    temporary_created = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            temporary_created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary_created = False
    except FileExistsError as exc:
        raise CapabilityPermissionError(
            "manifest temporary file already exists; inspect and remove it manually"
        ) from exc
    finally:
        if temporary_created:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return updated
