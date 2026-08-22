"""
₹0 PATENT BATCH ka offline test suite — point 7 (10 relevance traps) + point 9.

Yahan koi network nahi, koi API key nahi, koi Gemini nahi, koi pytest nahi.
Seedha chalao:

    python3 tests/test_patents.py

Kya cover hota hai (batch ke point number ke saath):
  [1]  connector unit tests — parse()/build_query()/to_record() pure functions
  [2]  query + routing — patent_intent, planner ka plan, discovery ke tasks (3)
  [3]  patent family dedup — US/EP/WO ek hi invention (5)
  [4]  source type + read depth — "patent padha" kab kehna banta hai (1, 6)
  [5]  relevance traps — same keyword alag invention, purana prior art, adhoora
       metadata (7)
  [6]  legal status honesty — status na mile to andaaza nahi (1, 7)
  [7]  patent ≠ scientific proof — teen alag gates (4)
  [8]  provider failure / quota — crash nahi, raw error leak nahi (2)
  [9]  no-network proof — http_get ko raiser banakar poora parsing chalana
  [10] novelty honesty — "koi patent nahi mila" ≠ "idea novel hai" (8)
  [11] determinism — ek hi input par hamesha ek hi output (9)
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import patents as patents_mod  # noqa: E402
from research_engine.claim_labels import (  # noqa: E402
    ESTABLISHED, SOURCE_REPORTED, downgrade, line_verdict)
from research_engine.claim_verification import PASS as V_PASS  # noqa: E402
from research_engine.claim_verification import UNKNOWN as V_UNKNOWN  # noqa: E402
from research_engine.claim_verification import check_d  # noqa: E402
from research_engine.connectors import patent_connector as pc  # noqa: E402
from research_engine.connectors.base import (AccessBlocked,  # noqa: E402
                                             RateLimited)
from research_engine.consensus_gate import evaluate  # noqa: E402
from research_engine.dedup import DeduplicationEngine  # noqa: E402
from research_engine.depth import DEEP, MAXIMUM, QUICK  # noqa: E402
from research_engine.gemini_reasoning import GeminiReasoning  # noqa: E402
from research_engine.models import (EvidencePack, Passage,  # noqa: E402
                                    SourceRecord, SourceType)
from research_engine.patents import (DEPTH_ABSTRACT, DEPTH_CLAIMS,  # noqa: E402
                                     DEPTH_FULL, DEPTH_METADATA,
                                     MIN_ABSTRACT_CHARS, MIN_CLAIMS_CHARS,
                                     MIN_DESCRIPTION_CHARS, PatentMeta,
                                     family_key, novelty_note,
                                     novelty_overclaim, patent_intent)
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.relevance import RelevanceEngine  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402
from research_engine.synthesizer import FinalSynthesizer  # noqa: E402

PASS = 0
FAIL = 0

# Test process ki env ko waisi hi lauta dena hai jaisi mili thi (stage 8 mein
# key set/unset hoti hai). Key ki VALUE kabhi print nahi hoti.
_ORIG_ODP_KEY = os.environ.get("USPTO_ODP_API_KEY")
_REAL_HTTP_GET = pc.http_get


def check(name: str, condition: bool, extra: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


# ── query aur text fixtures ──────────────────────────────────────────────────
# QUERY jaan-boojh kar aisa: `term_overlap()` substring match karta hai, isliye
# chhote term ("ion") "operation" ke andar match ho jaate aur hair-dryer wala
# trap khud-ba-khud pass ho jaata. Yahan ke saare terms lambe hain.
QUERY = "solid state lithium battery electrode ceramic separator"

LONG_ABSTRACT = (
    "A solid state lithium battery cell in which a sintered ceramic separator "
    "layer is arranged between a lithium metal anode and a composite cathode, "
    "wherein the separator has a garnet type structure.")

CLAIMS_TEXT = (
    "1. A solid state battery comprising a lithium metal anode, a composite "
    "cathode, and a sintered ceramic separator disposed therebetween.\n"
    "2. The battery of claim 1, wherein the ceramic separator comprises a "
    "garnet type lithium lanthanum zirconium oxide sheet.\n"
    "3. The battery of claim 1, wherein the ceramic separator thickness is "
    "less than fifty micrometres.")

DESCRIPTION_TEXT = (
    "The present disclosure relates to a solid state lithium battery in which "
    "a ceramic separator is sintered directly onto the cathode layer. ") * 12

EPO_URI = "http://data.epo.org/linked-data/data/publication/EP/2777777/B1/-"
EPO_URI_2 = "http://data.epo.org/linked-data/data/publication/EP/3111111/A1/-"

# EPO SPARQL fixture. Row 1 aur 2 EK HI publication ki hain (do inventor + do
# IPC = cross product) — inhe do patent ginna hi wo jhooth hai jo parse() rokta
# hai. Row 3 ka `number` field gayab hai (URI se banega) aur wo topic se bilkul
# alag invention hai. Row 4 kachra hai (na number na URI) — chupchaap skip.
EPO_FIXTURE = {
    "head": {"vars": ["publication", "number", "title"]},
    "results": {"bindings": [
        {"publication": {"value": EPO_URI},
         "number": {"value": "EP2777777B1"},
         "title": {"value": "Solid state lithium battery electrode with "
                            "ceramic separator"},
         "abstract": {"value": LONG_ABSTRACT},
         "publicationDate": {"value": "2016-05-11"},
         "filingDate": {"value": "2014-07-21"},
         "family": {"value": "56789012"},
         "applicant": {"value": "Toyota Jidosha KK"},
         "inventor": {"value": "Tanaka Hiroshi"},
         "ipc": {"value": "H01M10/0562"}},
        {"publication": {"value": EPO_URI},
         "number": {"value": "EP2777777B1"},
         "title": {"value": "Solid state lithium battery electrode with "
                            "ceramic separator"},
         "inventor": {"value": "Sato Kenji"},
         "ipc": {"value": "H01M4/13"}},
        {"publication": {"value": EPO_URI_2},
         "title": {"value": "Handheld hair dryer with rotating nozzle"},
         "abstract": {"value": "A hair dryer having a rotating nozzle and a "
                               "rechargeable battery pack for cordless "
                               "operation."},
         "publicationDate": {"value": "2017-01-18"}},
        {"title": {"value": "na number na URI — is row se record nahi banta"}},
    ]},
}

# USPTO ODP fixture. Doosra element jaan-boojh kar string hai (defensive parse).
ODP_FIXTURE = {
    "patentFileWrapperDataBag": [
        {"applicationNumberText": "16123456",
         "applicationURI": "https://api.uspto.gov/api/v1/patent/applications/16123456",
         "applicationMetaData": {
             "inventionTitle": "Solid state lithium battery electrode with "
                               "ceramic separator",
             "patentNumber": "10987654",
             "filingDate": "2016-08-02",
             "patentIssueDate": "2018-06-05",
             "applicationStatusDescriptionText": "Patented Case",
             "abstractText": LONG_ABSTRACT,
             "applicantBag": [{"applicantNameText": "Toyota Motor Corporation"}],
             "inventorBag": [{"inventorNameText": "Tanaka Hiroshi"},
                             {"inventorNameText": "Sato Kenji"}],
             "cpcClassificationBag": ["H01M10/0562"],
         }},
        "ye row dict nahi hai — parse ko ise chhodna chahiye",
    ]
}

class _Resp:
    """http_get ka jawab — sirf .json() chahiye hota hai."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _record(meta: PatentMeta, sid: str) -> SourceRecord:
    """PatentMeta → SourceRecord, asli connector ke raaste se (fake nahi)."""
    rec = pc.EpoLinkedDataConnector().to_record(meta, QUERY)
    rec.source_id = sid
    rec.relevance_score = 0.7
    return rec


