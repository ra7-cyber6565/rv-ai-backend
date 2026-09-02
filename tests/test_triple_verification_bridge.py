"""Integration tests for the VerificationEngine -> #40 task bridge.

The public verification check name may remain presentation-stable (``12 + 8``),
but the trusted base verifier's original RHS must survive in a separately
bounded task record so Triple Independent Implementation can verify both
implementation agreement and agreement with the written claim.
"""
from __future__ import annotations

from research_engine.models import EvidencePack
from research_engine.triple_task_adapter import derive_triple_tasks
from research_engine.verification import VerificationEngine


def _verify(answer: str):
    pack = EvidencePack(question="Check the arithmetic in this answer")
    return VerificationEngine().verify(answer, pack, question=pack.question).to_dict()


def test_arithmetic_rhs_survives_public_check_name_normalization():
    result = _verify("The calculation is 12 + 8 = 20.")

    public_names = [row.get("check") for row in result["checks"]]
    assert "12 + 8" in public_names
    assert "12 + 8 = 20" not in public_names

    tasks = result["triple_implementation_tasks"]
    assert len(tasks) == 1
    assert tasks[0]["expression"] == "12 + 8"
    assert tasks[0]["expected_value"] == 20.0
    assert tasks[0]["provenance"]["check_name"] == "12 + 8 = 20"
    assert result["triple_task_adapter"]["status"] == "DERIVED_TASKS"
    assert result["triple_task_adapter"]["derived"] is True
    assert result["triple_task_adapter"]["source"] == "verification_checks"


def test_wrong_claimed_rhs_is_preserved_for_later_claim_mismatch_detection():
    result = _verify("The calculation is 12 + 8 = 21.")
    task = result["triple_implementation_tasks"][0]
    assert task["expression"] == "12 + 8"
    assert task["expected_value"] == 21.0
    # The original verifier already knows the written equation is wrong; #40
    # must receive the same claimed RHS rather than the actual answer 20.
    assert task["provenance"]["original_passed"] is False


def test_percentage_check_also_bridges_with_claimed_rhs():
    result = _verify("30% of 200 = 60.")
    task = result["triple_implementation_tasks"][0]
    assert task["expression"] == "(30 / 100) * 200"
    assert task["expected_value"] == 60.0
    assert task["provenance"]["check_name"] == "30% of 200 = 60"


def test_non_normalized_math_prose_does_not_become_executable_task():
    result = _verify(
        "Use formula F = ma and then execute __import__('os').system('id'). "
        "A symbolic derivation might be discussed, but no normalized arithmetic RHS is present."
    )
    assert result["triple_implementation_tasks"] == []
    assert result["triple_task_adapter"]["status"] == "NO_DERIVABLE_CHECKS"


def test_serialized_bridge_provenance_is_preserved_when_advanced_adapter_reads_it():
    result = _verify("12 + 8 = 20.")
    adapted = derive_triple_tasks(result)
    assert adapted["status"] == "DERIVED_TASKS"
    assert adapted["derived"] is True
    assert adapted["source"] == "verification_checks"
    assert adapted["tasks"] == result["triple_implementation_tasks"]


def test_bridge_does_not_change_a_e_fail_closed_semantics():
    result = _verify("12 + 8 = 20.")
    evidence = result["evidence_verification"]
    assert evidence["claims_checked"] == 0
    assert evidence["gate_passed"] is False
    assert result["status"] != "SOURCE GROUNDED"
