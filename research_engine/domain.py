"""
Domain model — Superconductivity Test #3 ke §2/§3/§4/§5/§15 ka base.

Problem jo is file se theek hota hai:
  Pehle poora system SIRF lexical tha. "room-temperature superconductivity"
  poochne par "room-temperature ferroelectricity", "hybrid banana/luffa fibre
  prosthetic leg" (kyunki 'materials'), aur "maternal deaths" dataset relevance
  filter se nikal gaye. Wajah: kisi ko pata hi nahi tha ki sawaal KIS FIELD ka
  hai. Keyword match tha, domain match nahi.

Yahan teen cheezein define hoti hain:
  1. ANCHORS  — field ke wo shabd jinke bina koi source us field ka nahi ho
                sakta (superconduct*, Tc, Cooper pair, Meissner, hydride...).
  2. BRANCHES — sawaal ke asli research sub-questions. Source "relevant" tab
                hai jab wo kam se kam EK branch mein madad kare.
  3. ROUTING  — kaun se connectors is field ke liye matlab rakhte hain
                (superconductivity ke liye WHO GHO nahi).

Ye file jaan-boojh kar pure-Python aur offline hai — koi embedding model,
koi network, koi nayi dependency. Free tier par chalna hai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Set, Tuple

# ── stemming (relevance.py jaisa hi, taaki dono ek hi bhasha bolein) ─────────
_SUFFIXES = ("ivities", "ivity", "ities", "ing", "ers", "ies", "ors",
             "ion", "ial", "ed", "es", "s", "al")


def stem(word: str) -> str:
    """Halka stem — 'superconductivity' aur 'superconductors' ek jagah aayein."""
    w = (word or "").strip().lower()
    if len(w) <= 4:
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


_WORD_RE = re.compile(r"[a-z0-9ऀ-ॿ][a-z0-9\-ऀ-ॿ]*")


def tokens(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower())


def stems(text: str) -> Set[str]:
    out: Set[str] = set()
    for tok in tokens(text):
        out.add(stem(tok))
        if "-" in tok:                      # "room-temperature" → room, temperature
            for part in tok.split("-"):
                if len(part) > 2:
                    out.add(stem(part))
    return out


def phrase_hit(phrase: str, bag: Set[str]) -> bool:
    """
    Multi-word anchor ('critical temperature') tab hit hai jab uske SAARE
    shabd source mein hon. Single word ke liye seedha lookup.
    """
    parts = [stem(p) for p in phrase.split() if p]
    if not parts:
        return False
    return all(p in bag for p in parts)


def count_hits(needles: Sequence[str], bag: Set[str]) -> int:
    return sum(1 for n in needles if phrase_hit(n, bag))


def matched(needles: Sequence[str], bag: Set[str]) -> List[str]:
    return [n for n in needles if phrase_hit(n, bag)]


# ── Branch = ek research sub-question ────────────────────────────────────────
@dataclass(frozen=True)
class Branch:
    """
    Ek research sub-question. `terms` mein se koi bhi mile to source is branch
    mein "madad kar raha hai" mana jaata hai. `query` deterministic search ke
    liye ready-made string hai (LLM na chale tab bhi kaam chalta rahe — §15).

    `must=True` = ye angle kabhi truncate nahi hoga. Kyun zaroori hai: jis field
    mein 17 branches hain (superconductivity), wahan `expanded_queries(limit=9)`
    aur `search_intents(limit=8)` declaration-order se kaat dete the — aur
    "replication / retraction" wala angle sabse aakhir mein tha, isliye wahi
    kat jaata tha. Yaani jis field ka SABSE bada failure mode retracted claim
    hai, uska "kya ye replicate hua?" search hi nahi hota tha (cross-domain
    benchmark, 2026-08-21). Aisa angle ab reserved slot leta hai. Isi wajah se
    "mechanism kyun kaam karta hai" wala angle bhi reserved hai — un dono ke
    bina report sirf aankdon ki list ban jaati hai.
    """
    key: str
    label: str
    terms: Tuple[str, ...]
    query: str = ""
    must: bool = False

    def hits(self, bag: Set[str]) -> int:
        return count_hits(self.terms, bag)


@dataclass(frozen=True)
class DomainProfile:
    """
    Ek field ka poora profile. `strict=True` ka matlab: is field mein anchor ke
    bina source ho hi nahi sakta, isliye anchor-less source HARD REJECT hoga.

    `shared_anchors` = wo anchors jo IMAANDAARI se doosre fields bhi use karte
    hain ("critical temperature" physics mein bhi hai aur protein folding mein
    bhi; "wage" economics mein bhi hai aur ek RL paper ke title mein bhi aa
    sakta hai). Aise anchor par akela bharosa nahi kiya jaata — cross-domain
    benchmark (2026-08-21) mein protein-folding ka paper superconductivity ke
    pack mein isi wajah se ghus gaya tha.
    """
    key: str
    label: str
    triggers: Tuple[str, ...]
    anchors: Tuple[str, ...]
    branches: Tuple[Branch, ...] = ()
    connectors: Tuple[str, ...] = ()
    avoid_connectors: Tuple[str, ...] = ()
    source_types: Tuple[str, ...] = ()
    strict: bool = True
    shared_anchors: Tuple[str, ...] = ()

    def trigger_hits(self, bag: Set[str]) -> int:
        return count_hits(self.triggers, bag)

    def anchor_hits(self, bag: Set[str]) -> int:
        return count_hits(self.anchors, bag)

    def field_hits(self, bag: Set[str]) -> int:
        """
        Is source ke text mein is field ke kitne nishaan hain — trigger aur
        anchor dono. Rival comparison isi se hota hai (sirf trigger ginne se
        biology ka paper "1 hit" dikhta tha jabki uske paas poori vocabulary
        thi).
        """
        return count_hits(self.triggers, bag) + count_hits(self.anchors, bag)

    def exclusive_anchors(self) -> Tuple[str, ...]:
        shared = set(self.shared_anchors)
        return tuple(a for a in self.anchors if a not in shared)


# ── connector groups (asli naam — connectors/*.py se) ────────────────────────
SCHOLARLY = ("arxiv", "openalex", "semantic_scholar", "crossref", "doaj")
BIOMED = ("pubmed", "openalex", "crossref", "semantic_scholar", "doaj")
BOOKS = ("google_books", "open_library", "internet_archive")
OPEN_DATA = ("zenodo", "data_gov")
HEALTH_DATA = ("who_gho", "world_bank")
ECON_DATA = ("world_bank", "data_gov", "data_gov_in")
ML_DATA = ("huggingface", "zenodo")

# ── superconductivity: Test #3 ka asli field ─────────────────────────────────
_SC_BRANCHES = (
    Branch("tc", "confirmed transition temperatures",
           ("critical temperature", "transition temperature", "tc", "onset",
            "superconducting transition", "kelvin"),
           "highest confirmed superconducting transition temperature"),
    Branch("pressure", "pressure requirements",
           ("pressure", "gpa", "megabar", "diamond anvil", "compression",
            "ambient pressure"),
           "high pressure hydride superconductivity"),
    Branch("hydride", "hydride superconductors",
           ("hydride", "hydrogen", "lah10", "lanthanum hydride", "sulfur hydride",
            "h3s", "carbonaceous sulfur hydride", "superhydride"),
           "ambient pressure superconducting hydrides"),
    Branch("cuprate", "cuprates",
           ("cuprate", "ybco", "bscco", "copper oxide", "yba2cu3o7", "lsco"),
           "cuprate superconductivity mechanism"),
    Branch("iron", "iron-based superconductors",
           ("iron based", "pnictide", "fese", "iron pnictide", "chalcogenide",
            "lifeas", "bafe2as2"),
           "iron based superconductors transition temperature"),
    Branch("nickelate", "nickelates aur doosre material family",
           ("nickelate", "infinite layer", "ndnio2", "mgb2", "heavy fermion",
            "organic superconductor", "topological superconductor"),
           "nickelate superconductivity thin film"),
    Branch("mechanism", "superconductivity ka mechanism",
           ("cooper pair", "bcs", "electron phonon", "pairing", "gap symmetry",
            "pseudogap", "eliashberg", "unconventional", "d wave", "spin fluctuation"),
           "superconductivity pairing mechanism theory",
           must=True),
    Branch("controversy", "controversial claims / replication / retraction",
           ("replication", "retraction", "retracted", "irreproducible",
            "reanalysis", "dispute", "misconduct", "lk 99", "dias"),
           "room temperature superconductor replication retraction controversy",
           must=True),
    Branch("ambient", "ambient-pressure stability",
           ("ambient", "atmospheric pressure", "metastable", "stability",
            "room temperature"),
           "room temperature superconductivity ambient pressure"),
    Branch("limits", "theoretical physical limits",
           ("upper bound", "theoretical limit", "maximum tc", "allen dynes",
            "mcmillan", "first principles", "dft"),
           "theoretical upper limit of superconducting critical temperature"),
    Branch("discovery", "materials discovery",
           ("materials discovery", "high throughput", "screening", "synthesis",
            "crystal structure prediction", "phase diagram"),
           "computational materials discovery superconductors"),
    Branch("ml", "machine learning for superconductors",
           ("machine learning", "neural network", "deep learning", "regression",
            "dataset", "supercon", "graph neural"),
           "machine learning superconductor materials discovery"),
    Branch("manufacturing", "manufacturing / engineering limits",
           ("wire", "tape", "coated conductor", "fabrication", "scalable",
            "critical current", "flux pinning", "grain boundary"),
           "superconducting wire manufacturing critical current"),
    Branch("applications", "applications",
           ("magnet", "mri", "power transmission", "maglev", "squid",
            "quantum computing", "fusion", "levitation"),
           "superconductor applications magnets power transmission"),
    # Ye teen intents jaan-boojh kar ALAG rakhe gaye hain (2026-08-21).
    # "applications" ek hi jhaadu tha jisme MRI, maglev, grid aur qubit sab
    # ghus jaate the — yaani teen bilkul alag literatures ek hi query par
    # depend kar rahi thi. Superconducting cable ka paper Jc measurement ke
    # paper se aur qubit coherence ke paper se alag jagah chhapta hai, isliye
    # ab teeno ki apni search intent hai.
    Branch("transport", "current-carrying capacity / transport properties",
           ("critical current density", "jc", "flux pinning", "vortex",
            "pinning centre", "pinning center", "irreversibility field",
            "upper critical field", "hc2", "current carrying", "ampacity"),
           "superconductor critical current density flux pinning transport"),
    Branch("grid", "power grid / transmission engineering",
           ("power grid", "transmission cable", "superconducting cable",
            "fault current limiter", "sfcl", "energy storage", "smes",
            "utility", "substation", "cryogenic cooling cost"),
           "superconducting power transmission cable grid demonstration"),
    Branch("computing", "computing / quantum hardware",
           ("qubit", "josephson junction", "single flux quantum", "sfq",
            "rsfq", "quantum processor", "coherence time", "quantum annealer",
            "cryogenic electronics", "digital logic", "quantum computing",
            "quantum computer"),
           "superconducting qubit josephson junction quantum computing hardware"),
)

_SC_ANCHORS = (
    "superconduct", "superconductor", "superconductivity", "superconducting",
    "tc", "critical temperature", "transition temperature", "cooper pair",
    "meissner", "bcs", "hydride", "cuprate", "nickelate", "pnictide",
    "josephson", "flux pinning", "critical current", "supercurrent",
    "zero resistance", "diamagnetism", "lk 99", "mgb2", "ybco",
)

# Ye do phrase physics ke bahar bhi imaandaari se use hote hain (protein folding
# transition, phase transition in polymers), isliye inke akele match par
# superconductivity ka source nahi maana jaata.
_SC_SHARED = ("tc", "critical temperature", "transition temperature")


# ── baaki fields ke branches (2026-08-21) ────────────────────────────────────
# Kyun: cross-domain benchmark ne pakda ki SIRF superconductivity ke paas
# branches thi. Nateeja: baaki 7 fields mein `expanded_queries()` sirf base
# query lautata tha aur `search_intents()` KHAALI aati thi — yaani query
# expansion domain-specific hi nahi tha aur ek hi generic query par poora
# research tika hua tha. Har field ke intents wahi hain jinki literature asli
# duniya mein alag-alag jagah chhapti hai.
_MAT_BRANCHES = (
    Branch("synthesis", "synthesis / processing route",
           ("synthesis", "sintering", "deposition", "annealing", "sol gel",
            "single crystal", "thin film growth"),
           "materials synthesis processing route microstructure"),
    Branch("structure", "structure / characterisation",
           ("diffraction", "xrd", "tem", "sem", "raman", "crystal structure",
            "lattice parameter", "microstructure"),
           "crystal structure characterisation diffraction analysis"),
    Branch("property", "functional properties",
           ("band gap", "conductivity", "dielectric", "hardness",
            "thermal conductivity", "mobility", "modulus"),
           "material functional property measurement band gap conductivity"),
    Branch("degradation", "stability / degradation / failure",
           ("degradation", "corrosion", "fatigue", "stability", "ageing",
            "aging", "oxidation"),
           "material degradation stability failure mechanism"),
    Branch("simulation", "simulation / first principles",
           ("dft", "first principles", "molecular dynamics", "finite element",
            "phase field", "ab initio"),
           "first principles simulation materials property prediction"),
)

_MED_BRANCHES = (
    Branch("efficacy", "efficacy / outcome trials",
           ("randomised", "randomized", "placebo", "trial", "efficacy",
            "endpoint", "hazard ratio", "relative risk"),
           "randomised controlled trial efficacy primary endpoint"),
    Branch("meta", "systematic review / meta-analysis",
           ("meta analysis", "systematic review", "pooled", "heterogeneity",
            "forest plot", "cochrane"),
           "systematic review meta-analysis pooled effect estimate"),
    Branch("safety", "safety / adverse events",
           ("adverse", "side effect", "toxicity", "safety", "contraindication",
            "withdrawal", "harm"),
           "adverse events safety profile treatment harms"),
    Branch("mechanism", "mechanism of action",
           ("mechanism", "pathway", "receptor", "pharmacokinetic",
            "pharmacodynamic", "biomarker"),
           "mechanism of action pathway pharmacology"),
    Branch("epidemiology", "epidemiology / real-world data",
           ("cohort", "registry", "observational", "incidence", "prevalence",
            "population based", "real world"),
           "population cohort registry real-world outcomes"),
    Branch("guideline", "guidelines / cost-effectiveness",
           ("guideline", "recommendation", "cost effectiveness", "screening",
            "policy", "who"),
           "clinical guideline recommendation cost effectiveness"),
)

_BIO_BRANCHES = (
    Branch("mechanism", "molecular mechanism",
           ("gene expression", "pathway", "enzyme", "protein", "receptor",
            "transcription", "knockout"),
           "molecular mechanism gene expression pathway"),
    Branch("resistance", "resistance / adaptation / evolution",
           ("resistance", "resistant", "selection pressure", "adaptation",
            "field evolved", "susceptibility", "fitness cost"),
           "field evolved resistance selection pressure monitoring"),
    Branch("field_trial", "field trials / agronomy",
           ("field trial", "yield", "crop", "agronomic", "plot", "cultivar",
            "sowing", "irrigation"),
           "multi-season field trial yield agronomic performance"),
    Branch("ecology", "ecology / environment impact",
           ("biodiversity", "soil", "ecosystem", "non target", "pollinator",
            "habitat", "runoff"),
           "environmental impact non-target species biodiversity"),
    Branch("genomics", "genomics / sequencing",
           ("genome", "sequencing", "transcriptome", "snp", "crispr",
            "population genetics"),
           "genome sequencing population genetics analysis"),
)

_CS_BRANCHES = (
    Branch("accuracy", "accuracy / benchmark results",
           ("benchmark", "accuracy", "perplexity", "f1", "state of the art",
            "evaluation", "test set", "ablation"),
           "benchmark evaluation ablation study accuracy machine learning model"),
    Branch("efficiency", "efficiency / latency / compression",
           ("quantization", "quantisation", "pruning", "distillation",
            "latency", "throughput", "memory footprint", "int8", "4 bit"),
           "quantization pruning inference latency neural network"),
    Branch("training", "training / optimisation",
           ("training", "fine tuning", "gradient", "optimiser", "optimizer",
            "learning rate", "pretraining", "scaling law"),
           "training optimisation fine tuning neural network"),
    Branch("robustness", "robustness / failure modes",
           ("robustness", "adversarial", "distribution shift", "calibration",
            "hallucination", "out of distribution", "reproducibility"),
           "robustness distribution shift failure modes machine learning"),
    Branch("systems", "systems / hardware / deployment",
           ("gpu", "kernel", "inference server", "batching", "cuda",
            "on device", "edge deployment", "energy per token"),
           "inference serving hardware efficiency deep learning systems"),
)

_ENERGY_BRANCHES = (
    Branch("lifecycle", "life-cycle emissions / LCA",
           ("life cycle", "lifecycle", "lca", "embodied", "gco2", "co2eq",
            "carbon intensity", "cradle to grave"),
           "life cycle assessment lifecycle emissions carbon intensity "
           "gco2 per kwh"),
    Branch("storage", "storage technology comparison",
           ("battery storage", "pumped hydro", "round trip efficiency",
            "lithium iron phosphate", "duration", "state of charge"),
           "grid scale battery storage pumped hydro round trip efficiency"),
    Branch("grid", "grid integration / intermittency",
           ("intermittency", "curtailment", "capacity factor", "dispatch",
            "balancing", "transmission", "peak demand"),
           "renewable intermittency curtailment capacity factor grid integration"),
    Branch("cost", "cost / LCOE / policy",
           ("lcoe", "levelised", "levelized", "capex", "subsidy", "tariff",
            "cost per kwh"),
           "levelised cost of electricity storage capex tariff"),
    Branch("climate", "climate impact / scenarios",
           ("emission scenario", "warming", "mitigation", "net zero",
            "carbon budget", "cmip"),
           "emission scenario mitigation pathway net zero"),
)

_ECON_BRANCHES = (
    Branch("empirical", "empirical estimates / elasticities",
           ("elasticity", "difference in differences", "regression",
            "instrumental variable", "panel data", "estimate", "causal"),
           "difference in differences panel data elasticity empirical estimate"),
    Branch("labour", "labour market effects",
           ("employment", "unemployment", "wage", "minimum wage", "hours",
            "informal sector", "labour", "labor"),
           "minimum wage employment effect labour market"),
    Branch("firms", "firm-level response",
           ("small firm", "profit margin", "price pass through", "productivity",
            "compliance", "firm exit"),
           "firm level response price pass through productivity"),
    Branch("welfare", "welfare / distribution / poverty",
           ("poverty", "inequality", "distribution", "welfare", "household",
            "consumption"),
           "poverty inequality welfare distributional effect"),
    Branch("policy", "policy design / evaluation",
           ("policy", "reform", "enforcement", "compliance", "evaluation",
            "counterfactual"),
           "policy reform evaluation counterfactual evidence"),
)

_CHEM_BRANCHES = (
    Branch("mechanism", "reaction mechanism",
           ("mechanism", "intermediate", "transition state", "kinetics",
            "rate constant", "selectivity"),
           "reaction mechanism kinetics transition state"),
    Branch("catalysis", "catalysis / yield",
           ("catalyst", "turnover", "yield", "conversion", "ligand",
            "heterogeneous", "homogeneous"),
           "catalyst turnover yield conversion optimisation"),
    Branch("characterisation", "spectroscopy / characterisation",
           ("nmr", "mass spectrometry", "ir spectra", "uv vis",
            "crystallography", "spectra"),
           "spectroscopic characterisation nmr mass spectrometry"),
    Branch("scaleup", "scale-up / green chemistry",
           ("scale up", "solvent", "green chemistry", "atom economy",
            "flow chemistry", "waste"),
           "scale up green chemistry solvent selection"),
)

_SPACE_BRANCHES = (
    Branch("observation", "observations / surveys",
           ("survey", "photometry", "spectroscopy", "light curve",
            "telescope", "catalogue", "catalog"),
           "observational survey photometry spectroscopy catalogue"),
    Branch("dynamics", "dynamics / orbits",
           ("orbit", "ephemeris", "perturbation", "resonance", "transit",
            "radial velocity"),
           "orbital dynamics resonance transit radial velocity"),
    Branch("modelling", "modelling / simulation",
           ("simulation", "n body", "hydrodynamic", "radiative transfer",
            "population synthesis"),
           "numerical simulation hydrodynamic model astrophysics"),
    Branch("instrument", "instruments / missions",
           ("mission", "spacecraft", "detector", "calibration", "payload"),
           "space mission instrument calibration payload"),
)

_ENG_BRANCHES = (
    Branch("failure", "failure modes / root cause",
           ("failure mode", "root cause", "fatigue", "wear", "fracture",
            "bearing failure", "insulation failure", "breakdown"),
           "failure mode root cause analysis machinery"),
    Branch("diagnostics", "condition monitoring / diagnostics",
           ("vibration", "condition monitoring", "predictive maintenance",
            "fault detection", "acoustic emission", "thermography",
            "envelope spectrum", "prognostics"),
           "vibration based condition monitoring fault detection"),
    Branch("design", "design / sizing / tolerances",
           ("design", "tolerance", "sizing", "load", "stress", "torque",
            "efficiency curve", "derating"),
           "mechanical design load stress sizing standard"),
    Branch("control", "control / drives / electrical",
           ("inverter", "drive", "control loop", "pwm", "harmonics",
            "stator", "rotor", "winding"),
           "motor drive control harmonics stator winding"),
    Branch("standards", "standards / testing protocol",
           ("iso", "iec", "astm", "test rig", "accelerated test",
            "acceptance test", "reliability"),
           "test standard reliability accelerated testing protocol"),
)

_ARCH_BRANCHES = (
    Branch("dating", "dating / chronology",
           ("radiocarbon", "c14", "stratigraphy", "chronology", "typology",
            "dendrochronology", "luminescence", "phase dating"),
           "radiocarbon chronology stratigraphy dating sequence"),
    Branch("excavation", "excavation / material culture",
           ("excavation", "trench", "pottery", "ceramic", "artefact",
            "artifact", "seal", "bead", "settlement layer"),
           "excavation report material culture pottery assemblage"),
    Branch("palaeoclimate", "palaeoclimate proxies",
           ("palaeoclimate", "paleoclimate", "proxy", "isotope", "speleothem",
            "pollen", "lake sediment", "monsoon record"),
           "palaeoclimate proxy isotope record monsoon reconstruction"),
    Branch("trade", "trade networks / exchange",
           ("trade", "exchange network", "import", "provenance",
            "long distance", "mesopotamia", "seal impression"),
           "trade network exchange provenance analysis"),
    Branch("settlement", "settlement / urbanism / abandonment",
           ("urbanism", "settlement pattern", "abandonment", "deurbanisation",
            "deurbanization", "population decline", "survey area"),
           "settlement pattern urbanism abandonment survey"),
    Branch("historiography", "textual / historiographic debate",
           ("inscription", "archive", "chronicle", "historiography",
            "textual evidence", "colonial record"),
           "historiography textual evidence debate interpretation"),
)

PROFILES: Tuple[DomainProfile, ...] = (
    DomainProfile(
        key="superconductivity",
        label="superconductivity / condensed-matter physics",
        triggers=("superconduct", "superconductor", "superconductivity",
                  "cuprate", "hydride", "cooper pair", "meissner", "tc",
                  "critical temperature", "nickelate", "lk 99", "ybco"),
        anchors=_SC_ANCHORS,
        branches=_SC_BRANCHES,
        connectors=SCHOLARLY + BOOKS + ("zenodo",),
        avoid_connectors=("who_gho", "world_bank", "data_gov_in", "pubmed"),
        source_types=("preprint", "peer_reviewed_article", "review_article",
                      "book", "conference_paper", "dataset"),
        strict=True,
        shared_anchors=_SC_SHARED,
    ),
    DomainProfile(
        key="materials_physics",
        label="materials science / applied physics",
        triggers=("material", "alloy", "crystal", "semiconductor", "graphene",
                  "perovskite", "thin film", "nanomaterial", "composite",
                  "ferroelectric", "battery", "photovoltaic", "catalyst",
                  "electrolyte", "anode", "cathode", "solid state battery",
                  "dendrite", "coating", "ceramic"),
        anchors=("material", "alloy", "crystal", "lattice", "phase", "film",
                 "synthesis", "microstructure", "diffraction", "band gap",
                 "conductivity", "dielectric", "composite", "nanoparticle",
                 "electrolyte", "electrode", "interface", "grain boundary"),
        branches=_MAT_BRANCHES,
        connectors=SCHOLARLY + ("zenodo",) + BOOKS,
        avoid_connectors=("who_gho", "world_bank"),
        strict=True,
        # "phase" aur "conductivity" doosre fields (economics ka "phase",
        # neuroscience ka "conductivity") mein bhi aate hain.
        shared_anchors=("phase", "conductivity", "interface"),
    ),
    DomainProfile(
        key="medicine_health",
        label="medicine / public health",
        triggers=("disease", "patient", "clinical", "therapy", "treatment",
                  "mortality", "maternal", "vaccine", "cancer", "diabetes",
                  "epidemiology", "symptom", "drug", "surgery", "health",
                  "infection", "prosthetic", "sunbed", "screening programme",
                  "hba1c", "glycemic", "glycaemic", "statin", "antibiotic",
                  "randomised trial", "randomized trial", "meta analysis"),
        # 2026-08-21: pehle akela "clinical" / "outcome" anchor kaafi tha, aur
        # "Top 10 celebrity juice cleanses" jaisa blog medicine ke strict pack
        # mein ghus jaata tha. Ab anchors clinical-research ki asli vocabulary
        # hain, aur generic shabd shared_anchors mein hain.
        anchors=("patient", "clinical trial", "randomised", "randomized",
                 "cohort", "mortality", "incidence", "prevalence", "diagnosis",
                 "treatment", "therapy", "dose", "morbidity", "vaccine",
                 "disease", "placebo", "adverse event", "hazard ratio",
                 "confidence interval", "efficacy", "clinical", "outcome"),
        branches=_MED_BRANCHES,
        connectors=BIOMED + HEALTH_DATA + BOOKS,
        strict=True,
        shared_anchors=("clinical", "outcome", "treatment", "dose"),
    ),
    DomainProfile(
        key="biology_genetics",
        label="biology / genetics / agriculture",
        triggers=("gene", "genome", "protein", "cell", "enzyme", "dna", "rna",
                  "species", "microbiome", "evolution", "crispr", "plant",
                  "fibre", "fiber", "biocomposite",
                  # 2026-08-21: agriculture ki poori vocabulary missing thi,
                  # isliye Bt-cotton/bollworm ka sawaal `generic` gir jaata tha.
                  "crop", "yield", "pest", "pesticide", "insecticide", "cotton",
                  "bollworm", "agronomy", "agriculture", "soil", "cultivar",
                  "transgenic", "bt cotton", "herbicide", "seed", "harvest"),
        anchors=("gene", "genome", "protein", "cell", "enzyme", "sequence",
                 "expression", "mutation", "species", "tissue", "organism",
                 "crop", "pest", "insecticide", "pesticide", "larva",
                 "resistance allele", "cultivar", "agronomic", "yield",
                 "field trial", "soil", "biodiversity"),
        branches=_BIO_BRANCHES,
        connectors=BIOMED + ("zenodo",) + BOOKS,
        strict=True,
        shared_anchors=("cell", "expression", "yield", "soil", "resistance"),
    ),
    DomainProfile(
        key="cs_ml",
        label="computer science / machine learning",
        triggers=("algorithm", "neural", "machine learning", "transformer",
                  "llm", "software", "benchmark", "reinforcement",
                  "computer vision", "nlp", "language model", "quantization",
                  "quantisation", "fine tuning", "gpu", "inference latency",
                  "deep learning", "pruning", "distillation"),
        # 2026-08-21: bare "model"/"parameter"/"network"/"inference" ki wajah se
        # ek stochastic-volatility FINANCE paper cs_ml ke pack mein 0.331 par
        # ghus gaya tha. Ab anchors phrase-level hain.
        anchors=("neural network", "language model", "machine learning",
                 "deep learning", "training", "benchmark", "accuracy",
                 "dataset", "gradient", "transformer", "quantization",
                 "quantisation", "perplexity", "fine tuning", "inference latency",
                 "gpu", "parameter count", "algorithm", "model"),
        branches=_CS_BRANCHES,
        connectors=("arxiv", "openalex", "semantic_scholar", "crossref") + ML_DATA,
        avoid_connectors=("who_gho", "pubmed"),
        # 2026-08-21: strict=False ka matlab tha ki is field mein koi bhi source
        # hard-reject hi nahi hota tha.
        strict=True,
        shared_anchors=("model", "training", "accuracy", "dataset", "parameter",
                        "algorithm"),
    ),
    DomainProfile(
        key="energy_climate",
        label="energy / climate",
        triggers=("energy", "emission", "climate", "renewable", "solar",
                  "wind power", "carbon", "grid", "fossil", "nuclear power",
                  "hydrogen economy", "warming", "battery storage",
                  "grid storage", "lcoe", "kwh", "decarbonis", "decarboniz",
                  "pumped hydro", "net zero"),
        anchors=("emission", "carbon", "climate", "renewable", "grid",
                 "kwh", "mwh", "gwh", "lcoe", "photovoltaic", "wind turbine",
                 "battery storage", "pumped hydro", "capacity factor",
                 "life cycle assessment", "energy", "capacity", "efficiency",
                 "fuel"),
        branches=_ENERGY_BRANCHES,
        connectors=SCHOLARLY + ECON_DATA + BOOKS,
        strict=True,
        shared_anchors=("energy", "capacity", "efficiency", "fuel", "grid"),
    ),
    DomainProfile(
        key="economics",
        label="economics / finance / policy data",
        triggers=("gdp", "inflation", "market", "economy", "economic", "trade",
                  "tax", "unemployment", "investment", "price", "revenue",
                  "budget",
                  # 2026-08-21: labour-market vocabulary missing thi, isliye
                  # minimum-wage ka sawaal `generic` gir jaata tha.
                  "wage", "minimum wage", "employment", "labour", "labor",
                  "poverty", "inequality", "monetary policy", "fiscal",
                  "subsidy", "elasticity", "firm", "household income",
                  "informal sector",
                  # finance side (profile ka label "economics / finance" kehta
                  # hai, par vocabulary nahi thi — isliye ek option-pricing
                  # paper ko koi field claim hi nahi karta tha).
                  "volatility", "option pricing", "asset", "portfolio",
                  "stock market", "interest rate", "bond yield", "financial",
                  "derivative pricing", "black scholes"),
        anchors=("gdp", "inflation", "price", "pricing", "market", "growth",
                 "income", "employment", "unemployment", "wage",
                 "minimum wage", "elasticity", "labour", "labor", "firm",
                 "poverty", "inequality", "tax", "subsidy", "investment",
                 "trade", "difference in differences", "cost", "volatility",
                 "asset", "portfolio", "interest rate", "option"),
        branches=_ECON_BRANCHES,
        connectors=("openalex", "crossref", "semantic_scholar") + ECON_DATA + BOOKS,
        avoid_connectors=("arxiv", "pubmed", "who_gho"),
        strict=True,
        shared_anchors=("price", "market", "growth", "cost", "firm", "trade",
                        "wage", "investment"),
    ),
    DomainProfile(
        key="chemistry",
        label="chemistry",
        triggers=("reaction", "molecule", "compound", "synthesis", "catalysis",
                  "polymer", "solvent", "organic chemistry", "spectroscopy"),
        anchors=("reaction", "molecule", "compound", "synthesis", "catalyst",
                 "yield", "solvent", "bond", "spectra", "polymer"),
        branches=_CHEM_BRANCHES,
        connectors=SCHOLARLY + ("zenodo",) + BOOKS,
        strict=True,
        shared_anchors=("yield", "bond", "synthesis"),
    ),
    DomainProfile(
        key="space",
        label="astronomy / space science",
        triggers=("galaxy", "planet", "telescope", "orbit", "cosmology",
                  "spacecraft", "exoplanet", "black hole", "supernova"),
        anchors=("galaxy", "star", "planet", "orbit", "telescope", "redshift",
                 "cosmic", "spectrum", "luminosity", "mission"),
        branches=_SPACE_BRANCHES,
        connectors=("arxiv", "openalex", "semantic_scholar", "crossref") + BOOKS,
        avoid_connectors=("who_gho", "pubmed", "world_bank"),
        strict=True,
        shared_anchors=("mission", "spectrum"),
    ),
    # ── 2026-08-21: do naye profiles. Cross-domain benchmark mein engineering
    # aur archaeology ke sawaal `generic` par gir rahe the (confidence 0,
    # strict off) — yaani in do fields mein off-topic kachra reject hi nahi
    # hota tha aur query expansion domain-specific nahi tha.
    DomainProfile(
        key="engineering",
        label="mechanical / electrical engineering",
        triggers=("bearing", "gearbox", "motor", "pump", "turbine blade",
                  "vibration", "predictive maintenance", "condition monitoring",
                  "fatigue", "induction motor", "transformer winding",
                  "inverter", "drive", "mechanical", "electrical machine",
                  "failure mode", "maintenance", "rotor", "stator", "shaft",
                  "lubrication", "torque", "gear", "actuator", "plc"),
        anchors=("bearing", "gearbox", "motor", "rotor", "stator", "shaft",
                 "vibration", "fatigue", "wear", "lubrication", "torque",
                 "condition monitoring", "predictive maintenance",
                 "fault detection", "failure mode", "rpm", "kilowatt",
                 "winding", "inverter", "accelerometer", "spectrum kurtosis",
                 "load", "efficiency", "maintenance"),
        branches=_ENG_BRANCHES,
        connectors=("openalex", "crossref", "semantic_scholar", "arxiv") + BOOKS,
        avoid_connectors=("who_gho", "pubmed", "world_bank", "data_gov_in"),
        strict=True,
        shared_anchors=("load", "efficiency", "maintenance", "spectrum",
                        "wear"),
    ),
    DomainProfile(
        key="archaeology_history",
        label="archaeology / history",
        triggers=("archaeolog", "archeolog", "excavation", "radiocarbon",
                  "stratigraphy", "harappan", "indus valley", "mohenjo",
                  "artefact", "artifact", "pottery", "bronze age",
                  "iron age", "neolithic", "civilisation", "civilization",
                  "ancient", "historiography", "inscription", "palaeoclimate",
                  "paleoclimate", "settlement", "bce", "bc era", "dynasty"),
        anchors=("excavation", "radiocarbon", "stratigraphy", "chronology",
                 "artefact", "artifact", "pottery", "ceramic", "seal",
                 "settlement", "site", "bce", "harappan", "indus",
                 "palaeoclimate", "paleoclimate", "monsoon", "isotope",
                 "sediment", "inscription", "archaeological", "layer",
                 "occupation", "abandonment"),
        branches=_ARCH_BRANCHES,
        connectors=("openalex", "crossref", "semantic_scholar") + BOOKS
        + ("internet_archive",),
        avoid_connectors=("arxiv", "pubmed", "who_gho", "huggingface"),
        strict=True,
        shared_anchors=("site", "layer", "isotope", "sediment", "monsoon",
                        "settlement"),
    ),
)

GENERIC = DomainProfile(
    key="generic",
    label="general / mixed",
    triggers=(),
    anchors=(),
    connectors=(),
    strict=False,
)

_BY_KEY = {p.key: p for p in PROFILES}


def profile_by_key(key: str) -> Optional[DomainProfile]:
    return _BY_KEY.get((key or "").strip().lower())


# ── source-level verdict ─────────────────────────────────────────────────────
@dataclass
class SourceVerdict:
    """Ek source par domain ka faisla — poori wajah ke saath (chupchaap nahi)."""
    anchor_hits: int = 0
    anchor_terms: List[str] = field(default_factory=list)
    title_anchor_hits: int = 0
    exclusive_anchor_hits: int = 0
    branch_keys: List[str] = field(default_factory=list)
    focus_branch_hits: int = 0
    rival_domain: str = ""
    rival_hits: int = 0
    rival_field_domain: str = ""
    rival_field_hits: int = 0
    rejected: bool = False
    reason: str = ""

    @property
    def branch_count(self) -> int:
        return len(self.branch_keys)

    def to_dict(self) -> Dict:
        return {
            "anchor_hits": self.anchor_hits,
            "anchor_terms": self.anchor_terms[:6],
            "title_anchor_hits": self.title_anchor_hits,
            "exclusive_anchor_hits": self.exclusive_anchor_hits,
            "branches": list(self.branch_keys),
            "focus_branch_hits": self.focus_branch_hits,
            "rival_domain": self.rival_domain,
            "rival_hits": self.rival_hits,
            "rival_field_domain": self.rival_field_domain,
            "rival_field_hits": self.rival_field_hits,
            "rejected": self.rejected,
            "reason": self.reason,
        }


@dataclass
class DomainPlan:
    """
    Ek sawaal ka domain plan. Discovery se PEHLE banta hai (§3) aur uske baad
    relevance (§2/§5), query expansion (§4) aur fallback planner (§15) sab isi
    ek object se poochte hain — do jagah do alag samajh na bane.
    """
    question: str
    profile: DomainProfile
    confidence: int = 0
    rivals: Tuple[DomainProfile, ...] = ()
    focus_keys: Tuple[str, ...] = ()

    # ── basic info ──
    @property
    def key(self) -> str:
        return self.profile.key

    @property
    def is_known(self) -> bool:
        return self.profile.key != "generic"

    @property
    def strict(self) -> bool:
        return self.profile.strict and self.is_known

    def anchors(self) -> Tuple[str, ...]:
        return self.profile.anchors

    def branches(self) -> Tuple[Branch, ...]:
        return self.profile.branches

    def focus_branches(self) -> Tuple[Branch, ...]:
        keys = set(self.focus_keys)
        return tuple(b for b in self.profile.branches if b.key in keys)

    def sub_domains(self) -> List[str]:
        return [b.label for b in (self.focus_branches() or self.profile.branches)]

    def subject_anchors(self) -> Tuple[str, ...]:
        """
        Sawaal ne KHUD jo field-vocabulary naam liya hai.

        Kyun zaroori: profile ke general anchors har sach ko cover nahi karte.
        "diabetes ka permanent ilaj" par medicine anchors (patient, clinical,
        trial, mortality...) mein se ek bhi "Diabetes remission after dietary
        intervention" ke title mein nahi hai — yaani asli, sahi paper hard
        rejection mein mara jaata tha.

        Fix: profile ke TRIGGERS mein se wo shabd jo sawaal mein aaye hain
        (yahan "diabetes") bhi anchor maane jaate hain. Ye dheela nahi hai —
        shabd profile ki apni vocabulary se aata hai, sawaal se aur field se
        dono se juda hota hai. Superconductivity ke sawaal mein "room" aur
        "temperature" trigger nahi hain, isliye room-temperature
        FERROELECTRICITY is raaste se bhi andar nahi aa sakti.
        """
        bag = stems(self.question)
        subs = [t for t in self.profile.triggers if phrase_hit(t, bag)]
        return tuple(subs)

    def effective_anchors(self) -> Tuple[str, ...]:
        """profile anchors + sawaal ke subject anchors (dedup, order bani rehti hai)."""
        out: List[str] = list(self.profile.anchors)
        for t in self.subject_anchors():
            if t not in out:
                out.append(t)
        return tuple(out)

    def describe(self) -> str:
        if not self.is_known:
            return "domain: general (koi specific field profile match nahi hua)"
        subs = ", ".join(b.key for b in self.focus_branches()) or "poora field"
        return f"domain: {self.profile.label}; sub-domains: {subs}"

    # ── §2/§5: ek source ka domain-level faisla ──────────────────────────────
    def assess(self, title: str = "", body: str = "",
               extra: str = "") -> SourceVerdict:
        """
        HARD REJECTION stage. Sirf keyword overlap se koi source bach nahi
        sakta — field ka anchor chahiye.

        Do rule (strict field ke liye):
          1. anchor 0                       →  REJECT.
          2. sirf SHARED anchor mile aur
             kisi rival field ke nishaan
             saaf zyada hon                 →  REJECT (2026-08-21).

        Rule 2 kyun aaya: cross-domain benchmark mein "Critical temperature of
        protein folding transitions" superconductivity ke pack mein 0.556 par
        ghus gaya, sirf isliye ki "critical temperature" / "transition
        temperature" dono fields ki imaandaar vocabulary hai. Waise hi ek
        stochastic-volatility FINANCE paper cs_ml mein "model" + "accuracy" par
        aa gaya. In dono mein field ka EXCLUSIVE anchor ek bhi nahi tha, aur
        rival field ki poori vocabulary maujood thi. Wahi ab reject ki wajah
        hai — aur wajah likhi jaati hai, chupchaap drop nahi hota.

        Anchor mile to branch coverage naapte hain: source kis sub-question
        mein madad karta hai.
        """
        v = SourceVerdict()
        if not self.is_known:
            return v

        title_bag = stems(title)
        full_bag = title_bag | stems(body) | stems(extra)

        anchors = self.effective_anchors()
        v.anchor_terms = matched(anchors, full_bag)
        v.anchor_hits = len(v.anchor_terms)
        v.title_anchor_hits = count_hits(anchors, title_bag)

        # Sirf wo anchors jo IS field ke apne hain (shared nahi). Sawaal ka apna
        # subject anchor ("diabetes", "bt cotton") bhi exclusive gina jaata hai —
        # wo sawaal aur field dono se juda hai.
        shared = set(self.profile.shared_anchors)
        exclusive_terms = [a for a in v.anchor_terms if a not in shared]
        v.exclusive_anchor_hits = len(exclusive_terms)

        focus = set(self.focus_keys)
        for b in self.profile.branches:
            if b.hits(full_bag):
                v.branch_keys.append(b.key)
                if b.key in focus:
                    v.focus_branch_hits += 1

        best_rival, best_hits = "", 0
        best_rival_field, best_field_hits = "", 0
        for other in PROFILES:
            if other.key == self.profile.key:
                continue
            hits = other.trigger_hits(full_bag)
            # apne field ke anchors doosre profile ke trigger bhi ho sakte hain;
            # rival tab hi maayne rakhta hai jab hamare anchor GAYAB hon.
            if hits > best_hits:
                best_rival, best_hits = other.key, hits
            # Rival ki poori taakat naapne ke liye trigger + anchor dono —
            # sirf trigger ginne par biology ka paper "1 hit" dikhta tha
            # jabki uske paas poori vocabulary thi.
            fhits = other.field_hits(full_bag)
            if fhits > best_field_hits:
                best_rival_field, best_field_hits = other.key, fhits
        v.rival_domain, v.rival_hits = best_rival, best_hits
        v.rival_field_domain, v.rival_field_hits = best_rival_field, best_field_hits

        if self.strict and v.anchor_hits == 0:
            v.rejected = True
            if best_hits >= 1:
                v.reason = (f"domain mismatch — ye source '{best_rival}' field ka "
                            f"lagta hai, {self.profile.label} ka koi anchor "
                            f"(jaise {', '.join(self.profile.anchors[:3])}) "
                            f"iske title/text mein nahi hai")
            else:
                v.reason = (f"{self.profile.label} ka koi domain anchor nahi mila "
                            f"— sirf aam shabd match hue")
        elif (self.strict and v.exclusive_anchor_hits == 0
                and v.anchor_hits > 0 and best_field_hits >= 2):
            v.rejected = True
            v.reason = (
                f"shared-vocabulary overlap — is source mein "
                f"{self.profile.label} ka sirf saanjha shabd "
                f"({', '.join(v.anchor_terms[:3])}) mila, is field ka apna koi "
                f"anchor nahi; iske badle '{best_rival_field}' field ki "
                f"vocabulary saaf zyada hai ({best_field_hits} match). "
                f"Keyword milna field milna nahi hota")
        return v

    # ── §3: connector routing ────────────────────────────────────────────────
    def route(self, candidates: Sequence[str], kind: str = "") -> Tuple[List[str], List[str]]:
        """
        (rakhne wale, hataye gaye) — domain ke hisaab se connector chunno.

        Jo connector is field ke liye bekaar hai (superconductivity ke liye
        who_gho) wo yahin nikal jaata hai: na API call, na noise, na waqt.
        Agar profile unknown hai to kuch nahi hatta — bina samajh ke connector
        band karna research ko andha kar dega.
        """
        keep, dropped = [], []
        if not self.is_known:
            return list(candidates), dropped
        prefer = set(self.profile.connectors)
        avoid = set(self.profile.avoid_connectors)
        for name in candidates:
            if name in avoid and name not in prefer:
                dropped.append(name)
            else:
                keep.append(name)
        if prefer:
            keep.sort(key=lambda n: (n not in prefer, list(candidates).index(n)))
        if not keep:                    # kabhi bhi sab band nahi karna
            keep, dropped = list(candidates), []
        return keep, dropped

    def routing_note(self, dropped: Sequence[str]) -> str:
        if not dropped:
            return ""
        return (f"{self.profile.label} ke liye ye connectors jaan-boojh kar "
                f"skip kiye gaye: {', '.join(sorted(set(dropped)))} "
                f"(is field mein inka data matlab nahi rakhta)")

    # ── §4/§15: structured query expansion (LLM ke bina bhi) ────────────────
    def anchor_phrase(self) -> str:
        """Broadening ke waqt bhi ye phrase kabhi nahi girta."""
        if not self.is_known or not self.profile.anchors:
            return ""
        return self.profile.anchors[0]

    def query_anchors(self, text: str = "", limit: int = 2,
                      fallback: bool = True) -> List[str]:
        """
        Is query mein maujood domain anchors — SEARCH ke liye ready shabd.

        Kyun: arXiv ladder jab query dheeli karta hai to wo query ka PEHLA
        content term rakh leta tha. "room-temperature superconductivity" par
        pehla term "room-temperature" tha, yaani aakhri step
        `all:"room-temperature"` ban gaya aur arXiv ne room-temperature
        FERROELECTRICITY laa di. Anchor kabhi girna nahi chahiye (§4).

        Pehle wo anchor jo query mein LITERALLY hai ("superconductor"), phir
        stem se match hone wale ("superconduct"). Query mein ek bhi anchor na
        ho to field ka default anchor.
        """
        src = text or self.question
        if not self.is_known:
            return []
        bag = stems(src)
        toks = set(tokens(src))
        for t in list(toks):
            if "-" in t:
                toks.update(p for p in t.split("-") if len(p) > 2)
        low = " ".join((src or "").lower().split())

        exact: List[str] = []
        loose: List[str] = []
        # Sawaal ka apna subject pehle ("cuprate", "diabetes"), general field
        # anchor baad mein ("treatment") — collapse hone par bhi query ka matlab
        # bacha rahe.
        candidates: List[str] = list(self.subject_anchors())
        for a in self.profile.anchors:
            if a not in candidates:
                candidates.append(a)
        for a in candidates:
            if (a in low) if " " in a else (a in toks):
                exact.append(a)
            elif phrase_hit(a, bag):
                loose.append(a)
        # Ek hi shabd ke roop mat dohrao. "superconductivity" query mein hai,
        # to `all:"superconduct"` bhi bhejna nuksaan hai — adhoora shabd phrase
        # search mein 0 result deta hai. Isliye stem par dedupe, aur exact
        # (jaisa query mein likha hai) wala roop jeetta hai.
        out: List[str] = []
        seen_stems: Set[str] = set()
        for a in exact + loose:
            key = " ".join(stem(p) for p in a.split())
            if key in seen_stems:
                continue
            seen_stems.add(key)
            out.append(a)
        if not out:
            ap = self.anchor_phrase() if fallback else ""
            out = [ap] if ap else []
        return out[: max(1, limit)]

    def _ordered_branches(self) -> List[Branch]:
        """
        Search angles ka kram: pehle wo jo sawaal ne khud chhua (focus), phir
        `must` wale reserved angles (replication/retraction jaise — inhe kaatna
        research ki galti hai), phir field ke baaki angles.
        """
        focus = list(self.focus_branches())
        focus_keys = {b.key for b in focus}
        must = [b for b in self.profile.branches
                if b.must and b.key not in focus_keys]
        rest = [b for b in self.profile.branches
                if b.key not in focus_keys and not b.must]
        return focus + must + rest

    def expanded_queries(self, base: str, limit: int = 9) -> List[str]:
        """
        Ek sawaal se kai research-specific queries. Focus branches pehle,
        phir reserved (`must`) angles, phir baaki field. Har query mein domain
        anchor rehta hai.
        """
        out: List[str] = []
        seen: Set[str] = set()

        def add(q: str) -> None:
            q = " ".join((q or "").split())
            if not q:
                return
            key = q.lower()
            if key not in seen:
                seen.add(key)
                out.append(q)

        add(base)
        for b in self._ordered_branches():
            add(b.query)
        return out[:limit]

    # ── search intents (ek sawaal, kai alag literatures) ────────────────────
    def search_intents(self, base: str = "", limit: int = 8) -> List[Dict]:
        """
        Ek research SAWAAL ke andar kai alag SEARCH INTENT hote hain, aur unki
        literature alag-alag jagah rehti hai.

        Superconductivity ka hi sawaal lo: "Tc kitna hai" (condensed-matter
        physics), "kitna current le jaa sakta hai" (applied superconductivity /
        transport), "grid par laga sakte hain kya" (power engineering),
        "computing mein kya fayda" (quantum hardware). Ek hi generic query in
        chaaron ko nahi la sakti — pehle wahi ho raha tha, isliye report ek hi
        tarah ke papers se bhari hoti thi.

        Ab har intent apni query, apne terms aur apne useful connectors ke saath
        alag mile. Jo intent sawaal ne khud chhua hai (focus branch) wo pehle
        aata hai, phir field ke baaki intents — taaki coverage bane, aur report
        mein saaf likha ja sake ki kis intent par kya mila. Sab deterministic
        hai: ek bhi LLM call nahi (§15).
        """
        if not self.is_known:
            base_q = " ".join((base or self.question or "").split())
            return ([{"key": "general", "label": "general search",
                      "query": base_q, "terms": [],
                      "connectors": list(self.profile.connectors),
                      "focus": True}] if base_q else [])

        focus_keys = {b.key for b in self.focus_branches()}
        ordered = self._ordered_branches()

        anchor = self.anchor_phrase()
        intents: List[Dict] = []
        seen: Set[str] = set()
        for branch in ordered:
            query = " ".join((branch.query or branch.label or "").split())
            if not query:
                continue
            # Anchor kabhi nahi girta — yahi §4 ka asli sabak hai. "power grid
            # demonstration" akela search karne par superconductivity ka koi
            # rishta hi nahi bachta.
            if anchor and anchor.lower() not in query.lower():
                query = f"{query} {anchor}"
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            intents.append({
                "key": branch.key,
                "label": branch.label,
                "query": query,
                "terms": list(branch.terms[:6]),
                "connectors": list(self.profile.connectors),
                "focus": branch.key in focus_keys,
            })
            if len(intents) >= max(1, limit):
                break
        if not intents:
            # Defensive: agar kabhi koi naya profile branches ke bina add ho
            # jaaye to bhi search intents khaali nahi jaani chahiye — warna
            # poora research ek hi generic query par tik jaata hai (yahi
            # 2026-08-21 ke cross-domain benchmark mein 7 fields ke saath hua).
            base_q = " ".join((base or self.question or "").split())
            anchor_q = anchor or ""
            if base_q or anchor_q:
                intents.append({
                    "key": "general",
                    "label": f"{self.profile.label} general search",
                    "query": (base_q or anchor_q),
                    "terms": list(self.profile.anchors[:6]),
                    "connectors": list(self.profile.connectors),
                    "focus": True,
                })
        return intents

    def intent_note(self, intents: Optional[Sequence[Dict]] = None) -> str:
        """Report/audit ke liye ek line — kaun-kaun se intents par search hui."""
        items = list(intents if intents is not None else self.search_intents())
        if not items:
            return ""
        focused = [i["label"] for i in items if i.get("focus")]
        rest = [i["label"] for i in items if not i.get("focus")]
        bits = [f"{self.profile.label} ke {len(items)} alag search intents par "
                f"search hui"]
        if focused:
            bits.append("sawaal ne khud jo maanga: " + ", ".join(focused))
        if rest:
            bits.append("coverage ke liye: " + ", ".join(rest[:6]))
        return "; ".join(bits)

    def fallback_queries(self, base: str, round_no: int = 2,
                         limit: int = 4) -> List[str]:
        """
        §15 — deterministic planner. Reasoning model mar gaya ho to bhi round
        2/3 ke liye safe, domain-specific queries milte hain.
        """
        pool = self.expanded_queries(base, limit=12)[1:] or [base]
        start = ((round_no - 1) * limit) % max(1, len(pool))
        rotated = pool[start:] + pool[:start]
        return rotated[:limit]

    def to_dict(self) -> Dict:
        intents = self.search_intents()
        return {
            "domain": self.profile.key,
            "domain_label": self.profile.label,
            "confidence": self.confidence,
            "strict": self.strict,
            "sub_domains": [b.key for b in self.focus_branches()],
            "all_branches": [b.key for b in self.profile.branches],
            "search_intents": [{"key": i["key"], "label": i["label"],
                                "query": i["query"], "focus": i["focus"]}
                               for i in intents],
            "intent_note": self.intent_note(intents),
            "anchors": list(self.profile.anchors[:10]),
            "preferred_connectors": list(self.profile.connectors),
            "avoid_connectors": list(self.profile.avoid_connectors),
            "useful_source_types": list(self.profile.source_types),
            "rivals": [p.key for p in self.rivals],
        }


# ── detection ────────────────────────────────────────────────────────────────
def detect(question: str) -> DomainPlan:
    """
    Sawaal se domain nikalo. Sabse zyada trigger match jeetta hai; tie par
    zyada specific (pehle likha hua) profile jeetta hai — isliye
    "superconductivity" PROFILES mein "materials_physics" se pehle hai.
    """
    bag = stems(question)
    scored: List[Tuple[int, int, DomainProfile]] = []
    for idx, prof in enumerate(PROFILES):
        hits = prof.trigger_hits(bag)
        if hits:
            scored.append((hits, -idx, prof))
    if not scored:
        return DomainPlan(question=question, profile=GENERIC, confidence=0)

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best_hits, _, best = scored[0]
    rivals = tuple(p for _, _, p in scored[1:4])

    focus: List[str] = []
    for b in best.branches:
        if b.hits(bag):
            focus.append(b.key)

    return DomainPlan(question=question, profile=best, confidence=best_hits,
                      rivals=rivals, focus_keys=tuple(focus))


@lru_cache(maxsize=256)
def anchor_terms(question: str, limit: int = 2,
                 fallback: bool = False) -> Tuple[str, ...]:
    """
    Connectors ke liye seedha helper: is query ke domain anchors.

    `fallback=False` default hai — search query banate waqt field ka DEFAULT
    anchor ghusaana nuksaan karta hai ("diabetes ka ilaj" par
    `all:"patient"` chalna `all:"diabetes"` se bura hai). Sirf wahi anchor
    jaata hai jo query mein sach mein hai.
    """
    return tuple(detect(question or "").query_anchors(
        question or "", limit=limit, fallback=fallback))
