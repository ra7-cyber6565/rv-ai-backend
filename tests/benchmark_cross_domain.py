"""
Cross-Domain Research Reliability Benchmark — 8 alag-alag field, poora OFFLINE.

Kyun: Benchmark V2 sirf superconductivity par pass hota tha. Us se ye pata
nahi chalta ki engine sach mein research karta hai ya humne (anjaane mein)
sirf ek hi domain ke liye tuning kar di hai. Isliye yahan aath bilkul alag
field ke sawal chalte hain, aur HAR field mein wahi jaal bichhaye gaye hain:
relevant + bilkul unrelated source, keyword-overlap wala dhoka, mirror copy,
sirf-snippet, sirf-abstract, poora full text, ghatiya quality, ulta (contra)
evidence, sirf-support evidence, patla evidence, retracted metadata, aur
model ka quota khatam ho jaana.

Chalao:  python3 tests/benchmark_cross_domain.py

₹0: koi network, koi API key, koi paid service. Saare source fixture hain,
Gemini ki jagah ek fake model hai jo apna hi prompt padh kar jawab banata
hai (isliye citation ID aur read-level jhooth nahi ho sakte).
"""
from __future__ import annotations

import os
import re
import sys
import time
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import domain as domain_mod                # noqa: E402
from research_engine import gemini_reasoning                    # noqa: E402
from research_engine.models import SourceRecord, SourceType     # noqa: E402
from research_engine.orchestrator import DeepResearchEngine     # noqa: E402
from research_engine.relevance import RelevanceEngine           # noqa: E402

PASSED = 0
FAILED = 0

# scorecard: domain -> axis -> [pass, fail]
SCORE: Dict[str, Dict[str, List[int]]] = {}
# domain -> ["axis: check name", ...]
FAILURES: Dict[str, List[str]] = {}

AXES = ("domain", "relevance", "evidence", "verification", "consensus",
        "hypothesis", "fallback", "presentation")

_CTX = {"domain": "-", "axis": "-"}

@contextmanager
def scope(domain_key: str, axis: str):
    """Har check ko domain + axis ke khaate mein daal do (scorecard ke liye)."""
    old = dict(_CTX)
    _CTX["domain"] = domain_key
    _CTX["axis"] = axis
    try:
        yield
    finally:
        _CTX.update(old)


def _tally(ok: bool, label: str) -> None:
    dom = SCORE.setdefault(_CTX["domain"], {a: [0, 0] for a in AXES})
    cell = dom.setdefault(_CTX["axis"], [0, 0])
    cell[0 if ok else 1] += 1
    if not ok:
        FAILURES.setdefault(_CTX["domain"], []).append(f"{_CTX['axis']}: {label}")


def check(label: str, cond: bool, extra: str = "") -> bool:
    global PASSED, FAILED
    ok = bool(cond)
    if ok:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}" + (f" -> {extra}" if extra else ""))
    _tally(ok, label)
    return ok


def eq(label: str, got, want) -> bool:
    return check(label, got == want, f"got={got!r} want={want!r}")


# ── fixture model ────────────────────────────────────────────────────────────
@dataclass
class Row:
    """Ek source fixture — tag batata hai ki ye kaunsa jaal hai."""
    tag: str
    title: str
    snippet: str
    url: str = ""
    connector: str = "openalex"
    stype: SourceType = SourceType.PAPER
    peer: bool = True
    doi: str = ""
    retracted: bool = False
    full_text: bool = False


@dataclass
class DomainCase:
    """Ek field ka poora benchmark — sawal, fixtures aur expected behaviour."""
    key: str
    label: str
    question: str
    expect_domain: str          # domain.detect() ka expected profile key
    strict: bool                # is field mein hard rejection chalni chahiye
    intents: Tuple[str, ...]    # query expansion mein inmein se kuch dikhna chahiye
    top_words: Tuple[str, ...]  # sabse upar wale source ke title mein inmein se ek
    connector: str
    junk_connector: str
    # (tag, title, snippet) — tag hi decide karta hai ki ye kaunsa jaal hai
    sources: Tuple[Tuple[str, str, str], ...]
    claim: str                  # strong claim (core_full ke text se entail hota hai)
    reported: str               # sirf source-reported baat
    mechanism: str
    against: str
    unknown: str
    conclusion: str
    numbers_ok: str
    numbers_bad: str
    hyp: Tuple[str, ...]

    def rows(self) -> List[Row]:
        return build_rows(self)


_TAG_HOST = {"core_full": "arxiv.org/abs", "contra": "www.nature.com/articles",
             "lowq": "medium.com/@notes", "support": "zenodo.org/record"}
_NO_PEER = ("lowq", "junk_web", "support")


def _slug(case_key: str, tag: str, i: int) -> str:
    """
    URL/DOI mein domain ka naam NAHI daalte.

    Kyun: pehle URL `.../energy-junk-1` tha, aur engine URL ko bhi text ki
    tarah dekhta hai — yaani ek gestational-diabetes paper sirf apne URL ke
    "energy" shabd se energy domain ka anchor pa jaata tha. Us se benchmark
    dono taraf se jhootha ho jaata: kachra bach jaata aur asli source ko muft
    ka fayda milta. Ab neutral hash.
    """
    return hashlib.md5(f"{case_key}|{tag}|{i}".encode()).hexdigest()[:10]


def build_rows(case: DomainCase) -> List[Row]:
    """
    Tag se traits — taaki har domain mein bilkul wahi jaal ban jaayein aur
    fixture likhne mein sirf asli text (title + snippet) likhna pade.
    """
    rows: List[Row] = []
    for i, (tag, title, snippet) in enumerate(case.sources, start=1):
        host = _TAG_HOST.get(tag, "openalex.org/W")
        peer = tag not in _NO_PEER
        conn = {"support": "zenodo", "lowq": "web_search",
                "junk": case.junk_connector,
                "junk_web": "web_search"}.get(tag, case.connector)
        stype = SourceType.PAPER
        if tag == "support":
            stype = SourceType.DATASET
        elif tag in ("lowq", "junk_web"):
            stype = SourceType.WEB
        slug = _slug(case.key, tag, i)
        rows.append(Row(
            tag=tag, title=title, snippet=snippet,
            url=f"https://{host}/{slug}", connector=conn,
            stype=stype, peer=peer,
            doi=(f"10.9999/{slug}" if tag not in ("lowq", "junk_web") else ""),
            retracted=(tag == "retracted"),
            full_text=(tag in ("core_full", "contra"))))
    # mirror = core_full ki hu-ba-hu copy, doosre host se, wahi DOI (dedup ka kaam)
    base = next((r for r in rows if r.tag == "core_full"), None)
    if base is not None:
        rows.append(Row(tag="mirror", title=base.title, snippet=base.snippet,
                        url=("https://www.researchgate.net/publication/"
                             + _slug(case.key, "mirror", 0)),
                        connector="semantic_scholar", stype=base.stype,
                        peer=True, doi=base.doi))
    return rows


# ── 1. Medicine / drug research ──────────────────────────────────────────────
MEDICINE = DomainCase(
    key="medicine", label="Medicine / drug research",
    question=("Type 2 diabetes ke patients mein metformin ke saath GLP-1 "
              "receptor agonist dene se cardiovascular mortality kam hoti hai "
              "kya, aur randomised clinical trials mein iska dose kitna raha?"),
    expect_domain="medicine_health", strict=True,
    intents=("adverse", "meta-analysis", "mechanism"),
    top_words=("semaglutide", "glp-1", "cardiovascular"),
    connector="pubmed", junk_connector="arxiv",
    sources=(
        ("core_full",
         "Semaglutide added to metformin and cardiovascular mortality in type 2 diabetes: a randomised controlled trial",
         "In a randomised controlled trial of 3297 adults with type 2 diabetes already taking metformin, adding weekly semaglutide reduced cardiovascular mortality from 6.2% to 4.1% over 104 weeks. The prespecified intention-to-treat analysis reported a cumulative subcutaneous dose of 0.5 g, and gastrointestinal adverse events were the most common reason for withdrawal."),
        ("core_abs",
         "Cardiovascular outcomes of GLP-1 receptor agonists in type 2 diabetes: a meta-analysis of 12 trials",
         "This meta-analysis pooled 12 randomised trials covering 94,000 patients with type 2 diabetes. GLP-1 receptor agonists were associated with a 12% relative reduction in cardiovascular death compared with placebo when added to metformin. Heterogeneity was moderate and the effect was smaller in trials with follow-up shorter than 18 months."),
        ("core_snip",
         "Registry follow-up of metformin plus GLP-1 agonist therapy in 8,400 patients",
         "Registry follow-up of 8,400 patients on metformin plus a GLP-1 agonist reported lower cardiovascular death, but the registry was not randomised."),
        ("meta",
         "Glycaemic control and cardiovascular risk in type 2 diabetes: national guideline chapter",
         ""),
        ("contra",
         "No reduction in cardiovascular mortality with a GLP-1 agonist added to metformin: the CV-NEUTRAL trial",
         "In this randomised controlled trial of 4,120 adults with type 2 diabetes, adding a GLP-1 receptor agonist to metformin did not reduce cardiovascular mortality (hazard ratio 0.98, 95% CI 0.84-1.14) over three years. The authors report that earlier positive trials enrolled patients at lower baseline risk and conclude that the mortality benefit was not replicated."),
        ("support",
         "Trial-level dataset: GLP-1 agonist cardiovascular outcome trials 2015-2024",
         "Summary tables for cardiovascular outcome trials of GLP-1 receptor agonists in type 2 diabetes, including mortality counts, metformin background therapy and reported adverse events."),
        ("retracted",
         "Retracted: dramatic cardiovascular mortality benefit of high-dose GLP-1 agonist therapy",
         "This paper reported a 60% reduction in cardiovascular mortality with high-dose GLP-1 agonist therapy in type 2 diabetes. It was retracted after the institution could not verify the patient records or the trial registration date."),
        ("overlap",
         "Metformin hydrochloride as a green corrosion inhibitor for mild steel in acidic media",
         "Metformin hydrochloride was evaluated as a corrosion inhibitor for mild steel in 1 M HCl. Weight-loss and electrochemical impedance measurements show 92% inhibition efficiency at 500 ppm."),
        ("junk",
         "Superconductivity at 250 K in lanthanum hydride under high pressures",
         "LaH10 shows a superconducting critical temperature of 250 K at 170 GPa, measured by four-probe resistance in a diamond anvil cell."),
        ("junk_web",
         "Top 10 celebrity juice cleanses that changed fitness in 2024",
         "A listicle about celebrity juice cleanses, gym routines and detox teas. No clinical data, no measurements."),
        ("lowq",
         "My experience: I stopped metformin and started a weekly GLP-1 shot",
         "A personal blog post describing one person's home glucose readings after switching medicines. No control group and no laboratory confirmation."),
    ),
    claim=("Randomised controlled trial mein metformin ke saath semaglutide ne "
           "cardiovascular mortality 6.2% se 4.1% tak ghatai"),
    reported=("Meta-analysis 12 trials mein cardiovascular death mein 12% "
              "relative reduction bataata hai"),
    mechanism=("GLP-1 receptor agonist insulin secretion badhata hai aur weight "
               "ghatata hai, isse dil par load kam hota hai"),
    against=("CV-NEUTRAL trial mein wahi combination mortality kam nahi kar paaya "
             "(hazard ratio 0.98)"),
    unknown=("18 mahine se lambe follow-up par effect kitna tikta hai, ye saaf "
             "nahi hai"),
    conclusion=("Evidence mixed hai: bade trials fayda dikhate hain, ek bada "
                "trial nahi — isliye guideline-level dava abhi nahi banta"),
    numbers_ok="Cumulative dose 0.5 g (500 mg) tha [S1], jo 0.2 g se zyada hai.",
    numbers_bad="Cumulative dose 0.5 g (5 mg) tha [S1], jo 2 g se zyada hai.",
    hyp=("Mortality ka fayda sirf high baseline cardiovascular risk wale "
         "patients mein dikhta hai",
         "Weight loss hi asli mechanism hai, glucose control nahi",
         "Trial ke chhote follow-up ne fayde ko bada dikha diya"),
)

