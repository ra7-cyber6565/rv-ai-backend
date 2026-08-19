"""
test_connectors.py — LIVE connector test (ise APNE LAPTOP par chalao)

    cd C:\\Users\\intel\\Music\\infinity-research-ai-main\\infinity-research-ai-main\\backend
    venv\\Scripts\\activate
    python test_connectors.py

Kyun zaroori hai: har API apne JSON mein field ke naam alag rakhti hai
(OpenAlex 'display_name', Crossref 'title' ek list hoti hai, DOAJ sab kuch
'bibjson' ke andar rakhta hai…). Code defensive hai — galat field ka matlab
crash nahi, balki KHAALI metadata. Aur khaali metadata chupke se evidence
quality gira deta hai. Isliye ye script har connector se ek real result maangti
hai aur check karti hai ki title/url sach mein bhare hain ya nahi.

2026-08-17 KA SABAK — ye script "OK" bol kar ek asli bug chhupa gayi thi:
    arXiv ne healthcare-bias query par "Portfolio Tail Risk Measurement" ka
    paper diya. Field mapping perfect thi (title/url/year sab bhare the), isliye
    status "OK" aaya — par jawab topic se bilkul bahar tha.
    Sabak: field mapping OK hona aur result SAHI hona do alag cheezein hain.
    Isliye ab har result ka RELEVANCE bhi check hota hai, aur kam overlap par
    "RELEVANCE KAM" warning aati hai — chahe saare fields bhare hon.

Aur "0 results" ab teen alag cheezon mein bata hai:
    khaali  — search chali, sach mein kuch nahi mila
    RUKA    — search chali hi nahi (rate limit / 403 / timeout)
    SKIP    — API key hi nahi hai

*** Gemini ki ek bhi call nahi hoti — sirf free search APIs hit hoti hain.
    Tavily free tier (~1000/month) mein se ye test ~2 use karega. ***
"""
from __future__ import annotations

import os
import sys
import traceback
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

QUERY = "algorithmic bias in healthcare risk prediction"
RESULTS: List[Dict] = []

# Kam se kam kitne query terms result mein hone chahiye, warna "RELEVANCE KAM"
MIN_TERM_OVERLAP = 2


def probe(connector) -> None:
    """Ek connector chalao (safe_search se) aur field-quality + relevance report do."""
    from research_engine.connectors.base import content_terms, term_overlap

    label = connector.name
    needs_key = getattr(connector, "api_key", None) is not None and not getattr(
        connector, "api_key", "")
    if needs_key:
        print(f"\n[SKIP] {label} — API key .env mein nahi hai "
              f"(is connector ke bina baaki sab phir bhi chalta hai)")
        RESULTS.append({"connector": label, "status": "SKIP (no key)", "count": 0})
        return

    print(f"\n[{label}] chal raha hai…")
    outcome = connector.safe_search(QUERY, max_results=3)   # kabhi raise nahi karta
    records = outcome["records"]
    note = outcome.get("note", "")
    reason = outcome.get("reason", "")

    if note:
        print(f"  note    : {note}")

    if reason in ("rate_limited", "blocked", "timeout"):
        # search hi nahi hui — ise "kuch nahi mila" MAT samjho
        print(f"  RUKA ({outcome['seconds']}s): {outcome['error']}")
        RESULTS.append({"connector": label, "status": f"RUKA ({reason})", "count": 0})
        return
    if outcome["error"]:
        print(f"  ERROR ({outcome['seconds']}s): {outcome['error']}")
        RESULTS.append({"connector": label, "status": f"ERROR {outcome['error'][:40]}",
                        "count": 0})
        return
    if not records:
        print(f"  0 results ({outcome['seconds']}s) — search chali par is query par "
              f"kuch nahi mila")
        RESULTS.append({"connector": label, "status": "0 results", "count": 0})
        return

    first = records[0]
    title = (first.title or "").strip()
    url = (first.url or "").strip()
    snippet = (first.snippet or "").strip()

    missing = [name for name, value in (("title", title), ("url", url)) if not value]
    if not snippet:
        missing.append("snippet(soft)")

    # ── relevance: yahi wo check hai jo pichhli baar nahi tha ──
    terms = content_terms(QUERY)
    overlaps = [term_overlap(terms, f"{r.title} {r.snippet}") for r in records]
    relevant = sum(1 for o in overlaps if o >= MIN_TERM_OVERLAP)

    if missing:
        status = f"FIELD MISSING: {', '.join(missing)}"
    elif relevant == 0:
        status = "RELEVANCE KAM (fields theek, topic galat)"
    elif relevant < len(records):
        status = f"OK ({relevant}/{len(records)} topic se jude)"
    else:
        status = "OK"

    print(f"  {len(records)} results ({outcome['seconds']}s) → {status}")
    print(f"  title   : {title[:95] or '(KHAALI — field name badal gaya hoga)'}")
    print(f"  url     : {url[:95] or '(KHAALI)'}")
    print(f"  snippet : {snippet[:95] or '(khaali — kuch APIs abstract nahi deti)'}")
    print(f"  year={first.year}  authors={len(first.authors or [])}  "
          f"doi={first.doi or '-'}  peer_reviewed={first.peer_reviewed}  "
          f"type={first.source_type.value}")
    print(f"  term match ({len(terms)} terms): {overlaps}  → {relevant} relevant")
    RESULTS.append({"connector": label, "status": status, "count": len(records)})


