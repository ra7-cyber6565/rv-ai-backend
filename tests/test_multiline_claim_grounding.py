"""Regression coverage for bounded multiline claim/citation grounding.

The model may wrap one labelled claim across Markdown lines.  A citation on a
continuation line must count for that claim, while a citation in the next
bullet, section, or an unbounded distant line must never be borrowed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import claim_verification as claim_checks
from research_engine.citation import (
    CITATION_INSTRUCTION,
    CitationEngine,
    labelled_claim_spans,
)
from research_engine.claim_labels import downgrade
from research_engine.evidence import EvidenceEngine
from research_engine.evidence_verification import EvidenceVerifier
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


CLAIM = "Higher urban density reduces per-capita car travel in the studied cities."
SUPPORT = (CLAIM + " The result remained after adjustment for household income. ") * 3


def _pack() -> EvidencePack:
    source = SourceRecord(
        title="Urban density and car travel",
        url="https://example.org/density",
        snippet=SUPPORT,
        source_type=SourceType.PAPER,
        peer_reviewed=True,
        read_level="full_text",
        full_text_chars=len(SUPPORT),
        relevance_score=0.9,
        quality_score=0.8,
        source_id="S1",
    )
    pack = EvidencePack(
        question="Does higher urban density reduce per-capita car travel?",
        sources=[source],
        topic_terms=["urban", "density", "car", "travel"],
    )
    # Production full-text readers persist an exact Passage with capture-time
    # provenance; a SourceRecord display snippet alone is not A-E proof.
    pack.passages = [Passage(
        source_id="S1", text=SUPPORT, locator="Fixture section 1",
        provenance="full_text_fixture", read_level_at_capture="full_text",
    )]
    return pack


def test_claim_span_accepts_a_nearby_continuation_citation():
    answer = f"- [FACT] {CLAIM}\n  [S1]"
    spans = labelled_claim_spans(answer)
    assert spans == [(0, 2, answer)]

    claims = CitationEngine().extract_claims(answer, _pack())
    assert len(claims) == 1
    assert claims[0].source_ids == ["S1"]
    assert CLAIM.rstrip(".") in claims[0].text


def test_next_markdown_bullet_citation_is_never_borrowed():
    answer = (
        f"- [FACT] {CLAIM}\n"
        "- Background reading only; this is a separate bullet [S1]"
    )
    spans = labelled_claim_spans(answer)
    assert spans[0][0:2] == (0, 1)

    engine = CitationEngine()
    claims = engine.extract_claims(answer, _pack())
    assert claims[0].source_ids == []
    assert len(engine.find_ungrounded_claims(answer)) == 1


def test_heading_and_continuation_cap_prevent_distant_citation_bleed():
    heading_answer = f"[FACT] {CLAIM}\n## Sources\n[S1]"
    assert labelled_claim_spans(heading_answer)[0][0:2] == (0, 1)

    capped_answer = "\n".join([
        f"[FACT] {CLAIM}",
        "continuation one",
        "continuation two",
        "continuation three",
        "continuation four",
        "continuation five",
        "[S1]",
    ])
    assert labelled_claim_spans(capped_answer)[0][0:2] == (0, 6)
    assert CitationEngine().extract_claims(capped_answer, _pack())[0].source_ids == []


def test_ungrounded_report_uses_the_same_claim_block_rule():
    grounded = f"- [EVIDENCE] {CLAIM}\n  Evidence source: [S1]"
    ungrounded = f"- [EVIDENCE] {CLAIM}\n  Explanation without a source."
    engine = CitationEngine()
    assert engine.find_ungrounded_claims(grounded) == []
    assert len(engine.find_ungrounded_claims(ungrounded)) == 1


def test_both_AE_verifiers_accept_the_same_multiline_claim():
    answer = f"- [FACT] {CLAIM}\n  [S1]"
    pack = _pack()

    detailed = claim_checks.verify_answer(answer, pack)
    assert detailed.total == 1
    assert detailed.claims[0].passes_ae is True
    assert detailed.claims[0].canonical_span["span_kind"] == "passage"
    assert detailed.to_dict()["gate_passed"] is True

    release = EvidenceVerifier().verify(answer, pack)
    assert release.claims_checked == 1
    assert release.passed_claims == 1
    assert release.gate_passed is True


def test_label_gate_uses_continuation_citation_without_changing_layout():
    answer = f"- [FACT] {CLAIM}\n  [S1]\nNormal explanation remains unchanged."
    output, report = downgrade(answer, _pack(), check_entailment=True)
    assert output == answer
    assert report["checked"] == 1
    assert report["a_e_checked"] == 1
    assert report["a_e_failed"] == 0
    assert report["downgraded"] == 0


def test_label_gate_does_not_steal_citation_from_next_bullet():
    answer = (
        f"- [FACT] {CLAIM}\n"
        "- Separate background bullet [S1]"
    )
    output, report = downgrade(answer, _pack(), check_entailment=True)
    assert output.splitlines()[0].startswith("- [UNVERIFIED]")
    assert output.splitlines()[1] == "- Separate background bullet [S1]"
    assert report["to_unverified"] == 1


def test_strict_support_gate_reads_block_but_rewrites_only_first_line():
    unsupported = (
        "- [ESTABLISHED FACT] National transmission losses became exactly zero.\n"
        "  Citation used for comparison: [S1]"
    )
    output, report = claim_checks.enforce_strict_labels(unsupported, _pack())
    assert output.splitlines()[0].startswith("- [UNVERIFIED]")
    assert output.splitlines()[1] == "  Citation used for comparison: [S1]"
    assert report["checked"] == 1
    assert report["to_unverified"] == 1


def test_multiline_claims_raise_grounding_only_when_each_has_its_own_source():
    answer = "\n".join([
        f"- [SOURCE-REPORTED] {CLAIM}\n  [S1]",
        f"- [EVIDENCE] {CLAIM}\n  [S1]",
        f"- [FACT] {CLAIM}\n  [S1]",
    ])
    engine = EvidenceEngine()
    claims = engine.extract_claims(answer, _pack())
    table = engine.evidence_table(claims)
    assert table["total_claims"] == 3
    assert table["grounded_claims"] == 3
    assert table["grounded_ratio"] == 1.0


def test_prompt_contract_matches_the_parser_boundary():
    assert "usi bounded block" in CITATION_INSTRUCTION
    assert "Agle bullet" in CITATION_INSTRUCTION


def _main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not failed else f"\n{failed} test fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
