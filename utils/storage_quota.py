"""Bounded local workspace policy for Infinity Research AI.

The goal is simple: D: is a fast working area, not an endlessly growing archive.
This module never deletes arbitrary files. Cleanup is allowed only for files that
ArchiveManifest has already marked VERIFIED in cloud storage.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from utils.archive_manifest import ArchiveManifest
from utils.storage_paths import configured_root


_GB = 1024 ** 3


class StorageQuotaError(RuntimeError):
    pass


def _float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class StoragePolicy:
    max_local_bytes: int
    min_free_bytes: int

    @classmethod
    def from_env(cls) -> "StoragePolicy":
        max_gb = _float_env("INFINITY_MAX_LOCAL_GB", 50.0, minimum=1.0, maximum=500.0)
        min_free_gb = _float_env("INFINITY_MIN_FREE_GB", 5.0, minimum=1.0, maximum=100.0)
        return cls(int(max_gb * _GB), int(min_free_gb * _GB))


def folder_size_bytes(root: str) -> int:
    """Return regular-file bytes under root without following symlinks."""
    total = 0
    if not os.path.isdir(root):
        return 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries: Iterable[os.DirEntry[str]] = os.scandir(current)
            with entries as scan:
                for entry in scan:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except (FileNotFoundError, PermissionError):
                        continue
        except (FileNotFoundError, PermissionError):
            continue
    return total


def storage_pressure(*, extra_bytes: int = 0, policy: StoragePolicy | None = None) -> dict:
    root, explicit = configured_root()
    policy = policy or StoragePolicy.from_env()
    Path(root).mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    used_by_app = folder_size_bytes(root)
    projected = used_by_app + max(0, int(extra_bytes))
    projected_free = usage.free - max(0, int(extra_bytes))
    reasons: list[str] = []
    if projected > policy.max_local_bytes:
        reasons.append("local_workspace_limit")
    if projected_free < policy.min_free_bytes:
        reasons.append("minimum_disk_free")
    return {
        "root": root,
        "explicit": explicit,
        "app_bytes": used_by_app,
        "projected_app_bytes": projected,
        "max_local_bytes": policy.max_local_bytes,
        "disk_free_bytes": usage.free,
        "projected_disk_free_bytes": projected_free,
        "min_free_bytes": policy.min_free_bytes,
        "blocked": bool(reasons),
        "reasons": reasons,
    }


def assert_capacity(extra_bytes: int, policy: StoragePolicy | None = None) -> dict:
    """Refuse new writes that would violate configured workspace safety limits."""
    state = storage_pressure(extra_bytes=extra_bytes, policy=policy)
    if state["blocked"]:
        raise StorageQuotaError(
            "Local working storage safety limit reached; archive/cleanup verified files "
            "or increase the explicitly configured limit."
        )
    return state


def _inside_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def cleanup_verified_archives(
    manifest: ArchiveManifest,
    *,
    target_reclaim_bytes: int,
) -> dict:
    """Delete only cloud-VERIFIED local copies until target bytes are reclaimed.

    Security rules:
    - file must still exist;
    - the exact provider/path-aware archive record must be verified;
    - local path must be inside configured Infinity storage root;
    - symlinks are never deleted through this cleanup path.
    """
    root, _ = configured_root()
    reclaimed = 0
    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    target = max(0, int(target_reclaim_bytes))

    for item in manifest.items():
        if reclaimed >= target:
            break
        digest = str(item.get("sha256") or "")
        archive_ref = str(item.get("archive_id") or digest)
        path = str(item.get("local_path") or "")
        if not archive_ref or not path:
            continue
        if item.get("local_deleted") is True:
            continue
        if not manifest.safe_to_delete_local(archive_ref):
            skipped.append({"path": path, "reason": "not_verified"})
            continue
        if not _inside_root(path, root):
            skipped.append({"path": path, "reason": "outside_storage_root"})
            continue
        if os.path.islink(path):
            skipped.append({"path": path, "reason": "symlink"})
            continue
        if not os.path.isfile(path):
            skipped.append({"path": path, "reason": "missing"})
            continue

        size = os.path.getsize(path)
        os.remove(path)
        manifest.mark_local_deleted(archive_ref)
        reclaimed += size
        deleted.append(path)

    return {
        "target_reclaim_bytes": target,
        "reclaimed_bytes": reclaimed,
        "deleted_count": len(deleted),
        "deleted": deleted,
        "skipped": skipped,
    }