# ── 2. Materials / superconductivity ─────────────────────────────────────────
MATERIALS = DomainCase(
    key="materials", label="Materials / superconductivity",
    question=("Ambient pressure par kis material ka superconducting critical "
              "temperature sabse zyada hai, aur hydride vs cuprate mein asli "
              "farak kya hai?"),
    expect_domain="superconductivity", strict=True,
    intents=("replication", "pairing"),
    top_words=("hydride", "cuprate", "superconduct"),
    connector="arxiv", junk_connector="pubmed",
    sources=(
        ("core_full",
         "Superconductivity at 250 K in lanthanum hydride under high pressures",
         "LaH10 shows a superconducting critical temperature of 250 K at 170 GPa. Four-probe resistance, the isotope effect and the magnetic field dependence are reported for the hydride sample inside a diamond anvil cell, and the transition disappears when the pressure is released."),
        ("core_abs",
         "Ambient pressure critical temperature record in mercury based cuprates",
         "Mercury based cuprates remain the highest confirmed ambient pressure superconductors, with a critical temperature near 133 K that rises to about 164 K under 30 GPa. This review compares hole doping, apical oxygen distance and the pairing symmetry of the cuprate family with the hydride family, and notes that no cuprate has exceeded 140 K at ambient pressure."),
        ("core_snip",
         "Nickelate thin films: superconductivity below 20 K",
         "Infinite-layer nickelate thin films superconduct below about 20 K, far under the cuprate record, but offer a cleaner test of the pairing mechanism."),
        ("meta",
         "Superconductivity: a graduate textbook chapter on critical temperature",
         ""),
        ("contra",
         "Failed replication of ambient pressure room temperature superconductivity in nitrogen doped lutetium hydride",
         "Three independent groups did not reproduce the reported ambient pressure superconductivity of nitrogen doped lutetium hydride. Resistance measurements on nine samples show no transition above 10 K, and the authors conclude that the original resistance drop was an artefact of the background subtraction rather than a real superconducting transition."),
        ("support",
         "Dataset: measured critical temperatures of 28,000 inorganic compounds",
         "A curated dataset of measured superconducting critical temperatures with pressure, structure and doping fields for inorganic compounds."),
        ("retracted",
         "Retracted: room-temperature superconductivity in a carbonaceous sulfur hydride",
         "A critical temperature of 288 K was reported in carbonaceous sulfur hydride at 267 GPa. The paper was retracted after questions about the background subtraction of the raw magnetic susceptibility data."),
        ("overlap",
         "Critical temperature of protein folding transitions in thermophilic enzymes",
         "The critical temperature of the folding transition was measured by circular dichroism for eleven thermophilic enzymes, giving midpoints between 341 K and 372 K."),
        ("junk",
         "Trends in maternal mortality ratio across 185 countries",
         "Maternal mortality ratios were estimated for 185 countries using civil registration and survey data."),
        ("junk_web",
         "Why this altcoin could 10x after the next halving",
         "A crypto trading blog post with price targets and no measurements."),
        ("lowq",
         "I think room temperature superconductors are already secret tech",
         "A blog post arguing from YouTube videos that a working ambient superconductor is being hidden. No data."),
    ),
    claim=("LaH10 mein 250 K ka superconducting critical temperature 170 GPa "
           "par report hua"),
    reported=("Ambient pressure par sabse ooncha confirmed critical temperature "
              "mercury cuprate ka ~133 K hai"),
    mechanism=("Hydrogen ke halke atom lattice ko tez hilate hain, isse electron "
               "jodi banana aasan hota hai — par unhe rokne ke liye bahut "
               "pressure chahiye"),
    against=("Lutetium hydride ka ambient claim teen swatantra group mein "
             "replicate nahi hua"),
    unknown=("Ambient pressure par 200 K se ooncha koi confirmed material nahi "
             "mila"),
    conclusion=("Aaj ke hisaab se ambient room-temperature superconductivity "
                "confirm nahi hai; 250-288 K wale claims pressure maangte hain "
                "ya retract ho chuke hain"),
    numbers_ok="Tc 250 K (-23.15 °C) [S1] hai, jo 77 K se zyada hai.",
    numbers_bad="Tc 250 K (23 °C) [S1] hai, jo 300 K se zyada hai.",
    hyp=("Ambient pressure par Tc ki chhat lattice ki stiffness tay karti hai",
         "Lutetium hydride ka claim background subtraction ka artefact tha",
         "Cuprate aur hydride mein pairing mechanism alag hai"),
)

# ── 3. Energy / climate ──────────────────────────────────────────────────────
ENERGY = DomainCase(
    key="energy", label="Energy / climate",
    question=("Solar power ki intermittency ke liye grid-scale battery storage "
              "aur pumped hydro mein se kaun zyada carbon emissions bachata "
              "hai, aur kitna?"),
    expect_domain="energy_climate", strict=True,
    intents=("lifecycle", "capacity factor"),
    top_words=("storage", "battery", "hydro", "grid"),
    connector="openalex", junk_connector="pubmed",
    sources=(
        ("core_full",
         "Life-cycle greenhouse gas emissions of grid-scale lithium battery storage versus pumped hydro",
         "A life-cycle assessment of grid-scale storage paired with solar generation finds 33 kg CO2-equivalent per MWh delivered for lithium iron phosphate batteries and 12 kg CO2-equivalent per MWh for pumped hydro over a 40-year plant life. The battery result is dominated by cell manufacturing, and the pumped hydro result by reservoir construction and land change."),
        ("core_abs",
         "Curtailment, round-trip efficiency and emissions savings of storage on a solar-heavy grid",
         "This modelling study of a solar-heavy regional grid compares four storage portfolios. Storage reduced curtailment from 19% to 6% of annual solar generation and cut grid emissions by 21%, but the emissions benefit fell to 9% when the charging mix included coal at night. Round-trip efficiency of 86% for batteries and 78% for pumped hydro was assumed."),
        ("core_snip",
         "Pumped hydro capacity factor in a solar-dominated dispatch model",
         "Dispatch simulation gives pumped hydro a 24% capacity factor when paired with solar, against 31% for batteries in the same year."),
        ("meta",
         "National electricity storage capacity statistics: annual chapter",
         ""),
        ("contra",
         "Battery storage did not reduce system emissions in a coal-heavy grid: measured dispatch evidence",
         "Using measured half-hourly dispatch data for three years, this study finds that grid-scale battery storage did not reduce system carbon emissions and in one year increased them by 4%, because the batteries charged from coal generation at night and discharged during gas-fired peaks. The emission savings reported by earlier modelling studies were not replicated in the measured record."),
        ("support",
         "Dataset: hourly emissions factors and storage dispatch for 14 grids",
         "Hourly marginal emissions factors, storage charge and discharge volumes and curtailment records for fourteen regional grids."),
        ("retracted",
         "Retracted: 90% emissions reduction from residential battery storage",
         "The paper claimed a 90% reduction in household emissions from battery storage. It was retracted after the authors confirmed the charging emissions factor had been entered as zero."),
        ("overlap",
         "Storage and retrieval of episodic memory during sleep consolidation",
         "Hippocampal replay during slow-wave sleep supports the storage and later retrieval of episodic memories in rodents."),
        ("junk",
         "Prevalence of gestational diabetes in a tertiary care hospital",
         "Screening of 1,200 pregnant women found gestational diabetes in 14.8% of cases using the oral glucose tolerance test."),
        ("junk_web",
         "10 home decor trends for summer balconies",
         "A lifestyle blog listicle about balcony furniture and planters."),
        ("lowq",
         "Why batteries are always greener than dams — my take",
         "An opinion blog post comparing batteries and dams with no lifecycle data or citations."),
    ),
    claim=("Life-cycle assessment mein battery storage 33 kg CO2e per MWh aur "
           "pumped hydro 12 kg CO2e per MWh deta hai"),
    reported=("Storage ne curtailment 19% se 6% tak ghatai aur grid emissions "
              "21% kam kiye"),
    mechanism=("Storage solar ki bachi hui bijli raat ke liye rakh leta hai, "
               "isliye peak par gas/coal plant kam chalte hain"),
    against=("Coal-heavy grid ke measured dispatch data mein battery ne "
             "emissions kam nahi kiye, ek saal 4% badha diye"),
    unknown=("Charging mix badalne par net fayda kitna bachta hai, ye grid par "
             "nirbhar hai aur saaf nahi"),
    conclusion=("Fayda technology se zyada grid ke charging mix par tikta hai — "
                "ek hi jawab sab grid ke liye nahi banta"),
    numbers_ok="Ek cycle 1 MJ (1000 kJ) [S1] hai, jo 0.5 MJ se zyada hai.",
    numbers_bad="Ek cycle 1 MJ (10 kJ) [S1] hai, jo 5 MJ se zyada hai.",
    hyp=("Emissions ka fayda charging mix se tay hota hai, storage technology se nahi",
         "Pumped hydro ka fayda lambi umr se aata hai, efficiency se nahi",
         "Curtailment ghatane se hone wala fayda solar share badhne par ghatta hai"),
)

