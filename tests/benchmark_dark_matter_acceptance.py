"""
§24 — DARK MATTER ACCEPTANCE BENCHMARK (poora OFFLINE, ₹0).

Kyun ye file: live dark-matter run mein app ne 17 alag jhooth bole the — 18
source retrieve kiye par sirf 9 cite kiye, ausat relevance 0.43 par bhi
"✅ VERIFIED" likh diya, telescope-calibration aur exoplanet ke paper evidence
bana diye, CMB/BBN/Bullet Cluster jaise zaroori raaste dhoondhe hi nahi, 14
line par [NO-SOURCE] tha, counter-search chali hi nahi, sirf saal ke farq ko
"contradiction" bataya, PBH/MOND/dark-photon ko "humari nayi hypothesis" kaha,
adhoore jawab ko COMPLETE kaha, raw 429/504 jawab mein chhap gaya, recovery
footer do baar aaya, aur Calculations section gayab ho gaya.

Ye benchmark un 17 failures ko ek acceptance matrix bana deta hai: DM-01 se
DM-17. Har group ek hi live galti ka darwaaza band karta hai. Fixtures wahi
jaal dohraate hain jo live run mein the.

Chalao:  PYTHONPATH=. python3 tests/benchmark_dark_matter_acceptance.py

Harness (DomainCase / fake model / stub discovery) `benchmark_cross_domain`
se import hota hai — us file mein kuch badla NAHI gaya. Koi network, koi API
key, koi paid provider: saare source fixture hain aur Gemini ki jagah wahi
fake model hai jo apna prompt padh kar jawab banata hai.
"""
from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from typing import Dict, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # backend/
sys.path.insert(0, _HERE)                    # tests/ — harness import ke liye

from benchmark_cross_domain import (RAW_TOKENS, DomainCase, Row,  # noqa: E402
                                    _by_tag, _human_part, _heading_pos,
                                    _pick_rows, _run, _titles, full_text_urls)
from research_engine.answer_order import (LAB_HEADING,            # noqa: E402
                                          display_heading)
from research_engine.consensus_gate import (CONSENSUS_UNAVAILABLE,  # noqa: E402
                                            opposition_in_queries)
from research_engine.contradiction import ContradictionEngine    # noqa: E402
from research_engine.models import (ACCESS_DEPTH_ALLOWED,        # noqa: E402
                                    ACCESS_FULL, EvidencePack,
                                    NOVELTY_POSSIBLE, NOVELTY_STATES,
                                    SourceRecord, SourceType)
from research_engine.quality_producers import (BANNED_ACCESS_LABEL,  # noqa: E402
                                               DIRECT_RELEVANCE_FLOOR,
                                               TRISTATE_FIELDS,
                                               context_block)

# ── acceptance matrix: har ID ek live failure ────────────────────────────────
FAILURE_IDS: Tuple[Tuple[str, str], ...] = (
    ("DM-01", "off-topic paper (calibration/exoplanet/genome) evidence nahi bana"),
    ("DM-02", "retrieved vs cited ki ginti alag-alag aur imaandaar"),
    ("DM-03", "kamzor average relevance par VERIFIED nahi"),
    ("DM-04", "chhoote hue evidence raaste 'missing' likhe gaye, chup nahi rahe"),
    ("DM-05", "[NO-SOURCE] par koi strong claim nahi"),
    ("DM-06", "counter-search consensus se PEHLE sach mein chali"),
    ("DM-07", "mirror copy independent source nahi gini"),
    ("DM-08", "sirf saal ke farq ko contradiction nahi kaha"),
    ("DM-09", "PBH/MOND/dark-photon kabhi 'POSSIBLY NOVEL' nahi"),
    ("DM-10", "APP ORIGINAL RESEARCH LAB alag, evidence se mix nahi"),
    ("DM-11", "quota khatam hone par status imaandaar (COMPLETE nahi)"),
    ("DM-12", "raw 429/504/traceback jawab mein nahi"),
    ("DM-13", "recovery footer / heading dobara nahi chhapta"),
    ("DM-14", "calculation ka dava tabhi jab hisaab SACH mein hua"),
    ("DM-15", "access-depth ka overclaim nahi (FULL-TEXT VERIFIED banned)"),
    ("DM-16", "retracted paper flag hua ya bahar, strong claim mein nahi"),
    ("DM-17", "audit mein 'check nahi hua' — 0 ka jhooth nahi"),
)
_LABELS: Dict[str, str] = dict(FAILURE_IDS)

PASSED = 0
FAILED = 0
SCORE: Dict[str, List[int]] = {k: [0, 0] for k, _ in FAILURE_IDS}
FAILURES: Dict[str, List[str]] = {}
_CTX = {"id": "DM-00"}


@contextmanager
def dm(failure_id: str):
    """Har check ko uske live-failure khaate mein daalo."""
    old = _CTX["id"]
    _CTX["id"] = failure_id
    print("\n-- %s : %s" % (failure_id, _LABELS.get(failure_id, "?")))
    try:
        yield
    finally:
        _CTX["id"] = old


def check(label: str, cond: bool, extra: str = "") -> bool:
    global PASSED, FAILED
    ok = bool(cond)
    cell = SCORE.setdefault(_CTX["id"], [0, 0])
    cell[0 if ok else 1] += 1
    if ok:
        PASSED += 1
        print("  [PASS] %s" % label)
    else:
        FAILED += 1
        print("  [FAIL] %s%s" % (label, (" -> " + extra) if extra else ""))
        FAILURES.setdefault(_CTX["id"], []).append(label)
    return ok


def eq(label: str, got, want) -> bool:
    return check(label, got == want, "got=%r want=%r" % (got, want))

# ── live run ka sawaal + wahi jaal ───────────────────────────────────────────
QUESTION = ("Dark matter ke baare mein ab tak ka sabse mazboot evidence kya "
            "hai — galaxy rotation curves, gravitational lensing, CMB power "
            "spectrum aur Bullet Cluster observations kya kehte hain, aur "
            "kaunse dave abhi confirm nahi hue?")

