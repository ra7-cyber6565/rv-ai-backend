"""
QueryBuilder ka offline test — koi network, koi Gemini, koi API key nahi.

Ye test ussi live failure ko pakadta hai jisme energy ke sawaal par Gagea (phool)
aur WHO surgeons-density jaisi sources aa gayi thi. Asli wajah: lambe prompt ke
PEHLE 6 shabd search par chale ja rahe the ("मान", "मानव", "सभ्यता", "अगले"...).

Chalao:  python3 -m pytest tests/test_query_builder.py -q
Ya:      python3 tests/test_query_builder.py       (pytest na ho to bhi chalega)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.query_builder import (  # noqa: E402
    is_instruction_prompt, search_query, topic_terms,
)

# Wahi 2000-character instruction-style prompt (live test se)
ENERGY_PROMPT = """मान लो मानव सभ्यता को अगले 100 वर्षों में एक ऐसी ऊर्जा तकनीक
खोजनी है जो आज की nuclear, solar और battery technologies से कई गुना अधिक
efficient हो और लगभग unlimited clean energy दे सके।

तुम्हें Physics, materials science, chemistry, mathematics, computer science,
engineering, economics और human psychology — इन सभी fields को जोड़कर सोचना है।

Internet पर उपलब्ध research papers, books, PDFs, patents और datasets खोजो और
पढ़ो। जो भी evidence मिले उसे clearly cite करो।

कम-से-कम 3 hypotheses बनाओ जो अभी तक किसी ने test नहीं की हों। हर hypothesis को
HYPOTHESIS label करो, और उसके assumptions साफ लिखो।

