import pytest

from research_engine.neural_symbolic_hybrid import NeuralProposal, audit_neural_symbolic


def _atom(name):
    return {"atom": name}


def _contract(conclusion="B"):
    return {
        "atoms": ["A", "B"],
        "premises": [
            {"implies": [_atom("A"), _atom("B")]},
            _atom("A"),
        ],
        "conclusion": _atom(conclusion),
    }


def _proposal(**overrides):
    data = dict(
        proposal_id="P1",
        model_id="model-A",
        model_revision="rev-1",
        model_output_sha256="a" * 64,
        model_confidence=0.99,
        formal_logic=_contract(),
        self_reported_proved=False,
    )
    data.update(overrides)
    return NeuralProposal(**data)


def test_symbolic_entailment_can_pass_hybrid_gate_without_claiming_truth():
    report = audit_neural_symbolic([_proposal()])
    audit = report.audits[0]
    assert audit.symbolic_status == "PROVED"
    assert audit.symbolic_entailed is True
    assert audit.symbolic_consistent is True
    assert audit.hybrid_gate_passed is True
    assert audit.model_confidence_is_truth_probability is False
    assert audit.neural_self_report_can_override_symbolic_gate is False
    assert audit.natural_language_formalization_performed is False
    assert audit.truth_proven is False
    assert report.neural_inference_executed_by_this_function is False
    assert report.symbolic_verification_executed is True
    assert report.truth_proven is False


def test_high_model_confidence_cannot_override_failed_symbolic_gate():
    report = audit_neural_symbolic([
        _proposal(
            model_confidence=1.0,
            formal_logic={
                "atoms": ["A", "B"],
                "premises": [_atom("A")],
                "conclusion": _atom("B"),
            },
            self_reported_proved=True,
        )
    ])
    audit = report.audits[0]
    assert audit.symbolic_status == "NOT_PROVED"
    assert audit.symbolic_entailed is False
    assert audit.counterexample
    assert audit.hybrid_gate_passed is False
    assert audit.self_reported_proved is True
    assert audit.neural_self_report_can_override_symbolic_gate is False


def test_inconsistent_premises_do_not_create_vacuous_hybrid_proof():
    report = audit_neural_symbolic([
        _proposal(formal_logic={
            "atoms": ["A", "B"],
            "premises": [_atom("A"), {"not": _atom("A")}],
            "conclusion": _atom("B"),
        })
    ])
    audit = report.audits[0]
    assert audit.symbolic_status == "INCONSISTENT_PREMISES"
    assert audit.symbolic_entailed is None
    assert audit.symbolic_consistent is False
    assert audit.hybrid_gate_passed is False


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf")])
def test_model_confidence_must_be_finite_unit_interval(confidence):
    with pytest.raises(ValueError, match="model_confidence"):
        audit_neural_symbolic([_proposal(model_confidence=confidence)])


def test_invalid_model_output_digest_and_duplicate_ids_fail_closed():
    with pytest.raises(ValueError, match="SHA-256"):
        audit_neural_symbolic([_proposal(model_output_sha256="not-a-digest")])
    with pytest.raises(ValueError, match="proposal_id values must be unique"):
        audit_neural_symbolic([_proposal(), _proposal()])


def test_report_hash_is_order_independent_for_proposal_set():
    first = _proposal(proposal_id="P1", model_output_sha256="a" * 64)
    second = _proposal(
        proposal_id="P2",
        model_id="model-B",
        model_revision="rev-2",
        model_output_sha256="b" * 64,
    )
    left = audit_neural_symbolic([first, second])
    right = audit_neural_symbolic([second, first])
    assert left.report_sha256 == right.report_sha256
    assert left.audits == right.audits


def test_empty_proposal_set_is_not_a_fake_hybrid_validation():
    with pytest.raises(ValueError, match="1..1000"):
        audit_neural_symbolic([])
