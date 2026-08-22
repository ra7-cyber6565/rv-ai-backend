"""Independent tests for the user's human-first final-answer contract.

These tests intentionally do not depend on Gemini/network. They protect the
453-line presentation requirements from future regressions.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.answer_order import (LAB_HEADING,  # noqa: E402
                                          canonical_key, display_heading)
from research_engine.models import EvidencePack, SourceRecord  # noqa: E402
from research_engine.models import SourceType  # noqa: E402
from research_engine.synthesizer import (EMIT_ORDER,  # noqa: E402
                                         FinalSynthesizer, SECTION_TITLES)

# §12 (2026-08-22) — ye list ab HARD-CODED nahi hai.
#
# Pehle yahan purani Hinglish heading likhi thi ("Research se kya pata chala?",
# "Humari Hypotheses", …) aur aakhir mein "Sources phir audit" tha. §12 ne dono
# baatein jaan-boojh kar badli hain: heading ab dual hai (canonical naam + "—" +
# Hinglish) aur mandatory order mein audit Sources se PEHLE aata hai. Is list ko
# `answer_order` se banane ka matlab hai ki heading ka wording badalne par test
# jhoothi fail nahi dega, lekin section ki PEHCHAN aur kram par sakhti waisi hi
# rehti hai.
#
# Index = section ki pehchan (SECTION_TITLES ka index), chhapne ka kram
# `EMIT_ORDER` tay karta hai. Index 2 aur 6 §12 ki 10-section list ke bahar ke
# "extra" section hain, isliye unke naam yahan literal hain.
EXPECTED_ORDER = [
    display_heading("direct_answer"),            # 0
    display_heading("established_knowledge"),    # 1
    "Ye kyun hota hai?",                         # 2 (extra)
    display_heading("supporting_evidence"),      # 3
    display_heading("counterevidence"),          # 4
    LAB_HEADING,                                 # 5 (§12: bilkul yahi shabd)
    "Hypothesis ko kaise test karenge?",         # 6 (extra)
    display_heading("unknowns"),                 # 7
    display_heading("conclusion"),               # 8
    display_heading("sources"),                  # 9
    display_heading("audit"),                    # 10
]


def _source(source_id: str, level: str, *, snippet: str = "Useful research evidence") -> SourceRecord:
    s = SourceRecord(
        title=f"Source {source_id}",
        url=f"https://example.org/{source_id.lower()}",
        snippet=snippet,
        source_type=SourceType.PAPER,
        read_level=level,
        relevance_score=0.8,
        quality_score=0.8,
        peer_reviewed=True,
    )
    s.source_id = source_id
    if level == "full_text":
        s.full_text_chars = max(500, len(snippet))
    return s


def test_required_human_first_section_order_is_canonical():
    assert SECTION_TITLES == EXPECTED_ORDER
    assert SECTION_TITLES[0] == "Seedha jawab"
    # §12 — app ki apni soch ka naam shabd-ba-shabd yahi rehna chahiye.
    assert SECTION_TITLES[5] == "APP ORIGINAL RESEARCH LAB"
    # §12 ka mandatory tail: pehle audit, PHIR Sources.
    #
    # JAAN-BOOJH KAR BADLA GAYA: pehle ye assert `SECTION_TITLES[-2:] ==
    # ["Sources", "Research quality / technical audit"]` tha, yaani "Sources
    # phir audit" — jo §12 se ULTA hai. Ab list ka index sirf pehchan hai, kram
    # `EMIT_ORDER` batata hai, isliye check bhi wahin se hota hai.
    tail = [canonical_key(SECTION_TITLES[i]) for i in EMIT_ORDER[-2:]]
    assert tail == ["audit", "sources"], tail
    # har mandatory section theek ek baar emit hona chahiye
    assert len(EMIT_ORDER) == len(SECTION_TITLES)
    assert sorted(EMIT_ORDER) == list(range(len(SECTION_TITLES)))


def test_prompt_explicitly_keeps_internal_technical_junk_out_of_main_answer():
    synth = FinalSynthesizer()
    pack = EvidencePack(question="test", sources=[_source("S1", "abstract")])
    prompt = synth.prompt(
        question="test question",
        analysis="internal analysis",
        critique="",
        hypothesis_text="",
        pack=pack,
        plan={"relevant_fields": ["science"]},
    ).lower()
    for required in (
        "seedha jawab",
        "pipeline",
        "connector",
        "[pass]",
        "[fail]",
        "technical",
        "simple example",
    ):
        assert required in prompt
    assert "system ka andar ka kaam mat likho" in prompt


def test_hypothesis_template_explains_every_required_user_facing_part():
    synth = FinalSynthesizer()
    source = _source("S1", "full_text", snippet="AI signal optimization reduced waiting time.")
    pack = EvidencePack(question="traffic", sources=[source])
    hypothesis = {
        "statement": "Integrated AI traffic control may reduce congestion.",
        "simple": "AI signals aur public transport ko saath optimize kare.",
        "reasoning": "Different transport parts affect each other.",
        "supporting_evidence": ["S1"],
        "contradicting_evidence": ["S1"],
        "risks": ["Bad sensor data"],
        "assumptions": ["Sensors reliable hain"],
        "how_to_test": ["A/B city corridor trial"],
        "prediction": {
            "variables": ["waiting time"],
            "expected_outcome": "waiting time ghatni chahiye",
            "measurement_method": "before/after sensors",
            "falsification_condition": "waiting time same ya zyada rahe",
        },
        "if_true": ["system ko scale kiya ja sakta hai"],
        "if_false": ["signal-only approach reject hogi"],
        "status": "UNTESTED HYPOTHESIS",
        "confidence_reasoning_based": "moderate",
    }
    text = synth._hypothesis_section([hypothesis], pack=pack)
    for phrase in (
        "Simple words mein:",
        "Is idea ko support karne wali research:",
        "Iske against evidence:",
        "Problem / risk:",
        "Humari assumption:",
        "Isko test kaise karenge:",
        "Agar ye sahi hua:",
        "Agar ye galat hua:",
        "Current status: UNTESTED",
    ):
        assert phrase in text


def test_large_pdf_selected_pages_are_never_called_whole_document_read():
    synth = FinalSynthesizer()
    source = _source("S1", "full_text", snippet="Relevant page excerpt about superconductivity.")
    source.pages_read = 7
    source.pages_total = 300
    source.read_note = "300 pages mein se 7 relevant pages process hue."
    pack = EvidencePack(question="superconductivity", sources=[source])

    source_text = synth._sources_section(pack, honesty={"cited": [{"source_id": "S1"}]})
    # §9 (2026-08-22) — access-depth ka vocabulary ab sirf paanch label ka hai
    # (`models.ACCESS_DEPTH_LABELS`). "PARTIAL FULL-TEXT REVIEW" jaan-boojh kar
    # hataya gaya tha, kyunki wo wording "full-text review ho gaya" ka bhram
    # deti thi. Chune hue pages ka sach ab `RELEVANT SECTIONS REVIEWED` kehta
    # hai. Rule waisa hi sakht hai: poore document ka dava kabhi nahi.
    assert "RELEVANT SECTIONS REVIEWED" in source_text
    assert "7/300" in source_text
    assert "poora document nahi" in source_text
    assert "FULL TEXT ACCESSED" not in source_text
    assert "poora document padha gaya" not in source_text

    access_text = synth._access_block({"read_levels": {"full_text": 1}}, pack)
    assert "7/300" in access_text
    assert "poora document ek saath nahi" in access_text
    assert "claim verification alag A-E check" in access_text


def test_full_text_access_does_not_automatically_claim_entailment_verified():
    synth = FinalSynthesizer()
    source = _source("S1", "full_text")
    pack = EvidencePack(question="test", sources=[source])
    text = synth._sources_section(pack)
    # §9 — label sirf ACCESS ki baat karta hai. Pehle yahan
    # "FULL-TEXT VERIFIED ACCESS" expect hota tha; us naam mein "VERIFIED"
    # shabd hi §8 ka rule todta hai (access ≠ claim verification), isliye label
    # ka naam badla gaya. Verification wali baat neeche `_access_block()` mein
    # rehti hai, aur wahi is test ke doosre hisse mein check hoti hai.
    assert "FULL TEXT ACCESSED" in text
    assert "VERIFIED" not in text
    access = synth._access_block({"read_levels": {"full_text": 1}}, pack)
    assert "claim verification alag A-E check" in access
    assert "automatically verified nahi" in access


def test_abstract_snippet_metadata_access_labels_remain_explicit():
    synth = FinalSynthesizer()
    sources = [
        _source("S1", "abstract"),
        _source("S2", "snippet"),
        _source("S3", "metadata", snippet=""),
    ]
    pack = EvidencePack(question="test", sources=sources)
    text = synth._sources_section(pack)
    # §9 — "ABSTRACT REVIEWED" hataya gaya: "reviewed" se lagta tha ki paper
    # padh kar jaancha gaya. Ab saaf hai ki sirf abstract mila.
    assert "ABSTRACT ONLY" in text
    assert "SNIPPET ONLY" in text
    assert "METADATA ONLY" in text


def test_human_readable_audit_does_not_dump_pass_fail_tokens():
    synth = FinalSynthesizer()
    verification = {
        "status": "UNVERIFIABLE HERE",
        "checks": [
            {"check": "Claim cited text/excerpt se support hoti hai", "passed": False,
             "detail": "claim aur cited excerpt ka support match nahi hua"},
            {"check": "Cited source sawal se relevant hai", "passed": True,
             "detail": "relevance check pass hua"},
        ],
    }
    text = synth._numbers_check(verification)
    assert "[PASS]" not in text
    assert "[FAIL]" not in text
    assert "problem" in text.lower()


def test_access_depth_text_never_equates_full_text_with_automatic_claim_verification():
    synth = FinalSynthesizer()
    pack = EvidencePack(question="test", sources=[_source("S1", "full_text")])
    text = synth._access_block({"read_levels": {"full_text": 1}}, pack).lower()
    assert "automatically verified nahi" in text


def main() -> int:
    """
    Direct runner (2026-08-22).

    Is file ke saare test pytest-style function the aur sandbox mein pytest
    available nahi hai — `python3 tests/test_user_presentation_contract.py`
    chup-chaap exit 0 de deta tha. Yaani "test pass ho gaya" aur "test chala hi
    nahi" ek jaise dikhte the, aur is file ke 4 asli failure kaafi der tak
    chhupe rahe. Ab direct chalane par bhi sach dikhta hai.
    """
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except AssertionError as exc:                  # noqa: PERF203
            failed += 1
            print(f"  [FAIL] {name} -> {exc}")
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {name} -> {type(exc).__name__}: {exc}")
        else:
            print(f"  [PASS] {name}")
    print(f"\n{'FAIL' if failed else 'ok'} — {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