# ── 4. Mechanical / electrical engineering ───────────────────────────────────
ENGINEERING = DomainCase(
    key="engineering", label="Mechanical / electrical engineering",
    question=("Induction motor ki bearing failure ka sabse aam kaaran kya hai, "
              "aur vibration monitoring se kitna pehle pata chal jaata hai?"),
    expect_domain="engineering", strict=True,
    intents=("failure mode", "standard"),
    top_words=("bearing", "motor", "vibration"),
    connector="openalex", junk_connector="pubmed",
    sources=(
        ("core_full",
         "Bearing fault detection in induction motors using vibration envelope analysis",
         "Envelope analysis of vibration signals detected outer-race bearing defects in three-phase induction motors an average of 41 days before failure across 62 machines. Electrical discharge through the bearing from inverter common-mode voltage was the dominant root cause in 38 of 62 cases, followed by lubricant contamination, and the detection lead time fell to 12 days for inner-race defects."),
        ("core_abs",
         "Root causes of premature bearing failure in inverter-fed machines: a survey of maintenance records",
         "This survey of 4,100 maintenance records from twelve plants classifies premature bearing failures in inverter-fed induction motors. Electrical erosion accounted for 44% of failures, misalignment for 21%, contamination for 18% and inadequate lubrication for 12%. Shaft grounding rings reduced the electrical erosion share to 9% where fitted, and vibration monitoring was in place on 61% of the machines."),
        ("core_snip",
         "Comparison of vibration and current signature monitoring for motor bearings",
         "On 18 test rigs, vibration monitoring detected bearing wear about three weeks earlier than motor current signature analysis."),
        ("meta",
         "Rotating machinery condition monitoring: ISO standard summary chapter",
         ""),
        ("contra",
         "Vibration monitoring gave no useful warning of bearing failure in variable-load conveyor drives",
         "In a two-year trial on 40 variable-load conveyor drive motors, vibration monitoring did not give a useful early warning of bearing failure: the alarm threshold was crossed after the fault had already progressed, and 27 of 40 failures were missed entirely because load variation masked the defect frequencies. The reported lead times from constant-load studies were not reproduced."),
        ("support",
         "Dataset: accelerometer traces for 62 induction motor bearing run-to-failure tests",
         "Raw accelerometer traces, load records and teardown photographs for run-to-failure tests of induction motor bearings."),
        ("retracted",
         "Retracted: 99.8% accurate bearing failure prediction six months in advance",
         "The paper claimed 99.8% accuracy six months before failure. It was retracted after reviewers found the test set overlapped the training set."),
        ("overlap",
         "Bearing witness: oral history interviews with retired railway workers",
         "Twenty oral history interviews with retired railway workers, bearing witness to working conditions in the 1960s."),
        ("junk",
         "Efficacy of oral rehydration salts in paediatric diarrhoea",
         "A randomised trial of oral rehydration salts in 480 children reported reduced hospitalisation."),
        ("junk_web",
         "Best 5 gaming chairs under 10,000 rupees",
         "A shopping blog post ranking gaming chairs by comfort and price."),
        ("lowq",
         "My motor bearing died — here is what I think happened",
         "A forum post guessing at the cause of one failed bearing with no measurements or teardown."),
    ),
    claim=("Vibration envelope analysis ne bearing defect ausatan 41 din pehle "
           "pakda, aur 62 mein se 38 case mein electrical discharge asli kaaran tha"),
    reported=("Maintenance record survey mein electrical erosion 44% failures "
              "ka kaaran nikla"),
    mechanism=("Inverter ki common-mode voltage bearing ke through discharge "
               "karti hai, isse race par pitting banti hai aur wahi vibration "
               "signature deti hai"),
    against=("Variable-load conveyor drives par vibration monitoring ne 40 mein "
             "27 failure miss kar diye"),
    unknown=("Variable load par lead time kitna bachta hai — iska koi bharosemand "
             "number nahi mila"),
    conclusion=("Constant-load machines par vibration monitoring hafton ka warning "
                "deta hai; variable load par yahi dava tikta nahi"),
    numbers_ok="Shaft ka span 0.5 m (500 mm) [S1] hai, jo 0.2 m se zyada hai.",
    numbers_bad="Shaft ka span 0.5 m (5 mm) [S1] hai, jo 2 m se zyada hai.",
    hyp=("Bearing failure ka asli driver inverter ki common-mode voltage hai",
         "Vibration monitoring ka lead time load ki variability se tay hota hai",
         "Shaft grounding ring lagane se electrical erosion ka share girta hai"),
)

# ── 5. AI / software / computer science ──────────────────────────────────────
CS_AI = DomainCase(
    key="cs_ai", label="AI / software / computer science",
    question=("Transformer language model ki inference latency kam karne ke liye "
              "quantization karne se accuracy par kitna asar padta hai?"),
    expect_domain="cs_ml", strict=True,
    intents=("benchmark", "ablation"),
    top_words=("quantization", "quantized", "inference", "transformer"),
    connector="arxiv", junk_connector="openalex",
    sources=(
        ("core_full",
         "Post-training 4-bit quantization of transformer language models: latency and accuracy trade-off",
         "Post-training 4-bit weight quantization of a 7B parameter transformer reduced median inference latency from 0.5 s to 0.18 s per request on a single GPU while accuracy on the held-out benchmark fell by 1.9 points. An ablation shows that keeping the attention output projection in 8-bit recovers 1.2 of those points at a 6% latency cost."),
        ("core_abs",
         "A benchmark study of 8-bit and 4-bit quantization across six transformer model families",
         "We benchmark eight post-training quantization methods on six transformer families between 1B and 70B parameters. At 8-bit, accuracy loss stays under 0.5 points for every family, while at 4-bit the loss ranges from 0.8 to 5.6 points and grows sharply for models trained with fewer tokens per parameter. Latency gains at 4-bit range from 1.9x to 2.7x on the same hardware."),
        ("core_snip",
         "Quantized attention kernels: throughput measurements on commodity GPUs",
         "Measured throughput for quantized attention kernels improves 2.1x at batch size 1, with no change in output tokens for greedy decoding."),
        ("meta",
         "Efficient inference for large language models: workshop proceedings index",
         ""),
        ("contra",
         "4-bit quantization did not preserve accuracy on reasoning benchmarks: a replication study",
         "Repeating four published post-training 4-bit quantization recipes, this study finds that accuracy was not preserved on multi-step reasoning benchmarks: the drop was 7.4 points on average, against the 1 to 2 points reported by the original papers, and two recipes failed to reproduce any latency gain at batch size 32. The authors attribute the gap to evaluation on short-answer tasks only."),
        ("support",
         "Dataset: latency and accuracy traces for 240 quantized model checkpoints",
         "Per-checkpoint latency, memory and benchmark accuracy traces for 240 quantized transformer checkpoints with the evaluation harness configuration."),
        ("retracted",
         "Retracted: lossless 2-bit quantization of large language models",
         "The paper claimed lossless 2-bit quantization. It was retracted after the authors found the evaluation script had loaded the unquantized weights."),
        ("overlap",
         "A stochastic volatility model for option pricing with latent market factors",
         "We estimate a stochastic volatility model for index options using a particle filter, and report improved pricing accuracy for short-dated contracts."),
        ("junk",
         "Soil nitrogen dynamics under conservation tillage in semi-arid plots",
         "Soil nitrogen was measured over five seasons under conservation tillage in semi-arid experimental plots."),
        ("junk_web",
         "This one prompt makes any AI 10x smarter, trust me",
         "A viral blog post with a prompt template and screenshots, no measurements."),
        ("lowq",
         "I quantized my model and it felt faster",
         "A short blog post reporting a subjective impression of speed after quantization, with no timings."),
    ),
    claim=("4-bit quantization ne median inference latency 0.5 s se 0.18 s tak "
           "girayi aur accuracy 1.9 point kam hui"),
    reported=("8-bit par accuracy loss har family mein 0.5 point se kam raha"),
    mechanism=("Kam bits mein weight rakhne se memory bandwidth bachti hai, aur "
               "latency ka bada hissa wahi bandwidth hai"),
    against=("Replication study mein reasoning benchmarks par 4-bit ka drop 7.4 "
             "point tha, 1-2 point nahi"),
    unknown=("Lambe reasoning task par 4-bit ka asar kitna hai, ye abhi settled "
             "nahi hai"),
    conclusion=("8-bit lagbhag muft hai; 4-bit ka faisla task par nirbhar karta "
                "hai — short-answer benchmark par sasta, reasoning par mehnga"),
    numbers_ok="Latency 0.5 s (500 ms) [S1] thi, jo 0.2 s se zyada hai.",
    numbers_bad="Latency 0.5 s (5 ms) [S1] thi, jo 2 s se zyada hai.",
    hyp=("4-bit ka accuracy loss training tokens per parameter se tay hota hai",
         "Reasoning task par quantization ka nuksaan short-answer se zyada hai",
         "Attention output projection ko 8-bit rakhna sabse sasta bachav hai"),
)

