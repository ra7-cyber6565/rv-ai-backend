"""Bounded public-code locations for live failures, never exception messages.

Only Git-tracked Python module names from this checkout may leave the process.
No locals, source lines, provider payloads, arbitrary class names or private
filenames are inspected or emitted. These diagnostics do not establish cause.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[1]
_KINDS = (
    (TimeoutError, "timeout"), (ConnectionError, "connection_error"),
    (PermissionError, "permission_error"), (FileNotFoundError, "file_not_found"),
    (sqlite3.Error, "database_error"), (RecursionError, "recursion_error"),
    (MemoryError, "memory_error"), (ImportError, "import_error"),
    (AttributeError, "attribute_error"), (KeyError, "key_error"),
    (IndexError, "index_error"), (TypeError, "type_error"),
    (ValueError, "value_error"), (AssertionError, "assertion_error"),
    (ArithmeticError, "arithmetic_error"), (OSError, "os_error"),
    (RuntimeError, "runtime_error"),
)
KINDS = frozenset(kind for _, kind in _KINDS) | {"other_error"}
FAILURE_CODES = frozenset({"live_research_execution_failed", "live_result_evaluation_failed"})


@lru_cache(maxsize=1)
def _public_modules():
    """Fail closed if the tracked-source inventory cannot be obtained."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT,
            capture_output=True, check=True, timeout=3,
        )
        if len(result.stdout) > 512_000:
            return {}
        modules = {}
        for raw in result.stdout.split(b"\0"):
            name = raw.decode("utf-8", errors="strict")
            if not re.fullmatch(r"(?:[A-Za-z_][A-Za-z_0-9]*/)*[A-Za-z_][A-Za-z_0-9]*\.py", name):
                continue
            path = (ROOT / name).resolve()
            if ROOT not in path.parents:
                continue
            modules[str(path)] = name[:-3].replace("/", ".")
        return modules
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return {}


def sanitize_diagnostics(value):
    """Revalidate child-process diagnostics before publishing a hosted receipt."""
    raw = value if type(value) is dict else {}
    allowed = set(_public_modules().values())
    errors = []
    rows = raw.get("errors")
    for row in rows[:3] if type(rows) is list else []:
        if type(row) is not dict:
            continue
        kind = row.get("kind")
        kind = kind if type(kind) is str and kind in KINDS else "other_error"
        frames = []
        candidates = row.get("frames")
        for frame in candidates[-8:] if type(candidates) is list else []:
            if type(frame) is not dict:
                continue
            module, line = frame.get("module"), frame.get("line")
            if type(module) is str and module in allowed and type(line) is int and 1 <= line <= 1_000_000:
                frames.append({"module": module, "line": line})
        errors.append({"kind": kind, "frames": frames})
    return {"schema": 1, "errors": errors}


def exception_diagnostics(error):
    """Locate at most three chained errors, without calling str/repr on them."""
    modules = _public_modules()
    errors, seen = [], set()
    current = error
    while isinstance(current, BaseException) and id(current) not in seen and len(errors) < 3:
        seen.add(id(current))
        kind = next((label for cls, label in _KINDS if isinstance(current, cls)), "other_error")
        frames = []
        trace = current.__traceback__
        visited = 0
        while trace is not None and visited < 128:
            visited += 1
            # Compare only against known public paths. Never export an unknown
            # filename or a dynamically supplied function name.
            module = modules.get(trace.tb_frame.f_code.co_filename)
            if module:
                frames.append({"module": module, "line": trace.tb_lineno})
            trace = trace.tb_next
        errors.append({"kind": kind, "frames": frames[-8:]})
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return sanitize_diagnostics({"errors": errors})
