"""
Benchmark V2 — superconductivity ka wahi HARD sawal, poori tarah OFFLINE.

Kyun: is sawal par live run mein ek saath teen tarah ki galtiyan aayi thin —
(a) bilkul unrelated sources (WHO maternal mortality, NHA data, sunbed cancer,
banana/luffa agriculture, HfO2 ferroelectricity), (b) Gemini ka 429 raw protobuf
jawab mein chhap gaya, (c) phir bhi report confident dikhi. Ye benchmark unhi
teen cheezon ka permanent taala hai — fixed fixtures ke saath, taaki result
network ke mood par depend na kare.

Chalao:  python3 tests/benchmark_superconductivity.py

Kya check hota hai (Benchmark V2 scorecard):
    1. kachra reject      — paanchon junk source final pack se bahar
    2. ranking            — superconductivity ka peer-reviewed paper sabse upar
    3. imaandaar labels    — read_level wahi jo reader ne sach mein diya
    4. koi raw API error   — insaani hisse mein 429/protobuf nahi
    5. imaandaar status    — quota mare to RESEARCH INCOMPLETE, healthy par COMPLETE
    6. consensus gate      — sirf supporting evidence se "consensus" nahi banta
    7. physics sanity      — galat unit conversion pakda jaata hai
    8. hypotheses          — evidence strong ho to 3+, LLM mare to plan
    9. structure           — insaan pehle, sources/audit sabse aakhir
   10. ₹0                  — koi network call nahi, sab stubbed aur deterministic
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_reasoning                  # noqa: E402
from research_engine.models import SourceRecord, SourceType    # noqa: E402
from research_engine.orchestrator import DeepResearchEngine    # noqa: E402

PASSED = 0
FAILED = 0

# intel ka diya hua exact benchmark sawal (shabd badle nahi gaye).
QUESTION = (
    "Kya room-temperature superconductivity practically possible hai? Ambient "
    "pressure par kaun-kaun se materials (hydrides, cuprates) ka critical "
    "temperature sabse zyada hai, aur power grid ya quantum computing mein "
    "iska kya fayda hoga?")

# ── fixtures ─────────────────────────────────────────────────────────────────
# (title, url, snippet, peer_reviewed, doi, connector, type)
ROUND1 = [
    ("Superconductivity at 250 K in lanthanum hydride under high pressures",
     "https://arxiv.org/abs/1812.01561",
     "LaH10 shows a superconducting critical temperature of 250 K at 170 GPa. "
     "Resistance drop, isotope effect and magnetic field dependence are "
     "reported for the hydride sample in a diamond anvil cell.",
     True, "10.1038/s41586-019-1201-8", "arxiv", SourceType.PAPER),
    ("Room-temperature superconductivity in a carbonaceous sulfur hydride",
     "https://www.nature.com/articles/s41586-020-2801-z",
     "A critical temperature of 288 K is reported in carbonaceous sulfur "
     "hydride at 267 GPa. The paper was later retracted after questions about "
     "the background subtraction of the raw susceptibility data.",
     True, "10.1038/s41586-020-2801-z", "crossref", SourceType.PAPER),
    ("Highest ambient-pressure critical temperature in mercury cuprates",
     "https://openalex.org/W2100",
     "HgBa2Ca2Cu3O8+d holds the highest confirmed ambient-pressure "
     "superconducting transition temperature at about 133 K, rising to 164 K "
     "under 30 GPa of applied pressure.",
     True, "10.1038/363056a0", "openalex", SourceType.PAPER),
]

ROUND2 = [
    ("Comment on claimed room-temperature superconductivity in hydrides",
     "https://arxiv.org/abs/2110.12854",
     "The reported transition is not supported by the published raw data. "
     "Independent replication of the carbonaceous sulfur hydride result has "
     "failed, and the criticism concerns data processing, not chemistry.",
     True, "10.1088/1361-6668/critique", "arxiv", SourceType.PAPER),
    ("Superconducting power transmission cable field demonstration",
     "https://zenodo.org/record/778899",
     "A 1 km high-temperature superconducting cable cooled by liquid nitrogen "
     "carried 200 MW in a city grid trial, with measured losses and the "
     "cryogenic energy penalty tabulated.",
     False, "10.5281/zenodo.778899", "zenodo", SourceType.DATASET),
]

ROUND3 = [
    ("Nickelate thin films: superconductivity without copper",
     "https://openalex.org/W3300",
     "Infinite-layer nickelate thin films superconduct below 15 K at ambient "
     "pressure, giving a second family to test pairing mechanisms.",
     True, "10.1038/nickelate", "openalex", SourceType.PAPER),
    ("Josephson junctions and transmon qubits: why Tc matters for quantum "
     "computing",
     "https://doaj.org/article/qubit-tc",
     "Superconducting qubits need materials with low loss; a higher critical "
     "temperature would relax dilution-refrigerator requirements but coherence "
     "depends on surface losses, not Tc alone.",
     True, "10.1234/qubit-tc", "doaj", SourceType.PAPER),
]

# Bilkul wahi kachra jo live benchmark mein aa gaya tha.
JUNK = [
    ("Trends in maternal mortality 2000 to 2020",
     "https://www.who.int/publications/maternal-mortality",
     "WHO, UNICEF and UNFPA estimates of maternal mortality ratios by country.",
     True, "10.1/mmr", "who_gho", SourceType.DATASET),
    ("National Health Accounts estimates for India",
     "https://data.gov.in/nha-estimates",
     "Out-of-pocket health expenditure share of total health expenditure.",
     False, "", "data_gov_in", SourceType.DATASET),
    ("Sunbed use and melanoma risk: a population survey",
     "https://openalex.org/W777",
     "Indoor tanning behaviour and skin cancer incidence in adults.",
     True, "10.1/sunbed", "openalex", SourceType.PAPER),
    ("Banana pseudostem and luffa fibre composites for packaging",
     "https://openalex.org/W888",
     "Mechanical properties of banana and luffa natural fibre composites.",
     True, "10.1/luffa", "openalex", SourceType.PAPER),
    ("Ferroelectricity in hafnium oxide thin films for memory devices",
     "https://openalex.org/W555",
     "HfO2 films show ferroelectric polarization switching useful for FeRAM "
     "memory. The effect comes from the polar orthorhombic phase and is "
     "dielectric in nature.",
     True, "10.1/hfo2", "openalex", SourceType.PAPER),
]


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def eq(name: str, got, want) -> None:
    check(name, got == want, f"mila {got!r}, chahiye {want!r}")


def _records(rows) -> list:
    """Har call par taaza objects — pipeline inhe mutate karta hai."""
    return [SourceRecord(
        title=t, url=u, snippet=s, connector=conn, source_type=kind,
        peer_reviewed=peer, doi=doi, year=2023, full_text_available=bool(doi))
        for t, u, s, peer, doi, conn, kind in rows]


class _FakeVectors:
    last_error = ""

    def retrieve(self, question, project_id, n_results=4):
        return {"context": "", "sources": []}


class _Discovery:
    """Round-wise fixtures + har round mein thoda kachra (asli haalat)."""

    def __init__(self, per_round: dict):
        self.per_round = per_round
        self.calls: list = []

    def __call__(self, **kwargs):
        round_no = int(kwargs.get("round_no") or 1)
        self.calls.append((round_no, list(kwargs.get("queries") or [])))
        records = _records(self.per_round.get(round_no, []))
        return {
            "records": records,
            "log": [{"connector": "openalex", "count": len(records), "error": "",
                     "reason": "", "note": "", "seconds": 0.4}],
            "connectors_searched": ["arxiv", "openalex", "crossref", "zenodo"],
            "seen_urls": {r.url for r in records},
        }


# Sirf inhi ka full text milta hai — labels ki imaandaari isi se test hoti hai.
FULL_TEXT_URLS = {
    "https://arxiv.org/abs/1812.01561",
    "https://www.nature.com/articles/s41586-020-2801-z",
    "https://openalex.org/W2100",
    "https://arxiv.org/abs/2110.12854",
}


def _reader(pack, max_sources=3, budget_chars=2400):
    """
    Reader network par jaata hai, isliye stub. Jo full text de sakta hai usi ka
    read_level badalta hai — baaki honestly "paywall" bolta hai. Yahi cheez
    point 5 (labels 100% honest) ko testable banati hai.
    """
    entries = []
    for source in pack.sources[:max_sources]:
        if (source.url or "") in FULL_TEXT_URLS:
            source.full_text_chars = 48000
            source.read_level = "full_text"
            entries.append({"source_id": source.source_id, "ok": True,
                            "chars": 48000, "reason": "", "title": source.title})
        else:
            entries.append({"source_id": source.source_id, "ok": False,
                            "chars": 0, "title": source.title,
                            "reason": "publisher paywall — koi legal free route "
                                      "nahi mila"})
    ok = [e for e in entries if e["ok"]]
    return {"attempted": len(entries), "succeeded": len(ok),
            "failed": len(entries) - len(ok), "skipped": 0,
            "chars_read": sum(e["chars"] for e in entries),
            "note": f"{len(ok)}/{len(entries)} ka full text mila",
            "entries": entries}


# Har round mein thoda kachra jaan-boojh kar (URL dobara nahi, warna duplicate
# ban jaata aur test ki asli baat — "kachra hataya gaya" — dhundhli ho jaati).
#
# Round 1/2 jaan-boojh kar patle hain: 3 se kam independent source par engine
# khud aur round chalata hai. Yahi asli haalat bhi hai — pehli hi search mein
# poora jawab nahi milta, aur criticism/grid/qubit ka evidence baad ke rounds
# mein aata hai.
ALL_ROUNDS = {
    1: ROUND1[0:1] + JUNK[0:2],
    2: ROUND1[1:2] + JUNK[2:4],
    3: ROUND1[2:3] + ROUND2 + ROUND3 + JUNK[4:5],
}
SUPPORT_ONLY = {1: ROUND1, 2: [], 3: []}


def _hypothesis_blocks(count: int = 3) -> str:
    """
    Parser ke maange hue labels ke saath poori hypotheses (adhoora dhaancha nahi).
    point 11 chahta hai: support, counter-evidence, assumptions, falsification,
    required experiment aur confidence — sab asli.
    """
    seeds = [
        ("Ambient pressure par Tc ki chhat lattice ki stiffness tay karti hai",
         "hydrogen ke halke atom tezi se hilte hain, aur yahi tez hilna current "
         "ko bina rukawat behne deta hai", "[S1]", "[S3] mein bina pressure ke "
         "Tc sirf 133 K tak pahunchta hai",
         "pressure calibration dono papers mein ek hi tareeke se hui hai",
         "H-H distance 5% ghatane par Tc 20 K badhega",
         "diamond anvil cell mein 10 sample, 4-probe resistance + magnetic "
         "susceptibility, ek control sample bina hydrogen ke",
         "agar H-H distance ghatane par Tc na badhe to ye hypothesis khatam",
         "MEDIUM"),
        ("Retracted hydride result ka asli sabab background subtraction tha",
         "raw data se background hatane ka tareeka galat tha, isliye jump asli "
         "nahi tha", "[S4]", "[S2] ka original paper aaj bhi 288 K claim karta hai",
         "dono groups ne ek jaisa sample banaya tha",
         "raw susceptibility publish hone par jump gayab ho jayega",
         "teen independent lab mein same synthesis, raw data pehle se register "
         "kiya hua (pre-registered)",
         "agar raw data mein jump bacha rahe to ye hypothesis khatam", "LOW"),
        ("Grid ka asli faisla cryogenic energy penalty se hoga, Tc se nahi",
         "thanda rakhne mein jo bijli lagti hai, wahi tay karti hai ki cable "
         "faydemand hai ya nahi", "[S5]", "[S6] ke mutabiq qubit ke liye Tc se "
         "zyada surface loss maayne rakhta hai",
         "liquid nitrogen ki supply chain sasti bani rahegi",
         "60% se zyada penalty par HTS cable copper se mehnga padega",
         "1 km cable par 12 mahine ka load trial, copper cable ke saath "
         "side-by-side metering",
         "agar penalty ke baad bhi total loss copper se kam rahe to ye "
         "hypothesis khatam", "MEDIUM"),
    ]
    out = []
    for i, (stmt, simple, support, counter, assume, pred, exp, fals,
            conf) in enumerate(seeds[:count], start=1):
        out.append(
            f"## Hypothesis {i}\n"
            f"- Statement: {stmt}\n"
            f"- Simple explanation: Humara idea ye hai ki {simple}. Jaise ghar "
            f"ki tanki ka pump — pump ka kharcha bachat se zyada ho to poora "
            f"idea bekaar.\n"
            f"- Reasoning: Step 1 — {support} ka data. Step 2 — usi tarah ka "
            f"lattice doosre paper mein kam Tc deta hai.\n"
            f"- Supporting evidence: {support} isi taraf ishara karta hai\n"
            f"- Counter-evidence: {counter}\n"
            f"- Novelty: pehle ye farak sirf measurement error par daala gaya tha\n"
            f"- Assumptions: {assume}\n"
            f"- Prediction: {pred}\n"
            f"- Required experiment: {exp}\n"
            f"- Falsification test: {fals}\n"
            f"- Risks: high-pressure setup mein diamond failure ka khatra\n"
            f"- Confidence: {conf}\n")
    return "\n".join(out)


# Jo raw text kabhi bhi insaani jawab mein nahi dikhna chahiye (point 9).
RAW_TOKENS = ("ResourceExhausted", "grpc_status", "quota_id", "retry_delay",
              "Traceback", "protobuf", "RuntimeError")

_ANALYSIS = (
    "## Factual Findings\n"
    "- [ESTABLISHED] LaH10 mein 250 K ka Tc 170 GPa par report hua [S1].\n"
    "- [SOURCE-REPORTED] Carbonaceous sulfur hydride ka 288 K ka claim baad "
    "mein retract hua [S2].\n"
    "- [ESTABLISHED] Ambient pressure ka sabse ooncha confirmed Tc mercury "
    "cuprate mein ~133 K hai [S3].\n"
    "## Context & Mechanisms\n"
    "Hydride mein hydrogen ke halke atom lattice ko tez hilate hain, isse "
    "electron jodi (Cooper pair) banana aasan hota hai [S1].\n"
    "## Cross-Disciplinary Connections\n"
    "Power grid ka faisla cryogenic penalty par tikta hai [S5], aur quantum "
    "computing mein Tc se zyada surface loss maayne rakhta hai [S6].\n"
    "## Evidence Audit\n[MIXED EVIDENCE] [S1] [S2] [S3] [S4]\n"
    "## Source Relevance Check\n"
    "Saare use kiye gaye sources superconductivity ke hi hain.\n")

_CRITIQUE = (
    "## Weaknesses\n"
    "- [S2] retract ho chuka hai, isliye 288 K ko result nahi maana ja sakta.\n"
    "- Sabhi ooncha Tc high pressure par hai, ambient par nahi [S1].\n"
    "## Missing Evidence\n"
    "- Ambient pressure par 200 K+ ka koi replication nahi mila.\n"
    "## Alternative Explanations\n"
    "- Resistance drop measurement artefact bhi ho sakta hai [S4].\n")


def _synthesis(bad_math: bool = False) -> str:
    """Healthy synthesis. `bad_math=True` par wahi galtiyan jo point 12 pakadta
    hai: ek hi value do units mein galat, aur ulti tulna."""
    numbers = ("Tc 250 K (-23.15 °C) tak pahuncha hai [S1], jo liquid nitrogen "
               "ke 77 K se zyada hai.")
    if bad_math:
        numbers = ("Tc 250 K (23 °C) tak pahuncha hai [S1], jo 30 °C se zyada "
                   "hai.")
    return (
        "## Seedha jawab\n"
        "Aaj tak ambient pressure par room-temperature superconductivity kisi "
        "ne confirm nahi ki. Sabse ooncha bharosemand ambient Tc mercury "
        "cuprate ka ~133 K hai [S3]; 250-288 K wale claims ya to bahut ooncha "
        "pressure maangte hain [S1] ya retract ho gaye [S2].\n\n"
        "## Research se kya pata chala?\n"
        "### Fact\n"
        f"- **[S1] LaH10:** {numbers}\n"
        "- **[S3] Hg-cuprate:** ambient par ~133 K, 30 GPa par ~164 K.\n"
        "### Inference\n"
        "- [INFERENCE] Pressure hataane par aaj ke hydride ka fayda khatam ho "
        "jaata hai [S1].\n\n"
        "## Ye kyun hota hai?\n"
        "Halke hydrogen atom lattice ko tez hilate hain, par unhe ek jagah "
        "rakhne ke liye bahut pressure chahiye [S1].\n\n"
        "## Evidence kya kehta hai?\n"
        "Do papers ka full text padha gaya, ek claim retract hai [S2], aur ek "
        "swatantra criticism bhi mili [S4].\n\n"
        "## Iske against kya mila?\n"
        "Replication fail hui aur data processing par sawaal uthe [S4].\n\n"
        "## Kya abhi unknown hai?\n"
        "Ambient pressure par 200 K+ ka koi confirmed material nahi mila.\n\n"
        "## Final conclusion\n"
        "Grid ke liye aaj bhi 77 K wale cuprate cable hi practical hain [S5]; "
        "quantum computing mein Tc badhne se dilution fridge ki zaroorat kam "
        "hogi par coherence ka masla surface loss ka hai [S6].\n")


class _Gemini:
    """
    `GeminiReasoning.generate` ki jagah — teen mood:

        healthy   — teeno pass theek, [S#] citations ke saath
        dead      — pehli call se hi 429 (khaali string + errors entry, exactly
                    jaise asli code karta hai — exception nahi)
        bad_math  — jawab aata hai par usme galat unit conversion aur ulti tulna
    """

    def __init__(self, mood: str = "healthy", fail_after: int = 99):
        self.mood = mood
        self.fail_after = 0 if mood == "dead" else fail_after
        self.labels: list = []
        self.prompts: list = []

    def __call__(self, brain, prompt, label=""):
        if brain.remaining <= 0:
            raise gemini_reasoning.QuotaExhausted(
                f"call budget ({brain.budget}) khatam — '{label}' skip hua")
        brain.calls_used += 1
        self.labels.append(label)
        self.prompts.append(prompt)
        if brain.calls_used > self.fail_after:
            # Bilkul wahi ganda raw text jo live run mein report mein chhap gaya.
            brain.errors.append(
                f"{label} failed: ResourceExhausted: 429 grpc_status:8 "
                f"quota_id: GenerateRequestsPerDayPerProject "
                f"retry_delay {{ seconds: 44 }}")
            return ""
        wants_hypotheses = "## Hypothesis 1" in prompt
        tail = ("\n\n" + _hypothesis_blocks(3)) if wants_hypotheses else ""
        if label == "critique":
            return _CRITIQUE + tail
        if label == "synthesis":
            return _synthesis(self.mood == "bad_math") + tail
        return _ANALYSIS + tail


# Live benchmark ka poora prompt: sawal + "kam se kam 3 nayi hypotheses banao".
QUESTION_WITH_HYPOTHESES = QUESTION + " Kam se kam 3 nayi hypotheses banao."


def _run(per_round: dict, question: str = QUESTION, mode: str = "MAXIMUM",
         mood: str = "healthy"):
    """Poora asli pipeline — sirf network (discovery/reader/vectors) aur Google
    stubbed. Koi API key, koi paisa, koi randomness."""
    disc = _Discovery(per_round)
    fake = _Gemini(mood=mood)
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="benchmark-v2", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = _FakeVectors()
        engine.discovery.discover = disc
        engine.reader.enrich = _reader
        return engine.research(question, depth_mode=mode), disc, fake
    finally:
        gemini_reasoning.GeminiReasoning.generate = original


def _titles(result: dict) -> str:
    return " | ".join(str(s.get("title", "")) for s in result["sources"])


def _human_part(answer: str) -> str:
    """Report ka wo hissa jo user sach mein padhta hai."""
    return (answer or "").split("### Technical details")[0]


def _heading_pos(answer: str, heading: str) -> int:
    """
    Heading ki jagah — poori line ke shuru se match karke.

    Sirf `answer.index("## Sources")` kaafi nahi hai: "### Sources ne khud kya
    kaha" ke andar bhi "## Sources" chhupa hota hai, aur us galat jagah se
    slice/kram ka poora hisaab bigad jaata hai. Line ke aage kuch aur likha ho
    (jaise "### Technical details (developer ke liye…)") to bhi chalega.
    """
    m = re.search(r"^" + re.escape(heading) + r"(?:\s.*)?$", answer or "", re.M)
    return m.start() if m else -1


# ── 1. kachra reject ────────────────────────────────────────────────────────
def test_junk_sources_are_rejected():
    print("\n1. kachra reject — paanchon unrelated source pack se bahar")
    result, _, _ = _run(ALL_ROUNDS)
    titles = _titles(result).lower()
    for junk in ("maternal mortality", "national health accounts", "sunbed",
                 "banana pseudostem", "ferroelectricity"):
        check(f"final pack mein nahi: {junk}", junk not in titles, titles[:300])
    check("superconductivity ke sources bache hain",
          "superconduct" in titles or "cuprate" in titles or "hydride" in titles,
          titles[:300])
    cov = result["coverage"]
    check("paanchon kachra source honestly off-topic gine gaye",
          int(cov.get("offtopic_dropped") or 0) >= 5,
          str(cov.get("offtopic_dropped")))
    answer = result["answer"]
    for junk in ("maternal mortality", "Banana pseudostem", "Sunbed"):
        check(f"jawab mein bhi kahin cite nahi hua: {junk}",
              junk.lower() not in answer.lower())


# ── 2. ranking ──────────────────────────────────────────────────────────────
def test_top_source_is_a_superconductivity_paper():
    print("\n2. ranking — sabse upar superconductivity ka peer-reviewed paper")
    result, _, _ = _run(ALL_ROUNDS)
    top = result["sources"][0]
    title = str(top.get("title", "")).lower()
    check("top source superconductivity ka hi hai",
          any(word in title for word in
              ("superconduct", "hydride", "cuprate", "nickelate")), title)
    eq("aur wo peer-reviewed hai", top.get("peer_reviewed"), True)
    eq("aur uska type paper hai", top.get("source_type"), "paper")
    check("dataset/grid cable top par nahi chadha",
          "cable" not in title, title)


def _source_blocks(answer: str) -> list:
    """Report ke 'Sources' section ke blocks — (url, 'kitna padha' wali line)."""
    start = _heading_pos(answer, "## Sources")
    end = _heading_pos(answer, "## Research quality / technical audit")
    out = []
    for block in answer[start:end].split("**[S")[1:]:
        lines = block.splitlines()
        url = next((l.strip() for l in lines if l.strip().startswith("http")), "")
        read = next((l for l in lines if "Kitna padha gaya" in l), "")
        out.append((url, read))
    return out


# ── 3. imaandaar read labels ────────────────────────────────────────────────
def test_read_levels_are_honest():
    print("\n3. labels — 'poora text padha' sirf wahan jahan sach mein pada")
    result, _, _ = _run(ALL_ROUNDS)
    blocks = _source_blocks(result["answer"])
    check("sources section mein har source ka block hai", len(blocks) >= 6,
          str(len(blocks)))
    claimed = set()
    for url, read in blocks:
        check(f"access depth likha hua hai: {url[:44]}", bool(read), url)
        if "FULL-TEXT VERIFIED" in read:
            claimed.add(url)
        else:
            check(f"full-text ke bajaye asli depth likhi hai: {url[:44]}",
                  any(word in read for word in ("SNIPPET ONLY", "ABSTRACT REVIEWED",
                                                "METADATA ONLY")), read)
    eq("full-text ka dava bilkul unhi URLs par hai jinka text mila",
       claimed, {u for u, _ in blocks} & FULL_TEXT_URLS)
    levels = result["coverage"]["read_levels"]
    eq("coverage ki ginti bhi wahi kahani kehti hai",
       int(levels.get("full_text") or 0), len(claimed))
    reading = result["coverage"]["reading"]
    eq("reader ki succeeded ginti bhi match karti hai",
       int(reading.get("succeeded") or 0), len(claimed))
    check("jinka text nahi mila unki wajah bhi likhi hai",
          all(e.get("reason") for e in reading["per_source"]
              if not e.get("read")), str(reading["per_source"]))


# ── 4. koi raw API error insaani hisse mein ─────────────────────────────────
def test_no_raw_api_error_reaches_the_user():
    print("\n4. quota mari — 429/protobuf insaani jawab mein nahi")
    result, _, _ = _run(ALL_ROUNDS, mood="dead")
    human = _human_part(result["answer"])
    for token in RAW_TOKENS:
        check(f"insaani jawab mein raw '{token}' nahi", token not in human)
    for token in RAW_TOKENS:
        check(f"warnings mein bhi raw '{token}' nahi",
              token not in " ".join(result.get("warnings", [])))
    check("par wajah chhupayi bhi nahi gayi — insaani bhasha mein likhi hai",
          "quota" in human.lower() or "AI" in human, human[:400])
    tech = " ".join(result.get("technical_details", []))
    check("raw wajah sirf sabse neeche technical block mein zinda hai",
          "429" in tech or "ResourceExhausted" in tech, tech[:200])


# ── 5. imaandaar status ─────────────────────────────────────────────────────
def test_status_is_honest_both_ways():
    print("\n5. status — quota mare to INCOMPLETE, healthy par COMPLETE")
    dead, _, _ = _run(ALL_ROUNDS, mood="dead")
    eq("LLM band tha to status RESEARCH INCOMPLETE",
       dead["status"], "RESEARCH INCOMPLETE")
    check("evidence level bhi wahi kehta hai",
          "RESEARCH INCOMPLETE" in dead["evidence_level"], dead["evidence_level"])
    check("aur VERIFIED/STRONG ka top label nahi laga",
          "UNVERIFIED" in dead["evidence_level"]
          or not any(w in dead["evidence_level"] for w in ("✅ VERIFIED", "STRONG")),
          dead["evidence_level"])
    check("jawab khaali template nahi hai", len(dead["answer"]) > 2000,
          str(len(dead["answer"])))

    ok, _, fake = _run(ALL_ROUNDS)
    eq("teeno reasoning pass chale", fake.labels,
       ["analysis", "critique", "synthesis"])
    eq("healthy run ka status COMPLETE", ok["status"], "COMPLETE")
    check("koi failure_kind nahi", not ok.get("failure_kind"),
          str(ok.get("failure_kind")))


# ── 6. consensus gate ───────────────────────────────────────────────────────
def test_consensus_needs_both_sides():
    print("\n6. consensus — sirf support-side evidence se sehmati nahi banti")
    # QUICK mode: ek hi round chalta hai, aur us round mein criticism wali query
    # nahi jaati — yaani opposition side dekha hi nahi gaya. Aisi haalat mein
    # "sab sehmat hain" likhna wahi bug tha jo live run mein aaya tha.
    result, disc, _ = _run(SUPPORT_ONLY, mode="QUICK")
    answer = result["answer"]
    queries = " ".join(q for _, qs in disc.calls for q in qs).lower()
    check("is run mein sach mein ek bhi criticism-side query nahi chali",
          "criticism" not in queries and "contradictory" not in queries,
          queries[:200])
    check("isliye report saaf kehti hai: consensus evaluate nahi kiya ja saka",
          "Consensus evaluate nahi kiya ja saka" in answer, answer[-1500:])
    check("aur wajah bhi likhi hai — sirf support-side search hui",
          "Sirf support-side search hui" in answer, answer[-1500:])
    check("koi jhoothi 'sab sehmat hain' line nahi",
          "sab sehmat hain" not in answer.lower()
          or "kehna galat hoga" in answer, answer[-1500:])

    # Doosri taraf: poore MAXIMUM run mein round 2/3 mein criticism query jaati
    # hai, isliye gate khulta hai — par tab bhi seemit bhasha ke saath.
    full, disc2, _ = _run(ALL_ROUNDS)
    all_queries = " ".join(q for _, qs in disc2.calls for q in qs).lower()
    check("poore run mein opposition-side query sach mein chali",
          "criticism" in all_queries or "contradictory" in all_queries,
          all_queries[-200:])
    check("gate khulne par bhi dava naapa-tola hai",
          "Consensus ka andaaza retrieved sources tak seemit hai"
          in full["answer"], full["answer"][-1500:])
    check("aur tab 'evaluate nahi ho saka' nahi likha jaata",
          "Consensus evaluate nahi kiya ja saka" not in full["answer"])


# ── 7. physics sanity ───────────────────────────────────────────────────────
def test_physics_sanity_catches_bad_numbers():
    print("\n7. physics — galat unit conversion aur ulti tulna pakdi jaati hai")
    bad, _, _ = _run(ALL_ROUNDS, mood="bad_math")
    eq("verification status numeric galti bata raha hai",
       bad["verification"]["status"], "MATH ERROR FOUND")
    physics = bad["verification"]["physics"]
    eq("physics check chalaya gaya (sawal quantitative tha)",
       physics["applicable"], True)
    failed = [c["check"] for c in physics["checks"] if c["passed"] is False]
    check("'250 K = 23 °C' wali unit galti pakdi gayi",
          "unit conversion" in failed, str(physics["checks"]))
    check("'23 °C, 30 °C se zyada' wali ulti tulna bhi pakdi gayi",
          "comparison direction" in failed, str(physics["checks"]))
    check("report insaani bhasha mein samjhati hai kya galat hai",
          "Ek hi value do units mein alag-alag likhi gayi hai" in bad["answer"],
          bad["answer"][:200])
    check("aur exact number bhi likha hai (250.00 K vs 296.15 K)",
          "296.15 K" in bad["answer"], bad["answer"][:200])
    joined = " | ".join(physics["warnings"])
    check("saaf mana kiya gaya ki ise verified maanein",
          "verified mat maanein" in joined, joined[:300])
    check("aur ye warning user ko dikhne wale hisse tak pahunchi",
          "verified mat maanein" in bad["answer"], "answer mein nahi mili")
    for token in RAW_TOKENS:
        check(f"physics fail hone par bhi raw '{token}' nahi",
              token not in _human_part(bad["answer"]))

    ok, _, _ = _run(ALL_ROUNDS)
    check("sahi numbers wale jawab par ye shor nahi hota",
          ok["verification"]["status"] != "MATH ERROR FOUND",
          ok["verification"]["status"])
    eq("healthy run mein ek bhi sanity check fail nahi",
       ok["verification"]["physics"]["failed"], 0)
    check("aur '250-288 K' jaisi range galti se negative nahi padhi gayi",
          "absolute zero" not in ok["answer"], ok["answer"][:200])


# ── 8. hypotheses ───────────────────────────────────────────────────────────
_HYP_TEXT_FIELDS = (
    ("statement", 25, "statement testable hai"),
    ("simple", 30, "aam bhasha wali line hai"),
    ("contradicting_evidence", 15, "counter-evidence likha hai"),
    ("assumptions", 15, "assumptions likhe hain"),
    ("falsification_test", 15, "falsification test hai"),
    ("experiment", 20, "zaroori experiment/simulation hai"),
)


def test_three_full_hypotheses_when_evidence_is_strong():
    print("\n8. hypotheses — evidence strong ho to 3 poori, LLM mare to plan")
    result, _, _ = _run(ALL_ROUNDS, question=QUESTION_WITH_HYPOTHESES)
    hyps = result["hypotheses"]
    check("maangi hui teen hypotheses mili", len(hyps) >= 3, str(len(hyps)))
    for i, h in enumerate(hyps[:3], start=1):
        for field, least, label in _HYP_TEXT_FIELDS:
            check(f"H{i}: {label}", len(str(h.get(field) or "")) >= least,
                  f"{field}={h.get(field)!r}")
        check(f"H{i}: support source se cite kiya gaya",
              "[S" in str(h.get("supporting_evidence") or ""),
              str(h.get("supporting_evidence")))
        check(f"H{i}: testable prediction hai",
              len(str((h.get("prediction") or {}).get("text") or "")) >= 15,
              str(h.get("prediction")))
        check(f"H{i}: confidence diya gaya",
              str(h.get("confidence_reasoning_based") or "").upper()
              in ("LOW", "MEDIUM", "HIGH"), str(h.get("confidence_reasoning_based")))
        eq(f"H{i}: koi field missing nahi", list(h.get("missing_fields") or []), [])
        eq(f"H{i}: hypothesis ki tarah label hui, fact ki tarah nahi",
           h.get("status"), "UNTESTED HYPOTHESIS")
        check(f"H{i}: disclaimer saath hai",
              "asli validation lab/field test se hi hoga"
              in str(h.get("disclaimer") or ""), str(h.get("disclaimer")))
    check("report mein bhi hypothesis section bhara hua hai",
          "## Humari Hypotheses" in result["answer"]
          and "UNTESTED HYPOTHESIS" in result["answer"])

    # LLM band: jhoothi hypothesis banane se behtar hai saaf kehna, aur uski
    # jagah wahi plan dena jo sources se seedha nikalta hai.
    dead, _, _ = _run(ALL_ROUNDS, question=QUESTION_WITH_HYPOTHESES, mood="dead")
    eq("LLM band tha to ek bhi hypothesis nahi bani (jhoothi bhi nahi)",
       len(dead["hypotheses"]), 0)
    ledger = dead["requested_ledger"]
    eq("par jo maanga gaya tha uska hisaab likha gaya", ledger["any_requested"],
       True)
    check("aur unmet list mein 3 hypotheses ka zikr hai",
          any("hypothes" in str(item.get("what", "")).lower()
              for item in ledger["unmet"]), str(ledger["unmet"])[:300])
    check("report saaf maanti hai ki maangi hui hypotheses nahi bani",
          "ek bhi poori nahi ban paayi" in dead["answer"], dead["answer"][:200])
    check("uski jagah system ka apna agla-kadam plan aaya",
          "agla-kadam plan" in dead["answer"], dead["answer"][:200])
    check("khaali dhaancha nahi chhapa",
          "Reasoning model ne ye section nahi diya" not in dead["answer"])
    for token in RAW_TOKENS:
        check(f"is haalat mein bhi raw '{token}' nahi",
              token not in _human_part(dead["answer"]))


# ── 9. structure ────────────────────────────────────────────────────────────
_AUDIT_JARGON = ("Citations jo asli source par point karti hain",
                 "API calls ka asli hisaab", "Reasoning (AI) passes ka sach")


def _order(answer: str, *headings: str) -> bool:
    """Kya ye headings isi kram mein hain (aur sab maujood hain)?"""
    spots = []
    for h in headings:
        pos = _heading_pos(answer, h)
        if pos < 0:
            return False
        spots.append(pos)
    return spots == sorted(spots)


def test_structure_human_first_audit_last():
    print("\n9. structure — insaan pehle, sources aur audit sabse aakhir")
    ok, _, _ = _run(ALL_ROUNDS)
    answer = ok["answer"]
    check("jawab seedha 'Seedha jawab' se shuru hota hai",
          answer.lstrip().startswith("## Seedha jawab"), answer[:80])
    check("kram: insaani sections → Sources → audit",
          _order(answer, "## Seedha jawab", "## Research se kya pata chala?",
                 "## Evidence kya kehta hai?", "## Final conclusion",
                 "## Sources", "## Research quality / technical audit"),
          "kram galat hai")
    human = answer[:_heading_pos(answer, "## Sources")]
    for jargon in _AUDIT_JARGON:
        check(f"audit ki bhasha upar nahi ghusi: {jargon[:28]}",
              jargon not in human)
    check("healthy run mein developer-only technical block hi nahi banta",
          "### Technical details" not in answer)

    dead, _, _ = _run(ALL_ROUNDS, mood="dead")
    check("kharaab run mein bhi wahi kram, technical block sabse aakhir",
          _order(dead["answer"], "## Seedha jawab", "## Final conclusion",
                 "## Sources", "## Research quality / technical audit",
                 "### Technical details"), "kram galat hai")
    tail = dead["answer"].split("### Technical details")[1]
    check("aur raw 429 sirf usi aakhri block mein hai",
          "ResourceExhausted" in tail
          and "ResourceExhausted" not in _human_part(dead["answer"]),
          tail[:200])


# ── 10. ₹0 + determinism ────────────────────────────────────────────────────
def test_zero_cost_and_deterministic():
    print("\n10. ₹0 — koi paid call nahi, aur do run ka jawab bilkul same")
    first, disc1, fake1 = _run(ALL_ROUNDS)
    second, disc2, fake2 = _run(ALL_ROUNDS)

    api = first["api_accounting"]
    eq("ek bhi asli HTTP API attempt nahi hua (sab stubbed)",
       int(api.get("actual_http_attempts") or 0), 0)
    check("reasoning calls budget ke andar rahe",
          int(api.get("logical_reasoning_calls") or 0)
          <= int(api.get("budget") or 0),
          f"{api.get('logical_reasoning_calls')}/{api.get('budget')}")
    eq("koi model switch/retry ki zaroorat nahi padi",
       int(api.get("model_switches") or 0), 0)
    connectors = set(first["coverage"]["connectors_searched"])
    check("saare connectors free/open-access hi hain",
          connectors <= {"arxiv", "openalex", "crossref", "zenodo", "doaj",
                         "pubmed", "europepmc", "semantic_scholar", "who_gho",
                         "data_gov_in", "worldbank", "openaire"},
          str(connectors))

    eq("dono run mein bilkul wahi search calls gayi", disc1.calls, disc2.calls)
    eq("dono run mein wahi reasoning passes", fake1.labels, fake2.labels)
    eq("status same", first["status"], second["status"])
    eq("source ids same",
       [s.get("source_id") for s in first["sources"]],
       [s.get("source_id") for s in second["sources"]])
    eq("verification status same",
       first["verification"]["status"], second["verification"]["status"])
    check("aur poora jawab shabd-ba-shabd same hai (koi randomness nahi)",
          first["answer"] == second["answer"],
          f"{len(first['answer'])} vs {len(second['answer'])} chars")


TESTS = (
    test_junk_sources_are_rejected,
    test_top_source_is_a_superconductivity_paper,
    test_read_levels_are_honest,
    test_no_raw_api_error_reaches_the_user,
    test_status_is_honest_both_ways,
    test_consensus_needs_both_sides,
    test_physics_sanity_catches_bad_numbers,
    test_three_full_hypotheses_when_evidence_is_strong,
    test_structure_human_first_audit_last,
    test_zero_cost_and_deterministic,
)


def main() -> int:
    print("=" * 74)
    print("BENCHMARK V2 — superconductivity hard question, poora offline")
    print("=" * 74)
    print(f"Sawal: {QUESTION}")
    for test in TESTS:
        try:
            test()
        except Exception as exc:                     # noqa: BLE001
            global FAILED
            FAILED += 1
            import traceback
            print(f"  [FAIL] {test.__name__} crash kar gaya — {exc!r}")
            traceback.print_exc()
    print("\n" + "=" * 74)
    print(f"BENCHMARK V2: {PASSED} passed, {FAILED} failed")
    print("=" * 74)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())



