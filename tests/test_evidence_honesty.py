"""
Retrieval floor + evidence honesty gate ka offline test.

Ye test us live failure ko dobara banata hai (2026-08-19) jisme energy ke sawaal
par report ne "✅ VERIFIED — 2 peer-reviewed + 4 independent sources" chhaapa,
jabki:
    * saare sources off-topic the (Gagea naam ke phool ki botany, WHO ka
      surgeons-density page),
    * 5 mein se 0 ka full text pada gaya tha,
    * 3 reasoning pass mein se sirf 1 chala tha (Gemini quota 429).

Do cheezein saabit karni hain:
    1. RelevanceEngine.rank() zero-overlap sources ko HATA de — chahe unka
      domain kitna bhi bada ho (who.int, openalex.org quality mein pass hote hain).
    2. EvidenceEngine.grade_evidence() par teen honesty gate lagein: kamzor
      relevance, zero full-text reading, ya adhoora reasoning — kisi ek se bhi
      "VERIFIED"/"STRONG" impossible ho jaye, aur wajah likhi jaye.

Koi network, koi Gemini, koi API key nahi.

Chalao:  python3 tests/test_evidence_honesty.py
Ya:      python3 -m pytest tests/test_evidence_honesty.py -q
"""
from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.evidence import EvidenceEngine  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.relevance import RelevanceEngine  # noqa: E402

QUESTION = ("ek aisi energy technology jo nuclear, solar aur battery se kayi guna "
            "zyada efficient ho aur lagbhag unlimited clean energy de sake")


def _paper(title: str, url: str, snippet: str = "", **kw) -> SourceRecord:
    base = dict(title=title, url=url, snippet=snippet or title,
                connector="openalex", source_type=SourceType.PAPER)
    base.update(kw)
    return SourceRecord(**base)


# Bilkul wahi kachra jo live test mein top par aa gaya tha — sab BADE domain se
OFFTOPIC = [
    _paper("Gagea bohemica: a taxonomic revision of the genus in the Balkans",
           "https://openalex.org/W1", peer_reviewed=True, doi="10.1/gagea"),
    _paper("Density of surgeons per 100000 population, by country",
           "https://www.who.int/data/gho/indicator/surgeons", peer_reviewed=False),
    _paper("China-Pakistan Economic Corridor: geopolitics of connectivity",
           "https://openalex.org/W2", peer_reviewed=True, doi="10.1/cpec"),
    _paper("Estimates of the global burden of foodborne diseases",
           "https://www.who.int/publications/foodborne", peer_reviewed=True),
]

ON_TOPIC = [
    _paper("Solid-state battery energy density limits for clean energy storage",
           "https://openalex.org/W10",
           "We review solar and battery chemistry pathways toward higher energy "
           "efficiency, including nuclear-assisted charging cycles.",
           peer_reviewed=True, doi="10.1/battery", year=2024),
    _paper("Advances in nuclear fusion for unlimited clean energy",
           "https://www.nature.com/articles/fusion-energy",
           "Fusion energy research suggests a route to nearly unlimited clean "
           "electricity if plasma efficiency thresholds are met.",
           peer_reviewed=True, doi="10.1/fusion", year=2023),
    _paper("Perovskite solar cell efficiency roadmap",
           "https://openalex.org/W11",
           "Solar energy conversion efficiency has improved rapidly; we compare "
           "perovskite technology against silicon.",
           peer_reviewed=True, doi="10.1/solar", year=2025),
    _paper("Grid-scale energy storage economics",
           "https://www.sciencedirect.com/science/article/storage",
           "Battery storage cost curves and clean energy deployment scenarios.",
           peer_reviewed=True, doi="10.1/grid", year=2024),
]


# ── 1. relevance floor ───────────────────────────────────────────────────────
def test_zero_overlap_sources_are_dropped():
    engine = RelevanceEngine()
    ranked = engine.rank(list(OFFTOPIC) + list(ON_TOPIC), QUESTION, max_sources=10)
    titles = [s.title for s in ranked]
    for junk in OFFTOPIC:
        assert junk.title not in titles, f"off-topic source zinda hai: {junk.title}"
    assert len(ranked) == len(ON_TOPIC), f"on-topic sources gum ho gaye: {titles}"


def test_offtopic_only_pack_stays_empty():
    """
    Sirf kachra mile to pack KHAALI rehna chahiye — "kuch to de do" ke chakkar
    mein off-topic bharna hi purana bug tha.
    """
    engine = RelevanceEngine()
    ranked = engine.rank(list(OFFTOPIC), QUESTION, max_sources=10)
    assert ranked == [], f"off-topic hi rakh liye: {[s.title for s in ranked]}"
    assert engine.last_filter["dropped_offtopic"] == len(OFFTOPIC)