DARK_MATTER = DomainCase(
    key="darkmatter", label="Dark matter evidence",
    question=QUESTION,
    expect_domain="space", strict=True,
    intents=("observational", "simulation", "instrument"),
    top_words=("rotation", "dark matter", "halo", "lensing", "cosmic"),
    connector="arxiv", junk_connector="pubmed",
    sources=(
        ("core_full",
         "Dark matter halo mass profiles from the rotation curves of 175 disc galaxies",
         "For 175 disc galaxies with resolved 21 cm rotation curves, the outer rotation velocity stays flat near 220 km/s instead of falling as the visible mass alone predicts. The best fitting dark matter halo contributes 5.4 times more mass than the stars and gas inside 30 kpc, and baryon only models are rejected for 168 of the 175 galaxies. The halo concentration is degenerate with the assumed mass to light ratio, which the authors state as the main systematic."),
        ("core_abs",
         "Planck CMB power spectrum: cold dark matter density and the acoustic peak ratio",
         "The measured temperature power spectrum of the cosmic microwave background gives a cold dark matter density of Omega_c h^2 = 0.120. The relative heights of the first three acoustic peaks cannot be fitted with baryons alone, and big bang nucleosynthesis independently limits the baryon density to Omega_b h^2 = 0.0224, which leaves about five times more non baryonic matter than baryonic matter in the cosmic budget."),
        ("core_snip",
         "Weak lensing mass map of the Bullet Cluster is offset from the X-ray gas",
         "In the merging cluster 1E0657-56 the weak lensing mass peak is offset by about 200 kpc from the X-ray emitting gas, which is difficult to explain without non baryonic dark matter."),
        ("meta",
         "Dark matter evidence across scales: review chapter for a graduate cosmology text",
         ""),
        ("contra",
         "No dark matter halo is needed: the radial acceleration relation explains the same rotation curves",
         "Using the same 175 disc galaxy rotation curves, this analysis reports that the outer rotation velocity is set by the baryonic mass alone through a single acceleration scale, and finds no significant residual left for a dark matter halo. The authors conclude that the halo fits are not required and that the reported 5.4 times extra mass inside 30 kpc is an artefact of the assumed mass to light ratio."),
        ("support",
         "Dataset: 175 galaxy rotation curves with 3.6 micron photometry and gas surface densities",
         "Machine readable rotation curves, photometry and gas surface density tables for 175 disc galaxies, distributed with the dark matter halo fits and the mass to light ratio grid."),
        ("retracted",
         "Retracted: direct detection of a dark matter signal at 8.6 keV with 90% probability",
         "This paper reported an annual modulation signal at 8.6 keV and claimed a 90% probability that dark matter had been directly detected. It was retracted after the collaboration could not reproduce the detector calibration or the background model."),
        ("overlap",
         "The dark matter of the genome: long non-coding RNA function across 42 human tissues",
         "Long non coding RNAs, often called the dark matter of the genome, were profiled across 42 human tissues. Expression was tissue specific for 61% of the transcripts and knockdown changed the cell cycle in two lines."),
        ("offaxis",
         "Photometric calibration residuals of the survey CCD pipeline over 41 observing nights",
         "We characterise flat field and photometric calibration residuals of the survey CCD pipeline across 41 observing nights. The zero point drifts by 0.8% with focal plane temperature, and the revised calibration procedure for the instrument reduces the scatter to 0.3%."),
        ("exoplanet",
         "TESS transit photometry of a warm Neptune orbiting a bright K dwarf",
         "We report the transit detection of a warm Neptune with an orbital period of 8.4 days around a bright K dwarf, combining TESS photometry with radial velocity follow up to measure a planet mass of 21 Earth masses and a radius of 4.2 Earth radii."),
        ("junk",
         "Efficacy of oral rehydration salts in paediatric diarrhoea: a randomised trial",
         "A randomised trial of oral rehydration salts in 480 children with acute diarrhoea reported reduced hospitalisation and shorter duration of symptoms."),
        ("junk_web",
         "Top 7 space facts that will blow your mind in 2024",
         "A listicle of space trivia, telescope photos and quiz questions. No measurements, no data, no references."),
        ("lowq",
         "My blog theory: dark matter is just gravity behaving differently",
         "A personal blog post arguing from intuition that gravity changes at large distances. No data, no fits, no measurements of any galaxy."),
    ),
    claim=("175 disc galaxies mein bahar ki rotation velocity 220 km/s par flat "
           "rehti hai aur 30 kpc ke andar dark matter halo stars+gas se 5.4 guna "
           "zyada mass deta hai"),
    reported=("Planck ke CMB power spectrum se cold dark matter density "
              "Omega_c h^2 = 0.120 batayi gayi hai"),
    mechanism=("Non-baryonic matter sirf gravity se interact karta hai, isliye "
               "wo galaxy ke bahar tak mass deta hai par roshni nahi deta — "
               "usi se flat rotation curve aur lensing ka offset banta hai"),
    against=("Radial acceleration relation wale analysis mein wahi 175 rotation "
             "curves baryonic mass se hi fit ho gaye, halo ki zaroorat nahi padi"),
    unknown=("Dark matter particle ka mass aur non-gravitational interaction "
             "abhi kisi lab detection se confirm nahi hua"),
    conclusion=("Rotation curve, CMB ke acoustic peaks aur lensing ka offset — "
                "teen alag raaste ek hi taraf ishara karte hain, par particle "
                "ki pehchaan abhi baaki hai"),
    numbers_ok=("Halo ke andar dark matter ka mass 5.4 guna hai [S1], jo 1 guna "
                "se zyada hai."),
    numbers_bad=("Outer rotation velocity 220 km/s (0.22 m/s) hai [S1], jo "
                 "300 km/s se zyada hai."),
    hyp=("Primordial black hole population dark matter ka bada hissa ho sakti hai",
         "Dark photon coupling se rotation curve ka bacha hua farak banta hai",
         "Modeling systematic error se lensing residual dikh raha hai"),
)

