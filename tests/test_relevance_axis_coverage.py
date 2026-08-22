"""
§5 ka test — EVIDENCE AXES: coverage, retry ladder aur "ginti ≠ coverage".

Asli failure jo ye file pakadti hai: dark-matter run mein 18 source aaye,
report ne unhe ginaya, aur CMB, BBN, Bullet Cluster, lensing, large-scale
structure, dwarf galaxies aur direct detection par ek bhi saboot nahi tha —
phir bhi jawab COMPLETE aur ✅ VERIFIED likha gaya. Ab wo mumkin nahi:
zaroori axis khaali ho to ledger `answer_complete=False` deta hai.

Offline test: koi network, koi Gemini, koi pytest nahi. Seedha
`python3 tests/test_relevance_axis_coverage.py` chalao.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import evidence_axes as ax                       # noqa: E402
from research_engine.models import SourceRecord, SourceType           # noqa: E402
from research_engine.requested import contract_ledger, quality_contract  # noqa: E402

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


class _Mode:
    """DepthConfig ki jagah — contract ko sirf `.name` chahiye."""

    def __init__(self, name: str) -> None:
        self.name = name


DM_QUESTION = ("dark matter ke saboot par deep research karo — rotation curves, "
               "CMB, BBN, Bullet Cluster, lensing, large-scale structure, dwarf "
               "galaxies, direct detection, MOND aur primordial black holes")

# §5 ka naam-le-kar diya gaya set — inme se ek bhi gayab nahi hona chahiye.
DM_CORE = ("rotation_curves", "milky_way_dynamics", "cmb", "bbn", "lensing",
           "bullet_cluster", "large_scale_structure", "dwarf_galaxies",
           "direct_detection", "collider", "pbh_microlensing",
           "pbh_gravitational_waves", "mond_strengths", "mond_limits",
           "systematics")
def src(sid: str, title: str, snippet: str, score: float = 0.8,
        rejected: str = "", parts=None) -> SourceRecord:
    """Ek source — relevance gate ka nateeja iske fields mein hota hai."""
    s = SourceRecord(title=title, url=f"https://example.org/{sid}",
                     snippet=snippet, connector="openalex",
                     source_type=SourceType.PAPER, year=2021,
                     peer_reviewed=True, relevance_score=score)
    s.source_id = sid
    if rejected:
        s.rejected_reason = rejected
    if parts is not None:
        s.relevance_parts = parts
    return s


ROTATION = src("S1", "Flat rotation curve of spiral galaxies",
               "Circular velocity stays flat out to large radii in this HI "
               "rotation survey of spiral galaxies.")
# Bilkul wahi kachra jo live run mein aaya tha.
EXOPLANET = src("S2", "TESS photometric calibration for exoplanet transits",
                "Calibration uncertainty of TESS photometry used for exoplanet "
                "transit detection.")


# ── 1. dark matter ke 15 axes gayab nahi hote ───────────────────────────────

def test_dark_matter_axes_present() -> None:
    print("\n[1] Dark matter ke 15 zaroori raaste + replication + counter")
    axes = ax.axes_for(DM_QUESTION)
    ids = [a.axis_id for a in axes]
    missing = [a for a in DM_CORE if a not in ids]
    check("15 curated axes sab maujood", not missing, str(missing))
    check("replication axis bhi hai", "replication" in ids)
    check("counter_evidence axis bhi hai", "counter_evidence" in ids)
    check("sab mandatory hain", all(a.mandatory for a in axes),
          str([a.axis_id for a in axes if not a.mandatory]))
    check("generic mechanism/quantitative nahi ghusaye (list phoolti nahi)",
          "mechanism" not in ids and "quantitative" not in ids, str(ids))
    check("har axis ki wajah likhi hai", all(a.why for a in axes),
          str([a.axis_id for a in axes if not a.why]))
    check("dono run same (deterministic)",
          [a.axis_id for a in ax.axes_for(DM_QUESTION)] == ids)
    check("axis set dark_matter chuna gaya",
          ax.axis_set_for(DM_QUESTION)[0] == "dark_matter",
          ax.axis_set_for(DM_QUESTION)[0])

# ── 2. retry ladder: 6 ALAG koshishein, wahi query 6 baar nahi ──────────────

def test_ladder_has_six_distinct_steps() -> None:
    print("\n[2] Ladder ki 6 seedhiyan, chhe alag query")
    axis = ax.axes_for(DM_QUESTION)[0]
    rungs = axis.ladder("dark matter evidence")
    check("6 rung bane", len(rungs) == 6, str(len(rungs)))
    check("step number 1..6", [r["step"] for r in rungs] == [1, 2, 3, 4, 5, 6],
          str([r["step"] for r in rungs]))
    check("naam spec ke kram mein",
          [r["name"] for r in rungs] == [n for n, _ in ax.LADDER_STEPS],
          str([r["name"] for r in rungs]))
    queries = [r["query"] for r in rungs]
    check("chhe query alag-alag", len(set(queries)) == 6, str(queries))
    check("koi query khaali nahi", all(q.strip() for q in queries))
    check("aakhri rung counter-side hai",
          "criticism" in queries[-1] and "limitations" in queries[-1],
          queries[-1])
    check("primary rung review nahi maangti",
          "review" not in queries[3], queries[3])
    check("topic anchor har query mein",
          all("dark matter" in q or "dark" in q for q in queries), str(queries))
    check("query mein shabd dohraye nahi",
          all(len(q.split()) == len({w.lower() for w in q.split()})
              for q in queries), str(queries))
    check("limit maanti hai", len(axis.ladder("dark matter", limit=2)) == 2)

# ── 3. chaar status: "search nahi hui" ≠ "kuch nahi mila" ───────────────────

def test_status_is_tri_state() -> None:
    print("\n[3] NOT SEARCHED / MISSING / WEAK / COVERED — chaaron alag")
    axes = ax.axes_for(DM_QUESTION)
    weak = src("S3", "Weak lensing shear catalogue systematics",
               "Weak lensing convergence map and shear calibration.",
               score=0.20)
    recs = ax.coverage(axes, [ROTATION, weak],
                       searched={"rotation_curves": ["q1"], "cmb": ["q1"],
                                 "lensing": ["q1"]})
    by = {r["axis_id"]: r for r in recs}
    check("relevant source mila -> COVERED",
          by["rotation_curves"]["status"] == ax.AXIS_COVERED,
          by["rotation_curves"]["status"])
    check("query gayi, kuch nahi mila -> MISSING",
          by["cmb"]["status"] == ax.AXIS_MISSING, by["cmb"]["status"])
    check("query hi nahi gayi -> NOT SEARCHED",
          by["bbn"]["status"] == ax.AXIS_NOT_SEARCHED, by["bbn"]["status"])
    check("floor se neeche wala source -> WEAK",
          by["lensing"]["status"] == ax.AXIS_WEAK, by["lensing"]["status"])
    check("WEAK ko relevant nahi ginte",
          by["lensing"]["relevant_sources"] == []
          and by["lensing"]["sources_found"] == ["S3"], str(by["lensing"]))
    check("har status ki wajah insaani bhasha mein",
          all(r["status_why"] for r in recs))
    check("searched flag alag se record hua",
          by["rotation_curves"]["searched"] is True
          and by["bbn"]["searched"] is False)
    check("matched terms record hue",
          "rotation curve" in by["rotation_curves"]["matched_terms"]
          or "flat rotation" in by["rotation_curves"]["matched_terms"],
          str(by["rotation_curves"]["matched_terms"]))
    check("sirf chaar status vocabulary",
          {r["status"] for r in recs} <= set(ax.AXIS_STATUSES))

# ── 4. rejected / off-topic source kisi axis ko "bhar" nahi sakta ───────────

def test_rejected_sources_never_cover_an_axis() -> None:
    print("\n[4] Relevance gate se nikaala hua source axis cover nahi karta")
    axes = ax.axes_for(DM_QUESTION)
    rejected = src("S4", "TESS calibration uncertainty of photometric systematics",
                   "Calibration uncertainty and selection effect in TESS "
                   "photometry.", score=0.9,
                   rejected="topic mismatch — exoplanet photometry")
    recs = {r["axis_id"]: r for r in
            ax.coverage(axes, [rejected], searched={"systematics": ["q1"]})}
    check("rejected source COVERED nahi banata",
          recs["systematics"]["status"] != ax.AXIS_COVERED,
          recs["systematics"]["status"])
    check("phir bhi ginti mein dikhta hai (chhupaya nahi)",
          recs["systematics"]["sources_found"] == ["S4"],
          str(recs["systematics"]["sources_found"]))
    no_prop = src("S5", "Systematic uncertainty in beam smearing corrections",
                  "Modelling error and beam smearing correction study.",
                  score=0.85, parts={"tests_proposition": False})
    recs2 = {r["axis_id"]: r for r in
             ax.coverage(axes, [no_prop], searched={"systematics": ["q1"]})}
    check("proposition test fail -> COVERED nahi",
          recs2["systematics"]["status"] == ax.AXIS_WEAK,
          recs2["systematics"]["status"])
    recs3 = {r["axis_id"]: r for r in
             ax.coverage(axes, [EXOPLANET], searched={"cmb": ["q1"],
                                                      "bbn": ["q1"]})}
    check("exoplanet paper CMB axis nahi bharta",
          recs3["cmb"]["status"] == ax.AXIS_MISSING, recs3["cmb"]["status"])
    check("exoplanet paper BBN axis bhi nahi bharta",
          recs3["bbn"]["status"] == ax.AXIS_MISSING, recs3["bbn"]["status"])
    check("18 source ginne se coverage nahi banta",
          ax.coverage_summary(list(recs3.values()))["axes_covered"] <= 1,
          str(ax.coverage_summary(list(recs3.values()))["axes_covered"]))
# ── 5. summary: "naapa hi nahi" ≠ "zero mila" ───────────────────────────────

def test_summary_unknown_is_not_zero() -> None:
    print("\n[5] coverage_summary — unknown None hai, 0 nahi")
    empty = ax.coverage_summary([])
    check("kuch naapa nahi -> axes_covered None",
          empty["axes_covered"] is None, str(empty["axes_covered"]))
    check("kuch naapa nahi -> mandatory_missing None",
          empty["mandatory_missing"] is None, str(empty["mandatory_missing"]))
    check("kuch naapa nahi -> coverage_ratio None",
          empty["coverage_ratio"] is None, str(empty["coverage_ratio"]))
    check("axes_total sirf yahi 0 hota hai", empty["axes_total"] == 0)
    check("None wala summary bhi crash nahi karta",
          ax.coverage_summary(None)["axes_covered"] is None)

    axes = ax.axes_for(DM_QUESTION)
    recs = ax.coverage(axes, [ROTATION], searched={"rotation_curves": ["q1"],
                                                   "cmb": ["q1"], "bbn": ["q1"]})
    got = ax.coverage_summary(recs)
    check("17 axes gine gaye", got["axes_total"] == 17, str(got["axes_total"]))
    check("ek relevant source 17 raaste nahi bharta",
          got["axes_covered"] == 2, str(got["axes_covered"]))
    check("jinpar search gayi aur kuch nahi mila = MISSING 2",
          got["axes_missing"] == 2, str(got["axes_missing"]))
    check("jinpar search hi nahi gayi = 13 (unknown, zero nahi)",
          got["axes_not_searched"] == 13, str(got["axes_not_searched"]))
    check("zaroori raaste khaali gine gaye",
          got["mandatory_missing"] == 15, str(got["mandatory_missing"]))
    check("coverage ratio sach bolta hai (0.118)",
          got["coverage_ratio"] < 0.2, str(got["coverage_ratio"]))
    labels = " | ".join(got["missing_labels"])
    for word in ("CMB", "nucleosynthesis", "lensing", "Bullet Cluster",
                 "large-scale", "dwarf", "direct particle"):
        check(f"khaali raasta naam se dikhta hai: {word}", word in labels, labels)
    check("missing_labels 12 par capped", len(got["missing_labels"]) <= 12,
          str(len(got["missing_labels"])))

# ── 6. agli koshish: wahi query dobara nahi jaati ───────────────────────────

def test_next_queries_advance_the_ladder() -> None:
    print("\n[6] next_queries — seedhi aage badhti hai, dohrati nahi")
    axes = ax.axes_for(DM_QUESTION)
    first = ax.next_queries(axes, [], "dark matter evidence", round_no=1, limit=3)
    check("pehle round mein 3 query", len(first) == 3, str(len(first)))
    check("pehle round mein pehli seedhi (exact)",
          [r["step"] for r in first] == [1, 1, 1], str([r["step"] for r in first]))
    check("mandatory curated axis pehle aate hain",
          first[0]["axis_id"] == "rotation_curves", first[0]["axis_id"])

    tried = ax.coverage(axes, [], searched={a.axis_id: ["q1"] for a in axes})
    second = ax.next_queries(axes, tried, "dark matter", round_no=1, limit=3)
    check("sab par ek query ho chuki -> agli seedhi (step 2)",
          [r["step"] for r in second] == [2, 2, 2],
          str([r["step"] for r in second]))
    check("step 2 ka naam synonym",
          all(r["name"] == "synonym" for r in second),
          str([r["name"] for r in second]))
    check("query text bhi badla (dohrav nahi)",
          {r["query"] for r in second}.isdisjoint({r["query"] for r in first}),
          str([r["query"] for r in second]))

    covered_all = [{"axis_id": a.axis_id, "ladder_steps_used": 1,
                    "status": ax.AXIS_COVERED} for a in axes]
    check("jispar search hui aur cover bhi ho gaya -> dobara nahi poochte",
          ax.next_queries(axes, covered_all, "dark matter", 1, 3) == [])
    capped = ax.next_queries([axes[0]], [{"axis_id": axes[0].axis_id,
                                          "ladder_steps_used": 9,
                                          "status": ax.AXIS_MISSING}],
                             "dark matter", round_no=9, limit=1)
    check("ladder 6 se aage nahi jaati", capped[0]["step"] == 6,
          str(capped[0]["step"]))
    check("aakhri seedhi counter-side hoti hai",
          capped[0]["name"] == "counter", capped[0]["name"])
    check("axes khaali -> koi query nahi (crash nahi)",
          ax.next_queries([], [], "dark matter", 1, 3) == [])

# ── 7. counter-side ke liye ek slot RESERVED hai ────────────────────────────

def test_counter_axis_always_gets_a_slot() -> None:
    print("\n[7] Counter-search budget ki daya par nahi — slot reserved")
    axes = ax.axes_for(DM_QUESTION)
    ids = [a.axis_id for a in axes]
    check("counter axis list mein aakhir mein hai (isliye chhoot jaata tha)",
          ids.index("counter_evidence") == len(ids) - 1,
          str(ids.index("counter_evidence")))
    first = ax.next_queries(axes, [], "dark matter evidence", round_no=1, limit=3)
    check("3 ke chhote budget mein bhi counter query jaati hai",
          any("counter" in r["axis_id"] for r in first),
          str([r["axis_id"] for r in first]))
    only_one = ax.next_queries(axes, [], "dark matter", round_no=1, limit=1)
    check("budget 1 ho to bhi counter hi chuna jaata hai",
          only_one[0]["axis_id"] == "counter_evidence", only_one[0]["axis_id"])
    counter_row = [r for r in first if "counter" in r["axis_id"]][0]
    check("counter query criticism/limitation ki taraf jaati hai",
          any(w in counter_row["query"].lower()
              for w in ("criticism", "limitation", "against", "problem")),
          counter_row["query"])
    done = ax.coverage(axes, [], searched={"counter_evidence": ["q1"]})
    after = ax.next_queries(axes, done, "dark matter", round_no=1, limit=3)
    check("counter par query ho gayi to slot zabardasti nahi chheenta",
          not any("counter" in r["axis_id"] for r in after),
          str([r["axis_id"] for r in after]))
    check("us haalat mein poora budget doosre axes ko milta hai",
          len(after) == 3, str(len(after)))

# ── 8. §10 — counter-search "chali ya nahi" teen haalat ─────────────────────

def test_counter_search_flag_is_tri_state() -> None:
    print("\n[8] counter_search_done — None / False / True")
    axes = ax.axes_for(DM_QUESTION)
    check("axes naape hi nahi -> None (jhoothi True nahi)",
          ax.counter_search_done(None) is None)
    check("khaali record -> None", ax.counter_search_done([]) is None)
    no_counter = ax.coverage([a for a in axes if "counter" not in a.axis_id],
                             [ROTATION], searched={"rotation_curves": ["q1"]})
    check("counter axis hi nahi tha -> None",
          ax.counter_search_done(no_counter) is None)
    never = ax.coverage(axes, [ROTATION], searched={"rotation_curves": ["q1"]})
    check("counter par ek bhi query nahi gayi -> False",
          ax.counter_search_done(never) is False,
          str(ax.counter_search_done(never)))
    ran = ax.coverage(axes, [ROTATION], searched={"counter_evidence": ["q1"]})
    check("counter par query chali -> True", ax.counter_search_done(ran) is True)

# ── 9. user ne jo naam KHUD liya, uska apna axis banta hai ──────────────────

NAMED_QUESTION = ("XENONnT aur LZ ke data se dark matter direct detection par "
                  "research karo, aur Bullet Cluster ka lensing bhi dekho")


def test_named_entities_become_mandatory_axes() -> None:
    print("\n[9] Sawaal mein liya gaya naam apna mandatory axis banta hai")
    names = ax.named_entities(NAMED_QUESTION)
    check("XENONnT pakda gaya", "XENONnT" in names, str(names))
    check("Bullet Cluster (do shabd wala naam) bhi pakda gaya",
          "Bullet Cluster" in names, str(names))
    check("andaza nahi lagaya — jo likha hi nahi wo naam nahi aaya",
          "LUX" not in names and "PandaX" not in names, str(names))
    check("RV/APP/VERIFIED jaise apne shabd naam nahi bante",
          not ({"RV", "APP", "VERIFIED", "DEEP", "NO", "SOURCE"} & set(
              ax.named_entities("RV APP ka DEEP run VERIFIED tha, NO SOURCE mila"))),
          str(ax.named_entities("RV APP ka DEEP run VERIFIED tha, NO SOURCE mila")))
    check("'Dark Matter' khud ko entity nahi banata",
          "Dark Matter" not in ax.named_entities("Dark Matter par research"),
          str(ax.named_entities("Dark Matter par research")))

    axes = ax.axes_for(NAMED_QUESTION)
    ids = [a.axis_id for a in axes]
    check("named axis add hua", "named_xenonnt" in ids, str(ids))
    named = [a for a in axes if a.axis_id.startswith("named_")][0]
    check("named axis bhi mandatory hai", named.mandatory is True)
    check("named axis entity yaad rakhta hai", named.entity == "XENONnT",
          str(named.entity))
    check("named axis ki wajah user ke naam par hai",
          "XENONnT" in named.why and "naam" in named.why, named.why)
    check("named axis ki apni query banti hai",
          "XENONnT" in named.base_query(), named.base_query())
    check("jo naam curated axis pehle se cover karta hai uska duplicate nahi",
          "named_bullet_cluster" not in ids and "bullet_cluster" in ids, str(ids))
    check("named axis ke baad bhi domain set dark_matter hi raha",
          ax.axis_set_for(NAMED_QUESTION)[0] == "dark_matter")
    check("named axis ke saath bhi ladder chalti hai",
          len(named.ladder("dark matter")) == 6)
    check("dono run same (deterministic)",
          [a.axis_id for a in ax.axes_for(NAMED_QUESTION)] == ids)

# ── 10. ASLI TAALA: khaali zaroori axis par jawab COMPLETE nahi ho sakta ────

def _delivered(**extra) -> dict:
    """Baaki sab shart poori — sirf axes wali baat test ke haath mein rahe."""
    base = {
        "sections_present": list(quality_contract(DM_QUESTION, _Mode("DEEP"))
                                 ["required_sections"]),
        "counter_search_performed": True,
        "directly_relevant_sources": 9,
        "average_relevance": 0.71,
    }
    base.update(extra)
    return base


def test_ledger_blocks_complete_and_verified_on_axis_gaps() -> None:
    print("\n[10] Ledger: zaroori raasta khaali -> COMPLETE/VERIFIED band")
    contract = quality_contract(DM_QUESTION, _Mode("DEEP"))
    check("DEEP mein axes mandatory hain",
          contract["evidence_axes_required"] is True)

    gaps = contract_ledger(contract, _delivered(
        axes_total=17, axes_covered=1, axes_mandatory_missing=16,
        axes_missing_labels=["CMB / Planck power spectrum",
                             "Big-Bang nucleosynthesis / baryon budget"]))
    check("jawab COMPLETE nahi", gaps["answer_complete"] is False)
    check("VERIFIED likhna mana", gaps["verified_allowed"] is False)
    check("result_state INSUFFICIENT_EVIDENCE (sirf PARTIAL nahi)",
          gaps["result_state"] == "INSUFFICIENT_EVIDENCE", gaps["result_state"])
    item = [i for i in gaps["items"] if i["key"] == "evidence_axes"][0]
    check("ledger mein raaste ki ginti dikhti hai",
          item["got"] == "1/17 raaste par relevant source", item["got"])
    check("item mandatory hai", item["mandatory"] is True)
    check("wajah mein khaali raaste ka naam hai", "CMB" in item["why"], item["why"])
    check("saaf likha hai ki source ki ginti kami nahi dhakti",
          "ginti" in item["why"], item["why"])
    check("mandatory_missing list mein evidence_axes hai",
          "evidence_axes" in [i["key"] for i in gaps["mandatory_missing"]],
          str([i["key"] for i in gaps["mandatory_missing"]]))
    check("18 source bhi ise pass nahi karwa sakte",
          contract_ledger(contract, _delivered(
              directly_relevant_sources=18, average_relevance=0.90,
              axes_total=17, axes_covered=1,
              axes_mandatory_missing=16))["answer_complete"] is False)

def test_ledger_unknown_coverage_is_not_a_pass() -> None:
    print("\n[10b] Naapa hi nahi -> pass nahi, PARTIAL")
    contract = quality_contract(DM_QUESTION, _Mode("MAXIMUM"))
    unknown = contract_ledger(contract, _delivered())
    item = [i for i in unknown["items"] if i["key"] == "evidence_axes"][0]
    check("ok None hai (na pass, na fail ka jhooth)", item["ok"] is None)
    check("unknown flag lagta hai", item["unknown"] is True)
    check("got saaf kehta hai 'check nahi hua'",
          item["got"] == "check nahi hua", item["got"])
    check("wajah likhi hai ki naapa hi nahi gaya",
          "naapa" in item["why"], item["why"])
    check("phir bhi jawab COMPLETE nahi", unknown["answer_complete"] is False)
    check("aur VERIFIED bhi nahi", unknown["verified_allowed"] is False)
    check("state PARTIAL (evidence kam nahi, check adhoora hai)",
          unknown["result_state"] == "PARTIAL", unknown["result_state"])


def test_ledger_passes_when_every_axis_is_covered() -> None:
    print("\n[10c] Sab raaste bhare -> COMPLETE (gate zid nahi karta)")
    contract = quality_contract(DM_QUESTION, _Mode("DEEP"))
    ok = contract_ledger(contract, _delivered(
        axes_total=17, axes_covered=17, axes_mandatory_missing=0))
    item = [i for i in ok["items"] if i["key"] == "evidence_axes"][0]
    check("item pass hua", item["ok"] is True)
    check("pass hone par jhoothi wajah nahi chipkti", item["why"] == "",
          item["why"])
    check("jawab COMPLETE", ok["answer_complete"] is True)
    check("VERIFIED allowed", ok["verified_allowed"] is True)
    check("state COMPLETE", ok["result_state"] == "COMPLETE", ok["result_state"])


def test_quick_mode_shows_gap_without_lying() -> None:
    print("\n[10d] QUICK: kami dikhti hai, par 'turant jawab' ka wada nahi tootta")
    contract = quality_contract(DM_QUESTION, _Mode("QUICK"))
    check("QUICK mein axes mandatory nahi",
          contract["evidence_axes_required"] is False)
    led = contract_ledger(contract, _delivered(
        axes_total=17, axes_covered=1, axes_mandatory_missing=16))
    item = [i for i in led["items"] if i["key"] == "evidence_axes"][0]
    check("item chhupaya nahi gaya", item["got"].endswith("relevant source"),
          item["got"])
    check("par mandatory nahi", item["mandatory"] is False)
    check("kami sach likhi hai (ok False)", item["ok"] is False)
    check("QUICK ka status isse nahi girta", led["answer_complete"] is True)
    check("counter-search QUICK mein bhi mandatory hai",
          contract["counter_search_required"] is True)

# ── 11. user ko dikhne wali baat: "kya nahi mila" ───────────────────────────

def test_coverage_note_names_what_is_missing() -> None:
    print("\n[11] coverage_note — '18 source mile' ki jagah 'kya nahi mila'")
    check("naapa nahi gaya to note khud kehta hai ki keh nahi sakte",
          "naapa nahi gaya" in ax.coverage_note(None), ax.coverage_note(None))
    check("khaali list par bhi wahi imaandaar line",
          "naapa nahi gaya" in ax.coverage_note([]))
    axes = ax.axes_for(DM_QUESTION)
    recs = ax.coverage(axes, [ROTATION, EXOPLANET],
                       searched={"rotation_curves": ["q1"], "cmb": ["q1"],
                                 "bbn": ["q1"]})
    note = ax.coverage_note(recs)
    first = note.splitlines()[0]
    check("pehli line mein chaaron ginti hai",
          all(w in first for w in ("relevant source mila", "kamzor match",
                                   "dhoondh kar bhi kuch nahi",
                                   "search hi nahi hui")), first)
    check("CMB ka naam le kar batata hai ki nahi mila",
          "CMB" in note, note[:400])
    check("khaali raaste ke saath status likha hai",
          ax.AXIS_MISSING in note or ax.AXIS_NOT_SEARCHED in note, note[:200])
    check("wajah bhi likhi hai ki ye raasta zaroori kyun tha",
          "kyun zaroori" in note, note[:400])
    check("aakhir mein saaf faisla: jawab poora nahi",
          "poora nahi kaha ja sakta" in note, note[-200:])
    check("cover ho chuke raaste shor nahi karte (line nahi banti)",
          "rotation" not in note.lower().split("\n", 1)[1][:200],
          note.split("\n", 1)[1][:200])
    check("limit maanti hai (bahut lambi list nahi)",
          len(ax.coverage_note(recs, limit=2).splitlines())
          <= len(note.splitlines()))

# ── 12. deterministic + koi network call nahi ───────────────────────────────

def test_everything_is_deterministic_and_offline() -> None:
    print("\n[12] Do run bilkul same, aur koi API call nahi")
    axes = ax.axes_for(DM_QUESTION)
    searched = {"rotation_curves": ["q1"], "cmb": ["q1"]}
    run1 = ax.coverage(axes, [ROTATION, EXOPLANET], searched=searched)
    run2 = ax.coverage(ax.axes_for(DM_QUESTION), [ROTATION, EXOPLANET],
                       searched=searched)
    check("coverage record same", run1 == run2)
    check("summary same", ax.coverage_summary(run1) == ax.coverage_summary(run2))
    check("note same", ax.coverage_note(run1) == ax.coverage_note(run2))
    check("next_queries same",
          ax.next_queries(axes, run1, "dark matter", 2, 3)
          == ax.next_queries(axes, run2, "dark matter", 2, 3))
    check("axes_to_dict serialize hota hai",
          len(ax.axes_to_dict(axes)) == len(axes)
          and all("axis_id" in d and "why" in d for d in ax.axes_to_dict(axes)))
    check("module mein koi network/LLM import nahi",
          not any(m in open(ax.__file__, encoding="utf-8").read()
                  for m in ("import requests", "import httpx", "genai",
                            "urllib.request")))
    check("floor 0.50 hai (relevance gate ke saath ek jaisa)",
          abs(ax.COVERAGE_FLOOR - 0.50) < 1e-9, str(ax.COVERAGE_FLOOR))
    check("6 hi ladder steps hain", len(ax.LADDER_STEPS) == 6,
          str(len(ax.LADDER_STEPS)))


def main() -> int:
    print("=" * 70)
    print("§5 EVIDENCE AXES — coverage, ladder aur 'ginti ≠ coverage'")
    print("=" * 70)
    test_dark_matter_axes_present()
    test_ladder_has_six_distinct_steps()
    test_status_is_tri_state()
    test_rejected_sources_never_cover_an_axis()
    test_summary_unknown_is_not_zero()
    test_next_queries_advance_the_ladder()
    test_counter_axis_always_gets_a_slot()
    test_counter_search_flag_is_tri_state()
    test_named_entities_become_mandatory_axes()
    test_ledger_blocks_complete_and_verified_on_axis_gaps()
    test_ledger_unknown_coverage_is_not_a_pass()
    test_ledger_passes_when_every_axis_is_covered()
    test_quick_mode_shows_gap_without_lying()
    test_coverage_note_names_what_is_missing()
    test_everything_is_deterministic_and_offline()
    print("\n" + "=" * 70)
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
