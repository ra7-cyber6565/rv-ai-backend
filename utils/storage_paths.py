"""Central storage layout for Infinity Research AI.

The laptop can keep heavy runtime data off C: by setting either:

    INFINITY_DATA_ROOT=D:\\InfinityResearchAI

or the older compatible variable:

    INFINITY_WORK_ROOT=D:\\InfinityResearchAI

When an explicit root is configured, this module fails closed if it is missing
or unwritable. It does not silently fall back to the system drive.

Cloud deployments may leave both variables empty; in that case a repository-
local ``runtime_data`` folder is used. This fallback is for development/cloud
containers only, not the recommended laptop setup.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parent.parent
SUBDIRS = (
    "archive",
    "cache",
    "knowledge",
    "logs",
    "models",
    "research_memory",
    "temp",
    "uploads",
    "vector_db",
)


def _clean(raw: object) -> str:
    return str(raw or "").strip()


def configured_root(env: Mapping[str, str] | None = None) -> tuple[str, bool]:
    """Return ``(path, explicitly_configured)``."""
    source = env if env is not None else os.environ
    raw = _clean(source.get("INFINITY_DATA_ROOT")) or _clean(source.get("INFINITY_WORK_ROOT"))
    if raw:
        return os.path.abspath(os.path.expanduser(raw)), True
    return str(REPO_ROOT / "runtime_data"), False


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
    root, explicit = configured_root(env)
    _probe_writable(root)
    paths = {"root": root, "explicit": str(explicit).lower()}
    for name in SUBDIRS:
        folder = Path(root) / name
        folder.mkdir(parents=True, exist_ok=True)
        paths[name] = str(folder)
    return paths


def _set_path_env(name: str, value: str, *, force: bool) -> None:
    if force or not _clean(os.environ.get(name)):
        os.environ[name] = value


def configure_process_storage() -> dict[str, object]:
    """Configure model/cache/temp/database locations before heavy imports.

    If the user explicitly selected D: (or another root), model downloads,
    ChromaDB, research memory, knowledge metadata and temp/cache paths are
    redirected there. Explicit selection wins over stale cache variables so the
    app cannot quietly keep filling C:.
    """
    layout = ensure_layout()
    root, explicit = configured_root()

    # App-owned locations.
    _set_path_env("KNOWLEDGE_GRAPH_FILE", str(Path(layout["knowledge"]) / "knowledge_graph.json"), force=explicit)
    _set_path_env("KNOWLEDGE_STORE_FILE", str(Path(layout["knowledge"]) / "knowledge_store.json"), force=explicit)
    _set_path_env("RESEARCH_MEMORY_DIR", layout["research_memory"], force=explicit)
    _set_path_env("CHROMA_DB_DIR", layout["vector_db"], force=explicit)
    _set_path_env("INFINITY_ARCHIVE_DIR", layout["archive"], force=explicit)

    # Heavy third-party caches/models.
    cache_root = Path(layout["cache"])
    model_root = Path(layout["models"])
    _set_path_env("HF_HOME", str(model_root / "huggingface"), force=explicit)
    _set_path_env("HUGGINGFACE_HUB_CACHE", str(model_root / "huggingface" / "hub"), force=explicit)
    _set_path_env("TRANSFORMERS_CACHE", str(model_root / "transformers"), force=explicit)
    _set_path_env("SENTENCE_TRANSFORMERS_HOME", str(model_root / "sentence_transformers"), force=explicit)
    _set_path_env("TORCH_HOME", str(model_root / "torch"), force=explicit)
    _set_path_env("XDG_CACHE_HOME", str(cache_root), force=explicit)

    # Python/OS temp files. Set all common variants for Windows/Linux tools.
    for temp_name in ("TMP", "TEMP", "TMPDIR"):
        _set_path_env(temp_name, layout["temp"], force=explicit)

    usage = shutil.disk_usage(root)
    return {
        "root": root,
        "explicit": explicit,
        "paths": {k: v for k, v in layout.items() if k not in {"root", "explicit"}},
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
    }


def storage_status() -> dict[str, object]:
    """Internal detailed storage status.

    This deliberately includes the absolute root and diagnostic error text for
    local logs/debugging. Do not expose this mapping directly from a public API;
    use :func:`public_storage_status` instead.
    """
    root, explicit = configured_root()
    status: dict[str, object] = {"root": root, "explicit": explicit, "available": False}
    try:
        _probe_writable(root)
        usage = shutil.disk_usage(root)
        status.update({
            "available": True,
            "disk_total_bytes": usage.total,
            "disk_free_bytes": usage.free,
        })
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


def public_storage_status(status: Mapping[str, object] | None = None) -> dict[str, object]:
    """Return public-safe storage health without filesystem-path disclosure.

    ``storage_status()`` is intentionally useful for local diagnostics and can
    contain an absolute Windows/Linux path plus raw exception text. Public
    ``/health``/``/api`` responses must not leak those details. This helper keeps
    only aggregate capacity/readiness fields and replaces raw errors with a stable
    coarse code.

    ``status`` may be supplied by tests/callers to sanitize an already-collected
    internal mapping without probing the disk again.
    """
    raw = dict(status) if status is not None else storage_status()
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
    return out