# ── runs (₹0 stubs, har variant ek hi baar) ──────────────────────────────────
PROMPT = QUESTION + " Kam se kam 3 nayi hypotheses banao."


def rounds_live(case: DomainCase) -> Dict[int, List[Row]]:
    """Live run jaisa mix: har round mein thoda kaam ka, thoda kachra."""
    return {1: _pick_rows(case, "core_full", "offaxis", "junk"),
            2: _pick_rows(case, "core_abs", "mirror", "exoplanet", "junk_web",
                          "lowq"),
            3: _pick_rows(case, "core_snip", "contra", "support", "retracted",
                          "meta", "overlap")}


def rounds_support_side(case: DomainCase) -> Dict[int, List[Row]]:
    """Sirf ek taraf ka evidence — yahan consensus ka dava NAHI banta."""
    return {1: _pick_rows(case, "core_full", "core_abs", "support"), 2: [], 3: []}


def rounds_thin(case: DomainCase) -> Dict[int, List[Row]]:
    """Sirf snippet + metadata — yahan VERIFIED asambhav hona chahiye."""
    return {1: _pick_rows(case, "core_snip", "meta"), 2: [], 3: []}


VARIANTS = {
    "live": lambda: _run(DARK_MATTER, rounds_live(DARK_MATTER), question=PROMPT),
    "dead": lambda: _run(DARK_MATTER, rounds_live(DARK_MATTER), mood="dead",
                         question=PROMPT),
    "bad_math": lambda: _run(DARK_MATTER, rounds_live(DARK_MATTER),
                             mood="bad_math", question=PROMPT),
    "overclaim": lambda: _run(DARK_MATTER, rounds_live(DARK_MATTER),
                              mood="overclaim", question=PROMPT),
    "support": lambda: _run(DARK_MATTER, rounds_support_side(DARK_MATTER),
                            question=PROMPT),
    "thin": lambda: _run(DARK_MATTER, rounds_thin(DARK_MATTER), question=PROMPT),
}

_CACHE: Dict[str, tuple] = {}


def run(variant: str):
    if variant not in _CACHE:
        _CACHE[variant] = VARIANTS[variant]()
    return _CACHE[variant]


def _all_titles(result: dict) -> str:
    return (_titles(result) + " | " + " | ".join(
        str(s.get("title", "")) for s in (result.get("uncited_sources") or []))
    ).lower()


def _tag_title(tag: str) -> str:
    row = _by_tag(DARK_MATTER).get(tag)
    return row.title if row else ""


def _ctx(result: dict) -> dict:
    return dict(result.get("quality_context") or {})


def section_of(answer: str, heading: str) -> str:
    """Ek `## heading` ka body — agle `## ` tak. Na mile to khaali string."""
    start = _heading_pos(answer, "## %s" % heading)
    if start < 0:
        return ""
    end = answer.find("\n## ", start + 5)
    return answer[start:(end if end > 0 else len(answer))]

# ── DM-01: off-topic paper kabhi evidence nahi banta ─────────────────────────
# Live run mein telescope-calibration ka paper, exoplanet transit ka paper aur
# "dark matter of the genome" (RNA) ka paper dark-matter ke evidence ki tarah
# gine gaye the. Ye group unka darwaaza band karta hai.
_OFF_TOPIC_TAGS = ("overlap", "offaxis", "exoplanet", "junk", "junk_web", "lowq")


def check_offtopic_never_evidence() -> None:
    with dm("DM-01"):
        for variant in ("live", "dead", "overclaim"):
            titles = _all_titles(run(variant)[0])
            for tag in _OFF_TOPIC_TAGS:
                head = _tag_title(tag)[:44].lower()
                check("%s: '%s' wala paper pack mein nahi aaya" % (variant, tag),
                      bool(head) and head not in titles, head)
        ctx = _ctx(run("live")[0])
        codes = {k: int(v or 0) for k, v in
                 (ctx.get("relevance_reject_codes") or {}).items()}
        check("relevance gate sach mein chala", ctx.get("relevance_gate_ran") is True,
              repr(ctx.get("relevance_gate_ran")))
        check("reject hone ki wajah code ke saath darj hui",
              sum(codes.values()) >= 6, repr(codes))
        check("domain mismatch apne code mein gina gaya",
              codes.get("DOMAIN_MISMATCH", 0) >= 3, repr(codes))
        check("sawaal ka subject hi missing tha — apna code",
              codes.get("SUBJECT_MISSING", 0) >= 1, repr(codes))
        check("bina data wali web page apne code mein",
              codes.get("NO_DATA_WEB", 0) >= 1, repr(codes))
        check("proposition test fail hone par bhi wajah likhi",
              codes.get("NO_PROPOSITION_TEST", 0) >= 1, repr(codes))
        check("sirf on-topic source hi 'directly relevant' bane",
              int(ctx.get("directly_relevant_sources") or 0) >= 4,
              repr(ctx.get("directly_relevant_sources")))


