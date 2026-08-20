"""In-process asynchronous research job runner.

Deep/MAXIMUM research can take long enough that a browser/proxy HTTP request
may time out even while the backend is still working. This runner lets the API
return a job id immediately, then clients poll status/result separately.

It uses only Python's standard library (₹0) and deliberately defaults to one
worker so multiple expensive research jobs cannot drain free quotas in parallel.
Jobs are process-local: a server restart marks in-flight work as lost, which is
reported honestly rather than pretending the result is durable.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))


MAX_WORKERS = _positive_int("RESEARCH_JOB_WORKERS", 1, 2)
MAX_JOBS = _positive_int("RESEARCH_JOB_HISTORY", 50, 200)


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
    def __init__(self, max_workers: int = MAX_WORKERS, max_jobs: int = MAX_JOBS):
        self.max_jobs = max(1, max_jobs)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="infinity-research",
        )
        self._jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.RLock()

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
        except Exception as exc:  # noqa: BLE001 - job boundary must capture failures
            with self._lock:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"[:1200]
                job.finished_at = time.time()
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
        finished = sorted(
            (job for job in self._jobs.values() if job.status in {"completed", "failed"}),
            key=lambda j: j.finished_at or j.created_at,
        )
        while len(self._jobs) >= self.max_jobs and finished:
            old = finished.pop(0)
            self._jobs.pop(old.job_id, None)
            self._futures.pop(old.job_id, None)
        if len(self._jobs) >= self.max_jobs:
            raise RuntimeError("Research job queue full hai; pehle current job complete hone do")


runner = ResearchJobRunner()
