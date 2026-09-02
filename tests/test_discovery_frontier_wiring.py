from research_engine.discovery_frontier_wiring import (
    apply_discovery_frontier_wiring,
    build_discovery_frontier_packet,
    install,
)
from research_engine.models import ResearchResult


def _result():
    return {
        "question": "Can a feedback mechanism transfer across domains?",
        "answer": "Current answer remains partial.",
        "status": "PARTIAL",
        "coverage": {
            "advanced_discovery": {
                "recursive_research": {"gaps": ["Independent replication is missing."]},
                "domain_validation": {"domain": "control"},
            },
            "existing": {"kept": True},
        },
        "contradictions": [
            {
                "valid": True,
                "normalized_proposition": "Two independent sources report opposing response directions.",
                "source_ids": ["S1", "S2"],
            }
        ],
        "unexpected_observations": [
            {
                "signal_id": "U1",
                "statement": "The response reverses sign only after the perturbation threshold.",
                "domain": "control",
                "source_refs": ["S1"],
                "provenance_ref": "lab:run-7:window-3",
                "provenance_complete": True,
                "unresolved": True,
                "relevance": 0.9,
                "surprise": 0.9,
                "evidence_strength": 0.7,
            }
        ],
        "hypotheses": [
            {
                "id": "H1",
                "statement": "Feedback may stabilize the observed response.",
                "mechanism": "negative feedback stabilizes the response after perturbation",
                "mechanism_domain": "biology",
                "invariants": ["negative feedback", "bounded response"],
                "assumptions": ["calibrated measurement"],
                "supporting_evidence": "Supported by [S1].",
            },
            {
                "id": "H2",
                "statement": "Energy balance may constrain the response.",
                "mechanism": "energy balance constrains the response under bounded input",
                "mechanism_domain": "engineering",
                "invariants": ["energy balance", "bounded response"],
                "assumptions": ["closed accounting boundary"],
                "supporting_evidence": "Supported by [S2].",
            },
        ],
        "transfer_targets": [
            {
                "target_id": "T1",
                "domain": "control",
                "context": "A controller subject to an external perturbation",
                "preserved_invariants": ["negative feedback", "bounded response"],
                "disanalogies": ["actuator latency differs from biological response delay"],
                "evidence_refs": ["S3"],
            }
        ],
    }


def test_runtime_packet_generates_only_auditable_candidates():
    packet = build_discovery_frontier_packet(_result())
    assert packet["ran"] is True
    assert packet["status"] == "AUDITED"
    assert len(packet["questions"]) >= 2
    assert packet["serendipity"][0]["state"] == "CANDIDATE_SERENDIPITY"
    assert packet["cross_domain_transfers"]
    assert packet["creative_candidates"]
    assert packet["free_form_mechanism_inference_performed"] is False
    assert packet["free_form_unexpected_observation_inference_performed"] is False
    assert packet["truth_proven"] is False
    assert packet["global_novelty_proven"] is False


def test_missing_explicit_mechanism_fields_never_get_invented():
    data = _result()
    data["hypotheses"] = [
        {"id": "H1", "statement": "Prose mentions feedback but has no structured mechanism fields."}
    ]
    data["transfer_targets"] = []
    packet = build_discovery_frontier_packet(data)
    assert packet["input_mechanism_count"] == 0
    assert packet["cross_domain_transfers"] == []
    assert packet["creative_candidates"] == []


def test_untrusted_unexpected_observation_stays_review_required():
    data = _result()
    data["unexpected_observations"][0]["provenance_complete"] = False
    data["unexpected_observations"][0]["provenance_ref"] = ""
    packet = build_discovery_frontier_packet(data)
    assert packet["serendipity"][0]["state"] == "REVIEW_REQUIRED"
    assert packet["serendipity"][0]["truth_proven"] is False


def test_invalid_explicit_inputs_are_rejected_not_promoted():
    data = _result()
    data["unexpected_observations"].append({
        "signal_id": "bad",
        "statement": "Bad numeric evidence signal",
        "source_refs": ["S9"],
        "provenance_ref": "x",
        "provenance_complete": True,
        "relevance": float("nan"),
        "surprise": 1.0,
        "evidence_strength": 1.0,
    })
    data["transfer_targets"].append({
        "target_id": "bad-target",
        "domain": "control",
        "context": "Missing disanalogies should fail closed",
        "preserved_invariants": ["negative feedback"],
        "disanalogies": [],
        "evidence_refs": ["S4"],
    })
    packet = build_discovery_frontier_packet(data)
    assert packet["rejected_unexpected_observations"] == 1
    assert packet["rejected_transfer_targets"] == 1
    assert packet["truth_proven"] is False


def test_apply_wiring_preserves_answer_status_and_existing_coverage():
    data = _result()
    result = apply_discovery_frontier_wiring(data)
    assert result["answer"] == data["answer"]
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["existing"] == {"kept": True}
    assert result["coverage"]["discovery_frontier"]["result_status_upgraded"] is False


def test_no_structured_inputs_is_explicit_not_fake_discovery():
    packet = build_discovery_frontier_packet({"coverage": {}, "hypotheses": []})
    assert packet["status"] == "NO_STRUCTURED_DISCOVERY_INPUTS"
    assert packet["questions"] == []
    assert packet["serendipity"] == []
    assert packet["cross_domain_transfers"] == []
    assert packet["creative_candidates"] == []


def test_real_research_result_serialization_receives_discovery_packet():
    install()
    result = ResearchResult(
        question="short question",
        answer="partial answer",
        status="PARTIAL",
        coverage={
            "advanced_discovery": {
                "recursive_research": {"gaps": ["Independent replication is missing."]},
                "domain_validation": {"domain": "physics"},
            }
        },
    ).to_dict()
    packet = result["coverage"]["discovery_frontier"]
    assert packet["ran"] is True
    assert packet["questions"]
    assert packet["candidate_discovery_label"] == "Candidate discovery — not established fact."
    assert result["status"] == "PARTIAL"


def test_install_is_idempotent():
    from research_engine import result_coverage_gate

    before = result_coverage_gate.enforce
    install()
    once = result_coverage_gate.enforce
    install()
    twice = result_coverage_gate.enforce
    assert before is once
    assert once is twice