# ── DM-02: retrieved, cited aur unused ki ginti ALAG-ALAG ────────────────────
# Live run mein 18 source retrieve hue, 9 cite hue, aur audit ne 18 ko hi
# "evidence" bata diya. Ab teen alag counter hain aur teeno milte hain.
def check_retrieved_vs_cited() -> None:
    with dm("DM-02"):
        result = run("live")[0]
        ctx = _ctx(result)
        got, cited = int(ctx["sources_retrieved"]), int(ctx["sources_cited"])
        unused = int(ctx["sources_unused"])
        eq("retrieved = cited + unused", cited + unused, got)
        eq("cited ki ginti asli list se milti hai", len(result["sources"]), cited)
        eq("unused ki ginti asli list se milti hai",
           len(result.get("uncited_sources") or []), unused)
        check("live run mein 2 source cite hi nahi hue (chhupaye nahi gaye)",
              unused == 2, repr(unused))
        answer = _human_part(result["answer"])
        check("audit mein retrieved ka number likha hai",
              re.search(r"Sources retrieved:\s*\*\*%d\*\*" % got, answer) is not None)
        check("audit mein cite hue sources ka number alag likha hai",
              re.search(r"verified against real sources:\s*\*\*%d\*\*" % cited,
                        answer) is not None)
        check("audit mein 'retrieve hua par use nahi kiya' bhi likha hai",
              re.search(r"not used in the answer:\s*\*\*%d\*\*" % unused,
                        answer) is not None)
        check("source ki ginti ko evidence strength nahi kaha gaya",
              "VERIFIED" not in str(result.get("evidence_level") or ""),
              str(result.get("evidence_level"))[:80])


# ── DM-03: kamzor relevance par "✅ VERIFIED" asambhav ────────────────────────
# Live run ne average relevance 0.43 par bhi "✅ VERIFIED" chhaap diya tha.
_BARE_VERIFIED = re.compile(r"(?<!UN)VERIFIED")


def check_no_verified_on_weak_evidence() -> None:
    with dm("DM-03"):
        for variant in ("live", "dead", "thin", "support", "overclaim", "bad_math"):
            result = run(variant)[0]
            answer = result["answer"]
            state = dict(result.get("research_state") or {})
            check("%s: kahin bhi bina 'UN' wala VERIFIED nahi" % variant,
                  _BARE_VERIFIED.search(answer) is None,
                  repr(_BARE_VERIFIED.findall(answer)[:3]))
            check("%s: '✅ VERIFIED' badge nahi" % variant,
                  "✅ VERIFIED" not in answer)
            check("%s: verified_allowed jhoot nahi bola" % variant,
                  state.get("verified_allowed") is False,
                  repr(state.get("verified_allowed")))
        thin_ctx = _ctx(run("thin")[0])
        avg = float(thin_ctx.get("average_relevance") or 0.0)
        check("patla run relevance floor ke NEECHE hai (fixture sach me kamzor)",
              avg < DIRECT_RELEVANCE_FLOOR, "avg=%.4f floor=%s" % (avg, DIRECT_RELEVANCE_FLOOR))
        eq("kamzor run ka status PARTIAL", run("thin")[0].get("status"), "PARTIAL")
        live_ctx = _ctx(run("live")[0])
        check("average relevance number audit ke liye maujood hai",
              isinstance(live_ctx.get("average_relevance"), float),
              repr(live_ctx.get("average_relevance")))


# ── DM-04: chhoote hue evidence raaste NAAM le kar 'missing' likhe gaye ───────
# Live run ne CMB, BBN, Bullet Cluster, lensing, LSS aur dwarf galaxies wale
# raaste dhoondhe hi nahi, aur chup-chaap jawab de diya.
_MUST_NAME_AXES = ("CMB / Planck power spectrum",
                   "Big-Bang nucleosynthesis / baryon budget",
                   "large-scale structure / BAO",
                   "dwarf galaxies / small-scale tests",
                   "observational & modelling systematics",
                   "counter-evidence / criticism")


def check_missing_axes_named() -> None:
    with dm("DM-04"):
        result = run("live")[0]
        ctx = _ctx(result)
        answer = result["answer"]
        missing = int(ctx.get("axes_mandatory_missing") or 0)
        labels = list(ctx.get("axes_missing_labels") or [])
        check("khaali raaste ginne gaye, 0 maan kar chhode nahi",
              missing >= 6, repr(missing))
        eq("har khaali raaste ka naam bhi diya gaya", len(labels), missing)
        for label in _MUST_NAME_AXES:
            check("jawab mein naam se likha: %s" % label, label in answer)
        eq("total axes = covered + weak + missing + not-searched",
           sum(int(ctx.get(key) or 0) for key in
               ("axes_covered", "axes_weak", "axes_missing", "axes_not_searched")),
           int(ctx.get("axes_total") or -1))
        eq("mandatory-missing = weak + missing + not-searched",
           sum(int(ctx.get(key) or 0) for key in
               ("axes_weak", "axes_missing", "axes_not_searched")), missing)
        check("jawab khud maanta hai ki isse poora nahi kaha ja sakta",
              "poora nahi kaha ja sakta" in answer)


# ── DM-05: [NO-SOURCE] line par koi strong claim nahi ────────────────────────
# Live run mein 14 line par [NO-SOURCE] tha aur wahi line "established" bhi
# batayi gayi thi.
def check_no_source_claims() -> None:
    with dm("DM-05"):
        for variant in ("live", "overclaim", "bad_math", "support", "thin"):
            result = run(variant)[0]
            ctx = _ctx(result)
            answer = result["answer"]
            eq("%s: bina source wale claim ki ginti" % variant,
               int(ctx.get("no_source_claims") or 0), 0)
            eq("%s: critical claim bina source ka nahi" % variant,
               int(ctx.get("critical_no_source_claims") or 0), 0)
            eq("%s: ungrounded claim ki list khaali" % variant,
               list(result.get("ungrounded_claims") or []), [])
            eq("%s: galat [S#] citation nahi" % variant,
               list(result.get("invalid_citations") or []), [])
            check("%s: [NO-SOURCE] tag jawab mein nahi bacha" % variant,
                  "[NO-SOURCE]" not in answer, str(answer.count("[NO-SOURCE]")))
        report = dict(run("overclaim")[0].get("label_report") or {})
        check("overclaim par label downgrade sach me hua",
              int(report.get("downgraded") or 0) >= 1, repr(report)[:120])


