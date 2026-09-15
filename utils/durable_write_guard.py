"""Shared admission guard for writes into Infinity's managed durable root.

The storage quota module owns the actual policy. This helper answers one extra
question every writer needs consistently: is this destination really inside the
explicit persistence-bearing root? Local/temp/custom paths remain untouched so
unit tests and laptop workflows do not accidentally inherit cloud-volume limits.
"""
from __future__ import annotations

import os

from utils.storage_paths import configured_root
from utils.storage_quota import assert_capacity


def is_managed_durable_path(path: str) -> bool:
    """Return True only for paths inside an explicitly configured durable root."""
    root, explicit = configured_root()
    if not explicit or not str(path or "").strip():
        return False
    try:
        candidate = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
        durable = os.path.realpath(os.path.abspath(os.path.expanduser(str(root))))
        return os.path.commonpath([candidate, durable]) == durable
    except (OSError, ValueError):
        return False


def guard_durable_write(path: str, extra_bytes: int) -> dict | None:
    """Fail closed on a managed durable write that would violate storage policy.

    ``extra_bytes`` is an admission estimate, not a claim about exact filesystem
    growth. The quota policy independently enforces both total app bytes and
    minimum free disk, so conservative callers can reserve expected write/index
    overhead before mutating durable state.
    """
    if not is_managed_durable_path(path):
        return None
    return assert_capacity(max(0, int(extra_bytes)))


__all__ = ["guard_durable_write", "is_managed_durable_path"]
