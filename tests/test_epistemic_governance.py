import math

import pytest

from research_engine.epistemic_governance import (
    AlternativeExplanation,
    EvidenceItem,
    ResearchStandard,
    UncertaintyDecomposition,
    assess_claim,
    build_final_evidence_packet,
    build_runtime_evidence_packet,
)
from research_engine.models import EvidencePack, SourceRecord, SourceType


def _support(eid="e1", *, group="g1", primary=True, epistemic_type="MEASURED"):
    return EvidenceItem(
        evidence_id=eid,
        description="A pre-registered measurement supports the claim",
        epistemic_type=epistemic_type,
        source_id=f"source-{eid}",
        independent_group=group,
        supports_claim=True,
        primary_source=primary,
    )


def _contradiction(eid="c1", *, group="g2"):
    return EvidenceItem(
        evidence_id=eid,
        description="An independent measurement contradicts the claim",
        epistemic_type="MEASURED",
        source_id=f"source-{eid}",
        independent_group=group,
        supports_claim=False,
        primary_source=True,
    )


def _alternative(aid="alt-1"):
    return AlternativeExplanation(
        alternative_id=aid,
        statement="A competing mechanism can produce the same observed pattern",
        mechanism="A different causal pathway changes the measured endpoint",
        discriminating_predictions=(
            "The alternative predicts no response under intervention B",
        ),
        evidence_fit=0.6,
    )


def _complete_assessment(claim_id="claim-1"):
    return assess_claim(
        claim_id=claim_id,
        statement="The intervention changes the measured endpoint",
        claim_epistemic_type="MEASURED",
        confidence=0.8,
        uncertainty=UncertaintyDecomposition(
            measurement=0.05,
            sampling=0.05,
            model=0.1,
            epistemic=0.1,
            distribution_shift=0.05,
            unknown_unknown_allowance=0.1,
        ),
        evidence=(
            _support("e1", group="lab-a"),
            _support("e2", group="lab-b"),
        ),
        alternatives=(_alternative(),),
        what_would_change_my_mind=(
            "A blinded replication showing no effect within the pre-registered tolerance",
        ),
        evidence_frontier=(
            "Independent replication in a different population remains useful",
        ),
        open_questions=("Which mechanism dominates under regime C?",),
        disconfirming_search_performed=True,
        standard=ResearchStandard(
            min_supporting_evidence=2,
            min_primary_sources=1,
            min_independent_groups=2,
        ),
    )


def test_complete_measured_assessment_passes_without_calling_confidence_truth():
    assessment = _complete_assessment()
    assert assessment.hierarchical_status == "MEASURED_OR_OBSERVED"
    assert assessment.standard_passed is True
    assert assessment.blockers == ()
    assert assessment.anti_confirmation_complete is True
    assert assessment.confidence == pytest.approx(0.8)
    assert assessment.confidence_is_truth_probability is False
    assert assessment.truth_proven is False
    assert len(assessment.assessment_hash) == 64


def test_no_evidence_cannot_be_upgraded_by_high_confidence():
    assessment = assess_claim(
        claim_id="unsupported",
        statement="A strong sounding claim lacks supplied evidence",
        claim_epistemic_type="INFERRED",
        confidence=0.999,
        uncertainty=UncertaintyDecomposition(epistemic=0.9),
        evidence=(),
        alternatives=(_alternative(),),
        what_would_change_my_mind=("A direct measurement would change the assessment",),
        disconfirming_search_performed=True,
    )
    assert assessment.hierarchical_status == "UNSUPPORTED"
    assert assessment.standard_passed is False
    assert "insufficient_supporting_evidence" in assessment.blockers
    assert assessment.truth_proven is False


def test_direct_contradiction_is_preserved_and_blocks_unqualified_completion():
    assessment = assess_claim(
        claim_id="contested",
        statement="The treatment improves the measured outcome",
        claim_epistemic_type="MEASURED",
        confidence=0.7,
        uncertainty=UncertaintyDecomposition(),
        evidence=(_support(), _contradiction()),
        alternatives=(_alternative(),),
        what_would_change_my_mind=("A larger blinded replication resolves the conflict",),
        disconfirming_search_performed=True,
    )
    assert assessment.hierarchical_status == "CONTESTED"
    assert assessment.standard_passed is False
    assert assessment.contradicting_evidence_ids == ("c1",)
    assert "contradicting_evidence_present" in assessment.blockers