# ── DM-06: counter-search consensus se PEHLE, aur links ka dher ≠ consensus ───
# Live run mein counter-search chali hi nahi thi, phir bhi "sab sources sehmat
# hain" jaisa taal diya gaya tha.
def check_counter_search_before_consensus() -> None:
    with dm("DM-06"):
        for variant in ("live", "dead", "thin", "support"):
            result, disc, _fake = run(variant)
            ctx = _ctx(result)
            check("%s: counter-search sach mein chali" % variant,
                  ctx.get("counter_search_performed") is True,
                  repr(ctx.get("counter_search_performed")))
            check("%s: khilaaf dhoondhne wali query bhi bheji gayi" % variant,
                  opposition_in_queries(disc.queries()) is True)
        support = run("support")[0]
        eq("ek-tarfa run mein takraav 0 mila",
           int(_ctx(support).get("contradictions_present") or 0), 0)
        check("phir bhi 'sab sehmat hain' nahi kaha — limit likhi gayi",
              "Consensus ka andaaza retrieved sources tak seemit hai"
              in support["answer"])
        thin = run("thin")[0]
        check("patle run mein consensus ka faisla hi nahi liya gaya",
              CONSENSUS_UNAVAILABLE in thin["answer"])
        check("links ka dher consensus nahi — ye saaf likha gaya",
              "Retrieved links ka dher scientific consensus nahi hota"
              in thin["answer"])


# ── DM-07: mirror copy independent source nahi ginn gayi ─────────────────────
# Live run mein ek hi paper do host se aaya tha aur dono alag "independent
# evidence" gine gaye the.
def check_mirror_not_independent() -> None:
    with dm("DM-07"):
        result = run("live")[0]
        ctx = _ctx(result)
        rows = list(result["sources"]) + list(result.get("uncited_sources") or [])
        urls = [str(row.get("url") or "") for row in rows]
        check("researchgate ki mirror copy pack mein hi nahi aayi",
              not any("researchgate.net" in url for url in urls), repr(urls))
        base = _tag_title("core_full")[:44].lower()
        eq("asli paper ka title sirf ek baar", _all_titles(result).count(base), 1)
        eq("har URL alag (dedup ke baad)",
           int(ctx.get("distinct_urls") or 0), int(ctx.get("sources_retrieved") or -1))
        check("independent family ki ginti source ki ginti se KAM hai",
              int(ctx.get("independent_source_families") or 0)
              < int(ctx.get("sources_retrieved") or 0),
              "families=%s sources=%s" % (ctx.get("independent_source_families"),
                                          ctx.get("sources_retrieved")))


# ── DM-08: sirf saal ka farq "contradiction" nahi ────────────────────────────
# Live run ne 2010 vs 2022 ke do papers ko takraav bata diya tha.
def _year_only_pair() -> Tuple[EvidencePack, ContradictionEngine]:
    def rec(sid: str, year: int, title: str, snippet: str, host: str) -> SourceRecord:
        return SourceRecord(source_id=sid, title=title, snippet=snippet,
                            url="https://%s/%s" % (host, sid.lower()),
                            year=year, source_type=SourceType.PAPER,
                            peer_reviewed=True, connector="arxiv",
                            doi="10.9999/%s" % sid.lower())
    old = rec("S1", 2010,
              "Galaxy rotation curves indicate a dark matter halo in disc galaxies",
              "The outer rotation velocity of disc galaxies stays flat, which "
              "shows that a dark matter halo dominates the mass budget of the "
              "galaxy.", "arxiv.org/abs")
    new = rec("S2", 2022,
              "Galaxy rotation curves and the dark matter halo mass of disc galaxies",
              "The outer rotation velocity of disc galaxies stays flat, and the "
              "dark matter halo mass may dominate the galaxy budget, although "
              "the result is uncertain and could suggest otherwise.",
              "www.nature.com/articles")
    pack = EvidencePack(question=QUESTION, sources=[old, new])
    return pack, ContradictionEngine()


def check_year_only_is_not_contradiction() -> None:
    with dm("DM-08"):
        pack, engine = _year_only_pair()
        found = engine.detect(pack)
        report = engine.rejection_report()
        eq("12 saal ke farq se koi takraav nahi bana", len(found), 0)
        eq("wo 'takraav' YEAR_ONLY keh kar hataya gaya",
           [(c.kind, c.reject_code) for c in engine.last_rejected],
           [("RECENCY", "YEAR_ONLY")])
        eq("YEAR_ONLY ka counter audit mein darj hai",
           int((report.get("counts") or {}).get("YEAR_ONLY") or 0), 1)
        check("hataye jaane ki wajah user ki bhasha mein likhi hai",
              "sirf publication year" in str((report.get("why") or {}).get("YEAR_ONLY")))
        live = _ctx(run("live")[0])
        rows = [c for c in (live.get("contradictions") or []) if c.get("valid")]
        check("live run ke saare takraav sach me ulti direction ke hain",
              all(row.get("opposing_direction") is True for row in rows),
              repr([row.get("opposing_direction") for row in rows]))
        check("har takraav ka schema poora (proposition + dono claim + spans)",
              rows and all(row.get("schema_complete") and row.get("normalized_proposition")
                           and row.get("evidence_spans") for row in rows))
        eq("live run mein RECENCY jaisa jhootha takraav nahi bacha",
           int((live.get("contradiction_reject_codes") or {}).get("YEAR_ONLY") or 0), 0)


# ── DM-09: PBH / MOND / dark photon kabhi "POSSIBLY NOVEL" nahi ───────────────
# Live run ne inhe "humari nayi hypothesis" bata diya tha.
_KNOWN_IDEA_WORDS = ("primordial black hole", "dark photon", "systematic")