# ── 6. Archaeology / history ─────────────────────────────────────────────────
ARCHAEOLOGY = DomainCase(
    key="archaeology", label="Archaeology / history",
    question=("Indus valley civilisation ke shehron ka patan monsoon ke badlav "
              "se hua ya vyapar toot jaane se, aur purane sabooton se timeline "
              "kya nikalti hai?"),
    expect_domain="archaeology_history", strict=True,
    intents=("radiocarbon", "excavation"),
    top_words=("indus", "harappa", "monsoon", "civilisation"),
    connector="openalex", junk_connector="arxiv",
    sources=(
        ("core_full",
         "Weakening monsoon and the deurbanisation of Indus valley settlements: a radiocarbon chronology",
         "A radiocarbon chronology from 41 excavated Indus valley settlement layers places the start of deurbanisation between 2100 and 1900 BCE, overlapping a documented weakening of the summer monsoon recorded in speleothem oxygen isotopes. Settlement counts in the Ghaggar-Hakra plain fall by 71% within this window while eastern settlements in the Ganges-Yamuna doab increase."),
        ("core_abs",
         "Trade contraction with Mesopotamia and Harappan urban decline: evidence from seals and weights",
         "This synthesis reviews Harappan seals, standardised weights and carnelian bead finds in Mesopotamian contexts to date the contraction of long-distance trade. Datable finds drop sharply after about 1900 BCE, roughly a century after the earliest deurbanisation layers, which the authors read as trade contraction following urban decline rather than causing it. Stratigraphic uncertainty of one to two centuries is acknowledged."),
        ("core_snip",
         "Speleothem oxygen isotope record of the Holocene Indian summer monsoon",
         "A speleothem oxygen isotope record shows a multi-century weakening of the Indian summer monsoon beginning around 2200 BCE."),
        ("meta",
         "Archaeological survey of India: annual excavation report index",
         ""),
        ("contra",
         "Monsoon weakening did not drive Indus deurbanisation: settlement continuity at eastern sites",
         "Excavation of nine eastern Indus sites shows settlement continuity and even growth through the interval of monsoon weakening, so climate did not drive deurbanisation everywhere. Crop assemblages shift from wheat and barley to drought-tolerant millets without any break in occupation, and the authors argue the earlier climate-collapse chronology was not reproduced once local stratigraphy was dated directly."),
        ("support",
         "Dataset: radiocarbon dates from 41 Indus valley excavation layers",
         "Calibrated radiocarbon dates, laboratory codes, stratigraphic context and settlement size estimates for 41 excavated Indus valley layers."),
        ("retracted",
         "Retracted: a single catastrophic flood ended the Harappan civilisation in 1750 BCE",
         "The paper claimed a single catastrophic flood ended the Harappan civilisation. It was retracted after the sediment cores were found to have been mislabelled between two sites."),
        ("overlap",
         "Monsoon dynamics in a 1.5 degree warmer climate: CMIP6 projections",
         "CMIP6 projections show a 6% increase in Indian summer monsoon rainfall under 1.5 degrees of warming, with higher interannual variability."),
        ("junk",
         "Quantization of transformer language models for faster inference",
         "Post-training quantization reduced inference latency of a transformer language model with a small accuracy loss."),
        ("junk_web",
         "Ancient aliens built the pyramids — the hidden evidence",
         "A blog post claiming extraterrestrial construction, based on documentary screenshots."),
        ("lowq",
         "My theory about why the Indus cities were abandoned",
         "A personal blog post speculating about abandonment with no dated evidence or excavation data."),
    ),
    claim=("41 excavated layers ki radiocarbon chronology deurbanisation ki "
           "shuruaat 2100-1900 BCE ke beech rakhti hai"),
    reported=("Mesopotamia ke saath vyapar ke datable finds 1900 BCE ke baad "
              "tezi se girte hain"),
    mechanism=("Monsoon kamzor hone se Ghaggar-Hakra plain ki kheti girti hai, "
               "aur aabadi poorab ki taraf shift hoti hai"),
    against=("Poorabi sites par monsoon weakening ke dauran bhi bastiyan chalti "
             "rahin, isliye climate hi ek wajah nahi thi"),
    unknown=("Vyapar toot jaana wajah tha ya nateeja — chronology ka farak sirf "
             "ek sadi ka hai, aur wo uncertainty ke andar hai"),
    conclusion=("Do wajahon ka kram overlap karta hai; ek hi kaaran chunne layak "
                "resolution abhi ke dates mein nahi hai"),
    numbers_ok="Layer ka gap 730 days (2 years) [S1] hai, jo 1 year se zyada hai.",
    numbers_bad="Layer ka gap 730 days (20 years) [S1] hai, jo 5 years se zyada hai.",
    hyp=("Deurbanisation pehle shuru hui aur vyapar ka patan uska nateeja tha",
         "Poorabi sites ki continuity millet par shift hone se aayi",
         "Ghaggar-Hakra ka patan nadi ke raaste badalne se juda hai, sirf barish se nahi"),
)

# ── 7. Economics / finance ───────────────────────────────────────────────────
ECONOMICS = DomainCase(
    key="economics", label="Economics / finance",
    question=("Minimum wage badhane se chhote shehron mein employment par kya "
              "asar padta hai, aur India ke data mein kya dikha?"),
    expect_domain="economics", strict=True,
    intents=("elasticity", "panel"),
    top_words=("minimum wage", "employment", "labour"),
    connector="openalex", junk_connector="arxiv",
    sources=(
        ("core_full",
         "Minimum wage increases and employment in small urban labour markets: a difference-in-differences study",
         "Using a difference-in-differences design across 214 small urban labour markets, a 10% minimum wage increase is associated with a 0.9% fall in formal employment within two years, concentrated in firms with fewer than ten workers. The implied own-wage employment elasticity is -0.09, and informal employment rises by 1.4% over the same window."),
        ("core_abs",
         "Minimum wage compliance and employment effects in Indian districts: panel evidence 2005-2019",
         "This panel study of 588 Indian districts exploits staggered state-level minimum wage revisions. Formal employment falls by 0.6% for a 10% statutory increase where compliance is high, and shows no measurable change where enforcement inspections are rare. Informal wage growth tracks the statutory floor only in districts with active inspection, which the authors read as partial pass-through rather than full compliance."),
        ("core_snip",
         "Firm size and the employment response to wage floors",
         "Employment responses to wage floors are three times larger in firms below ten workers than in firms above fifty, in the same district-year sample."),
        ("meta",
         "Periodic labour force survey: methodology note index",
         ""),
        ("contra",
         "No detectable employment loss after minimum wage increases: evidence from bordering districts",
         "Comparing bordering districts on either side of state minimum wage changes, this study finds no detectable employment loss after increases: the point estimate is 0.05% with a confidence interval spanning zero, and the negative elasticities reported by earlier national panel studies were not reproduced once local demand shocks were absorbed by the border design."),
        ("support",
         "Dataset: state-level statutory minimum wages and district employment counts",
         "Statutory minimum wage schedules by state and year with district-level formal and informal employment counts and inspection records."),
        ("retracted",
         "Retracted: minimum wage increases destroyed 4 million jobs in two years",
         "The paper claimed four million job losses. It was retracted after the employment series was found to include a change in survey definition treated as a real decline."),
        ("overlap",
         "Wage of the machine: reward shaping for reinforcement learning agents",
         "We study reward shaping for reinforcement learning agents and show that a shaped wage signal speeds up convergence in gridworld tasks."),
        ("junk",
         "Bearing fault detection in induction motors using vibration analysis",
         "Vibration envelope analysis detected bearing defects in induction motors weeks before failure."),
        ("junk_web",
         "5 side hustles that will make you rich in 2025",
         "A money blog listicle about side hustles with no data."),
        ("lowq",
         "Minimum wage is obviously bad for jobs — common sense",
         "An opinion blog post arguing from first principles with no data or citations."),
    ),
    claim=("214 small urban labour markets ke difference-in-differences mein 10% "
           "minimum wage increase par formal employment 0.9% gira"),
    reported=("India ke 588 district panel mein high-compliance jagah employment "
              "0.6% gira, aur kam enforcement wali jagah koi badlav nahi"),
    mechanism=("Chhoti firms ke paas price badhane ki gunjaish kam hoti hai, "
               "isliye wo hours ya headcount ghatati hain"),
    against=("Bordering districts ke design mein koi detectable employment loss "
             "nahi mila (estimate 0.05%, confidence interval zero ke aas-paas)"),
    unknown=("Informal sector mein shift kitna sthayi hai — is par bharosemand "
             "lamba data nahi mila"),
    conclusion=("Asar chhota aur design par nirbhar hai; 'jobs khatam ho jaate "
                "hain' jaisa dava is evidence se nahi banta"),
    numbers_ok="Employment 2% se 1% tak gira [S1], yaani 1% badlav 2% se kam hai.",
    numbers_bad="Employment 2% se 1% tak gira [S1], yaani 1% badlav 5% se zyada hai.",
    hyp=("Employment ka asar enforcement ki taakat se tay hota hai, statutory floor se nahi",
         "Chhoti firms ka adjustment hours mein hota hai, headcount mein nahi",
         "Informal employment ka badhna formal loss ka aadha hissa absorb karta hai"),
)

