"""Truth-preserving Railway runtime volume attestation.

Railway documents two runtime variables that exist when a persistent Volume is
attached to a service: ``RAILWAY_VOLUME_NAME`` and
``RAILWAY_VOLUME_MOUNT_PATH``.  The app already knows its configured durable
root; this module compares the platform-provided mount path with that durable
root without exposing either value publicly.

This is deliberately a *runtime attachment attestation*, not a persistence
proof.  A matching mount marker can tell us that Railway mounted a Volume at
this container start; only a same-job/same-token restart acceptance can prove
that the application's state actually survives a redeploy.
"""
from __future__ import annotations

import os
from typing import Mapping


_RAILWAY_RUNTIME_KEYS = (
    "RAILWAY_PROJECT_ID",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_DEPLOYMENT_ID",
)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _absolute(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(value)))


def railway_runtime_volume_status(
    env: Mapping[str, str] | None = None,
    *,
    durable_root: str = "",
) -> dict[str, bool]:
    """Return path-free booleans describing Railway Volume runtime markers.

    ``railway_runtime`` is true when Railway's ordinary runtime identity
    variables are present.  ``railway_volume_attached`` requires *both* official
    Volume variables; a partial marker fails closed.  ``mount_matches`` is true
    only when the platform mount path resolves to the exact configured durable
    root.
    """
    source = env if env is not None else os.environ
    railway_runtime = any(_clean(source.get(name)) for name in _RAILWAY_RUNTIME_KEYS)
    volume_name = _clean(source.get("RAILWAY_VOLUME_NAME"))
    mount_path = _clean(source.get("RAILWAY_VOLUME_MOUNT_PATH"))
    attached = bool(volume_name and mount_path)

    durable = _clean(durable_root)
    mount_matches = bool(
        attached
        and durable
        and _absolute(mount_path) == _absolute(durable)
    )
    return {
        "railway_runtime": railway_runtime,
        "railway_volume_attached": attached,
        "railway_volume_mount_matches_durable_root": mount_matches,
        "persistent_volume_ready": bool(railway_runtime and attached and mount_matches),
    }


__all__ = ["railway_runtime_volume_status"]
