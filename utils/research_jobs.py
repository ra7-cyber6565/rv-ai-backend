"""Asynchronous research job runner with durable local metadata/results.

Deep/MAXIMUM research can outlive an HTTP request. This runner returns a job id
immediately, limits concurrency to protect free quotas, and persists job state
under the configured Infinity data root so completed results survive process
restarts.

Important honesty rule: a process restart cannot magically resume Python work
that was running in memory. Previously queued/running jobs are therefore marked
``interrupted`` on reload instead of pretending they are still active.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from utils.storage_paths import ensure_layout


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))


MAX_WORKERS = _positive_int("RESEARCH_JOB_WORKERS", 1, 2)
MAX_JOBS = _positive_int("RESEARCH_JOB_HISTORY", 50, 200)


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

    def public(self, *, include_result: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "question": self.question,
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }
        if include_result and self.status == "completed":
            data["result"] = self.result
        return data


class ResearchJobRunner:
    def __init__(
        self,
        max_workers: int = MAX_WORKERS,
        max_jobs: int = MAX_JOBS,
        store_path: str | None = None,
        persist: bool = True,
    ):
        self.max_jobs = max(1, max_jobs)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="infinity-research",
        )
        self._jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.RLock()
        self._persist_enabled = bool(persist)
        self._store_path = os.path.abspath(store_path or default_job_store_path()) if persist else ""
        if self._persist_enabled:
            Path(self._store_path).parent.mkdir(parents=True, exist_ok=True)
            self._load_persisted()

    def _load_persisted(self) -> None:
        if not self._store_path or not os.path.exists(self._store_path):
            return
        try:
            with open(self._store_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            rows = raw.get("jobs", []) if isinstance(raw, dict) else []
            for row in rows:
                if not isinstance(row, dict) or not row.get("job_id"):
                    continue
                allowed = {field.name for field in Job.__dataclass_fields__.values()}
                payload = {k: v for k, v in row.items() if k in allowed}
                job = Job(**payload)
                if job.status in {"queued", "running"}:
                    job.status = "interrupted"
                    job.error = "Server/process restart ke wajah se running research resume nahi ho saki."
                    job.finished_at = time.time()
                self._jobs[job.job_id] = job
            self._prune_locked()
            self._persist_locked()
        except Exception:
            # Corrupt job history must never stop the research service from
            # starting. Preserve the bad file for inspection and start clean.
            try:
                broken = f"{self._store_path}.corrupt-{int(time.time())}"
                os.replace(self._store_path, broken)
            except Exception:
                pass
            self._jobs = {}

    def _persist_locked(self) -> None:
        if not self._persist_enabled or not self._store_path:
            return
        parent = os.path.dirname(self._store_path)
        fd, temp_path = tempfile.mkstemp(prefix="research_jobs_", suffix=".json", dir=parent)
        try:
            rows = [asdict(job) for job in sorted(self._jobs.values(), key=lambda j: j.created_at)]
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "jobs": rows}, handle, ensure_ascii=False, indent=2)
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
            self._persist_locked()
        try:
            result = run(
                question=job.question,
                project_id=job.project_id,
                depth_mode=job.mode,
                custom=custom or None,
                job_id=job.job_id,
            )
            with self._lock:
                job.result = result
                job.status = "completed"
                job.finished_at = time.time()
                self._persist_locked()
        except Exception as exc:  # noqa: BLE001 - job boundary must capture failures
            with self._lock:
                job.status = "failed"
                # Keep the stored/public error short and useful; provider raw
                # protobuf/tracebacks belong in technical logs, not user output.
                job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
                job.finished_at = time.time()
                self._persist_locked()
        finally:
            with self._lock:
                self._futures.pop(job_id, None)

    def get(self, job_id: str, *, include_result: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.public(include_result=include_result) if job else None

    def list(self, limit: int = 20) -> list[Dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.public(include_result=False) for j in jobs[:limit]]

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
            self._jobs.pop(old.job_id, None)
            self._futures.pop(old.job_id, None)
        if len(self._jobs) >= self.max_jobs:
            raise RuntimeError("Research job queue full hai; pehle current job complete hone do")


runner = ResearchJobRunner()
