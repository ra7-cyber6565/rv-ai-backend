"""Guarded one-shot patcher for P0-C live evidence gate hardening.

Edits only scripts/run_live_zero_cost_gate.py and refuses to run if the expected
P0-B-era source shape changed. Delete this helper before the final PR.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "run_live_zero_cost_gate.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"STOP: {label} guard expected exactly 1 match, got {count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if "P0-C — live release must prove non-vacuous" in text:
        print("P0-C already applied; no changes made.")
        return 0

    old = '''    strong_checked = int(claim_checks.get("strong_claims_checked") or 0)\n    strong_passed = int(claim_checks.get("strong_claims_passed") or 0)\n    claim_gate_value = claim_checks.get("gate_passed")\n    claim_gate_detail = (\n        f"{claim_gate_value} ({strong_passed}/{strong_checked} strong-label "\n        "claim(s) passed A-E)"\n    )\n'''
    new = '''    strong_checked = int(claim_checks.get("strong_claims_checked") or 0)\n    strong_passed = int(claim_checks.get("strong_claims_passed") or 0)\n    claim_gate_value = claim_checks.get("gate_passed")\n    claim_gate_detail = (\n        f"{claim_gate_value} ({strong_passed}/{strong_checked} strong-label "\n        "claim(s) passed A-E)"\n    )\n\n    # P0-C — live release must prove non-vacuous P0-A achievement AND P0-B\n    # evidence-before-generation adherence. `gate_passed=True` alone is a safety\n    # property and can be vacuously true at 0/0, so it is never enough here.\n    critical_total = int(claim_checks.get("critical_claims") or 0)\n    critical_same_source = int(\n        claim_checks.get("critical_claims_same_source_ae_passed") or 0\n    )\n    claim_achievement_value = claim_checks.get("claim_verification_achievement")\n    claim_achievement_ok = (\n        critical_total > 0\n        and critical_same_source > 0\n        and claim_achievement_value is True\n    )\n    claim_achievement_detail = (\n        f"{claim_achievement_value} "\n        f"({critical_same_source}/{critical_total} critical claim(s) passed same-source A-E)"\n    )\n\n    evidence_first = verification.get("evidence_first_audit") or {}\n    evidence_first_required = evidence_first.get("evidence_first_required") is True\n    preselected_count = int(\n        evidence_first.get("preselected_evidence_spans_count") or 0\n    )\n    preselected_strong = int(\n        evidence_first.get("preselected_strong_eligible_spans") or 0\n    )\n    preselected_matched = int(\n        evidence_first.get("critical_claims_preselected_span_matched") or 0\n    )\n    preselected_unmatched = int(\n        evidence_first.get("critical_claims_preselected_span_unmatched") or 0\n    )\n    preselection_complete = evidence_first.get("critical_claim_preselection_complete")\n    evidence_first_achievement = evidence_first.get("evidence_first_achievement")\n    evidence_first_ok = (\n        evidence_first_required\n        and preselected_count > 0\n        and preselected_strong > 0\n        and preselection_complete is True\n        and preselected_unmatched == 0\n        and preselected_matched > 0\n        and evidence_first_achievement is True\n    )\n    evidence_first_detail = (\n        f"required={evidence_first_required}, achievement={evidence_first_achievement}, "\n        f"matched={preselected_matched}, unmatched={preselected_unmatched}, "\n        f"eligible={preselected_strong}/{preselected_count}"\n    )\n'''
    text = replace_once(text, old, new, "claim-state insertion")

    old = '''        ("claim_gate", claim_gate_value is True, claim_gate_detail),\n        ("three_hypotheses", len(hypotheses) >= 3,\n'''
    new = '''        ("claim_gate", claim_gate_value is True, claim_gate_detail),\n        ("claim_verification_achievement", claim_achievement_ok,\n         claim_achievement_detail),\n        ("evidence_first_achievement", evidence_first_ok, evidence_first_detail),\n        ("three_hypotheses", len(hypotheses) >= 3,\n'''
    text = replace_once(text, old, new, "live checks insertion")

    old = '''            "citations": len(result.get("citations") or []),\n            "hypotheses": len(hypotheses),\n            "discovery_status": str(discovery.get("status") or ""),\n'''
    new = '''            "citations": len(result.get("citations") or []),\n            "hypotheses": len(hypotheses),\n            # P0-C stores only structural evidence counters/booleans. No source\n            # passage, URL, prompt or claim text is copied into the receipt.\n            "critical_claims": critical_total,\n            "critical_claims_same_source_ae_passed": critical_same_source,\n            "claim_verification_achievement": bool(claim_achievement_ok),\n            "evidence_first_required": bool(evidence_first_required),\n            "preselected_evidence_spans_count": preselected_count,\n            "preselected_strong_eligible_spans": preselected_strong,\n            "critical_claims_preselected_span_matched": preselected_matched,\n            "critical_claims_preselected_span_unmatched": preselected_unmatched,\n            "critical_claim_preselection_complete": preselection_complete is True,\n            "evidence_first_achievement": bool(evidence_first_ok),\n            "discovery_status": str(discovery.get("status") or ""),\n'''
    text = replace_once(text, old, new, "receipt summary insertion")

    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print("P0-C live evidence gate patch applied safely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
