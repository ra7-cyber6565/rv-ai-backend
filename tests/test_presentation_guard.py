"""Offline tests for deterministic A-L presentation guard."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.answer_order import LAB_WARNING, display_heading  # noqa: E402
from research_engine.models import (EvidencePack, SourceRecord,  # noqa: E402
                                    SourceType)
from research_engine.presentation_guard import PresentationGuard  # noqa: E402
from research_engine.synthesizer import FinalSynthesizer  # noqa: E402

# §12 (2026-08-22) — fixture ki heading ab canonical hain, hard-coded nahi.
# Pehle yahan purani Hinglish heading likhi thi ("## Research se kya pata
# chala?", "## Humari Hypotheses") aur aakhir mein Sources phir audit tha, jo
# §12 ke mandatory order se ULTA hai. Guard ke check ab canonical key se section
# dhoondhte hain, isliye fixture ko bhi wahi sach dikhana chahiye — warna test
# ek aise report par pass hota rehta jo app kabhi banati hi nahi.
H_DIRECT = display_heading("direct_answer")
H_ESTABLISHED = display_heading("established_knowledge")
H_SUPPORT = display_heading("supporting_evidence")
H_AGAINST = display_heading("counterevidence")
H_LAB = display_heading("original_lab")
H_CONCLUSION = display_heading("conclusion")
H_AUDIT = display_heading("audit")
H_SOURCES = display_heading("sources")


def _pack(*, complete: bool = True) -> EvidencePack:
    source = SourceRecord(
        title="Relevant paper",
        url="https://example.org/paper",
        snippet="Research evidence supports the result.",
        source_type=SourceType.PAPER,
        read_level="abstract",
        relevance_score=0.8,
        quality_score=0.8,
    )
    source.source_id = "S1"
    return EvidencePack(
        question="test question",
        sources=[source],
        reasoning_planned=1,
        reasoning_done=1 if complete else 0,
    )


def _complete_report(seedha: str = "Chhota jawab.") -> str:
    return f"""## {H_DIRECT}

{seedha}

[FAIL] internal numeric consistency raw line
https://bad.example/raw-link

## {H_ESTABLISHED}

### Fact — jo research se already support hota hai
Research evidence se main result support hota hai. Inference sources ko jodne par nikalti hai aur hypothesis abhi test hona baaki hai.

## Ye kyun hota hai?

Simple example se samjho: system ke do parts ek dusre ko affect karte hain, isliye result badalta hai.

## {H_SUPPORT}

Evidence support karta hai, lekin source access aur claim verification alag checks hain.

## {H_AGAINST}

Kuch evidence opposite direction suggest karta hai, isliye limitation samajhna important hai.

## {H_LAB}

{LAB_WARNING}

### Hypothesis 1 — test idea
**Simple words mein:** ek possible idea.
**Is idea ko support karne wali research:** S1.
**Iske against evidence:** weak counter-evidence.
**Problem / risk:** noisy data.
**Humari assumption:** measurement reliable hai.
**Isko test kaise karenge:** controlled experiment.
**Agar ye sahi hua:** prediction match hogi.
**Agar ye galat hua:** prediction fail hogi.
**Current status: UNTESTED HYPOTHESIS**

## Hypothesis ko kaise test karenge?

Controlled experiment aur independent replication se test karenge.

## {H_CONCLUSION}

उपलब्ध साक्ष्यों के आधार पर result promising hai, lekin limitation aur uncertainty abhi bhi hai.

## {H_AUDIT}

Sources aur numbers ki checking human-readable form mein neeche hai.

## {H_SOURCES}