फिर हर hypothesis के खिलाफ जाने वाला evidence भी खोजो (red team). अंत में बताओ कि
कौन सा experiment या simulation इसे settle कर सकता है, और अगर evidence
insufficient है तो साफ बोलो कि यह speculative है — verified नहीं।"""

SHORT_QUESTIONS = [
    "cancer ki nai dawa par research kya kehti hai",
    "मधुमेह का इलाज क्या है",
    "hypothesis testing kaise karte hain",
    "black holes ke bare me btao",
]


def test_energy_prompt_finds_energy_not_filler():
    terms = topic_terms(ENERGY_PROMPT, limit=8)
    assert "energy" in terms, terms
    # ye wahi galat shabd hain jo pehle top-6 mein aa rahe the
    # (filler ab English mein map hote hain, isliye dono roop check karo)
    for junk in ("मान", "मानव", "human", "सभ्यता", "civilization", "अगले",
                 "वर्षों", "year", "ऐसी", "100"):
        assert junk not in terms, f"filler {junk} still in {terms}"
    # instruction vocabulary topic nahi ban sakta
    for meta in ("research", "hypothesis", "evidence", "source", "paper", "खोजो"):
        assert meta not in terms, f"instruction word {meta} treated as topic: {terms}"
    # aur asli technical shabd andar hone chahiye
    hits = {t for t in terms} & {"nuclear", "solar", "battery", "clean",
                                 "efficient", "unlimited", "technology"}
    assert len(hits) >= 3, f"only {hits} out of {terms}"


def test_no_devanagari_left_in_query():
    """Papers/datasets ka index English mein hai — Hindi token bheja to 0 result."""
    q = search_query(ENERGY_PROMPT)
    leftover = [ch for ch in q if "ऀ" <= ch <= "ॿ"]
    assert not leftover, f"Devanagari bach gaya query mein: {q}"


def test_energy_prompt_is_instruction_style():
    assert is_instruction_prompt(ENERGY_PROMPT) is True
    for q in SHORT_QUESTIONS:
        assert is_instruction_prompt(q) is False, q


def test_query_length_capped():
    q = search_query(ENERGY_PROMPT)
    assert 0 < len(q) <= 200, (len(q), q)
    # OpenAlex ne HTTP 400 diya tha kyunki poora prompt URL mein chala gaya tha
    assert "\n" not in q


def test_devanagari_mapped_to_english():
    # papers ka index English mein hai — Hindi bhejna = 0 results
    assert "diabetes" in topic_terms("मधुमेह का इलाज क्या है")
    assert "energy" in topic_terms("सौर ऊर्जा की दक्षता")


def test_short_question_still_works():
    for q in SHORT_QUESTIONS:
        terms = topic_terms(q)
        assert terms, q
        assert len(search_query(q)) >= 3, q
    # chhote sawaal mein "hypothesis" TOPIC hai, filler nahi
    assert "hypothesi" in topic_terms("hypothesis testing kaise karte hain") \
        or "hypothesis" in topic_terms("hypothesis testing kaise karte hain")


def test_extra_steering_words_survive():
    q = search_query("सौर ऊर्जा की दक्षता", extra=["systematic review"])
    assert "systematic review" in q


def test_terms_are_real_words_not_broken_stems():
    """
    Andar plural ki ginti stem par hoti hai, par BAHAR asli shabd jaana chahiye.

    Pehle "diabetes" -> "diabete" nikalta tha. Wo teen jagah nuksaan karta tha:
    PubMed/OpenAlex ko tootela shabd search hota, relevance guard "technology"
    ko "technologies" wale title mein dhoondh nahi paati thi, aur user ko
    honesty report mein "diabete" dikhta tha.
    """
    terms = topic_terms("intermittent fasting type 2 diabetes par kya asar hota hai")
    assert "diabetes" in terms, terms
    assert "diabete" not in terms, terms
    for broken in ("serie", "diseas", "batterie", "studie"):
        assert broken not in topic_terms(
            "series of studies on diseases and batteries efficiency"), broken


def test_plural_and_singular_stay_one_term():
    """battery + batteries = ek hi cheez — warna dono ka score aadha reh jaata."""
    terms = topic_terms("battery research: batteries ki energy density kaise badhti hai")
    assert len([t for t in terms if t.startswith("batter")]) == 1, terms


def test_hinglish_grammar_never_reaches_the_search_query():
    """
    Hinglish sawaal ka topic English shabdon mein jaana chahiye, grammar nahi.

    Do wajah: (1) PubMed/OpenAlex mein "kehti"/"daalta" ka koi index nahi hai,
    (2) "research"/"study" jaise shabd HAR paper ke abstract mein hote hain — inhe
    topic term maanne se relevance guard jhooth bolne lagta hai (Gagea ki botany
    bhi ek match maar kar off-topic hone se bach jaati thi).
    """
    q = search_query("intermittent fasting type 2 diabetes par kya asar daalta hai, "
                     "research kya kehti hai")
    for junk in ("kehti", "daalta", "research", "kya", "hai", "par"):
        assert junk not in q.split(), f"{junk} query mein bach gaya: {q}"
    assert "fasting" in q and "diabetes" in q, q
    # Hinglish topic shabd English mein badle hain (papers ka index English hai)
    assert "effect" in q, q
    assert "drug" in search_query("cancer ki nai dawa par research kya kehti hai")
    assert "sleep" in search_query("sugar ki bimari me neend ka kya asar hota h")


def test_short_question_topic_words_survive():
    """Filter zyada aggressive na ho jaye — asli topic bachna chahiye."""
    assert "hypothesis" in topic_terms("hypothesis testing kaise karte hain")
    assert "holes" in topic_terms("black holes ke bare me btao")
    for word in ("solid", "state", "battery", "energy"):
        assert word in topic_terms(
            "solid state battery ki energy density par latest research"), word


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  FAIL {name}: {exc}")
    print("\ntopic_terms(ENERGY_PROMPT) =", topic_terms(ENERGY_PROMPT, limit=8))
    print("search_query(ENERGY_PROMPT) =", search_query(ENERGY_PROMPT))
    sys.exit(1 if fails else 0)
