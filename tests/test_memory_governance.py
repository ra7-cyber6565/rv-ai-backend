import json

import pytest

from research_engine.memory_governance import (
    DecayPolicy,
    FailureMemory,
    MemoryRecord,
    assess_knowledge_decay,
    consolidate_memories,
)


def test_decay_never_increases_confidence_and_marks_stale():
    result = assess_knowledge_decay(
        memory_id="fact-1",
        confidence=0.9,
        last_verified_at="2026-01-01T00:00:00+00:00",
        now="2026-03-02T00:00:00+00:00",
        policy=DecayPolicy(half_life_days=30, stale_after_days=45),
    )
    assert result.usable_confidence_ceiling == pytest.approx(0.225)
    assert result.usable_confidence_ceiling <= result.original_confidence
    assert result.stale is True
    assert result.revalidation_required is True
    assert result.confidence_increased_by_decay is False


def test_decay_floor_can_never_exceed_original_confidence():
    result = assess_knowledge_decay(
        memory_id="low-confidence",
        confidence=0.1,
        last_verified_at="2026-01-01T00:00:00+00:00",
        now="2026-01-02T00:00:00+00:00",
        policy=DecayPolicy(half_life_days=100, stale_after_days=200, minimum_confidence_floor=0.9),
    )
    assert result.usable_confidence_ceiling == 0.1


def test_decay_rejects_time_reversal_and_invalid_policy():
    with pytest.raises(ValueError, match="must not precede"):
        assess_knowledge_decay(
            memory_id="x",
            confidence=0.5,
            last_verified_at="2026-02-01T00:00:00+00:00",
            now="2026-01-01T00:00:00+00:00",
            policy=DecayPolicy(30, 30),
        )
    with pytest.raises(ValueError):
        DecayPolicy(0, 30).normalized()


def test_exact_duplicate_consolidation_preserves_all_provenance_without_deleting():
    records = [
        MemoryRecord("m1", {"claim": "A", "value": 1}, ("s1",)),
        MemoryRecord("m2", {"value": 1, "claim": "A"}, ("s2",)),
    ]
    groups = consolidate_memories(records)
    assert len(groups) == 1
    group = groups[0]
    assert group.member_ids == ("m1", "m2")
    assert group.provenance_ids == ("s1", "s2")
    assert group.exact_content_match is True
    assert group.destructive_merge_performed is False
    assert records[0].memory_id == "m1"


def test_different_content_is_not_semantically_merged_without_explicit_key():
    groups = consolidate_memories([
        MemoryRecord("m1", {"claim": "A"}, ("s1",)),
        MemoryRecord("m2", {"claim": "A maybe"}, ("s2",)),
    ])
    assert len(groups) == 2


def test_declared_equivalence_can_group_different_content_but_marks_non_exact():
    groups = consolidate_memories([
        MemoryRecord("m1", {"claim": "A"}, ("s1",), equivalence_key="eq-1"),
        MemoryRecord("m2", {"claim": "A translated"}, ("s2",), equivalence_key="eq-1"),
    ])
    assert len(groups) == 1
    assert groups[0].exact_content_match is False
    assert groups[0].equivalence_key == "eq-1"
    assert groups[0].destructive_merge_performed is False


def test_consolidation_requires_unique_ids_and_provenance():
    with pytest.raises(ValueError, match="unique"):
        consolidate_memories([
            MemoryRecord("same", {"x": 1}, ("s1",)),
            MemoryRecord("same", {"x": 1}, ("s2",)),
        ])
    with pytest.raises(ValueError, match="provenance"):
        consolidate_memories([MemoryRecord("m1", {"x": 1}, ())])


def _failure(store, failure_id="f1", **overrides):
    data = dict(
        occurred_at="2026-08-30T00:00:00+00:00",
        mistake_class="IMPLEMENTATION_BUG",
        component="orchestrator",
        symptom="wrong result was returned",
        root_cause="stale cache key reused",
        severity=0.8,
        recurrence_key="stale-cache",
        evidence_ids=("log-1",),
        remediation="bind cache key to revision",
    )
    data.update(overrides)
    return store.record_failure(failure_id, **data)


def test_failure_memory_is_persistent_hash_chained_and_resolution_does_not_erase(tmp_path):
    store = FailureMemory(str(tmp_path), project_id="p1")
    first = _failure(store)
    assert first["resolved"] is False
    store.resolve_failure("f1", resolution="revision-bound cache deployed", evidence_ids=("test-1",))
    store.save()

    loaded = FailureMemory(str(tmp_path), project_id="p1")
    assert loaded.audit_integrity()["valid"] is True
    record = loaded.load()["failures"]["f1"]
    assert record["resolved"] is True
    assert record["root_cause"] == "stale cache key reused"
    assert len(loaded.load()["audit_chain"]) == 2


def test_failure_ids_are_immutable_and_resolution_is_single_use(tmp_path):
    store = FailureMemory(str(tmp_path))
    _failure(store)
    with pytest.raises(ValueError, match="already exists"):
        _failure(store)
    store.resolve_failure("f1", resolution="fixed and independently checked", evidence_ids=("e2",))
    with pytest.raises(ValueError, match="already resolved"):
        store.resolve_failure("f1", resolution="again", evidence_ids=("e3",))


def test_failure_requires_known_taxonomy_and_evidence(tmp_path):
    store = FailureMemory(str(tmp_path))
    with pytest.raises(ValueError, match="mistake_class"):
        _failure(store, mistake_class="made_up_class")
    with pytest.raises(ValueError, match="evidence"):
        _failure(store, evidence_ids=())


def test_recurrence_report_surfaces_repeated_pattern_and_unresolved_count(tmp_path):
    store = FailureMemory(str(tmp_path))
    _failure(store, "f1")
    _failure(store, "f2", occurred_at="2026-08-31T00:00:00+00:00", evidence_ids=("log-2",))
    _failure(
        store,
        "f3",
        mistake_class="DATA_QUALITY",
        recurrence_key="bad-csv",
        component="loader",
        evidence_ids=("log-3",),
    )
    store.resolve_failure("f1", resolution="fixed", evidence_ids=("test-1",))
    report = store.recurrence_report()
    assert report["total_failures"] == 3
    top = report["patterns"][0]
    assert top["recurrence_key"] == "stale-cache"
    assert top["count"] == 2
    assert top["unresolved"] == 1
    assert "IMPLEMENTATION_BUG" in report["taxonomy"]


def test_on_disk_audit_tampering_fails_closed_on_reload(tmp_path):
    store = FailureMemory(str(tmp_path))
    _failure(store)
    store.save()
    path = store.path
    data = json.loads(open(path, "r", encoding="utf-8").read())
    data["audit_chain"][0]["details_hash"] = "0" * 64
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    with pytest.raises(ValueError, match="hash mismatch"):
        FailureMemory(str(tmp_path)).load()


def test_failure_severity_boolean_and_invalid_timestamp_fail_closed(tmp_path):
    store = FailureMemory(str(tmp_path))
    with pytest.raises(ValueError):
        _failure(store, severity=True)
    with pytest.raises(ValueError, match="timezone"):
        _failure(store, occurred_at="2026-08-30T00:00:00")
