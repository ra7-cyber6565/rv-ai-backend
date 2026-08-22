"""FastAPI guard for project-scoped public endpoints."""
from __future__ import annotations

from fastapi import HTTPException

from utils.project_access import project_access


def require_project_access(project_id: object, token: object) -> None:
    """Refuse missing/wrong project capabilities without exposing id existence."""
    if not project_access.verify(project_id, token):
        # Same response for malformed id, missing token and wrong token: do not
        # turn this into a project namespace enumeration oracle.
        raise HTTPException(status_code=404, detail="Project session nahi mila")


__all__ = ["require_project_access"]
