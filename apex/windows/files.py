"""User-root-scoped file operations; permanent deletion is never exposed."""
from __future__ import annotations
import os
import shutil
from pathlib import Path

def approved_roots() -> list[Path]:
    raw = os.environ.get("APEX_ALLOWED_FILE_ROOTS")
    if raw:
        candidates = [Path(part.strip()).expanduser() for part in raw.split(";") if part.strip()]
    else:
        home = Path.home()
        candidates = [home / folder for folder in ("Desktop", "Documents", "Downloads", "Pictures")]
    roots = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            if resolved.is_dir():
                roots.append(resolved)
        except OSError:
            continue
    return roots

def _approved(path: str | Path, *, must_exist: bool = False) -> Path:
    if os.name != "nt":
        raise OSError("APEX file operations require Windows")
    candidate = Path(path).expanduser()
    # Reject reparse points along the path, not just at the leaf.
    cursor = candidate
    while True:
        try:
            metadata = cursor.lstat()
            if cursor.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise PermissionError("reparse points and symbolic links are not valid operation paths")
        except FileNotFoundError:
            pass
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    resolved = candidate.resolve(strict=must_exist)
    for root in approved_roots():
        try:
            if os.path.commonpath((str(root).casefold(), str(resolved).casefold())) == str(root).casefold():
                return resolved
        except ValueError:
            continue
    raise PermissionError("file path is outside the user-approved APEX roots")

def list_directory(path: str, limit: int = 100) -> dict:
    folder = _approved(path, must_exist=True)
    if isinstance(limit, bool) or not 1 <= limit <= 300:
        raise ValueError("limit must be between 1 and 300")
    rows = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if len(rows) >= limit:
                break
            try:
                info = entry.stat(follow_symlinks=False)
                rows.append({"name": entry.name[:260], "is_directory": entry.is_dir(follow_symlinks=False),
                             "size_bytes": info.st_size, "modified_at": info.st_mtime,
                             "is_symlink": entry.is_symlink()})
            except OSError:
                continue
    return {"path": str(folder), "entries": rows, "count": len(rows), "source": "APEX scoped filesystem provider"}

def create_folder(path: str) -> dict:
    target = _approved(path)
    target.mkdir(parents=False, exist_ok=False)
    return {"summary": f"Created folder '{target.name}'.", "path": str(target), "verified": target.is_dir()}

def copy_file(source: str, destination: str) -> dict:
    src = _approved(source, must_exist=True)
    dst = _approved(destination)
    if not src.is_file() or src.is_symlink() or dst.exists():
        raise ValueError("source must be a regular file and destination must not already exist")
    shutil.copy2(src, dst)
    if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
        raise RuntimeError("copied file did not pass size verification")
    return {"summary": f"Copied '{src.name}' to '{dst.name}'.", "source": str(src),
            "destination": str(dst), "verified": True}

def move_file(source: str, destination: str) -> dict:
    src = _approved(source, must_exist=True)
    dst = _approved(destination)
    if not src.is_file() or src.is_symlink() or dst.exists():
        raise ValueError("source must be a regular file and destination must not already exist")
    shutil.move(str(src), str(dst))
    if not dst.is_file() or src.exists():
        raise RuntimeError("move postcondition failed")
    return {"summary": f"Moved '{src.name}' to '{dst.name}'.", "source": str(src),
            "destination": str(dst), "verified": True}

def rename_file(source: str, new_name: str) -> dict:
    src = _approved(source, must_exist=True)
    if not src.is_file() or src.is_symlink() or not isinstance(new_name, str) or not 1 <= len(new_name) <= 240:
        raise ValueError("rename requires a regular file and a valid new filename")
    if Path(new_name).name != new_name or new_name in {".", ".."}:
        raise ValueError("new_name must be a filename, not a path")
    dst = _approved(src.with_name(new_name))
    if dst.exists():
        raise FileExistsError("destination already exists")
    src.rename(dst)
    if not dst.is_file() or src.exists():
        raise RuntimeError("rename postcondition failed")
    return {"summary": f"Renamed file to '{dst.name}'.", "path": str(dst), "verified": True}

def move_to_recycle_bin(path: str) -> dict:
    target = _approved(path, must_exist=True)
    if target in approved_roots() or target.is_symlink():
        raise PermissionError("cannot delete an approved root or symbolic link")
    try:
        from send2trash import send2trash
    except ImportError as exc:
        raise RuntimeError("send2trash is not installed; Recycle Bin deletion is unavailable") from exc
    send2trash(str(target))
    if target.exists():
        raise RuntimeError("Recycle Bin operation did not remove the original path")
    return {"summary": f"Moved '{target.name}' to the Recycle Bin.", "path": str(target), "verified": True}

def provider_available() -> bool:
    return os.name == "nt"
