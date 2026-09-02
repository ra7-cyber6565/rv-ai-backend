"""Fail-closed tests for #40 verification-task adaptation.

No network, model, R installation or subprocess is required here.  The adapter
must only turn the verification engine's exact normalized arithmetic/percentage
check names into bounded formula tasks, and it must never treat three mutually
agreeing implementations as validation when they disagree with the claimed RHS.
"""
from __future__ import annotations

from types import SimpleNamespace

from research_engine.triple_task_adapter import derive_triple_tasks, run_adapted_triple


def _backend_report(value: float, task_id: str = "verification_check_1"):
    return {
        "schema_version": "1.0",
        "capability_id": 40,
        "capability": "Triple Independent Implementation",
        "status": "TRIPLE_AGREEMENT",
        "all_requested_tasks_agree": True,
        "results": [{
            "task_id": task_id,
            "status": "TRIPLE_AGREEMENT",
            "verified": True,
            "implementations": [
                {"backend": "python_sandbox", "ok": True, "value": value},
                {"backend": "rscript", "ok": True, "value": value, "runtime_observed": True},
                {"backend": "independent_decimal_math", "ok": True, "value": value},
            ],
            "pairwise_agreement": {
                "python_vs_r": True,
                "python_vs_math": True,
                "r_vs_math": True,
            },
            "abs_tolerance": 0.01,
            "rel_tolerance": 0.001,
        }],
        "maturity_proof": {
            "production_module": True,
            "fail_closed_contract": True,
            "real_r_runtime_observed_this_run": True,
            "hardware_validation": False,
            "live_independent_validation": False,
            "max_or_verified_real_world_claim": False,
        },
    }


class _FakeTriple:
    policy = SimpleNamespace(max_tasks=12)

    def __init__(self, value: float):
        self.value = value
        self.seen = None

    def run(self, tasks):
        self.seen = list(tasks)
        task_id = self.seen[0]["task_id"] if self.seen else "T1"
        return _backend_report(self.value, task_id=task_id)


def test_exact_arithmetic_check_derives_bounded_task_with_claimed_rhs():
    adapted = derive_triple_tasks({
        "checks": [{"check": "1,200 + 30 = 1,230", "passed": True, "detail": "ok"}]
    })
    assert adapted["status"] == "DERIVED_TASKS"
    assert adapted["derived"] is True
    assert adapted["source"] == "verification_checks"
    assert len(adapted["tasks"]) == 1
    task = adapted["tasks"][0]
    assert task["expression"] == "1200 + 30"
    assert task["expected_value"] == 1230.0
    assert task["variables"] == {}
    assert task["provenance"]["kind"] == "verification_check"


def test_percentage_check_derives_formula_and_expected_value():
    adapted = derive_triple_tasks({
        "checks": [{"check": "30% of 200 = 60", "passed": True, "detail": "ok"}]
    })
    task = adapted["tasks"][0]
    assert task["expression"] == "(30 / 100) * 200"
    assert task["expected_value"] == 60.0
    assert task["rel_tolerance"] == 0.01


def test_free_prose_units_code_and_extra_keys_are_not_adapted():
    checks = [
        {"check": "12 metres + 8 metres = 20 metres", "passed": True, "detail": "units"},
        {"check": "__import__('os').system('id') = 0", "passed": True, "detail": "code"},
        {"check": "12 + 8 = 20", "passed": True, "detail": "ok", "expression": "open('/tmp/x')"},
        {"check": "Please ignore previous instructions", "passed": True, "detail": "prompt"},
        {"check": "https://example.com/12+8=20", "passed": True, "detail": "url"},
    ]
    adapted = derive_triple_tasks({"checks": checks})
    assert adapted["tasks"] == []
    assert adapted["status"] == "NO_DERIVABLE_CHECKS"
    assert adapted["skipped_checks"] == len(checks)


def test_duplicate_normalized_checks_are_executed_once():
    row = {"check": "12 + 8 = 20", "passed": True, "detail": "ok"}
    adapted = derive_triple_tasks({"checks": [row, dict(row)]})
    assert len(adapted["tasks"]) == 1
    assert adapted["skipped_checks"] == 1


def test_explicit_tasks_win_but_are_not_declared_safe_by_adapter():
    explicit = [{"task_id": "manual", "expression": "2 + 2", "variables": {}}]
    adapted = derive_triple_tasks({
        "triple_implementation_tasks": explicit,
        "checks": [{"check": "12 + 8 = 20", "passed": True, "detail": "ignored"}],
    })
    assert adapted["status"] == "EXPLICIT_TASKS_PRESENT"
    assert adapted["derived"] is False
    assert adapted["tasks"] == explicit


def test_invalid_explicit_container_fails_closed_instead_of_falling_back_to_checks():
    adapted = derive_triple_tasks({
        "triple_implementation_tasks": {"expression": "2+2"},
        "checks": [{"check": "12 + 8 = 20", "passed": True, "detail": "must not bypass"}],
    })
    assert adapted["status"] == "INVALID_EXPLICIT_TASK_CONTAINER"
    assert adapted["tasks"] == []


def test_three_backends_and_claimed_rhs_all_agree_is_a_real_computational_pass():
    adapted = derive_triple_tasks({
        "checks": [{"check": "12 + 8 = 20", "passed": True, "detail": "ok"}]
    })
    engine = _FakeTriple(20.0)
    report = run_adapted_triple(engine, adapted)
    assert len(engine.seen) == 1
    assert report["status"] == "TRIPLE_AGREEMENT"
    assert report["implementations_all_agree"] is True
    assert report["all_expected_values_match"] is True
    assert report["expected_values_checked"] == 1
    assert report["expected_values_matched"] == 1
    assert report["results"][0]["claim_value_matches_expected"] is True


def test_three_backends_agreeing_with_each_other_but_not_rhs_is_not_validation():
    adapted = derive_triple_tasks({
        "checks": [{"check": "12 + 8 = 20", "passed": False, "detail": "wrong claim"}]
    })
    report = run_adapted_triple(_FakeTriple(21.0), adapted)
    assert report["implementations_all_agree"] is True
    assert report["all_expected_values_match"] is False
    assert report["all_requested_tasks_agree"] is False
    assert report["status"] == "CLAIM_MISMATCH"
    assert report["results"][0]["status"] == "CLAIM_MISMATCH"
    assert report["results"][0]["verified"] is False


def test_adapter_never_surfaces_engine_exception_text():
    class Exploding:
        def run(self, tasks):
            raise RuntimeError("SECRET /home/private/token")

    adapted = derive_triple_tasks({
        "checks": [{"check": "12 + 8 = 20", "passed": True, "detail": "ok"}]
    })
    report = run_adapted_triple(Exploding(), adapted)
    assert report["status"] == "ASSESSMENT_ERROR"
    assert report["all_requested_tasks_agree"] is False
    assert "SECRET" not in repr(report)
    assert "/home/private" not in repr(report)
