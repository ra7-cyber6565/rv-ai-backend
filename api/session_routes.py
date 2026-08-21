"""Anonymous project/session capability API.

Creating a session costs no model/API quota. It returns a random project namespace
plus an opaque bearer capability. Clients must send that capability in
``X-Project-Token`` when an endpoint reads/writes project-scoped data.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from utils.project_access import project_access


router = APIRouter()


@router.post("/session", status_code=201)
def create_session():
    """Create an isolated anonymous project namespace for this client."""
    if not project_access.status().get("project_capability_tokens_ready"):
        raise HTTPException(
            status_code=503,
            detail="Private project access layer ready nahi hai; session create nahi hua.",
        )
    session = project_access.create()
    return {
        **session,
        "note": (
            "project_access_token ko X-Project-Token header mein bhejein. "
            "Token ko URL, analytics, logs ya public source code mein mat daalein."
        ),
    }