def test_inference_is_never_relabelled_measured_just_because_evidence_exists():
    assessment = assess_claim(
        claim_id="inference",
        statement="The latent mechanism explains the observed association",
        claim_epistemic_type="INFERRED",
        confidence=0.7,
        uncertainty=UncertaintyDecomposition(model=0.3, epistemic=0.3),
        evidence=(_support(epistemic_type="LITERATURE_REPORT"),),
        alternatives=(_alternative(),),
        what_would_change_my_mind=("A discriminating intervention falsifies the mechanism",),
        disconfirming_search_performed=True,
    )
    assert assessment.hierarchical_status == "INFERENCE_OR_REPORT"
    assert assessment.claim_epistemic_type == "INFERRED"


def test_missing_falsifier_alternative_or_disconfirming_search_fails_closed():
    assessment = assess_claim(
        claim_id="confirmation-risk",
        statement="Evidence is currently one-sided",
        claim_epistemic_type="LITERATURE_REPORT",
        confidence=0.5,
        uncertainty=UncertaintyDecomposition(epistemic=0.5),
        evidence=(_support(),),
    )
    assert assessment.standard_passed is False
    assert "disconfirming_search_missing" in assessment.blockers
    assert "what_would_change_my_mind_missing" in assessment.blockers
    assert "alternative_explanation_missing" in assessment.blockers
    assert "anti_confirmation_incomplete" in assessment.blockers


def test_alternative_requires_a_discriminating_prediction():
    with pytest.raises(ValueError, match="discriminating prediction"):
        AlternativeExplanation(
            alternative_id="bad-alt",
            statement="Alternative explanation exists",
            mechanism="Alternative pathway exists",
            discriminating_predictions=(),
            evidence_fit=0.5,
        ).normalized()


def test_personalized_standard_can_only_tighten_never_weaken_base_floor():
    base = ResearchStandard(
        min_supporting_evidence=2,
        min_primary_sources=1,
        min_independent_groups=2,
        require_disconfirming_search=True,
        require_falsifier=True,
        require_alternative_explanation=True,
    )
    attempted_weaker = ResearchStandard(
        min_supporting_evidence=0,
        min_primary_sources=0,
        min_independent_groups=0,
        require_disconfirming_search=False,
        require_falsifier=False,
        require_alternative_explanation=False,
    )
    effective = base.tightened_by(attempted_weaker)
    assert effective.min_supporting_evidence == 2
    assert effective.min_primary_sources == 1
    assert effective.min_independent_groups == 2
    assert effective.require_disconfirming_search is True
    assert effective.require_falsifier is True
    assert effective.require_alternative_explanation is True

    stronger = base.tightened_by(
        ResearchStandard(min_supporting_evidence=5, min_primary_sources=3, min_independent_groups=4)
    )
    assert stronger.min_supporting_evidence == 5
    assert stronger.min_primary_sources == 3
    assert stronger.min_independent_groups == 4


def test_uncertainty_decomposition_is_bounded_and_not_truth_probability():
    uncertainty = UncertaintyDecomposition(
        measurement=0.1,
        sampling=0.2,
        model=0.3,
        epistemic=0.4,
        distribution_shift=0.1,
        unknown_unknown_allowance=0.2,
    )
    combined = uncertainty.combined_upper_bound
    assert 0.0 <= combined <= 1.0
    assert math.isfinite(combined)
    with pytest.raises(ValueError, match="in \[0,1\]"):
        UncertaintyDecomposition(model=1.1).normalized()
    with pytest.raises(ValueError, match="finite"):
        UncertaintyDecomposition(model=float("nan")).normalized()


