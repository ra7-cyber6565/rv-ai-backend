"""
Bhasha mirror + plain-language rules ka offline test.

Kyun ye test hai: purane synthesis prompt mein "write in simple, conversational
Hindi/Hinglish" HARD-CODED tha. Matlab English mein poochhne wale user ko bhi
Hinglish jawab milta (aur QUICK chat isse alag behave karta tha). Saath hi
"simple language" bola jaata tha par simple ka MATLAB nahi bataya jaata tha.

Do cheezein pakadni hain:
    1. detect_language() Hindi / Hinglish / English theek pehchane.
    2. Har Gemini prompt (analysis, synthesis, critic) mein bhasha rule +
       samjhane ka tarika jaaye — aur headings ka "translate mat karo" rule bhi,
       kyunki synthesizer/critic apne output ko HEADING ke naam se parse karte
       hain. Heading badli to poora section chup-chaap gum ho jaata hai.

Koi network, koi Gemini, koi API key nahi.

Chalao:  python3 tests/test_explain_style.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.critic import Critic  # noqa: E402
from research_engine.explain_style import (  # noqa: E402
    detect_language, language_rule, style_block,
)
from research_engine.gemini_reasoning import GeminiReasoning  # noqa: E402
from research_engine.models import EvidencePack, SourceRecord, SourceType  # noqa: E402
from research_engine.synthesizer import SECTION_TITLES, FinalSynthesizer  # noqa: E402

HINDI = "मधुमेह में रुक-रुक कर उपवास करने से क्या असर पड़ता है?"
HINDI_MIXED = ("मान लो एक ऐसी energy technology चाहिए जो nuclear, solar और "
               "battery से कई गुना efficient हो")
HINGLISH = "diabetes me intermittent fasting ka kya asar hota hai bhai, smjao"
HINGLISH_SHORT = "cancer ki nai dawa par research kya kehti h"
ENGLISH = "What does the research say about intermittent fasting and type 2 diabetes?"
ENGLISH_TECH = "Explain how solid-state batteries improve energy density"


def test_devanagari_is_hindi():
    assert detect_language(HINDI) == "hindi"
    # Technical shabd angrezi mein hone par bhi sawaal Hindi ka hai
    assert detect_language(HINDI_MIXED) == "hindi"


def test_roman_hindi_is_hinglish():
    assert detect_language(HINGLISH) == "hinglish"
    assert detect_language(HINGLISH_SHORT) == "hinglish"


def test_plain_english_is_english():
    assert detect_language(ENGLISH) == "english"
    assert detect_language(ENGLISH_TECH) == "english"


def test_empty_question_does_not_crash():
    for value in ("", None, "   ", "12345", "???"):
        assert detect_language(value) in ("hindi", "hinglish", "english")


def test_language_rule_says_the_right_language():
    assert "Devanagari" in language_rule(HINDI)
    hing = language_rule(HINGLISH)
    assert "Hinglish" in hing and "Devanagari mat use karo" in hing
    eng = language_rule(ENGLISH)
    assert "ENGLISH" in eng
    # English sawaal par Hinglish par SWITCH karna mana ho — ye wahi bug tha
    assert "Do not switch to Hindi or Hinglish" in eng


def test_spelling_is_never_corrected():
    """User ki shorthand par comment karna mana hai — ye standing rule hai."""
    rule = language_rule(HINGLISH_SHORT)
    assert "spelling" in rule and "theek" in rule


def test_style_block_defines_what_simple_means():
    block = style_block(HINGLISH)
    for must in ("SEEDHA jawab", "bracket", "example", "vaakya"):
        assert must in block, must


def test_style_block_protects_headings():
    block = style_block(HINDI, SECTION_TITLES)
    assert "HEADINGS" in block
    assert SECTION_TITLES[0] in block
    assert "translate" in block


def test_hinglish_gets_everyday_word_rules():
    """§2: kitaabi/Sanskritized Hindi ban, aur GALAT->SAHI jodiyan prompt mein."""
    block = style_block(HINGLISH)
    assert "SHABDON KA CHUNAV" in block
    assert "Sanskritized Hindi BILKUL nahi" in block
    for wrong, right in (("संदेश प्रेषित करें", "message bhejo"),
                         ("प्रमाण उपलब्ध है", "evidence milta hai"),
                         ("परिकल्पना का परीक्षण", "hypothesis ko test karna"),
                         ("शुभ प्रभात", "Good morning"),
                         ("निष्कर्ष", "Final conclusion"),
                         ("उपलब्ध साक्ष्यों के आधार पर",
                          "jo evidence mila hai uske basis par")):
        assert wrong in block, wrong
        assert right in block, right
    # Devanagari sawaal par bhi wahi rule jaana chahiye
    assert "SHABDON KA CHUNAV" in style_block(HINDI)


def test_word_rules_keep_common_english_words_english():
    block = style_block(HINGLISH)
    for word in ("research", "evidence", "hypothesis", "dataset", "message",
                 "answer"):
        assert word in block, word


def test_teacher_voice_and_full_explanation_demanded():
    """§3 + §5: teacher ki tarah bolo, aur har result ka poora matlab do."""
    block = style_block(HINGLISH)
    assert "teacher" in block
    assert "Seedhi baat ye hai" in block and "Example se samjho" in block
    assert "debug console" in block          # aisa MAT likho
    for must in ("limitation", "evidence", "kyun hua"):
        assert must in block, must


def test_simple_does_not_mean_shallow():
    """§17: aasan bhasha ka matlab halka jawab nahi."""
    block = style_block(HINGLISH)
    assert "halka jawab NAHI" in block
    for must in ("uncertainty", "assumptions", "limitations"):
        assert must in block, must
    assert "causation" in block


def test_english_question_gets_english_word_rules():
    """English poochhne wale ko 'message bhejo' wale examples nahi jaane chahiye."""
    block = style_block(ENGLISH)
    assert "WORD CHOICE" in block
    assert "SHABDON KA CHUNAV" not in block
    assert "संदेश प्रेषित करें" not in block
    assert "teacher" in block
    assert "does NOT mean a thin answer" in block
    assert "correlation is not causation" in block


# ── prompts mein sach mein pahuncha ya nahi ──────────────────────────────────
def _pack() -> EvidencePack:
    src = SourceRecord(title="Intermittent fasting and glycemic control",
                       url="https://pubmed.ncbi.nlm.nih.gov/1",
                       snippet="A randomized trial of time-restricted eating.",
                       connector="pubmed", source_type=SourceType.PAPER,
                       peer_reviewed=True, doi="10.1/if")
    src.source_id = "S1"
    return EvidencePack(question=HINDI, sources=[src], passages=[])


PLAN = {"relevant_fields": ["Medicine", "Biology"], "sub_questions": ["kya evidence hai?"]}


def test_analysis_prompt_carries_language_rule():
    prompt = GeminiReasoning(budget=1).prompt_analysis(ENGLISH, _pack(), PLAN)
    assert "ENGLISH" in prompt
    assert "SAMJHANE KA TARIKA" in prompt


def test_no_source_prompt_carries_language_rule():
    prompt = GeminiReasoning(budget=1).prompt_no_sources(HINDI, PLAN)
    assert "Devanagari" in prompt


def test_synthesis_prompt_mirrors_english():
    prompt = FinalSynthesizer().prompt(ENGLISH, "analysis text", "", "", _pack(), PLAN)
    assert "ENGLISH" in prompt
    # purana hard-coded nirdesh wapas nahi aana chahiye
    assert "simple, conversational Hindi/Hinglish" not in prompt
    assert "HEADINGS" in prompt and SECTION_TITLES[0] in prompt


def test_synthesis_prompt_mirrors_hindi():
    prompt = FinalSynthesizer().prompt(HINDI, "analysis text", "", "", _pack(), PLAN)
    assert "HINDI (Devanagari)" in prompt


def test_critic_prompt_carries_language_rule():
    prompt = Critic().prompt(HINGLISH, "analysis text", _pack())
    assert "HINGLISH" in prompt
    assert "Weaknesses" in prompt


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
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not failed else f"\n{failed} test fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
