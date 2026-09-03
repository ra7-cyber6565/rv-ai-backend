import hashlib

import pytest

from research_engine.literature_debate import (
    LiteraturePosition,
    debate_literature,
    report_to_dict,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pos(
    source_id: str,
    position_id: str,
    *,
    proposition_id: str = "P1",
    independence_key: str | None = None,
    content: str | None = None,
    quality: str = "STRONG",
    retracted: bool = False,
    provenance_complete: bool = True,
    parents=(),
):
    text = content or f"{position_id} result from {source_id}"
    return LiteraturePosition(
        source_id=source_id,
        proposition_id=proposition_id,
        position_id=position_id,
        position_text=text,
        independence_key=independence_key or f"family:{source_id}",
        content_hash=_digest(text),
        evidence_ref=f"{source_id}:page-1",
        quality=quality,
        retracted=retracted,
        provenance_complete=provenance_complete,
        parent_source_ids=tuple(parents),
    )


def test_two_independent_opposing_positions_create_unresolved_debate():
    report = debate_literature([_pos("S1", "SUPPORT"), _pos("S2", "CHALLENGE")])
    debate = report.debates[0]
    assert debate.status == "DISPUTED_UNRESOLVED"
    assert debate.effective_components == 2
    assert debate.eligible_components == 2
    assert len(debate.cross_examinations) == 1
    assert debate.cross_examinations[0].answer_known is False
    assert report.unresolved_propositions == ("P1",)
    assert report.consensus_proves_truth is False
    assert report.truth_proven is False
    assert report.independent_validation_proven is False


def test_ten_syndicated_support_copies_count_as_one_component():
    shared = "identical syndicated article text"
    rows = [
        _pos(
            f"S{index}",
            "SUPPORT",
            independence_key=f"nominal-group-{index}",
            content=shared,
        )
        for index in range(10)
    ]
    report = debate_literature(rows)
    debate = report.debates[0]
    assert debate.source_count == 10
    assert debate.effective_components == 1
    assert debate.eligible_components == 1
    assert debate.status == "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    assert debate.components[0].collapsed_copy_count == 9


def test_declared_same_independence_group_collapses_different_wording():
    rows = [
        _pos("S1", "SUPPORT", independence_key="doi:10.1/work", content="version A"),
        _pos("S2", "SUPPORT", independence_key="doi:10.1/work", content="version B"),
        _pos("S3", "CHALLENGE", independence_key="doi:10.2/other", content="challenge"),
    ]
    debate = debate_literature(rows).debates[0]
    assert debate.effective_components == 2
    assert debate.eligible_components == 2
    assert debate.status == "DISPUTED_UNRESOLVED"


def test_genealogy_chain_cannot_masquerade_as_replication():
    rows = [
        _pos("S1", "SUPPORT"),
        _pos("S2", "SUPPORT", parents=("S1",)),
        _pos("S3", "SUPPORT", parents=("S2",)),
    ]
    debate = debate_literature(rows).debates[0]
    assert debate.effective_components == 1
    assert debate.status == "INSUFFICIENT_INDEPENDENT_EVIDENCE"


def test_one_sided_independent_literature_is_not_called_resolved_consensus():
    report = debate_literature([
        _pos("S1", "SUPPORT"),
        _pos("S2", "SUPPORT"),
        _pos("S3", "SUPPORT"),
    ])
    debate = report.debates[0]
    assert debate.eligible_components == 3
    assert debate.position_count == 1
    assert debate.status == "ONE_SIDED_LITERATURE"
    assert debate.unresolved is True
    assert debate.cross_examinations == ()
    assert report.consensus_proves_truth is False


def test_retracted_position_remains_visible_but_cannot_be_strong_independent_side():
    report = debate_literature([
        _pos("S1", "SUPPORT"),
        _pos("S2", "CHALLENGE", retracted=True),
    ])
    debate = report.debates[0]
    assert debate.source_count == 2
    assert debate.effective_components == 2
    assert debate.eligible_components == 1
    assert debate.status == "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    challenge = next(c for c in debate.components if c.position_id == "CHALLENGE")
    assert challenge.strong_count_eligible is False
    assert challenge.eligible_source_ids == ()


def test_weak_or_incomplete_provenance_does_not_form_strong_side():
    rows = [
        _pos("S1", "SUPPORT"),
        _pos("S2", "CHALLENGE", quality="WEAK"),
        _pos("S3", "CHALLENGE", provenance_complete=False),
    ]
    debate = debate_literature(rows).debates[0]
    assert debate.eligible_components == 1
    assert debate.status == "INSUFFICIENT_INDEPENDENT_EVIDENCE"


def test_duplicate_source_position_for_same_proposition_is_rejected():
    with pytest.raises(ValueError, match="same source cannot submit multiple positions"):
        debate_literature([_pos("S1", "SUPPORT"), _pos("S1", "CHALLENGE")])


def test_same_source_can_participate_in_distinct_propositions():
    report = debate_literature([
        _pos("S1", "SUPPORT", proposition_id="P1"),
        _pos("S1", "CHALLENGE", proposition_id="P2"),
    ])
    assert report.proposition_count == 2
    assert set(report.insufficient_propositions) == {"P1", "P2"}


def test_invalid_hash_and_invalid_ids_fail_closed():
    with pytest.raises(ValueError, match="content_hash"):
        LiteraturePosition(
            source_id="S1",
            proposition_id="P1",
            position_id="SUPPORT",
            position_text="x",
            independence_key="family:S1",
            content_hash="not-a-sha",
            evidence_ref="S1:p1",
        ).normalized()
    with pytest.raises(ValueError, match="source_id"):
        _pos("bad id with spaces", "SUPPORT").normalized()


def test_report_hash_is_deterministic_under_input_order_changes():
    rows = [_pos("S1", "SUPPORT"), _pos("S2", "CHALLENGE"), _pos("S3", "SUPPORT")]
    first = debate_literature(rows)
    second = debate_literature(list(reversed(rows)))
    assert first.report_hash == second.report_hash
    assert [d.report_hash for d in first.debates] == [d.report_hash for d in second.debates]


def test_serialized_report_keeps_epistemic_boundaries_explicit():
    payload = report_to_dict(debate_literature([
        _pos("S1", "SUPPORT"),
        _pos("S2", "CHALLENGE"),
    ]))
    assert payload["consensus_proves_truth"] is False
    assert payload["truth_proven"] is False
    assert payload["independent_validation_proven"] is False
    debate = payload["debates"][0]
    assert debate["consensus_proves_truth"] is False
    assert debate["truth_proven"] is False
    assert debate["independent_validation_proven"] is False
    assert debate["cross_examinations"][0]["answer_known"] is False
