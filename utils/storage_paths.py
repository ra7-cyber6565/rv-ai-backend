"""Central storage layout for Infinity Research AI.

Laptop/backward-compatible setup can keep using either::

    INFINITY_DATA_ROOT=D:\\InfinityResearchAI
    INFINITY_WORK_ROOT=D:\\InfinityResearchAI

Those legacy variables still put *all* app data under one root, exactly as
before. Cloud deployments can optionally split durable state from large,
rebuildable runtime data::

    INFINITY_DURABLE_ROOT=/data
    INFINITY_EPHEMERAL_ROOT=/tmp/infinity_ai

This lets a small persistent volume hold research state while model/cache/temp
files remain on ephemeral container storage. An explicitly configured root
fails closed if it is missing or unwritable; no silent fallback drive is used.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parent.parent
DURABLE_SUBDIRS = (
    "archive",
    "knowledge",
    "research_memory",
    "uploads",
    "vector_db",
)
EPHEMERAL_SUBDIRS = (
    "cache",
    "logs",
    "models",
    "temp",
)
# Kept for callers/tests that import the old aggregate constant.
SUBDIRS = DURABLE_SUBDIRS + EPHEMERAL_SUBDIRS


def _clean(raw: object) -> str:
    return str(raw or "").strip()


def _absolute(raw: str) -> str:
    return os.path.abspath(os.path.expanduser(raw))


def _legacy_configured_root(
    env: Mapping[str, str] | None = None,
) -> tuple[str, bool]:
    source = env if env is not None else os.environ
    raw = _clean(source.get("INFINITY_DATA_ROOT")) or _clean(source.get("INFINITY_WORK_ROOT"))
    if raw:
        return _absolute(raw), True
    return str(REPO_ROOT / "runtime_data"), False


def configured_root(env: Mapping[str, str] | None = None) -> tuple[str, bool]:
    """Return the app's persistence-bearing root for legacy callers.

    Historically this function exposed the one unified data root. Existing
    persistence/quota guards still call it, so when split storage is enabled it
    must resolve to the durable root rather than the ephemeral runtime root.
    With no split variable configured, behavior is byte-for-byte compatible
    with the old ``INFINITY_DATA_ROOT`` / ``INFINITY_WORK_ROOT`` resolution.
    """
    source = env if env is not None else os.environ
    durable_raw = _clean(source.get("INFINITY_DURABLE_ROOT"))
    if durable_raw:
        return _absolute(durable_raw), True
    return _legacy_configured_root(source)


def configured_storage_roots(
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Resolve durable/ephemeral roots while preserving legacy behavior.

    New split variables take precedence only for their own storage class. If a
    split variable is absent, that class falls back to the legacy unified root.
    Thus existing laptop/cloud configurations are unchanged until they opt in.
    """
    source = env if env is not None else os.environ
    legacy_root, legacy_explicit = _legacy_configured_root(source)

    durable_raw = _clean(source.get("INFINITY_DURABLE_ROOT"))
    ephemeral_raw = _clean(source.get("INFINITY_EPHEMERAL_ROOT"))

    durable_root = _absolute(durable_raw) if durable_raw else legacy_root
    ephemeral_root = _absolute(ephemeral_raw) if ephemeral_raw else legacy_root
    return {
        "durable_root": durable_root,
        "ephemeral_root": ephemeral_root,
        "durable_explicit": bool(durable_raw) or legacy_explicit,
        "ephemeral_explicit": bool(ephemeral_raw) or legacy_explicit,
        "split": durable_root != ephemeral_root,
    }


def _probe_writable(root: str) -> None:
    path = Path(root)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".infinity_storage_probe"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Infinity storage root unavailable/unwritable: {root}. "
            "No fallback drive will be used."
        ) from exc


