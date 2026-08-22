"""Fail-closed guard for operational/history/admin endpoints.

The public research API intentionally has no paid auth service. That does NOT
mean project lists, server-side history, or destructive project operations should
be enumerable by anyone who discovers the backend URL.

Set a strong random ``INFINITY_ADMIN_TOKEN`` only in the backend environment when
an operator needs these endpoints. Never embed this token in the Android APK or
frontend JavaScript. Missing/invalid tokens return 404 so disabled admin surfaces
are not advertised as an authentication oracle.
"""
from __future__ import annotations

import hmac
import os
from typing import Mapping

from fastapi import Header, HTTPException


_MIN_TOKEN_LENGTH = 24


def _configured_token(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return str(source.get("INFINITY_ADMIN_TOKEN", "") or "").strip()


def admin_configured(env: Mapping[str, str] | None = None) -> bool:
    return len(_configured_token(env)) >= _MIN_TOKEN_LENGTH


def admin_token_valid(provided: object, env: Mapping[str, str] | None = None) -> bool:
    expected = _configured_token(env)
    candidate = str(provided or "").strip()
    if len(expected) < _MIN_TOKEN_LENGTH or not candidate:
        return False
    return hmac.compare_digest(expected, candidate)


def require_admin(
    x_infinity_admin_token: str | None = Header(default=None, alias="X-Infinity-Admin-Token"),
) -> None:
    if not admin_token_valid(x_infinity_admin_token):
        # 404 is deliberate: when admin access is not configured, these routes
        # behave as if they are not a public feature at all.
        raise HTTPException(status_code=404, detail="Not found")


def public_admin_status(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Non-secret readiness only; never returns token length/value."""
    return {"admin_endpoints_configured": admin_configured(env)}


__all__ = [
    "admin_configured",
    "admin_token_valid",
    "require_admin",
    "public_admin_status",
]