def main() -> int:
    print("=" * 72)
    print("LIVE CONNECTOR TEST — Gemini calls: 0")
    print(f"query: {QUERY}")
    print("=" * 72)

    from research_engine.connectors import BookConnector, PaperConnector, WebConnector

    web, papers, books = WebConnector(), PaperConnector(), BookConnector()

    print("\n" + "-" * 72)
    print("WEB (Tavily -> Wikipedia -> DuckDuckGo)")
    print("-" * 72)
    for connector in web.connectors:
        probe(connector)

    print("\n" + "-" * 72)
    print("PAPERS (koi paid key nahi chahiye)")
    print("-" * 72)
    for connector in papers.connectors:
        probe(connector)

    print("\n" + "-" * 72)
    print("BOOKS / ARCHIVES")
    print("-" * 72)
    for connector in books.connectors:
        probe(connector)

    # ── poori discovery fan-out ──
    print("\n" + "=" * 72)
    print("POORI DISCOVERY (parallel fan-out + dedup + ranking)")
    print("=" * 72)
    try:
        from research_engine.depth import get_depth_config
        from research_engine.planner import ResearchPlanner
        from research_engine.source_discovery import SourceDiscovery

        config = get_depth_config("DEEP")
        planner = ResearchPlanner()
        plan = planner.plan(QUERY, config)
        queries = planner.search_queries(QUERY, planner.classify(QUERY), round_no=1)
        outcome = SourceDiscovery().discover(
            queries=queries,
            plan=plan["connectors"],
            max_per_connector=config.max_per_connector,
            max_web=config.max_sources,
            round_no=1,
        )
        found, log = outcome["records"], outcome["log"]

        print(f"queries bheji: {queries}")
        print(f"total raw sources: {len(found)}")
        by_connector: Dict[str, int] = {}
        for record in found:
            by_connector[record.connector] = by_connector.get(record.connector, 0) + 1
        for name, count in sorted(by_connector.items(), key=lambda item: -item[1]):
            print(f"  {name:22} {count}")

        empty_titles = sum(1 for r in found if not (r.title or "").strip())
        empty_urls = sum(1 for r in found if not (r.url or "").strip())
        print(f"khaali title: {empty_titles} | khaali url: {empty_urls}")

        # discovery ke baad bhi topic-drift check karo (pichhli baar yahi chhoot gaya)
        from research_engine.connectors.base import content_terms, term_overlap
        terms = content_terms(QUERY)
        off_topic = [r for r in found
                     if term_overlap(terms, f"{r.title} {r.snippet}") < MIN_TERM_OVERLAP]
        print(f"topic se bahar lagne wale sources: {len(off_topic)}/{len(found)}")
        for record in off_topic[:5]:
            print(f"  ? {record.connector:18} {(record.title or '')[:70]}")
        if off_topic:
            print("  (ye ranking mein neeche jayenge — RelevanceEngine ka kaam — par "
                  "agar ek hi connector se aa rahe hain to us connector ki query "
                  "banane ki logic dekhni chahiye)")

        stopped = [e for e in log
                   if e.get("reason") in ("rate_limited", "blocked", "timeout")]
        errors = [e for e in log if e.get("error") and e not in stopped]
        if stopped:
            print("ruke (search hi nahi hui):")
            for entry in stopped:
                print(f"  - {entry.get('connector')} [{entry.get('reason')}]: "
                      f"{str(entry.get('error'))[:90]}")
        if errors:
            print("connector errors:")
            for entry in errors[:10]:
                print(f"  - {entry.get('connector')}: {entry.get('error')}")
        print(f"\ndiscovery note: {SourceDiscovery.discovery_note(log)}")
    except Exception:
        print("discovery fail hui:")
        traceback.print_exc(limit=3)

    # ── summary ──
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    problems = 0
    for row in RESULTS:
        ok = row["status"].startswith(("OK", "SKIP"))
        if not ok:
            problems += 1
        print(f"{'  ' if ok else '!!'} {row['connector']:22} "
              f"{row['count']:>3} results  {row['status']}")

    print(f"\n{len(RESULTS) - problems}/{len(RESULTS)} connectors theek hain.")
    if problems:
        print("\nAgey kya karna hai:")
        print("  * 'FIELD MISSING' → us API ka JSON shape badla hai. Wo line mujhe "
              "bhej do, main mapping fix kar dunga.")
        print("  * 'RELEVANCE KAM' → fields theek hain par result topic se bahar hai. "
              "Ye zyada khatarnaak hai (dikhta 'kaam kar raha' hai) — us connector "
              "ki query-building logic fix karni hogi.")
        print("  * 'RUKA (rate_limited)' → API ne roka, search chali hi nahi. "
              "1-2 min baad phir chalao; Semantic Scholar ke liye free key "
              ".env mein SEMANTIC_SCHOLAR_API_KEY se lag jaati hai.")
        print("  * 'RUKA (timeout)' → source free hai par slow. .env mein "
              "CONNECTOR_READ_TIMEOUT=60 daal kar dobara try karo.")
        print("  * 'RUKA (blocked)' → 403. google_books ke liye .env mein "
              "GOOGLE_BOOKS_COUNTRY apna country code daalo.")
        print("  * '0 results' → search chali par kuch nahi mila. Ek aam query "
              "(jaise 'diabetes') se test karke confirm karo.")
        print("  * 'ERROR ModuleNotFoundError' → pip install -r requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
