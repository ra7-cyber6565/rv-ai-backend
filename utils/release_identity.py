"""Small, sanitized helpers for tying release evidence to one Git revision.

Release receipts are useful only when they identify the code that produced
them.  These helpers deliberately expose only a validated 40-character Git
SHA plus coarse availability/cleanliness booleans; command output, paths and
operating-system errors never cross the public/receipt boundary.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Mapping


_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_DEPLOYMENT_REVISION_KEYS = (
    "RAILWAY_GIT_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "SOURCE_VERSION",
    "GIT_COMMIT_SHA",
)


def normalize_git_revision(value: object) -> str:
    """Return a lowercase full Git SHA, or an empty string when invalid."""
    candidate = str(value or "").strip()
    return candidate.lower() if _GIT_SHA_RE.fullmatch(candidate) else ""


def deployment_revision(env: Mapping[str, str] | None = None) -> str:
    """Read a validated build revision from supported hosting variables.

    Railway supplies ``RAILWAY_GIT_COMMIT_SHA`` for GitHub-triggered builds.
    The additional names keep the public contract portable without trusting an
    arbitrary user-facing value: every candidate still has to be a full SHA.
    """
    source = os.environ if env is None else env
    for key in _DEPLOYMENT_REVISION_KEYS:
        revision = normalize_git_revision(source.get(key))
        if revision:
            return revision
    return ""


def repository_identity(root: Path) -> dict[str, object]:
    """Return sanitized revision/cleanliness state for a local Git checkout."""
    try:
        revision_run = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        revision = normalize_git_revision(revision_run.stdout)
        if revision_run.returncode != 0 or not revision:
            return {"available": False, "revision": "", "clean": False}
        status_run = subprocess.run(
            [
                "git", "-C", str(root), "status", "--porcelain=v1",
                "--untracked-files=normal",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if status_run.returncode != 0:
            return {"available": False, "revision": revision, "clean": False}
        return {
            "available": True,
            "revision": revision,
            "clean": not bool(status_run.stdout.strip()),
        }
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "revision": "", "clean": False}

