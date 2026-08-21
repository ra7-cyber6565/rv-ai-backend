"""Asynchronous research job runner with durable bounded local results.

Deep/MAXIMUM research can outlive an HTTP request. This runner returns a job id
immediately, limits concurrency to protect free quotas, and persists job state
under the configured Infinity data root so completed results survive process
restarts.

Important honesty rules:
- a process restart cannot magically resume Python work that was running in
  memory; queued/running jobs reload as ``interrupted``;
- completed results are stored in separate gzip JSON files instead of growing
  one unbounded metadata JSON forever;
- per-result persistence is bounded and may be compacted when exceptionally
  large, with that fact disclosed in job metadata;
- persistence failure does not rewrite a successfully completed research run as
  a fake model/research failure. It remains available in memory for the current
  process and reports that durability was not achieved;
- the JSON job ledger is single-writer. A cross-process OS lock fails closed if
  a second Python worker tries to own the same durable store;
- persisted result filenames are treated as untrusted metadata and are never
  allowed to escape the managed ``results`` directory;
- when cloud archive is explicitly enabled, durable retry intent is recorded
  before history pruning can forget a result. Job-history pruning never deletes
  those local bytes; only the separate VERIFIED-archive cleanup path may do so.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from utils.process_lock import ExclusiveProcessFileLock, ProcessLockError
from utils.storage_paths import configured_root, ensure_layout
from utils.storage_quota import assert_capacity


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


MAX_WORKERS = _positive_int("RESEARCH_JOB_WORKERS", 1, 2)
MAX_JOBS = _positive_int("RESEARCH_JOB_HISTORY", 50, 200)
MAX_RESULT_BYTES = _positive_int("RESEARCH_JOB_RESULT_MAX_MB", 8, 64) * 1024 * 1024

_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|access[_-]?token|refresh[_-]?token|client[_-]?secret|secret)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SAFE_RESULT_FILE_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}\.json\.gz$")
_ARCHIVE_DISABLED = {"", "none", "off", "disabled"}


def _safe_error(exc: Exception, *, limit: int = 240) -> str:
    """Return a short user-safe error without provider trace/token leakage."""
    message = " ".join(str(exc).split())
    message = _SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}=[hidden]", message)
    message = _GOOGLE_KEY_RE.sub("[hidden-key]", message)
    message = _URL_RE.sub("[url-hidden]", message)
    lowered = message.lower()
    if any(marker in lowered for marker in (
        "traceback (most recent call last)",
        "resourceexhausted",
        "protobuf",
        "google.rpc",
        "grpc._channel",
        "<html",
        "<!doctype html",
    )):
        message = "Provider/service error; technical details hidden. Retry or use an available free fallback."
    if not message:
        message = "Research worker error"
    return f"{type(exc).__name__}: {message[:limit]}"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _clamp_json(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 6,
    string_limit: int = 100_000,
    list_limit: int = 100,
    dict_limit: int = 200,
) -> Any:
    """Deterministically bound pathological nested research output."""
    if depth >= max_depth:
        if isinstance(value, (dict, list, tuple)):
            return "[nested content compacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= string_limit:
            return value
        return value[:string_limit] + "\n[content compacted for durable storage]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        items = list(value.items())
        for key, child in items[:dict_limit]:
            out[str(key)] = _clamp_json(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
        if len(items) > dict_limit:
            out["_compacted_keys"] = len(items) - dict_limit
        return out
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        out = [
            _clamp_json(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                string_limit=string_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for child in values[:list_limit]
        ]
        if len(values) > list_limit:
            out.append({"_compacted_items": len(values) - list_limit})
        return out
    return str(value)[:string_limit]


def _bounded_result(result: Dict[str, Any], max_bytes: int) -> tuple[bytes, int, bool]:
    """Serialize a result within the durable per-job cap.

    Returns ``(stored_json_bytes, original_serialized_bytes, compacted)``.
    """
    raw = _json_bytes(result)
    original_size = len(raw)
    if original_size <= max_bytes:
        return raw, original_size, False

    for string_limit, list_limit, dict_limit, max_depth in (
        (100_000, 100, 200, 6),
        (25_000, 50, 100, 5),
        (5_000, 20, 50, 4),
    ):
        compacted = _clamp_json(
            result,
            string_limit=string_limit,
            list_limit=list_limit,
            dict_limit=dict_limit,
            max_depth=max_depth,
        )
        if isinstance(compacted, dict):
            compacted["_storage_compacted"] = True
            compacted["_original_serialized_bytes"] = original_size
        candidate = _json_bytes(compacted)
        if len(candidate) <= max_bytes:
            return candidate, original_size, True

    priority = (
        "answer",
        "final_answer",
        "final",
        "report",
        "summary",
        "conclusion",
        "synthesis",
        "run_status",
        "status",
        "coverage",
        "audit",
        "citations",
        "sources",
        "hypotheses",
    )
    minimal: Dict[str, Any] = {
        "_storage_compacted": True,
        "_original_serialized_bytes": original_size,
        "_original_top_level_keys": list(result.keys())[:200],
        "_storage_note": (
            "Result exceeded the configured durable-storage cap. Final/report/audit fields were retained where possible; "
            "large intermediate retrieval/debug payloads were compacted."
        ),
    }
    for key in priority:
        if key in result:
            minimal[key] = _clamp_json(
                result[key],
                max_depth=4,
                string_limit=10_000,
                list_limit=20,
                dict_limit=50,
            )
    candidate = _json_bytes(minimal)
    if len(candidate) <= max_bytes:
        return candidate, original_size, True

    emergency = {
        "_storage_compacted": True,
        "_original_serialized_bytes": original_size,
        "_storage_note": "Result was too large for the configured durable-storage cap.",
    }
    return _json_bytes(emergency), original_size, True


def default_job_store_path() -> str:
    folder = Path(ensure_layout()["research_memory"]) / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / "research_jobs.json")


@dataclass
class Job:
    job_id: str
    project_id: str
    question: str
    mode: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: str = ""
    result_file: str = ""
    result_bytes: int = 0
    result_compacted: bool = False
    durable: bool = False
    storage_warning: str = ""

    def public(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "question": self.question,
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result_durable": bool(self.durable and self.status == "completed"),
            "result_compacted": self.result_compacted,
            "result_bytes": self.result_bytes,
            "storage_warning": self.storage_warning,
        }


class ResearchJobRunner:
    def __init__(
        self,
        max_workers: int = MAX_WORKERS,
        max_jobs: int = MAX_JOBS,
        store_path: str | None = None,
        persist: bool = True,
        max_result_bytes: int = MAX_RESULT_BYTES,
        enforce_process_lock: bool | None = None,
        archive_runtime_override: Any = None,
    ):
        self.max_jobs = max(1, max_jobs)
        self.max_result_bytes = max(1024, int(max_result_bytes))
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="infinity-research",
        )
        self._jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.RLock()
        self._persist_enabled = bool(persist)
        self._store_path = os.path.abspath(store_path or default_job_store_path()) if persist else ""
        self._result_dir = os.path.join(os.path.dirname(self._store_path), "results") if persist else ""
        self._process_lock: ExclusiveProcessFileLock | None = None
        self._archive_runtime_override = archive_runtime_override
        should_lock = _bool_env("RESEARCH_JOB_PROCESS_LOCK", True) if enforce_process_lock is None else bool(enforce_process_lock)
        if self._persist_enabled:
            Path(self._store_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self._result_dir).mkdir(parents=True, exist_ok=True)
            if should_lock:
                guard = ExclusiveProcessFileLock(self._store_path + ".process.lock")
                try:
                    guard.acquire()
                except ProcessLockError as exc:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                    raise RuntimeError(
                        "Durable research job store already another Python process use kar raha hai. "
                        "JSON corruption se bachne ke liye multiple backend workers blocked hain; single worker use karein."
                    ) from exc
                self._process_lock = guard
            try:
                self._load_persisted()
            except Exception:
                self.close(wait=False)
                raise

    def close(self, *, wait: bool = True) -> None:
        """Release worker threads and the single-writer process lock."""
        try:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)
        finally:
            if self._process_lock is not None:
                self._process_lock.release()
                self._process_lock = None

    def _inside_configured_root(self, path: str) -> bool:
        root, explicit = configured_root()
        if not explicit:
            return False
        try:
            return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
        except ValueError:
            return False

    def _safe_result_path_from_name(self, filename: str) -> str:
        name = str(filename or "").strip()
        if not name or os.path.isabs(name) or name != os.path.basename(name):
            return ""
        if not _SAFE_RESULT_FILE_RE.fullmatch(name):
            return ""
        candidate = os.path.abspath(os.path.join(self._result_dir, name))
        try:
            if os.path.commonpath([candidate, os.path.abspath(self._result_dir)]) != os.path.abspath(self._result_dir):
                return ""
        except ValueError:
            return ""
        return candidate

    def _result_path(self, job: Job) -> str:
        return self._safe_result_path_from_name(job.result_file)

    @staticmethod
    def _archive_remote_path(job: Job) -> str:
        return f"research-results/{job.job_id}.json.gz"

    def _archive_runtime(self):
        if self._archive_runtime_override is not None:
            return self._archive_runtime_override
        from storage.archive_runtime import archive_runtime
        return archive_runtime

    @staticmethod
    def _archive_explicitly_disabled() -> bool:
        raw = str(os.getenv("CLOUD_ARCHIVE_PROVIDER", "none") or "none").strip().lower()
        return raw in _ARCHIVE_DISABLED

    def _record_archive_intent_locked(self, job: Job, path: str) -> bool:
        """Queue cloud intent without letting provider failure fail research."""
        if not path or not os.path.isfile(path):
            return False
        try:
            runtime = self._archive_runtime()
            if not runtime.archive_required():
                return True
            result = runtime.submit_file(path, self._archive_remote_path(job))
            if result.get("intent_recorded"):
                return True
            note = "Cloud archive intent save nahi ho saka; local result delete nahi kiya jayega."
            if note not in job.storage_warning:
                job.storage_warning = (job.storage_warning + " " + note).strip()
            return False
        except Exception:
            # If cloud is not explicitly enabled, archive plumbing is optional.
            # If it *is* enabled, fail closed for deletion and retain local bytes.
            return self._archive_explicitly_disabled()

    def _persist_result_locked(self, job: Job) -> None:
        if not self._persist_enabled or job.status != "completed" or job.result is None:
            return
        stored, original_size, compacted = _bounded_result(job.result, self.max_result_bytes)
        compressed = gzip.compress(stored, compresslevel=6)
        if self._inside_configured_root(self._result_dir):
            assert_capacity(len(compressed))

        final_name = f"{job.job_id}.json.gz"
        final_path = self._safe_result_path_from_name(final_name)
        if not final_path:
            raise RuntimeError("Generated research result path invalid hai")
        fd, temp_path = tempfile.mkstemp(prefix=f"{job.job_id}_", suffix=".json.gz.tmp", dir=self._result_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(compressed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, final_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        job.result_file = final_name
        job.result_bytes = original_size
        job.result_compacted = compacted
        job.durable = True
        job.storage_warning = (
            "Large result durable storage ke liye compact kiya gaya; final/report/audit fields ko priority di gayi."
            if compacted else ""
        )
        job.result = None
        # Persisted local result is already safe. Cloud archival is additive and
        # non-blocking; a provider outage only leaves durable retry intent/local
        # bytes, never converts completed research into a failure.
        self._record_archive_intent_locked(job, final_path)

    def _load_result_locked(self, job: Job) -> Optional[Dict[str, Any]]:
        if job.result is not None:
            return job.result
        path = self._result_path(job)
        if not path:
            job.durable = False
            if job.result_file:
                job.storage_warning = "Persisted result path invalid tha; unsafe path ko refuse kiya gaya."
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
            return {"result": data}
        except Exception as exc:  # noqa: BLE001
            job.durable = False
            job.storage_warning = "Persisted research result read nahi ho saka; file missing/corrupt ho sakti hai."
            return {
                "_result_unavailable": True,
                "message": "Persisted research result safely read nahi ho saka.",
                "error_type": type(exc).__name__,
            }

    def _delete_result_file_locked(self, job: Job) -> bool:
        """Apply retention without violating an enabled cloud-archive contract.

        With archive disabled, old result files follow the normal bounded-history
        lifecycle and may be deleted.  With archive enabled, history metadata may
        be pruned after durable archive intent is recorded, but the local bytes are
        intentionally retained.  Verified-file cleanup is centralized in
        ``cleanup_verified_archives`` so manifest ``local_deleted`` state stays
        correct and no second deletion implementation drifts from the safety rule.
        """
        path = self._result_path(job)
        if not path or not os.path.exists(path):
            return True
        if os.path.islink(path):
            return True

        try:
            runtime = self._archive_runtime()
            if runtime.archive_required():
                # If already verified this returns True; we still leave deletion
                # to the centralized verified cleanup path. Otherwise ensure a
                # crash-safe retry record exists before forgetting job metadata.
                if runtime.local_delete_allowed(path, self._archive_remote_path(job)):
                    return True
                return self._record_archive_intent_locked(job, path)
        except Exception:
            if not self._archive_explicitly_disabled():
                return False

        try:
            if os.path.isfile(path):
                os.remove(path)
            return True
        except OSError:
            return False

    def _quarantine_corrupt_store(self) -> None:
        if not self._store_path or not os.path.exists(self._store_path):
            return
        try:
            broken = f"{self._store_path}.corrupt-{int(time.time())}"
            os.replace(self._store_path, broken)
        except OSError:
            pass

    def _read_persisted_rows(self) -> list[dict[str, Any]]:
        if not self._store_path or not os.path.exists(self._store_path):
            return []
        try:
            with open(self._store_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except json.JSONDecodeError as exc:
            self._quarantine_corrupt_store()
            raise RuntimeError("Research job history JSON corrupt hai; bad copy quarantine ki gayi.") from exc
        except OSError as exc:
            # A permission/disk read failure is not corruption. Never rename a
            # valid store merely because the filesystem is temporarily unhappy.
            raise RuntimeError("Research job history read nahi ho saki") from exc

        if not isinstance(raw, dict) or not isinstance(raw.get("jobs", []), list):
            self._quarantine_corrupt_store()
            raise RuntimeError("Research job history schema invalid hai; bad copy quarantine ki gayi.")
        return [row for row in raw.get("jobs", []) if isinstance(row, dict)]

    def _load_persisted(self) -> None:
        rows = self._read_persisted_rows()
        allowed = set(Job.__dataclass_fields__)
        for row in rows:
            if not row.get("job_id"):
                continue
            payload = {k: v for k, v in row.items() if k in allowed}
            try:
                job = Job(**payload)
            except (TypeError, ValueError):
                # One malformed row should not destroy every valid historical job.
                continue

            if job.result_file and not self._safe_result_path_from_name(job.result_file):
                job.result_file = ""
                job.durable = False
                job.storage_warning = "Persisted result path invalid tha; unsafe path ko ignore kiya gaya."

            if job.status in {"queued", "running"}:
                job.status = "interrupted"
                job.error = "Server/process restart ke wajah se running research resume nahi ho saki."
                job.finished_at = time.time()
                job.durable = False
            elif job.status == "completed" and job.result is not None and not job.result_file:
                try:
                    self._persist_result_locked(job)
                except Exception as exc:  # noqa: BLE001
                    job.durable = False
                    job.storage_warning = f"Legacy result migration failed: {type(exc).__name__}"
            elif job.status == "completed" and job.result_file:
                # Enabling Drive later should pick up already-durable completed
                # results too; provider-disabled mode remains a no-op.
                path = self._result_path(job)
                if path and os.path.isfile(path):
                    self._record_archive_intent_locked(job, path)
            self._jobs[job.job_id] = job

        self._prune_locked()
        # If this write fails, startup fails closed but the valid input store is
        # not mislabeled as corrupt.
        self._persist_locked()

    def _persist_locked(self) -> None:
        if not self._persist_enabled or not self._store_path:
            return
        parent = os.path.dirname(self._store_path)
        fd, temp_path = tempfile.mkstemp(prefix="research_jobs_", suffix=".json", dir=parent)
        try:
            rows = []
            for job in sorted(self._jobs.values(), key=lambda j: j.created_at):
                row = asdict(job)
                if job.status == "completed":
                    row["result"] = None
                rows.append(row)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 2, "jobs": rows}, handle, ensure_ascii=False, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._store_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def submit(
        self,
        *,
        project_id: str,
        question: str,
        mode: str,
        custom: Optional[Dict[str, Any]],
        run: Callable[..., Dict[str, Any]],
    ) -> Job:
        job_id = uuid.uuid4().hex
        job = Job(
            job_id=job_id,
            project_id=project_id or "default",
            question=(question or "").strip(),
            mode=(mode or "DEEP").upper(),
        )
        if not job.question:
            raise ValueError("question khaali nahi ho sakta")

        with self._lock:
            self._prune_locked()
            self._jobs[job_id] = job
            self._persist_locked()
            future = self._executor.submit(self._execute, job_id, custom or {}, run)
            self._futures[job_id] = future
        return job

    def _execute(
        self,
        job_id: str,
        custom: Dict[str, Any],
        run: Callable[..., Dict[str, Any]],
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = time.time()
            try:
                self._persist_locked()
            except Exception as exc:  # noqa: BLE001
                job.storage_warning = f"Running-state persistence failed: {type(exc).__name__}"

        try:
            result = run(
                question=job.question,
                project_id=job.project_id,
                depth_mode=job.mode,
                custom=custom or None,
                job_id=job.job_id,
            )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job.status = "failed"
                job.error = _safe_error(exc)
                job.finished_at = time.time()
                job.durable = False
                try:
                    self._persist_locked()
                except Exception:
                    pass
                self._futures.pop(job_id, None)
            return

        with self._lock:
            job.result = result if isinstance(result, dict) else {"result": result}
            job.status = "completed"
            job.finished_at = time.time()
            job.error = ""
            if self._persist_enabled:
                try:
                    self._persist_result_locked(job)
                except Exception as exc:  # noqa: BLE001
                    job.durable = False
                    job.storage_warning = (
                        "Research complete hua, lekin durable result save nahi ho saka: "
                        f"{type(exc).__name__}. Current process me result available hai."
                    )
            try:
                self._persist_locked()
            except Exception as exc:  # noqa: BLE001
                job.durable = False
                job.storage_warning = (
                    "Research complete hua, lekin job metadata durable save nahi ho saka: "
                    f"{type(exc).__name__}."
                )
            self._futures.pop(job_id, None)

    def get(self, job_id: str, *, include_result: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            data = job.public()
            if include_result and job.status == "completed":
                loaded = self._load_result_locked(job)
                data["result"] = loaded if loaded is not None else {
                    "_result_unavailable": True,
                    "message": "Persisted research result available nahi hai.",
                }
                data["result_durable"] = bool(job.durable and loaded is not None)
                data["storage_warning"] = job.storage_warning
            return data

    def list(self, limit: int = 20) -> list[Dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.public() for j in jobs[:limit]]

    def _prune_locked(self) -> None:
        if len(self._jobs) < self.max_jobs:
            return
        finished_states = {"completed", "failed", "interrupted"}
        finished = sorted(
            (job for job in self._jobs.values() if job.status in finished_states),
            key=lambda j: j.finished_at or j.created_at,
        )
        while len(self._jobs) >= self.max_jobs and finished:
            old = finished.pop(0)
            if not self._delete_result_file_locked(old):
                # Cloud archive was explicitly enabled but we could not even
                # persist safe archive intent. Keep metadata + bytes and try the
                # next finished job; if none are safe, reject a new submission
                # rather than destroy the only local copy.
                continue
            self._jobs.pop(old.job_id, None)
            self._futures.pop(old.job_id, None)
        if len(self._jobs) >= self.max_jobs:
            raise RuntimeError("Research job queue full hai; pehle current job complete/archive hone do")


runner = ResearchJobRunner()
