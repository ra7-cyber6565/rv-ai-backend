#!/usr/bin/env python3
"""Reconcile historical PR81 handoff expectations with the current safer guard.

Historical PR81 carried an older handoff implementation/tests that treated
omitting duplicate claims as successful "structured compaction".  The current
stack deliberately supersedes that behavior with
LOSSLESS_SHARED_FIELDS_THEN_HARD_FAIL: claims/falsification/test reasoning are
never omitted merely to manufacture a complete specialist handoff.

The merge workflow already resolves company_handoff_guard.py to the current
implementation.  This companion reconciliation removes the obsolete PR81-only
compaction test module and restores the current fail-closed regression in the
shared research-company test file.  It changes tests only; product code stays on
the current lossless guard while PR81 Round-2/trading runtime changes remain.
"""
from __future__ import annotations

import re
from pathlib import Path


def restore_current_overflow_test() -> None:
    path = Path("tests/test_research_company.py")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"def test_overlong_handoff_keeps_every_role_and_uses_structured_compaction\(\):.*?"
        r"(?=\n\ndef test_timeout_keeps_usage_unknown_and_completion_gate_open)",
        re.S,
    )
    replacement = '''def test_overlong_handoff_keeps_every_role_and_blocks_complete_review():
    verbose = report(claims=[{"text": "Measured description " * 90, "source_ids": ["S1"],
                              "kind": "SOURCE_REPORTED"} for _ in range(10)])
    result = company.run_company("Q", packet(), get_depth_config("COMPANY"), worker=lambda p: envelope(verbose))
    handoff = company.chief_handoff(result)
    assert len(result["handoff_truncated_roles"]) == 4
    assert result["handoff_compacted_roles"] == []
    assert all(role in handoff for role, _ in company.ROLES[:4])
    passes = {"planned_passes": [], "done_passes": [], "notes": [], "api_accounting": {}}
    company.attach_company_passes(passes, result)
    assert "specialist_handoff" in passes["planned_passes"]
    assert "specialist_handoff" not in passes["done_passes"]
'''
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"expected one historical overflow test, found {count}")
    path.write_text(updated, encoding="utf-8")


def remove_superseded_compaction_tests() -> None:
    path = Path("tests/test_company_handoff_compaction.py")
    if path.exists():
        path.unlink()


def verify_current_guard() -> None:
    text = Path("research_engine/company_handoff_guard.py").read_text(encoding="utf-8")
    required = (
        '"LOSSLESS_SHARED_FIELDS_THEN_HARD_FAIL"',
        "claim_payload_exceeds_safe_projection",
        "full_report_exceeds_handoff_budget",
        "__bounded_structured_handoff_guard__",
    )
    missing = [value for value in required if value not in text]
    if missing:
        raise SystemExit(f"current lossless handoff guard missing invariants: {missing}")


def main() -> int:
    verify_current_guard()
    restore_current_overflow_test()
    remove_superseded_compaction_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
