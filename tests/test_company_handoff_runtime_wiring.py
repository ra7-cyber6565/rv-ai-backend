"""Prove the specialist handoff guard is installed by the normal package path.

Existing unit tests import ``company_handoff_guard`` directly, which would install
its monkey-patch as an import side effect.  This fresh-process regression instead
imports only the public package first, so a future accidental removal of runtime
wiring cannot stay falsely green.
"""
from __future__ import annotations

import subprocess
import sys


def test_normal_package_import_installs_company_handoff_guard():
    code = r'''
import research_engine
import sys

assert "research_engine.company_handoff_guard" in sys.modules
from research_engine import research_company
fn = research_company.chief_handoff
original = getattr(fn, "__company_cross_review_original__", None)
print(getattr(fn, "__module__", ""))
print(getattr(original, "__bounded_structured_handoff_guard__", False))
'''
    proc = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = proc.stdout.strip().splitlines()
    assert lines[-2] == "research_engine.company_cross_review_wiring"
    assert lines[-1] == "True"