def check_known_ideas_never_novel() -> None:
    with dm("DM-09"):
        result = run("live")[0]
        ctx = _ctx(result)
        answer = result["answer"]
        counts = dict(ctx.get("hypothesis_novelty_counts") or {})
        eq("teeno hypotheses 'KNOWN IDEA' hain", counts, {"KNOWN IDEA": 3})
        check("koi bhi novelty label spec ki list se bahar nahi",
              all(label in NOVELTY_STATES for label in counts),
              repr(list(counts)))
        check("'POSSIBLY NOVEL' shabd jawab mein hi nahi",
              NOVELTY_POSSIBLE not in answer)
        eq("bina prior-art search novelty claim 0",
           int(ctx.get("hypothesis_novel_without_search") or 0), 0)
        eq("mana kiye gaye novelty label 0",
           list((ctx.get("hypothesis_report") or {}).get("forbidden_novelty_labels") or []), [])
        report = dict(ctx.get("hypothesis_report") or {})
        eq("teeno ko 'pehle se maujood idea' flag mila",
           len(report.get("known_ideas_flagged") or []), 3)
        for hyp in (result.get("hypotheses") or []):
            check("hypothesis ka novelty ka kaaran likha hai: %s"
                  % str(hyp.get("hypothesis_id")),
                  len(str(hyp.get("novelty_why") or "")) > 20)
            check("hypothesis ke closest prior work naam se diye: %s"
                  % str(hyp.get("hypothesis_id")),
                  bool(hyp.get("closest_prior_work")))
        low = answer.lower()
        for word in _KNOWN_IDEA_WORDS:
            check("'%s' ko app ki khoj nahi kaha gaya" % word,
                  word not in low or "app ki khoj nahi" in low
                  or "pehle se maujood" in low)


# ── DM-10: APP ORIGINAL RESEARCH LAB alag — evidence ke saath mix nahi ───────
def check_lab_is_separated() -> None:
    with dm("DM-10"):
        result = run("live")[0]
        answer = result["answer"]
        lab_at = _heading_pos(answer, "## %s" % LAB_HEADING)
        check("LAB ka heading exact naam se maujood", lab_at > 0, str(lab_at))
        eq("LAB heading sirf ek baar", answer.count("## %s" % LAB_HEADING), 1)
        check("LAB conclusion ke BAAD aata hai",
              lab_at > _heading_pos(answer, "## %s" % display_heading("conclusion")))
        lab_end = answer.find("\n## ", lab_at + 5)
        lab_body = answer[lab_at:(lab_end if lab_end > 0 else len(answer))]
        check("LAB ke shuru mein hi warning: ye app ki khud ki soch hai",
              "app ki KHUD ki soch hai" in lab_body)
        check("warning mein 'established fact nahi' bhi likha hai",
              "established fact nahi" in lab_body)
        ids = [str(h.get("hypothesis_id")) for h in (result.get("hypotheses") or [])]
        check("saari RV-HYP sirf LAB ke andar hain",
              ids and all(answer.count(hid) == lab_body.count(hid) for hid in ids),
              repr(ids))
        support = section_of(answer, display_heading("supporting_evidence"))
        check("supporting-evidence section mein koi RV-HYP nahi",
              not any(hid in support for hid in ids))
        eq("har hypothesis card par app-generated disclaimer",
           lab_body.count("generated by this app"), len(ids))
        report = dict(_ctx(result).get("hypothesis_report") or {})
        if report.get("schema_complete") is False:
            check("adhoore hypothesis record chhupaye nahi gaye — ID ke saath likhe",
                  all(hid in answer for hid in (report.get("incomplete_ids") or [])))


# ── DM-11: adhoora run kabhi COMPLETE + VERIFIED nahi ────────────────────────
# Live run mein quota khatam ho gaya tha, phir bhi jawab "COMPLETE" aur
# "✅ VERIFIED" tha. §20 ke chaar alag state yahan alag-alag padhe jaate hain.
def check_status_is_honest() -> None:
    with dm("DM-11"):
        dead = run("dead")[0]
        eq("quota khatam hone par status", dead.get("status"), "RESEARCH INCOMPLETE")
        eq("failure ki wajah code ke saath", dead.get("failure_kind"), "daily_quota")
        check("adhoore run mein reasoning ko poora nahi kaha",
              _ctx(dead).get("reasoning_complete") is not True)
        eq("patle run ka status", run("thin")[0].get("status"), "PARTIAL")
        for variant in ("live", "dead", "thin", "support", "overclaim", "bad_math"):
            state = dict(run(variant)[0].get("research_state") or {})
            check("%s: job ka khatam hona jawab ka poora hona NAHI hai" % variant,
                  "jawab poora hona NAHI" in str((state.get("reasons") or {}).get("job_status")))
            check("%s: answer_state ko COMPLETE nahi kaha" % variant,
                  str(state.get("answer_state") or "").upper() != "COMPLETE",
                  repr(state.get("answer_state")))
            eq("%s: verified allowed nahi" % variant, state.get("verified_allowed"), False)
            eq("%s: state ke beech chupa hua conflict nahi" % variant,
               list(state.get("conflicts") or []), [])
        live = run("live")[0]
        check("11 raaste khaali hone par jawab mein saaf chetavani hai",
              "zaroori raaste khaali hain" in live["answer"])


# ── DM-12: raw 429 / grpc / traceback user ke jawab mein nahi ────────────────
# Live run mein `ResourceExhausted: 429 grpc_status:8 …` seedha jawab ke beech
# chhap gaya tha. Contract: raw text SIRF developer wale tail block mein.
_TECH_MARKER = "### Technical details"


