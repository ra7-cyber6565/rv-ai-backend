"""Surface outline compatibility + evidence-first semantic coverage regressions."""
from __future__ import annotations

import research_engine  # noqa: F401  # install production hardening
from research_engine.advanced_semantic_coverage import substantive_coverage
from research_engine import final_quality_gate as FQ
from research_engine.structured_answer import coverage


QUESTION = """
### 1. Human Attention and Dopamine
Explain sustained human attention, reward prediction and digital distraction with evidence.

### 2. Jung and Consciousness
Compare Jungian individuation, consciousness research and Hermetic claims with uncertainty.

### 3. CIA Records and Secret Societies
Separate declassified-document provenance, Freemasonry history and unsupported allegations.

### 4. Game Theory and Human Agency
Compare incentives, cooperation and long-term agency with counter-evidence and limitations.
""".strip()

LABELS = [
    "1. Human Attention and Dopamine",
    "2. Jung and Consciousness",
    "3. CIA Records and Secret Societies",
    "4. Game Theory and Human Agency",
]


def _thin_answer() -> str:
    return "\n\n".join(f"**{label}**\nSimple explanation." for label in LABELS)


def _substantive_answer() -> str:
    paragraph = (
        "[EVIDENCE] This section explains the requested mechanism using the retrieved "
        "evidence, separates direct support from inference and uncertainty, identifies "
        "a competing explanation or limitation, and states what would change the "
        "conclusion. Counter-evidence is kept distinct rather than silently omitted."
    )
    return "\n\n".join(f"**{label}**\n{paragraph}" for label in LABELS)


def test_surface_coverage_contract_remains_label_delivery_only():
    audit = coverage(QUESTION, _thin_answer())
    assert audit["required"] is True
    assert audit["complete"] is True
    assert audit["items_covered"] == audit["items_total"] == 4
    assert audit["missing"] == []
    assert "outline delivery audit only" in audit["note"]


def test_semantic_coverage_separately_rejects_heading_only_delivery():
    audit = substantive_coverage(QUESTION, _thin_answer())
    assert audit["required"] is True
    assert audit["surface_complete"] is True
    assert audit["complete"] is False
    assert audit["items_covered"] == 0
    assert len(audit["substantive_missing"]) == 4
    assert audit["semantic_coverage_percent"] == 0.0


def test_semantic_coverage_accepts_substantive_evidence_aware_sections():
    audit = substantive_coverage(QUESTION, _substantive_answer())
    assert audit["complete"] is True
    assert audit["items_covered"] == audit["items_total"] == 4
    assert audit["semantic_coverage_percent"] == 100.0


def test_evidence_first_final_quality_hard_blocks_thin_structured_sections():
    state = FQ._Evaluation()
    spec = FQ.QualityContract(required_sections=(), evidence_first_required=True)
    FQ.FinalQualityGate._check_requirements(
        state,
        {"question": QUESTION, "status": "COMPLETE"},
        _thin_answer(),
        {},
        spec,
    )
    assert state.checks["structured_sections_substantive"] is False
    semantic_issues = [
        issue for issue in state.issues
        if issue.code == "REQUESTED_DELIVERABLE_MISSING"
        and "semantic_structured_coverage" in issue.details
    ]
    assert semantic_issues
    assert semantic_issues[0].hard_cap == 40


def test_legacy_non_evidence_first_gate_does_not_acquire_hidden_semantic_requirement():
    state = FQ._Evaluation()
    spec = FQ.QualityContract(required_sections=(), evidence_first_required=False)
    FQ.FinalQualityGate._check_requirements(
        state,
        {"question": QUESTION, "status": "COMPLETE"},
        _thin_answer(),
        {},
        spec,
    )
    assert "structured_sections_substantive" not in state.checks
    assert not any(
        issue.code == "REQUESTED_DELIVERABLE_MISSING"
        and "semantic_structured_coverage" in issue.details
        for issue in state.issues
    )
