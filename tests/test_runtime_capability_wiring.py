import pytest

from research_engine.models import ResearchResult
from research_engine.runtime_capability_wiring import (
    apply_runtime_capability_wiring,
    build_runtime_capability_snapshot,
    build_runtime_formal_logic_packet,
    evaluate_formal_logic_contract,
    install,
)


def _atom(name):
    return {"atom": name}


def _implies(left, right):
    return {"implies": [left, right]}


def _contract():
    return {
        "atoms": ["A", "B", "C"],
        "premises": [
            _implies(_atom("A"), _atom("B")),
            _implies(_atom("B"), _atom("C")),
            _atom("A"),
        ],
        "conclusion": _atom("C"),
    }


def test_explicit_structured_logic_contract_is_proved_symbolically():
    result = evaluate_formal_logic_contract(_contract())
    assert result["status"] == "PROVED"
    assert result["entailed"] is True
    assert result["consistent"] is True
    assert result["method"] == "symbolic-sat"
    assert result["natural_language_formalization_performed"] is False
    assert result["truth_proven"] is False


def test_nonentailed_contract_returns_counterexample_not_fake_proof():
    contract = {
        "atoms": ["A", "B"],
        "premises": [_atom("A")],
        "conclusion": _atom("B"),
    }
    result = evaluate_formal_logic_contract(contract)
    assert result["status"] == "NOT_PROVED"
    assert result["entailed"] is False
    assert result["counterexample"]
    assert result["truth_proven"] is False


def test_inconsistent_premises_do_not_create_vacuous_proof():
    contract = {
        "atoms": ["A", "B"],
        "premises": [_atom("A"), {"not": _atom("A")}],
        "conclusion": _atom("B"),
    }
    result = evaluate_formal_logic_contract(contract)
    assert result["status"] == "INCONSISTENT_PREMISES"
    assert result["entailed"] is None
    assert result["consistent"] is False


def test_prose_is_never_silently_converted_into_formal_logic():
    packet = build_runtime_formal_logic_packet([
        {"id": "H1", "statement": "If A causes B and B causes C, maybe A causes C."}
    ])
    assert packet["status"] == "NO_EXPLICIT_CONTRACTS"
    assert packet["explicit_contracts"] == 0
    assert packet["results"] == []
    assert packet["natural_language_formalization_performed"] is False


def test_invalid_contract_is_reported_without_crashing_whole_result():
    packet = build_runtime_formal_logic_packet([
        {
            "id": "H1",
            "formal_logic": {
                "atoms": ["A"],
                "premises": [],
                "conclusion": _atom("UNKNOWN"),
            },
        }
    ])
    assert packet["status"] == "PARTIAL_INVALID_CONTRACTS"
    assert packet["invalid_contracts"] == 1
    assert packet["results"][0]["status"] == "INVALID_CONTRACT"
    assert packet["results"][0]["truth_proven"] is False


def test_formula_depth_budget_fails_closed():
    node = _atom("A")
    for _ in range(20):
        node = {"not": node}
    with pytest.raises(ValueError, match="depth budget"):
        evaluate_formal_logic_contract({
            "atoms": ["A"],
            "premises": [],
            "conclusion": node,
        })


def test_runtime_capability_snapshot_uses_catalog_and_never_claims_execution():
    result = {
        "verification": {"claim_checks": {}},
        "coverage": {
            "experiment_intelligence": {"ran": True},
            "knowledge_watch": {"ran": True},
            "source_integrity": {"ran": True},
        },
        "lab": {"ran": True},
    }
    packet = build_runtime_capability_snapshot(result)
    names = {row["name"] for row in packet["registered_components"]}
    assert {
        "research_pipeline",
        "formal_logic",
        "claim_verification",
        "bounded_lab",
        "experiment_intelligence",
        "knowledge_watch",
        "source_integrity",
    }.issubset(names)
    assert packet["discovery_only"] is True
    assert packet["execution_authority_granted"] is False
    assert packet["permission_enforcement_proven_by_snapshot"] is False
    assert packet["execution_proven_by_snapshot"] is False
    assert packet["truth_proven"] is False


def test_unavailable_components_are_not_invented():
    packet = build_runtime_capability_snapshot({"coverage": {}})
    names = {row["name"] for row in packet["registered_components"]}
    assert names == {"research_pipeline", "formal_logic"}
    assert "hardware_control" not in packet["capabilities"]
    assert "live_trading" not in packet["capabilities"]


def test_apply_wiring_only_adds_coverage_and_preserves_status_answer():
    original = {
        "question": "q",
        "answer": "answer",
        "status": "PARTIAL",
        "coverage": {"existing": {"kept": True}},
        "hypotheses": [{"id": "H1", "formal_logic": _contract()}],
        "verification": {},
    }
    result = apply_runtime_capability_wiring(original)
    assert result["answer"] == "answer"
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}
    assert result["coverage"]["formal_logic"]["results"][0]["status"] == "PROVED"
    assert result["coverage"]["capability_discovery"]["discovery_only"] is True


def test_real_research_result_serialization_contains_both_runtime_packets():
    install()
    result = ResearchResult(
        question="short question",
        answer="bounded answer",
        status="PARTIAL",
        hypotheses=[{"id": "H1", "formal_logic": _contract()}],
        verification={"claim_checks": {}},
        coverage={"knowledge_watch": {"ran": True}},
    ).to_dict()
    assert result["coverage"]["formal_logic"]["ran"] is True
    assert result["coverage"]["formal_logic"]["results"][0]["status"] == "PROVED"
    assert result["coverage"]["capability_discovery"]["ran"] is True
    assert result["coverage"]["capability_discovery"]["discovery_only"] is True
    assert result["status"] == "PARTIAL"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    after_first = result_coverage_gate.enforce
    install()
    after_second = result_coverage_gate.enforce
    assert before is after_first
    assert after_first is after_second