def check_no_raw_provider_text() -> None:
    with dm("DM-12"):
        for variant in ("live", "dead", "thin", "support", "overclaim", "bad_math"):
            answer = run(variant)[0]["answer"]
            leaks = [token for token in RAW_TOKENS if token in _human_part(answer)]
            eq("%s: user ke hisse mein raw provider text nahi" % variant, leaks, [])
        dead = run("dead")[0]
        answer = dead["answer"]
        marker = answer.find(_TECH_MARKER)
        present = [token for token in RAW_TOKENS if token in answer]
        check("dead run mein raw error gayab nahi kiya gaya (developer ko chahiye)",
              bool(present), repr(present))
        check("raw text ka block hi maujood hai aur uska naam saaf hai",
              marker > 0, str(marker))
        for token in present:
            check("'%s' sirf developer block ke andar hai" % token,
                  answer.find(token) > marker,
                  "at=%d marker=%d" % (answer.find(token), marker))
        details = " ".join(str(row) for row in (dead.get("technical_details") or []))
        check("raw error structured field mein bhi mila (API ke liye)",
              any(token in details for token in RAW_TOKENS), details[:80])
        check("developer block ka heading khud batata hai ki ye jawab nahi hai",
              "user ke jawab ka hissa nahi" in answer)
        live = run("live")[0]
        eq("healthy run mein technical_details khaali",
           list(live.get("technical_details") or []), [])
        eq("healthy run ke jawab mein raw token bilkul nahi",
           [token for token in RAW_TOKENS if token in live["answer"]], [])


# ── DM-13: recovery footer aur heading dobara nahi chhapte ───────────────────
# Live run mein recovery ke baad "Seedha jawab" aur evidence-level footer do
# baar chhap gaye the.
def check_no_duplicate_blocks() -> None:
    with dm("DM-13"):
        for variant in ("live", "dead", "thin", "support", "overclaim", "bad_math"):
            answer = run(variant)[0]["answer"]
            heads = re.findall(r"(?m)^#{2,3} .+$", answer)
            dupes = sorted({head for head in heads if heads.count(head) > 1})
            eq("%s: koi heading do baar nahi" % variant, dupes, [])
            check("%s: 'Seedha jawab' sirf ek baar" % variant,
                  len(re.findall(r"(?mi)^#{2,3}.*seedha jawab", answer)) == 1)
            check("%s: evidence-level footer sirf ek baar" % variant,
                  answer.lower().count("evidence ka level:") <= 1,
                  str(answer.lower().count("evidence ka level:")))
            check("%s: purana 'saboot ka star' footer dobara nahi" % variant,
                  answer.lower().count("saboot ka star:") <= 1)
            check("%s: developer block bhi sirf ek baar" % variant,
                  answer.count(_TECH_MARKER) <= 1, str(answer.count(_TECH_MARKER)))
            # `answer.count("## Sources")` galat jawab deta hai: "### Sources ki
            # checking" ke andar bhi "## Sources" chhupa hota hai. Heading ki
            # ginti line-anchored regex se hi honi chahiye.
            check("%s: Sources section sirf ek baar" % variant,
                  len(re.findall(r"(?m)^## %s\s*$" % re.escape(
                      display_heading("sources")), answer)) == 1)


# ── DM-14: calculation ka dava tabhi jab hisaab SACH mein hua ────────────────
# Live run mein Calculations section gayab tha par jawab number bata raha tha.
def check_calculation_honesty() -> None:
    with dm("DM-14"):
        for variant in ("live", "dead", "thin", "support", "bad_math"):
            result = run(variant)[0]
            ctx = _ctx(result)
            answer = result["answer"]
            section = section_of(answer, "Calculations — formula, inputs, units aur assumptions")
            check("%s: Calculations ka section maujood hai" % variant,
                  bool(section), str(len(section)))
            count = int(ctx.get("calculations_count") or 0)
            if count == 0:
                check("%s: hisaab nahi hua to saaf likha 'koi calculation nahi'" % variant,
                      "Koi calculation is jawab mein nahi hai" in section, section[:90])
                eq("%s: usable calculation ki ginti bhi 0" % variant,
                   int(ctx.get("calculations_usable") or 0), 0)
            else:
                eq("%s: har calculation record ke saath aaya" % variant,
                   len(ctx.get("calculations") or []), count)
            eq("%s: inputs bana kar calculation nahi kiya" % variant,
               int(ctx.get("calculations_with_invented_inputs") or 0), 0)
        bad = run("bad_math")[0]
        verification = dict(bad.get("verification") or {})
        checks = {str(row.get("check")): row.get("passed")
                  for row in (verification.get("checks") or [])}
        eq("galat unit conversion pakdi gayi", checks.get("unit conversion"), False)
        eq("ulti tulna (comparison direction) pakdi gayi",
           checks.get("comparison direction"), False)
        eq("maths galat hone par status", verification.get("status"), "MATH ERROR FOUND")


# ── DM-15: access-depth ka overclaim nahi ────────────────────────────────────
# Live run mein sirf abstract padh kar "FULL-TEXT VERIFIED" likh diya gaya tha.
def check_access_depth_honesty() -> None:
    with dm("DM-15"):
        for variant in ("live", "dead", "thin", "support", "overclaim"):
            result = run(variant)[0]
            answer = result["answer"]
            ctx = _ctx(result)
            eq("%s: '%s' label banned hai" % (variant, BANNED_ACCESS_LABEL),
               answer.count(BANNED_ACCESS_LABEL), 0)
            eq("%s: access-depth ka mismatch 0" % variant,
               int(ctx.get("access_depth_mismatch_count") or 0), 0)
            check("%s: 'VERIFIED' shabd depth ke vocabulary mein hi nahi" % variant,
                  not any("VERIFIED" in label for label in ACCESS_DEPTH_ALLOWED))
        live = run("live")[0]
        answer = live["answer"]
        used = {label: answer.count(label) for label in ACCESS_DEPTH_ALLOWED
                if answer.count(label)}
        check("depth ke saare label spec ki list se hi aaye", bool(used), repr(used))
        full_seen = answer.count("Kitna padha gaya: %s" % ACCESS_FULL)
        check("poora text sirf unhi ke liye claim hua jinka full text mila",
              full_seen <= len(full_text_urls(DARK_MATTER)),
              "claimed=%d allowed=%d" % (full_seen, len(full_text_urls(DARK_MATTER))))
        check("sirf-abstract wale source ko poora padha nahi bataya",
              "ABSTRACT ONLY" in answer)
        check("depth ka matlab bhi user ki bhasha mein samjhaya",
              "poora text process hua" in answer)