# ── 8. Biology / agriculture / environment ───────────────────────────────────
BIOLOGY = DomainCase(
    key="biology", label="Biology / agriculture / environment",
    question=("Bt cotton ke lagatar use se pink bollworm mein resistance kitni "
              "tezi se badhi, aur crop yield par iska kya asar hua?"),
    expect_domain="biology_genetics", strict=True,
    intents=("field trial", "monitoring"),
    top_words=("bollworm", "cotton", "resistance"),
    connector="openalex", junk_connector="arxiv",
    sources=(
        ("core_full",
         "Field-evolved resistance of pink bollworm to Bt cotton: eight seasons of monitoring",
         "Monitoring of pink bollworm populations across 132 field sites over eight seasons shows survival on Cry1Ac cotton rising from 4% to 61%, with resistance allele frequency increasing fastest where refuge planting fell below 5% of area. Yield in the same districts declined from 2 tonne per hectare to 1.4 tonne per hectare over the period, and insecticide sprays per season doubled."),
        ("core_abs",
         "Resistance management and yield outcomes in Bt cotton systems: a multi-district field trial synthesis",
         "This synthesis of field trials across 26 districts compares refuge compliance, pest survival and yield. Districts maintaining a non-Bt refuge above 20% of area held pink bollworm survival under 10% through six seasons, while non-compliant districts crossed 50% survival by season five. Yield differences between compliant and non-compliant districts reached 0.5 tonne per hectare, and the authors note that sowing date also shifted the pest pressure."),
        ("core_snip",
         "Cry1Ac binding site mutation in pink bollworm populations",
         "A cadherin binding site mutation associated with Cry1Ac resistance was detected in 38% of sampled pink bollworm larvae."),
        ("meta",
         "Cotton crop statistics: state-wise area and production index",
         ""),
        ("contra",
         "Yield did not decline with rising bollworm resistance where irrigation improved",
         "In these district-level field records, yield did not decline with rising pink bollworm resistance: irrigation expansion and hybrid seed adoption raised yield by 0.3 tonne per hectare even as survival on Cry1Ac cotton passed 50%. The strong resistance-yield link reported by monitoring studies was not reproduced once irrigation was controlled for."),
        ("support",
         "Dataset: pink bollworm survival assays and refuge compliance by district",
         "Bioassay survival counts, resistance allele frequencies, refuge area shares and yield records by district and season."),
        ("retracted",
         "Retracted: Bt cotton caused a 90% collapse in pollinator populations",
         "The paper claimed a 90% pollinator collapse from Bt cotton. It was retracted after the control plots were found to have been sprayed with a broad-spectrum insecticide."),
        ("overlap",
         "Resistance and reactance of thin-film resistors under thermal cycling",
         "Sheet resistance of thin-film resistors was measured over 2,000 thermal cycles, showing a 3% drift attributed to grain boundary diffusion."),
        ("junk",
         "Minimum wage increases and employment in small urban labour markets",
         "A difference-in-differences study of minimum wage increases and formal employment in small urban labour markets."),
        ("junk_web",
         "7 houseplants that purify your air overnight",
         "A gardening blog listicle about houseplants with no measurements."),
        ("lowq",
         "Bt cotton failed in my field, so it fails everywhere",
         "A single-farm blog post generalising from one season with no bioassay or yield records."),
    ),
    claim=("132 field sites ke aath season ke monitoring mein Cry1Ac cotton par "
           "pink bollworm ka survival 4% se 61% tak badha"),
    reported=("20% se zyada refuge rakhne wale district mein survival chhe season "
              "tak 10% se neeche raha"),
    mechanism=("Refuge kam hone par resistant larvae ko susceptible partner nahi "
               "milta, isliye resistance allele tezi se failta hai"),
    against=("Jahan irrigation badhi, wahan resistance badhne ke baad bhi yield "
             "0.3 tonne per hectare badhi"),
    unknown=("Resistance aur yield ka rishta irrigation/hybrid ke bina alag se "
             "kitna hai, ye saaf nahi"),
    conclusion=("Resistance ka badhna field data mein saaf hai; yield par asar "
                "irrigation jaise doosre factor se mix ho jaata hai"),
    numbers_ok="Yield 2 tonne (2000 kg) [S1] thi, jo 1 tonne se zyada hai.",
    numbers_bad="Yield 2 tonne (20 kg) [S1] thi, jo 5 tonne se zyada hai.",
    hyp=("Resistance ki raftaar refuge compliance se tay hoti hai",
         "Yield ka girna resistance aur irrigation dono ka mila-jula nateeja hai",
         "Cadherin mutation ki frequency spray ke dabaav se badhti hai"),
)

CASES: Tuple[DomainCase, ...] = (MEDICINE, MATERIALS, ENERGY, ENGINEERING,
                                 CS_AI, ARCHAEOLOGY, ECONOMICS, BIOLOGY)

# ── network ki jagah stubs (₹0) ──────────────────────────────────────────────
def _records(rows: List[Row]) -> List[SourceRecord]:
    """Har call par taaza objects — pipeline inhe mutate karta hai."""
    return [SourceRecord(
        title=r.title, url=r.url, snippet=r.snippet, connector=r.connector,
        source_type=r.stype, peer_reviewed=r.peer, doi=r.doi, year=2023,
        retracted=r.retracted, full_text_available=bool(r.doi)) for r in rows]


class _FakeVectors:
    last_error = ""

    def retrieve(self, question, project_id, n_results=4):
        return {"context": "", "sources": []}


class _Discovery:
    def __init__(self, per_round: Dict[int, List[Row]], connectors: List[str]):
        self.per_round = per_round
        self.connectors = connectors
        self.calls: List[Tuple[int, List[str]]] = []

    def __call__(self, **kwargs):
        round_no = int(kwargs.get("round_no") or 1)
        self.calls.append((round_no, list(kwargs.get("queries") or [])))
        records = _records(self.per_round.get(round_no, []))
        return {
            "records": records,
            "log": [{"connector": self.connectors[0], "count": len(records),
                     "error": "", "reason": "", "note": "", "seconds": 0.3}],
            "connectors_searched": list(self.connectors),
            "seen_urls": {r.url for r in records},
        }

    def queries(self) -> List[str]:
        out: List[str] = []
        for _, qs in self.calls:
            out.extend(qs)
        return out


def _make_reader(full_urls: set):
    """Sirf inhi URL ka full text milta hai — baaki par imaandaar 'paywall'."""
    def _reader(pack, max_sources=3, budget_chars=2400):
        entries = []
        for s in pack.sources[:max_sources]:
            if (s.url or "") in full_urls:
                s.full_text_chars = 48000
                s.read_level = "full_text"
                entries.append({"source_id": s.source_id, "ok": True,
                                "chars": 48000, "reason": "", "title": s.title})
            else:
                entries.append({"source_id": s.source_id, "ok": False,
                                "chars": 0, "title": s.title,
                                "reason": "publisher paywall — koi legal free "
                                          "route nahi mila"})
        ok = [e for e in entries if e["ok"]]
        return {"attempted": len(entries), "succeeded": len(ok),
                "failed": len(entries) - len(ok), "skipped": 0,
                "chars_read": sum(e["chars"] for e in entries),
                "note": f"{len(ok)}/{len(entries)} ka full text mila",
                "entries": entries}
    return _reader


def _by_tag(case: DomainCase) -> Dict[str, Row]:
    return {r.tag: r for r in case.rows()}


def _pick_rows(case: DomainCase, *tags: str) -> List[Row]:
    bag = _by_tag(case)
    return [bag[t] for t in tags if t in bag]


def rounds_full(case: DomainCase) -> Dict[int, List[Row]]:
    """Asli haalat: har round mein thoda kaam ka, thoda kachra."""
    return {1: _pick_rows(case, "core_full", "overlap", "junk"),
            2: _pick_rows(case, "core_abs", "mirror", "junk_web", "lowq"),
            3: _pick_rows(case, "core_snip", "contra", "support", "retracted",
                          "meta")}


def rounds_support_only(case: DomainCase) -> Dict[int, List[Row]]:
    """Sirf support-side evidence — yahan consensus claim NAHI hona chahiye."""
    return {1: _pick_rows(case, "core_full", "core_abs", "support"), 2: [], 3: []}


def rounds_thin(case: DomainCase) -> Dict[int, List[Row]]:
    """Insufficient evidence — sirf snippet aur metadata."""
    return {1: _pick_rows(case, "core_snip", "meta"), 2: [], 3: []}


def full_text_urls(case: DomainCase) -> set:
    return {r.url for r in case.rows() if r.full_text}


# ── fake Gemini: apna hi prompt padh kar jawab banata hai ────────────────────
# Kyun: agar stub apne mann se [S1]/[S4] likhe to citation-validity aur
# read-level ke test jhoothe ho jaayenge (kabhi pass, kabhi fail — pack ka kram
# badalne par). Isliye ye model prompt se asli source ID aur asli read level
# nikaalta hai, bilkul jaise ek imaandaar model karta.
# Support both the legacy prompt shape (``[S1] (...)``) and the hardened
# source-data grammar (``[S1] SOURCE DESCRIPTOR ...``). The benchmark fake
# model must read the same guarded prompt production sends to real models.
_HEAD_RE = re.compile(r"^\[(S\d+)\](?:\s+\(|\s+SOURCE DESCRIPTOR)", re.M)
_WORD_RE = re.compile(r"[a-z0-9]{4,}")

RAW_TOKENS = ("ResourceExhausted", "grpc_status", "quota_id", "retry_delay",
              "Traceback", "protobuf", "RuntimeError")


