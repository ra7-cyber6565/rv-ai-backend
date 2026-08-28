import hashlib

import pytest

from research_engine.source_integrity import (
    DynamicSourceTrust,
    ResolvedSourceOutcome,
    SourceObservation,
    analyze_source_integrity,
)


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
