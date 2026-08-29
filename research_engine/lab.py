"""#116 — LAB stage: app apni hypothesis ko KHUD test kare.

Aaj tak pipeline hypothesis banata tha aur "UNTESTED" likh kar aage badh jaata
tha. Ye module us beech ka khaali hissa bharta hai: jo test **is machine ke
andar, bina paisa aur bina internet** ho sakta hai, wo sach me chalta hai, aur
uska nateeja alag se likha jaata hai.

Kya ye module JAAN-BOOJH KAR nahi karta:
  * Model ka likha Python nahi chalata. Sirf `SafeNumericExecutor` ka bounded
    arithmetic (koi import, filesystem, network, subprocess, randomness nahi).
  * Koi network call, koi API, koi paid provider — kharcha ₹0.
  * Koi random number. Seed fixed hai taaki wahi input par wahi nateeja aaye.
  * TESTED_PASS ko "sach sabit ho gaya" nahi kehta. Ye sirf itna kehta hai ki
    app ke andar ka hisaab/consistency check pass hua — asli duniya ka
    experiment abhi bhi baaki hai.

Paanch recipe (sab deterministic):
  numeric_formula     — hypothesis ka apna formula dobara chala kar naapo
  threshold           — "X se zyada/kam" wala daawa evidence ke numbers se naapo
  direction           — "badhega/ghatega" khud ke numbers se ulta hai ya nahi
  proportion_interval — "k of n" par Wilson interval; chhota sample = koi verdict nahi
  walk_forward        — asli train → held-out backtest (naive baseline se muqabla);
                        series na ho to DATA_MISSING, jhoothi "chal gaya" nahi

Status shabd (isse bahar kuch nahi):
  TESTED_PASS, TESTED_FAIL, DATA_MISSING, NOT_TESTABLE_HERE, NOT_RUN
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import physics_checks
from . import market_data
from . import simulation_lab
from .advanced_discovery import NumericExecutionPolicy, SafeNumericExecutor

# ── status vocabulary ────────────────────────────────────────────────────────
# Chaar asli nateeje + ek "chala hi nahi". NOT_RUN alag rakha gaya hai kyunki
# budget khatam hona ya kill switch lagna "data nahi mila" NAHI hai — dono ko
# ek naam dena jhooth ho jaata.
TESTED_PASS = "TESTED_PASS"
TESTED_FAIL = "TESTED_FAIL"
DATA_MISSING = "DATA_MISSING"
NOT_TESTABLE_HERE = "NOT_TESTABLE_HERE"
NOT_RUN = "NOT_RUN"

LAB_STATUSES: Tuple[str, ...] = (TESTED_PASS, TESTED_FAIL, DATA_MISSING,
                                 NOT_TESTABLE_HERE, NOT_RUN)

# Rollup ka kram: ek FAIL poore hypothesis ka FAIL hai (ek bhi ulta nateeja
# kaafi hai), PASS uske baad, phir "naap hi nahi paaye".
_ROLLUP_ORDER: Tuple[str, ...] = (TESTED_FAIL, TESTED_PASS, DATA_MISSING,
                                  NOT_TESTABLE_HERE, NOT_RUN)

LAB_DISCLAIMER = (
    "Ye test app ne KHUD apne andar chalaya hai (sirf hisaab aur consistency "
    "check, ₹0, bina internet). TESTED_PASS ka matlab \"sach sabit ho gaya\" "
    "NAHI hai — asli duniya ka experiment abhi bhi baaki hai."
)
RISK_REVIEW_NOTE = (
    "Ye hypothesis medical/chemical/biological ya safety-sensitive hai. Yahan "
    "ka hisaab clinical ya safety validation NAHI hai; asli protocol se pehle "
    "qualified review zaroori hai."
)


@dataclass
class LabPolicy:
    """Lab ki chhat. Inhe badalna = jaan-boojh kar faisla, chupke se nahi."""
    max_hypotheses: int = 6
    max_specs_per_hypothesis: int = 4
    max_wall_seconds: float = 6.0
    seed: int = 20260826            # fixed — koi randomness use nahi hoti,
    #                                 ye sirf reproducibility ka record hai
    relative_tolerance: float = 0.05   # 5% — recompute vs stated result
    min_proportion_sample: int = 5     # isse chhote sample par koi verdict nahi
    max_evidence_chars: int = 240_000  # evidence text ki chhat (safety valve)
    # Walk-forward ki chhat (#118). Ye market_data se aati hai taaki ek hi jagah
    # par tay ho ki "kitna data kaafi hai" — do jagah likhne se dono chupke se
    # alag ho jaati hain, aur tab report kis chhat par tiki hai ye pata hi nahi
    # chalta. Chhoti series par verdict dena sabse aasan jhooth hai.
    min_series_points: int = market_data.MIN_SERIES_POINTS
    min_holdout_points: int = market_data.MIN_HOLDOUT_POINTS
    train_fraction: float = market_data.TRAIN_FRACTION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_hypotheses": self.max_hypotheses,
            "max_specs_per_hypothesis": self.max_specs_per_hypothesis,
            "max_wall_seconds": self.max_wall_seconds,
            "seed": self.seed,
            "relative_tolerance": self.relative_tolerance,
            "min_proportion_sample": self.min_proportion_sample,
            "min_series_points": self.min_series_points,
            "min_holdout_points": self.min_holdout_points,
            "train_fraction": self.train_fraction,
            "randomness_used": False,
            "network_used": False,
            "model_written_code_executed": False,
        }


def wilson_interval(successes: int, total: int, z: float = 1.96
                    ) -> Tuple[float, float]:
    """Wilson score interval — chhote sample par imaandaar range.

    NOTE: `exam_intelligence._wilson` bhi yahi hisaab karta hai. Use hataya
    nahi gaya (purane caller uspar tike hain); dono ka nateeja ek hi rehna
    chahiye, aur test isi baat ko pin karta hai.
    """
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1 + (z * z / total)
    centre = (p + (z * z / (2 * total))) / denominator
    spread = z * math.sqrt((p * (1 - p) / total)
                           + (z * z / (4 * total * total))) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


# ── kaunsa test ban sakta hai — sab deterministic pattern, koi model call nahi ─
_GT_RE = re.compile(
    r"(?:more than|greater than|higher than|above|over|exceeds?|at least|"
    r"no less than|>=|>|se\s+(?:zyada|adhik|ooncha|upar|bada)|"
    r"kam\s+se\s+kam)\s*", re.IGNORECASE)
_LT_RE = re.compile(
    r"(?:less than|lower than|below|under|fewer than|at most|no more than|"
    r"<=|<|se\s+(?:kam|neeche|chhota)|zyada\s+se\s+zyada)\s*", re.IGNORECASE)
_UP_RE = re.compile(
    r"\bincrease(?:s|d)?\b|\brise(?:s|n)?\b|\bimprove(?:s|d|ment)?\b|"
    r"\bhigher\b|\bgain(?:s)?\b|\bgrowth\b|\bbadh(?:ega|egi|ta|ti|egee)?\b|"
    r"\bzyada\s+ho(?:ga|gi)\b", re.IGNORECASE)
_DOWN_RE = re.compile(
    r"\bdecrease(?:s|d)?\b|\breduc(?:e|es|ed|tion)\b|\bdrop(?:s|ped)?\b|"
    r"\bfall(?:s|en)?\b|\bdecline(?:s|d)?\b|\blower(?:s|ed)?\b|"
    r"\bghat(?:ega|egi|ta|ti)?\b|\bkam\s+ho(?:ga|gi)\b|\bkami\b",
    re.IGNORECASE)
_PROPORTION_RE = re.compile(
    r"(\d{1,6})\s*(?:out\s+of|of|/|me\s+se|mein\s+se)\s*(\d{1,6})\b",
    re.IGNORECASE)
_PERCENT_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*%")
_SERIES_RE = re.compile(
    r"\bback[-\s]?test(?:s|ed|ing)?\b|\bwalk[-\s]?forward\b|\btime[-\s]?series\b|"
    r"\bforecast(?:s|ed|ing)?\b|\bout[-\s]?of[-\s]?sample\b|"
    r"\bnext\s+(?:year|month|quarter|week|day)\b|\bagle\s+(?:saal|mahine|hafte)\b",
    re.IGNORECASE)
# "insaan par test", "clinical trial" — ye machine ke andar ho hi nahi sakta.
_HUMAN_LAB_RE = re.compile(
    r"\bclinical trial\b|\brandomi[sz]ed controlled\b|\bin vivo\b|\bin vitro\b|"
    r"\bpatients?\b|\bparticipants?\b|\banimal model\b|\bcell line\b|"
    r"\bsynthesi[sz]e\b|\bfabricat(?:e|ion)\b|\bprototype\b|\bwind tunnel\b|"
    r"\btelescope time\b|\bbeam\s?line\b", re.IGNORECASE)


@dataclass
class TestSpec:
    """Ek naapne layak test ka structured plan. Yahan koi code nahi hota."""
    spec_id: str
    hypothesis_id: str
    recipe: str
    what: str                       # Hinglish: kya naapa ja raha hai
    origin: str = ""                # kis field se ye test nikla
    relation: str = ""              # gt / lt  (threshold)
    target_value: Optional[float] = None
    target_unit: str = ""
    dimension: str = ""
    target_si: Optional[float] = None
    direction: str = ""             # up / down
    successes: Optional[int] = None
    total: Optional[int] = None
    claimed_proportion: Optional[float] = None
    text: str = ""                  # jis text par recipe chalegi
    evidence_text: str = ""
    question: str = ""
    safety_sensitive: bool = False
    notes: List[str] = field(default_factory=list)
    # #118 — walk_forward ke liye NAAPI hui time series. Ye lab KHUD nahi laata:
    # discovery (jise network ki ijaazat hai) laati hai aur `plan_specs` yahan
    # rakh deti hai. Isi wajah se lab ka `network_used: False` waada sach rehta
    # hai — lab sirf hisaab karta hai. None = koi series nahi mili, aur uski
    # wajah `series_reason` me hai (khaali reason = "wajah bhi pata nahi").
    series: Optional[Any] = None
    series_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        series = self.series
        return {
            "spec_id": self.spec_id,
            "hypothesis_id": self.hypothesis_id,
            "recipe": self.recipe,
            "what": self.what,
            "origin": self.origin,
            "relation": self.relation,
            "target_value": self.target_value,
            "target_unit": self.target_unit,
            "dimension": self.dimension,
            "direction": self.direction,
            "successes": self.successes,
            "total": self.total,
            "claimed_proportion": self.claimed_proportion,
            "safety_sensitive": self.safety_sensitive,
            "notes": list(self.notes),
            # Series ka chhota parichay (poore points nahi — report bhaari ho
            # jaati). `series_provider` khaali hona hi batata hai ki koi series
            # nahi thi, aur `series_reason` batata hai kyun.
            "series_provider": (str(getattr(series, "provider", "") or "")
                                if series is not None else ""),
            "series_points": len(getattr(series, "points", None) or ()),
            "series_reason": self.series_reason,
            "model_written_code": False,
        }


@dataclass
class TestResult:
    """Ek test ka nateeja. `status` LAB_STATUSES me se hi hota hai."""
    spec_id: str
    hypothesis_id: str
    recipe: str
    status: str
    what: str
    observed: str = ""
    expected: str = ""
    detail: str = ""
    reason_code: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    computed: Optional[float] = None
    requires_risk_review: bool = False
    stress_test: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "hypothesis_id": self.hypothesis_id,
            "recipe": self.recipe,
            "status": self.status,
            "what": self.what,
            "observed": self.observed,
            "expected": self.expected,
            "detail": self.detail,
            "reason_code": self.reason_code,
            "evidence_ids": list(self.evidence_ids),
            "computed": self.computed,
            "requires_risk_review": self.requires_risk_review,
            "stress_test": dict(self.stress_test),
            # Ye do line kabhi badalti nahi: lab ka pass hona sabooti nahi hai.
            "is_established_fact": False,
            "real_world_experiment_pending": True,
        }


def _spec_id(hypothesis_id: str, index: int) -> str:
    base = (hypothesis_id or "RV-HYP-UNKNOWN").strip()
    return f"{base}/LAB-{index + 1}"


def _text_of(hypothesis: Dict[str, Any], *keys: str) -> str:
    """Sirf jo likha hai wahi lautao — khaali field ko bharte nahi."""
    parts: List[str] = []
    for key in keys:
        value = hypothesis.get(key)
        if isinstance(value, dict):
            for inner in ("expected_outcome", "text", "measurement_method",
                          "falsification_condition"):
                token = str(value.get(inner) or "").strip()
                if token:
                    parts.append(token)
        elif value:
            parts.append(str(value).strip())
    return "\n".join(p for p in parts if p)


def evidence_text(pack: Any, policy: Optional[LabPolicy] = None) -> str:
    """Sources ka wo text jo lab ko naapne ke liye milta hai (+ source id)."""
    limit = (policy or LabPolicy()).max_evidence_chars
    rows: List[str] = []
    for source in list(getattr(pack, "sources", None) or []):
        tag = str(getattr(source, "source_id", "") or "")
        for attr in ("title", "snippet", "full_text"):
            token = str(getattr(source, attr, "") or "").strip()
            if token:
                rows.append(f"[{tag}] {token}" if tag else token)
        if sum(len(r) for r in rows) > limit:
            break
    return "\n".join(rows)[:limit]


def _threshold_from(text: str) -> Optional[Tuple[str, Any]]:
    """"250 K se zyada" / "at least 30%" → (relation, Quantity). Warna None."""
    for quantity in physics_checks.parse_quantities(text or ""):
        before = (text or "")[max(0, quantity.start - 34):quantity.start]
        after = (text or "")[quantity.end:quantity.end + 24]
        for cue, relation in ((_GT_RE, "gt"), (_LT_RE, "lt")):
            match = cue.search(before)
            if match and len(before) - match.end() <= 2:
                return relation, quantity
        # Hindi kram: number pehle, cue baad me ("250 K se zyada").
        if physics_checks._TAIL_MORE_RE.match(after):
            return "gt", quantity
        if physics_checks._TAIL_LESS_RE.match(after):
            return "lt", quantity
    return None


def _nearest_percent(text: str, anchor: int,
                     window: int = 90) -> Optional[float]:
    """Anchor ke sabse paas ka percent (0-1 me). Do barabar door ho to None.

    "12 of 20 trials ... 90% success" me 90% ko usi ginti ka daawa maana ja
    sakta hai. Par agar do percent barabar door hain to kaunsa daawa hai ye
    guess karna padega — aur guess par kisi hypothesis ko fail karna galat hai.
    """
    best: Optional[Tuple[int, float]] = None
    ties = 0
    for match in _PERCENT_RE.finditer(text or ""):
        distance = abs(match.start() - anchor)
        if distance > window:
            continue
        try:
            value = float(match.group(1).replace(",", "")) / 100.0
        except ValueError:
            continue
        if not 0.0 <= value <= 1.0:
            continue
        if best is None or distance < best[0]:
            best, ties = (distance, value), 1
        elif distance == best[0]:
            ties += 1
    if best is None or ties > 1:
        return None
    return best[1]


def plan_specs(hypothesis: Dict[str, Any], pack: Any = None,
               policy: Optional[LabPolicy] = None,
               question: str = "") -> List[TestSpec]:
    """Hypothesis me se wo test nikaalo jo YAHIN naap sakte hain.

    Kuch guess nahi hota: har spec kisi likhe hue field se banti hai, aur jo
    likha hi nahi gaya uske liye koi test nahi banaya jaata.
    """
    policy = policy or LabPolicy()
    if not isinstance(hypothesis, dict):
        return []
    hid = str(hypothesis.get("hypothesis_id") or "").strip()
    safety = bool(hypothesis.get("safety_sensitive"))
    claim = _text_of(hypothesis, "statement", "prediction", "prediction_text")
    reason = _text_of(hypothesis, "reasoning", "statement", "prediction")
    ev_text = evidence_text(pack, policy)
    specs: List[TestSpec] = []

    def add(**kwargs: Any) -> None:
        if len(specs) >= policy.max_specs_per_hypothesis:
            return
        specs.append(TestSpec(spec_id=_spec_id(hid, len(specs)),
                              hypothesis_id=hid, safety_sensitive=safety,
                              question=question, **kwargs))

    # 1. Apna hisaab dobara chalao — sabse mazboot test, kyunki formula, input
    #    aur nateeja teeno hypothesis ne khud likhe hain.
    if physics_checks._FORMULA_HINT.search(reason or ""):
        add(recipe="numeric_formula", origin="reasoning/prediction",
            what="Hypothesis ka apna hisaab dobara chala kar dekha",
            text=reason, evidence_text=ev_text)

    # 2. "X se zyada/kam" — evidence ke asli numbers se naapa jaata hai.
    threshold = _threshold_from(claim)
    if threshold and ev_text:
        relation, quantity = threshold
        add(recipe="threshold", origin="prediction/statement",
            what=(f"Daawa: value {'>' if relation == 'gt' else '<'} "
                  f"{quantity.label()} — evidence ke numbers se naapa"),
            relation=relation, target_value=quantity.value,
            target_unit=quantity.unit, dimension=quantity.dimension,
            target_si=quantity.si, text=claim, evidence_text=ev_text)

    # 3. "badhega / ghatega" — hypothesis ke KHUD ke numbers ulte hain ya nahi.
    #    Spec sirf tab banti hai jab "A se B" ka joda sach me nikal aaye: bina
    #    baseline aur outcome ke ye test chal hi nahi sakta, aur jo test chal
    #    nahi sakta uska plan banana report me bekaar shor hai.
    direction = ("up" if _UP_RE.search(claim or "") else
                 "down" if _DOWN_RE.search(claim or "") else "")
    if direction and _direction_pair(claim)[0] is not None:
        add(recipe="direction", origin="prediction/statement",
            what=f"Daawa ki cheez {'badhegi' if direction == 'up' else 'ghategi'}"
                 " — likhe hue numbers isse ulte hain ya nahi",
            direction=direction, text=claim, evidence_text=ev_text)

    # 4. "k of n" — chhote sample par confident daawa nahi ban sakta.
    #    Percent ko ginti se JODNA sirf tab hota hai jab dono ek hi text me
    #    hain aur paas-paas hain. Evidence ki ginti + claim ka percent jodna ek
    #    andaaza hota, aur us andaaze par TESTED_FAIL dena hypothesis ko galat
    #    tarike se maar deta.
    from_claim = _PROPORTION_RE.search(claim or "")
    counts = from_claim or _PROPORTION_RE.search(ev_text)
    if counts:
        successes, total = int(counts.group(1)), int(counts.group(2))
        claimed = _nearest_percent(claim, counts.start()) if from_claim else None
        add(recipe="proportion_interval", origin="prediction/evidence",
            what=f"{successes}/{total} par Wilson interval — daawa uske andar hai ya bahar",
            successes=successes, total=total, claimed_proportion=claimed,
            text=claim, evidence_text=ev_text,
            notes=([] if from_claim else
                   ["ginti evidence se aayi, claim ka percent uske saath jodna "
                    "andaaza hota — isliye sirf range report hui"]))


    # 5. Time-series daawa — ab asli backtest chalta hai (#118). Series DO
    #    raaston se aa sakti hai, aur kram jaan-boojh kar ye hai:
    #      (a) provider ki naapi hui series (discovery ne `series_meta` me di) —
    #          ye sabse bharosemand hai, kyunki isme period aur value provider
    #          ke apne feed se aaye hain;
    #      (b) evidence text me se nikaali series — jab (a) na ho.
    #    Dono na milein to spec BANTI HAI (kyunki daawa forecast ka hai) par
    #    wajah saath jaati hai, taaki report "test hua hi nahi" saaf keh sake.
    if _SERIES_RE.search(claim or ""):
        series, reason = market_data.series_from_pack(pack)
        if series is None:
            if (ev_text or "").strip():
                series, reason = market_data.series_from_text(ev_text)
            else:
                # Padhne ke liye kuch tha hi nahi — "period nahi mila" kehna
                # jhooth hoga, kyunki humne koi text dekha hi nahi.
                reason = market_data.NO_SERIES
        add(recipe="walk_forward", origin="prediction/statement",
            what="Forecast/backtest jaisa daawa — walk-forward test chahiye",
            text=claim, evidence_text=ev_text,
            series=series, series_reason=("" if series is not None else reason))
    return specs


# ── ek jagah se result banane ka tareeqa (status kabhi bahar se nahi aata) ────

def _result(spec: TestSpec, status: str, **kwargs: Any) -> TestResult:
    assert status in LAB_STATUSES, status
    return TestResult(spec_id=spec.spec_id, hypothesis_id=spec.hypothesis_id,
                      recipe=spec.recipe, status=status, what=spec.what,
                      requires_risk_review=spec.safety_sensitive, **kwargs)


_CLAUSE = r"[^\n,;।]"
# Teen shakal, aur teeno ka kram alag hai:
#   arrow    "20 % → 12 %"                (pehla number pehle)
#   english  "from 20 % to 12 %"          (pehla number 'from' ke BAAD)
#   hinglish "20 % se 12 % tak badhegi"   (pehla number 'se' ke PEHLE)
_ARROW_PAIR_RE = re.compile(
    rf"(?P<left>{_CLAUSE}{{0,48}}?)\s*(?:→|-->|->)\s*(?P<right>{_CLAUSE}{{0,48}})")
_FROM_TO_RE = re.compile(
    rf"\bfrom\b(?P<left>{_CLAUSE}{{0,48}}?)\bto\b(?P<right>{_CLAUSE}{{0,48}})",
    re.IGNORECASE)
# Hinglish form ko ek saaf ANT chahiye (tak / ho jaayega / pahunchega). Bina
# iske "300 K se zyada hoga, kam se kam 280 K" jaisa threshold daawa galti se
# "300 → 280 ghat raha hai" ban jaata — yaani ek sahi hypothesis TESTED_FAIL.
_SE_TAK_RE = re.compile(
    rf"(?P<left>{_CLAUSE}{{0,48}}?)\s*\bse\b\s*(?P<right>{_CLAUSE}{{0,48}}?)\s*"
    r"(?:\btak\b|\bho\s+j\w+\b|\bpahunch\w*\b)", re.IGNORECASE)
_PAIR_SHAPES = (_ARROW_PAIR_RE, _FROM_TO_RE, _SE_TAK_RE)

_TAG_RE = re.compile(r"^\s*\[([^\]]{1,40})\]\s*")

# Bina physics unit wale number (₹100, 40 marks, 20 lakh). `parse_quantities`
# inhe nahi pehchanta, aur trading/exam/business ke daawe mostly aise hi hote
# hain — isliye ek tang raasta: dono taraf ka SHABD ek hi ho.
_BARE_NUM_RE = re.compile(
    r"(?P<pre>[₹$€£])?\s*(?P<num>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<word>[A-Za-zऀ-ॿ]{2,16}|[₹$€£])?")


@dataclass
class _BareQuantity:
    """Quantity ki tarah bartaav karta chhota record (si = wahi number)."""
    value: float
    unit: str
    dimension: str
    si: float

    def label(self) -> str:
        return f"{self.value:g} {self.unit}".strip()


def _bare_quantity(text: str, take_last: bool) -> Optional[_BareQuantity]:
    """Number + uske saath ka shabd. Shabd na ho to None (guess nahi karte)."""
    found: List[_BareQuantity] = []
    for match in _BARE_NUM_RE.finditer(text or ""):
        word = (match.group("pre") or match.group("word") or "").strip()
        if not word:
            continue
        try:
            value = float(match.group("num").replace(",", ""))
        except ValueError:
            continue
        found.append(_BareQuantity(value=value, unit=word,
                                   dimension="bare:" + word.casefold(),
                                   si=value))
    if not found:
        return None
    return found[-1] if take_last else found[0]


def _direction_pair(text: str) -> Tuple[Optional[Tuple[Any, Any]], str]:
    """(start, end) quantity ka joda + wajah-code. Joda mila to code "" hota hai.

    Ek hi jagah se planning aur runner dono ye faisla lete hain, taaki aisi
    spec kabhi na bane jo chal hi na sake.

    Bare-number raasta jaan-boojh kar tang hai: dono taraf ka shabd ek hi hona
    chahiye ("100 rupees se 80 rupees tak"). Warna "chapter 2 se 5 tak padhne
    se marks badhenge" jaisa jumla "2 → 5 badh raha hai" ban kar jhoota
    TESTED_PASS de deta — aur jhoota PASS gayab test se zyada khatarnaak hai.
    """
    shape_found = False
    for shape in _PAIR_SHAPES:
        for match in shape.finditer(text or ""):
            shape_found = True
            left = physics_checks.parse_quantities(match.group("left"))
            right = physics_checks.parse_quantities(match.group("right"))
            if left and right:
                start, end = left[-1], right[0]   # joda ke sabse paas ke number
            else:
                start = _bare_quantity(match.group("left"), take_last=True)
                end = _bare_quantity(match.group("right"), take_last=False)
            if start is None or end is None:
                continue
            if start.dimension != end.dimension:
                continue
            if start.si is None or end.si is None:
                continue
            return (start, end), ""
    if not shape_found:
        return None, "no_baseline_and_outcome_pair"
    return None, "pair_not_comparable"


def _tagged_quantities(text: str, dimension: str
                       ) -> List[Tuple[str, Any]]:
    """(source_id, Quantity) — sirf usi dimension ke, line ke tag ke saath.

    Ek hi source ka title aur snippet dono me wahi number likha ho to wo EK
    naap hai, do nahi — warna report "3 numbers mile" keh kar evidence ko
    zyada dikhata hai.
    """
    rows: List[Tuple[str, Any]] = []
    seen: set = set()
    for line in (text or "").splitlines():
        tag_match = _TAG_RE.match(line)
        tag = tag_match.group(1) if tag_match else ""
        body = line[tag_match.end():] if tag_match else line
        for quantity in physics_checks.parse_quantities(body):
            if quantity.dimension != dimension or quantity.si is None:
                continue
            key = (tag, round(float(quantity.si), 9))
            if key in seen:
                continue
            seen.add(key)
            rows.append((tag, quantity))
    return rows


def _run_numeric_formula(spec: TestSpec, policy: LabPolicy,
                         executor: SafeNumericExecutor) -> TestResult:
    """Hypothesis ka apna formula + apne input → dobara hisaab.

    Yahan model ka likha CODE nahi chalta: `_expr_from_formula` symbols ki
    jagah SI numbers rakh deta hai, aur bacha hua sirf arithmetic bounded AST
    se chalta hai.
    """
    records = physics_checks.extract_calculations(
        spec.text, question=spec.question, evidence_text=spec.evidence_text)
    usable = [r for r in records if r.formula and r.inputs]
    if not usable:
        return _result(spec, DATA_MISSING, reason_code="no_calculation_found",
                       detail="Hypothesis me formula + input dono likhe hue "
                              "nahi mile, isliye hisaab dobara chalaya hi "
                              "nahi ja saka.")
    record = usable[0]
    expression, missing = physics_checks._expr_from_formula(
        record.formula, record.inputs, record.units)
    if expression is None:
        return _result(spec, DATA_MISSING, reason_code="inputs_missing",
                       expected=record.result,
                       detail="Ye input nahi mile: " + "; ".join(missing[:4]))
    outcome = executor.evaluate(expression)
    if not outcome.get("ok"):
        return _result(spec, NOT_TESTABLE_HERE,
                       reason_code=str(outcome.get("error") or "not_evaluable"),
                       expected=record.result,
                       detail=f"Formula `{record.formula}` bounded calculator "
                              "ke andar chal nahi paaya.")
    computed = float(outcome["value"])
    stated = physics_checks.parse_quantities(record.result or "")
    if not stated or stated[0].si is None:
        return _result(spec, DATA_MISSING, reason_code="no_stated_result",
                       observed=f"{computed:g}",
                       detail="Hisaab chala, par hypothesis ne apna nateeja "
                              "(number + unit) likha hi nahi — isliye milaan "
                              "nahi ho saka.")
    target = float(stated[0].si)
    scale = max(abs(target), abs(computed), 1e-12)
    close = abs(computed - target) / scale <= policy.relative_tolerance
    return _result(spec, TESTED_PASS if close else TESTED_FAIL,
                   observed=f"{computed:g} (SI)",
                   expected=f"{target:g} (SI, likha hua: {record.result})",
                   computed=computed,
                   reason_code="recomputed_match" if close else "recomputed_mismatch",
                   detail=f"Formula `{record.formula}` ko app ne khud dobara "
                          f"chalaya. Farq { (abs(computed - target) / scale) * 100:.1f}% "
                          f"(chhat {policy.relative_tolerance * 100:.0f}%).")


def _run_threshold(spec: TestSpec, policy: LabPolicy,
                   executor: SafeNumericExecutor) -> TestResult:
    """"X se zyada/kam" ko evidence ke asli numbers se naapo."""
    if spec.target_si is None:
        return _result(spec, DATA_MISSING, reason_code="no_target_value",
                       detail="Daawe me koi naapne layak number+unit nahi tha.")
    rows = _tagged_quantities(spec.evidence_text, spec.dimension)
    if not rows:
        return _result(spec, DATA_MISSING,
                       reason_code="no_matching_measurement",
                       expected=f"{spec.target_value:g} {spec.target_unit}",
                       detail=f"Sources me is daawe ke jaisa ({spec.dimension}) "
                              "koi naapa hua number nahi mila.")
    ok, bad = [], []
    for tag, quantity in rows:
        holds = (quantity.si > spec.target_si if spec.relation == "gt"
                 else quantity.si < spec.target_si)
        (ok if holds else bad).append((tag, quantity))
    sign = ">" if spec.relation == "gt" else "<"
    expected = f"{sign} {spec.target_value:g} {spec.target_unit}"

    def show(rows_in: Sequence[Tuple[str, Any]]) -> str:
        return ", ".join(f"{q.label()}" + (f" [{t}]" if t else "")
                         for t, q in rows_in[:4])

    if ok and bad:
        return _result(spec, DATA_MISSING,
                       reason_code="mixed_evidence_no_verdict", expected=expected,
                       observed=show(ok + bad),
                       evidence_ids=[t for t, _ in (ok + bad) if t],
                       detail=f"Daawa poora karte hain: {show(ok)}; ulta kehte "
                              f"hain: {show(bad)}. Dono taraf evidence hai, "
                              "isliye koi ek nateeja nahi nikala gaya.")
    if ok:
        return _result(spec, TESTED_PASS, expected=expected, observed=show(ok),
                       evidence_ids=[t for t, _ in ok if t],
                       reason_code="all_measurements_satisfy",
                       detail=f"Sources ke {len(ok)} naape hue number is daawe "
                              "ke saath hain.")
    return _result(spec, TESTED_FAIL, expected=expected, observed=show(bad),
                   evidence_ids=[t for t, _ in bad if t],
                   reason_code="measurements_contradict",
                   detail=f"Sources ke {len(bad)} naape hue number is daawe ke "
                          "ULTE hain.")


def _run_direction(spec: TestSpec, policy: LabPolicy,
                   executor: SafeNumericExecutor) -> TestResult:
    """"Badhega/ghatega" — hypothesis ke khud ke numbers ulta keh rahe hain?

    Ye test SIRF tab chalta hai jab text me saaf joda ho ("from A to B",
    "A se B tak", "A → B"). Bina baseline aur outcome ke, do numbers ka kram
    kuch sabit nahi karta — isliye us case me hum jaan-boojh kar koi verdict
    nahi dete.
    """
    pair, problem = _direction_pair(spec.text)
    if pair is None:
        return _result(spec, DATA_MISSING, reason_code=problem,
                       detail=("Text me \"A se B\" jaisa saaf joda nahi tha, "
                               "isliye ghatna-badhna naapa nahi ja saka."
                               if problem == "no_baseline_and_outcome_pair" else
                               "Joda mila, par dono taraf ek hi tarah ka "
                               "naapne layak (number + unit) nahi tha."))
    start, end = pair
    delta = end.si - start.si
    observed = f"{start.label()} → {end.label()}"
    if delta == 0:
        return _result(spec, DATA_MISSING, reason_code="no_change_in_numbers",
                       observed=observed,
                       detail="Dono number barabar hain — na badhna, na ghatna.")
    moved_up = delta > 0
    consistent = moved_up == (spec.direction == "up")
    word = "badhne" if spec.direction == "up" else "ghatne"
    return _result(spec, TESTED_PASS if consistent else TESTED_FAIL,
                   observed=observed,
                   expected=f"{word} ka daawa",
                   computed=delta,
                   reason_code=("numbers_match_direction" if consistent
                                else "numbers_contradict_direction"),
                   detail=(f"Likhe hue numbers {'badh' if moved_up else 'ghat'} "
                           f"rahe hain, aur daawa {word} ka tha — "
                           + ("dono ek hi taraf." if consistent
                              else "yaani hypothesis apne hi numbers se ulti hai.")))


def _run_proportion_interval(spec: TestSpec, policy: LabPolicy,
                             executor: SafeNumericExecutor) -> TestResult:
    """k/n par Wilson interval — chhota ya patla sample koi verdict nahi deta."""
    successes = int(spec.successes or 0)
    total = int(spec.total or 0)
    if total <= 0 or successes < 0 or successes > total:
        return _result(spec, DATA_MISSING, reason_code="counts_not_usable",
                       detail="Ginti samajh nahi aayi (k, n theek nahi).")
    if total < policy.min_proportion_sample:
        return _result(spec, DATA_MISSING, reason_code="sample_too_small",
                       observed=f"{successes}/{total}",
                       detail=f"Sample sirf {total} ka hai (chhat "
                              f"{policy.min_proportion_sample}). Itne se koi "
                              "bharosemand nateeja nahi nikalta.")
    low, high = wilson_interval(successes, total)
    band = f"{low * 100:.1f}%–{high * 100:.1f}% (95% Wilson)"
    if spec.claimed_proportion is None:
        return _result(spec, DATA_MISSING, reason_code="no_claimed_proportion",
                       observed=f"{successes}/{total} → {band}",
                       detail="Observed range nikal gayi, par hypothesis ne "
                              "koi number wala daawa kiya hi nahi — isliye "
                              "pass/fail ka sawaal nahi.")
    claimed = float(spec.claimed_proportion)
    inside = low <= claimed <= high
    if inside and (high - low) > 0.5:
        return _result(spec, DATA_MISSING,
                       reason_code="interval_too_wide_underpowered",
                       observed=band, expected=f"{claimed * 100:.1f}%",
                       detail="Range itni chaudi hai ki ye daawa aur uska ulta "
                              "dono usme aa jaate hain — sample chhota hai, "
                              "test kuch sabit nahi karta.")
    return _result(spec, TESTED_PASS if inside else TESTED_FAIL,
                   observed=band, expected=f"{claimed * 100:.1f}%",
                   computed=(low + high) / 2.0,
                   reason_code=("claim_inside_interval" if inside
                                else "claim_outside_interval"),
                   detail=(f"{successes}/{total} se bani range {band} me daawa "
                           + ("aata hai — data iske khilaaf nahi."
                              if inside else "NAHI aata — data isse ulta hai.")))


# ── walk-forward (#118): asli train → held-out test ──────────────────────────
# `series_data_missing` ka naam #116 se WAHI rakha gaya hai — report ki line,
# audit ki line aur test uspar tike hain, aur data lane judne se ye baat badalti
# nahi: series na ho to aaj bhi koi backtest nahi chalta. Baaki code naye hain,
# kyunki "series thi par test-layak nahi thi" aur "series hi nahi thi" ek jaise
# report karna wahi purana jhooth hota.
_WF_NOT_RUN: Dict[str, str] = {
    market_data.NO_SERIES: (
        "Is daawe ke liye time-ordered data chahiye (train → held-out, "
        "walk-forward). Aisa koi series yahan maujood nahi hai, isliye koi "
        "backtest chalaya hi nahi gaya — is number ko 'test ho chuka' mat "
        "samjho."),
    market_data.NO_PERIODS: (
        "Evidence me numbers the par unke saath koi period (saal/mahina/"
        "quarter) nahi tha, isliye time-order hi nahi bana — koi backtest "
        "chalaya hi nahi gaya."),
    market_data.TOO_SHORT: (
        "Series itni chhoti hai ki usme train aur held-out dono nahi bante. "
        "Itne data par 'test pass' likhna muft ka credit hota, isliye koi "
        "backtest chalaya hi nahi gaya."),
    market_data.IRREGULAR: (
        "Periods me gaps/duplicate the (barabar step nahi), isliye walk-forward "
        "ka matlab hi nahi banta — koi backtest chalaya hi nahi gaya."),
    market_data.MIXED: (
        "Ek hi series me saal, mahina aur quarter mile-jule the. Unhe jodna "
        "khud ek galti hoti, isliye koi backtest chalaya hi nahi gaya."),
    market_data.CONFLICT: (
        "Ek hi period par do alag values mili — kaunsi sahi hai ye evidence se "
        "tay nahi hota, isliye koi backtest chalaya hi nahi gaya."),
    market_data.UNIT_MISMATCH: (
        "Series ke points alag-alag unit me the (jaise % aur ₹ crore), aur unka "
        "aapas me hisaab bekaar hota — isliye koi backtest chalaya hi nahi gaya."),
    market_data.HOLDOUT_SMALL: (
        f"Held-out hissa {market_data.MIN_HOLDOUT_POINTS} point se bhi chhota "
        "reh gaya. Itne se koi bharosemand nateeja nahi nikalta, isliye koi "
        "backtest chalaya hi nahi gaya."),
    market_data.FLAT_HOLDOUT: (
        "Held-out hisse me value hili hi nahi. Aise data par har model 'sahi' "
        "lagta hai, isliye ise pass/fail nahi maana gaya — koi asli muqabla "
        "hua hi nahi."),
}

# "Series thi, par test-layak nahi thi" — NO_SERIES yahan JAAN-BOOJH KAR nahi
# hai, kyunki uska matlab ulta hai (series hi nahi thi). Dono ko ek bucket me
# daalna audit line ko jhootha bana deta.
_WF_UNUSABLE_CODES: Tuple[str, ...] = tuple(
    code for code in _WF_NOT_RUN if code != market_data.NO_SERIES)


def _wf_detail(reason_code: str) -> str:
    """Har na-chalne wali wajah ka apna text. Anjaan code par bhi jhooth nahi."""
    known = _WF_NOT_RUN.get(reason_code or "")
    if known:
        return known
    return (f"Walk-forward test chalaya hi nahi gaya (wajah: "
            f"{reason_code or 'pata nahi'}) — is number ko 'test ho chuka' mat "
            "samjho.")


def _series_label(series: Any) -> str:
    """Series kahan se aayi — provider + id + kitne point. Guess nahi."""
    provider = str(getattr(series, "provider", "") or "unknown-source")
    series_id = str(getattr(series, "series_id", "") or "")
    points = getattr(series, "points", None) or ()
    frequency = str(getattr(series, "frequency", "") or "")
    bits = [provider + (f"/{series_id}" if series_id else "")]
    if frequency:
        bits.append(frequency)
    bits.append(f"{len(points)} point")
    return ", ".join(bits)


def _run_walk_forward(spec: TestSpec, policy: LabPolicy,
                      executor: SafeNumericExecutor) -> TestResult:
    """Asli walk-forward backtest: train → held-out, naive baseline se muqabla.

    Yahan koi network call NAHI hoti. Series discovery ne laayi hai (record ke
    `series_meta` se) ya evidence text se nikli hai, aur `plan_specs` use
    `spec.series` me rakh chuki hai — isliye lab ka `network_used: False`
    waada waisa hi sach rehta hai.

    Pass ka matlab SIRF itna hai: is purane data par drift model naive
    random-walk baseline se kam galti karta tha. Ye "forecast sahi hai" ya
    "aage bhi chalega" NAHI hai, aur financial advice bilkul nahi.
    """
    series = spec.series
    if series is None or not getattr(series, "points", None):
        reason = spec.series_reason or market_data.NO_SERIES
        return _result(spec, DATA_MISSING, reason_code=reason,
                       detail=_wf_detail(reason))

    outcome = market_data.walk_forward(
        series,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction)
    label = _series_label(series)
    source_ids = [str(sid) for sid in (getattr(series, "source_ids", None) or ())
                  if str(sid)]

    if not outcome.ok:
        return _result(spec, DATA_MISSING,
                       reason_code=outcome.reason_code or market_data.NO_SERIES,
                       observed=label, evidence_ids=source_ids,
                       detail=_wf_detail(outcome.reason_code))

    beats = outcome.beats_naive
    observed = (f"{label} | train {outcome.n_train} → held-out {outcome.n_test} "
                f"({outcome.holdout_first}…{outcome.last_period}) | "
                f"MAE model {outcome.model_mae:.4g} vs naive "
                f"{outcome.naive_mae:.4g} | disha {outcome.hits}/{outcome.scored}")
    ratio = (outcome.model_mae / outcome.naive_mae
             if outcome.naive_mae > 0 else None)

    # Held-out bilkul flat — naive baseline ki galti 0 thi, to muqabla hi nahi
    # hua. Ise pass kehna sabse saaf jhooth hota.
    if beats is None:
        return _result(spec, DATA_MISSING, reason_code=market_data.FLAT_HOLDOUT,
                       observed=observed, evidence_ids=source_ids,
                       detail=_wf_detail(market_data.FLAT_HOLDOUT))

    passed = bool(beats)
    # The same measured series can be stressed without inventing a digital
    # twin, transition matrix, or physical calibration.  These scenarios are
    # synthetic falsification probes only; they never change the historical
    # walk-forward verdict or claim future robustness.
    try:
        stress = simulation_lab.black_swan_suite(
            series.values(), seed=policy.seed)
        stress_test = {
            "ran": True,
            "scenario_hash": stress.scenario_hash,
            "scenario_count": len(stress.scenarios),
            "scenarios": [
                {
                    "name": row.name,
                    "max_abs_step": row.max_abs_step,
                    "max_drawdown_abs": row.max_drawdown_abs,
                    "finite": row.finite,
                }
                for row in stress.scenarios
            ],
            "synthetic_only": stress.synthetic_only,
            "future_guarantee": stress.future_guarantee,
            "source_ids": source_ids,
        }
    except Exception:
        stress_test = {
            "ran": False,
            "reason": "stress_suite_failed_closed",
            "synthetic_only": True,
            "future_guarantee": False,
            "source_ids": source_ids,
        }
    return _result(
        spec, TESTED_PASS if passed else TESTED_FAIL,
        observed=observed,
        expected="naive random-walk baseline se KAM galti (MAE)",
        computed=ratio, evidence_ids=source_ids,
        reason_code=("model_beats_naive_baseline" if passed
                     else "model_loses_to_naive_baseline"),
        stress_test=stress_test,
        detail=((f"Held-out {outcome.n_test} period par model ki galti naive "
                 f"baseline se kam rahi (MAE {outcome.model_mae:.4g} < "
                 f"{outcome.naive_mae:.4g}). "
                 if passed else
                 f"Held-out {outcome.n_test} period par model naive baseline se "
                 f"HAAR gaya (MAE {outcome.model_mae:.4g} >= "
                 f"{outcome.naive_mae:.4g}) — is daawe ko data ne support nahi "
                 "kiya. ")
                + market_data.BACKTEST_NOTE + " "
                + market_data.NOT_ADVICE_NOTE))


RECIPES: Dict[str, Any] = {
    "numeric_formula": _run_numeric_formula,
    "threshold": _run_threshold,
    "direction": _run_direction,
    "proportion_interval": _run_proportion_interval,
    "walk_forward": _run_walk_forward,
}


def run_specs(specs: Sequence[TestSpec], policy: Optional[LabPolicy] = None,
              executor: Optional[SafeNumericExecutor] = None,
              deadline: Optional[float] = None) -> List[TestResult]:
    """Har spec ko uski recipe se chalao. Kuch bhi galat ho to NOT_RUN.

    Fail-closed: andar ka koi error kabhi TESTED_PASS nahi ban sakta.
    """
    policy = policy or LabPolicy()
    executor = executor or SafeNumericExecutor(NumericExecutionPolicy())
    results: List[TestResult] = []
    for spec in specs:
        if deadline is not None and time.monotonic() > deadline:
            results.append(_result(spec, NOT_RUN, reason_code="budget_exhausted",
                                   detail="Lab ka time budget khatam ho gaya, "
                                          "ye test chalaya hi nahi gaya."))
            continue
        runner = RECIPES.get(spec.recipe)
        if runner is None:
            results.append(_result(spec, NOT_TESTABLE_HERE,
                                   reason_code="unknown_recipe",
                                   detail=f"'{spec.recipe}' naam ki koi test "
                                          "recipe nahi hai."))
            continue
        try:
            results.append(runner(spec, policy, executor))
        except Exception as exc:      # noqa: BLE001 — fail-closed by design
            results.append(_result(spec, NOT_RUN, reason_code="internal_error",
                                   detail=f"Test chalate waqt andar dikkat aayi "
                                          f"({type(exc).__name__}) — isliye koi "
                                          "nateeja nahi maana gaya."))
    return results


def rollup(results: Sequence[TestResult]) -> str:
    """Poore hypothesis ka ek nateeja. Ek FAIL sab par bhaari padta hai."""
    present = {r.status for r in results}
    for status in _ROLLUP_ORDER:
        if status in present:
            return status
    return NOT_TESTABLE_HERE


_ROLLUP_REASON: Dict[str, str] = {
    TESTED_FAIL: "app ke apne test me ye hypothesis fail hui",
    TESTED_PASS: "app ke andar ke hisaab/consistency test pass hue (asli "
                 "duniya ka experiment abhi baaki)",
    DATA_MISSING: "test banaya gaya par usko chalane ka data nahi mila",
    NOT_TESTABLE_HERE: "is hypothesis ka koi hissa yahan naapa nahi ja sakta",
    NOT_RUN: "test chalaya hi nahi gaya",
}


def _why_not_testable(hypothesis: Dict[str, Any]) -> Tuple[str, str]:
    """Koi test hi nahi ban paayi — wajah do me se ek, aur wo saaf likhi jaaye."""
    plan = _text_of(hypothesis, "experiment", "how_to_test", "falsification_test")
    if _HUMAN_LAB_RE.search(plan or ""):
        return ("needs_real_world_experiment",
                "Iska test asli lab/field me hoga (samples, insaan, hardware "
                "ya observation time) — wo is machine ke andar ho hi nahi "
                "sakta, isliye koshish bhi nahi ki gayi.")
    return ("no_computable_claim",
            "Is hypothesis me koi naapne layak number, threshold ya ginti "
            "likhi hi nahi gayi, isliye yahan chalane wala koi test nahi bana.")


def run_lab(question: str, hypotheses: Sequence[Dict[str, Any]],
            pack: Any = None, policy: Optional[LabPolicy] = None,
            kill_switch: bool = False) -> Dict[str, Any]:
    """LAB stage: hypothesis → test spec → asli hisaab → imaandaar nateeja.

    Input dicts ko chhua nahi jaata (copy bhi nahi banate — sirf padhte hain),
    isliye ye stage confidence, validation ya novelty kabhi nahi badalta.
    """
    policy = policy or LabPolicy()
    executor = SafeNumericExecutor(NumericExecutionPolicy())
    rows = [h for h in (hypotheses or []) if isinstance(h, dict)]
    report: Dict[str, Any] = {
        "ran": False,
        "kill_switch": bool(kill_switch),
        "policy": policy.to_dict(),
        "executor": executor.policy_report(),
        "seed": policy.seed,
        "gemini_calls": 0,
        "provider_cost": 0,
        "hypotheses": [],
        "counts": {status: 0 for status in LAB_STATUSES},
        "budget_exhausted": False,
        "warnings": [],
        "disclaimer": LAB_DISCLAIMER,
        "note": "",
    }
    if not rows:
        report["note"] = ("Koi hypothesis nahi thi, isliye lab stage chala hi "
                          "nahi — ye 'test fail hua' nahi hai.")
        return report
    deadline = time.monotonic() + policy.max_wall_seconds
    for index, hypothesis in enumerate(rows):
        block: Dict[str, Any] = {
            "hypothesis_id": str(hypothesis.get("hypothesis_id") or ""),
            "statement": str(hypothesis.get("statement") or "")[:240],
            "requires_risk_review": bool(hypothesis.get("safety_sensitive")),
            "tests": [],
            "is_established_fact": False,
            "real_world_experiment_pending": True,
        }
        if kill_switch:
            block["verdict"] = NOT_RUN
            block["verdict_reason"] = "kill_switch"
            block["detail"] = ("Lab stage band tha (kill switch), isliye koi "
                               "test nahi chala.")
        elif index >= policy.max_hypotheses:
            block["verdict"] = NOT_RUN
            block["verdict_reason"] = "hypothesis_budget"
            block["detail"] = (f"Ek run me sirf {policy.max_hypotheses} "
                               "hypotheses tak test hoti hain.")
        else:
            specs = plan_specs(hypothesis, pack, policy, question)
            if not specs:
                code, detail = _why_not_testable(hypothesis)
                block["verdict"] = NOT_TESTABLE_HERE
                block["verdict_reason"] = code
                block["detail"] = detail
            else:
                results = run_specs(specs, policy, executor, deadline)
                block["tests"] = [r.to_dict() for r in results]
                block["verdict"] = rollup(results)
                block["verdict_reason"] = _ROLLUP_REASON[block["verdict"]]
                block["detail"] = "; ".join(r.detail for r in results
                                            if r.detail)[:900]
                report["ran"] = True
                if any(r.status == NOT_RUN and r.reason_code == "budget_exhausted"
                       for r in results):
                    report["budget_exhausted"] = True
        report["counts"][block["verdict"]] += 1
        if block["requires_risk_review"]:
            block["risk_note"] = RISK_REVIEW_NOTE
        report["hypotheses"].append(block)
    if report["budget_exhausted"]:
        report["warnings"].append(
            "Lab ka time budget khatam hua — kuch test chale hi nahi. Unhe "
            "'fail' nahi, 'nahi hua' padha jaaye.")
    if not report["ran"] and not kill_switch:
        report["note"] = ("Hypotheses thi, par unme se koi bhi yahan naapi ja "
                          "sakne wali nahi nikli — wajah har hypothesis ke "
                          "saath likhi hai.")
    return report


# ── jawab me kya likha jaayega ────────────────────────────────────────────────
# Ye `## APP ORIGINAL RESEARCH LAB` heading KHUD nahi banata (wo answer_order
# ka hissa hai) — ye uske andar jaane wala `###` block deta hai.
LAB_SUBHEADING = "### App ne khud kya test kiya (LAB)"

_VERDICT_LABEL: Dict[str, str] = {
    TESTED_PASS: "TESTED_PASS — app ke andar ka test pass (proof nahi)",
    TESTED_FAIL: "TESTED_FAIL — app ke apne test me fail",
    DATA_MISSING: "DATA_MISSING — test bana, data nahi mila",
    NOT_TESTABLE_HERE: "NOT_TESTABLE_HERE — yahan naapa hi nahi ja sakta",
    NOT_RUN: "NOT_RUN — chalaya hi nahi gaya",
}


def lab_report_section(report: Optional[Dict[str, Any]]) -> str:
    """LAB ka nateeja padhne layak Hinglish block. Khaali report par ""."""
    if not isinstance(report, dict) or not report.get("hypotheses"):
        return ""
    lines: List[str] = [LAB_SUBHEADING, "", report.get("disclaimer")
                        or LAB_DISCLAIMER, ""]
    for block in report["hypotheses"]:
        title = block.get("hypothesis_id") or "hypothesis"
        verdict = str(block.get("verdict") or NOT_RUN)
        lines.append(f"**{title}** — {_VERDICT_LABEL.get(verdict, verdict)}")
        statement = str(block.get("statement") or "").strip()
        if statement:
            lines.append(f"- Daawa: {statement}")
        reason = str(block.get("verdict_reason") or "")
        if reason:
            lines.append(f"- Kyun: {reason}")
        for test in block.get("tests") or []:
            bits = [f"`{test.get('recipe')}`", str(test.get("status"))]
            if test.get("observed"):
                bits.append(f"naapa: {test['observed']}")
            if test.get("expected"):
                bits.append(f"daawa: {test['expected']}")
            lines.append("  - " + " | ".join(bits))
            if test.get("detail"):
                lines.append(f"    {test['detail']}")
        if block.get("risk_note"):
            lines.append(f"- ⚠️ {block['risk_note']}")
        lines.append("")
    for warning in report.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    if report.get("note"):
        lines.append(f"- {report['note']}")
    return "\n".join(lines).rstrip() + "\n"


def lab_limits(report: Optional[Dict[str, Any]]) -> List[str]:
    """Wo seemayein jo LAB ke baad BHI sach hain — jawab ke audit me jaati hain.

    Purana `verification_claude.simulation_limits()` har simulation/forecast
    wali baat par ek hi line lagata tha ("ye engine khud nahi chalata"). Wo
    line ab aadhi galat hai: kuch test sach me chalte hain. Isliye seema ab
    NAAPI hui hai — jo chala uska naam, aur jo nahi chala uski wajah.
    """
    if not isinstance(report, dict) or not report.get("hypotheses"):
        return []
    limits: List[str] = []
    counts = report.get("counts") or {}
    if counts.get(TESTED_PASS):
        limits.append(
            f"{counts[TESTED_PASS]} hypothesis app ke apne andar ke test "
            "(hisaab/consistency) me pass hui — ye asli duniya ka experiment "
            "NAHI hai, aur ise 'proven' nahi padha jaaye.")
    if counts.get(TESTED_FAIL):
        limits.append(
            f"{counts[TESTED_FAIL]} hypothesis app ke apne test me FAIL hui — "
            "usko jawab ke core hisse me support ke tor par use nahi kiya gaya.")
    series_missing = any(
        test.get("reason_code") == "series_data_missing"
        for block in report["hypotheses"] for test in (block.get("tests") or []))
    if series_missing:
        limits.append(
            "Forecast/backtest wale daawe ke liye time-ordered data nahi tha, "
            "isliye koi walk-forward test chalaya hi nahi gaya. Un numbers ko "
            "'run karke verify kiya gaya' mat samjho.")
    # Series MILI thi par test-layak nahi thi (chhoti, gaps wali, unit-mixed,
    # ya flat held-out). Ye "data nahi tha" se ALAG baat hai, aur dono ko ek
    # line me daalna wahi purana jhooth hota — isliye alag line.
    unusable = sorted({
        str(test.get("reason_code") or "")
        for block in report["hypotheses"] for test in (block.get("tests") or [])
        if test.get("recipe") == "walk_forward"
        and str(test.get("reason_code") or "") in _WF_UNUSABLE_CODES})
    if unusable:
        limits.append(
            "Series banane ki koshish hui par wo backtest-layak nahi nikli (" +
            ", ".join(unusable) + "), isliye us daawe par koi walk-forward "
            "nateeja nahi hai — na pass, na fail.")
    # Jo backtest SACH ME chala, uski seema bhi likhna zaroori hai: wo purane
    # data par chala hai, aur uska pass hona future ka waada nahi hai.
    ran_backtest = sum(
        1 for block in report["hypotheses"] for test in (block.get("tests") or [])
        if test.get("recipe") == "walk_forward"
        and test.get("status") in (TESTED_PASS, TESTED_FAIL))
    if ran_backtest:
        limits.append(
            f"{ran_backtest} walk-forward backtest sach me chala, par sirf "
            "PURANE (out-of-sample) data par — purane data par sahi nikalna "
            "future ka waada NAHI hai, aur ye financial advice nahi hai.")
    if report.get("budget_exhausted"):
        limits.append("Lab ka time budget khatam hua — kuch test adhoore rahe.")
    return limits


def verdict_for(report: Optional[Dict[str, Any]], hypothesis_id: str) -> str:
    """Ek hypothesis ka lab verdict — na mile to NOT_RUN (kabhi PASS nahi)."""
    if not isinstance(report, dict):
        return NOT_RUN
    for block in report.get("hypotheses") or []:
        if str(block.get("hypothesis_id") or "") == str(hypothesis_id or ""):
            return str(block.get("verdict") or NOT_RUN)
    return NOT_RUN


def merge_into_hypotheses(hypotheses: Sequence[Dict[str, Any]],
                          report: Optional[Dict[str, Any]]
                          ) -> List[Dict[str, Any]]:
    """Har hypothesis dict ki COPY me `lab` block jodo.

    Purani keys (confidence band, validation, novelty) chhui nahi jaati — lab
    ka nateeja unke saath rehta hai, unki jagah nahi leta.
    """
    blocks = list((report or {}).get("hypotheses") or [])
    by_id = {str(b.get("hypothesis_id") or ""): b for b in blocks
             if str(b.get("hypothesis_id") or "")}
    out: List[Dict[str, Any]] = []
    for index, hypothesis in enumerate(hypotheses or []):
        if not isinstance(hypothesis, dict):
            continue
        copy = dict(hypothesis)
        hid = str(hypothesis.get("hypothesis_id") or "")
        block = by_id.get(hid)
        if block is None and not hid and index < len(blocks):
            # ID enrich() ke bina khaali reh sakti hai — tab kram se milaate hain.
            block = blocks[index]
        copy["lab"] = dict(block) if block else {
            "verdict": NOT_RUN, "verdict_reason": "lab_did_not_run",
            "tests": [], "is_established_fact": False,
            "real_world_experiment_pending": True,
        }
        copy["lab_verdict"] = copy["lab"].get("verdict") or NOT_RUN
        out.append(copy)
    return out