def _pack_info(prompt: str) -> List[Tuple[str, str, str]]:
    """[(source_id, read_level, block_text)] — prompt se hi."""
    marks = list(_HEAD_RE.finditer(prompt or ""))
    out: List[Tuple[str, str, str]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(prompt)
        block = prompt[m.start():end]
        lvl = re.search(r"^Read:\s*(?:DATA>\s*)?(\S+)", block, re.M)
        out.append((m.group(1), lvl.group(1) if lvl else "snippet", block))
    return out


def _best(info, sentence: str, level: str = "") -> Tuple[str, str]:
    want = set(_WORD_RE.findall(sentence.lower()))
    best: Tuple[int, str, str] = (-1, "", "")
    for sid, lvl, block in info:
        if level and lvl != level:
            continue
        score = len(want & set(_WORD_RE.findall(block.lower())))
        if score > best[0]:
            best = (score, sid, lvl)
    return (best[1], best[2])


def _cite(info, sentence: str) -> str:
    sid, _ = _best(info, sentence)
    return f"{sentence} [{sid}]" if sid else sentence


def _line(info, sentence: str, prefer_full: bool = True) -> str:
    """Imaandaar label: [ESTABLISHED] sirf tab jab source ka full text padha ho."""
    sid, lvl = _best(info, sentence, level="full_text") if prefer_full else ("", "")
    if not sid:
        sid, lvl = _best(info, sentence)
    if not sid:
        return f"- [UNVERIFIED] {sentence}"
    tag = "ESTABLISHED" if lvl == "full_text" else "SOURCE-REPORTED"
    return f"- [{tag}] {sentence} [{sid}]"


def _overclaim(info, sentence: str) -> str:
    """Ganda model: snippet/metadata source par bhi [ESTABLISHED] chipka deta hai."""
    for sid, lvl, _block in info:
        if lvl in ("snippet", "metadata"):
            return f"- [ESTABLISHED] {sentence} [{sid}]"
    return _line(info, sentence)


def _analysis(case: DomainCase, info, mood: str) -> str:
    strong = (_overclaim(info, case.claim) if mood == "overclaim"
              else _line(info, case.claim))
    audit = " ".join(f"[{sid}]" for sid, _l, _b in info[:4]) or "(koi source nahi)"
    return ("## Factual Findings\n"
            f"{strong}\n"
            f"{_line(info, case.reported, prefer_full=False)}\n"
            "## Context & Mechanisms\n"
            f"{_cite(info, case.mechanism)}\n"
            "## Cross-Disciplinary Connections\n"
            f"{_cite(info, case.conclusion)}\n"
            "## Evidence Audit\n"
            f"[MIXED EVIDENCE] {audit}\n"
            "## Source Relevance Check\n"
            f"Saare use kiye gaye sources {case.label} ke hi hain.\n")


def _critique(case: DomainCase, info) -> str:
    return ("## Weaknesses\n"
            f"- {_cite(info, case.against)}\n"
            "- Retracted paper ko result nahi maana ja sakta.\n"
            "## Missing Evidence\n"
            f"- {case.unknown}\n"
            "## Alternative Explanations\n"
            f"- {_cite(info, case.mechanism)} — par measurement artefact bhi "
            "ho sakta hai.\n")


def _synthesis(case: DomainCase, info, mood: str) -> str:
    numbers = case.numbers_bad if mood == "bad_math" else case.numbers_ok
    strong = (_overclaim(info, case.claim) if mood == "overclaim"
              else _line(info, case.claim))
    return ("## Seedha jawab\n"
            f"{_cite(info, case.conclusion)}\n\n"
            "## Research se kya pata chala?\n"
            "### Fact\n"
            f"- **{case.label}:** {numbers}\n"
            f"{_line(info, case.reported, prefer_full=False)}\n"
            "### Inference\n"
            f"- [INFERENCE] {_cite(info, case.mechanism)}\n\n"
            "## Ye kyun hota hai?\n"
            f"{_cite(info, case.mechanism)}\n\n"
            "## Evidence kya kehta hai?\n"
            f"{strong}\n\n"
            "## Iske against kya mila?\n"
            f"{_cite(info, case.against)}\n\n"
            "## Kya abhi unknown hai?\n"
            f"{case.unknown}\n\n"
            "## Final conclusion\n"
            f"{_cite(info, case.conclusion)}\n")


def _hyp_blocks(case: DomainCase, info, count: int = 3) -> str:
    """Poore field wale hypotheses — parser ke maange hue saare labels ke saath."""
    ids = [sid for sid, _l, _b in info] or ["S1"]
    out = []
    for i, stmt in enumerate(case.hyp[:count], start=1):
        sup = ids[min(i - 1, len(ids) - 1)]
        cnt = ids[min(i, len(ids) - 1)]
        out.append(
            f"## Hypothesis {i}\n"
            f"- Statement: {stmt}\n"
            f"- Simple explanation: Humara idea ye hai ki {stmt.lower()}. "
            f"Iska matlab hai ki {case.label} mein jo asar dikha, wo har jagah "
            f"ek jaisa nahi hoga — wajah alag ho sakti hai.\n"
            f"- Reasoning: Step 1 — [{sup}] ka data isi taraf jaata hai. "
            f"Step 2 — [{cnt}] ulta ishara karta hai, isliye farak kisi teesri "
            f"cheez se aa raha hai.\n"
            f"- Supporting evidence: [{sup}] isi taraf ishara karta hai\n"
            f"- Counter-evidence: [{cnt}] mein wahi asar nahi mila\n"
            f"- Novelty: pehle is farak ko sirf measurement error maana jaata tha\n"
            f"- Assumptions: dono studies ne ek jaisa measurement protocol use kiya\n"
            f"- Prediction: agar ye sach hai to {case.label} ke agle dataset mein "
            f"asar 30% tak kam dikhega\n"
            f"- Required experiment: 20 unit ka pre-registered comparison, ek "
            f"control group ke saath, aur raw data pehle se register kiya hua\n"
            f"- Falsification test: agar control group mein bhi wahi asar mile "
            f"to ye hypothesis khatam\n"
            f"- Risks: sample chhota rah gaya to nateeja shor mein dab jaayega\n"
            f"- Confidence: MEDIUM\n")
    return "\n".join(out)


class _Model:
    """
    `GeminiReasoning.generate` ki jagah — chaar mood:

        healthy    — teeno pass theek, sahi label aur asli [S#] IDs
        dead       — pehli call se hi 429 (khaali string + raw error, bilkul
                     jaise asli SDK karta hai — exception nahi)
        bad_math   — jawab aata hai par unit conversion aur tulna ulti
        overclaim  — snippet-only source par bhi [ESTABLISHED] chipkata hai
                     (Claim Verification A-E ka gate isi se test hota hai)
    """

    def __init__(self, case: DomainCase, mood: str = "healthy") -> None:
        self.case = case
        self.mood = mood
        self.labels: List[str] = []
        self.prompts: List[str] = []

    def __call__(self, brain, prompt, label=""):
        if brain.remaining <= 0:
            raise gemini_reasoning.QuotaExhausted(
                f"call budget ({brain.budget}) khatam — '{label}' skip hua")
        brain.calls_used += 1
        self.labels.append(label)
        self.prompts.append(prompt)
        if self.mood == "dead":
            brain.errors.append(
                f"{label} failed: ResourceExhausted: 429 grpc_status:8 "
                f"quota_id: GenerateRequestsPerDayPerProject "
                f"retry_delay {{ seconds: 44 }}")
            return ""
        info = _pack_info(prompt)
        tail = ("\n\n" + _hyp_blocks(self.case, info)
                if "## Hypothesis 1" in prompt else "")
        if label == "critique":
            return _critique(self.case, info) + tail
        if label == "synthesis":
            return _synthesis(self.case, info, self.mood) + tail
        return _analysis(self.case, info, self.mood) + tail


def _run(case: DomainCase, per_round: Dict[int, List[Row]],
         mode: str = "MAXIMUM", mood: str = "healthy",
         question: Optional[str] = None):
    """Poora asli pipeline — sirf network aur Google stubbed."""
    disc = _Discovery(per_round, [case.connector, "openalex", "crossref",
                                  "zenodo"])
    fake = _Model(case, mood=mood)
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id=f"xdomain-{case.key}",
                                    enable_kg=False, enable_memory=False)
        engine.vectors = _FakeVectors()
        engine.discovery.discover = disc
        engine.reader.enrich = _make_reader(full_text_urls(case))
        q = question or (case.question + " Kam se kam 3 nayi hypotheses banao.")
        return engine.research(q, depth_mode=mode), disc, fake
    finally:
        gemini_reasoning.GeminiReasoning.generate = original


VARIANTS = {
    "healthy":   lambda c: _run(c, rounds_full(c)),
    "dead":      lambda c: _run(c, rounds_full(c), mood="dead"),
    "bad_math":  lambda c: _run(c, rounds_full(c), mood="bad_math"),
    "overclaim": lambda c: _run(c, rounds_full(c), mood="overclaim"),
    "support":   lambda c: _run(c, rounds_support_only(c)),
    "thin":      lambda c: _run(c, rounds_thin(c)),
}

_CACHE: Dict[Tuple[str, str], tuple] = {}


def run_cached(case: DomainCase, variant: str):
    """Ek (domain, variant) ka run ek hi baar — 8 domain × 6 variant sasta rahe."""
    key = (case.key, variant)
    if key not in _CACHE:
        _CACHE[key] = VARIANTS[variant](case)
    return _CACHE[key]


def _titles(result: dict) -> str:
    return " | ".join(str(s.get("title", "")) for s in result["sources"])


def _human_part(answer: str) -> str:
    return (answer or "").split("### Technical details")[0]


def _heading_pos(answer: str, heading: str) -> int:
    m = re.search(r"^" + re.escape(heading) + r"(?:\s.*)?$", answer or "", re.M)
    return m.start() if m else -1


def _tag_titles(case: DomainCase, *tags: str) -> List[str]:
    bag = _by_tag(case)
    return [bag[t].title for t in tags if t in bag]


def _pack_order(result: dict) -> List[dict]:
    """
    Engine ki ASLI ranking — S1, S2, S3 … ke kram mein poora evidence pack.

    Kyun `result["sources"]` nahi: wo list citation order mein hai (jawaab mein
    [S#] kis kram se aaya). Yaani usse "ranking" naapna dar-asal reasoning model
    ki pasand naapna hai, engine ki ranking nahi. Source ID pack ke kram se
    milta hai, aur pack ka kram hi `relevance.rank()` ka faisla hai — isliye
    ranking ke checks yahan se padhte hain. Cited + uncited dono chahiye, warna
    pack adhoora dikhta hai.
    """
    rows = list(result.get("sources") or []) + list(result.get("uncited_sources") or [])
    def num(row: dict) -> int:
        m = re.search(r"\d+", str(row.get("source_id") or ""))
        return int(m.group()) if m else 10 ** 6
    seen: Set[str] = set()
    out: List[dict] = []
    for row in sorted(rows, key=num):
        sid = str(row.get("source_id") or row.get("title") or "")
        if sid in seen:
            continue
        seen.add(sid)
        out.append(row)
    return out or [{}]


