"""Operational cloud-archive endpoints.

Detailed archive status can walk manifest/retry/storage state and is therefore
operator-only even though its returned fields are sanitized. This prevents an
unauthenticated caller from turning repeated status requests into disk-scan load.
Cheap provider readiness remains available through /health and /api.

Cleanup is deliberately explicit and bounded. It delegates to the one canonical
verified-archive cleanup function, which refuses unverified or size-only records,
paths outside the configured Infinity root, and symlinks. The API returns
aggregate counts only instead of leaking absolute local paths.
"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query

from storage.archive_runtime import archive_runtime
from utils.admin_guard import require_admin
from utils.storage_quota import cleanup_verified_archives


router = APIRouter()


@router.get("/archive/status")
def archive_status(_admin: None = Depends(require_admin)):
    """Read-only, non-secret detailed archive/retention readiness (admin-only)."""
    return archive_runtime.public_status()


@router.post("/archive/retry", status_code=202)
def retry_archive(
    limit: int = Query(default=5, ge=1, le=20),
    _admin: None = Depends(require_admin),
):
    """Schedule a bounded retry batch without blocking the HTTP request."""
    return archive_runtime.kick_retries(limit=limit)


@router.post("/archive/cleanup")
def cleanup_archive(
    target_mb: int = Query(default=512, ge=1, le=4096),
    _admin: None = Depends(require_admin),
):
    """Reclaim local bytes only from checksum-verified cloud archive records.

    This is not a generic delete endpoint. The canonical cleanup layer requires
    exact provider/path/content identity, matching remote SHA-256, configured-root
    containment and symlink safety. A remote object whose size matches but whose
    content checksum was not proved is retained locally. No filename/local path
    is reflected to the HTTP caller.
    """
    result = cleanup_verified_archives(
        archive_runtime.manifest,
        target_reclaim_bytes=int(target_mb) * 1024 * 1024,
    )
    reasons = Counter(
        str(row.get("reason") or "unknown")
        for row in (result.get("skipped") or [])
        if isinstance(row, dict)
    )
    return {
        "target_reclaim_bytes": int(result.get("target_reclaim_bytes", 0) or 0),
        "reclaimed_bytes": int(result.get("reclaimed_bytes", 0) or 0),
        "deleted_count": int(result.get("deleted_count", 0) or 0),
        "skipped_count": sum(reasons.values()),
        "skipped_by_reason": dict(sorted(reasons.items())),
        "rule": (
            "Only exact cloud-VERIFIED records with matching remote SHA-256, "
            "inside configured storage root, are eligible."
        ),
    }
