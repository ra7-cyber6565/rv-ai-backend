"""Evidence-first manifest identity binds question, policy and eligibility basis."""
from __future__ import annotations

from research_engine.evidence_drafting import build_evidence_draft_manifest
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


PASSAGE = (
    "Electrical resistance measurements show a superconducting transition in "
    "lanthanum hydride LaH10 near 250 K at 170 GPa. Magnetic susceptibility "
    "tracks the same transition and the measurements were repeated on multiple "
    "samples in a diamond anvil cell."
)


def _pack(*, quality: float = 0.88) -> EvidencePack:
    source = SourceRecord(
        title="Fixture paper",
        url="https://example.org/lah10",
        source_type=SourceType.PAPER,
        connector="fixture",
        peer_reviewed=True,
        read_level="full_text",
        full_text_chars=40000,
        relevance_score=0.92,
        quality_score=quality,
        source_id="S1",
    )
    return EvidencePack(
        sources=[source],
        passages=[Passage(
            source_id="S1",
            text=PASSAGE,
            locator="p.42 ¶3",
            provenance="full_text_excerpt",
            read_level_at_capture="full_text",
        )],
    )


def test_manifest_identity_is_deterministic_for_same_question_and_inputs():
    question = "What does the LaH10 experiment show at 250 K and 170 GPa?"
    first = build_evidence_draft_manifest(question, _pack())
    second = build_evidence_draft_manifest(question, _pack())
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.question_sha256 == second.question_sha256
    assert len(first.manifest_sha256) == 64
    assert len(first.question_sha256) == 64


def test_same_passage_for_different_question_has_different_identity():
    first = build_evidence_draft_manifest(
        "What does the LaH10 experiment show?", _pack())
    second = build_evidence_draft_manifest(
        "What pressure was used in the LaH10 experiment?", _pack())
    assert first.spans[0].passage_sha256 == second.spans[0].passage_sha256
    assert first.question_sha256 != second.question_sha256
    assert first.manifest_sha256 != second.manifest_sha256


def test_manifest_identity_binds_eligibility_basis_not_only_boolean_result():
    question = "What does the LaH10 experiment show?"
    high = build_evidence_draft_manifest(question, _pack(quality=0.88))
    lower = build_evidence_draft_manifest(question, _pack(quality=0.70))
    assert high.spans[0].passage_sha256 == lower.spans[0].passage_sha256
    assert high.spans[0].strong_claim_eligible is True
    assert lower.spans[0].strong_claim_eligible is True
    assert high.manifest_sha256 != lower.manifest_sha256


def test_manifest_identity_binds_policy_even_when_span_text_is_same():
    question = "What does the LaH10 experiment show?"
    first = build_evidence_draft_manifest(question, _pack(), segment_chars=900)
    second = build_evidence_draft_manifest(question, _pack(), segment_chars=1200)
    assert first.spans[0].passage_sha256 == second.spans[0].passage_sha256
    assert first.manifest_sha256 != second.manifest_sha256


def test_compact_manifest_exposes_hashes_and_policy_without_raw_text():
    question = "Private-ish user wording must not be copied into compact manifest"
    manifest = build_evidence_draft_manifest(question, _pack())
    payload = manifest.to_dict()
    assert payload["identity_version"] == "p0b-id-2"
    assert payload["question_sha256"] == manifest.question_sha256
    assert payload["selection_policy"]["segment_chars"] == 1200
    assert question not in str(payload)
    assert PASSAGE not in str(payload)
    assert "passage" not in payload["spans"][0]


def test_prompt_carries_question_bound_stamp_without_raw_question_metadata():
    question = "What does the LaH10 experiment show?"
    manifest = build_evidence_draft_manifest(question, _pack())
    block = manifest.prompt_block()
    before_evidence = block.split("BEGIN_PRESELECTED_EVIDENCE", 1)[0]
    assert f"manifest_sha256={manifest.manifest_sha256}" in block
    assert f"question_sha256={manifest.question_sha256}" in block
    assert "identity_version=p0b-id-2" in block
    assert question not in before_evidence