# ── check group 1: domain detection + query expansion ────────────────────────
def check_domain(case: DomainCase) -> None:
    with scope(case.key, "domain"):
        plan = domain_mod.detect(case.question)
        eq("domain detection sahi", plan.profile.key, case.expect_domain)
        eq("hard rejection (strict) chaalu", plan.strict, case.strict)
        qs = plan.expanded_queries(case.question)
        check("expansion ne base query ke alawa bhi queries banayi",
              len(qs) >= 3, str(qs[:3]))
        intents = plan.search_intents()
        check("teen se zyada alag search intents",
              len({i.get("key") for i in intents}) >= 3,
              str([i.get("key") for i in intents]))
        blob = " ".join(qs + [str(i.get("query", "")) for i in intents]
                        + list(plan.fallback_queries(case.question))).lower()
        hits = [w for w in case.intents if w in blob]
        check("query expansion domain-specific hai (sawaal ke shabdon se aage)",
              len(hits) >= 2, f"mile={hits} blob={blob[:160]}")


# ── check group 2: relevance + ranking + duplicates ──────────────────────────
def check_relevance(case: DomainCase) -> None:
    result, disc, _ = run_cached(case, "healthy")
    with scope(case.key, "relevance"):
        titles = _titles(result).lower()
        all_titles = (titles + " | " + " | ".join(
            str(s.get("title", "")).lower()
            for s in (result.get("uncited_sources") or [])))
        for tag in ("junk", "junk_web"):
            for t in _tag_titles(case, tag):
                check(f"off-domain kachra reject ({tag}): {t[:44]}",
                      t.lower() not in all_titles, all_titles[:200])
        for t in _tag_titles(case, "overlap"):
            check(f"keyword-overlap wala dhoka reject: {t[:44]}",
                  t.lower() not in all_titles, all_titles[:200])
        for t in _tag_titles(case, "core_full", "core_abs"):
            check(f"kaam ka source pack mein hai: {t[:44]}",
                  t.lower() in all_titles, all_titles[:200])
        base = _tag_titles(case, "core_full")
        if base:
            check("mirror/duplicate copy ek hi baar",
                  all_titles.count(base[0].lower()) == 1,
                  str(all_titles.count(base[0].lower())))
        top = _pack_order(result)[0]
        ttitle = str(top.get("title", "")).lower()
        check("ranking mein sabse upar is field ka hi source",
              any(w in ttitle for w in case.top_words), ttitle)
        eq("aur wo peer-reviewed hai", top.get("peer_reviewed"), True)
        low = _tag_titles(case, "lowq")
        if low:
            top3 = " | ".join(str(s.get("title", "")).lower()
                              for s in _pack_order(result)[:3])
            check("ghatiya quality wala source top-3 mein nahi",
                  low[0].lower() not in top3, top3[:160])
        cov = result["coverage"]
        check("off-topic ginti honestly report hui",
              int(cov.get("offtopic_dropped") or 0) >= 3,
              str(cov.get("offtopic_dropped")))
        check("avg relevance report hui", cov.get("avg_relevance") is not None)


