"""
§11 + TEST H — "retrieved links ka dher consensus nahi hota".

Offline: koi network, koi Gemini, koi pytest. Seedha
`python3 tests/test_consensus_gate.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.consensus_gate import (  # noqa: E402
    CONSENSUS_UNAVAILABLE, MIN_INDEPENDENT, evaluate, opposition_in_queries)
from research_engine.contradiction import ContradictionEngine  # noqa: E402
from research_engine.models import (  # noqa: E402
    EvidencePack, Passage, SourceRecord, SourceType)
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.synthesizer import FinalSynthesizer  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, extra: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def _source(idx: int, stance: str, origin: str, relevance: float = 0.7,
            level: str = "abstract") -> SourceRecord:
    text = {
        "support": "Superconductivity was confirmed and the transition "
                   "significantly improved above 250 K in this hydride sample.",
        "oppose": "The claimed room-temperature superconductivity did not "
                  "reproduce; no significant Meissner signal was observed.",
        "neutral": "Crystal structure of the hydride phase is reported without "
                   "transport measurements.",
    }[stance]
    s = SourceRecord(
        title=f"Hydride superconductivity study {idx}",
        url=f"https://{origin}/paper-{idx}",
        snippet=text,
        connector="openalex",
        source_type=SourceType.PAPER,
        year=2020 + (idx % 4),
        peer_reviewed=True,
        relevance_score=relevance,
    )
    s.source_id = f"S{idx}"
    s.read_level = level
    return s


def _pack(sources, queries=None, reasoning_done: int = 3,
          reasoning_planned: int = 3, dedup: bool = True) -> EvidencePack:
    pack = EvidencePack(
        question="Kya room-temperature superconductivity possible hai?",
        sources=list(sources),
        passages=[Passage(source_id=s.source_id, text=s.snippet) for s in sources],
        topic_terms=["superconductivity", "room", "temperature"],
        retrieval_filter=({"candidates": len(sources) + 4, "deduplicated": True,
                           "duplicates_removed": 4} if dedup else {}),
        search_queries=list(queries or []),
    )
    pack.reasoning_planned = reasoning_planned
    pack.reasoning_done = reasoning_done
    return pack


GOOD_QUERIES = [
    "room temperature superconductivity ambient pressure",
    "high pressure hydride superconductivity critical temperature",
    "room temperature superconductivity contradictory findings criticism limitations",
]
SUPPORT_ONLY_QUERIES = [
    "room temperature superconductivity ambient pressure",
    "hydride superconductivity critical temperature Tc",
]


def healthy_pack() -> EvidencePack:
    sources = [
        _source(1, "support", "journals.aps.org"),
        _source(2, "support", "nature.com"),
        _source(3, "support", "arxiv.org"),
        _source(4, "oppose", "science.org"),
    ]
    return _pack(sources, queries=GOOD_QUERIES)


def main() -> int:
    print("\n[1] Saari shartein poori — level banta hai")
    pack = healthy_pack()
    gate = evaluate(pack, contradictions=[], queries=GOOD_QUERIES)
    check("gate pass hua", gate.passed, str(gate.to_dict()["unmet"]))
    check("chhe shartein check hui", len(gate.checks) == 6, str(len(gate.checks)))
    engine = ContradictionEngine()
    report = engine.consensus_report(pack, [], contradiction_analysis_done=True,
                                     reasoning_complete=True, queries=GOOD_QUERIES)
    check("level asli hai, blocked nahi",
          report["level"] != CONSENSUS_UNAVAILABLE, report["level"])
    check("gate_passed flag true", report["gate_passed"] is True)

    print("\n[2] TEST H — contradiction analysis chali hi nahi → consensus nahi")
    report_h = engine.consensus_report(pack, None)
    check("level exactly wahi vaakya hai",
          report_h["level"] == CONSENSUS_UNAVAILABLE, report_h["level"])
    check("gate_passed false", report_h["gate_passed"] is False)
    check("wajah likhi hui hai", bool(report_h["unmet_conditions"]))
    check("analysis_complete shart tooti",
          "analysis_complete" in report_h["gate"]["unmet"],
          str(report_h["gate"]["unmet"]))
    check("raw level jaankari khoyi nahi (audit ke liye)",
          bool(report_h.get("level_if_gate_passed")))
    check("note mein exact vaakya hai", CONSENSUS_UNAVAILABLE in report_h["note"])

    print("\n[3] Reasoning adhoora (quota) → consensus nahi")
    thin = _pack(healthy_pack().sources, queries=GOOD_QUERIES,
                 reasoning_done=1, reasoning_planned=3)
    r = engine.consensus_report(thin, [], contradiction_analysis_done=True,
                               queries=GOOD_QUERIES)
    check("quota-adhoore run par level block", r["level"] == CONSENSUS_UNAVAILABLE)
    check("wajah mein pass ki ginti hai",
          any("1/3" in u for u in r["unmet_conditions"]),
          str(r["unmet_conditions"]))

    print("\n[4] Sirf support-side search hui → consensus nahi")
    one_sided = _pack(healthy_pack().sources, queries=SUPPORT_ONLY_QUERIES)
    g = evaluate(one_sided, contradictions=[], reasoning_complete=True)
    check("support_and_opposition_search shart tooti",
          "support_and_opposition_search" in g.to_dict()["unmet"],
          str(g.to_dict()["unmet"]))
    check("opposition marker detect hota hai",
          opposition_in_queries(GOOD_QUERIES)
          and not opposition_in_queries(SUPPORT_ONLY_QUERIES))

    print("\n[5] Off-topic dher (live superconductivity failure) → consensus nahi")
    junk = [
        _source(1, "support", "who.int", relevance=0.12, level="metadata"),
        _source(2, "support", "worldbank.org", relevance=0.10, level="metadata"),
        _source(3, "support", "data.gov.in", relevance=0.08, level="metadata"),
    ]
    junk_pack = _pack(junk, queries=SUPPORT_ONLY_QUERIES, reasoning_done=1,
                      reasoning_planned=3, dedup=False)
    for s in junk_pack.sources:
        s.snippet = "Maternal mortality estimates by country."
    junk_pack.passages = []
    gj = evaluate(junk_pack, contradictions=None)
    unmet = gj.to_dict()["unmet"]
    for name in ("source_relevance", "claim_level_extraction",
                 "support_and_opposition_search", "duplicates_removed",
                 "analysis_complete"):
        check(f"shart tooti: {name}", name in unmet, str(unmet))
    check("koi bhi shart poori na ho to gate pass nahi", not gj.passed)

    print("\n[6] Kam independent origins → consensus nahi")
    same_origin = [_source(i, "support", "example.org") for i in (1, 2, 3, 4)]
    for s in same_origin:
        s.url = "https://example.org/one-paper"
    g6 = evaluate(_pack(same_origin, queries=GOOD_QUERIES), contradictions=[],
                  reasoning_complete=True)
    check("independent_sources shart tooti",
          "independent_sources" in g6.to_dict()["unmet"],
          f"MIN_INDEPENDENT={MIN_INDEPENDENT} " + str(g6.to_dict()["unmet"]))

    print("\n[7] Report mein exact vaakya chhapta hai, bewakoofi wala nahi")
    synth = FinalSynthesizer()
    answer = synth.assemble(
        gemini_answer="## Seedha jawab\nAbhi tak nahi.", pack=pack,
        evidence_level="WEAK", confidence_note="", contradictions=[],
        hypotheses=[], verification={}, coverage={}, honesty={},
        consensus=report_h)
    check("exact vaakya report mein hai", CONSENSUS_UNAVAILABLE in answer)
    check("'sehmati ka level: Consensus evaluate' jaisa vaakya nahi bana",
          "level: Consensus evaluate" not in answer)
    check("shartein report mein likhi hui hain",
          "Ye shartein poori nahi hui" in answer)
    check("APPARENT CONSENSUS ka daawa nahi hua",
          "sehmati dikhti hai" not in answer)

    print("\n[8] Round 2 se opposition query pipeline ka hissa hai")
    planner = ResearchPlanner()
    q1 = planner.search_queries("Kya room temperature superconductivity possible hai?",
                                round_no=1)
    q2 = planner.search_queries("Kya room temperature superconductivity possible hai?",
                                round_no=2)
    check("round 2 mein counter-evidence query hai", opposition_in_queries(q2),
          str(q2))
    check("round 1 topic-focused rehta hai", len(q1) >= 1, str(q1))
    check("round 2 ki queries round 1 se alag hain",
          set(q2) - set(q1) != set(), str(q2))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_consensus_gate_checks_all_pass():
    """
    pytest ke liye entry point (2026-08-21) — saare check `main()` ke andar hain,
    isliye pytest is file se 0 test collect kar raha tha aur CI ka step bina kuch
    chalaye green ho jaata tha.
    """
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