def test_final_packet_separates_measured_inferred_and_unresolved_deterministically():
    measured = _complete_assessment("measured")
    inferred = assess_claim(
        claim_id="inferred",
        statement="A mechanism remains an inference pending a direct test",
        claim_epistemic_type="INFERRED",
        confidence=0.4,
        uncertainty=UncertaintyDecomposition(epistemic=0.6),
        evidence=(_support("e3", group="lab-c", epistemic_type="LITERATURE_REPORT"),),
        alternatives=(_alternative("alt-2"),),
        what_would_change_my_mind=("A direct intervention contradicts the mechanism",),
        disconfirming_search_performed=True,
    )
    first = build_final_evidence_packet("packet-v1", (measured, inferred))
    second = build_final_evidence_packet("packet-v1", (inferred, measured))
    assert first.packet_hash == second.packet_hash
    assert first.measured_claim_ids == ("measured",)
    assert first.inferred_claim_ids == ("inferred",)
    assert first.truth_proven is False


def test_duplicate_evidence_claims_and_invalid_types_fail_closed():
    duplicate = _support("dup")
    with pytest.raises(ValueError, match="evidence_id values must be unique"):
        assess_claim(
            claim_id="dup-claim",
            statement="Duplicate evidence identifiers are invalid",
            claim_epistemic_type="MEASURED",
            confidence=0.5,
            uncertainty=UncertaintyDecomposition(),
            evidence=(duplicate, duplicate),
            alternatives=(_alternative(),),
            what_would_change_my_mind=("Independent evidence could change the conclusion",),
            disconfirming_search_performed=True,
        )
    with pytest.raises(ValueError, match="unsupported claim_epistemic_type"):
        assess_claim(
            claim_id="bad-type",
            statement="This claim uses an invalid epistemic label",
            claim_epistemic_type="CERTAIN_TRUTH",
            confidence=1.0,
            uncertainty=UncertaintyDecomposition(),
            evidence=(),
        )


def _runtime_claim_checks(*, with_span=True, contradicted=False):
    spans = ([{
        "source_id": "S1",
        "passage": "The measured endpoint changed in the registered experiment.",
    }] if with_span else [])
    return {
        "critical_claim_spans": [{
            "claim_id": "CL001",
            "text": "The measured endpoint changed in the registered experiment.",
            "epistemic_type": "LITERATURE_REPORT",
            "result": "CONTRADICTED" if contradicted else "SUPPORTED",
            "contradicted": contradicted,
            "evidence_spans": spans,
        }]
    }


def _runtime_pack():
    return EvidencePack(sources=[SourceRecord(
        source_id="S1",
        title="Registered experiment",
        snippet="The measured endpoint changed.",
        url="https://example.org/study",
        year=2024,
        publisher="Example Lab",
        source_type=SourceType.PAPER,
        is_primary=True,
    )])


def test_runtime_packet_keeps_missing_alternatives_and_falsifier_as_blockers():
    result = build_runtime_evidence_packet(
        question="Did the endpoint change?",
        claim_checks=_runtime_claim_checks(),
        pack=_runtime_pack(),
        disconfirming_search_performed=True,
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assessment = result["assessments"][0]
    assert assessment["hierarchical_status"] == "INFERENCE_OR_REPORT"
    assert "alternative_explanation_missing" in assessment["blockers"]
    assert "what_would_change_my_mind_missing" in assessment["blockers"]
    assert result["truth_proven"] is False
    assert result["confidence_is_truth_probability"] is False


def test_runtime_packet_mutation_cannot_preserve_supported_assessment_hash():
    supported = build_runtime_evidence_packet(
        question="Did the endpoint change?",
        claim_checks=_runtime_claim_checks(),
        pack=_runtime_pack(),
        disconfirming_search_performed=True,
    )
    unsupported = build_runtime_evidence_packet(
        question="Did the endpoint change?",
        claim_checks=_runtime_claim_checks(with_span=False),
        pack=_runtime_pack(),
        disconfirming_search_performed=True,
    )
    assert supported["packet_hash"] != unsupported["packet_hash"]
    assert unsupported["assessments"][0]["hierarchical_status"] == "UNSUPPORTED"
    assert "insufficient_supporting_evidence" in unsupported["assessments"][0]["blockers"]


def test_real_research_pipeline_exposes_epistemic_packet():
    from tests.benchmark_cross_domain import MATERIALS, _run, rounds_full

    result, _discovery, _model = _run(MATERIALS, rounds_full(MATERIALS))
    packet = result["epistemic_packet"]
    assert packet["ran"] is True
    assert packet["truth_proven"] is False
    assert packet["confidence_is_truth_probability"] is False
    assert result["coverage"]["epistemic_governance"] == packet