# ── check group 3: evidence depth + citation integrity ───────────────────────
def _id_url(result: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for s in list(result.get("sources") or []) + list(result.get("uncited_sources") or []):
        out[str(s.get("source_id"))] = str(s.get("url") or "")
    return out


def check_evidence(case: DomainCase) -> None:
    result, _, _ = run_cached(case, "healthy")
    with scope(case.key, "evidence"):
        cov = result["coverage"]
        levels = cov.get("read_levels") or {}
        allowed = {u.lower() for u in full_text_urls(case)}
        per = (cov.get("reading") or {}).get("per_source") or []
        id2url = _id_url(result)
        read_ok = [p for p in per if p.get("read")]
        for p in read_ok:
            url = id2url.get(str(p.get("source_id")), "").lower()
            check(f"full_text sirf usi source ka jo asli mein padha gaya ({p.get('source_id')})",
                  any(url.startswith(a) or a in url for a in allowed), url or "url-missing")
        eq("full_text ki ginti = actually padhe gaye sources",
           int(levels.get("full_text") or 0), len(read_ok))
        check("snippet/abstract/metadata levels bhi report hue",
              sum(int(levels.get(k) or 0)
                  for k in ("snippet", "abstract", "metadata")) >= 2, str(levels))
        for p in per:
            if not p.get("read"):
                check(f"na padhe source ka reason diya ({p.get('source_id')})",
                      bool(str(p.get("reason") or "").strip()), str(p))
        answer = result["answer"]
        used = set(re.findall(r"\[(S\d+)\]", answer))
        known = set(id2url)
        check("answer ke saare [S#] IDs asli retrieved evidence ke hain",
              used and used.issubset(known), f"used={sorted(used)} known={sorted(known)}")
        audit = result.get("verification") or {}
        eq("invalid citations = 0", int(result.get("invalid_citations") or 0), 0)
        names = [str(c.get("check")) for c in (audit.get("checks") or [])]
        check("citation validity check chali", "citation validity" in names, str(names))
        retr = int(cov.get("retracted_sources") or 0)
        check("retracted/unreliable source flag hua ya bahar phenka",
              retr >= 1 or all(t.lower() not in _titles(result).lower()
                               for t in _tag_titles(case, "retracted")),
              f"retracted_sources={retr}")


# ── check group 4: claim verification A–E + label gates ──────────────────────
_A_E = ("internal numeric consistency", "citation validity",
        "claims grounded in sources", "physical limits", "unit conversion")


def _established_ids(answer: str) -> List[str]:
    out: List[str] = []
    for line in _human_part(answer).splitlines():
        if "[ESTABLISHED]" in line:
            out.extend(re.findall(r"\[(S\d+)\]", line))
    return out


def check_verification(case: DomainCase) -> None:
    with scope(case.key, "verification"):
        healthy, _, _ = run_cached(case, "healthy")
        names = [str(c.get("check")) for c in
                 ((healthy.get("verification") or {}).get("checks") or [])]
        for want in _A_E:
            check(f"claim verification check chali: {want}", want in names, str(names))
        check("paanchvi check (comparison/consensus direction) bhi chali",
              "comparison direction" in names, str(names))
        cov = healthy["coverage"]
        per = (cov.get("reading") or {}).get("per_source") or []
        deep = {str(p.get("source_id")) for p in per if p.get("read")}
        bad = [s for s in _established_ids(healthy["answer"]) if s not in deep]
        check("[ESTABLISHED] sirf us source par jiska full text padha gaya",
              not bad, f"galat={bad} full_text={sorted(deep)}")

        over, _, _ = run_cached(case, "overclaim")
        lr = over.get("label_report") or {}
        check("overclaim wale model ka strong label downgrade hua",
              int(lr.get("downgraded") or 0) >= 1, str(lr)[:200])
        hp = _human_part(over["answer"])
        check("downgrade ke baad honest label dikha",
              "[SOURCE-REPORTED]" in hp or "[UNVERIFIED]" in hp, hp[:160])
        obad = [s for s in _established_ids(over["answer"])
                if s not in {str(p.get("source_id")) for p in
                             ((over["coverage"].get("reading") or {})
                              .get("per_source") or []) if p.get("read")}]
        check("overclaim ke baad bhi koi jhootha [ESTABLISHED] nahi bacha",
              not obad, str(obad))

        thin, _, _ = run_cached(case, "thin")
        thp = _human_part(thin["answer"])
        check("patla evidence hone par koi [ESTABLISHED] nahi",
              "[ESTABLISHED]" not in thp, thp[:160])
        check("patle run mein honest label (UNKNOWN/INFERENCE/HYPOTHESIS) use hua",
              any(t in thp for t in ("[INFERENCE]", "[HYPOTHESIS]", "[UNKNOWN]",
                                     "[UNVERIFIED]", "[SOURCE-REPORTED]")), thp[:200])
        check("patla run VERIFIED/COMPLETE nahi kehlaya",
              "VERIFIED" not in str(thin.get("status", "")).upper(),
              str(thin.get("status")))

        math_r, _, _ = run_cached(case, "bad_math")
        ver = math_r.get("verification") or {}
        failed = {str(c.get("check")) for c in (ver.get("checks") or [])
                  if not c.get("passed")}
        check("galat unit conversion pakdi gayi", "unit conversion" in failed, str(failed))
        check("ulti comparison direction pakdi gayi",
              "comparison direction" in failed, str(failed))
        check("maths error hone par verification status honest",
              "MATH" in str(ver.get("status", "")).upper(), str(ver.get("status")))


# ── check group 5: contradiction + consensus honesty ─────────────────────────
_CONSENSUS_BRAG = ("sab sehmat hain", "strong consensus", "scientific consensus hai",
                   "poori duniya maanti hai")


def check_consensus(case: DomainCase) -> None:
    with scope(case.key, "consensus"):
        healthy, _, _ = run_cached(case, "healthy")
        answer = _human_part(healthy["answer"])
        pos = _heading_pos(answer, "## Iske against kya mila?")
        check("'iske against kya mila' section maujood", pos >= 0)
        seg = answer[pos:pos + 900] if pos >= 0 else ""
        check("opposition/contradiction ko asli mein consider kiya",
              len(seg.strip()) > 120 and "[S" in seg, seg[:160])
        check("contradiction list khaali nahi",
              bool(healthy.get("contradictions")), str(healthy.get("contradictions"))[:120])

        sup, _, _ = run_cached(case, "support")
        sa = sup["answer"]
        check("sirf support-side evidence par consensus claim nahi kiya",
              "Consensus evaluate nahi kiya ja saka" in sa, sa[-400:])
        check("kaaran bataya ki criticism-side query chali hi nahi",
              "Sirf support-side search hui" in sa, sa[-400:])
        brag = [ln.strip()[:90] for ln in sa.splitlines()
                if any(b in ln.lower() for b in _CONSENSUS_BRAG)
                and not any(n in ln.lower() for n in ("galat", "nahi", "mat "))]
        check("jhoothi sehmati ki bhasha nahi", not brag, str(brag))


# ── check group 6: hypothesis honesty (evidence gate) ────────────────────────
# Labels wahi jo user ko asli answer mein dikhte hain (synthesizer ki Hinglish).
_HYP_FIELDS = ("**Isko test kaise karenge:**",
               "**Kaunsa result ise galat sabit kar dega:**",
               "**Zaroori experiment / simulation:**",
               "**Humari assumption:**")


def _field_body(section: str, label: str) -> str:
    pos = section.find(label)
    if pos < 0:
        return ""
    return section[pos + len(label):].split("\n")[0].strip()


def check_hypothesis(case: DomainCase) -> None:
    with scope(case.key, "hypothesis"):
        healthy, _, _ = run_cached(case, "healthy")
        hyps = healthy.get("hypotheses") or []
        check("maange gaye 3 hypotheses mile", len(hyps) >= 3, f"mile={len(hyps)}")
        answer = _human_part(healthy["answer"])
        hpos = _heading_pos(answer, "## Humari Hypotheses")
        hsec = answer[hpos:] if hpos >= 0 else ""
        for field in _HYP_FIELDS:
            body = _field_body(hsec, field)
            check(f"hypothesis ka field bhara hua: {field.strip('*: ')}",
                  len(body) > 15, f"body={body[:60]!r}")
        check("hypothesis ke saath test/falsification ka plan diya",
              _heading_pos(answer, "## Hypothesis ko kaise test karenge?") > 0)

        thin, _, _ = run_cached(case, "thin")
        tcov = thin["coverage"]
        thyp = thin.get("hypotheses") or []
        check("patle evidence par hypothesis gate ne ginti kaati",
              len(thyp) <= 1,
              f"thin_hyp={len(thyp)} on_topic={tcov.get('on_topic_sources')} "
              f"full_text={tcov.get('full_text_sources_read')}")

        dead, _, _ = run_cached(case, "dead")
        check("model marne par jhoothe hypotheses nahi bane",
              len(dead.get("hypotheses") or []) == 0,
              str(len(dead.get("hypotheses") or [])))


# ── check group 7: fallback resilience + determinism ─────────────────────────
_MUST_SECTIONS = ("## Seedha jawab", "## Research se kya pata chala?",
                  "## Ye kyun hota hai?", "## Evidence kya kehta hai?",
                  "## Iske against kya mila?", "## Kya abhi unknown hai?",
                  "## Final conclusion")


def check_fallback(case: DomainCase) -> None:
    with scope(case.key, "fallback"):
        dead, _, fake = run_cached(case, "dead")
        answer = dead["answer"]
        human = _human_part(answer)
        leaks = [t for t in RAW_TOKENS if t in human]
        check("user ke jawab mein koi raw 429/traceback nahi", not leaks, str(leaks))
        check("model band hone par bhi status honest (RESEARCH INCOMPLETE)",
              "INCOMPLETE" in str(dead.get("status", "")).upper(), str(dead.get("status")))
        check("adhoore run ko VERIFIED/COMPLETE nahi bola",
              "VERIFIED" not in str(dead.get("status", "")).upper(), str(dead.get("status")))
        check("quota khatam hone ka insaani kaaran bataya",
              bool(str(dead.get("status_reason") or "").strip()),
              str(dead.get("status_reason"))[:80])
        for sec in _MUST_SECTIONS:
            pos = _heading_pos(human, sec)
            nxt = len(human)
            for other in _MUST_SECTIONS + ("## Sources",):
                p2 = _heading_pos(human, other)
                if p2 > pos >= 0:
                    nxt = min(nxt, p2)
            body = human[pos + len(sec):nxt].strip() if pos >= 0 else ""
            check(f"model ke bina bhi section bhara: {sec}",
                  pos >= 0 and len(body) > 60, f"len={len(body)}")
        check("bina LLM ke bhi sources cite hue", "[S1]" in human, human[:120])

        one = VARIANTS["dead"](case)[0]["answer"]
        two = VARIANTS["dead"](case)[0]["answer"]
        eq("do baar chalane par offline fallback bilkul same output",
           _human_part(one) == _human_part(two), True)


# ── check group 8: presentation order (human-first) ──────────────────────────
def check_presentation(case: DomainCase) -> None:
    with scope(case.key, "presentation"):
        healthy, _, _ = run_cached(case, "healthy")
        answer = healthy["answer"]
        first = _heading_pos(answer, "## Seedha jawab")
        src = _heading_pos(answer, "## Sources")
        audit = _heading_pos(answer, "## Research quality / technical audit")
        tech = answer.find("### Technical details")
        eq("jawab seedha insaani answer se shuru hota hai", first, 0)
        check("sources human explanation ke baad aate hain", first < src, f"{first} {src}")
        check("technical audit sources ke baad", src < audit, f"{src} {audit}")
        check("developer technical details sabse aakhir mein",
              tech == -1 or tech > audit, f"{tech} {audit}")
        check("jawab ki shuruaat mein koi raw JSON/label dump nahi",
              not any(t in answer[:400] for t in RAW_TOKENS + ("{'", '{"')),
              answer[:120])
        check("audit section mein A–E jaanch dikhi",
              "A–E" in answer or "paanch-check" in answer, answer[audit:audit + 400])


# ── domain-confusion matrix ──────────────────────────────────────────────────
# Har row = ek sawaal ka domain, har column = kis domain ke core sources ko
# score kiya gaya. Diagonal upar hona chahiye; forbidden jodiyon ko keyword
# overlap ke bharose andar nahi aana chahiye.
FORBIDDEN: Tuple[Tuple[str, str], ...] = (
    ("materials", "biology"),     # thin-film "resistance" wala biology paper
    ("materials", "medicine"),
    ("cs_ai", "economics"),       # "model" shabd se finance paper AI mein nahi
    ("economics", "cs_ai"),
    ("medicine", "materials"),
    ("energy", "archaeology"),
    ("archaeology", "energy"),
    ("biology", "materials"),
    ("engineering", "archaeology"),
)
_FLOOR = 0.30


def _core_records(case: DomainCase) -> List[SourceRecord]:
    rows = [r for r in case.rows() if r.tag in ("core_full", "core_abs", "core_snip")]
    return _records(rows)


def confusion_matrix() -> Dict[str, Dict[str, float]]:
    eng = RelevanceEngine()
    grid: Dict[str, Dict[str, float]] = {}
    for row_case in CASES:
        row: Dict[str, float] = {}
        for col_case in CASES:
            scores = [eng.score_relevance(r, row_case.question)
                      for r in _core_records(col_case)]
            row[col_case.key] = round(max(scores) if scores else 0.0, 3)
        grid[row_case.key] = row
    return grid


def check_confusion(grid: Dict[str, Dict[str, float]]) -> None:
    for case in CASES:
        with scope(case.key, "relevance"):
            own = grid[case.key][case.key]
            check("apne domain ke core source floor se upar", own > _FLOOR, f"{own}")
            for a, b in FORBIDDEN:
                if a != case.key:
                    continue
                other = grid[a][b]
                check(f"cross-domain confusion nahi: {b} ka source {a} ke sawaal mein",
                      other < own and other < _FLOOR,
                      f"{b}={other} vs apna={own}")


def print_matrix(grid: Dict[str, Dict[str, float]]) -> None:
    keys = [c.key for c in CASES]
    print("\nDOMAIN-CONFUSION MATRIX (row = sawaal ka domain, col = source ka domain)")
    print("  " + "".join(f"{k[:9]:>11}" for k in keys).rjust(12))
    for k in keys:
        cells = "".join(f"{grid[k][c]:>11.3f}" for c in keys)
        print(f"{k[:11]:<12}{cells}")


# ── scorecard ────────────────────────────────────────────────────────────────
def print_scorecard() -> Tuple[int, int]:
    print("\nCROSS-DOMAIN SCORECARD")
    head = "domain".ljust(13) + "".join(f"{a[:9]:>11}" for a in AXES) + f"{'total':>12}"
    print(head)
    tp = tf = 0
    for case in CASES:
        per = SCORE.get(case.key, {})
        cells = ""
        dp = df = 0
        for axis in AXES:
            p, f = per.get(axis, [0, 0])
            dp += p
            df += f
            cells += f"{str(p) + '/' + str(p + f):>11}"
        tp += dp
        tf += df
        mark = "OK " if df == 0 else "FAIL"
        print(f"{case.key[:12]:<13}{cells}{(str(dp) + '/' + str(dp + df) + ' ' + mark):>12}")
    print(f"{'ALL':<13}{'':>{11 * len(AXES)}}{str(tp) + '/' + str(tp + tf):>12}")
    if FAILURES:
        print("\nEXACT FAILED CHECKS")
        for key, items in FAILURES.items():
            print(f"  [{key}]")
            for it in items:
                print(f"    - {it}")
    return tp, tf


def main() -> int:
    groups = (check_domain, check_relevance, check_evidence, check_verification,
              check_consensus, check_hypothesis, check_fallback, check_presentation)
    for case in CASES:
        print(f"\n===== {case.label} ({case.key}) =====")
        for fn in groups:
            try:
                fn(case)
            except Exception as exc:  # harness bug bhi failure hai, chhupana nahi
                with scope(case.key, "presentation"):
                    check(f"{fn.__name__} bina crash chala", False, f"{type(exc).__name__}: {exc}")
    print("\n===== domain-confusion matrix =====")
    grid = confusion_matrix()
    check_confusion(grid)
    print_matrix(grid)
    passed, failed = print_scorecard()
    print(f"\nCROSS-DOMAIN BENCHMARK: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
