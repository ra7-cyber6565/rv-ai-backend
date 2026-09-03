import pytest

from research_engine.knowledge_watch import (
    KnowledgeWatch, sha256_content, update_from_research_run,
)


class _Source:
    def __init__(self, source_id="S1", *, retracted=False):
        self.source_id = source_id
        self.title = "Stable paper"
        self.doi = "10.1234/stable"
        self.url = "https://doi.org/10.1234/stable"
        self.year = 2025
        self.locator = "p. 4"
        self.retracted = retracted


class _Pack:
    def __init__(self, source):
        self.sources = [source]


def _checks(local_sid="S1"):
    return {"claims": [{
        "text": "The measured endpoint increased under the stated protocol.",
        "same_source_ae_passed": True,
        "supporting_source_id": local_sid,
    }]}


def _watch(tmp_path):
    return KnowledgeWatch(str(tmp_path), project_id="P1")


def test_new_source_then_unchanged_observation_does_not_queue_claim(tmp_path):
    watch = _watch(tmp_path)
    watch.link_claim("C1", ["S1"])
    first = watch.observe_source("S1", content="paper v1", status="ACTIVE", version_label="v1")
    second = watch.observe_source("S1", content="paper v1", status="ACTIVE", version_label="v1")
    assert first["event"]["kind"] == "NEW_SOURCE"
    assert first["material_change"] is False
    assert second["event"]["kind"] == "UNCHANGED"
    assert second["queued_claim_ids"] == []
    assert watch.pending_revalidations() == []


def test_content_change_queues_every_dependent_claim_once(tmp_path):
    watch = _watch(tmp_path)
    watch.link_claim("C1", ["S1"])
    watch.link_claim("C2", ["S1", "S2"])
    watch.observe_source("S1", content="v1", status="ACTIVE")
    changed = watch.observe_source("S1", content="v2", status="ACTIVE")
    assert changed["event"]["kind"] == "CONTENT_CHANGED"
    assert changed["queued_claim_ids"] == ["C1", "C2"]
    assert len(watch.pending_revalidations()) == 2
    again = watch.observe_source("S1", content="v3", status="ACTIVE")
    assert again["event"]["kind"] == "CONTENT_CHANGED"
    assert again["queued_claim_ids"] == []
    assert len(watch.pending_revalidations()) == 2


def test_retraction_and_removal_are_material_and_preserve_history(tmp_path):
    watch = _watch(tmp_path)
    watch.link_claim("C1", ["S1"])
    watch.observe_source("S1", content="original", status="ACTIVE", version_label="1")
    retracted = watch.observe_source("S1", content="retraction notice", status="RETRACTED", version_label="2")
    assert retracted["event"]["kind"] == "RETRACTED"
    assert retracted["queued_claim_ids"] == ["C1"]
    assert len(watch.source_history("S1")) == 2
    watch.resolve_revalidation("C1", "S1", outcome="REJECTED")
    removed = watch.observe_source("S1", content=None, status="REMOVED", version_label="3")
    assert removed["event"]["kind"] == "REMOVED"
    assert removed["queued_claim_ids"] == ["C1"]
    assert len(watch.source_history("S1")) == 3


def test_replaced_revalidation_requires_new_evidence(tmp_path):
    watch = _watch(tmp_path)
    watch.link_claim("C1", ["S1"])
    watch.observe_source("S1", content="v1")
    watch.observe_source("S1", content="v2")
    with pytest.raises(ValueError, match="replacement"):
        watch.resolve_revalidation("C1", "S1", outcome="REPLACED")
    resolved = watch.resolve_revalidation("C1", "S1", outcome="REPLACED", replacement_evidence_ids=["S2"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["outcome"] == "REPLACED"
    assert resolved["replacement_evidence_ids"] == ["S2"]


def test_restoration_is_distinguished_from_new_source(tmp_path):
    watch = _watch(tmp_path)
    watch.observe_source("S1", content="v1")
    watch.observe_source("S1", content=None, status="REMOVED")
    restored = watch.observe_source("S1", content="v2", status="ACTIVE")
    assert restored["event"]["kind"] == "RESTORED"
    assert watch.events(source_id="S1")[-1]["kind"] == "RESTORED"


def test_persistence_roundtrip_keeps_pending_queue_and_source_versions(tmp_path):
    watch = _watch(tmp_path)
    watch.link_claim("C1", ["S1"])
    watch.observe_source("S1", content="v1")
    watch.observe_source("S1", content="v2")
    watch.save()
    reloaded = _watch(tmp_path)
    assert reloaded.pending_revalidations()[0]["claim_id"] == "C1"
    assert len(reloaded.source_history("S1")) == 2


def test_content_hash_is_deterministic_and_status_validation_is_strict(tmp_path):
    assert sha256_content("abc") == sha256_content(b"abc")
    watch = _watch(tmp_path)
    with pytest.raises(ValueError):
        watch.observe_source("S1", content="x", status="MADE_UP")
    with pytest.raises(ValueError):
        watch.observe_source("S1", content=None, status="ACTIVE")
    with pytest.raises(ValueError):
        watch.link_claim("C1", [])


def test_unknown_revalidation_or_source_fails_closed(tmp_path):
    watch = _watch(tmp_path)
    with pytest.raises(KeyError):
        watch.resolve_revalidation("C1", "S1", outcome="CONFIRMED")
    with pytest.raises(KeyError):
        watch.source_history("S1")


def test_runtime_adapter_uses_stable_identity_not_run_local_labels(tmp_path):
    first = update_from_research_run(
        _watch(tmp_path), pack=_Pack(_Source("S1")), claim_checks=_checks("S1"))
    second = update_from_research_run(
        _watch(tmp_path), pack=_Pack(_Source("S9")), claim_checks=_checks("S9"))
    assert first["linked_claims"] == second["linked_claims"] == 1
    watch = _watch(tmp_path)
    assert len(watch.load()["sources"]) == 1
    assert len(watch.load()["claim_sources"]) == 1
    assert second["pending_revalidations"] == 0
    assert second["selected_passages_hashed_as_source_content"] is False
    assert second["truth_proven"] is False


def test_runtime_retraction_queues_the_exact_dependent_claim(tmp_path):
    update_from_research_run(
        _watch(tmp_path), pack=_Pack(_Source()), claim_checks=_checks())
    receipt = update_from_research_run(
        _watch(tmp_path), pack=_Pack(_Source(retracted=True)),
        claim_checks=_checks())
    assert receipt["newly_queued_claims"]
    assert receipt["pending_revalidations"] == 1
    pending = _watch(tmp_path).pending_revalidations()[0]
    assert pending["trigger"] == "RETRACTED"


def test_real_research_pipeline_exposes_knowledge_watch_receipt(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RESEARCH_MEMORY_DIR", str(tmp_path))
    from tests.benchmark_cross_domain import MATERIALS, _run, rounds_full

    result, _discovery, _model = _run(MATERIALS, rounds_full(MATERIALS))
    receipt = result["knowledge_watch"]
    assert receipt["ran"] is True
    assert receipt["stable_identity"] is True
    assert receipt["truth_proven"] is False
    assert result["coverage"]["knowledge_watch"] == receipt
