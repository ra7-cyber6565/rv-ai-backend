"""
progress_tracker_api.py — Spec Section 13 (Research Progress)

Progress tracker already exists (utils/progress_tracker.py), lekin GET endpoint nahi tha.
Ye module simple wrapper hai jo stage updates ko API format mein deta hai.
"""
from __future__ import annotations

from typing import Dict, Optional, List
from datetime import datetime


class ProgressAPIWrapper:
    """
    Progress tracking ko API-friendly format mein expose karte ho.
    """

    def __init__(self):
        self.jobs: Dict[str, Dict] = {}

    def track(self, job_id: str, question: str) -> Dict:
        """Job start karo."""
        self.jobs[job_id] = {
            "job_id": job_id,
            "question": question,
            "started_at": datetime.utcnow().isoformat(),
            "current_stage": "QUEUED",
            "stages_completed": [],
            "stage_notes": {},
            "source_counts": {},
            "gemini_calls_used": 0,
            "is_complete": False,
        }
        return self.jobs[job_id]

    def update_stage(self, job_id: str, stage: str, note: str = "") -> Dict:
        """Current stage update karo."""
        if job_id not in self.jobs:
            return {"error": "Job not found"}

        job = self.jobs[job_id]
        job["current_stage"] = stage
        job["stages_completed"].append(stage)
        if note:
            job["stage_notes"][stage] = note

        return job

    def set_counts(self, job_id: str, **kwargs) -> Dict:
        """Source counts, Gemini calls, etc update karo."""
        if job_id not in self.jobs:
            return {"error": "Job not found"}

        job = self.jobs[job_id]
        for key, value in kwargs.items():
            if key == "gemini_calls":
                job["gemini_calls_used"] = value
            else:
                job["source_counts"][key] = value

        return job

    def complete(self, job_id: str) -> Dict:
        """Job complete mark karo."""
        if job_id not in self.jobs:
            return {"error": "Job not found"}

        job = self.jobs[job_id]
        job["is_complete"] = True
        job["completed_at"] = datetime.utcnow().isoformat()
        return job

    def get_progress(self, job_id: str) -> Dict:
        """Current progress fetch karo."""
        if job_id not in self.jobs:
            return {"error": "Job not found", "job_id": job_id}

        job = self.jobs[job_id]

        # Calculate progress percentage (11 main stages)
        stages = [
            "QUEUED", "PLANNING", "DOCUMENT_RETRIEVAL", "DISCOVERY",
            "PROCESSING", "EVIDENCE_EXTRACTION", "DEDUPLICATION",
            "REASONING", "VERIFICATION", "SYNTHESIS", "COMPLETE"
        ]
        completed = len([s for s in job["stages_completed"] if s in stages])
        progress_pct = min(100, int((completed / len(stages)) * 100))

        return {
            "job_id": job_id,
            "question": job["question"],
            "progress_percent": progress_pct,
            "current_stage": job["current_stage"],
            "stages_completed": job["stages_completed"],
            "stage_notes": job["stage_notes"],
            "source_counts": job["source_counts"],
            "gemini_calls_used": job["gemini_calls_used"],
            "is_complete": job["is_complete"],
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
        }


# Singleton
_progress_api = ProgressAPIWrapper()


def track_job(job_id: str, question: str) -> Dict:
    return _progress_api.track(job_id, question)


def update_stage(job_id: str, stage: str, note: str = "") -> Dict:
    return _progress_api.update_stage(job_id, stage, note)


def set_counts(job_id: str, **kwargs) -> Dict:
    return _progress_api.set_counts(job_id, **kwargs)


def complete_job(job_id: str) -> Dict:
    return _progress_api.complete(job_id)


def get_progress(job_id: str) -> Dict:
    return _progress_api.get_progress(job_id)