def ensure_layout(env: Mapping[str, str] | None = None) -> dict[str, str]:
    roots = configured_storage_roots(env)
    durable_root = str(roots["durable_root"])
    ephemeral_root = str(roots["ephemeral_root"])
    _probe_writable(durable_root)
    if ephemeral_root != durable_root:
        _probe_writable(ephemeral_root)

    paths = {
        # ``root``/``explicit`` remain for backward compatibility. In split
        # mode, root intentionally means the persistence-bearing durable root.
        "root": durable_root,
        "explicit": str(bool(roots["durable_explicit"])).lower(),
        "durable_root": durable_root,
        "ephemeral_root": ephemeral_root,
        "durable_explicit": str(bool(roots["durable_explicit"])).lower(),
        "ephemeral_explicit": str(bool(roots["ephemeral_explicit"])).lower(),
        "split": str(bool(roots["split"])).lower(),
    }
    for name in DURABLE_SUBDIRS:
        folder = Path(durable_root) / name
        folder.mkdir(parents=True, exist_ok=True)
        paths[name] = str(folder)
    for name in EPHEMERAL_SUBDIRS:
        folder = Path(ephemeral_root) / name
        folder.mkdir(parents=True, exist_ok=True)
        paths[name] = str(folder)
    return paths


def _set_path_env(name: str, value: str, *, force: bool) -> None:
    if force or not _clean(os.environ.get(name)):
        os.environ[name] = value


def configure_process_storage() -> dict[str, object]:
    """Configure app state plus third-party cache/temp locations.

    Legacy unified roots still force every path under that root. With the new
    split variables, app-owned durable state follows ``INFINITY_DURABLE_ROOT``
    while large rebuildable model/cache/temp data follows
    ``INFINITY_EPHEMERAL_ROOT``.
    """
    layout = ensure_layout()
    roots = configured_storage_roots()
    durable_root = str(roots["durable_root"])
    ephemeral_root = str(roots["ephemeral_root"])
    durable_explicit = bool(roots["durable_explicit"])
    ephemeral_explicit = bool(roots["ephemeral_explicit"])

    # App-owned durable locations.
    _set_path_env("KNOWLEDGE_GRAPH_FILE", str(Path(layout["knowledge"]) / "knowledge_graph.json"), force=durable_explicit)
    _set_path_env("KNOWLEDGE_STORE_FILE", str(Path(layout["knowledge"]) / "knowledge_store.json"), force=durable_explicit)
    _set_path_env("RESEARCH_MEMORY_DIR", layout["research_memory"], force=durable_explicit)
    _set_path_env("CHROMA_DB_DIR", layout["vector_db"], force=durable_explicit)
    _set_path_env("INFINITY_ARCHIVE_DIR", layout["archive"], force=durable_explicit)

    # Heavy third-party caches/models stay rebuildable/ephemeral when split.
    # Transformers now uses HF_HOME/HUGGINGFACE_HUB_CACHE; exporting the legacy
    # TRANSFORMERS_CACHE variable itself triggers a deprecation warning in newer
    # Transformers releases, so the app deliberately no longer creates it.
    cache_root = Path(layout["cache"])
    model_root = Path(layout["models"])
    _set_path_env("HF_HOME", str(model_root / "huggingface"), force=ephemeral_explicit)
    _set_path_env("HUGGINGFACE_HUB_CACHE", str(model_root / "huggingface" / "hub"), force=ephemeral_explicit)
    _set_path_env("SENTENCE_TRANSFORMERS_HOME", str(model_root / "sentence_transformers"), force=ephemeral_explicit)
    _set_path_env("TORCH_HOME", str(model_root / "torch"), force=ephemeral_explicit)
    _set_path_env("XDG_CACHE_HOME", str(cache_root), force=ephemeral_explicit)

    # Python/OS temp files. Set all common variants for Windows/Linux tools.
    for temp_name in ("TMP", "TEMP", "TMPDIR"):
        _set_path_env(temp_name, layout["temp"], force=ephemeral_explicit)

    durable_usage = shutil.disk_usage(durable_root)
    ephemeral_usage = shutil.disk_usage(ephemeral_root)
    return {
        "root": durable_root,
        "explicit": durable_explicit,
        "durable_root": durable_root,
        "ephemeral_root": ephemeral_root,
        "split": bool(roots["split"]),
        "paths": {
            k: v
            for k, v in layout.items()
            if k
            not in {
                "root",
                "explicit",
                "durable_root",
                "ephemeral_root",
                "durable_explicit",
                "ephemeral_explicit",
                "split",
            }
        },
        "disk_total_bytes": durable_usage.total,
        "disk_free_bytes": durable_usage.free,
        "ephemeral_disk_total_bytes": ephemeral_usage.total,
        "ephemeral_disk_free_bytes": ephemeral_usage.free,
    }


