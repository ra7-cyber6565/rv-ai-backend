"""Operational cloud-archive endpoints.

Detailed archive status can walk manifest/retry/storage state and is therefore
operator-only even though its returned fields are sanitized. This prevents an
unauthenticated caller from turning repeated status requests into disk-scan load.
Cheap provider readiness remains available through /health and /api.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from storage.archive_runtime import archive_runtime
from utils.admin_guard import require_admin


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