S1 — relevant paper; ABSTRACT ONLY.
"""


def test_guard_moves_raw_technical_junk_out_of_main_and_keeps_it_in_audit_tail():
    text, audit = PresentationGuard().enforce(
        _complete_report(),
        pack=_pack(),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "COMPLETE"},
    )
    main = text.split(f"## {H_AUDIT}", 1)[0]
    assert "[FAIL]" not in main
    assert "internal numeric consistency" not in main
    assert "https://bad.example" not in main
    assert "Technical details jo main answer se neeche move kiye gaye" in text
    assert any("technical/raw" in repair for repair in audit.repairs)


def test_guard_simplifies_formal_hindi_and_adds_missing_unknown_section():
    text, audit = PresentationGuard().enforce(
        _complete_report(),
        pack=_pack(),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "COMPLETE"},
    )
    assert "उपलब्ध साक्ष्यों के आधार पर" not in text
    assert "jo evidence mila hai uske basis par" in text
    assert f"## {display_heading('unknowns')}" in text
    assert any("formal Hindi" in repair for repair in audit.repairs)
    assert any("unknown/limitations" in repair for repair in audit.repairs)


def test_guard_strengthens_thin_seedha_only_from_existing_report_sections():
    text, audit = PresentationGuard().enforce(
        _complete_report(seedha="Bas itna."),
        pack=_pack(),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "COMPLETE"},
    )
    seedha = text.split(f"## {H_ESTABLISHED}", 1)[0]
    assert "Research evidence se main result support hota hai" in seedha
    assert len(seedha) > 240
    assert any("Seedha jawab strengthened" in repair for repair in audit.repairs)


def test_incomplete_run_is_detected_and_synthesizer_has_truthful_rewrite():
    text, audit = PresentationGuard().enforce(
        _complete_report(seedha="Detailed research result evidence aur uncertainty ke saath explain kiya gaya hai."),
        pack=_pack(complete=False),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "RESEARCH INCOMPLETE"},
    )
    assert audit.checks["J_incomplete_run_not_called_verified"] is False
    repaired = FinalSynthesizer._repair_incomplete_honesty(text)
    assert "Ye research run complete nahi hua" in repaired
    assert "preliminary" in repaired
    assert "fully verified final conclusion nahi" in repaired


def test_A_to_L_checklist_is_exposed_internally_not_as_user_log():
    text, audit = PresentationGuard().enforce(
        _complete_report(
            seedha=(
                "Research se jo result mila uska simple meaning ye hai ki evidence ek direction dikhata hai, "
                "lekin against evidence aur uncertainty bhi hai. Hypothesis ek possible testable idea hai; "
                "next step controlled test aur source verification hai."
            )
        ),
        pack=_pack(),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "COMPLETE"},
    )
    assert len(audit.checks) == 12
    assert set(key[0] for key in audit.checks) == set("ABCDEFGHIJKL")
    assert "A_main_conclusion_understandable" in audit.checks
    assert "L_first_section_gives_useful_picture" in audit.checks
    assert "A_main_conclusion_understandable" not in text


# ── §12 ke naye case (2026-08-22) ───────────────────────────────────────────

_RICH_SEEDHA = (
    "Research se jo result mila uska simple meaning ye hai ki evidence ek direction dikhata hai, "
    "lekin against evidence aur uncertainty bhi hai. Hypothesis ek possible testable idea hai; "
    "next step controlled test aur source verification hai."
)


def _audit_of(report: str, **kwargs):
    # `or` se default nahi lagate: khaali list ek asli case hai ("koi hypothesis
    # nahi"), aur `[] or default` chup-chaap default le aata tha.
    hypotheses = kwargs["hypotheses"] if "hypotheses" in kwargs \
        else [{"statement": "test idea"}]
    _, audit = PresentationGuard().enforce(
        report,
        pack=kwargs.get("pack") or _pack(),
        hypotheses=hypotheses,
        status=kwargs.get("status") or {"status": "COMPLETE"},
    )
    return audit


def test_check_I_wants_audit_then_sources_as_the_last_two_sections():
    """
    §12 ka mandatory order: aakhir mein pehle audit, phir Sources.

    Ye check JAAN-BOOJH KAR badla gaya hai. Pehle guard "Sources phir audit"
    maangta tha aur heading ka poora literal naam match karta tha — dual heading
    ("Audit and limits — research quality aur technical audit") aane ke baad wo
    chup-chaap False deta tha, yaani ek asli check mar chuka tha aur kisi ko
    pata nahi chalta.
    """
    good = _audit_of(_complete_report(seedha=_RICH_SEEDHA))
    assert good.checks["I_sources_and_audit_last"] is True

    # ulta kram (purani report) — check ko pakadna chahiye
    flipped = _complete_report(seedha=_RICH_SEEDHA).replace(
        f"## {H_AUDIT}", "@@AUDIT@@").replace(
        f"## {H_SOURCES}", f"## {H_AUDIT}").replace(
        "@@AUDIT@@", f"## {H_SOURCES}")
    assert _audit_of(flipped).checks["I_sources_and_audit_last"] is False

    # Sources ke BAAD ek aur section — bhi fail hona chahiye
    trailing = _complete_report(seedha=_RICH_SEEDHA) + "\n## Ek aur section\n\nkuch bhi\n"
    assert _audit_of(trailing).checks["I_sources_and_audit_last"] is False


def test_check_E_needs_the_app_original_research_lab_warning():
    """App ki apni soch par warning na ho to E pass nahi hona chahiye."""
    with_warning = _audit_of(_complete_report(seedha=_RICH_SEEDHA))
    assert with_warning.checks["E_hypotheses_explained"] is True

    stripped = _complete_report(seedha=_RICH_SEEDHA).replace(LAB_WARNING, "")
    assert _audit_of(stripped).checks["E_hypotheses_explained"] is False

    # hypotheses hi na ho to ye check lagoo nahi hota (jhoothi fail nahi)
    assert _audit_of(stripped, hypotheses=[]).checks["E_hypotheses_explained"] is True


def test_old_hinglish_headings_still_recognised_by_canonical_key():
    """
    Purani report (heading ka purana wording) par bhi guard ke check chalte hain.

    Section ki pehchaan ab canonical key se hoti hai, literal string se nahi —
    isliye heading ka shabd badalne par F/I/K jaise check bina wajah fail nahi
    hote, aur purani saved report bhi theek se padhi jaati hai.
    """
    old = (_complete_report(seedha=_RICH_SEEDHA)
           .replace(f"## {H_ESTABLISHED}", "## Research se kya pata chala?")
           .replace(f"## {H_SUPPORT}", "## Evidence kya kehta hai?")
           .replace(f"## {H_AGAINST}", "## Iske against kya mila?")
           .replace(f"## {H_LAB}", "## Humari Hypotheses")
           .replace(f"## {H_CONCLUSION}", "## Final conclusion")
           .replace(f"## {H_AUDIT}", "## Research quality / technical audit"))
    audit = _audit_of(old)
    for key in ("E_hypotheses_explained", "F_support_and_opposition_explained",
                "I_sources_and_audit_last", "K_limitations_simple"):
        assert audit.checks[key] is True, key


def main() -> int:
    """
    Direct runner (2026-08-22).

    Is file ke saare test pytest-style function the aur sandbox mein pytest
    available nahi hai — `python3 tests/test_presentation_guard.py` chup-chaap
    exit 0 de deta tha. "Test pass ho gaya" aur "test chala hi nahi" ek jaise
    dikh rahe the. Ab direct chalane par bhi sach dikhta hai.
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