def _paper(sid: str, title: str, snippet: str, origin: str,
           level: str = "abstract", year: int = 2021) -> SourceRecord:
    rec = SourceRecord(
        title=title, url=f"https://{origin}/paper-{sid.lower()}",
        snippet=snippet, connector="crossref", source_type=SourceType.PAPER,
        year=year, peer_reviewed=True, relevance_score=0.7)
    rec.source_id = sid
    rec.read_level = level
    return rec


def _pack(sources, queries=None) -> EvidencePack:
    """Consensus gate ki baaki shartein poori — taaki patent wali shart alag dikhe."""
    pack = EvidencePack(
        question="Solid state lithium battery electrode kaise banta hai?",
        sources=list(sources),
        passages=[Passage(source_id=s.source_id, text=s.snippet)
                  for s in sources],
        topic_terms=["solid", "state", "lithium", "battery", "electrode"],
        retrieval_filter={"candidates": len(sources) + 3, "deduplicated": True,
                          "duplicates_removed": 3},
        search_queries=list(queries or GOOD_QUERIES),
    )
    pack.reasoning_planned = 3
    pack.reasoning_done = 3
    return pack


GOOD_QUERIES = [
    "solid state lithium battery electrode ceramic separator",
    "solid state battery electrode contradictory findings criticism limitations",
]

def _family_trio():
    """
    EK invention, teen jagah publish — US, EP, WO. Family id teeno par same hai.

    EP member ke paas claims text hai, isliye family collapse ka survivor WAHI
    banna chahiye (sabse gehra padha gaya member jeetta hai).
    """
    common = dict(title="Solid state lithium battery electrode with ceramic "
                        "separator",
                  family_id="56789012", filing_date="2014-07-21",
                  abstract=LONG_ABSTRACT)
    us = PatentMeta(number="US9500001B2", assignee="Toyota Jidosha KK",
                    inventors=["Tanaka Hiroshi", "Sato Kenji"],
                    publication_date="2016-11-22", priority_date="2013-07-22",
                    legal_status="Patented Case",
                    legal_status_source="uspto_odp (USPTO Open Data Portal)",
                    url="https://api.uspto.gov/patent/US9500001B2",
                    provider="uspto_odp", **common)
    ep = PatentMeta(number="EP2777777B1", assignee="Toyota Jidosha KK",
                    inventors=["Tanaka Hiroshi"],
                    publication_date="2016-05-11", claims_text=CLAIMS_TEXT,
                    url=EPO_URI, provider="epo_lod", **common)
    wo = PatentMeta(number="WO2015012345A1", publication_date="2015-01-29",
                    url="", provider="epo_lod", **common)
    return us, ep, wo


