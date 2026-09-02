"""
§5 — evidence axes: ek sawaal ke andar chhupe alag-alag SABOOT ke raaste.

Kyun ye file bani (dark-matter run ka asli sabak):
    ek broad query — "dark matter evidence" — se 18 source aaye, jinme TESS,
    Swift, WISE aur exoplanet ke paper the, aur wo saboot jinke bina dark matter
    ka jawab adhoora hai (CMB, BBN, Bullet Cluster, lensing, large-scale
    structure, dwarf galaxies, direct detection) ek bhi nahi tha. Ginti 18 thi,
    coverage lagbhag zero. Isliye ab retrieval ka hisaab "kitne source mile" se
    nahi, "kaun-kaun sa saboot ka raasta cover hua" se hota hai.

Teen cheezein ye module deta hai:
    1. `axes_for(question)`  — is sawaal ke mandatory evidence axes
    2. `Axis.ladder(base)`   — har axis par 6-step retry ladder (§5)
    3. `coverage(...)`       — per-axis status, aur "search hi nahi hua" ko
                               "search hua par kuch nahi mila" se ALAG rakhta hai

Imaandaari ka niyam: axis par relevant source na mile to use MISSING likha
jaata hai. Kisi bhi haalat mein irrelevant source se axis "bhara" nahi jaata —
wahi galti pichhli report mein "18 sources" ban gayi thi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .domain import count_hits, matched, stems, tokens

# ── axis status (sirf ye chaar) ───────────────────────────────────────────────
AXIS_COVERED = "COVERED"            # kam se kam 1 relevant source
AXIS_WEAK = "WEAK"                  # source mila par relevance floor se neeche
AXIS_MISSING = "MISSING"            # search hui, kuch nahi mila
AXIS_NOT_SEARCHED = "NOT SEARCHED"  # is axis par query hi nahi gayi (unknown)
AXIS_STATUSES: Tuple[str, ...] = (AXIS_COVERED, AXIS_WEAK, AXIS_MISSING,
                                  AXIS_NOT_SEARCHED)

AXIS_STATUS_EXPLAIN: Dict[str, str] = {
    AXIS_COVERED: "is raaste ka relevant source mila",
    AXIS_WEAK: "kuch mila par topic se seedha jud nahi raha — isse saboot "
               "nahi maana ja sakta",
    AXIS_MISSING: "dhoondha gaya, par is raaste ka koi relevant source nahi mila",
    AXIS_NOT_SEARCHED: "is raaste par search hi nahi hui (ye 'kuch nahi mila' "
                       "se alag baat hai)",
}

# §5 ka retry ladder — jab axis par kuch na mile to isi kram se dobara koshish.
# Naam bhi record hote hain, taaki report bata sake kahan tak koshish hui.
LADDER_STEPS: Tuple[Tuple[str, str], ...] = (
    ("exact", "axis ki exact terminology"),
    ("synonym", "wahi baat doosre shabdon mein"),
    ("entity", "named mission / experiment / dataset"),
    ("primary", "primary research paper (review nahi)"),
    ("review_to_primary", "review se primary paper ka raasta"),
    ("counter", "negative / counter-evidence query"),
)


def _tidy_query(query: str, limit: int = 200) -> str:
    """
    Query se dohraye gaye shabd hata do (base + axis query mein topic do baar
    aa jaata hai) aur lambai baandh do — koi bhi free API lambi query par
    kharab jawab deti hai.
    """
    seen: Set[str] = set()
    words: List[str] = []
    for word in (query or "").split():
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
    return " ".join(words)[:limit].strip()


@dataclass(frozen=True)
class Axis:
    """
    Ek saboot ka raasta. `terms` mein se kuch mile to source is axis par "kaam
    kar raha hai". `query` deterministic hai — reasoning model band ho to bhi
    ye axis dhoondha jaata rahega (§15).

    `mandatory=True` = iske bina jawab adhoora hai, aur ledger mein ye kami
    likhi jayegi. `entity` axes (sawaal mein naam liye gaye mission/dataset)
    hamesha mandatory hote hain — user ne khud unka naam liya hai.
    """
    axis_id: str
    label: str
    terms: Tuple[str, ...]
    query: str = ""
    mandatory: bool = True
    why: str = ""
    entity: str = ""

    def hits(self, bag: Set[str]) -> int:
        return count_hits(self.terms, bag)

    def matched_terms(self, bag: Set[str]) -> List[str]:
        return matched(self.terms, bag)

    def base_query(self) -> str:
        return (self.query or " ".join(self.terms[:3])).strip()

    def ladder(self, base: str = "", limit: int = len(LADDER_STEPS)) -> List[Dict]:
        """
        §5 ka 6-step ladder — har step ek ALAG tarah ki koshish hai, wahi query
        chhe baar nahi. `base` sawaal ka saaf roop hai (topic anchor), taaki
        query axis + topic dono se bandhi rahe.
        """
        anchor = " ".join((base or "").split()[:8]).strip()
        axis_q = self.base_query()
        syn = self.terms[3:6] or self.terms[:3]
        ent = self.entity or (self.terms[2] if len(self.terms) > 2 else axis_q)
        steps = [
            ("exact", f"{anchor} {axis_q}".strip()),
            ("synonym", f"{anchor} {' '.join(syn)}".strip()),
            ("entity", f"{ent} {anchor}".strip()),
            ("primary", f"{axis_q} {anchor} measurement observation data".strip()),
            ("review_to_primary", f"{axis_q} {anchor} review".strip()),
            ("counter", f"{axis_q} {anchor} criticism limitations "
                        f"systematic uncertainty".strip()),
        ]
        out: List[Dict] = []
        for idx, (name, query) in enumerate(steps[:max(1, limit)]):
            out.append({"step": idx + 1, "name": name,
                        "what": dict(LADDER_STEPS)[name],
                        "query": _tidy_query(query)})
        return out

    def to_dict(self) -> Dict:
        return {"axis_id": self.axis_id, "label": self.label,
                "mandatory": self.mandatory, "query": self.base_query(),
                "why": self.why, "entity": self.entity,
                "terms": list(self.terms)}


# ── dark matter / cosmology (§5 ka naam-le-kar diya gaya set) ─────────────────
# Ye list benchmark ke liye "cheat" nahi hai: yahi wo saboot ke raaste hain
# jinke bina koi bhi dark-matter review adhoora maana jaata hai, aur pichhla
# answer inme se 7 par ek bhi source laaya hi nahi tha.
_DARK_MATTER_AXES: Tuple[Axis, ...] = (
    Axis("rotation_curves", "galaxy rotation curves",
         ("rotation curve", "flat rotation", "circular velocity",
          "velocity dispersion", "tully fisher", "hi rotation"),
         "galaxy rotation curves flat velocity dark matter",
         why="rotation curve hi wo pehla observation hai jisse missing mass ka "
             "sawaal khada hua"),
    Axis("milky_way_dynamics", "Milky Way dynamics / local mass",
         ("milky way", "galactic rotation", "solar neighbourhood",
          "local dark matter density", "gaia", "circular velocity curve"),
         "milky way rotation curve enclosed mass local dark matter density",
         why="requested calculation isi axis ka hissa hai (v, r se enclosed mass)"),
    Axis("cmb", "CMB / Planck power spectrum",
         ("cmb", "cosmic microwave background", "planck", "acoustic peak",
          "power spectrum", "wmap", "lambda cdm parameters"),
         "cosmic microwave background acoustic peaks dark matter density planck",
         why="CMB peaks se non-baryonic matter ka hissa naapa jaata hai"),
    Axis("bbn", "Big-Bang nucleosynthesis / baryon budget",
         ("nucleosynthesis", "bbn", "baryon density", "deuterium abundance",
          "primordial abundance", "helium abundance"),
         "big bang nucleosynthesis baryon density primordial abundance",
         why="BBN baryon ki kul matra baandh deta hai — missing mass baryonic "
             "nahi ho sakti"),
    Axis("lensing", "gravitational lensing mass maps",
         ("gravitational lensing", "weak lensing", "strong lensing",
          "convergence map", "einstein radius", "shear"),
         "gravitational lensing mass reconstruction dark matter halo",
         why="lensing se mass ka naksha milta hai, roshni se nahi"),
    Axis("bullet_cluster", "colliding clusters (Bullet Cluster)",
         ("bullet cluster", "colliding cluster", "merging cluster",
          "1e0657", "offset between gas and mass", "x-ray gas"),
         "bullet cluster colliding clusters mass gas offset dark matter",
         why="gas aur mass ka alag hona hi wo test hai jo modified gravity ke "
             "liye sabse mushkil hai"),
    Axis("large_scale_structure", "large-scale structure / BAO",
         ("large scale structure", "matter power spectrum", "bao", "lss",
          "baryon acoustic oscillation", "galaxy clustering", "cosmic web"),
         "large scale structure matter power spectrum baryon acoustic oscillations",
         why="structure formation ke bina aaj ki galaxy distribution nahi banti"),
)

_DARK_MATTER_AXES_2: Tuple[Axis, ...] = (
    Axis("dwarf_galaxies", "dwarf galaxies / small-scale tests",
         ("dwarf galaxy", "dwarf spheroidal", "ultra faint", "core cusp",
          "satellite galaxy", "missing satellites"),
         "dwarf spheroidal galaxies dark matter core cusp problem",
         why="chhoti galaxies par hi standard model ki sabse badi dikkat hai"),
    Axis("direct_detection", "direct particle detection",
         ("direct detection", "wimp", "xenon", "lux zeplin", "pandax",
          "nuclear recoil", "spin independent cross section"),
         "dark matter direct detection experiment limits nuclear recoil",
         why="lab mein kan pakadne ki koshish — aur uska ab tak null hona bhi "
             "ek asli nateeja hai"),
    Axis("collider", "collider / beam-dump searches",
         ("collider", "beam dump", "missing energy", "mono jet", "lhc",
          "invisible decay", "fixed target"),
         "collider beam dump search dark matter missing energy limits",
         why="particle side ka doosra raasta — iske limits hypothesis ko kaatte hain"),
    Axis("pbh_microlensing", "primordial black holes — microlensing limits",
         ("primordial black hole", "pbh", "microlensing", "ogle", "subaru hsc",
          "eros", "macho survey", "mass function constraint"),
         "primordial black hole microlensing constraints dark matter fraction",
         why="PBH ko dark matter kehne se pehle microlensing ke limits dekhna "
             "zaroori hai"),
    Axis("pbh_gravitational_waves", "primordial black holes — GW constraints",
         ("gravitational wave", "pbh", "ligo", "virgo", "merger rate",
          "stochastic background", "black hole binary"),
         "primordial black hole gravitational wave merger rate constraints",
         why="PBH ka doosra swatantra test — merger rate se hissa baandha jaata hai"),
    Axis("mond_strengths", "MOND / modified gravity — successes",
         ("mond", "modified newtonian dynamics", "radial acceleration relation",
          "baryonic tully fisher", "a0", "modified gravity success"),
         "MOND radial acceleration relation baryonic tully fisher success",
         why="alternative theory ki sabse mazboot baat bina sunwaayi nahi "
             "chhodni chahiye"),
    Axis("mond_limits", "MOND / modified gravity — cluster & cosmology limits",
         ("mond cluster", "relativistic extension", "tensor vector scalar",
          "cosmology constraint", "cluster mass discrepancy",
          "gravitational wave speed"),
         "MOND limitations galaxy clusters cosmology constraints failure",
         why="wahi theory clusters aur cosmology mein kahan girti hai — dono "
             "taraf ka hisaab"),
    Axis("systematics", "observational & modelling systematics",
         ("systematic uncertainty", "modelling error", "baryonic feedback",
          "inclination correction", "beam smearing", "selection effect",
          "calibration uncertainty"),
         "systematic uncertainties modelling errors mass measurement bias",
         why="\"sab kuch modelling error hai\" ko sirf systematics ka asli "
             "literature hi test kar sakta hai"),
)

# ── generic axes — har gambhir scientific sawaal par lagte hain ────────────────
# Ye kisi field ke naam par nahi, RESEARCH ke tareeke par bane hain. Isliye jis
# topic ka curated set nahi hai, wahan bhi retrieval axis-wise hi hota hai
# (varna wahi purani ek-broad-query wali galti wapas aa jaati).
_GENERIC_AXES: Tuple[Axis, ...] = (
    Axis("mechanism", "mechanism — ye kaam kaise karta hai",
         ("mechanism", "why", "cause", "pathway", "underlying physics",
          "theory", "explanation"),
         "mechanism explanation why it happens",
         why="bina mechanism jawab sirf aankdon ki list ban jaata hai"),
    Axis("quantitative", "quantitative measurement / data",
         ("measurement", "quantitative", "dataset", "observed value",
          "magnitude", "statistics", "sample size"),
         "quantitative measurement dataset observed values",
         why="number ke bina claim ka weight naapna mumkin nahi"),
    Axis("replication", "independent replication / reproducibility",
         ("replication", "reproducib", "independent confirmation",
          "multi centre", "multi center", "retraction", "failed to replicate"),
         "independent replication reproducibility confirmation",
         why="ek group ka nateeja saboot nahi — swatantra dohraav zaroori hai"),
    Axis("counter_evidence", "counter-evidence / criticism",
         ("criticism", "contradictory", "null result", "no effect",
          "refute", "challenge", "limitation", "disagree"),
         "criticism contradictory findings null result limitations",
         why="§10 — support-side ke saath counter-side search compulsory hai"),
)

# Ye do axes limit ki wajah se kabhi nahi katne chahiye: counter_evidence §10 ka
# compulsory counter-search hai, aur replication "ek group ka nateeja saboot
# nahi" wali shart hai.
_ALWAYS_KEEP_AXIS_IDS = ("replication", "counter_evidence")

_SUPERCONDUCTIVITY_AXES: Tuple[Axis, ...] = (
    Axis("transport", "resistivity / transport measurement",
         ("zero resistance", "resistivity", "four probe", "transport measurement",
          "critical current"),
         "zero resistance four probe transport measurement critical current",
         why="\"superconductor hai\" ka pehla naap yahi hai"),
    Axis("magnetic", "magnetic response / Meissner",
         ("meissner", "magnetic susceptibility", "diamagnetic", "flux expulsion",
          "shielding fraction"),
         "meissner effect magnetic susceptibility flux expulsion",
         why="sirf resistance drop dekhna kaafi nahi, magnetic jawab bhi chahiye"),
    Axis("replication_sc", "replication / retraction record",
         ("replication", "retracted", "failed to reproduce", "editorial note",
          "independent group"),
         "replication attempt retraction independent verification",
         why="is field ka sabse bada failure mode retracted claim hai"),
)

_CLINICAL_AXES: Tuple[Axis, ...] = (
    Axis("rct", "randomised controlled trials",
         ("randomised", "randomized", "placebo", "double blind", "trial arm",
          "intention to treat"),
         "randomised controlled trial placebo double blind outcome",
         why="clinical dawe ka sabse mazboot design yahi hai"),
    Axis("meta_analysis", "systematic review / meta-analysis",
         ("systematic review", "meta analysis", "pooled estimate",
          "forest plot", "heterogeneity"),
         "systematic review meta analysis pooled effect estimate",
         why="ek trial se nahi, kai trials ke pooled nateeje se tasveer banti hai"),
    Axis("harms", "adverse events / harms",
         ("adverse event", "side effect", "safety outcome", "toxicity",
          "contraindication", "harm"),
         "adverse events safety harms contraindications",
         why="fayda batana aur nuksan chhupana — ye galti safety-sensitive hai"),
    Axis("guideline", "guidelines / regulatory position",
         ("guideline", "recommendation", "regulatory", "approval",
          "label change", "who recommendation"),
         "clinical guideline recommendation regulatory approval status",
         why="practice mein kya maana jaata hai, ye alag saboot hai"),
)

_CLIMATE_AXES: Tuple[Axis, ...] = (
    Axis("observed_trend", "observed instrumental record",
         ("temperature record", "observed trend", "station data", "reanalysis",
          "satellite record", "anomaly"),
         "observed temperature record trend station satellite data",
         why="asli naap — model se pehle"),
    Axis("attribution", "attribution studies",
         ("attribution", "fingerprint", "detection and attribution",
          "counterfactual", "forcing"),
         "detection and attribution study forcing fingerprint",
         why="\"kis wajah se\" ka jawab attribution literature deta hai"),
    Axis("projection", "model projections / uncertainty",
         ("cmip", "projection", "scenario", "ensemble spread",
          "model uncertainty", "ssp"),
         "climate model projection scenario ensemble uncertainty",
         why="aage ka anumaan aur uski uncertainty ek saath aani chahiye"),
)

# Registry — trigger words se set chunte hain. Ek se zyada set match ho to
# sabse zyada hits wala jeetta hai (aur generic axes hamesha saath jaate hain).
AXIS_SETS: Tuple[Tuple[str, Tuple[str, ...], Tuple[Axis, ...]], ...] = (
    ("dark_matter",
     ("dark matter", "dark energy", "missing mass", "rotation curve", "mond",
      "modified gravity", "primordial black hole", "cosmology", "lambda cdm",
      "galaxy cluster", "cmb", "dark photon"),
     _DARK_MATTER_AXES + _DARK_MATTER_AXES_2),
    ("superconductivity",
     ("superconduct", "superconductor", "critical temperature", "meissner",
      "cooper pair", "hydride", "lk-99", "ambient pressure superconduct"),
     _SUPERCONDUCTIVITY_AXES),
    ("clinical",
     ("treatment", "therapy", "drug", "vaccine", "patient", "clinical",
      "dose", "disease", "mortality", "symptom"),
     _CLINICAL_AXES),
    ("climate",
     ("climate", "global warming", "emission", "greenhouse", "monsoon",
      "sea level", "carbon dioxide"),
     _CLIMATE_AXES),
)


# ── sawaal mein naam liye gaye mission / experiment / dataset ─────────────────
# §4 kehta hai: "named datasets/missions/experiments" ko identify karo. Jo user
# ne khud naam se maanga hai, wo axis MANDATORY hai — chahe curated set mein ho
# ya na ho. Pichhli report mein "Bullet Cluster" maanga gaya tha aur ek bhi
# source uska nahi tha, phir bhi answer COMPLETE likha gaya.
_ACRONYM_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,}(?:-[A-Za-z0-9]+)?|[A-Z]{2,}[a-z]?[A-Z]*)\b")
_PROPER_PAIR_RE = re.compile(r"\b([A-Z][a-z]{2,}\s+(?:[A-Z][a-z]{2,}|Cluster|Way|Telescope))\b")
_ENTITY_STOP = {
    "AI", "API", "PDF", "URL", "OK", "TODO", "AND", "THE", "NOT", "ALL",
    "RV", "APP", "UI", "USA", "INDIA", "HTML", "JSON", "RESEARCH", "LAB",
    "NO", "SOURCE", "MAXIMUM", "QUICK", "DEEP", "COMPLETE", "PARTIAL",
    "VERIFIED", "HYPOTHESIS", "ESTABLISHED", "FACT",
}
_PAIR_STOP = {"Dark Matter", "Deep Research", "App Original"}

# ── kaun sa ALL-CAPS shabd research target NAHI hai ───────────────────────────
# Naapa hua defect (2026-08-25, live run): intel ke sawaal me likha tha "Label
# everything: ESTABLISHED, SOURCE-REPORTED, INFERENCE, SPECULATION", "Agar RAM ya
# timeout ki dikkat ho to bata do" aur "DRM ya paywall bypass mat karna". Sab
# ALL-CAPS the, isliye `named_entities` ne inhe MANDATORY evidence axis bana
# diya — aur audit me user ko jhoothi shortfall dikhi:
# "12 naam se maange gaye target → 10/12 par kaam hua — in par kuch nahi mila:
# SPECULATION, DRM". Ye naam nahi the; ek app ki apni label-bhasha thi, doosri
# user ki PABANDI thi.
#
# Ilaaj do general niyam se — koi nayi topic list nahi:
#
#   A. App ki APNI bhasha kabhi target nahi hoti. Ye vocabulary pehle se ek
#      jagah likhi hai (`models._LABEL_TO_CLAIM`, `ClaimType`, `run_status` ke
#      status, aur `query_builder._META` ka research-process vocabulary), isliye
#      wahin se DERIVE karte hain. Naya label jodne par ye parat khud badh
#      jaati hai — dobara haath se likhna nahi padta.
#
#   B. Jis vaakya me user ne MANA kiya hai, us vaakya ke naam pabandi hain,
#      target nahi. Ye vyakaran ka cue hai, topic ka nahi ("mat", "don't",
#      "avoid", "bypass"), isliye kal ke "VPN mat use karna" par bhi chalega.
#
# `CIA` jaan-boojh kar BACHTA hai: wo "declassified intelligence programs
# including CIA remote viewing" me hai — koi mana nahi, koi label nahi. Yaani
# sahi target girta nahi, sirf label aur pabandi girti hai.
_CONSTRAINT_CUE_RE = re.compile(
    r"(?:\bmat\b|\bnahi\s+(?:karna|kehna|chahiye|bhejna)\b|\bdon'?t\b|"
    r"\bdo\s+not\b|\bnever\b|\bavoid\b|\bbypass\b|\bबिना\b|\bमत\b)",
    re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+|\n+")


def _derived_label_vocab() -> Set[str]:
    """
    App ki apni label/status/process bhasha — DERIVE ki hui, haath se likhi
    nahi. Import lazy aur fail-safe hai: koi module na mile to ye parat chup-chaap
    kam kaam karti hai, poora axis system girta nahi.
    """
    global _LABEL_VOCAB_CACHE
    if _LABEL_VOCAB_CACHE is not None:
        return _LABEL_VOCAB_CACHE
    vocab: Set[str] = set()

    def _feed(word: object) -> None:
        text = str(word or "").strip().upper()
        if len(text) >= 3:
            vocab.add(text)
        for part in re.split(r"[\s\-_]+", text):
            if len(part) >= 3:
                vocab.add(part)

    try:                                          # claim labels + claim types
        from .models import ClaimType, _LABEL_TO_CLAIM
        for key in _LABEL_TO_CLAIM:
            _feed(key)
        for member in ClaimType:
            _feed(member.value)
    except Exception:
        pass
    try:                                          # run status vocabulary
        from . import run_status
        for name in ("COMPLETE", "PARTIAL", "INCOMPLETE"):
            _feed(getattr(run_status, name, ""))
    except Exception:
        pass
    try:                                          # research-process vocabulary
        from .query_builder import _META
        for word in _META:
            _feed(word)
    except Exception:
        pass
    _LABEL_VOCAB_CACHE = vocab
    return vocab


_LABEL_VOCAB_CACHE: Optional[Set[str]] = None


def _constraint_sentences(text: str) -> List[str]:
    """Wo vaakya jinme user ne kuch MANA kiya hai."""
    return [s for s in _SENTENCE_SPLIT_RE.split(text or "")
            if _CONSTRAINT_CUE_RE.search(s)]


def named_entities(question: str, limit: int = 8) -> List[str]:
    """
    Sawaal mein liye gaye khaas naam (LIGO, Planck, Bullet Cluster, XENONnT...).
    Andaza nahi lagate — sirf wahi jo TEXT mein likhe hain, aur sirf wo jo app
    ki apni label-bhasha ya user ki pabandi nahi hain (upar ka note dekho).
    """
    text = question or ""
    label_vocab = _derived_label_vocab()
    banned = _constraint_sentences(text)

    def _only_in_constraints(name: str) -> bool:
        if not banned:
            return False
        hits = [s for s in _SENTENCE_SPLIT_RE.split(text) if name in s]
        return bool(hits) and all(s in banned for s in hits)

    out: List[str] = []
    for match in _ACRONYM_RE.findall(text):
        name = match.strip()
        if name.upper() in _ENTITY_STOP or len(name) < 3:
            continue
        if name.upper() in label_vocab or _only_in_constraints(name):
            continue
        if name not in out:
            out.append(name)
    for match in _PROPER_PAIR_RE.findall(text):
        name = " ".join(match.split())
        if name in _PAIR_STOP or name in out:
            continue
        if name.upper() in label_vocab or _only_in_constraints(name):
            continue
        out.append(name)
    return out[:limit]


def _entity_axis(name: str) -> Axis:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    lower = name.lower()
    terms = tuple({lower, slug.replace("_", " ")} - {""})
    return Axis(f"named_{slug}", f"named source: {name}", terms,
                query=f"{name} data results",
                why=f"user ne \"{name}\" ka naam khud liya hai, isliye iska "
                    f"saboot dhoondhna zaroori hai",
                entity=name)


# ── set ka faisla: ek shabd se poora curated set nahi milta ───────────────────
# Naapa hua defect (2026-08-25, intel ke 819-word human-agency mega-question par):
# sawaal me `cosmology` shabd EK baar aaya tha — wo bhi lens-list ke andar
# ("quantum mechanics, 'frequency/vibration' claims and cosmology") — aur purana
# `hits > best_hits` (best_hits = 0 se shuru) us ek hit par poora 15-axis
# `dark_matter` set de deta tha. Nateeja naapa gaya: 18 axes me 17 MISSING,
# queries jaise `all:"dark matter" AND all:"attention" AND all:"recoil"`,
# relevance gate ne 305 source `required_axis` par reject kiye, bache 40
# source (copula preprints, earthquake ground motion, LNG terminal, LiDAR),
# avg relevance 0.46 < 0.65 floor → contract fail → PARTIAL. Yaani PARTIAL
# literature ki kami nahi, is misroute ka nateeja tha.
#
# Ye theek wahi bimaari hai jo `domain_focus_guard` `domain.detect()` ke liye
# sambhalta hai ("vibration" → strict ENGINEERING), isliye paimana bhi wahi
# rakha gaya hai: ek akela nishaan lambe sawaal me ittefaq hai, saboot nahi.
#
# Do keemat jaan-boojh kar aise toli gayi hain:
#   * `generic` par gir jaana SASTA hai — mechanism/quantitative/replication/
#     counter_evidence axes phir bhi lagte hain (dekho `axes_for`, wahan
#     `curated` khaali hone par wo do axes wapas aa jaate hain). Yaani sirf
#     field ke ready-made raaste nahi milte, research band nahi hoti.
#   * galat curated set MEHNGA hai — upar naapa hua 17/18 MISSING.
# Isliye shak hone par generic.
_INCIDENTAL_SET_MIN_TOKENS = 40
# Do alag trigger = set ka dawa tikta hai. Chhote sawaal ("LK-99 ka Tc?") me
# ek hi shabd poora topic hota hai, isliye wahan ek hit kaafi hai.
_MIN_SET_SIGNALS = 2


def axis_set_verdict(question: str) -> Dict[str, object]:
    """
    Kaun sa curated axis set chuna gaya aur KYUN — audit ke liye padha ja sakne
    wala faisla. `axis_set_for()` isi par khada hai (do jagah do niyam nahi).
    """
    text = question or ""
    bag = stems(text)
    token_count = len(tokens(text))
    best_key, best_axes, best_hits, best_terms = "generic", (), 0, []
    for key, triggers, axes in AXIS_SETS:
        hits = count_hits(triggers, bag)
        if hits > best_hits:
            best_key, best_axes, best_hits = key, axes, hits
            best_terms = matched(triggers, bag)

    detail: Dict[str, object] = {
        "set": best_key, "axes": best_axes, "hits": best_hits,
        "matched_triggers": best_terms, "tokens": token_count,
    }
    if best_hits == 0:
        detail["reason"] = "kisi curated set ka koi trigger nahi mila"
        return detail
    if best_hits < _MIN_SET_SIGNALS and token_count >= _INCIDENTAL_SET_MIN_TOKENS:
        only = ", ".join(best_terms) or "—"
        detail.update(set="generic", axes=(), demoted=True, reason=(
            f"{token_count}-token sawaal me '{best_key}' set ka sirf ek nishaan "
            f"({only}) mila — ek shabd se poora sawaal is field ka nahi ban jaata"))
        return detail
    detail["reason"] = (f"'{best_key}' set ka dawa tikta hai ({best_hits} nishaan, "
                        f"{token_count} token)")
    return detail


def axis_set_for(question: str) -> Tuple[str, Tuple[Axis, ...]]:
    """(set_key, axes) — sabse zyada trigger hits wala set, par ek akela
    incidental hit lambe sawaal par set nahi jitata. Warna generic."""
    verdict = axis_set_verdict(question)
    return str(verdict["set"]), tuple(verdict["axes"])       # type: ignore[arg-type]


def axes_for(question: str, limit: int = 18) -> List[Axis]:
    """
    Is sawaal ke mandatory evidence axes: curated set + sawaal ke naam liye gaye
    entities + generic research axes. Order maayne rakhta hai — pehle field ke
    khaas raaste, phir naam se maange gaye, phir generic.

    Deterministic hai: ek hi sawaal par hamesha wahi axes (koi API call nahi).
    """
    _, curated = axis_set_for(question)
    picked: List[Axis] = []
    seen: Set[str] = set()

    def _add(axis: Axis) -> None:
        if axis.axis_id in seen:
            return
        seen.add(axis.axis_id)
        picked.append(axis)

    for axis in curated:
        _add(axis)
    for name in named_entities(question):
        axis = _entity_axis(name)
        # curated axis pehle se us entity ko cover karta ho to dobara nahi
        if any(name.lower() in " ".join(a.terms) for a in picked):
            continue
        _add(axis)
    for axis in _GENERIC_AXES:
        # generic mechanism/quantitative tab hi jodte hain jab curated set chhota
        # hai — warna 20 axes ban jaate hain aur har run "MISSING" se bhar jaata.
        if curated and axis.axis_id in {"mechanism", "quantitative"}:
            continue
        _add(axis)
    if len(picked) <= limit:
        return picked
    # `picked[:limit]` seedha kaatne se dikkat: entity axes (sawaal mein naam liye
    # gaye mission/dataset) list mein pehle aate hain, aur jab sawaal mein 8-10
    # instrument ke naam ho to limit wahin khatam ho jaati thi — sabse aakhir wala
    # `counter_evidence` axis chup-chaap gir jaata tha. Us haalat mein
    # `counter_search_done()` `None` lautata hai, yaani §10 ka counter-search axis
    # theek un sawaalon par gayab ho jaata jinme sabse zyada naam liye gaye hain.
    # Isliye kaatne se pehle ye axes hamesha reserve rakhe jaate hain.
    keep_last = [axis for axis in picked
                 if axis.axis_id in _ALWAYS_KEEP_AXIS_IDS]
    head = [axis for axis in picked
            if axis.axis_id not in _ALWAYS_KEEP_AXIS_IDS]
    room = max(0, limit - len(keep_last))
    return head[:room] + keep_last


# ── coverage ──────────────────────────────────────────────────────────────────
COVERAGE_FLOOR = 0.50       # isse neeche wala source axis "cover" nahi karta
_MIN_AXIS_HITS = 1


def _source_bag(source) -> Set[str]:
    parts = [str(getattr(source, "title", "") or ""),
             str(getattr(source, "snippet", "") or "")[:1200],
             str(getattr(source, "url", "") or "")]
    return stems(" ".join(parts))


def axis_of(source, axes: Sequence[Axis]) -> Tuple[str, int]:
    """Ye source kis axis par kaam kar raha hai — (axis_id, hits). Tie par pehla."""
    best_id, best_hits = "", 0
    bag = _source_bag(source)
    for axis in axes or []:
        hits = axis.hits(bag)
        if hits > best_hits:
            best_id, best_hits = axis.axis_id, hits
    return best_id, best_hits


def coverage(axes: Sequence[Axis], sources: Optional[Sequence] = None,
             searched: Optional[Dict[str, Sequence[str]]] = None,
             floor: float = COVERAGE_FLOOR) -> List[Dict]:
    """
    Per-axis coverage record (§5).

    `searched` = kis axis par kaunsi queries gayi (orchestrator/planner deta hai).
    Agar wo pata nahi hai to status `NOT SEARCHED` rehta hai — jaan-boojh kar,
    kyunki "dhoondha aur nahi mila" ek alag (aur bada) dawa hai.
    """
    records: List[Dict] = []
    for axis in axes or []:
        queries = list((searched or {}).get(axis.axis_id) or [])
        hit_ids: List[str] = []
        relevant_ids: List[str] = []
        terms: List[str] = []
        for source in sources or []:
            bag = _source_bag(source)
            hits = axis.hits(bag)
            if hits < _MIN_AXIS_HITS:
                continue
            sid = getattr(source, "source_id", "") or "?"
            hit_ids.append(sid)
            terms.extend(axis.matched_terms(bag))
            rejected = (getattr(source, "rejected_reason", "") or "").strip()
            score = float(getattr(source, "relevance_score", 0) or 0)
            parts = getattr(source, "relevance_parts", None) or {}
            if (not rejected and score >= float(floor)
                    and parts.get("tests_proposition") is not False):
                relevant_ids.append(sid)
        if relevant_ids:
            status = AXIS_COVERED
        elif hit_ids:
            status = AXIS_WEAK
        elif queries:
            status = AXIS_MISSING
        else:
            status = AXIS_NOT_SEARCHED
        records.append({
            "axis_id": axis.axis_id, "label": axis.label,
            "mandatory": axis.mandatory, "why_required": axis.why,
            "status": status, "status_why": AXIS_STATUS_EXPLAIN[status],
            # `searched` alag field hai kyunki COVERED do tarah se aa sakta hai:
            # (a) is axis par query chali aur source mila, ya (b) kisi doosri
            # query se aaya source ittefaq se is axis ke terms se match kar gaya.
            # §10 ke counter-search jaise gate ke liye (b) kaafi NAHI hai.
            "searched": bool(queries),
            "queries_tried": queries, "ladder_steps_used": len(queries),
            "sources_found": hit_ids, "relevant_sources": relevant_ids,
            "matched_terms": sorted(set(terms))[:6],
        })
    return records


def coverage_summary(records: Optional[Sequence[Dict]]) -> Dict:
    """
    Coverage ka ek nazar mein hisaab — aur yahi ledger/gate padhta hai.

    `axes_total` 0 ho to sab kuch `None` (yani "naapa hi nahi"), 0 nahi.
    """
    if not records:
        return {"axes_total": 0, "axes_covered": None, "axes_weak": None,
                "axes_missing": None, "axes_not_searched": None,
                "mandatory_missing": None, "coverage_ratio": None,
                "missing_labels": []}
    by_status = {status: [r for r in records if r["status"] == status]
                 for status in AXIS_STATUSES}
    mandatory = [r for r in records if r.get("mandatory")]
    man_missing = [r for r in mandatory
                   if r["status"] in (AXIS_MISSING, AXIS_WEAK, AXIS_NOT_SEARCHED)]
    covered = len(by_status[AXIS_COVERED])
    return {
        "axes_total": len(records),
        "axes_covered": covered,
        "axes_weak": len(by_status[AXIS_WEAK]),
        "axes_missing": len(by_status[AXIS_MISSING]),
        "axes_not_searched": len(by_status[AXIS_NOT_SEARCHED]),
        "mandatory_total": len(mandatory),
        "mandatory_missing": len(man_missing),
        "coverage_ratio": round(covered / len(records), 3),
        "missing_labels": [r["label"] for r in man_missing][:12],
    }


def next_queries(axes: Sequence[Axis], records: Optional[Sequence[Dict]] = None,
                 base: str = "", round_no: int = 1, limit: int = 3) -> List[Dict]:
    """
    §5 ka retry ladder chalane wala hissa: jo axis abhi cover nahi hua, uski
    AGLI seedhi ki query. Wahi query dobara nahi bhejte — step aage badhta hai.

    Priority (2026-08-22 ka sudhaar): "incidentally covered" axis ko bhi ek
    apni query milti hai. Kyun — cross-domain benchmark mein `counter_evidence`
    axis COVERED dikh raha tha kyunki ek support-side source ke andar "limitation"
    jaisa shabd tha, jabki counter-side par ek bhi query gayi hi nahi thi. Waisa
    coverage §10 ki shart poori nahi karta: counter-search ALAG se chalni chahiye,
    ittefaq se nahi. Isliye order ye hai —
        0. na search hui, na cover hua      (sabse andhera kona)
        1. search hui hi nahi (chahe source ittefaq se mil gaya ho)
        2. search hui par cover nahi hua    (ladder ki agli seedhi)
        3. search bhi hui aur cover bhi hua → chhod do
    Har level ke andar mandatory axis pehle.

    Return `[{axis_id, step, name, query}]`. Khaali list = sab axis cover hain
    aur sabpar apni query ja chuki hai.
    """
    status_by_id = {r["axis_id"]: r for r in (records or [])}

    def _rank(item) -> Tuple[int, int, int]:
        index, axis = item
        record = status_by_id.get(axis.axis_id) or {}
        tried = int(record.get("ladder_steps_used") or 0)
        covered = record.get("status") == AXIS_COVERED
        if not tried and not covered:
            tier = 0
        elif not tried:
            tier = 1
        elif not covered:
            tier = 2
        else:
            tier = 3
        return (tier, 0 if axis.mandatory else 1, index)

    out: List[Dict] = []
    for _, axis in sorted(enumerate(axes or []), key=_rank):
        record = status_by_id.get(axis.axis_id)
        used = int((record or {}).get("ladder_steps_used") or 0)
        if used and (record or {}).get("status") == AXIS_COVERED:
            continue
        # §5 ka ladder HAR AXIS ka apna hai: pehli koshish "exact", uske baad
        # "synonym", phir "entity"… Pehle yahan `round_no` bhi mila diya jaata tha
        # (`max(used, round_no - 1)`), jiska nateeja ye tha ki round 2 mein pehli
        # baar dhoondhe gaye axis ki "exact" query hi kabhi nahi chalti thi — wo
        # seedha "synonym" se shuru ho jaata tha. Ladder us axis ki apni koshishon
        # se aage badhta hai, round number se nahi.
        step_idx = min(used, len(LADDER_STEPS) - 1)
        rung = axis.ladder(base, limit=len(LADDER_STEPS))[step_idx]
        out.append({"axis_id": axis.axis_id, "label": axis.label,
                    "step": rung["step"], "name": rung["name"],
                    "query": rung["query"]})
        if len(out) >= max(1, limit):
            break

    # §10 — counter-side search ke liye ek slot RESERVED hai.
    #
    # Kyun: QUICK mode mein sirf ek round aur 3 axis queries chalti hain, aur
    # curated (domain) axes list mein pehle aate hain — isliye counter axis
    # aakhir tak pahunchta hi nahi tha. Benchmark ne ye pakda: report "sehmati"
    # ki baat kar rahi thi aur counter-side par ek bhi query nahi gayi thi.
    # Counter-search budget ki daya par nahi ho sakti, isliye aakhri slot iske
    # naam kar dete hain (agar counter axis par ab tak koi query nahi gayi).
    if out and not any("counter" in row["axis_id"] for row in out):
        pending = [a for a in (axes or []) if "counter" in a.axis_id
                   and not int((status_by_id.get(a.axis_id) or {})
                               .get("ladder_steps_used") or 0)]
        if pending:
            axis = pending[0]
            # Reserve slot par bhi ladder ka pehla rung hi chalega — is axis par
            # ab tak ek bhi query nahi gayi hai (`pending` ki shart), isliye
            # round number dekh kar seedha "synonym" par kood jaana galat tha.
            rung = axis.ladder(base, limit=len(LADDER_STEPS))[0]
            out[-1] = {"axis_id": axis.axis_id, "label": axis.label,
                       "step": rung["step"], "name": rung["name"],
                       "query": rung["query"]}
    return out


def counter_search_done(records: Optional[Sequence[Dict]]) -> Optional[bool]:
    """
    §10 ka flag: counter-side search SACH mein chali ya nahi.

    `None` = axes hi naape nahi gaye (isliye kuch keh nahi sakte). `True` sirf
    tab jab counter/criticism axis par kam se kam ek query chali ho — us axis par
    ittefaq se source mil jaana kaafi NAHI hai (yahi bug benchmark ne pakda).
    """
    if not records:
        return None
    rows = [r for r in records if "counter" in str(r.get("axis_id") or "")]
    if not rows:
        return None
    return any(int(r.get("ladder_steps_used") or 0) >= 1 for r in rows)


def coverage_note(records: Optional[Sequence[Dict]], limit: int = 8) -> str:
    """
    User ko dikhne wali seedhi baat. Ye report ka wo hissa hai jo pichhli baar
    hona hi chahiye tha: "18 sources mile" ke bajaye "kaunsa saboot mila hi nahi".
    """
    if not records:
        return ("Evidence axes ka coverage naapa nahi gaya — isliye ye nahi kaha "
                "ja sakta ki koi saboot ka raasta chhoot gaya ya nahi.")
    summary = coverage_summary(records)
    lines = [f"Saboot ke {summary['axes_total']} raaste dekhe gaye: "
             f"{summary['axes_covered']} par relevant source mila, "
             f"{summary['axes_weak']} par sirf kamzor match, "
             f"{summary['axes_missing']} par dhoondh kar bhi kuch nahi, "
             f"{summary['axes_not_searched']} par search hi nahi hui."]
    for record in records[:limit]:
        if record["status"] == AXIS_COVERED:
            continue
        ids = ", ".join(record["relevant_sources"] or record["sources_found"])
        lines.append(f"• {record['label']} — {record['status']} "
                     f"({record['status_why']})"
                     + (f" [{ids}]" if ids else "")
                     + (f"; kyun zaroori: {record['why_required']}"
                        if record.get("why_required") else ""))
    if summary["mandatory_missing"]:
        lines.append(f"Isliye is jawab ko poora nahi kaha ja sakta — "
                     f"{summary['mandatory_missing']} zaroori raaste khaali hain.")
    return "\n".join(lines)


def axes_to_dict(axes: Sequence[Axis]) -> List[Dict]:
    return [axis.to_dict() for axis in axes or []]