def storage_status() -> dict[str, object]:
    """Internal detailed storage status for durable and ephemeral roots."""
    roots = configured_storage_roots()
    durable_root = str(roots["durable_root"])
    ephemeral_root = str(roots["ephemeral_root"])
    status: dict[str, object] = {
        "root": durable_root,
        "explicit": bool(roots["durable_explicit"]),
        "ephemeral_root": ephemeral_root,
        "split": bool(roots["split"]),
        "available": False,
        "ephemeral_available": False,
    }
    try:
        _probe_writable(durable_root)
        usage = shutil.disk_usage(durable_root)
        status.update({
            "available": True,
            "disk_total_bytes": usage.total,
            "disk_free_bytes": usage.free,
        })
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"

    try:
        _probe_writable(ephemeral_root)
        usage = shutil.disk_usage(ephemeral_root)
        status.update({
            "ephemeral_available": True,
            "ephemeral_disk_total_bytes": usage.total,
            "ephemeral_disk_free_bytes": usage.free,
        })
    except Exception as exc:  # noqa: BLE001
        status["ephemeral_error"] = f"{type(exc).__name__}: {exc}"
    return status


def public_storage_status(status: Mapping[str, object] | None = None) -> dict[str, object]:
    """Return public-safe storage health without filesystem-path disclosure.

    Legacy/unified storage keeps the historical response shape exactly. The
    split-storage extension is additive only when split mode is actually active,
    so old exact-shape callers do not regress merely because the implementation
    learned about an optional ephemeral root.
    """
    raw = dict(status) if status is not None else storage_status()
    split = bool(raw.get("split"))
    out: dict[str, object] = {
        "available": bool(raw.get("available")),
        "explicit_root_configured": bool(raw.get("explicit")),
    }
    total = raw.get("disk_total_bytes")
    free = raw.get("disk_free_bytes")
    if isinstance(total, int) and total >= 0:
        out["disk_total_bytes"] = total
    if isinstance(free, int) and free >= 0:
        out["disk_free_bytes"] = free
    if isinstance(total, int) and total > 0 and isinstance(free, int) and free >= 0:
        out["disk_free_percent"] = round((free / total) * 100, 1)
    if not out["available"]:
        out["error"] = "storage_unavailable"

    if split:
        ephemeral_available = bool(raw.get("ephemeral_available", raw.get("available")))
        out["split_storage"] = True
        out["ephemeral_available"] = ephemeral_available
        ephemeral_total = raw.get("ephemeral_disk_total_bytes")
        ephemeral_free = raw.get("ephemeral_disk_free_bytes")
        if isinstance(ephemeral_total, int) and ephemeral_total >= 0:
            out["ephemeral_disk_total_bytes"] = ephemeral_total
        if isinstance(ephemeral_free, int) and ephemeral_free >= 0:
            out["ephemeral_disk_free_bytes"] = ephemeral_free
        if (
            isinstance(ephemeral_total, int)
            and ephemeral_total > 0
            and isinstance(ephemeral_free, int)
            and ephemeral_free >= 0
        ):
            out["ephemeral_disk_free_percent"] = round((ephemeral_free / ephemeral_total) * 100, 1)
        if not ephemeral_available:
            out["ephemeral_error"] = "ephemeral_storage_unavailable"
    return out
