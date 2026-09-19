"""Prove the specialist handoff guard is installed by the normal package path.

Existing unit tests import ``company_handoff_guard`` directly, which would install
its monkey-patch as an import side effect.  This fresh-process regression instead
imports only the public package first, so a future accidental removal of runtime
wiring cannot stay falsely green.
"""
from __future__ import annotations

import subprocess
import sys


def test_normal_package_import_installs_company_handoff_and_cross_review_guards():
    code = r'''
import research_engine
import sys

assert "research_engine.company_handoff_guard" in sys.modules
assert "research_engine.company_cross_review_wiring" in sys.modules
from research_engine import research_company
fn = research_company.chief_handoff
assert getattr(fn, "__module__", "") == "research_engine.company_cross_review_wiring"
assert getattr(fn, "__company_cross_review_wiring__", False) is True

# Round 2 wraps the compatibility guard, which still owns no compaction.
guard = getattr(fn, "__company_cross_review_original__", None)
assert getattr(guard, "__module__", "") == "research_engine.company_handoff_guard"
canonical = getattr(guard, "__canonical_chief_handoff__", None)
assert getattr(canonical, "__module__", "") == "research_engine.research_company"
print("handoff_and_cross_review_wiring_ok")
'''
    proc = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.stdout.strip().splitlines()[-1] == "handoff_and_cross_review_wiring_ok"
