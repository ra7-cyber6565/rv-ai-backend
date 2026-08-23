"""Guarded one-shot patcher for pytest 9 fixture-definition compatibility.

Temporary integration helper: it edits only the custom standalone test runner,
checks exact preconditions, and is removed before the final product commit.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "run_pytest_style_suites.py"

OLD_MARKER = '''_FIXTURE_MARKER = "_pytestfixturefunction"\n'''
NEW_MARKER = '''_FIXTURE_MARKERS = ("_pytestfixturefunction", "_fixture_function_marker")\n\n\ndef _fixture_marker(obj: Any) -> Any:\n    """Return fixture metadata for legacy pytest wrappers or pytest 9 definitions.\n\n    Pytest <=8-style wrappers expose ``_pytestfixturefunction``.  Pytest 9's\n    ``FixtureFunctionDefinition`` exposes ``_fixture_function_marker`` instead,\n    while the underlying callable is available as ``_fixture_function`` (already\n    handled by ``_unwrap_fixture`` below).  Keep both shapes: the zero-dependency\n    fake fixture probe still exercises the legacy contract.\n    """\n    for attr in _FIXTURE_MARKERS:\n        marker = getattr(obj, attr, None)\n        if marker is not None:\n            return marker\n    return None\n'''

OLD_COLLECT = '''        marker = getattr(obj, _FIXTURE_MARKER, None)\n        if marker is None or not callable(obj):\n            continue\n'''
NEW_COLLECT = '''        marker = _fixture_marker(obj)\n        if marker is None or not callable(obj):\n            continue\n'''

OLD_DOC = '''#   marker   : func._pytestfixturefunction  (.scope / .params / .autouse / .name)\n#   asli fn  : func.__pytest_wrapped__.obj  (pytest <= 8.3.x)\n#              func._fixture_function       (pytest >= 8.4)\n#              func.__wrapped__             (functools.wraps se)\n'''
NEW_DOC = '''#   marker   : func._pytestfixturefunction  (legacy wrapper shape)\n#              func._fixture_function_marker (pytest 9 FixtureFunctionDefinition)\n#              dono par .scope/.params/.autouse/.name\n#   asli fn  : func.__pytest_wrapped__.obj  (legacy wrapper)\n#              func._fixture_function       (pytest 9 FixtureFunctionDefinition)\n#              func.__wrapped__             (functools.wraps se)\n'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"STOP: {label} expected exactly once, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if "_fixture_function_marker" in text and "def _fixture_marker(" in text:
        print("Patch already present; no write needed.")
        return 0
    text = replace_once(text, OLD_MARKER, NEW_MARKER, "fixture marker constant")
    text = replace_once(text, OLD_COLLECT, NEW_COLLECT, "fixture collector lookup")
    if OLD_DOC in text:
        text = replace_once(text, OLD_DOC, NEW_DOC, "fixture shape documentation")
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print("Pytest 9 fixture-definition compatibility patch applied safely.")
    print("Supported markers:", _marker_names())
    return 0


def _marker_names() -> str:
    return "_pytestfixturefunction + _fixture_function_marker"


if __name__ == "__main__":
    raise SystemExit(main())
