"""
§16 ke TEST A, B, C — retrieval ki asli parakh (offline).

Ye teen test seedha live "Superconductivity Test #3" failure se aaye hain:
maternal-death dataset, NHA estimate, sunbed regulation aur room-temperature
FERROELECTRICITY ko superconductivity ke sawaal par "relevant" maan liya gaya
tha, aur wahi kachra poore pipeline mein aage chala gaya.

  A. maternal-health / health-spending dataset REJECT hona chahiye
  B. room-temperature ferroelectricity (superconductivity ke bina) REJECT
  C. seedha relevant superconductivity review, unrelated materials paper se
     UPAR rank kare

Koi network, koi Gemini, koi pytest. Seedha
`python3 tests/test_relevance_domain.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import domain  # noqa: E402
from research_engine.connectors.paper_connector import ArxivConnector  # noqa: E402
from research_engine.depth import get_depth_config  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.relevance import RelevanceEngine  # noqa: E402
from research_engine.source_kind import classify as classify_kind  # noqa: E402

QUESTION = ("Kya room-temperature superconductivity practically possible hai? "
            "Ambient pressure par kaun-kaun se materials (hydrides, cuprates) "
            "ka critical temperature sabse zyada hai?")

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


def rec(title: str, snippet: str, url: str, connector: str,
        stype: SourceType = SourceType.PAPER, year: int = 2023,
        peer: bool = True) -> SourceRecord:
    return SourceRecord(title=title, snippet=snippet, url=url, connector=connector,
                        source_type=stype, year=year, peer_reviewed=peer)


def score_one(engine: RelevanceEngine, s: SourceRecord) -> float:
    """
    Ek akela source, jaise rank() ke andar hota hai: pehle §6 ka kind, phir
    relevance. Kind ke bina scoring adhoori hai (dataset/review ka signal
    score_relevance khud padhta hai).
    """
    if not s.doc_kind:
        kv = classify_kind(title=s.title, snippet=s.snippet, url=s.url,
                           connector=s.connector, venue=s.venue,
                           publisher=s.publisher, doi=s.doi,
                           peer_reviewed=s.peer_reviewed)
        s.doc_kind = kv.kind
        s.doc_kind_label = kv.label
        s.doc_kind_confidence = kv.confidence
    return engine.score_relevance(s, QUESTION)


# ── live failure ke asli off-topic sources ────────────────────────────────────
JUNK = [
    rec("Maternal mortality ratio (modeled estimate, per 100 000 live births)",
        "Country-level maternal deaths dataset, 2000-2020, WHO Global Health "
        "Observatory indicator.",
        "https://www.who.int/data/gho/indicator/MMR", "who_gho",
        SourceType.DATASET, 2021, False),
    rec("National Health Accounts: current health expenditure estimate",
        "NHA estimate of health spending as share of GDP by country and year.",
        "https://apps.who.int/nha/database", "who_gho", SourceType.DATASET,
        2022, False),
    rec("Regulation of sunbed use and UV exposure limits",
        "Policy review of sunbed regulation and skin cancer prevention.",
        "https://www.who.int/publications/sunbeds", "who_gho",
        SourceType.WEB, 2019, False),
    rec("Banana and luffa fibre composites for low-cost prosthetic sockets",
        "Natural fibre reinforced composite prosthetic socket mechanical "
        "testing of banana and luffa fibres.",
        "https://example.org/banana-prosthetic", "openalex", SourceType.PAPER,
        2020),
]
FERRO = rec(
    "Room-temperature ferroelectricity in ultrathin hafnium oxide films",
    "We report robust room-temperature ferroelectric switching and polarization "
    "retention in HfO2 thin films for non-volatile memory devices. No "
    "measurements of electrical resistance vanishing were performed.",
    "https://example.org/ferroelectric", "openalex")
RELEVANT = rec(
    "Room-temperature superconductivity in hydrides: a critical review of "
    "reported critical temperature and ambient-pressure claims",
    "Review of superconductivity in high-pressure hydrides (LaH10, H3S) and "
    "cuprates, covering Meissner effect measurements, Cooper pairing, and the "
    "critical temperature Tc reported near room temperature, plus failed "
    "replication attempts of ambient-pressure claims.",
    "https://example.org/sc-review", "openalex")
UNRELATED_MATERIALS = rec(
    "Thermal conductivity of polycrystalline alumina ceramics",
    "Measurement of thermal transport in alumina ceramic samples sintered at "
    "different temperatures for structural applications.",
    "https://example.org/alumina", "openalex")


def main() -> int:
    engine = RelevanceEngine()
    plan = domain.detect(QUESTION)

    print("\n[0] Domain pehchana gaya")
    check("domain known hai", plan.is_known, plan.profile.key)
    check("superconductivity profile chuna",
          "superconduct" in plan.profile.key, plan.profile.key)

    print("\n[A] Health/dataset kachra reject hota hai")
    for s in JUNK:
        score = score_one(engine, s)
        check(f"reject: {s.title[:48]}", score <= 0.0 or bool(s.rejected_reason),
              f"score={score:.3f} reason={s.rejected_reason!r}")

    print("\n[B] Room-temperature ferroelectricity reject hota hai")
    ferro_score = score_one(engine, FERRO)
    check("ferroelectricity ka score zero/hard-reject hai",
          ferro_score <= 0.0 or bool(FERRO.rejected_reason),
          f"score={ferro_score:.3f} reason={FERRO.rejected_reason!r}")

    print("\n[C] Relevant review, unrelated materials paper se upar")
    good = score_one(engine, RELEVANT)
    other = score_one(engine, UNRELATED_MATERIALS)
    check("relevant review ka score sabse ooncha", good > other,
          f"{good:.3f} vs {other:.3f}")
    check("relevant review ka score theek-thaak hai", good >= 0.45, f"{good:.3f}")

    print("\n[A+B+C] rank() ke baad evidence pack saaf hai")
    candidates = JUNK + [FERRO, UNRELATED_MATERIALS, RELEVANT]
    ranked = engine.rank(candidates, QUESTION, max_sources=10, max_per_origin=3)
    titles = [s.title for s in ranked]
    check("relevant review pack mein hai", RELEVANT.title in titles)
    check("relevant review sabse pehle hai",
          titles and titles[0] == RELEVANT.title, str(titles[:2]))
    for s in JUNK:
        check(f"pack mein nahi: {s.title[:44]}", s.title not in titles)
    check("ferroelectricity pack mein nahi", FERRO.title not in titles,
          str(titles))
    info = engine.last_filter
    check("dropped ginti report hoti hai", int(info.get("dropped_offtopic", 0)) >= 4,
          str(info.get("dropped_offtopic")))
    check("hard rejection ki wajah likhi hui hai",
          int(info.get("hard_rejected", 0)) >= 1
          and bool(info.get("hard_rejected_examples")),
          str(info.get("hard_rejected_examples")))
    check("dedup ka record hai (§11 gate isi par tika hai)",
          info.get("deduplicated") is True)

    print("\n[§3] Connector routing — WHO GHO superconductivity par nahi chalta")
    planner = ResearchPlanner()
    cls = planner.classify(QUESTION)
    cplan = planner.connector_plan(cls, get_depth_config("MAXIMUM"), QUESTION)
    # Sirf wo lists jinpar SEARCH chalti hai. `skipped_connectors` bhi ek list
    # hai, par wo "band kiya gaya" ka record hai — usko chalne wale connectors
    # mein ginna ulta jawab de dega.
    will_run = []
    for key in ("papers", "books", "datasets"):
        will_run.extend([str(c) for c in (cplan.get(key) or [])])
    check("who_gho band hai", "who_gho" not in will_run, str(will_run))
    check("world_bank band hai", "world_bank" not in will_run, str(will_run))
    check("data_gov_in band hai", "data_gov_in" not in will_run, str(will_run))
    check("papers side chalti hai",
          any(c in will_run for c in ("openalex", "arxiv", "crossref")),
          str(will_run))
    check("arxiv sabse aage hai (is field ki priority)",
          (cplan.get("papers") or [""])[0] == "arxiv", str(cplan.get("papers")))
    check("band karne ki wajah likhi hui hai (§3 disclosure)",
          bool(cplan.get("skipped_connectors")) and bool(cplan.get("routing_note")),
          str(cplan.get("skipped_connectors")))

    print("\n[§4] arXiv query dheeli hone par bhi anchor nahi girta")
    # Live failure ki jad: ladder ka aakhri step `all:\"room-temperature\"` ban
    # gaya tha, aur usi ne room-temperature FERROELECTRICITY uthaya (TEST B ka
    # source). Isliye ladder ke HAR step par anchor rehna chahiye.
    for max_terms in (5, 3, 2, 1):
        q = ArxivConnector.build_search_query(QUESTION, max_terms=max_terms)
        check(f"max_terms={max_terms} par anchor bacha hai",
              "superconduct" in q.lower(), q)
        check(f"max_terms={max_terms} par akela 'room-temperature' nahi",
              q.lower() != 'all:"room-temperature"', q)

    print("\n[§4] Har round ki queries mein field anchor rehta hai")
    for round_no in (1, 2, 3):
        qs = planner.search_queries(QUESTION, round_no=round_no)
        check(f"round {round_no}: queries bani", len(qs) >= 2, str(qs))
        check(f"round {round_no}: har query mein anchor hai",
              all(any(a in q.lower() for a in
                      ("superconduct", "hydride", "cuprate", "transition temperature"))
                  for q in qs),
              str(qs))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_relevance_domain_checks_all_pass():
    """
    pytest ke liye entry point (2026-08-21) — saare check `main()` ke andar hain,
    isliye pytest is file se 0 test collect kar raha tha aur CI ka step bina kuch
    chalaye green ho jaata tha.
    """
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