def main() -> int:
    print("\n[1] Connector unit tests — parse/build_query/to_record (pure)")
    metas = pc.EpoLinkedDataConnector.parse(EPO_FIXTURE)
    check("cross-product rows ek hi publication gini gayi", len(metas) == 2,
          str([m.number for m in metas]))
    check("number waise hi jaisa provider ne diya",
          metas[0].number == "EP2777777B1", metas[0].number)
    check("dono inventor merge hue",
          metas[0].inventors == ["Tanaka Hiroshi", "Sato Kenji"],
          str(metas[0].inventors))
    check("dono IPC class merge hui",
          metas[0].ipc == ["H01M10/0562", "H01M4/13"], str(metas[0].ipc))
    check("family id waise hi rakha", metas[0].family_id == "56789012")
    check("jurisdiction + kind code number se PARSE hue (andaaza nahi)",
          metas[0].jurisdiction == "EP" and metas[0].kind_code == "B1",
          f"{metas[0].jurisdiction}/{metas[0].kind_code}")
    check("jo field provider ne nahi di wo KHAALI rahi",
          metas[0].priority_date == "" and metas[0].cpc == []
          and metas[0].legal_status == "")
    check("number na hone par URI se bana", metas[1].number == "EP3111111A1",
          metas[1].number)
    check("khaali payload par khaali list, crash nahi",
          pc.EpoLinkedDataConnector.parse({}) == []
          and pc.UsptoOdpConnector.parse({}) == [])

    status_row = {"results": {"bindings": [dict(EPO_FIXTURE["results"]["bindings"][0],
                                                legalStatus={"value": "granted"})]}}
    status_meta = pc.EpoLinkedDataConnector.parse(status_row)[0]
    check("status ke saath uska source bhi likha gaya",
          status_meta.legal_status == "granted"
          and "official publication nahi maanta" in status_meta.legal_status_source,
          status_meta.legal_status_source)

    sparql = pc.EpoLinkedDataConnector.build_query(QUERY, limit=5)
    check("FILTER usi variable par jo REQUIRED triple mein hai",
          "  ?publication patent:titleOfInvention ?title .\n" in sparql
          and "CONTAINS(LCASE(STR(?title))" in sparql)
    check("number OPTIONAL rakha (galat REQUIRED = chupchaap 0 result)",
          "OPTIONAL { ?publication patent:publicationNumber ?number }" in sparql)
    check("teen tak title term filter hue",
          2 <= sparql.count("CONTAINS(LCASE(STR(?title))") <= 3,
          str(sparql.count("CONTAINS(LCASE(STR(?title))")))
    check("LIMIT lagta hai", sparql.rstrip().endswith("LIMIT 5"))
    quoted = re.findall(r'"([^"]*)"', sparql)
    check("quote ke andar sirf safe chars (SPARQL injection band)",
          bool(quoted) and all(re.match(r"^[0-9a-z \-]*$", t) for t in quoted),
          str(quoted))

    nasty = pc.EpoLinkedDataConnector.build_query(
        'battery" } INSERT DATA { <x> <y> "z" } #', limit=3)
    nasty_quoted = re.findall(r'"([^"]*)"', nasty)
    check("gande input ke baad bhi quote ke andar sirf safe chars",
          all(re.match(r"^[0-9a-z \-]*$", t) for t in nasty_quoted),
          str(nasty_quoted))
    check("brace/quote query structure se bahar nahi nikle",
          "} INSERT" not in nasty and '"z"' not in nasty)
    check("term-less query par SPARQL banti hi nahi",
          pc.EpoLinkedDataConnector.build_query("?? !!") == "")

    numq = pc.EpoLinkedDataConnector.build_query("US11234567 prior art", limit=3)
    check("number wale sawaal mein filter NUMBER par (title par nahi)",
          "  ?publication patent:publicationNumber ?number .\n" in numq
          and 'CONTAINS(UCASE(STR(?number)), "US11234567")' in numq)
    check("number seedhe sawaal se nikla",
          pc.EpoLinkedDataConnector.number_in("US11234567 prior art")
          == "US11234567")
    check("comma/space/kind code wala number bhi normalize hua",
          pc.EpoLinkedDataConnector.number_in("EP 3,123,456 A1 ka status kya hai")
          == "EP3123456",
          pc.EpoLinkedDataConnector.number_in("EP 3,123,456 A1 ka status kya hai"))
    check("normal prose mein number 'dhoondh' nahi liya",
          pc.EpoLinkedDataConnector.number_in(
              "solid state battery electrode kaise banta hai") == "")
    check("URI se number parse hua",
          pc.EpoLinkedDataConnector.number_from_uri(EPO_URI) == "EP2777777B1")
    check("pattern na mile to URI ka aakhri tukda number nahi banaya",
          pc.EpoLinkedDataConnector.number_from_uri("https://example.org/a/b") == "")

    rec = pc.EpoLinkedDataConnector().to_record(metas[0], QUERY)
    check("source type PATENT (web/paper nahi)",
          rec.source_type == SourceType.PATENT and rec.is_patent)
    check("peer_reviewed jaan-boojh kar None (False bhi galat message hai)",
          rec.peer_reviewed is None)
    check("snippet par saaf label lagta hai",
          rec.snippet.startswith("ABSTRACT (patent ka summary):"),
          rec.snippet[:60])
    check("read level abstract (claims nahi aaye the)",
          rec.reading_level() == DEPTH_ABSTRACT, rec.reading_level())
    check("family key family id se bani (number se nahi)",
          rec.patent_family_key == "patfam:56789012", rec.patent_family_key)
    check("provider ka apna URL rakha gaya", rec.url == EPO_URI)
    check("inventors authors mein, assignee publisher mein",
          rec.authors == ["Tanaka Hiroshi", "Sato Kenji"]
          and rec.publisher == "Toyota Jidosha KK")
    check("doc kind saaf 'legal document' likha",
          rec.doc_kind == "patent" and "legal document" in rec.doc_kind_label)

    bare = pc.EpoLinkedDataConnector().to_record(
        PatentMeta(number="US9500001B2", title="Electrode assembly"), QUERY)
    check("text na mile to labelled METADATA ONLY line (khaali snippet nahi)",
          bare.snippet.startswith("METADATA ONLY"), bare.snippet[:40])
    check("metadata-only par read depth metadata hi rehta",
          bare.reading_level() == DEPTH_METADATA, bare.reading_level())
    check("provider URL na ho to Espacenet ka official public lookup",
          bare.url == "https://worldwide.espacenet.com/patent/search?q=US9500001B2",
          bare.url)
    guard_seen = pc.PatentProviderConnector.guard_text(bare)
    check("guard humare apne label ke shabd nahi ginta",
          "bibliographic" not in guard_seen.lower(), guard_seen[:80])
    check("...par patent ke apne facts ginta hai", "US9500001B2" in guard_seen)

    odp = pc.UsptoOdpConnector.parse(ODP_FIXTURE)
    check("ODP se ek meta bana (dict-nahi row chupchaap chhodi)", len(odp) == 1,
          str(len(odp)))
    check("ODP number ke aage US laga", odp[0].number == "US10987654",
          odp[0].number)
    check("legal status ke saath uska source",
          odp[0].legal_status == "Patented Case"
          and "uspto_odp" in odp[0].legal_status_source)
    check("family id jhoothi nahi banayi", odp[0].family_id == "")
    check("family id na hone par key priority+title par giri",
          family_key(odp[0])
          == "patpri:20160802:solid-state-lithium-battery-electrode",
          family_key(odp[0]))
    check("ODP par bhi publication date wahi jo provider ne diya",
          odp[0].publication_date == "2018-06-05" and odp[0].priority_date == "")
    check("cpc list waisi hi", odp[0].cpc == ["H01M10/0562"], str(odp[0].cpc))

    print("\n[2] Query + routing — kab patent search hoti hai, kab nahi")
    explicit = patent_intent("Kya is idea par pehle se koi patent hai — solid "
                             "state battery electrode?")
    check("seedha patent poocha to explicit intent",
          explicit["wanted"] and explicit["kind"] == "explicit",
          str(explicit))
    technical = patent_intent("Main ek solid state battery electrode banana "
                              "chahta hoon, existing approaches kya hain?")
    check("invention-jaisa sawaal to technical intent",
          technical["wanted"] and technical["kind"] == "technical",
          str(technical))
    generic = patent_intent("Solid state battery kya hoti hai aur kaise kaam "
                            "karti hai?")
    check("generic sawaal par patent search NAHI (bekaar API call)",
          not generic["wanted"] and "patent search yahan bekaar" in generic["reason"],
          generic["reason"])
    vague = patent_intent("Kya ye idea novel hai?")
    check("iraada hai par koi technical cheez nahi → search nahi",
          not vague["wanted"]
          and "koi technical cheez nahi" in vague["reason"], vague["reason"])
    check("khaali sawaal par wajah bhi khaali-honest",
          patent_intent("")["reason"] == "sawaal khaali hai")

    planner = ResearchPlanner()
    invention_q = ("Main ek solid state lithium battery electrode banana chahta "
                   "hoon — prior art kya hai?")
    cls = planner.classify(invention_q)
    deep_plan = planner.connector_plan(cls, DEEP, invention_q)
    check("DEEP + invention sawaal par keyless EPO plan mein aaya",
          "epo_lod" in deep_plan["patents"], str(deep_plan["patents"]))
    check("key wala provider SIRF key hone par plan mein",
          ("uspto_odp" in deep_plan["patents"])
          == bool(pc.UsptoOdpConnector.api_key()), str(deep_plan["patents"]))
    check("plan mein patent routing ki wajah likhi hai",
          bool(deep_plan["patent_intent"]["reason"])
          and deep_plan["patent_intent"]["wanted"] is True)
    quick_plan = planner.connector_plan(cls, QUICK, invention_q)
    check("QUICK mode mein patent tier khaali",
          quick_plan["patents"] == [] and not quick_plan["patent_intent"]["wanted"])
    check("QUICK par bhi wajah likhi (chupchaap band nahi)",
          "band hai" in quick_plan["patent_intent"]["reason"],
          quick_plan["patent_intent"]["reason"])
    generic_plan = planner.connector_plan(
        planner.classify("Solid state battery kya hoti hai?"), DEEP,
        "Solid state battery kya hoti hai?")
    check("generic sawaal ke plan mein patent connector nahi",
          generic_plan["patents"] == [], str(generic_plan["patents"]))

    discovery = SourceDiscovery()
    three_queries = ["q one", "q two", "q three"]
    check("patents khaali ho to discovery task hi nahi banta",
          [lbl for lbl, _ in discovery._tasks(three_queries,
                                              {"web": False, "patents": []}, 3, 3)]
          == [])
    labels = [lbl for lbl, _ in discovery._tasks(
        three_queries, {"web": False, "patents": ["epo_lod"]}, 3, 3)]
    check("teen query par bhi patent connector sirf EK baar (fair use)",
          labels == ["epo_lod"], str(labels))

    print("\n[3] Patent family dedup — ek invention = ek evidence")
    us_meta, ep_meta, wo_meta = _family_trio()
    trio = [_record(us_meta, "S1"), _record(ep_meta, "S2"),
            _record(wo_meta, "S3")]
    check("teeno ki family key ek hi",
          len({r.patent_family_key for r in trio}) == 1,
          str([r.patent_family_key for r in trio]))
    engine = DeduplicationEngine()
    report = engine.patent_family_report(trio)
    check("family report sach bolti hai (3 patent, 1 family, 2 collapse)",
          report == {"patent_sources": 3, "families": 1, "collapsed": 2,
                     "unknown_family": 0}, str(report))
    collapsed = engine.collapse_patent_families(trio)
    check("teen publication ek record ban gayi", len(collapsed) == 1,
          str(len(collapsed)))
    survivor = collapsed[0]
    check("survivor wahi jiska text sabse gehra padha gaya (EP = claims)",
          survivor.source_id == "S2"
          and survivor.reading_level() == DEPTH_CLAIMS,
          f"{survivor.source_id}/{survivor.reading_level()}")
    members = survivor.patent_meta.get("family_members") or []
    check("gire hue members chupchaap gayab nahi hue",
          {m["number"] for m in members} == {"US9500001B2", "WO2015012345A1"},
          str([m.get("number") for m in members]))
    check("har member ka apna read depth likha",
          all(m.get("read_depth") for m in members), str(members))
    check("read note mein saaf likha ki ye alag source nahi gina gaya",
          "same family" in (survivor.read_note or ""), survivor.read_note or "")

    # Trap 8 — ek hi assignee ke DO ALAG invention. Family alag hai, isliye
    # merge karna sabse bada jhooth hota (do inventions = ek dikhne lagte).
    other_invention = PatentMeta(
        number="US9600002B2", title="Cooling plate for battery module housing",
        assignee="Toyota Jidosha KK", family_id="99999999",
        filing_date="2015-03-11", abstract=LONG_ABSTRACT)
    pair = [_record(ep_meta, "S1"), _record(other_invention, "S2")]
    check("same assignee par bhi alag family alag hi rahi",
          len(engine.collapse_patent_families(pair)) == 2)

    # Trap 9 — translated/badla hua title. Title rule inhe pakad hi nahi sakta;
    # family id pakadti hai.
    german = PatentMeta(
        number="DE102014123456A1",
        title="Festkoerperbatterie mit keramischem Separator",
        family_id="56789012", filing_date="2014-07-21", abstract=LONG_ABSTRACT)
    translated = [_record(ep_meta, "S1"), _record(german, "S2")]
    check("translated title bhi family se ek hi gina gaya",
          len(engine.collapse_patent_families(translated)) == 1)

    # Trap: 1996 ka prior art jiska TITLE slug same hai par family/priority alag.
    old_same_title = PatentMeta(
        number="US5600003A", title="Solid state lithium battery electrode with "
                                   "ceramic coating",
        filing_date="1996-02-14", abstract=LONG_ABSTRACT)
    new_no_family = PatentMeta(
        number="US9700004B2", title="Solid state lithium battery electrode with "
                                    "ceramic separator sheet",
        filing_date="2016-02-14", abstract=LONG_ABSTRACT)
    old_new = [_record(old_same_title, "S1"), _record(new_no_family, "S2")]
    check("purana prior art naye patent mein merge NAHI hua",
          len(engine.collapse_patent_families(old_new)) == 2,
          f"{family_key(old_same_title)} vs {family_key(new_no_family)}")

    # Paper aur patent ka title ek jaisa ho sakta hai — dono bachne chahiye,
    # warna patent-vs-paper ka disagreement hi chhup jaata.
    twin = [_record(ep_meta, "S1"),
            _paper("S2", "Solid state lithium battery electrode with ceramic "
                         "separator", LONG_ABSTRACT, "nature.com")]
    check("ek jaise title wale paper aur patent dono bache",
          len(engine.deduplicate(twin)) == 2)

    blanks = [_record(PatentMeta(number="", title=""), "S1"),
              _record(PatentMeta(number="", title=""), "S2")]
    check("family ka pata hi na ho to merge nahi (do alag invention ho sakte)",
          len(engine.collapse_patent_families(blanks)) == 2)
    check("unknown family report mein ginti hui",
          engine.patent_family_report(blanks)["unknown_family"] == 2,
          str(engine.patent_family_report(blanks)))

    ranked_input = trio + [
        _paper("S4", "Sintered garnet separator for lithium metal anodes",
               LONG_ABSTRACT, "nature.com")]
    rel = RelevanceEngine()
    rel.rank(list(ranked_input), QUERY, max_sources=10)
    filt = rel.last_filter
    check("report mein patent family ka poora hisaab jaata hai",
          filt.get("patent_sources_found") == 3
          and filt.get("patent_families") == 1
          and filt.get("patent_family_duplicates_removed") == 2
          and filt.get("patent_family_unknown") == 0,
          json.dumps({k: v for k, v in filt.items() if "patent" in k}))

    print("\n[4] Source type + read depth — 'patent padha' kab kehna banta hai")
    only_meta = PatentMeta(number="US1", title="X")
    thin_abs = PatentMeta(number="US2", title="X",
                          abstract="a" * (MIN_ABSTRACT_CHARS - 1))
    ok_abs = PatentMeta(number="US3", title="X",
                        abstract="a" * MIN_ABSTRACT_CHARS)
    thin_claims = PatentMeta(number="US4", title="X", abstract=LONG_ABSTRACT,
                             claims_text="1. " + "c" * (MIN_CLAIMS_CHARS - 4))
    ok_claims = PatentMeta(number="US5", title="X", abstract=LONG_ABSTRACT,
                           claims_text="1. " + "c" * MIN_CLAIMS_CHARS)
    thin_desc = PatentMeta(number="US6", title="X", abstract=LONG_ABSTRACT,
                           claims_text=CLAIMS_TEXT,
                           description_text="d" * (MIN_DESCRIPTION_CHARS - 1))
    ok_desc = PatentMeta(number="US7", title="X", abstract=LONG_ABSTRACT,
                         claims_text=CLAIMS_TEXT,
                         description_text=DESCRIPTION_TEXT)
    check("kuch text na ho to depth metadata",
          only_meta.read_depth() == DEPTH_METADATA)
    check("threshold se ek char kam abstract = abstract nahi",
          thin_abs.read_depth() == DEPTH_METADATA)
    check("threshold par abstract", ok_abs.read_depth() == DEPTH_ABSTRACT)
    check("adhoora claims text claims nahi maana gaya",
          thin_claims.read_depth() == DEPTH_ABSTRACT)
    check("poora claims text = claims depth",
          ok_claims.read_depth() == DEPTH_CLAIMS)
    check("adhoori description full_text nahi bani",
          thin_desc.read_depth() == DEPTH_CLAIMS)
    check("poori description = full_text", ok_desc.read_depth() == DEPTH_FULL)
    check("claims sirf line-start numbers se gine (bich ka 'claim 1' nahi)",
          PatentMeta(number="US8", claims_text=CLAIMS_TEXT).claim_count() == 3,
          str(PatentMeta(number="US8", claims_text=CLAIMS_TEXT).claim_count()))
    check("claims text bina number ho to bhi 0 nahi bolta",
          PatentMeta(number="US9", claims_text="A battery comprising X.").claim_count() == 1)
    check("claims text hi na ho to 0", only_meta.claim_count() == 0)
    check("read note metadata-only par saaf",
          "sirf bibliographic metadata mila" in only_meta.read_note(),
          only_meta.read_note())
    check("read note mein 'claims text nahi mila' likha jaata hai",
          "claims text nahi mila" in ok_abs.read_note(), ok_abs.read_note())
    check("claims process hue to ginti ke saath likha",
          "3 claims process hue" in ok_desc.read_note(), ok_desc.read_note())

    long_snip = _record(only_meta, "S1")
    long_snip.snippet = "x" * 5000
    long_snip.read_level = ""
    check("lamba snippet se depth 'full_text' nahi ban jaata",
          long_snip.reading_level() == DEPTH_METADATA, long_snip.reading_level())

    deep_pack = _pack([_record(ep_meta, "S1"),
                       _paper("S2", "Garnet separator study", LONG_ABSTRACT,
                              "nature.com")])
    check("pack patent aur science ko alag ginta hai",
          len(deep_pack.patent_sources()) == 1
          and len(deep_pack.science_sources()) == 1)
    check("read depth counts patent ke hisaab se",
          deep_pack.patent_read_depth_counts() == {DEPTH_CLAIMS: 1},
          str(deep_pack.patent_read_depth_counts()))
    check("claims process hue to note wahi kehta",
          "claims/description sach mein" in deep_pack.patent_note(),
          deep_pack.patent_note()[:120])
    shallow_pack = _pack([_record(us_meta, "S1"),
                          _paper("S2", "Garnet separator study", LONG_ABSTRACT,
                                 "nature.com")])
    check("claims process na hue to 'patent padha' ka dawa mana kiya gaya",
          "'patent padha' jaisa dawa is jawab mein nahi banta"
          in shallow_pack.patent_note(), shallow_pack.patent_note()[:200])
    patent_only = _pack([_record(ep_meta, "S1"), _record(us_meta, "S2")])
    check("sirf patent wale pack par CHETAVANI",
          "CHETAVANI" in patent_only.patent_note(),
          patent_only.patent_note()[-160:])
    check("do publication ek family = ek invention gina gaya",
          patent_only.patent_family_count() == 1,
          str(patent_only.patent_family_count()))

    patent_sources_text = FinalSynthesizer()._sources_section(deep_pack)
    # EXPECTATION JAAN-BOOJH KAR BADLI GAYI (§9, 2026-08-22).
    # Pehle yahan "PATENT CLAIMS REVIEWED" maanga jaata tha. §9 ke baad access
    # depth ka vocabulary sirf paanch label ka hai (models.ACCESS_DEPTH_LABELS)
    # aur patent ke claims poora document nahi hote — wo document ka chuna hua
    # hissa hai, isliye label `RELEVANT SECTIONS REVIEWED` hai. Test ka ASLI
    # maqsad wahi hai jo pehle tha aur wo abhi bhi check hota hai: (a) andar ka
    # raw token "claims" user ko nahi dikhta, (b) patent ko legal dawa kaha
    # jaata hai, scientific proof nahi (agla check).
    check("patent claims ka raw technical label user ko nahi dikhaya",
          "RELEVANT SECTIONS REVIEWED" in patent_sources_text
          and "Kitna padha gaya: claims." not in patent_sources_text,
          patent_sources_text[-500:])
    check("patent source scientific proof se alag explain hua",
          "legal dawe" in patent_sources_text
          and "scientific result nahi" in patent_sources_text,
          patent_sources_text[-500:])

    cov = deep_pack.coverage_report()
    check("coverage report mein patent ke saare khaane",
          all(k in cov for k in ("patent_sources", "patent_families",
                                 "patent_read_levels", "science_sources",
                                 "patent_note")), str(sorted(cov.keys())))
    check("coverage ki ginti sach", cov["patent_sources"] == 1
          and cov["patent_families"] == 1 and cov["science_sources"] == 1)
    access_text = FinalSynthesizer._access_block(cov, deep_pack)
    check("access summary claims-depth source ko total mein ginta hai",
          "patent ke claims process hue" in access_text and "kul 2 sources" in access_text,
          access_text)
    no_patent_cov = _pack([_paper("S1", "Garnet separator study", LONG_ABSTRACT,
                                  "nature.com")]).coverage_report()
    check("patent-mukt pack mein bhi khaane maujood, par khaali",
          no_patent_cov["patent_sources"] == 0
          and no_patent_cov["patent_note"] == ""
          and no_patent_cov["patent_read_levels"] == {},
          str({k: v for k, v in no_patent_cov.items() if "patent" in k}))

    print("\n[5] Relevance traps — same keyword, alag invention")
    epo = pc.EpoLinkedDataConnector()
    on_topic = epo.to_record(metas[0], QUERY)
    off_topic = epo.to_record(metas[1], QUERY)      # hair dryer (battery pack)
    kept = pc.PatentProviderConnector.relevance_guard([on_topic, off_topic],
                                                      QUERY)
    check("ek shabd ('battery') match hone par hair dryer nahi bacha",
          [r.title for r in kept] == [on_topic.title],
          str([r.title for r in kept]))
    epo.last_reason = ""
    epo.last_note = ""
    all_dropped = epo._finish([off_topic], 1, QUERY)
    check("sab guard ne hataye to reason 'filtered' (0 mila nahi)",
          all_dropped == [] and epo.last_reason == "filtered", epo.last_reason)
    check("note saaf farak batata hai",
          "relevance guard ne hataye" in epo.last_note
          and "'0 patent mila' se alag" in epo.last_note, epo.last_note)
    epo.last_reason = ""
    epo.last_note = ""
    part_dropped = epo._finish([on_topic, off_topic], 2, QUERY)
    check("kuch bache to reason filtered nahi hota, par ginti note mein",
          len(part_dropped) == 1 and epo.last_reason == ""
          and "1 patent topic se door the" in epo.last_note, epo.last_note)

    old_art = PatentMeta(number="US5700005A",
                         title="Solid state lithium battery electrode with "
                               "ceramic separator plate",
                         publication_date="1998-03-10",
                         filing_date="1996-11-02", abstract=LONG_ABSTRACT)
    old_rec = epo.to_record(old_art, QUERY)
    check("purana prior art topic par hai to bachta hai (saal se nahi girta)",
          pc.PatentProviderConnector.relevance_guard([old_rec], QUERY) == [old_rec]
          and old_rec.year == 1998, str(old_rec.year))

    thin = PatentMeta(number="US5800006A", title="Electrode structure")
    thin_rec = epo.to_record(thin, QUERY)
    gaps = thin_rec.patent_meta.get("missing_fields") or []
    check("adhoora metadata chhupaya nahi, naam se likha gaya",
          {"assignee", "filing_date", "family_id", "legal_status"} <= set(gaps),
          str(gaps))
    check("adhoore field bhare nahi gaye",
          thin_rec.publisher == "" and thin_rec.year is None
          and thin_rec.patent_meta.get("family_key") == "patno:us5800006",
          str(thin_rec.patent_meta.get("family_key")))

    print("\n[6] Legal status — na mile to andaaza nahi")
    check("status na ho to label khud batata hai ki provider ne nahi diya",
          "provider ne nahi diya" in thin.status_label()
          and "maan lena galat hoga" in thin.status_label(),
          thin.status_label())
    check("status ho to uska source saath mein",
          us_meta.status_label()
          == "legal status: Patented Case (source: uspto_odp (USPTO Open Data "
             "Portal))", us_meta.status_label())
    sourceless = PatentMeta(number="US1", legal_status="granted")
    check("status ho par source na ho to jhootha source nahi joda",
          sourceless.status_label() == "legal status: granted",
          sourceless.status_label())

    print("\n[7] Patent ≠ scientific proof — teen alag gate")
    full_patent = PatentMeta(number="EP2777777B1",
                             title="Solid state lithium battery electrode",
                             family_id="56789012", abstract=LONG_ABSTRACT,
                             claims_text=CLAIMS_TEXT,
                             description_text=DESCRIPTION_TEXT)
    p_full = _record(full_patent, "S1")
    check("patent ka poora text bhi full_text depth deta hai",
          p_full.reading_level() == DEPTH_FULL, p_full.reading_level())
    patent_pack = _pack([p_full])
    line = "[ESTABLISHED] Ceramic separator lithium dendrite rok deta hai [S1]"
    verdict, why = line_verdict(line, patent_pack)
    check("patent full text par bhi label SOURCE-REPORTED",
          verdict == SOURCE_REPORTED, f"{verdict} / {why}")
    check("wajah mein saaf likha ki claims LEGAL dawe hain",
          "LEGAL dawe" in why, why)
    new_text, dg = downgrade(line, patent_pack)
    check("[ESTABLISHED] badal kar [SOURCE-REPORTED] hua",
          "[SOURCE-REPORTED]" in new_text and "[ESTABLISHED]" not in new_text,
          new_text)
    check("downgrade ki ginti report mein", dg["downgraded"] == 1
          and dg["checked"] == 1, json.dumps(dg))
    check("text kaata nahi gaya, sirf label badla",
          "Ceramic separator lithium dendrite rok deta hai [S1]" in new_text)

    paper_full = _paper("S2", "Dendrite suppression in garnet separators",
                        LONG_ABSTRACT, "nature.com", level="full_text")
    mixed_pack = _pack([p_full, paper_full])
    v2, why2 = line_verdict(
        "[ESTABLISHED] Ceramic separator dendrite rokta hai [S1] [S2]",
        mixed_pack)
    check("non-patent full text apne bal par ESTABLISHED de sakta hai",
          v2 == ESTABLISHED, f"{v2} / {why2}")

    d_patent = check_d([p_full])
    check("check D: sirf patent = UNKNOWN (PASS nahi)",
          d_patent.status == V_UNKNOWN and "genuine support" in d_patent.detail,
          f"{d_patent.status} / {d_patent.detail}")
    d_thin = check_d([_record(us_meta, "S1")])
    check("metadata/abstract wale patent par saaf likha claims process nahi hue",
          d_thin.status == V_UNKNOWN
          and "claims process hi nahi hue" in d_thin.detail, d_thin.detail)
    d_mixed = check_d([p_full, paper_full])
    check("paper ka full text ho to D PASS, patent 'sirf context'",
          d_mixed.status == V_PASS and "sirf context" in d_mixed.detail,
          f"{d_mixed.status} / {d_mixed.detail}")

    def _gate(pack):
        return evaluate(pack, contradictions=[], contradiction_analysis_done=True,
                        reasoning_complete=True, opposition_searched=True,
                        queries=GOOD_QUERIES, independent_sources=4).to_dict()

    only_patents = _gate(_pack([p_full, _record(us_meta, "S2")]))
    check("sirf patent wale pack par 'science_beyond_patents' unmet",
          "science_beyond_patents" in only_patents["unmet"],
          str(only_patents["unmet"]))
    with_science = _gate(_pack([
        p_full,
        _paper("S2", "Garnet separator dendrite study", LONG_ABSTRACT,
               "nature.com"),
        _paper("S3", "Sintering of ceramic electrolytes", LONG_ABSTRACT,
               "science.org"),
        _paper("S4", "Lithium metal anode cycling", LONG_ABSTRACT, "acs.org")]))
    check("teen scientific source aa jaayen to wo shart poori",
          "science_beyond_patents" not in with_science["unmet"],
          str(with_science["unmet"]))
    check("...par shart list mein dikhti hai (audit ke liye)",
          "science_beyond_patents" in [c["condition"]
                                       for c in with_science["checks"]])
    no_patents = _gate(_pack([
        _paper("S1", "Garnet separator dendrite study", LONG_ABSTRACT,
               "nature.com")]))
    check("patent-mukt pack par ye shart lagti hi nahi",
          "science_beyond_patents" not in [c["condition"]
                                           for c in no_patents["checks"]])

    reasoner = GeminiReasoning.__new__(GeminiReasoning)
    with_rule = GeminiReasoning.prompt_analysis(reasoner, "Sawaal?",
                                                patent_pack, {})
    without_rule = GeminiReasoning.prompt_analysis(
        reasoner, "Sawaal?",
        _pack([_paper("S1", "Garnet separator study", LONG_ABSTRACT,
                      "nature.com")]), {})
    check("patent wale pack ke prompt mein PATENT RULE jaata hai",
          "# PATENT RULE" in with_rule)
    check("patent na ho to prompt mein wo block nahi (bekaar tokens nahi)",
          "# PATENT RULE" not in without_rule)

    print("\n[8] Provider failure / quota — crash nahi, raw error leak nahi")

    class _Timeout(Exception):
        pass

    _Timeout.__name__ = "ReadTimeout"

    def _raiser(exc):
        def _call(*a, **kw):
            raise exc
        return _call

    calls: List[Dict] = []

    def _recorder(payload):
        def _call(url, params=None, timeout=None, headers=None, retries=None):
            calls.append({"url": url, "params": dict(params or {}),
                          "headers": dict(headers or {}), "retries": retries})
            return _Resp(payload)
        return _call

    try:
        cases = [
            ("rate_limited", RateLimited("HTTP 429 — is API ne rate limit lagayi")),
            ("blocked", AccessBlocked("HTTP 403 — server ne access nahi diya")),
            ("error", ValueError("provider ne kachra JSON bheja")),
            ("timeout", _Timeout("read timed out")),
        ]
        for expected, exc in cases:
            pc.http_get = _raiser(exc)
            out = pc.EpoLinkedDataConnector().safe_search(QUERY, 3)
            check(f"{expected}: crash nahi, reason theek",
                  out["reason"] == expected and out["count"] == 0
                  and out["records"] == [], f"{out['reason']} / {out['error']}")
            check(f"{expected}: reason vocabulary ke andar hai",
                  out["reason"] in {"no_key", "rate_limited", "blocked", "error",
                                    "timeout", "filtered", "no_query"})

        pc.http_get = _raiser(RuntimeError("ye kabhi call nahi honi chahiye"))
        no_key_out = pc.UsptoOdpConnector().safe_search(QUERY, 3)
        if pc.UsptoOdpConnector.api_key():
            check("key set hai to ODP skip nahi hota (env-aware)",
                  no_key_out["reason"] != "no_key", no_key_out["reason"])
        else:
            check("key na ho to reason 'no_key' (0 mila nahi)",
                  no_key_out["reason"] == "no_key", no_key_out["reason"])
            check("error line saaf kehti hai ki connector chala hi nahi",
                  "chala hi nahi" in no_key_out["error"], no_key_out["error"])

        empty_q = pc.EpoLinkedDataConnector().safe_search("?? !!", 3)
        check("kaam ka term na bane to reason 'no_query' (network gaya hi nahi)",
              empty_q["reason"] == "no_query" and empty_q["count"] == 0,
              empty_q["reason"])

        off_payload = {"results": {"bindings": [
            EPO_FIXTURE["results"]["bindings"][2]]}}
        pc.http_get = _recorder(off_payload)
        filtered = pc.EpoLinkedDataConnector().safe_search(QUERY, 3)
        check("sab off-topic nikle to reason 'filtered'",
              filtered["reason"] == "filtered" and filtered["count"] == 0,
              f"{filtered['reason']} / {filtered['note']}")

        calls.clear()
        pc.http_get = _recorder(EPO_FIXTURE)
        good = pc.EpoLinkedDataConnector().safe_search(QUERY, 3)
        check("happy path: on-topic patent aaya, hair dryer nahi",
              good["count"] == 1 and good["records"][0].is_patent,
              str(good["count"]))
        check("call sirf official EPO endpoint par gayi",
              calls and calls[0]["url"] == "https://data.epo.org/linked-data/query",
              str([c["url"] for c in calls]))
        check("EPO par retry BAND (apna hi fair-use quota na khaye)",
              calls[0]["retries"] == 0, str(calls[0]["retries"]))
    finally:
        pc.http_get = _REAL_HTTP_GET

    dummy = "dummy-odp-key-not-a-real-secret"
    try:
        os.environ["USPTO_ODP_API_KEY"] = dummy
        calls.clear()
        pc.http_get = _recorder(ODP_FIXTURE)
        odp_out = pc.UsptoOdpConnector().safe_search(QUERY, 3)
        check("key ho to ODP chalta hai aur patent laata hai",
              odp_out["count"] == 1 and odp_out["reason"] == "",
              f"{odp_out['count']} / {odp_out['reason']}")
        check("key SIRF request header mein gayi",
              calls and calls[-1]["headers"].get("X-API-KEY") == dummy,
              str(sorted((calls[-1]["headers"] if calls else {}).keys())))
        log_blob = json.dumps({k: v for k, v in odp_out.items() if k != "records"})
        record_blob = json.dumps([{"title": r.title, "url": r.url,
                                   "snippet": r.snippet, "note": r.read_note,
                                   "meta": r.patent_meta}
                                  for r in odp_out["records"]], default=str)
        check("key ki value log/report mein kahin nahi",
              dummy not in log_blob and dummy not in record_blob)
        check("URL/params mein bhi key nahi gayi",
              dummy not in json.dumps(calls[-1]["params"]) + calls[-1]["url"])
    finally:
        pc.http_get = _REAL_HTTP_GET
        if _ORIG_ODP_KEY is None:
            os.environ.pop("USPTO_ODP_API_KEY", None)
        else:
            os.environ["USPTO_ODP_API_KEY"] = _ORIG_ODP_KEY

    print("\n[9] No-network proof — http_get raiser hote hue bhi sab chalta hai")
    try:
        pc.http_get = _raiser(AssertionError("test mein network nahi chalega"))
        offline_metas = pc.EpoLinkedDataConnector.parse(EPO_FIXTURE)
        offline_rec = pc.EpoLinkedDataConnector().to_record(offline_metas[0], QUERY)
        offline_ok = (
            len(offline_metas) == 2
            and pc.EpoLinkedDataConnector.build_query(QUERY, limit=5).startswith("PREFIX")
            and offline_rec.source_type == SourceType.PATENT
            and family_key(offline_metas[0]) == "patfam:56789012"
            and patent_intent("Kya is electrode par patent hai?")["wanted"]
            and len(DeduplicationEngine().deduplicate(
                [_record(us_meta, "S1"), _record(ep_meta, "S2")])) == 1)
        check("parse/query/record/family/intent/dedup — sab bina network chale",
              offline_ok)
    finally:
        pc.http_get = _REAL_HTTP_GET

    print("\n[10] Novelty honesty — 'patent nahi mila' ≠ 'idea novel hai'")
    hits_note = novelty_note(3, providers_searched=["epo_lod"], families=1)
    check("mile to publications vs families ka farak likha",
          "3 prior-art signal mile" in hits_note
          and "1 alag invention families" in hits_note, hits_note[:160])
    zero_note = novelty_note(0, providers_searched=["epo_lod"],
                             providers_stopped=["uspto_odp"])
    check("0 mila to bhi 'novel hai' nahi bola",
          "'idea novel hai' nahi hai" in zero_note, zero_note[:200])
    check("jo provider chala hi nahi wo naam se likha",
          "uspto_odp" in zero_note, zero_note)
    never_note = novelty_note(0, providers_searched=[],
                              providers_stopped=["epo_lod"])
    check("search chali hi na ho to wahi likha (0 result nahi)",
          never_note.startswith("Patent search CHALI HI NAHI."), never_note[:80])
    check("teeno haalat mein legal disclaimer saath jaata hai",
          all("patentability ki opinion NAHI hai" in n
              for n in (hits_note, zero_note, never_note)))

    overclaims = novelty_overclaim(
        "Is idea novel hai aur ye patentable lagta hai; no prior art mila, "
        "yaani first of its kind hai.")
    check("novelty/patentability ka dawa pakda gaya",
          len(overclaims) >= 4, str(overclaims))
    check("normal scientific baat par jhoothi warning nahi",
          novelty_overclaim(
              "Ceramic separator ki ionic conductivity is study mein 1.2 mS/cm "
              "napi gayi, aur do aur groups ne isi range mein result diya.") == [],
          str(novelty_overclaim("Ceramic separator ki ionic conductivity")))

    print("\n[11] Determinism — ek hi input, hamesha ek hi output")
    q1 = pc.EpoLinkedDataConnector.build_query(QUERY, limit=5)
    q2 = pc.EpoLinkedDataConnector.build_query(QUERY, limit=5)
    check("SPARQL har baar bit-for-bit same", q1 == q2)
    p1 = [m.to_dict() for m in pc.EpoLinkedDataConnector.parse(EPO_FIXTURE)]
    p2 = [m.to_dict() for m in pc.EpoLinkedDataConnector.parse(EPO_FIXTURE)]
    check("parse ka output same", json.dumps(p1, sort_keys=True, default=str)
          == json.dumps(p2, sort_keys=True, default=str))
    check("family key same", family_key(ep_meta) == family_key(ep_meta))
    i1 = patent_intent("Main solid state battery electrode banana chahta hoon")
    i2 = patent_intent("Main solid state battery electrode banana chahta hoon")
    check("routing ka faisla same", i1 == i2)
    d1 = [r.source_id for r in DeduplicationEngine().deduplicate(
        [_record(us_meta, "S1"), _record(ep_meta, "S2"), _record(wo_meta, "S3")])]
    d2 = [r.source_id for r in DeduplicationEngine().deduplicate(
        [_record(us_meta, "S1"), _record(ep_meta, "S2"), _record(wo_meta, "S3")])]
    check("dedup ka survivor har baar wahi", d1 == d2 == ["S2"],
          f"{d1} / {d2}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_patents_all_checks_pass():
    """pytest entry point — poora offline suite ek test ke roop mein."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
