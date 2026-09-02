import hashlib

import pytest

from research_engine.source_integrity import (
    DynamicSourceTrust,
    ResolvedSourceOutcome,
    SourceObservation,
    analyze_source_integrity,
    analyze_evidence_pack,
)
from research_engine.models import EvidencePack, SourceRecord, SourceType


def _h(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(
    source_id,
    *,
    publisher=None,
    group=None,
    content=None,
    published=1000,
    parents=(),
    provenance=True,
    fingerprint="",
):
    return SourceObservation(
        source_id=source_id,
        publisher_id=publisher or f"pub-{source_id}",
        independence_group=group or f"group-{source_id}",
        content_hash=_h(content or source_id),
        published_at_epoch=published,
        provenance_complete=provenance,
        parent_source_ids=parents,
        claim_fingerprint=fingerprint,
    )


def test_dynamic_trust_changes_only_from_explicit_resolved_outcomes():
    trust = DynamicSourceTrust(prior_alpha=1.0, prior_beta=1.0)
    initial = trust.state("s1")
    assert initial.posterior_mean == pytest.approx(0.5)
    assert initial.resolved_weight == pytest.approx(0.0)
    assert initial.trust_is_truth_probability is False

    updated = trust.update(
        (
            ResolvedSourceOutcome("s1", True, 2.0, "resolution-1"),
            ResolvedSourceOutcome("s1", False, 1.0, "resolution-2"),
        )
    )[0]
    assert updated.alpha == pytest.approx(3.0)
    assert updated.beta == pytest.approx(2.0)
    assert updated.posterior_mean == pytest.approx(0.6)
    assert updated.resolved_weight == pytest.approx(3.0)
    assert updated.trust_is_truth_probability is False


def test_resolved_outcome_cannot_be_replayed_or_double_counted():
    trust = DynamicSourceTrust()
    trust.update((ResolvedSourceOutcome("s1", True, 1.0, "r1"),))
    with pytest.raises(ValueError, match="already applied"):
        trust.update((ResolvedSourceOutcome("s1", True, 1.0, "r1"),))
    with pytest.raises(ValueError, match="unique within update"):
        trust.update(
            (
                ResolvedSourceOutcome("s1", True, 1.0, "r2"),
                ResolvedSourceOutcome("s2", False, 1.0, "r2"),
            )
        )


def test_exact_syndication_across_nominal_independence_groups_counts_once():
    shared = "identical syndicated article"
    report = analyze_source_integrity(
        (
            _source("s1", group="g1", content=shared),
            _source("s2", group="g2", content=shared),
            _source("s3", group="g3", content=shared),
        )
    )
    assert report.source_count == 3
    assert report.unique_content_count == 1
    assert report.independence_group_count == 3
    assert report.effective_independent_support == 1
    assert report.consensus_proves_truth is False
    assert report.fraud_proven is False
    kinds = {item.kind for item in report.findings}
    assert "DUPLICATE_OR_SYNDICATED_CONTENT" in kinds
    assert set(report.quarantine_candidates) == {"s1", "s2", "s3"}


def test_same_independence_group_with_different_content_still_counts_once():
    report = analyze_source_integrity(
        (
            _source("s1", group="wire-service", content="version one"),
            _source("s2", group="wire-service", content="version two"),
            _source("s3", group="independent-lab", content="distinct measurement"),
        )
    )
    assert report.effective_independent_support == 2


def test_distinct_independent_sources_remain_distinct_without_proving_truth():
    report = analyze_source_integrity(
        (
            _source("s1", group="lab-a", content="measurement A"),
            _source("s2", group="lab-b", content="measurement B"),
        )
    )
    assert report.effective_independent_support == 2
    assert report.findings == ()
    assert report.consensus_proves_truth is False


def test_circular_genealogy_is_high_severity_and_quarantined_for_review():
    report = analyze_source_integrity(
        (
            _source("a", parents=("b",), published=1000),
            _source("b", parents=("c",), published=1000),
            _source("c", parents=("a",), published=1000),
        )
    )
    cycles = [item for item in report.findings if item.kind == "CIRCULAR_SOURCE_GENEALOGY"]
    assert len(cycles) == 1
    assert cycles[0].severity == "HIGH"
    assert cycles[0].fraud_proven is False
    assert set(cycles[0].source_ids) == {"a", "b", "c"}
    assert set(report.quarantine_candidates) >= {"a", "b", "c"}


def test_provenance_chronology_anomaly_is_surfaced_not_silently_rewritten():
    report = analyze_source_integrity(
        (
            _source("parent", published=2000),
            _source("child", published=1000, parents=("parent",)),
        )
    )
    finding = next(item for item in report.findings if item.kind == "PROVENANCE_CHRONOLOGY_ANOMALY")
    assert finding.severity == "HIGH"
    assert set(finding.source_ids) == {"child", "parent"}
    assert finding.fraud_proven is False


def test_missing_provenance_and_coordinated_claim_pattern_are_review_signals():
    report = analyze_source_integrity(
        (
            _source("s1", publisher="p1", group="g1", provenance=False, fingerprint="claim-x"),
            _source("s2", publisher="p1", group="g2", fingerprint="claim-x"),
            _source("s3", publisher="p2", group="g3", fingerprint="claim-x"),
        )
    )
    kinds = {item.kind for item in report.findings}
    assert "MISSING_PROVENANCE" in kinds
    assert "COORDINATED_CLAIM_PATTERN" in kinds
    assert report.fraud_proven is False


def test_integrity_report_is_deterministic_under_source_order():
    sources = (
        _source("s1", group="g1", content="shared"),
        _source("s2", group="g2", content="shared"),
        _source("s3", group="g3", content="unique"),
    )
    first = analyze_source_integrity(sources)
    second = analyze_source_integrity(tuple(reversed(sources)))
    assert first.report_hash == second.report_hash
    assert [item.finding_hash for item in first.findings] == [item.finding_hash for item in second.findings]


def test_invalid_source_metadata_fails_closed():
    with pytest.raises(ValueError, match="content_hash"):
        _source("s1").__class__(
            source_id="s1",
            publisher_id="p1",
            independence_group="g1",
            content_hash="bad",
            published_at_epoch=1000,
        ).normalized()
    with pytest.raises(ValueError, match="published_at_epoch"):
        SourceObservation("s1", "p1", "g1", _h("x"), float("nan")).normalized()
    with pytest.raises(ValueError, match="cite itself"):
        SourceObservation("s1", "p1", "g1", _h("x"), 1000, parent_source_ids=("s1",)).normalized()


def test_evidence_pack_adapter_flags_cross_origin_exact_duplication():
    first = SourceRecord(
        source_id="S1", title="Shared report", snippet="same exact measurement",
        url="https://alpha.example/paper", year=2024, publisher="Alpha",
        source_type=SourceType.PAPER,
    )
    second = SourceRecord(
        source_id="S2", title="Shared report", snippet="same exact measurement",
        url="https://beta.example/copy", year=2024, publisher="Beta",
        source_type=SourceType.WEB,
    )
    result = analyze_evidence_pack(EvidencePack(sources=[first, second]))
    assert result["ran"] is True
    assert result["high_risk"] is True
    assert result["effective_independent_support"] == 1
    assert result["quarantine_candidates"] == ["S1", "S2"]
    assert result["fraud_proven"] is False
    assert result["consensus_proves_truth"] is False
    assert result["clean_bill_of_health"] is False


def test_evidence_pack_adapter_never_calls_missing_metadata_clean():
    source = SourceRecord(source_id="S1", title="Undated source", snippet="visible")
    result = analyze_evidence_pack(EvidencePack(sources=[source]))
    assert result["status"] == "INSUFFICIENT_METADATA"
    assert result["assessed_source_count"] == 0
    assert result["clean_bill_of_health"] is False
    assert result["unassessed_sources"][0]["source_id"] == "S1"


def test_real_research_pipeline_invokes_source_integrity(monkeypatch):
    from research_engine import orchestrator
    from tests.benchmark_cross_domain import MATERIALS, _run, rounds_full

    calls = []
    original = orchestrator.analyze_evidence_pack

    def observed(pack):
        calls.append(tuple(source.source_id for source in pack.sources))
        return original(pack)

    monkeypatch.setattr(orchestrator, "analyze_evidence_pack", observed)
    result, _discovery, _model = _run(MATERIALS, rounds_full(MATERIALS))
    assert calls and calls[0]
    assert result["source_integrity"]["ran"] is True
    assert result["coverage"]["source_integrity"] == result["source_integrity"]
    assert result["source_integrity"]["clean_bill_of_health"] is False


def test_high_risk_runtime_signal_blocks_strong_label(monkeypatch):
    from research_engine import orchestrator
    from tests.benchmark_cross_domain import MATERIALS, _run, rounds_full

    monkeypatch.setattr(
        orchestrator,
        "analyze_evidence_pack",
        lambda pack: {
            "ran": True,
            "status": "REVIEW_REQUIRED",
            "high_risk": True,
            "clean_bill_of_health": False,
            "findings": [{"kind": "DUPLICATE_OR_SYNDICATED_CONTENT", "severity": "HIGH"}],
            "quarantine_candidates": [pack.sources[0].source_id],
            "limitations": [],
        },
    )
    result, _discovery, _model = _run(MATERIALS, rounds_full(MATERIALS))
    assert not result["evidence_level"].startswith(("✅ VERIFIED", "✅ STRONG"))
    assert any("Source-integrity audit" in warning for warning in result["warnings"])
