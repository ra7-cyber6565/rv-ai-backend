"""
`[ESTABLISHED]` sirf full text par — intel ka verbatim rule.

    Snippet/abstract-only evidence  →  SOURCE-REPORTED
    Full text + claim verification →  ESTABLISHED

Pichhle live run mein ek claim par `[ESTABLISHED]` tha aur usi report mein
"0/14 full-text fetch successful" likha tha. Ye test wahi jhooth pakadta hai.

Koi network, koi Gemini. Chalao:  python3 tests/test_claim_labels.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.claim_labels import (  # noqa: E402
    ESTABLISHED, LABEL_RULE_PROMPT, SOURCE_REPORTED, UNVERIFIED, downgrade,
    human_note, line_verdict,
)
from research_engine.models import EvidencePack, SourceRecord, SourceType  # noqa: E402


def _source(sid: str, level: str) -> SourceRecord:
    """
    `level` = metadata | snippet | abstract | full_text.

    `read_level` jaan-boojh kar EXPLICIT set karte hain — asli pipeline mein bhi
    ContentFetcher/EvidenceEngine yahi karte hain, aur `reading_level()` kabhi
    khud se "full_text" ka andaza nahi lagata (ye design honesty ka hissa hai).
    """
    record = SourceRecord(
        title=f"Paper {sid}", url=f"https://example.org/{sid}",
        snippet="Higher density areas show lower per-capita car travel."
                if level != "metadata" else "",
        connector="openalex", source_type=SourceType.PAPER, year=2021,
        peer_reviewed=True,
    )
    record.source_id = sid
    record.read_level = "" if level == "metadata" else level
    if level in ("abstract", "full_text"):
        record.snippet = "Ek lamba abstract. " * 20
    return record


def _pack(levels) -> EvidencePack:
    sources = [_source(sid, level) for sid, level in levels.items()]
    return EvidencePack(sources=sources, topic_terms=["density", "travel"])


def test_read_levels_are_what_we_think_they_are():
    """Baaki test isi par tike hain — pehle isko pakka karo."""
    pack = _pack({"S1": "full_text", "S2": "abstract", "S3": "snippet",
                  "S4": "metadata"})
    assert pack.by_id("S1").reading_level() == "full_text"
    assert pack.by_id("S2").reading_level() == "abstract"
    assert pack.by_id("S3").reading_level() == "snippet"
    assert pack.by_id("S4").reading_level() == "metadata"


def test_full_text_source_keeps_established():
    pack = _pack({"S1": "full_text"})
    verdict, why = line_verdict("[ESTABLISHED] Density se travel kam hota hai [S1].", pack)
    assert verdict == ESTABLISHED, (verdict, why)
    # §9 (2026-08-22): wajah mein ab wahi 5 allowed access label jaate hain jo
    # models.py tay karta hai. Pehle yahan "full text padha gaya" likha jaata
    # tha — 30 mein se 18 page wale source par wo line jhooth thi.
    assert "FULL TEXT ACCESSED" in why, why


def test_abstract_only_becomes_source_reported():
    pack = _pack({"S2": "abstract"})
    verdict, why = line_verdict("[ESTABLISHED] 30% kami hoti hai [S2].", pack)
    assert verdict == SOURCE_REPORTED, (verdict, why)
    assert "ABSTRACT ONLY" in why, why


def test_snippet_and_metadata_also_become_source_reported():
    pack = _pack({"S3": "snippet", "S4": "metadata"})
    for sid in ("S3", "S4"):
        verdict, _ = line_verdict(f"[FACT] Kuch hota hai [{sid}].", pack)
        assert verdict == SOURCE_REPORTED, sid


def test_no_citation_means_unverified():
    pack = _pack({"S1": "full_text"})
    verdict, why = line_verdict("[ESTABLISHED] Ye baat bina source ki hai.", pack)
    assert verdict == UNVERIFIED, (verdict, why)
    assert "citation" in why


def test_citation_to_missing_source_is_unverified():
    pack = _pack({"S1": "full_text"})
    verdict, why = line_verdict("[ESTABLISHED] Kuch baat [S9].", pack)
    assert verdict == UNVERIFIED, (verdict, why)
    assert "S9" in why


def test_one_full_text_source_in_the_line_is_enough():
    pack = _pack({"S1": "full_text", "S2": "snippet"})
    verdict, _ = line_verdict("[ESTABLISHED] Baat [S1][S2].", pack)
    assert verdict == ESTABLISHED


def test_downgrade_rewrites_labels_without_losing_content():
    pack = _pack({"S1": "full_text", "S2": "abstract"})
    text = ("## Seedha jawab\n"
            "[ESTABLISHED] Poora paper padha gaya wala claim [S1].\n"
            "[ESTABLISHED] Sirf abstract wala claim [S2].\n"
            "[STRONG EVIDENCE] Ye bhi sirf abstract par hai [S2].\n"
            "[INFERENCE] Ye pehle se imaandaar label hai [S1].\n"
            "Ek normal line jisme koi label nahi hai.\n")
    out, report = downgrade(text, pack)
    assert "[ESTABLISHED] Poora paper padha gaya wala claim [S1]." in out
    assert "[SOURCE-REPORTED] Sirf abstract wala claim [S2]." in out
    assert "[SOURCE-REPORTED] Ye bhi sirf abstract par hai [S2]." in out
    # content kabhi nahi kaata jaata — sirf label badalta hai
    assert "Ek normal line jisme koi label nahi hai." in out
    assert "[INFERENCE] Ye pehle se imaandaar label hai [S1]." in out
    assert len(out.splitlines()) == len(text.splitlines()), \
        "line count badalna nahi chahiye"
    assert report["checked"] == 3, report
    assert report["downgraded"] == 2, report
    assert report["to_source_reported"] == 2, report
    assert "SOURCE-REPORTED" in report["note"]


def test_downgrade_never_upgrades():
    """Honesty ek hi taraf jhukti hai — SOURCE-REPORTED ko ESTABLISHED nahi banate."""
    pack = _pack({"S1": "full_text"})
    out, report = downgrade("[SOURCE-REPORTED] Baat [S1].", pack)
    assert "[SOURCE-REPORTED]" in out
    assert "[ESTABLISHED]" not in out
    assert report["checked"] == 0 and report["downgraded"] == 0


def test_zero_full_text_run_cannot_keep_any_established():
    """Asli live failure: 0/14 full text, phir bhi [ESTABLISHED] chhap raha tha."""
    pack = _pack({f"S{i}": "abstract" for i in range(1, 6)})
    text = "\n".join(f"[ESTABLISHED] Claim {i} [S{i}]." for i in range(1, 6))
    out, report = downgrade(text, pack)
    assert "[ESTABLISHED]" not in out
    assert report["downgraded"] == 5, report


def test_empty_and_none_input_do_not_crash():
    for value in ("", None, "   "):
        out, report = downgrade(value, None)
        assert report["checked"] == 0
        assert out == (value or "")


def test_no_pack_still_refuses_established():
    out, report = downgrade("[ESTABLISHED] Baat [S1].", None)
    assert "[UNVERIFIED]" in out, out
    assert report["to_unverified"] == 1


def test_human_note_is_human_not_a_log():
    pack = _pack({"S2": "abstract"})
    _, report = downgrade("[ESTABLISHED] Baat [S2].", pack)
    note = human_note(report)
    for bad in ("[FAIL]", "[PASS]", "downgrade(", "None", "{"):
        assert bad not in note, bad
    assert "SOURCE-REPORTED" in note and "ESTABLISHED" in note
    # kuch downgrade na hua ho to bhi ek saaf line aani chahiye
    clean = human_note({"checked": 0})
    assert "zaroorat nahi padi" in clean


def test_prompt_rule_states_both_halves_of_the_rule():
    assert "ESTABLISHED" in LABEL_RULE_PROMPT
    assert "SOURCE-REPORTED" in LABEL_RULE_PROMPT
    assert "full_text" in LABEL_RULE_PROMPT
    assert "abstract/snippet/metadata" in LABEL_RULE_PROMPT


def test_synthesis_prompt_carries_the_label_rule():
    """Rule ko model tak pahunchna bhi chahiye, sirf safety net nahi."""
    from research_engine.synthesizer import FinalSynthesizer

    pack = _pack({"S1": "abstract"})
    prompt = FinalSynthesizer().prompt("density ka asar?", "analysis", "", "",
                                       pack, {"relevant_fields": ["Urban"]})
    assert "LABEL RULE" in prompt
    assert "SOURCE-REPORTED" in prompt


def _main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                 # noqa: BLE001
            failed += 1
            print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not failed else f"\n{failed} test fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
