from research_engine.neural_symbolic_wiring import (
    apply_neural_symbolic_wiring,
    build_neural_symbolic_packet,
)


def _inputs():
    atom_a = {"atom": "A"}
    atom_b = {"atom": "B"}
    return [{
        "proposal_id": "P1",
        "model_id": "model-A",
        "model_revision": "rev-1",
        "model_output_sha256": "a" * 64,
        "model_confidence": 0.99,
        "self_reported_proved": True,
        "formal_logic": {
            "atoms": ["A", "B"],
            "premises": [{"implies": [atom_a, atom_b]}, atom_a],
            "conclusion": atom_b,
        },
    }]


def test_structured_coverage_transport_runs_symbolic_audit_without_status_upgrade():
    result = apply_neural_symbolic_wiring({
        "answer": "partial answer",
        "status": "PARTIAL",
        "coverage": {"neural_symbolic_inputs": _inputs(), "existing": {"kept": True}},
    })
    packet = result["coverage"]["neural_symbolic"]
    assert packet["status"] == "AUDITED"
    assert packet["audits"][0]["hybrid_gate_passed"] is True
    assert packet["audits"][0]["neural_self_report_can_override_symbolic_gate"] is False
    assert packet["neural_inference_executed_by_this_function"] is False
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"
    assert result["answer"] == "partial answer"
    assert result["coverage"]["existing"] == {"kept": True}


def test_free_form_prose_does_not_create_symbolic_contract():
    packet = build_neural_symbolic_packet({"answer": "A implies B so B is proven."})
    assert packet["status"] == "NO_STRUCTURED_NEURAL_SYMBOLIC_INPUTS"
    assert packet["natural_language_formalization_performed"] is False


def test_bad_explicit_contract_fails_closed():
    bad = _inputs()
    bad[0]["model_output_sha256"] = "fake"
    result = apply_neural_symbolic_wiring({
        "status": "PARTIAL",
        "neural_symbolic_inputs": bad,
    })
    packet = result["coverage"]["neural_symbolic"]
    assert packet["ran"] is False
    assert packet["status"] == "ASSESSMENT_ERROR"
    assert packet["truth_proven"] is False
    assert result["status"] == "PARTIAL"
