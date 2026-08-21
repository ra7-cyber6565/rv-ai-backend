"""Operational cloud-archive endpoints.

Public status is aggregate-only and intentionally safe for health/UI use.  It
contains no local filenames/paths, Drive remote name, OAuth data or raw provider
errors.  A retry nudge mutates background work, so it remains admin-only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from storage.archive_runtime import archive_runtime
from utils.admin_guard import require_admin


router = APIRouter()


@router.get("/archive/status")
def archive_status():
    """Read-only, non-secret archive/retention readiness."""
    return archive_runtime.public_status()


@router.post("/archive/retry", status_code=202)
def retry_archive(
    limit: int = Query(default=5, ge=1, le=20),
    _admin: None = Depends(require_admin),
):
    """Schedule a bounded retry batch without blocking the HTTP request."""
    return archive_runtime.kick_retries(limit=limit)
