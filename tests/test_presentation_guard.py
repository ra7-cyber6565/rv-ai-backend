"""Offline tests for deterministic A-L presentation guard."""
from __future__ import annotations

from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.presentation_guard import PresentationGuard


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
    pack = EvidencePack(question="test question", sources=[source])
    pack.reasoning_complete = complete
    return pack


def _complete_report(seedha: str = "Chhota jawab.") -> str:
    return f"""## Seedha jawab

{seedha}

[FAIL] internal numeric consistency raw line
https://bad.example/raw-link

## Research se kya pata chala?

### Fact — jo research se already support hota hai
Research evidence se main result support hota hai. Inference sources ko jodne par nikalti hai aur hypothesis abhi test hona baaki hai.

## Ye kyun hota hai?

Simple example se samjho: system ke do parts ek dusre ko affect karte hain, isliye result badalta hai.

## Evidence kya kehta hai?

Evidence support karta hai, lekin source access aur claim verification alag checks hain.

## Iske against kya mila?

Kuch evidence opposite direction suggest karta hai, isliye limitation samajhna important hai.

## Humari Hypotheses

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

## Final conclusion

उपलब्ध साक्ष्यों के आधार पर result promising hai, lekin limitation aur uncertainty abhi bhi hai.

## Sources

S1 — relevant paper; ABSTRACT REVIEWED.

## Research quality / technical audit

Sources aur numbers ki checking human-readable form mein neeche hai.
"""


def test_guard_moves_raw_technical_junk_out_of_main_and_keeps_it_in_audit_tail():
    text, audit = PresentationGuard().enforce(
        _complete_report(),
        pack=_pack(),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "COMPLETE"},
    )
    main = text.split("## Sources", 1)[0]
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
    assert "## Kya abhi unknown hai?" in text
    assert any("formal Hindi" in repair for repair in audit.repairs)
    assert any("unknown/limitations" in repair for repair in audit.repairs)


def test_guard_strengthens_thin_seedha_only_from_existing_report_sections():
    text, audit = PresentationGuard().enforce(
        _complete_report(seedha="Bas itna."),
        pack=_pack(),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "COMPLETE"},
    )
    seedha = text.split("## Research se kya pata chala?", 1)[0]
    assert "Research evidence se main result support hota hai" in seedha
    assert len(seedha) > 240
    assert any("Seedha jawab strengthened" in repair for repair in audit.repairs)


def test_incomplete_run_must_say_it_is_not_complete_or_preliminary():
    text, audit = PresentationGuard().enforce(
        _complete_report(seedha="Detailed research result evidence aur uncertainty ke saath explain kiya gaya hai."),
        pack=_pack(complete=False),
        hypotheses=[{"statement": "test idea"}],
        status={"status": "RESEARCH INCOMPLETE"},
    )
    # The guard audits honesty rather than fabricating a completion statement.
    assert audit.checks["J_incomplete_run_not_called_verified"] is False


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
