"""Regression for numeric entailment: exact numbers cannot replace semantic support."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import claim_verification as CV
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


CLAIM = (
    "[ESTABLISHED FACT] Lanthanum hydride LaH10 shows superconductivity at "
    "250 K under 170 GPa pressure [S1]"
)

# Every number from the claim is present: 10, 250, 170.  The subject is still
# completely unrelated. Numeric identity alone must never make C pass.
ALL_NUMBER_SPOOF = (
    "A botanical reserve divided plot 10 into 250 survey transects and recorded "
    "a ridge elevation of 170 metres. Field workers catalogued moss, leaf shape, "
    "soil moisture, flowering time, rainfall, herbarium vouchers, and seasonal "
    "canopy cover. The report contains no superconductivity, hydride, pressure, "
    "electrical resistance, magnetic susceptibility, or phase-transition study."
)

REAL_SUPPORT = (
    "Electrical resistance and magnetic susceptibility measurements show that "
    "lanthanum hydride LaH10 becomes superconducting near 250 K at about 170 GPa "
    "pressure. The transition was reproduced across the reported high-pressure "
    "measurements and is discussed as the superconducting phase of LaH10."
)


def _source(text: str) -> SourceRecord:
    return SourceRecord(
        title="Fixture S1",
        url="https://example.org/s1",
        snippet="",
        source_type=SourceType.PAPER,
        connector="fixture",
        read_level="full_text",
        full_text_chars=40000,
        peer_reviewed=True,
        quality_score=0.90,
        relevance_score=0.90,
        source_id="S1",
    )


def _pack(text: str) -> EvidencePack:
    source = _source(text)
    pack = EvidencePack(question=CLAIM, sources=[source])
    pack.passages = [Passage(
        source_id="S1",
        text=text,
        locator="p.7",
        provenance="full_text_excerpt",
        read_level_at_capture="full_text",
    )]
    return pack


def test_all_claim_numbers_matching_unrelated_text_still_fails_c():
    body = CV.claim_body(CLAIM)
    wanted = CV._numbers(body)
    assert wanted
    low = ALL_NUMBER_SPOOF.lower()
    assert all(number in low for number in wanted), (wanted, ALL_NUMBER_SPOOF)

    span = {"source_id": "S1", "locator": "p.7", "passage": ALL_NUMBER_SPOOF}
    # Nonnumeric subject overlap is intentionally below the relaxed semantic floor.
    stripped_claim = CV._NUM_RE.sub(" ", body)
    stripped_span = CV._NUM_RE.sub(" ", ALL_NUMBER_SPOOF)
    assert CV._similarity(stripped_claim, stripped_span) < CV._ENTAIL_SIM_WITH_NUM
    assert CV.check_c_span(CLAIM, span).status == CV.FAIL


def test_all_number_spoof_cannot_create_same_source_ae_support():
    checked = CV.verify_claim(
        CLAIM, _pack(ALL_NUMBER_SPOOF), claim_id="CL001", critical=True,
        section="direct_answer",
    )
    assert checked.status("C") == CV.FAIL
    assert checked.passes_ae is False
    assert checked.verdict != CV.GENUINE_SUPPORT
    assert checked.supporting_source_id == ""


def test_real_numeric_support_remains_supported():
    checked = CV.verify_claim(
        CLAIM, _pack(REAL_SUPPORT), claim_id="CL001", critical=True,
        section="direct_answer",
    )
    assert checked.status("C") == CV.PASS
    assert checked.passes_ae is True
    assert checked.verdict == CV.GENUINE_SUPPORT
    assert checked.supporting_source_id == "S1"


def test_entailment_and_quality_floors_are_not_weakened():
    assert CV._ENTAIL_SIM == 0.30
    assert CV._ENTAIL_SIM_WITH_NUM == 0.12
    assert CV._MIN_TEXT_CHARS == 120
    assert CV._MIN_RELEVANCE == 0.25
    assert CV._MIN_QUALITY == 0.35
    assert CV._LOW_QUALITY == 0.20


def main() -> int:
    tests = [
        test_all_claim_numbers_matching_unrelated_text_still_fails_c,
        test_all_number_spoof_cannot_create_same_source_ae_support,
        test_real_numeric_support_remains_supported,
        test_entailment_and_quality_floors_are_not_weakened,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"[PASS] {test.__name__}")
        except Exception as exc:  # pragma: no cover - direct harness
            failed += 1
            print(f"[FAIL] {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