def test_user_document_is_never_dropped():
    """User ka apna PDF humara faisla nahi hai — wo hamesha rehta hai."""
    engine = RelevanceEngine()
    doc = SourceRecord(title="mera-note.pdf", url="", snippet="ye kisi aur topic ka hai",
                       connector="user_pdf", source_type=SourceType.DOCUMENT,
                       full_text_available=True, read_level="full_text")
    ranked = engine.rank([doc] + list(OFFTOPIC), QUESTION, max_sources=10)
    assert [s.title for s in ranked] == ["mera-note.pdf"]


def test_filter_report_is_honest():
    engine = RelevanceEngine()
    engine.rank(list(OFFTOPIC) + list(ON_TOPIC), QUESTION, max_sources=10)
    info = engine.last_filter
    assert info["candidates"] == 8
    assert info["kept"] == 4
    assert info["dropped_offtopic"] == 4
    assert info["avg_relevance"] > 0.2, info
    assert info["topic_terms"], "topic terms report mein hone chahiye"
    assert any("Gagea" in t for t in info["offtopic_titles"]), info["offtopic_titles"]


# ── 2. honesty gates ─────────────────────────────────────────────────────────
def _pack(sources, full_text=True, planned=3, done=3):
    ev = EvidenceEngine()
    # deepcopy zaroori hai: ON_TOPIC module-level objects hain aur build_pack
    # unhi objects ko pack mein daalta hai. Bina copy ke ek test ka
    # `full_text_chars = 4000` agle test mein zinda reh jaata tha, aur
    # "zero full text" wala test jhooth-much pass/fail hone lagta tha.
    ev_sources = [copy.deepcopy(s) for s in sources]
    pack = ev.build_pack(QUESTION, [], ev_sources, max_sources=10)
    if full_text:
        for s in pack.sources:
            s.full_text_chars = 4000
    pack.reasoning_planned = planned
    pack.reasoning_done = done
    return ev, pack


def test_good_pack_can_still_reach_top_label():
    """
    Sabse zaroori test: gate lagane ke baad bhi ACHHA evidence top label paa
    sakta hai. Warna hum bug ko "hamesha MIXED" se badal dete.
    """
    ev, pack = _pack(ON_TOPIC)
    grade = ev.grade_evidence(pack)
    assert "VERIFIED" in grade or "STRONG" in grade, grade
    assert "MIXED" not in grade, grade


def test_offtopic_pack_cannot_be_verified():
    ev, pack = _pack(ON_TOPIC)
    # relevance zabardasti gira do (jaise lambe prompt par hua tha)
    for s in pack.sources:
        s.relevance_score = 0.02
    grade = ev.grade_evidence(pack)
    assert "VERIFIED" not in grade and "STRONG" not in grade, grade
    assert "MIXED" in grade and "topic" in grade, grade


def test_zero_full_text_cannot_be_verified():
    ev, pack = _pack(ON_TOPIC, full_text=False)
    grade = ev.grade_evidence(pack)
    assert "VERIFIED" not in grade and "STRONG" not in grade, grade
    assert "poora text nahi" in grade, grade


def test_incomplete_reasoning_cannot_be_verified():
    """Live failure: 3 pass plan the, quota 429 ke baad sirf 1 chala."""
    ev, pack = _pack(ON_TOPIC, planned=3, done=1)
    grade = ev.grade_evidence(pack)
    assert "VERIFIED" not in grade and "STRONG" not in grade, grade
    assert "reasoning adhoora" in grade, grade
    assert "1/3" in grade, grade


def test_unrecorded_reasoning_is_not_a_free_pass():
    """planned=0 = kisi ne bataya hi nahi. Shabaashi nahi milegi."""
    ev, pack = _pack(ON_TOPIC, planned=0, done=0)
    assert not pack.reasoning_complete
    assert "VERIFIED" not in ev.grade_evidence(pack)


def test_pre_reasoning_grade_skips_only_that_gate():
    """
    Orchestrator reasoning se PEHLE ek kaccha grade nikaalta hai (hypothesis
    chahiye ya nahi). Us jagah reasoning gate nahi lagna chahiye, par baaki
    do gate wahin bhi lagne chahiye.
    """
    ev, pack = _pack(ON_TOPIC, planned=0, done=0)
    early = ev.grade_evidence(pack, check_reasoning=False)
    assert "VERIFIED" in early or "STRONG" in early, early

    ev2, pack2 = _pack(ON_TOPIC, full_text=False, planned=0, done=0)
    early2 = ev2.grade_evidence(pack2, check_reasoning=False)
    assert "VERIFIED" not in early2 and "STRONG" not in early2, early2


def test_coverage_report_tells_the_truth():
    ev, pack = _pack(ON_TOPIC, full_text=False, planned=3, done=1)
    cov = pack.coverage_report()
    assert cov["full_text_sources_read"] == 0
    assert cov["reasoning_passes"] == "1/3"
    assert "adhoora" in cov["reasoning_note"]
    assert cov["topic_terms"], cov


# ── runner (pytest ke bina bhi chale) ────────────────────────────────────────
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
