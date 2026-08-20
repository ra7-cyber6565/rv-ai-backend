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
    """
    key: str
    label: str
    terms: Tuple[str, ...]
    query: str = ""

    def hits(self, bag: Set[str]) -> int:
        return count_hits(self.terms, bag)


@dataclass(frozen=True)
class DomainProfile:
    """
    Ek field ka poora profile. `strict=True` ka matlab: is field mein anchor ke
    bina source ho hi nahi sakta, isliye anchor-less source HARD REJECT hoga.
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

    def trigger_hits(self, bag: Set[str]) -> int:
        return count_hits(self.triggers, bag)

    def anchor_hits(self, bag: Set[str]) -> int:
        return count_hits(self.anchors, bag)


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
           "superconductivity pairing mechanism theory"),
    Branch("controversy", "controversial claims / replication / retraction",
           ("replication", "retraction", "retracted", "irreproducible",
            "reanalysis", "dispute", "misconduct", "lk 99", "dias"),
           "room temperature superconductor replication retraction controversy"),
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
)

_SC_ANCHORS = (
    "superconduct", "superconductor", "superconductivity", "superconducting",
    "tc", "critical temperature", "transition temperature", "cooper pair",
    "meissner", "bcs", "hydride", "cuprate", "nickelate", "pnictide",
    "josephson", "flux pinning", "critical current", "supercurrent",
    "zero resistance", "diamagnetism", "lk 99", "mgb2", "ybco",
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
    ),
    DomainProfile(
        key="materials_physics",
        label="materials science / applied physics",
        triggers=("material", "alloy", "crystal", "semiconductor", "graphene",
                  "perovskite", "thin film", "nanomaterial", "composite",
                  "ferroelectric", "battery", "photovoltaic", "catalyst"),
        anchors=("material", "alloy", "crystal", "lattice", "phase", "film",
                 "synthesis", "microstructure", "diffraction", "band gap",
                 "conductivity", "dielectric", "composite", "nanoparticle"),
        connectors=SCHOLARLY + ("zenodo",) + BOOKS,
        avoid_connectors=("who_gho", "world_bank"),
        strict=True,
    ),
    DomainProfile(
        key="medicine_health",
        label="medicine / public health",
        triggers=("disease", "patient", "clinical", "therapy", "treatment",
                  "mortality", "maternal", "vaccine", "cancer", "diabetes",
                  "epidemiology", "symptom", "drug", "surgery", "health",
                  "infection", "prosthetic", "sunbed", "screening programme"),
        anchors=("patient", "clinical", "trial", "cohort", "mortality",
                 "incidence", "prevalence", "diagnosis", "treatment", "therapy",
                 "dose", "outcome", "morbidity", "vaccine", "disease"),
        connectors=BIOMED + HEALTH_DATA + BOOKS,
        strict=True,
    ),
    DomainProfile(
        key="biology_genetics",
        label="biology / genetics",
        triggers=("gene", "genome", "protein", "cell", "enzyme", "dna", "rna",
                  "species", "microbiome", "evolution", "crispr", "plant",
                  "fibre", "fiber", "biocomposite"),
        anchors=("gene", "genome", "protein", "cell", "enzyme", "sequence",
                 "expression", "mutation", "species", "tissue", "organism"),
        connectors=BIOMED + ("zenodo",) + BOOKS,
        strict=True,
    ),
    DomainProfile(
        key="cs_ml",
        label="computer science / machine learning",
        triggers=("algorithm", "neural", "machine learning", "transformer",
                  "llm", "software", "dataset", "benchmark", "model",
                  "reinforcement", "computer vision", "nlp"),
        anchors=("algorithm", "model", "training", "accuracy", "benchmark",
                 "neural", "network", "dataset", "inference", "gradient",
                 "transformer", "parameter"),
        connectors=("arxiv", "openalex", "semantic_scholar", "crossref") + ML_DATA,
        avoid_connectors=("who_gho", "pubmed"),
        strict=False,
    ),
    DomainProfile(
        key="energy_climate",
        label="energy / climate",
        triggers=("energy", "emission", "climate", "renewable", "solar",
                  "wind power", "carbon", "grid", "fossil", "nuclear power",
                  "hydrogen economy", "warming"),
        anchors=("energy", "emission", "carbon", "climate", "renewable",
                 "capacity", "grid", "fuel", "efficiency", "temperature rise"),
        connectors=SCHOLARLY + ECON_DATA + BOOKS,
        strict=False,
    ),
    DomainProfile(
        key="economics",
        label="economics / finance / policy data",
        triggers=("gdp", "inflation", "market", "economy", "trade", "tax",
                  "unemployment", "investment", "price", "revenue", "budget"),
        anchors=("gdp", "inflation", "price", "market", "growth", "income",
                 "cost", "employment", "trade", "investment", "tax"),
        connectors=("openalex", "crossref", "semantic_scholar") + ECON_DATA + BOOKS,
        avoid_connectors=("arxiv", "pubmed", "who_gho"),
        strict=False,
    ),
    DomainProfile(
        key="chemistry",
        label="chemistry",
        triggers=("reaction", "molecule", "compound", "synthesis", "catalysis",
                  "polymer", "solvent", "organic chemistry", "spectroscopy"),
        anchors=("reaction", "molecule", "compound", "synthesis", "catalyst",
                 "yield", "solvent", "bond", "spectra", "polymer"),
        connectors=SCHOLARLY + ("zenodo",) + BOOKS,
        strict=True,
    ),
    DomainProfile(
        key="space",
        label="astronomy / space science",
        triggers=("galaxy", "planet", "telescope", "orbit", "cosmology",
                  "spacecraft", "exoplanet", "black hole", "supernova"),
        anchors=("galaxy", "star", "planet", "orbit", "telescope", "redshift",
                 "cosmic", "spectrum", "luminosity", "mission"),
        connectors=("arxiv", "openalex", "semantic_scholar", "crossref") + BOOKS,
        avoid_connectors=("who_gho", "pubmed", "world_bank"),
        strict=True,
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
    branch_keys: List[str] = field(default_factory=list)
    focus_branch_hits: int = 0
    rival_domain: str = ""
    rival_hits: int = 0
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
            "branches": list(self.branch_keys),
            "focus_branch_hits": self.focus_branch_hits,
            "rival_domain": self.rival_domain,
            "rival_hits": self.rival_hits,
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

        Rule (strict field ke liye):
          anchor 0  →  REJECT. Wajah saath likhi jaati hai.
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

        focus = set(self.focus_keys)
        for b in self.profile.branches:
            if b.hits(full_bag):
                v.branch_keys.append(b.key)
                if b.key in focus:
                    v.focus_branch_hits += 1

        best_rival, best_hits = "", 0
        for other in PROFILES:
            if other.key == self.profile.key:
                continue
            hits = other.trigger_hits(full_bag)
            # apne field ke anchors doosre profile ke trigger bhi ho sakte hain;
            # rival tab hi maayne rakhta hai jab hamare anchor GAYAB hon.
            if hits > best_hits:
                best_rival, best_hits = other.key, hits
        v.rival_domain, v.rival_hits = best_rival, best_hits

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

    def expanded_queries(self, base: str, limit: int = 9) -> List[str]:
        """
        Ek sawaal se kai research-specific queries. Focus branches pehle,
        phir baaki field. Har query mein domain anchor rehta hai.
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
        for b in self.focus_branches():
            add(b.query)
        for b in self.profile.branches:
            add(b.query)
        return out[:limit]

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
        return {
            "domain": self.profile.key,
            "domain_label": self.profile.label,
            "confidence": self.confidence,
            "strict": self.strict,
            "sub_domains": [b.key for b in self.focus_branches()],
            "all_branches": [b.key for b in self.profile.branches],
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
