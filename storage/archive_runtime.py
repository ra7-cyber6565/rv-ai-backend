"""Crash-safe, non-blocking runtime wiring for optional cloud archives.

The archive provider is optional, but once the owner explicitly enables one the
backend must never delete a local finished artifact merely because an upload was
scheduled.  Every submission therefore records durable retry intent *before* a
background worker touches the network.  A successful upload is re-statted and
verified by :class:`utils.cloud_storage.ArchiveCoordinator`; only an exact
verified manifest record may later authorize local cleanup.

This module intentionally does not auto-delete local files.  It also exposes
only aggregate/public-safe operational status: no OAuth tokens, rclone remote
names, absolute local paths, filenames, or raw provider errors are returned.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from storage.provider_factory import build_provider, provider_status
from utils.archive_manifest import ArchiveManifest
from utils.archive_retry import ArchiveRetryQueue
from utils.cloud_storage import ArchiveCoordinator
from utils.storage_quota import storage_pressure


_DISABLED_NAMES = {"", "none", "off", "disabled"}


def _positive_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _configured_raw_name() -> str:
    return str(os.getenv("CLOUD_ARCHIVE_PROVIDER", "none") or "none").strip().lower()


class ArchiveRuntime:
    """Single-process background archive dispatcher with durable intent.

    The durable retry queue is the crash boundary.  ``submit_file`` writes an
    entry there synchronously, then (when the provider is ready) schedules the
    slower upload/verification on one bounded worker.  If the process exits
    between those steps, the next process still has the retry record and local
    path.
    """

    def __init__(
        self,
        *,
        manifest: ArchiveManifest | None = None,
        retry_queue: ArchiveRetryQueue | None = None,
        provider_builder: Callable[[], Any] = build_provider,
        provider_status_func: Callable[[], dict[str, Any]] = provider_status,
        max_pending: int | None = None,
    ):
        self.manifest = manifest or ArchiveManifest()
        self.retry_queue = retry_queue or ArchiveRetryQueue()
        self._provider_builder = provider_builder
        self._provider_status = provider_status_func
        self._max_pending = max_pending or _positive_int(
            "ARCHIVE_BACKGROUND_QUEUE_MAX", 32, 1, 200
        )
        self._lock = threading.RLock()
        self._executor: ThreadPoolExecutor | None = None
        self._futures: set[Future] = set()
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._capacity_deferred = 0

    def archive_required(self) -> bool:
        """Whether config says local cleanup must wait for cloud verification.

        Unknown provider names are deliberately treated as *required* rather
        than disabled.  A typo must fail closed for deletion instead of silently
        discarding the only local copy.
        """
        return _configured_raw_name() not in _DISABLED_NAMES

    def _status(self) -> dict[str, Any]:
        try:
            row = dict(self._provider_status() or {})
        except Exception:
            return {
                "provider": "invalid",
                "enabled": self.archive_required(),
                "ready": False,
                "reason": "archive provider status unavailable",
            }
        # Treat an invalid-but-explicit provider as enabled for local-retention
        # safety even if the factory status itself reports enabled=False.
        if self.archive_required() and row.get("provider") == "invalid":
            row["enabled"] = True
            row["ready"] = False
        return row

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="infinity-archive",
                )
            return self._executor

    def _coordinator(self) -> ArchiveCoordinator:
        provider = self._provider_builder()
        if provider is None:
            raise RuntimeError("cloud archive provider disabled")
        return ArchiveCoordinator(
            provider,
            manifest=self.manifest,
            retry_queue=self.retry_queue,
        )

    def _done(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
            try:
                ok = bool(future.result())
            except Exception:
                ok = False
            if ok:
                self._completed += 1
            else:
                self._failed += 1

    def _run_archive(self, local_path: str, remote_path: str) -> bool:
        try:
            coordinator = self._coordinator()
            # Old due work gets a tiny bounded chance before the newest file.
            # This prevents a steady stream of new research from starving old
            # failed uploads, without turning one request into an unbounded loop.
            try:
                coordinator.retry_due(
                    limit=_positive_int("ARCHIVE_RETRY_PER_KICK", 2, 1, 10)
                )
            except Exception:
                pass
            result = coordinator.archive(local_path, remote_path, delete_local=False)
            return bool(result.get("ok") and result.get("verified"))
        except Exception:
            # ArchiveCoordinator has already persisted/re-written retry intent on
            # upload/verification failures.  Never let a cloud error escape into
            # the research completion path.
            return False

    def submit_file(self, local_path: str, remote_path: str) -> dict[str, Any]:
        """Persist archive intent and schedule upload when possible.

        The returned shape is deliberately coarse and safe to attach to internal
        logs/tests.  It contains no local path, remote name, token, or raw error.
        """
        if not os.path.isfile(local_path):
            return {
                "enabled": self.archive_required(),
                "accepted": False,
                "intent_recorded": False,
                "reason": "local_file_missing",
            }
        if not str(remote_path or "").strip():
            return {
                "enabled": self.archive_required(),
                "accepted": False,
                "intent_recorded": False,
                "reason": "remote_path_invalid",
            }

        status = self._status()
        if not self.archive_required():
            return {
                "enabled": False,
                "accepted": False,
                "intent_recorded": False,
                "reason": "disabled",
            }

        provider_name = str(status.get("provider") or "").strip()
        if not provider_name or provider_name in {"none", "invalid"}:
            # We cannot write a meaningful retry record without a valid provider
            # identity.  Local cleanup will therefore remain blocked.
            return {
                "enabled": True,
                "accepted": False,
                "intent_recorded": False,
                "reason": "provider_configuration_invalid",
            }

        try:
            # Durable intent FIRST.  archive() removes this exact record only
            # after verified success.
            self.retry_queue.enqueue(
                local_path=local_path,
                remote_path=remote_path,
                provider=provider_name,
                error="archive_scheduled",
            )
        except Exception:
            return {
                "enabled": True,
                "accepted": False,
                "intent_recorded": False,
                "reason": "retry_intent_persist_failed",
            }

        if not status.get("ready"):
            return {
                "enabled": True,
                "accepted": False,
                "intent_recorded": True,
                "reason": "provider_not_ready",
            }

        with self._lock:
            if len(self._futures) >= self._max_pending:
                self._capacity_deferred += 1
                return {
                    "enabled": True,
                    "accepted": False,
                    "intent_recorded": True,
                    "reason": "background_queue_full",
                }
            future = self._ensure_executor().submit(
                self._run_archive,
                os.path.abspath(local_path),
                str(remote_path),
            )
            self._futures.add(future)
            self._submitted += 1
            future.add_done_callback(self._done)
        return {
            "enabled": True,
            "accepted": True,
            "intent_recorded": True,
            "reason": "scheduled",
        }

    def kick_retries(self, *, limit: int = 5) -> dict[str, Any]:
        """Schedule one bounded retry batch; useful for an admin/operator nudge."""
        status = self._status()
        if not self.archive_required():
            return {"accepted": False, "reason": "disabled"}
        if not status.get("ready"):
            return {"accepted": False, "reason": "provider_not_ready"}

        with self._lock:
            if len(self._futures) >= self._max_pending:
                self._capacity_deferred += 1
                return {"accepted": False, "reason": "background_queue_full"}

            def _work() -> bool:
                try:
                    result = self._coordinator().retry_due(
                        limit=max(1, min(20, int(limit)))
                    )
                    return int(result.get("failed", 0) or 0) == 0
                except Exception:
                    return False

            future = self._ensure_executor().submit(_work)
            self._futures.add(future)
            self._submitted += 1
            future.add_done_callback(self._done)
        return {"accepted": True, "reason": "scheduled"}

    def local_delete_allowed(self, local_path: str, remote_path: str) -> bool:
        """Fail-closed check used before lifecycle cleanup deletes local bytes."""
        if not self.archive_required():
            return True
        status = self._status()
        provider_name = str(status.get("provider") or "").strip().lower()
        if not provider_name or provider_name in {"none", "invalid"}:
            return False

        local = os.path.normcase(os.path.abspath(local_path))
        remote = str(remote_path or "").strip()
        try:
            rows = self.manifest.items()
        except Exception:
            return False
        for item in rows:
            item_local = os.path.normcase(os.path.abspath(str(item.get("local_path") or "")))
            if item_local != local:
                continue
            if str(item.get("provider") or "").strip().lower() != provider_name:
                continue
            if str(item.get("remote_path") or "").strip() != remote:
                continue
            reference = str(item.get("archive_id") or "")
            return bool(reference and self.manifest.safe_to_delete_local(reference))
        return False

    def public_status(self) -> dict[str, Any]:
        """Aggregate status only; no local/remote paths or raw provider errors."""
        provider = self._status()

        manifest_counts: dict[str, int] = {}
        manifest_providers: dict[str, int] = {}
        manifest_error = False
        try:
            rows = self.manifest.items()
            for item in rows:
                state = str(item.get("status") or "unknown")
                manifest_counts[state] = manifest_counts.get(state, 0) + 1
                name = str(item.get("provider") or "unknown")
                manifest_providers[name] = manifest_providers.get(name, 0) + 1
        except Exception:
            rows = []
            manifest_error = True

        retry_error = False
        try:
            retry = dict(self.retry_queue.summary())
        except Exception:
            retry = {"pending": 0, "missing_local_files": 0, "providers": {}}
            retry_error = True

        pressure_error = False
        try:
            pressure = storage_pressure()
            storage = {
                "app_bytes": int(pressure.get("app_bytes", 0) or 0),
                "max_local_bytes": int(pressure.get("max_local_bytes", 0) or 0),
                "disk_free_bytes": int(pressure.get("disk_free_bytes", 0) or 0),
                "min_free_bytes": int(pressure.get("min_free_bytes", 0) or 0),
                "blocked": bool(pressure.get("blocked")),
                "reasons": list(pressure.get("reasons") or []),
            }
        except Exception:
            storage = {
                "app_bytes": 0,
                "max_local_bytes": 0,
                "disk_free_bytes": 0,
                "min_free_bytes": 0,
                "blocked": True,
                "reasons": ["storage_status_unavailable"],
            }
            pressure_error = True

        with self._lock:
            background = {
                "pending": len(self._futures),
                "max_pending": self._max_pending,
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "capacity_deferred": self._capacity_deferred,
            }

        # provider_status deliberately contains readiness booleans only.  Remove
        # its human `reason` field so future adapters cannot accidentally put a
        # command/path/account detail into this public endpoint.
        provider_public = {
            key: value for key, value in provider.items()
            if key in {
                "provider", "enabled", "ready", "remote_configured",
                "rclone_available",
            }
        }
        return {
            "archive_required_for_local_cleanup": self.archive_required(),
            "provider": provider_public,
            "manifest": {
                "records": len(rows),
                "by_status": manifest_counts,
                "by_provider": manifest_providers,
                "status_read_error": manifest_error,
            },
            "retry_queue": {
                "pending": int(retry.get("pending", 0) or 0),
                "missing_local_files": int(retry.get("missing_local_files", 0) or 0),
                "providers": dict(retry.get("providers") or {}),
                "status_read_error": retry_error,
            },
            "storage": storage,
            "storage_status_error": pressure_error,
            "background": background,
            "local_auto_delete": False,
        }

    def close(self, *, wait: bool = False) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=not wait)


archive_runtime = ArchiveRuntime()


__all__ = ["ArchiveRuntime", "archive_runtime"]
