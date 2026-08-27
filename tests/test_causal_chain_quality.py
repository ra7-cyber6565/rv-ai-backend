"""Regression: explicit causal/second-order chains require per-arrow epistemic honesty."""
from __future__ import annotations

from research_engine.causal_chain_quality import (
    apply_causal_chain_gate,
    audit_causal_chain,
    extract_requested_chain,
    requires_causal_chain_audit,
)


QUESTION = """Build a causal / second-order model and assess every link separately.
Biology → environment → culture → language → attention → beliefs
Which links have strong evidence and which are uncertain?
"""


def _good_answer() -> str:
    return """
### Causal / second-order chain
- [EVIDENCE] Biology → environment [S1]: biological constraints interact with environmental exposure.
- [INFERENCE] environment → culture: population-level environments can shape recurring social practices, but this arrow is an inference here.
- [SOURCE-REPORTED] culture → language [S2]: the cited historical/linguistic source reports this relationship.
- [UNKNOWN] language → attention: the retrieved evidence does not establish the direction or size of this causal link.
- [SPECULATION] attention → beliefs: a directional causal effect is plausible but not established by this run.
"""


def test_extracts_longest_requested_arrow_chain_in_order():
    assert extract_requested_chain(QUESTION) == [
        "Biology", "environment", "culture", "language", "attention", "beliefs"
    ]
    assert requires_causal_chain_audit(QUESTION) is True


def test_fully_labelled_chain_passes_without_forcing_unknowns_to_fake_citations():
    audit = audit_causal_chain(QUESTION, _good_answer())
    assert audit["required"] is True
    assert audit["complete"] is True
    assert audit["edges_total"] == 5
    assert audit["edges_complete"] == 5
    statuses = [row["epistemic_status"] for row in audit["edges"]]
    assert statuses == ["EVIDENCE", "INFERENCE", "SOURCE-REPORTED", "UNKNOWN", "SPECULATION"]
    assert audit["missing_edges"] == []


def test_evidence_label_without_same_edge_citation_fails_closed():
    answer = _good_answer().replace(
        "[EVIDENCE] Biology → environment [S1]",
        "[EVIDENCE] Biology → environment",
    )
    audit = audit_causal_chain(QUESTION, answer)
    edge = audit["edges"][0]
    assert edge["epistemic_status"] == "EVIDENCE"
    assert edge["citation_required"] is True
    assert edge["citation_present"] is False
    assert edge["complete"] is False
    assert "evidence_label_without_source_citation" in edge["reasons"]
    assert audit["complete"] is False


def test_unlabelled_link_cannot_borrow_status_from_neighbouring_edge():
    answer = _good_answer().replace(
        "- [UNKNOWN] language → attention: the retrieved evidence does not establish the direction or size of this causal link.",
        "- language → attention: this sentence deliberately has no epistemic label.",
    )
    audit = audit_causal_chain(QUESTION, answer)
    edge = next(row for row in audit["edges"] if row["from"].casefold() == "language")
    assert edge["represented"] is True
    assert edge["epistemic_status"] is None
    assert "epistemic_status_missing" in edge["reasons"]
    assert audit["complete"] is False


def test_missing_link_is_reported_as_its_own_causal_gap_not_a_math_failure():
    answer = _good_answer().replace(
        "- [INFERENCE] environment → culture: population-level environments can shape recurring social practices, but this arrow is an inference here.\n",
        "",
    )
    result = apply_causal_chain_gate({
        "question": QUESTION,
        "answer": answer,
        "status": "COMPLETE",
        "warnings": [],
        "missing_sections": [],
        "quality_context": {
            "calculations": [{"formula": "", "unit_check": False}],
        },
    })
    assert result["status"] == "PARTIAL"
    assert result["coverage"]["causal_chain"]["complete"] is False
    assert any("environment → culture" in item for item in result["coverage"]["causal_chain"]["missing_edges"])
    assert any("Causal / second-order chain" in item for item in result["missing_sections"])
    joined = " ".join(result["warnings"] + [result.get("status_reason", "")])
    assert "CAUSAL CHAIN GAP" in joined
    assert "Calculation 1" not in joined


def test_gate_is_monotonic_and_does_not_upgrade_existing_partial_status():
    incomplete = _good_answer().replace("[SPECULATION] attention → beliefs", "attention → beliefs")
    result = apply_causal_chain_gate({
        "question": QUESTION,
        "answer": incomplete,
        "status": "PARTIAL",
        "status_reason": "Earlier evidence gap remains.",
    })
    assert result["status"] == "PARTIAL"
    assert result["status_reason"].startswith("Earlier evidence gap remains.")
    assert result["coverage"]["causal_chain"]["complete"] is False


def test_normal_non_chain_question_is_unchanged_except_machine_audit():
    question = "What is the strongest evidence about sustained human attention?"
    result = apply_causal_chain_gate({
        "question": question,
        "answer": "[EVIDENCE] A bounded answer [S1].",
        "status": "COMPLETE",
    })
    assert result["status"] == "COMPLETE"
    assert result["coverage"]["causal_chain"]["required"] is False
    assert result["coverage"]["causal_chain"]["complete"] is True


def test_arrow_pipeline_does_not_become_causal_contract_without_causal_cue():
    incidental = "Architecture: input → tokenization → hidden state → output. Explain each stage."
    assert requires_causal_chain_audit(incidental) is False
    audit = audit_causal_chain(incidental, "input → tokenization → hidden state → output")
    assert audit["required"] is False


def test_causal_prefix_and_trailing_instruction_are_not_parsed_as_node_names():
    causal = "Causal chain: exposure → habit → outcome: explain uncertainty for each link."
    assert extract_requested_chain(causal) == ["exposure", "habit", "outcome"]
    assert requires_causal_chain_audit(causal) is True
    answer = """
- [EVIDENCE] exposure → habit [S1]: measured association with causal support.
- [UNKNOWN] habit → outcome: direction is unresolved in this run.
"""
    audit = audit_causal_chain(causal, answer)
    assert audit["complete"] is True
    assert audit["edges_complete"] == 2