# ── DM-16: retracted paper flag hua, strong claim nahi bana ──────────────────
def check_retracted_is_flagged() -> None:
    with dm("DM-16"):
        result = run("live")[0]
        answer = result["answer"]
        retracted_title = _tag_title("retracted")[:44]
        if retracted_title.lower() in _all_titles(result):
            check("retracted paper par saaf warning likhi gayi",
                  "retraction/withdrawal ka signal" in answer)
            check("warning batati hai ki retracted kaam evidence nahi hota",
                  "Retracted kaam evidence nahi hota" in answer
                  or "evidence ki tarah use nahi karna" in answer)
            check("retracted paper ko Sources mein bhi flag kiya gaya",
                  "Is kaam par retraction/withdrawal ka signal hai" in answer)
            checks = {str(row.get("check")): row.get("passed")
                      for row in ((result.get("verification") or {}).get("checks") or [])}
            eq("'cited sources retraction-free' check FAIL hua",
               checks.get("cited sources retraction-free"), False)
            check("retracted source ke bawajood VERIFIED nahi",
                  dict(result.get("research_state") or {}).get("verified_allowed") is False)
        else:
            check("retracted paper pack se hi bahar", True)
        check("retracted paper ka result 'nateeja' nahi maana gaya",
              "Retracted paper ko result nahi maana ja sakta" in answer)
        check("90% wali fake probability aage nahi badhi",
              "90%" not in _human_part(answer).split("## %s"
                                                     % display_heading("sources"))[0]
              or "retract" in answer.lower())


# ── DM-17: "check nahi hua" ≠ "0 mila" ───────────────────────────────────────
# Live run ke audit mein wo checks bhi "0" dikhaye gaye the jo chale hi nahi
# the. §19 ka tri-state: None = chala nahi, 0 = chala aur kuch nahi mila.
def check_tristate_audit() -> None:
    with dm("DM-17"):
        result = run("live")[0]
        ctx = _ctx(result)
        unknown = list(ctx.get("unknown_fields") or [])
        check("jo check chala hi nahi, wo naam se list hua", bool(unknown), repr(unknown))
        for name in unknown:
            check("'%s' spec ki tri-state list ka hissa hai" % name,
                  name in TRISTATE_FIELDS)
            check("'%s' ki value sach mein None hai (0 nahi)" % name,
                  ctx.get(name) is None, repr(ctx.get(name)))
        block = context_block(ctx)
        check("audit saaf likhta hai ki ye check HO HI NAHI SAKA",
              "HO HI NAHI SAKA" in block)
        check("audit khud kehta hai ise 'zero' na padha jaaye",
              "'zero' na padha jaaye" in block)
        for name in unknown:
            check("'%s' user ke jawab mein bhi naam se aaya" % name,
                  name in result["answer"])
        eq("jo check chala aur 0 nikla, wo unknown mein NAHI hai",
           [name for name in ("no_source_claims", "contradictions_rejected",
                              "sources_unused") if name in unknown], [])
        check("0 wale counter sach mein 0 hain (None nahi)",
              ctx.get("no_source_claims") == 0
              and ctx.get("contradictions_rejected") == 0,
              repr((ctx.get("no_source_claims"), ctx.get("contradictions_rejected"))))


# ── scorecard ────────────────────────────────────────────────────────────────
CHECK_GROUPS = (
    check_offtopic_never_evidence, check_retrieved_vs_cited,
    check_no_verified_on_weak_evidence, check_missing_axes_named,
    check_no_source_claims, check_counter_search_before_consensus,
    check_mirror_not_independent, check_year_only_is_not_contradiction,
    check_known_ideas_never_novel, check_lab_is_separated,
    check_status_is_honest, check_no_raw_provider_text,
    check_no_duplicate_blocks, check_calculation_honesty,
    check_access_depth_honesty, check_retracted_is_flagged,
    check_tristate_audit,
)


def print_scorecard() -> None:
    print("\n" + "=" * 78)
    print("§24 DARK MATTER ACCEPTANCE MATRIX — har row ek live galti ka darwaaza")
    print("=" * 78)
    print("%-7s %5s %5s  %-6s  %s" % ("ID", "PASS", "FAIL", "STATUS", "live failure"))
    print("-" * 78)
    for failure_id, label in FAILURE_IDS:
        ok, bad = SCORE.get(failure_id, [0, 0])
        if ok == 0 and bad == 0:
            status = "SKIP"
        else:
            status = "CLOSED" if bad == 0 else "OPEN"
        print("%-7s %5d %5d  %-6s  %s" % (failure_id, ok, bad, status, label[:44]))
    print("-" * 78)
    closed = sum(1 for fid, _ in FAILURE_IDS
                 if SCORE.get(fid, [0, 0])[1] == 0 and sum(SCORE.get(fid, [0, 0])) > 0)
    print("Band ho chuke darwaaze: %d/%d" % (closed, len(FAILURE_IDS)))
    print("Total checks: %d pass, %d fail" % (PASSED, FAILED))
    if FAILURES:
        print("\nKhuli galtiyan:")
        for failure_id, labels in FAILURES.items():
            print("  %s (%s)" % (failure_id, _LABELS.get(failure_id, "?")))
            for label in labels:
                print("     - %s" % label)


def main() -> int:
    print("§24 dark-matter acceptance benchmark — poora offline, ₹0, koi API key nahi.")
    for group in CHECK_GROUPS:
        group()
    print_scorecard()
    if FAILED:
        print("\nRESULT: PARTIAL — %d check fail hue." % FAILED)
        return 1
    print("\nRESULT: sab %d check pass — 17/17 live galtiyon ka darwaaza band." % PASSED)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

