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

Aath recipe (sab deterministic):
  numeric_formula     — hypothesis ka apna formula dobara chala kar naapo
  threshold           — "X se zyada/kam" wala daawa evidence ke numbers se naapo
  direction           — "badhega/ghatega" khud ke numbers se ulta hai ya nahi
  proportion_interval — "k of n" par Wilson interval; chhota sample = koi verdict nahi
  walk_forward        — asli train → held-out backtest (naive baseline se muqabla);
                        series na ho to DATA_MISSING, jhoothi "chal gaya" nahi
  monte_carlo         — held-out ke asli per-step nateeje ko dobara-dobara jod kar
                        drawdown / losing streak / risk-of-ruin, aur usse risk per
                        trade. "Thousands of random simulations" ka jhooth NAHI:
                        ye deterministic block-resample hai aur asli path ginti
                        report hoti hai (#150e)
  parameter_robustness— ek hi magic number par tikka edge FAIL hai. Drift lookback
                        badal kar dekha jaata hai ki edge ek REGION me zinda hai
  baseline_tournament — model ko paanch simple baseline (naive, momentum,
                        mean-reversion, moving average, linear trend) me se HAR ek
                        ko held-out par haraana padega, warna "complex model" ka
                        koi haq nahi

#171e — EXAM/PADHAI ke paanch naye recipe. Ye upar wale aath ke UPAR bane hain,
unki jagah nahi lete: hypothesis ka rasta ek bit nahi badalta (in specs ka
janam `plan_exam_specs()` se hota hai, `plan_specs()` se nahi). Naapa jaata hai
BANA HUA paper/plan, kisi ka daawa nahi:
  syllabus_coverage   — syllabus ke kitne topic par ASLI me question bana
  difficulty_mix      — sab question ek hi band me gire ya mix hua (proxy naap,
                        aur ye baat report me likhi jaati hai)
  duplicate_questions — do question ek jaise nikle ya nahi (shabd ke overlap se)
  question_solvability— ginti wale question ka hissa bounded calculator me
                        CHALA kar dekha gaya; calculator na mile to NOT MEASURED
  plan_time_budget    — plan ka jodha hua time vs asli me mila hua time, aur
                        kisi ek din ka bojh insaani hadd me hai ya nahi

Status shabd (isse bahar kuch nahi):
  TESTED_PASS, TESTED_FAIL, DATA_MISSING, NOT_TESTABLE_HERE, NOT_RUN
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field, replace as dataclass_replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import physics_checks
from . import market_data
from . import simulation_lab
# #171e — exam/padhai ka naapne wala saamaan wahin rehta hai jahan uska parse
# hota hai (`exammodel.py` leaf module hai: ye planner/discovery ko import nahi
# karta, isliye koi cycle nahi banta). Lab yahan sirf CHALATA hai — split ka
# hisaab exammodel ka hai, aur "kitna kaafi hai" ki chhat bhi wahin se aati hai.
from . import exammodel
from .advanced_discovery import NumericExecutionPolicy, SafeNumericExecutor
# #155e — reject ka code ek hi jagah rehta hai (`rejects.py` leaf module hai,
# isliye yahan import karne se koi cycle nahi banta). Naam yahan chhota rakha
# gaya hai par value wahi hai — do jagah do string rakhna hi purani galti hai.
from .rejects import HUMAN_SUBJECT_ON_CRAFT_ASK as HUMAN_SUBJECT_ON_CRAFT
# #188b — "kaunsa shabd topic ka hai" ka faisla app ke apne hygiene module se
# hota hai. `query_hygiene` is import ke liye safe hai: wo `query_builder` ko
# sirf function ke ANDAR import karta hai, isliye koi cycle nahi banta. Nayi
# keyword list banana hi purani galti hai — wahi tokenizer dobara use hota hai.
from . import query_hygiene

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
    # #150e — 4 se 8. Pehle paanch branch the aur chhat 4 thi, yaani paanchvi spec
    # (walk_forward) CHUP-CHAAP gir jaati thi jab baaki chaar ban jaayein. Ab teen
    # naye backtest-baad ke test bhi hain (monte_carlo, parameter_robustness,
    # baseline_tournament), aur aath ka matlab hai: koi bhi spec cap ki wajah se
    # nahi girti. Chhat rakhi hui hai (0 nahi) taaki wall-clock budget bacha rahe.
    # #150g — 8 se 9: `trade_expectancy` naam ki nauvi spec judi. Ye number spec
    # ki asli ginti ke saath badhna CHAHIYE, warna sabse aakhri spec chup-chaap
    # girti hai aur report me uski koi line hi nahi aati.
    # #150i — 9 se 12: teen naye naap (slot_expectancy, regime_split,
    # event_window) judi. Wahi chetavni dobara: ye number badhaye bina naya
    # branch likhna = naya test likh kar use chup-chaap gira dena.
    max_specs_per_hypothesis: int = 12
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
    # #150e — teen naye test ki chhat. Ye bhi market_data se aati hain (wahi wajah:
    # "kitna kaafi hai" ek hi jagah tay ho). In numbers ko yahan se badalna ek
    # jaan-boojh kar liya faisla hai; chupke se kuch dheela nahi hota.
    mc_min_steps: int = market_data.MC_MIN_STEPS
    mc_min_paths: int = market_data.MC_MIN_PATHS
    mc_max_p95_drawdown: float = market_data.MC_MAX_P95_DRAWDOWN
    mc_max_ruin_prob: float = market_data.MC_MAX_RUIN_PROB
    sweep_min_settings: int = market_data.SWEEP_MIN_SETTINGS
    sweep_min_beat_share: float = market_data.SWEEP_MIN_BEAT_SHARE
    # #150g — TRADE-level naap ki chhat. Wahi niyam: har number market_data se
    # mirror hota hai, do jagah do value kabhi nahi. `walk_forward` sirf "agla
    # point kitna galat guess hua" naapta hai; trading ka sawaal entry/stop/
    # target/cost ke BAAD ka hai, aur wo naap yahin se aati hai.
    trade_min_trades: int = market_data.TRADE_MIN_TRADES
    trade_r_multiples: Tuple[float, ...] = market_data.TRADE_R_MULTIPLES
    trade_stop_units: float = market_data.TRADE_STOP_UNITS
    trade_max_bars: int = market_data.TRADE_MAX_BARS
    trade_cost_fraction: float = market_data.TRADE_COST_FRACTION
    trade_min_robust_share: float = market_data.TRADE_MIN_ROBUST_SHARE
    # #150i — WAQT, HAALAT aur KHABAR ki chhat. Ye teen cheezein pehle sirf text
    # ke ishaare par grade hoti thi ("session expectancy tested" likha hai =
    # MET). Ab inki asli naap hoti hai, aur naap ki chhat bhi ek hi jagah se
    # aati hai. Do jagah do value = report kis chhat par tiki hai, ye pata hi
    # nahi chalta.
    slot_min_trades: int = market_data.SLOT_MIN_TRADES
    slot_min_slots: int = market_data.SLOT_MIN_SLOTS
    regime_min_trades: int = market_data.REGIME_MIN_TRADES
    regime_min_regimes: int = market_data.REGIME_MIN_REGIMES
    regime_trend_lookback: int = market_data.REGIME_TREND_LOOKBACK
    regime_vol_lookback: int = market_data.REGIME_VOL_LOOKBACK
    event_min_trades: int = market_data.EVENT_MIN_TRADES
    event_min_windows: int = market_data.EVENT_MIN_WINDOWS
    event_shock_units: float = market_data.EVENT_SHOCK_UNITS
    # #171e — EXAM/PADHAI ki chhat. Wahi niyam jo upar trade ke saath hai: har
    # number `exammodel` se MIRROR hota hai, do jagah do value kabhi nahi. Agar
    # ye value yahan alag likh di jaaye to report kis chhat par tiki hai ye pata
    # hi nahi chalega, aur dono chupke se alag ho jaayengi. In numbers ko badalna
    # ek jaan-boojh kar liya faisla hai — koi test inhe khud dheela nahi karta.
    exam_min_coverage_share: float = exammodel.LAB_MIN_COVERAGE_SHARE
    exam_max_band_share: float = exammodel.LAB_MAX_BAND_SHARE
    exam_max_duplicate_pairs: int = exammodel.LAB_MAX_DUPLICATE_PAIRS
    exam_min_solved_share: float = exammodel.LAB_MIN_SOLVED_SHARE
    exam_duplicate_similarity: float = exammodel.DUPLICATE_SIMILARITY
    exam_daily_minutes: float = float(exammodel.DEFAULT_DAILY_MINUTES)
    # #155e — ye run "kuch bana kar do" wali farmaish hai (gaana/kavita/script)?
    # Default False rakha gaya hai jaan-boojh kar: science aur trading ke run me
    # LAB ka bartaav ek bit bhi nahi badalta. True hone par sirf ITNA hota hai ki
    # jis hypothesis ka test INSAAN ya uske body-signal se hoga, uske liye spec
    # banti hi nahi — kyunki wo naap yahan ho hi nahi sakti.
    craft_ask: bool = False

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
            "mc_min_steps": self.mc_min_steps,
            "mc_min_paths": self.mc_min_paths,
            "mc_max_p95_drawdown": self.mc_max_p95_drawdown,
            "mc_max_ruin_prob": self.mc_max_ruin_prob,
            "sweep_min_settings": self.sweep_min_settings,
            "sweep_min_beat_share": self.sweep_min_beat_share,
            "trade_min_trades": self.trade_min_trades,
            "trade_r_multiples": list(self.trade_r_multiples),
            "trade_stop_units": self.trade_stop_units,
            "trade_max_bars": self.trade_max_bars,
            "trade_cost_fraction": self.trade_cost_fraction,
            "trade_min_robust_share": self.trade_min_robust_share,
            "slot_min_trades": self.slot_min_trades,
            "slot_min_slots": self.slot_min_slots,
            "regime_min_trades": self.regime_min_trades,
            "regime_min_regimes": self.regime_min_regimes,
            "regime_trend_lookback": self.regime_trend_lookback,
            "regime_vol_lookback": self.regime_vol_lookback,
            "event_min_trades": self.event_min_trades,
            "event_min_windows": self.event_min_windows,
            "event_shock_units": self.event_shock_units,
            "exam_min_coverage_share": self.exam_min_coverage_share,
            "exam_max_band_share": self.exam_max_band_share,
            "exam_max_duplicate_pairs": self.exam_max_duplicate_pairs,
            "exam_min_solved_share": self.exam_min_solved_share,
            "exam_duplicate_similarity": self.exam_duplicate_similarity,
            "exam_daily_minutes": self.exam_daily_minutes,
            "craft_ask": self.craft_ask,
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

# ── #155e — gaane ki farmaish par LAB gaane ko test kare, INSAAN ko nahi ─────
# Kyun (measured, live song run 2026-08-30): gaana maangne par jo hypotheses
# bani unme "listeners ki GSR 20% badhegi", "EEG alpha girega", "10 logon ka
# 7-din journaling" jaisi baatein thin. Un par LAB ne apna threshold/proportion
# test chalane ki koshish ki aur evidence text ke kisi bhi number se "naap" kar
# verdict de diya — jabki naapa gaya insaan ka body-signal tha hi nahi. Ye do
# tarah se galat tha: (1) jis cheez ka data hi nahi hai uska PASS/FAIL dena
# jhooth hai, (2) maanga gaya tha GAANA, aur test insaan par ho raha tha.
#
# Isliye ye alag list rakhi gayi hai (`_HUMAN_LAB_RE` se juda): wo "asli lab
# chahiye" batati hai, ye "insaan/uska body-signal chahiye" batati hai — dono ki
# wajah aur dono ka reopen_if alag hai. Ye sirf CRAFT farmaish par lagti hai
# (`LabPolicy.craft_ask`), taaki science/trading ke run ka ek akshar na badle.
_HUMAN_SUBJECT_RE = re.compile(
    # body/brain signal (sensor lagega — machine ke andar nahi ho sakta)
    r"\bg\.?s\.?r\b|\bgalvanic skin\b|\bskin conductance\b|\bE\.?D\.?A\b|"
    r"\be\.?e\.?g\b|\bf?\.?m\.?r\.?i\b|\bmeg\b|\bfnirs\b|\bneuroimaging\b|"
    r"\bbrain (?:scan|activity|wave)\b|\balpha (?:wave|power|band)\b|"
    r"\bheart rate\b|\bh\.?r\.?v\b|\bpulse\b|\bblood pressure\b|\bcortisol\b|"
    r"\bsaliva\b|\bpupil (?:dilation|diameter)\b|\beye[-\s]?track\w*\b|"
    r"\bbiometric\w*\b|\bwearable\b|\bskin temperature\b|\bgoosebumps?\b|"
    r"\bfrisson\b|\bchills\b|"
    # insaan ko bulakar poochhna/dekhna (log chahiye — text nahi)
    r"\blisten(?:er|ing) (?:test|study|panel|experiment|session)s?\b|"
    r"\bfocus group\b|\bsurvey\b|\bquestionnaire\b|\blikert\b|\bself[-\s]?report\w*\b|"
    r"\bjournal(?:ing|ling)\b|\bdiary study\b|\binterview\w*\b|"
    r"\brecruit (?:\d+\s+)?(?:people|listeners|participants|volunteers)\b|"
    r"\bvolunteers?\b|\brespondents?\b|\bsubjects?\b|"
    r"\bA/?B test\w*\s+(?:on|with)\s+(?:listeners?|users?|people)\b|"
    # Hinglish/Hindi
    r"\b\d+\s*logon\s+(?:par|pe|ko|se)\b|\blogon\s+(?:par|pe)\s+test\b|"
    r"\bshrota\w*\b|\bsunne\s+walon\s+(?:par|pe|se|ko)\b|"
    r"\bdil\s*ki\s*dhadkan\b|\bpaseena\b",
    re.IGNORECASE)


def human_subject_hit(*texts: str) -> str:
    """Pehla jo phrase INSAAN/uske body-signal ki maang karta hai (warna "").

    Ek hi jagah se naapa jaata hai taaki "kis shabd par roka" report me,
    reject-list me aur test me — teeno jagah bilkul wahi phrase chhape.
    """
    for text in texts:
        found = _HUMAN_SUBJECT_RE.search(str(text or ""))
        if found:
            return found.group(0).strip()
    return ""


# Hypothesis ke SAB likhe hue field ek hi kram me — spec ka darwaza, wajah ki
# line aur reject-list teeno YAHI function poochhte hain, isliye teeno jagah
# bilkul ek hi phrase chhapta hai. Do jagah do kram rakhna hi purani galti hai.
_HUMAN_SUBJECT_FIELDS = ("statement", "prediction", "prediction_text",
                         "reasoning", "experiment", "how_to_test",
                         "falsification_test")


def human_subject_phrase(hypothesis: Dict[str, Any]) -> str:
    """Is hypothesis me se wo pehla phrase jo INSAAN par naap maangta hai."""
    if not isinstance(hypothesis, dict):
        return ""
    return human_subject_hit(*(_text_of(hypothesis, key)
                               for key in _HUMAN_SUBJECT_FIELDS))


# ── #188b — "number mil gaya" ≠ "IS daawe ka number mil gaya" ────────────────
# NAAPI HUI BIMARI (offline probe, 2026-09-02). SCIENCE run (craft_ask=False),
# hypothesis "Listeners ki GSR 20% se zyada badhegi jab chorus aayega", aur
# evidence me sirf perovskite solar cell ke paper:
#
#     RESULT threshold  TESTED_PASS  all_measurements_satisfy
#            expected='> 20 %'  observed='26.1 % [S1], 24.5 % [S2]'
#
# Yaani solar cell ki efficiency se GSR ka daawa "PASS" ho gaya. Wajah: grading
# sirf DIMENSION milati thi, aur "percent" kisi bhi cheez ka hota hai. Jhoota
# PASS na-chale test se zyada khatarnaak hai — isliye do taale lagte hain, aur
# dono SIRF un dimension par jinke number ka apna koi vishay nahi hota.
#
# JAAN-BOOJH KAR KYA NAHI KIYA: physical dimension (temperature/pressure/energy
# /length/...) par ye shart NAHI lagti. Naapa hua kaaran: "Tc" jaisa 2-akshar ka
# symbol tokenizer se nikal jaata hai ("Tc 250 K se zyada hoga" ke topic shabd
# sirf ['family'] nikle), to overlap maangte hi ek SAHI test DATA_MISSING ho
# jaata. Sahi test maar dena bhi nuksaan hai — isliye scope chhota rakha gaya.
def needs_subject_match(dimension: str) -> bool:
    """Kya is dimension ke number ka apna koi vishay nahi hota?

    `percent` har cheez ka hota hai (efficiency, GSR, win rate, mehngai), aur
    `bare:<shabd>` me unit hi nahi hoti. Sirf inhi par "number kis baare me hai"
    poochha jaata hai; K/Pa/J/m/s waale number khud apna vishay bata dete hain.

    Naapa hua sach (chhupaya nahi ja raha): AAJ threshold recipe par sirf
    `percent` aata hai — `bare:*` sirf direction ke pair (`_bare_quantity`) me
    banta hai. `bare:` yahan aage ke liye likha hai, taaki koi nayi recipe
    bina-unit ginti par threshold banaye to wo bhi is shart me aa jaaye.
    """
    dim = str(dimension or "")
    return dim == "percent" or dim.startswith("bare:")


# Nateeje ke naam. String hi rehne dena — report, test aur logs inhi par tikte
# hain (do jagah do string rakhna hi purani galti hai).
REASON_HUMAN_SIGNAL = "human_signal_not_gradable_here"
REASON_SUBJECT_MISMATCH = "no_measurement_about_this_subject"

# Ye do baat likhi hui seema hain — chhupaayi nahi jaati.
SUBJECT_MATCH_KNOWN_LIMIT = (
    "Subject-milaan sirf bina-unit naap (percent / bina-unit ginti) par lagta "
    "hai. K, Pa, J, m, s jaise number apna vishay khud bata dete hain, isliye "
    "wahan purana rasta bilkul waisa hi chalta hai."
)
HUMAN_SIGNAL_KNOWN_LIMIT = (
    "Insaani signal (GSR/EEG/HRV/cortisol/listening test) ka percent daawa app "
    "ke andar PASS nahi banta — chahe kisi paper me wo number likha ho. Ye "
    "jaan-boojh kar rakha gaya hai: aisa number asli logon par naapa jaata hai, "
    "aur uska faisla app ke shabd-milaan se karna jhooth hoga."
)

# Ye list `_HUMAN_SUBJECT_RE` se JAAN-BOOJH KAR chhoti hai, aur wajah likhi ja
# rahi hai. Wo list ek DUSRA sawaal poochhti hai — "is farmaish par insaan wala
# test PLAN karna chahiye ya nahi" — jahan chaudi jaal ka nuksaan sirf itna hai
# ki ek test plan nahi hota. Yahan sawaal GRADING ka hai, jahan chaudi jaal ek
# SAHI science test ko DATA_MISSING kar degi: "pulse duration", "sky survey",
# "subjects of the study", "interview" — ye shabd optics/astronomy/statistics me
# roz aate hain. Isliye yahan sirf wo phrase hain jinka matlab insaani body/brain
# signal ya insaani panel ke alawa kuch nahi ho sakta.
_BODY_SIGNAL_RE = re.compile(
    r"\bg\.?s\.?r\b|\bgalvanic skin\b|\bskin conductance\b|\bE\.?D\.?A\b|"
    r"\be\.?e\.?g\b|\bf\.?m\.?r\.?i\b|\bfnirs\b|\bmeg\b|"
    r"\bbrain (?:scan|activity|wave)\b|\balpha (?:wave|power|band)\b|"
    r"\bh\.?r\.?v\b|\bheart rate\b|\bblood pressure\b|\bcortisol\b|"
    r"\bpupil (?:dilation|diameter)\b|\beye[-\s]?track\w*\b|"
    r"\bskin temperature\b|\bgoosebumps?\b|\bfrisson\b|"
    r"\blisten(?:er|ing) (?:test|study|panel|experiment|session)s?\b|"
    r"\bfocus group\b|\blikert\b|\bself[-\s]?report\w*\b|"
    r"\b\d+\s*logon\s+(?:par|pe|ko|se)\b|\blogon\s+(?:par|pe)\s+test\b|"
    r"\bshrota\w*\b|\bsunne\s+walon\s+(?:par|pe|se|ko)\b|"
    r"\bdil\s*ki\s*dhadkan\b|\bpaseena\b",
    re.IGNORECASE)


def body_signal_hit(*texts: str) -> str:
    """Pehla phrase jo ASLI logon ke body/brain signal ki naap maangta hai."""
    for text in texts:
        found = _BODY_SIGNAL_RE.search(str(text or ""))
        if found:
            return found.group(0).strip()
    return ""


# Chaar akshar ka stem: "badhegi/badha/badhta" ek hi jad se aate hain, aur
# "listener/listeners" ko do alag shabd maanna hi galti hoti. Stemmer library
# nahi laayi ja rahi (₹0, offline, aur ek nayi dependency ka mol nahi hai).
_SUBJECT_STEM_CHARS = 4


def _subject_stems(text: str) -> set:
    """Daawe ke topic shabd + unke chhote stem — ek hi set me."""
    stems: set = set()
    for token in query_hygiene.content_tokens(text or ""):
        stems.add(token)
        if len(token) > _SUBJECT_STEM_CHARS:
            stems.add(token[:_SUBJECT_STEM_CHARS])
    return stems


def subject_overlap(claim: str, context: str) -> str:
    """Pehla topic shabd jo daawe aur is number ke aas-paas — DONO me hai.

    Khaali wapsi ka matlab: "number to mila, par kisi shabd se ye daawe se juda
    hi nahi". Topic shabd `query_hygiene.content_tokens` se aate hain, isliye
    junk/function shabd ("ka", "hoga", "kaam") is rishte ko jhootha nahi bana
    sakte.
    """
    stems = _subject_stems(claim)
    if not stems:
        return ""
    for token in query_hygiene.content_tokens(context or ""):
        if token in stems:
            return token
        if (len(token) > _SUBJECT_STEM_CHARS
                and token[:_SUBJECT_STEM_CHARS] in stems):
            return token
    return ""


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
    # #171e — bana hua PAPER/PLAN ka parse kiya hua saamaan. Ye bhi lab khud
    # nahi banata: `exam_material()` bahar se banata hai aur `plan_exam_specs()`
    # yahan rakh deta hai — theek `series` ki tarah. None = koi paper/plan nahi
    # tha, aur tab in recipes ka nateeja DATA_MISSING hota hai (khaali PASS
    # kabhi nahi). Report me sirf GINTI jaati hai, poora paper nahi.
    exam: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        series = self.series
        exam = self.exam if isinstance(self.exam, dict) else {}
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
            # Exam saamaan ka chhota parichay — sirf ginti. Poora paper report
            # me daalna do wajah se galat hai: report bhaari ho jaati hai, aur
            # bane hue question ko "naapa hua saboot" ki tarah padha jaata hai.
            "exam_questions": int(len(exam.get("questions") or ())),
            "exam_topics": int(len(exam.get("topics") or ())),
            "exam_plan_rows": int(len(exam.get("plan_rows") or ())),
            "exam_minutes_available": float(exam.get("minutes_available") or 0.0),
            "exam_answer_key_pairs": int(exam.get("answer_key_pairs") or 0),
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
    # #150g — NAAPE hue numbers, string me nahi. `observed` ek insaan ke padhne
    # ki line hai; usko wapas parse karke faisla lena hi "declare vs derive" ka
    # ulta rasta hai. Jise numbers par grade karna hai (jaise trademodel ke
    # contract point) wo yahan se le, line se nahi. Khaali dict ka matlab: is
    # recipe ne koi structured naap nahi di.
    numbers: Dict[str, Any] = field(default_factory=dict)

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
            "numbers": dict(self.numbers),
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
    # #155e — CRAFT farmaish par: jis daawe ka naap INSAAN ya uske body-signal se
    # hoga (GSR, EEG, heart rate, journaling, survey, "10 logon par"), uski spec
    # yahan BANTI HI NAHI. Ye filter nahi, darwaza band hai: spec ban jaati to
    # `threshold`/`proportion_interval` recipe evidence text ke kisi aur number
    # ko utha kar PASS/FAIL de deti — aur wo number kisi ke shareer ka nahi hota.
    # Wajah `_why_not_testable` wahi phrase utha kar likhta hai, isliye chup-chaap
    # kuch nahi girta. Gaane ke SHABD ka naap is module ka kaam hi nahi — wo SONG
    # LAB (#141) karta hai; ye stage sirf apne andar ka hisaab naapta hai.
    if policy.craft_ask and human_subject_phrase(hypothesis):
        return []
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
        # 6-8. #150e — "backtest chal gaya" se teen ALAG sawaalon ka jawab nahi
        #      milta, isliye teen alag spec: kitna risk zinda rehta hai (MC),
        #      edge ek region me hai ya ek magic number par (sweep), aur model
        #      simple baseline se behtar hai ya nahi (tournament). Ye spec sirf
        #      tab banti hain jab SERIES asli me maujood ho — series na hone par
        #      walk_forward ki ek DATA_MISSING line kaafi hai, aur teen aur
        #      "data nahi mila" line report ko bhaari aur bekaar bana deti.
        if series is not None:
            add(recipe="monte_carlo", origin="prediction/statement",
                what=("Held-out ke asli per-step nateeje dobara-dobara jod kar "
                      "drawdown / losing streak / risk-of-ruin, aur usse risk "
                      "per trade"),
                text=claim, evidence_text=ev_text, series=series)
            add(recipe="parameter_robustness", origin="prediction/statement",
                what=("Edge ek REGION me zinda hai ya ek magic number par — "
                      "drift lookback badal kar naapa"),
                text=claim, evidence_text=ev_text, series=series)
            add(recipe="baseline_tournament", origin="prediction/statement",
                what=("Model vs paanch simple baseline (naive, momentum, "
                      "mean-reversion, moving average, linear trend) — held-out "
                      "MAE par seedha muqabla"),
                text=claim, evidence_text=ev_text, series=series)
            # 9. #150g — upar ke chaar test forecast ki GALTI naapte hain. Ye
            #    nauva test poochta hai: entry, stop, target aur COST ke baad
            #    kya bachta hai. Ye alag sawaal hai, isliye alag spec — MAE se
            #    "paisa banega" nikaal lena hi trading ka sabse aam jhooth hai.
            add(recipe="trade_expectancy", origin="prediction/statement",
                what=("Asli trade-level naap: entry/stop/target + cost ke baad "
                      "expectancy, profit factor, drawdown, MAE aur haar ki "
                      "wajah (1R…3R take-profit tulna ke saath)"),
                text=claim, evidence_text=ev_text, series=series)
            # 10-12. #150i — teen sawaal jo ab tak SIRF text ke ishaare par grade
            #     hote the ("session expectancy tested" likh dena hi kaafi tha).
            #     Ab teeno ki asli naap hoti hai, aur teeno ALAG spec hain kyunki
            #     teeno alag sawaal hain: KAB trade karein (slot), KIS HAALAT me
            #     (regime), aur KHABAR ke aas-paas kya karein (event window).
            #     Ek hi spec me daalne se ek naap ka PASS doosre ko dhak leta.
            add(recipe="slot_expectancy", origin="prediction/statement",
                what=("Waqt ke hisaab se expectancy: har slot (ghanta / weekday / "
                      "mahina / quarter) ki apni NET expectancy, aur best-worst "
                      "ka faasla — 'session' ka naam nahi, naapa hua slot"),
                text=claim, evidence_text=ev_text, series=series)
            add(recipe="regime_split", origin="prediction/statement",
                what=("Regime pehchan: har entry se PEHLE trend/volatility ka "
                      "label, aur per-regime NET expectancy — kitne hisse trade "
                      "labelled thi ye bhi naapa jaata hai"),
                text=claim, evidence_text=ev_text, series=series)
            add(recipe="event_window", origin="prediction/statement",
                what=("Macro-event khidkiyan: pre-news / release / 1-5M / 5-15M "
                      "/ 15-60M ki apni expectancy aur har khidki ka "
                      "trade / wait / avoid faisla"),
                text=claim, evidence_text=ev_text, series=series)
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


def _tagged_rows(text: str, dimension: str
                 ) -> Tuple[List[Tuple[str, Any, str]], Dict[str, str]]:
    """(source_id, Quantity, us number ki apni line) + har source ki pehli line.

    Ek hi source ka title aur snippet dono me wahi number likha ho to wo EK
    naap hai, do nahi — warna report "3 numbers mile" keh kar evidence ko
    zyada dikhata hai.

    Doosri wapsi (`titles`) #188b ke liye hai: `evidence_text()` har source ko
    title → snippet → full_text ke kram me likhta hai, isliye kisi tag ki PEHLI
    line uska title hoti hai. "[S1] 26.1%" jaisi akeli line me koi topic shabd
    hi nahi hota, isliye subject-milaan number ki line ke SAATH uske source ka
    title bhi padhta hai.
    """
    rows: List[Tuple[str, Any, str]] = []
    titles: Dict[str, str] = {}
    seen: set = set()
    for line in (text or "").splitlines():
        tag_match = _TAG_RE.match(line)
        tag = tag_match.group(1) if tag_match else ""
        body = line[tag_match.end():] if tag_match else line
        if tag and tag not in titles:
            titles[tag] = body.strip()
        for quantity in physics_checks.parse_quantities(body):
            if quantity.dimension != dimension or quantity.si is None:
                continue
            key = (tag, round(float(quantity.si), 9))
            if key in seen:
                continue
            seen.add(key)
            rows.append((tag, quantity, body.strip()))
    return rows, titles


def _tagged_quantities(text: str, dimension: str
                       ) -> List[Tuple[str, Any]]:
    """(source_id, Quantity) — purana aakar, ab `_tagged_rows` ke upar.

    Jise sirf (tag, quantity) chahiye wo yahi bulaata hai. Do jagah do parser
    rakhna hi purani galti hai, isliye asli kaam ek hi function karta hai.
    """
    rows, _titles = _tagged_rows(text, dimension)
    return [(tag, quantity) for tag, quantity, _line in rows]


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
    # #188b, TAALA 1 — bina-unit naap par insaani signal ka daawa app ke andar
    # PASS nahi ban sakta. Ye #155e ke craft-time darwaze ki JAGAH nahi hai: wo
    # spec banne se PEHLE rokta hai aur sirf craft farmaish par; ye har run me
    # GRADING ke waqt rokta hai, aur sirf percent/bina-unit dimension par.
    signal = (body_signal_hit(spec.text)
              if needs_subject_match(spec.dimension) else "")
    if signal:
        return _result(spec, DATA_MISSING, reason_code=REASON_HUMAN_SIGNAL,
                       expected=f"{spec.target_value:g} {spec.target_unit}",
                       detail=f"Ye daawa asli logon par naapi jaane wali cheez "
                              f"ka hai (\"{signal}\"). Sources me likha koi "
                              f"{spec.target_unit or 'number'} isi naap ka hai "
                              "ya kisi aur cheez ka — ye app sirf shabd padhkar "
                              "tay nahi kar sakta, isliye koi nateeja nahi diya "
                              "gaya. Asli listening/lab test hi ise naapega.")
    rows, titles = _tagged_rows(spec.evidence_text, spec.dimension)
    if not rows:
        return _result(spec, DATA_MISSING,
                       reason_code="no_matching_measurement",
                       expected=f"{spec.target_value:g} {spec.target_unit}",
                       detail=f"Sources me is daawe ke jaisa ({spec.dimension}) "
                              "koi naapa hua number nahi mila.")
    # #188b, TAALA 2 — bina-unit number ka vishay bhi milna chahiye. Context =
    # us number ki apni line + usi source ki pehli line (title), kyunki
    # "[S1] 26.1%" me koi topic shabd hi nahi hota.
    off_topic: List[Tuple[str, Any]] = []
    if needs_subject_match(spec.dimension):
        kept: List[Tuple[str, Any, str]] = []
        for tag, quantity, line in rows:
            title = titles.get(tag, "")
            context = f"{title}\n{line}" if title and title != line else line
            if subject_overlap(spec.text, context):
                kept.append((tag, quantity, line))
            else:
                off_topic.append((tag, quantity))
        rows = kept
    pairs: List[Tuple[str, Any]] = [(tag, quantity)
                                    for tag, quantity, _line in rows]
    ok, bad = [], []
    for tag, quantity in pairs:
        holds = (quantity.si > spec.target_si if spec.relation == "gt"
                 else quantity.si < spec.target_si)
        (ok if holds else bad).append((tag, quantity))
    sign = ">" if spec.relation == "gt" else "<"
    expected = f"{sign} {spec.target_value:g} {spec.target_unit}"

    def show(rows_in: Sequence[Tuple[str, Any]]) -> str:
        return ", ".join(f"{q.label()}" + (f" [{t}]" if t else "")
                         for t, q in rows_in[:4])

    # Jo number chhode gaye wo CHHUPTE nahi — teeno nateeje ke saath jaate hain.
    skipped = (f" {len(off_topic)} number is daawe ke baare me nahi tha, isliye "
               f"chhoda gaya: {show(off_topic)}." if off_topic else "")
    if not pairs:
        return _result(spec, DATA_MISSING, reason_code=REASON_SUBJECT_MISMATCH,
                       expected=expected, observed=show(off_topic),
                       evidence_ids=[t for t, _ in off_topic if t],
                       numbers={"off_topic_numbers": len(off_topic),
                                "graded_numbers": 0},
                       detail=f"Is naap ({spec.dimension}) ke {len(off_topic)} "
                              f"number mile — {show(off_topic)} — par unme se "
                              "koi is daawe ke baare me nahi tha (na number ki "
                              "line me, na uske source ke title me daawe ka koi "
                              "shabd). Bina-unit ginti har cheez ki hoti hai, "
                              "isliye sirf number milne par nateeja nahi nikala.")
    if ok and bad:
        return _result(spec, DATA_MISSING,
                       reason_code="mixed_evidence_no_verdict", expected=expected,
                       observed=show(ok + bad),
                       evidence_ids=[t for t, _ in (ok + bad) if t],
                       detail=f"Daawa poora karte hain: {show(ok)}; ulta kehte "
                              f"hain: {show(bad)}. Dono taraf evidence hai, "
                              "isliye koi ek nateeja nahi nikala gaya." + skipped)
    if ok:
        return _result(spec, TESTED_PASS, expected=expected, observed=show(ok),
                       evidence_ids=[t for t, _ in ok if t],
                       reason_code="all_measurements_satisfy",
                       detail=f"Sources ke {len(ok)} naape hue number is daawe "
                              "ke saath hain." + skipped)
    return _result(spec, TESTED_FAIL, expected=expected, observed=show(bad),
                   evidence_ids=[t for t, _ in bad if t],
                   reason_code="measurements_contradict",
                   detail=f"Sources ke {len(bad)} naape hue number is daawe ke "
                          "ULTE hain." + skipped)


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


# ── #150e: backtest ke BAAD ke teen test ───────────────────────────────────────
# Teeno ki ek hi shakal hai: series → walk_forward → uske ASLI nateeje par ek
# aur naap. Isliye "series thi ya nahi" aur "walk-forward chala ya nahi" wali
# do wajah ek hi jagah se aati hain (`_series_outcome`) — do jagah likhne se
# dono chupke se alag ho jaati hain aur report kis wajah par ruki, ye pata hi
# nahi chalta.
_MC_NOT_RUN: Dict[str, str] = {
    market_data.FEW_STEPS: (
        f"Held-out me {market_data.MC_MIN_STEPS} step se kam the. Itne se "
        "drawdown/ruin ka koi distribution nahi banta, isliye koi simulation "
        "chalaya hi nahi gaya — 'risk per trade itna rakho' yahan se nahi aata."),
    market_data.NO_STEP_MOVED: (
        "Held-out ke saare step 0 the (model ne kabhi koi taraf hi nahi kaha). "
        "Aise data par har risk 'safe' dikhta, isliye koi simulation nahi chala."),
    market_data.FEW_PATHS: (
        "Deterministic resample se itne alag path bane hi nahi ki percentile ka "
        "matlab bane, isliye koi verdict nahi diya gaya."),
}
_SWEEP_NOT_RUN: Dict[str, str] = {
    market_data.FEW_SETTINGS: (
        f"{market_data.SWEEP_MIN_SETTINGS} se kam parameter setting chal payi "
        "(series chhoti hai), isliye 'edge ek region me hai' ya 'ek magic number "
        "par hai' — is sawaal ka jawab hi nahi nikla."),
}
_TOURNAMENT_NOT_RUN: Dict[str, str] = {
    market_data.NO_BASELINE: (
        "Koi bhi baseline held-out par forecast bana hi nahi paaya, isliye "
        "muqabla hua hi nahi — 'model jeet gaya' kehna yahan jhooth hota."),
}
# #150g — trade-level naap kis wajah se nahi chali. Har wajah ASLI kami batati
# hai, "feature nahi hai" nahi (feature hai).
_TRADE_NOT_RUN: Dict[str, str] = {
    market_data.FEW_TRADES: (
        f"Held-out hisse me {market_data.TRADE_MIN_TRADES} se kam poore trade "
        f"bane (entry se exit tak), isliye expectancy / profit factor naapa hi "
        f"nahi gaya. Is naap ke liye takreeban "
        f"{market_data.TRADE_MIN_SERIES_POINTS}+ point ki series chahiye — "
        "chhote sample par 'edge mil gaya' kehna sabse aam backtest jhooth hai."),
    market_data.NO_VOLATILITY: (
        "Train hisse me koi harkat hi nahi thi, isliye stop ki naap (SL kitni "
        "door) ban hi nahi saki — aur bina stop ke R-multiple, expectancy aur "
        "MAE ka koi matlab nahi hota."),
    market_data.NO_LOSS_TO_MEASURE: (
        "Sample me ek bhi haarne wala trade nahi tha, isliye loss-side (profit "
        "factor, average loss, tail loss) naapa hi nahi gaya. Aisa sample 'edge "
        "mil gaya' ka saboot NAHI hai — ye sirf itna kehta hai ki is chhote "
        "hisse me haar aayi hi nahi."),
}
# #150i — WAQT ki naap kis wajah se nahi chali. Yahan sabse zaroori baat: in
# wajahon me se koi bhi "edge nahi hai" nahi kehti. Ye sab "naap HO HI NAHI
# SAKI" kehti hain, aur isliye ye DATA_MISSING hain — TESTED_FAIL nahi.
_SLOT_NOT_RUN: Dict[str, str] = {
    market_data.SLOT_TOO_COARSE: (
        "Series saal-saal ki hai. Saal ke andar 'kaunsa waqt behtar' ka koi "
        "matlab nahi banta, isliye slot ki naap chalayi hi nahi gayi."),
    market_data.NO_SLOT_LABELS: (
        "Series ke period label me waqt ka koi hissa hi nahi hai (na ghanta, na "
        "din, na mahina), isliye kis slot me trade hua — ye pata hi nahi chal "
        "sakta."),
    market_data.FEW_SLOTS: (
        f"{market_data.SLOT_MIN_SLOTS} se kam slot me {market_data.SLOT_MIN_TRADES}"
        "+ trade bane, isliye slot-to-slot muqabla hua hi nahi. Ek hi slot ke "
        "number se 'ye waqt behtar hai' kehna sample ko waqt bata dena hai."),
    market_data.SLOT_NO_DIFFERENCE: (
        f"Sabse acche aur sabse bure slot ka faasla {market_data.SLOT_DIFF_R:g}R "
        "se kam nikla, yaani is series par waqt se koi naapa hua farak NAHI "
        "aaya. Ye 'session edge nahi mila' hai — 'session edge hai hi nahi' "
        "nahi."),
    market_data.NO_VOLATILITY: (
        "Train hisse me koi harkat hi nahi thi, isliye stop ki naap ban hi nahi "
        "saki aur kisi bhi slot ka R-multiple bemaani ho jaata."),
    market_data.FEW_TRADES: (
        f"Held-out me {market_data.TRADE_MIN_TRADES} se kam poore trade bane, "
        "isliye unhe slot me baantne ka koi matlab nahi tha."),
}
_REGIME_NOT_RUN: Dict[str, str] = {
    market_data.NO_REGIME_HISTORY: (
        "Entry se PEHLE itne bar hi nahi the ki trend aur volatility ka label "
        "ban sake. Regime sirf guzre hue data se banta hai (aage ka bar dekhna "
        "leakage hai), isliye label bina — naap bhi bina."),
    market_data.REGIME_UNLABELLED: (
        "Kuch trade aise the jinke entry se pehle regime ka label hi nahi ban "
        "paaya. 'Har scalp se pehle regime pehchana gaya' — ye daawa tab tak "
        "nahi ho sakta jab tak 100% trade labelled na hon."),
    market_data.FEW_REGIMES: (
        f"{market_data.REGIME_MIN_REGIMES} se kam regime me "
        f"{market_data.REGIME_MIN_TRADES}+ trade bane, isliye 'kis haalat me "
        "kaam karta hai' ka muqabla hua hi nahi."),
    market_data.REGIME_NO_DIFFERENCE: (
        f"Sabse acche aur sabse bure regime ka faasla "
        f"{market_data.REGIME_DIFF_R:g}R se kam nikla — is series par haalat "
        "badalne se naapa hua farak nahi aaya."),
    market_data.NO_VOLATILITY: (
        "Train hisse me koi harkat hi nahi thi, isliye na stop bani, na "
        "volatility-regime ka koi paimana."),
    market_data.FEW_TRADES: (
        f"Held-out me {market_data.TRADE_MIN_TRADES} se kam poore trade bane, "
        "isliye regime ke hisaab se baantna bemaani tha."),
}
_EVENT_NOT_RUN: Dict[str, str] = {
    market_data.EVENT_NEEDS_INTRADAY: (
        "Khabar ki khidki minute me naapi jaati hai (release, 1-5M, 5-15M, "
        "15-60M). Is series me intraday waqt hi nahi hai, isliye ye khidkiyan "
        "ban hi nahi sakti — daily bar par 'release ke 5 minute baad' ka koi "
        "matlab nahi."),
    market_data.NO_EVENTS: (
        "Evidence me na koi event ka naam+waqt mila, aur na series me koi aisa "
        "shock bar jo event ka proxy ban sake. Bina event, khidki ki naap ka "
        "sawaal hi nahi uthta."),
    market_data.EVENT_STEP_UNKNOWN: (
        "Bar ka waqfa (kitne minute ka ek bar) tay hi nahi ho paaya, isliye "
        "minute-waali khidkiyan naapi nahi ja saki."),
    market_data.FEW_EVENT_WINDOWS: (
        f"{market_data.EVENT_MIN_WINDOWS} se kam khidki me "
        f"{market_data.EVENT_MIN_TRADES}+ trade bane, isliye khidki-to-khidki "
        "muqabla nahi hua aur koi trade/wait/avoid verdict nahi diya gaya."),
    market_data.NO_VOLATILITY: (
        "Train hisse me koi harkat hi nahi thi, isliye na stop bani aur na "
        "shock ki chhat — event pehchana hi nahi ja sakta tha."),
    market_data.FEW_TRADES: (
        f"Held-out me {market_data.TRADE_MIN_TRADES} se kam poore trade bane, "
        "isliye unhe event ki khidkiyon me baantna bemaani tha."),
}


def _series_outcome(spec: TestSpec, policy: LabPolicy
                    ) -> Tuple[Any, Any, str, List[str]]:
    """(series, walk_forward outcome, label, source_ids). Fail par outcome None."""
    series = spec.series
    if series is None or not getattr(series, "points", None):
        return None, None, "", []
    source_ids = [str(sid) for sid in (getattr(series, "source_ids", None) or ())
                  if str(sid)]
    outcome = market_data.walk_forward(
        series,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction)
    return series, outcome, _series_label(series), source_ids


def _no_series_result(spec: TestSpec) -> TestResult:
    reason = spec.series_reason or market_data.NO_SERIES
    return _result(spec, DATA_MISSING, reason_code=reason,
                   detail=_wf_detail(reason))


def _outcome_blocked(spec: TestSpec, outcome: Any, label: str,
                     source_ids: List[str]) -> Optional[TestResult]:
    """Walk-forward hi verdict-layak na ho to teeno naye test bhi chup rehte hain.

    Do wajah: (a) walk-forward chala hi nahi, (b) held-out bilkul flat tha —
    naive baseline ki galti 0 thi, yaani muqabla hua hi nahi. (b) wahi purana
    #118 gate hai jo `walk_forward` recipe par lagta hai. Usko sirf ek recipe
    par lagana aur baaki teen par chhod dena naapa hua jhooth banata hai: usi
    series par walk_forward "koi verdict nahi ban sakta" kehta aur tournament
    TESTED_FAIL likh deta — jabki flat held-out par model JEET bhi nahi sakta
    (sab MAE 0 par barabar), isliye us "haar" ka koi matlab nahi hota.
    """
    if not outcome.ok:
        return _result(spec, DATA_MISSING,
                       reason_code=outcome.reason_code or market_data.NO_SERIES,
                       observed=label, evidence_ids=source_ids,
                       detail=_wf_detail(outcome.reason_code))
    if outcome.beats_naive is None:
        return _result(spec, DATA_MISSING, reason_code=market_data.FLAT_HOLDOUT,
                       observed=label, evidence_ids=source_ids,
                       detail=_wf_detail(market_data.FLAT_HOLDOUT))
    return None


def _run_monte_carlo(spec: TestSpec, policy: LabPolicy,
                     executor: SafeNumericExecutor) -> TestResult:
    """Drawdown / losing streak / risk-of-ruin — aur usse risk per trade.

    Ye "thousands of random simulations" NAHI hai aur aisa daawa bhi nahi karta:
    `market_data.mc_paths` ek deterministic block-resample hai (rotation + ulta
    kram), aur report me asli path ginti jaati hai. Isi wajah se lab ka
    `randomness_used: False` waada ek bit bhi nahi tootta.

    PASS ka matlab: risk ladder me KOI aisa level mila jispar p95 drawdown aur
    ruin ki probability chhat ke andar rahe aur median ending equity 1.0 se
    upar. Na mile to TESTED_FAIL — "chalo 1% le lo" jaisa andaaza nahi.
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    mc = market_data.monte_carlo(outcome.steps,
                                 min_steps=policy.mc_min_steps,
                                 min_paths=policy.mc_min_paths,
                                 max_p95_drawdown=policy.mc_max_p95_drawdown,
                                 max_ruin_prob=policy.mc_max_ruin_prob)
    if not mc.ok:
        return _result(spec, DATA_MISSING, reason_code=mc.reason_code,
                       observed=f"{label} | held-out step {mc.n_steps}",
                       evidence_ids=source_ids,
                       detail=_MC_NOT_RUN.get(
                           mc.reason_code,
                           f"Simulation chalaya hi nahi gaya (wajah: "
                           f"{mc.reason_code or 'pata nahi'})."))
    observed = (f"{label} | {mc.n_steps} held-out step se {mc.n_paths} "
                f"deterministic path | p95 drawdown "
                f"{mc.p95_drawdown:.1%} (risk {mc.reported_risk:.2%} par), "
                f"ruin {mc.ruin_prob:.2%}, sabse lamba losing streak "
                f"{mc.worst_streak}")
    tail = (" " + market_data.BACKTEST_NOTE + " "
            + market_data.NOT_ADVICE_NOTE)
    if not mc.survived:
        return _result(
            spec, TESTED_FAIL, observed=observed,
            expected=(f"kam se kam ek risk level jispar p95 drawdown ≤ "
                      f"{policy.mc_max_p95_drawdown:.0%} aur ruin ≤ "
                      f"{policy.mc_max_ruin_prob:.1%}"),
            evidence_ids=source_ids, reason_code=market_data.NO_SAFE_RISK,
            detail=("Risk ladder ka koi bhi level in chhaton ke andar nahi "
                    "bacha — is model ko is series par tradeable risk NAHI "
                    "mila. Upar ke numbers sabse chhote risk level ke hain, "
                    "kisi 'chune hue' risk ke nahi." + tail))
    return _result(
        spec, TESTED_PASS, observed=observed,
        expected=(f"p95 drawdown ≤ {policy.mc_max_p95_drawdown:.0%}, ruin ≤ "
                  f"{policy.mc_max_ruin_prob:.1%}, median ending equity > 1.0"),
        computed=mc.risk_fraction, evidence_ids=source_ids,
        reason_code="risk_level_survived_resampling",
        detail=(f"Sabse bada risk per trade jo in chhaton ke andar bacha: "
                f"{mc.risk_fraction:.2%} (median ending equity "
                f"{mc.median_end:.3g}). Ye {mc.n_paths} deterministic path par "
                f"naapa gaya, koi random draw nahi." + tail))


def _run_parameter_robustness(spec: TestSpec, policy: LabPolicy,
                              executor: SafeNumericExecutor) -> TestResult:
    """Edge ek REGION me zinda hai ya ek magic number par.

    Split wahi rehta hai, sirf drift lookback badalta hai. PASS tab jab kaafi
    settings chali hon AUR unme se kam se kam `sweep_min_beat_share` hissa naive
    baseline ko haraye. Ek hi setting jeete = magic number = TESTED_FAIL.
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    sweep = market_data.parameter_sweep(
        series,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction,
        min_settings=policy.sweep_min_settings,
        min_share=policy.sweep_min_beat_share)
    region = sweep.region_ok
    observed = (f"{label} | {sweep.usable} setting chali, {sweep.beat} ne naive "
                f"baseline ko haraya"
                + (f" (share {sweep.share:.0%})" if sweep.share is not None
                   else ""))
    if region is None:
        reason = sweep.reason_code or market_data.FEW_SETTINGS
        return _result(spec, DATA_MISSING, reason_code=reason,
                       observed=observed, evidence_ids=source_ids,
                       detail=_SWEEP_NOT_RUN.get(
                           reason, _wf_detail(reason)))
    tail = " " + market_data.BACKTEST_NOTE + " " + market_data.NOT_ADVICE_NOTE
    expected = (f"{sweep.usable} me se kam se kam "
                f"{policy.sweep_min_beat_share:.0%} settings naive baseline se "
                "behtar")
    if not region:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=sweep.share, evidence_ids=source_ids,
            reason_code="edge_only_at_isolated_setting",
            detail=("Edge sirf ginti ki settings par dikha — yaani ye ek magic "
                    "number par tikka hai, region me zinda nahi. Aise edge ka "
                    "live market me bachna sabse kam sambhav hai." + tail))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=sweep.share, evidence_ids=source_ids,
        reason_code="edge_survives_parameter_region",
        detail=(f"Lookback {sweep.best_lookback if sweep.best_lookback else 'poora itihaas'} "
                f"par sabse kam galti thi, par nateeja ek setting par nahi tikka: "
                f"{sweep.beat}/{sweep.usable} settings ne naive ko haraya." + tail))


def _run_baseline_tournament(spec: TestSpec, policy: LabPolicy,
                             executor: SafeNumericExecutor) -> TestResult:
    """Model vs paanch simple baseline, wahi held-out split.

    PASS tab jab model HAR compare hui baseline se kam galti kare. Ek bhi simple
    model behtar nikla to complex model ka koi haq nahi — TESTED_FAIL.
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    tour = market_data.baseline_tournament(
        series,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction)
    if not tour.ok:
        reason = tour.reason_code or market_data.NO_BASELINE
        return _result(spec, DATA_MISSING, reason_code=reason,
                       observed=label, evidence_ids=source_ids,
                       detail=_TOURNAMENT_NOT_RUN.get(reason,
                                                      _wf_detail(reason)))
    lost = [row["baseline"] for row in tour.rows
            if row.get("compared") and not row.get("model_better")]
    observed = (f"{label} | held-out {tour.n_test} | model MAE "
                f"{tour.model_mae:.4g} | {tour.beaten}/{tour.total} baseline "
                f"haraye | jeeta: {tour.winner}")
    expected = f"{tour.total}/{tour.total} baseline se kam galti (MAE)"
    tail = (" " + market_data.BASELINE_SCOPE_NOTE + " "
            + market_data.BACKTEST_NOTE + " " + market_data.NOT_ADVICE_NOTE)
    if not tour.beats_all:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=float(tour.beaten), evidence_ids=source_ids,
            reason_code="simpler_baseline_did_better",
            detail=("Ye simple baseline model se BEHTAR nikle: "
                    + ", ".join(lost) + ". Jab ek seedha model hi behtar hai, "
                    "complex model ka koi haq nahi." + tail))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=float(tour.beaten), evidence_ids=source_ids,
        reason_code="model_beats_every_baseline",
        detail=(f"Model ne saari {tour.total} baseline ko held-out par haraya "
                f"(model MAE {tour.model_mae:.4g})." + tail))


def _run_trade_expectancy(spec: TestSpec, policy: LabPolicy,
                          executor: SafeNumericExecutor) -> TestResult:
    """Entry + stop + target + COST ke baad kya bachta hai — asli trade naap.

    Baaki chaar recipe forecast ki GALTI naapte hain (MAE). Trading ka sawaal
    alag hai: har trade ka R-multiple, expectancy, profit factor, drawdown, MAE
    aur haar ki wajah. Yahi wo naap hai jispar intel ka contract tika hai, aur
    yahan do baat jaan-boojh kar saaf likhi jaati hai:

      * Series me sirf CLOSE hai. Isliye "ek hi bar me pehle SL laga ya TP" ye
        HISAAB NAHI HO SAKTA. `simulate_trades` pehle STOP maanta hai — yaani
        bura-se-bura — kyunki apne haq me maan lena hi sabse meetha jhooth hai,
        aur ye baat `CLOSE_ONLY_NOTE` me bahar bhi jaati hai.
      * PASS ka matlab sirf itna: NET expectancy positive, profit factor 1 se
        upar, aur edge ek hi R par nahi (kam se kam `trade_min_robust_share`
        hissa R-settings me zinda). Win rate PASS ki shart me JAAN-BOOJH KAR
        nahi hai — 90% win rate wala model bhi ek haar me sab de sakta hai.

    Teen alag "naap hi nahi hui" haalat DATA_MISSING hain, TESTED_FAIL nahi:
    kam trade, train me koi harkat nahi, aur sample me ek bhi haar na hona
    (loss-side naapa hi nahi gaya).
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    sim = market_data.trade_expectancy(
        series,
        r_multiples=policy.trade_r_multiples,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction,
        min_trades=policy.trade_min_trades,
        stop_units=policy.trade_stop_units,
        max_bars=policy.trade_max_bars,
        cost_fraction=policy.trade_cost_fraction,
        min_robust_share=policy.trade_min_robust_share)
    edge = sim.edge_after_cost
    best = sim.best or {}
    tail = (" " + market_data.CLOSE_ONLY_NOTE + " " + market_data.TRADE_COST_NOTE
            + " " + market_data.BACKTEST_NOTE + " " + market_data.NOT_ADVICE_NOTE)
    if edge is None:
        reason = sim.reason_code or market_data.FEW_TRADES
        return _result(spec, DATA_MISSING, reason_code=reason,
                       observed=(f"{label} | held-out {sim.n_test} | "
                                 f"{sim.usable}/{len(sim.rows)} R-setting naapi "
                                 f"ja saki"),
                       evidence_ids=source_ids,
                       detail=(_TRADE_NOT_RUN.get(reason, _wf_detail(reason))
                               + tail))
    observed = (f"{label} | held-out {sim.n_test} | best TP "
                f"{best.get('r_multiple')}R par {best.get('n_trades')} trade | "
                f"NET expectancy {best.get('expectancy_r'):+.3f}R, profit factor "
                f"{best.get('profit_factor'):.3g}, win rate "
                f"{(best.get('win_rate') or 0.0):.0%}, max drawdown "
                f"{best.get('max_drawdown_r'):.3g}R, MAE p95 "
                f"{best.get('mae_p95_r'):.3g}R")
    expected = (f"NET expectancy > {market_data.TRADE_MIN_EXPECTANCY_R:g}R, "
                f"profit factor > {market_data.TRADE_MIN_PROFIT_FACTOR:g}, aur "
                f"{policy.trade_min_robust_share:.0%} R-settings me expectancy "
                "positive")
    losses = ", ".join(f"{name} × {count}"
                       for name, count in sorted(
                           (best.get("loss_classes") or {}).items()))
    # #150g — NAAPE hue number, structured. Ye wahi jagah hai jahan se
    # `trademodel` ke contract point grade honge — `observed` line se NAHI.
    # Line insaan ke padhne ke liye hai; usko wapas parse karna "derive, never
    # declare" ka ulta rasta hai. Jo yahan nahi hai, wo naapa hi nahi gaya.
    measured: Dict[str, Any] = {
        "r_multiple": best.get("r_multiple"),
        "n_trades": best.get("n_trades"),
        "win_rate": best.get("win_rate"),
        "expectancy_r": best.get("expectancy_r"),
        "profit_factor": best.get("profit_factor"),
        "sharpe_r": best.get("sharpe_r"),
        "sortino_r": best.get("sortino_r"),
        "avg_win_r": best.get("avg_win_r"),
        "avg_loss_r": best.get("avg_loss_r"),
        "max_drawdown_r": best.get("max_drawdown_r"),
        "tail_loss_r": best.get("tail_loss_r"),
        "mae_median_r": best.get("mae_median_r"),
        "mae_p95_r": best.get("mae_p95_r"),
        # Cost sirf "lagayi gayi" kehna kaafi nahi — kitni lagi, ye naap bahar
        # jaati hai. 0 aaye to cost lagi hi nahi thi.
        "avg_cost_r": best.get("avg_cost_r"),
        "cost_fraction": float(policy.trade_cost_fraction),
        "stop_units": float(policy.trade_stop_units),
        "max_bars": int(policy.trade_max_bars),
        "loss_classes": dict(best.get("loss_classes") or {}),
        "exit_kinds": dict(best.get("exit_kinds") or {}),
        # R-ladder ka poora hisaab: kitni settings naapi ja saki, kitni me
        # expectancy positive rahi, aur wo hissa (region hai ya magic number).
        "r_settings_tried": len(sim.rows),
        "r_settings_measured": sim.usable,
        "r_settings_positive": sim.positive,
        "robust_share": sim.robust_share,
        "n_train": sim.n_train,
        "n_test": sim.n_test,
        "edge_after_cost": edge,
        "close_only": True,
    }
    if not edge:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=best.get("expectancy_r"), evidence_ids=source_ids,
            numbers=measured,
            reason_code=sim.reason_code or market_data.NO_EDGE_AFTER_COST,
            detail=("Cost lagne ke baad is series par is model ka koi edge NAHI "
                    "bacha — yaani ye setup live me paisa banane ka koi saboot "
                    "nahi de raha."
                    + (f" Haar ki naapi hui wajah: {losses}." if losses else "")
                    + tail))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=best.get("expectancy_r"), evidence_ids=source_ids,
        numbers=measured,
        reason_code="net_positive_expectancy_across_r_settings",
        detail=(f"Sabse acchi take-profit {best.get('r_multiple')}R nikli, aur "
                f"edge ek hi setting par nahi tikka: {sim.positive}/{sim.usable} "
                f"R-settings me NET expectancy positive rahi. Ye "
                f"{best.get('n_trades')} trade ka nateeja hai, kisi bade sample "
                f"ka nahi." + tail))


# ── #150i: WAQT, HAALAT aur KHABAR — teen naap jo pehle sirf text se grade hoti thi
def _run_slot_expectancy(spec: TestSpec, policy: LabPolicy,
                         executor: SafeNumericExecutor) -> TestResult:
    """KAB trade karna behtar hai — slot-wise NET expectancy ka asli muqabla.

    Do baat jaan-boojh kar saaf hai:
      * Slot ka naam "London"/"New York" nahi hota. Period stamp me timezone
        likha hi nahi hota, isliye ghanta `h00…h23` me naapa jaata hai aur uski
        wajah `SESSION_NAME_NOTE` me bahar bhi jaati hai. Session ka naam de
        dena ek aisa daawa hai jo data me maujood hi nahi.
      * Tulna EK hi R par hoti hai (`slot_min_*` ke saath mirror hui setting).
        Har slot ke liye uska "sabse accha R" dhoondhna cherry-picking hai —
        phir farak waqt ka nahi, R ke chunav ka hota hai.

    PASS ka matlab: best aur worst slot ka faasla naapi hui hadd se bada nikla,
    yaani is series par waqt sach me maayne rakhta hai. Faasla chhota nikalna
    TESTED_FAIL hai (asli negative nateeja), aur "naap hi nahi hui" DATA_MISSING.
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    split = market_data.slot_expectancy(
        series,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction,
        stop_units=policy.trade_stop_units,
        max_bars=policy.trade_max_bars,
        cost_fraction=policy.trade_cost_fraction,
        min_slot_trades=policy.slot_min_trades,
        min_slots=policy.slot_min_slots)
    measured = split.to_dict()
    tail = (" " + market_data.SESSION_NAME_NOTE + " " + market_data.CLOSE_ONLY_NOTE
            + " " + market_data.BACKTEST_NOTE + " " + market_data.NOT_ADVICE_NOTE)
    dependent = split.slot_dependent
    if not split.ok or dependent is None:
        reason = split.reason_code or market_data.FEW_SLOTS
        return _result(spec, DATA_MISSING, reason_code=reason,
                       observed=(f"{label} | held-out {split.n_test} | "
                                 f"granularity {split.granularity or 'none'} | "
                                 f"{split.measured} slot naapa ja saka"),
                       # `numbers=` jaan-boojh kar NAHI — DATA_MISSING ka matlab
                       # naap hui hi nahi. Aadha-adhoora dict bahar bhej dena
                       # aage "naapa hua" jaisa dikhta hai, aur wahi jhooth hai.
                       evidence_ids=source_ids,
                       detail=(_SLOT_NOT_RUN.get(reason, _wf_detail(reason))
                               + tail))
    best = split.best or {}
    worst = split.worst or {}
    observed = (f"{label} | held-out {split.n_test} | {split.granularity} | "
                f"{split.measured} slot naape | best {best.get('slot')} "
                f"{best.get('expectancy_r'):+.3f}R ({best.get('n_trades')} trade) "
                f"vs worst {worst.get('slot')} "
                f"{worst.get('expectancy_r'):+.3f}R ({worst.get('n_trades')} "
                f"trade) | faasla {split.spread_r:+.3f}R")
    expected = (f"best aur worst slot ka faasla >= {market_data.SLOT_DIFF_R:g}R "
                f"(kam se kam {policy.slot_min_slots} slot me "
                f"{policy.slot_min_trades}+ trade)")
    hour_note = ("" if split.intraday else
                 " Ghanta-wise (yaani asli 'session') naap NAHI hui — is series "
                 "me intraday waqt hi nahi hai, isliye ye "
                 f"{split.granularity} ka farak hai, session ka nahi.")
    if not dependent:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=split.spread_r, evidence_ids=source_ids, numbers=measured,
            reason_code=split.reason_code or market_data.SLOT_NO_DIFFERENCE,
            detail=("Slot badalne se koi naapa hua farak NAHI aaya — is series "
                    "par 'is waqt trade karo' wala daawa saboot ke bina hai."
                    + hour_note + tail))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=split.spread_r, evidence_ids=source_ids, numbers=measured,
        reason_code="slot_expectancy_spread_measured",
        detail=(f"{split.granularity} ke hisaab se expectancy sach me badalti "
                f"hai: {split.positive}/{split.measured} slot me NET expectancy "
                f"positive rahi. Ye {split.n_trades} trade ka nateeja hai, aur "
                f"{measured['labelled_share']} hissa trade ko slot mila."
                + hour_note + tail))


def _run_regime_split(spec: TestSpec, policy: LabPolicy,
                      executor: SafeNumericExecutor) -> TestResult:
    """KIS HAALAT me kaam karta hai — aur kya har entry se PEHLE haalat pata thi.

    Yahan do sawaal ek saath naape jaate hain, aur pehla doosre se bada hai:

      1. `labelled_before_entry` — har trade par entry se PEHLE regime ka label
         bana ya nahi. Label sirf `values[:entry_index]` se banta hai, yaani us
         waqt tak ka data aur bas itna hi; aage ka ek bhi bar dekhna leakage hai.
         Ye number hi "har scalp se pehle regime pehchana gaya" ka saboot hai.
      2. `regime_dependent` — regime badalne par expectancy asli me badalti hai.

    Agar kuch trade bina label reh gayi to nateeja TESTED_FAIL hai, DATA_MISSING
    nahi: naap chali thi, aur usne saaf bata diya ki "HAR" nahi hua. Per-regime
    number us adhoore hisse par tike hote, isliye wo daawa nahi banaya jaata.
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    split = market_data.regime_expectancy(
        series,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction,
        stop_units=policy.trade_stop_units,
        max_bars=policy.trade_max_bars,
        cost_fraction=policy.trade_cost_fraction,
        trend_lookback=policy.regime_trend_lookback,
        vol_lookback=policy.regime_vol_lookback,
        min_regime_trades=policy.regime_min_trades,
        min_regimes=policy.regime_min_regimes)
    measured = split.to_dict()
    tail = (" " + market_data.REGIME_PAST_ONLY_NOTE + " "
            + market_data.REGIME_RELATIVE_NOTE + " " + market_data.BACKTEST_NOTE
            + " " + market_data.NOT_ADVICE_NOTE)
    head = (f"{label} | held-out {split.n_test} | {split.measured} regime naape "
            f"| {split.n_trades} trade, {split.unlabelled} bina label")
    if split.ok and split.n_trades and split.unlabelled:
        return _result(
            spec, TESTED_FAIL, observed=head,
            expected="100% trade par entry se PEHLE regime ka label",
            computed=measured["labelled_share"], evidence_ids=source_ids,
            numbers=measured, reason_code=market_data.REGIME_UNLABELLED,
            detail=(_REGIME_NOT_RUN[market_data.REGIME_UNLABELLED]
                    + f" Naapa hua hissa: {measured['labelled_share']}."
                    + tail))
    dependent = split.regime_dependent
    if not split.ok or dependent is None:
        reason = split.reason_code or market_data.FEW_REGIMES
        return _result(spec, DATA_MISSING, reason_code=reason, observed=head,
                       # DATA_MISSING par koi number bahar nahi — dekho
                       # `_run_slot_expectancy` ki wahi wajah.
                       evidence_ids=source_ids,
                       detail=(_REGIME_NOT_RUN.get(reason, _wf_detail(reason))
                               + tail))
    best = split.best or {}
    worst = split.worst or {}
    observed = (f"{head} | best {best.get('regime')} "
                f"{best.get('expectancy_r'):+.3f}R ({best.get('n_trades')} trade) "
                f"vs worst {worst.get('regime')} "
                f"{worst.get('expectancy_r'):+.3f}R ({worst.get('n_trades')} "
                f"trade) | faasla {split.spread_r:+.3f}R")
    expected = (f"har entry se pehle label, aur best-worst regime ka faasla >= "
                f"{market_data.REGIME_DIFF_R:g}R (kam se kam "
                f"{policy.regime_min_regimes} regime me "
                f"{policy.regime_min_trades}+ trade)")
    if not dependent:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=split.spread_r, evidence_ids=source_ids, numbers=measured,
            reason_code=split.reason_code or market_data.REGIME_NO_DIFFERENCE,
            detail=("Regime badalne se koi naapa hua farak nahi aaya. Label har "
                    "entry se pehle bana (wo hissa sach hai), par 'is haalat me "
                    "hi trade karo' — is baat ka saboot is series par nahi mila."
                    + tail))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=split.spread_r, evidence_ids=source_ids, numbers=measured,
        reason_code="regime_labelled_before_entry_and_expectancy_differs",
        detail=(f"Har trade ka regime entry se PEHLE bana (labelled share "
                f"{measured['labelled_share']}), aur haalat badalne par "
                f"expectancy sach me badli: {split.positive}/{split.measured} "
                f"regime me NET expectancy positive rahi." + tail))


def _run_event_window(spec: TestSpec, policy: LabPolicy,
                      executor: SafeNumericExecutor) -> TestResult:
    """KHABAR ke aas-paas kya karein — har khidki ka naapa hua trade/wait/avoid.

    Do mode hain aur dono ka farak chhupaya nahi jaata:
      * calendar — evidence me event ka NAAM aur intraday waqt ek hi line par
        mila. Sirf isi mode me "pre-news" ka faisla ho sakta hai, kyunki event ka
        waqt pehle se pata tha.
      * shock proxy — koi calendar nahi mili, isliye bade move ko event ka
        nishaan maana gaya. Ye event ka PROXY hai, saboot nahi, aur is mode me
        `pre_event_verdict` hamesha None rehta hai (wajah bhi saath jaati hai).

    "wait" ek FAISLA hai (naapa, edge nahi mila, ruko). Jahan naap hi nahi hui
    wahan verdict None rehta hai — "wait" likh dena naap ke na hone ko chhupa
    dena hota, aur yahi is point ka sabse aasan jhooth hai.
    """
    series, outcome, label, source_ids = _series_outcome(spec, policy)
    if outcome is None:
        return _no_series_result(spec)
    blocked = _outcome_blocked(spec, outcome, label, source_ids)
    if blocked is not None:
        return blocked
    split = market_data.event_window_expectancy(
        series,
        text=spec.evidence_text,
        min_points=policy.min_series_points,
        min_holdout=policy.min_holdout_points,
        train_fraction=policy.train_fraction,
        stop_units=policy.trade_stop_units,
        max_bars=policy.trade_max_bars,
        cost_fraction=policy.trade_cost_fraction,
        shock_units=policy.event_shock_units,
        min_window_trades=policy.event_min_trades,
        min_windows=policy.event_min_windows)
    measured = split.to_dict()
    mode_note = (market_data.EVENT_CALENDAR_NOTE
                 if split.mode == market_data.EVENT_MODE_CALENDAR
                 else market_data.EVENT_SHOCK_NOTE)
    tail = (" " + mode_note + " " + market_data.EVENT_VERDICT_NOTE + " "
            + market_data.BACKTEST_NOTE + " " + market_data.NOT_ADVICE_NOTE)
    head = (f"{label} | mode {split.mode or 'none'} | {split.n_events} event | "
            f"held-out {split.n_test} | {split.measured} khidki naapi, "
            f"{split.decided} ka faisla bana")
    dependent = split.window_dependent
    if not split.ok or dependent is None:
        reason = split.reason_code or market_data.NO_EVENTS
        return _result(spec, DATA_MISSING, reason_code=reason, observed=head,
                       # DATA_MISSING par koi number bahar nahi — dekho
                       # `_run_slot_expectancy` ki wahi wajah.
                       evidence_ids=source_ids,
                       detail=(_EVENT_NOT_RUN.get(reason, _wf_detail(reason))
                               + tail))
    verdicts = ", ".join(f"{window}={verdict}"
                         for window, verdict in split.verdicts.items() if verdict)
    observed = f"{head} | {verdicts}"
    expected = (f"kam se kam {policy.event_min_windows} khidki me "
                f"{policy.event_min_trades}+ trade, aur khidkiyon ka faisla ek "
                "jaisa na ho")
    pre_note = ("" if split.mode == market_data.EVENT_MODE_CALENDAR else
                " Pre-news window ka faisla NAHI hua — uske liye asli event "
                "calendar chahiye, shock proxy se event ka waqt pehle se pata "
                "nahi hota.")
    if not dependent:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=split.decided, evidence_ids=source_ids, numbers=measured,
            reason_code=split.reason_code or market_data.EVENT_NO_DIFFERENCE,
            detail=("Har naapi hui khidki ka faisla ek hi nikla, yaani khabar ke "
                    "aas-paas bartaav badalne ka koi naapa hua kaaran is series "
                    "par nahi mila." + pre_note + tail))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=split.decided, evidence_ids=source_ids, numbers=measured,
        reason_code="event_window_verdicts_differ_by_window",
        detail=(f"{split.decided} khidki ka faisla naap se bana aur wo faisle ek "
                f"jaise NAHI hain — yaani event ki khidki asli me maayne rakhti "
                f"hai. Ye {split.n_trades} trade ka nateeja hai, aur "
                f"{measured['labelled_share']} hissa trade ko khidki mili."
                + pre_note + tail))


# ── #171e — EXAM/PADHAI ke paanch naap ───────────────────────────────────────
# Ye paanch recipe hypothesis ko nahi, BANE HUE paper/plan ko naapti hain. Isi
# wajah se inka janam `plan_exam_specs()` se hota hai, `plan_specs()` se nahi —
# science aur trading ka rasta ek bit bhi nahi badalta.
#
# Teen niyam poore batch par lage hain:
#   1. Chhat `policy` se aati hai, aur policy ki value `exammodel` se mirror
#      hoti hai. Recipe ke andar koi naya number nahi likha jaata.
#   2. `numbers=` sirf TESTED_PASS/TESTED_FAIL par jaata hai. DATA_MISSING ke
#      saath number bhejna "naap hui" ka jhootha nishaan ban jaata hai.
#   3. Har DATA_MISSING ke saath `reason_code` exammodel ka hi hota hai, aur
#      uska Hinglish matlab niche ki table se aata hai.
_EXAM_NOT_RUN: Dict[str, str] = {
    exammodel.NO_PAPER:
        "Naapne ke liye koi bana hua paper hi nahi mila — question nikal hi "
        "nahi paaye, isliye ye naap chalayi nahi gayi.",
    exammodel.NO_SYLLABUS:
        "Syllabus ke topic nahi mile (na official list, na paper me [Topic: …] "
        "tag), isliye coverage naapi hi nahi ja sakti. Ye 'coverage poori hai' "
        "NAHI hai — ye 'naapa hi nahi gaya' hai.",
    exammodel.FEW_QUESTIONS:
        f"Question ki ginti {exammodel.MIN_QUESTIONS_FOR_SPLIT} se kam thi — "
        "itne chhote paper par band/duplicate ka faisla dena bemaani hota.",
    exammodel.NO_KEY:
        "Answer key nahi mili, isliye jawab se judi koi naap nahi hui.",
    exammodel.NO_NUMERIC:
        "Paper me ginti wala (calculate karne layak) koi hissa nahi tha, "
        "isliye chala kar dekhne ka sawaal hi nahi utha.",
    exammodel.NO_EVALUATOR:
        "Bounded calculator nahi mila, isliye question chala kar dekhe hi "
        "nahi gaye. Apna alag calculator likh kar 'check ho gaya' kehna jhooth "
        "hota.",
    exammodel.NO_PLAN:
        "Koi study-plan ki line nahi mili (na din/hafte ka label, na time), "
        "isliye plan ka time-budget naapa hi nahi gaya.",
    exammodel.NO_TIME_BUDGET:
        "Farmaish me kitne din mile hain ye likha hi nahi tha, isliye 'plan "
        "time me fit hota hai ya nahi' ka faisla nahi ho sakta. Default maan "
        "kar PASS dena sabse aasaan jhooth hota.",
    exammodel.NO_TOPIC_WEIGHT:
        "Plan ki kisi line par time (minute/ghanta) likha hi nahi tha, isliye "
        "kul bojh joda hi nahi ja saka.",
}

_EXAM_TAIL = " " + exammodel.NOT_OFFICIAL_NOTE


def _exam_of(spec: TestSpec) -> Dict[str, Any]:
    """Spec ke saath aaya exam saamaan. Na ho to khaali dict (guess nahi)."""
    return spec.exam if isinstance(spec.exam, dict) else {}


def _exam_missing(spec: TestSpec, reason_code: str, extra: str = "") -> TestResult:
    """DATA_MISSING — wajah exammodel ki, aur uske saath koi number NAHI."""
    code = reason_code or exammodel.NO_PAPER
    detail = _EXAM_NOT_RUN.get(code, f"Ye naap chalayi nahi ja saki ({code}).")
    return _result(spec, DATA_MISSING, reason_code=code,
                   detail=detail + (" " + extra if extra else "") + _EXAM_TAIL)


def _run_syllabus_coverage(spec: TestSpec, policy: LabPolicy,
                           executor: SafeNumericExecutor) -> TestResult:
    """Syllabus ke kitne topic par ASLI me question bana — ginti se, daawe se nahi.

    Sabse aam jhooth yahi hai: paper ke saath "poora syllabus cover hai" likh
    dena. Yahan har topic par question dhoonde jaate hain, aur jo topic khaali
    reh gaye unke NAAM bhi report me jaate hain.
    """
    material = _exam_of(spec)
    split = exammodel.coverage_split(material.get("topics") or (),
                                     material.get("questions") or ())
    share = split.covered_share
    if not split.ok or share is None:
        return _exam_missing(spec, split.reason_code)
    measured = split.to_dict()
    observed = (f"{split.covered}/{split.topics} topic par question bana "
                f"(hissa {share}), paper me {split.questions} question")
    expected = (f"kam se kam {policy.exam_min_coverage_share} hissa topic par "
                "ek-ek question")
    small = (" Paper hi topic se chhota tha, isliye poora cover MUMKIN hi nahi "
             "tha — ye paper ki kami hai, syllabus ki nahi."
             if split.paper_too_small else "")
    if share < policy.exam_min_coverage_share - 1e-9:
        left = list(split.uncovered)[:6]
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=share, numbers=measured,
            reason_code="syllabus_coverage_below_floor",
            detail=(f"{split.reason}." + small + " Bina question wale topic: "
                    + (", ".join(left) if left else "—")
                    + (f" (+{len(split.uncovered) - len(left)} aur)"
                       if len(split.uncovered) > len(left) else "")
                    + _EXAM_TAIL))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=share, numbers=measured,
        reason_code="syllabus_coverage_met",
        detail=(f"Syllabus ke {split.covered} topic par question mila, yaani "
                f"{share} hissa — chhat {policy.exam_min_coverage_share} thi."
                + small + " Ye 'question sahi hain' NAHI kehta; sirf itna ki "
                "topic chhoote nahi." + _EXAM_TAIL))


def _run_difficulty_mix(spec: TestSpec, policy: LabPolicy,
                        executor: SafeNumericExecutor) -> TestResult:
    """Sab question ek hi band me gire ya mix hua — aur ye naap PROXY hai.

    Proxy hone ki baat detail me HAR baar jaati hai. Difficulty ka asli naap
    insaan ke attempt se hoti hai (kitne logon ne galat kiya) — wo data app ke
    paas nahi hai, aur uska dikhawa karna hi is point ka sabse aasaan jhooth
    hota.
    """
    material = _exam_of(spec)
    split = exammodel.difficulty_split(material.get("questions") or ())
    mixed = split.mixed
    if not split.ok or mixed is None:
        return _exam_missing(spec, split.reason_code)
    measured = split.to_dict()
    shares = {band: value for band, value in (split.shares or {}).items()
              if value is not None}
    top_band, top_share = "", 0.0
    for band in exammodel.DIFFICULTY_BANDS:
        value = float(shares.get(band) or 0.0)
        if value > top_share:
            top_band, top_share = band, value
    proxy = (" Ye naap PROXY hai (question ki lambai, option, marks aur ginti "
             "se banti hai) — asli difficulty insaan ke attempt se naapi jaati "
             "hai, aur wo data app ke paas nahi hai.")
    observed = (f"{split.questions} question | band "
                + ", ".join(f"{band}={split.counts.get(band, 0)}"
                            for band in exammodel.DIFFICULTY_BANDS)
                + f" | sabse bhaari {top_band or '—'}={top_share}")
    expected = (f"kam se kam 2 band me question, aur ek band me "
                f"{policy.exam_max_band_share} se zyada hissa nahi")
    if not mixed:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=top_share, numbers=measured,
            reason_code="difficulty_single_band",
            detail=(f"{split.reason} — yaani mix hi nahi hua." + proxy
                    + _EXAM_TAIL))
    if top_share > policy.exam_max_band_share + 1e-9:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=top_share, numbers=measured,
            reason_code="difficulty_band_share_above_cap",
            detail=(f"Do band to hain, par '{top_band}' band akela {top_share} "
                    f"hissa le gaya (chhat {policy.exam_max_band_share}) — "
                    "naam ka mix hai, asli mix nahi." + proxy + _EXAM_TAIL))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=top_share, numbers=measured,
        reason_code="difficulty_mix_met",
        detail=(f"Question {split.bands_used} band me baante hue mile aur koi "
                f"ek band {policy.exam_max_band_share} se zyada nahi le gaya."
                + proxy + _EXAM_TAIL))


def _run_duplicate_questions(spec: TestSpec, policy: LabPolicy,
                             executor: SafeNumericExecutor) -> TestResult:
    """Do question ek jaise nikle ya nahi — shabd ke overlap se, aankh se nahi.

    120 question maange gaye hon to sabse aam dhokha yahi hai: wahi sawaal
    thoda ghuma kar dobara likh dena. Har jodi ka overlap naapa jaata hai aur
    jodi ke NUMBER report me jaate hain.
    """
    material = _exam_of(spec)
    split = exammodel.duplicate_split(material.get("questions") or (),
                                      threshold=policy.exam_duplicate_similarity)
    pairs = split.duplicate_pairs
    if not split.ok or pairs is None:
        return _exam_missing(spec, split.reason_code)
    measured = split.to_dict()
    observed = (f"{split.questions} question me {pairs} jodi ka overlap "
                f"{split.threshold} ya usse zyada")
    expected = (f"{policy.exam_max_duplicate_pairs} se zyada ek-jaisi jodi "
                "nahi")
    if pairs > policy.exam_max_duplicate_pairs:
        named = ", ".join(f"Q{row['left']}~Q{row['right']} ({row['similarity']})"
                          for row in list(split.pairs)[:5])
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=float(pairs), numbers=measured,
            reason_code="duplicate_questions_found",
            detail=(f"{split.reason}. Jodi: {named}"
                    + (f" (+{pairs - 5} aur)" if pairs > 5 else "")
                    + ". Overlap shabd ke milan se naapa gaya hai, isliye "
                    "bilkul alag shabdon me likha wahi sawaal is naap se bach "
                    "sakta hai." + _EXAM_TAIL))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=float(pairs), numbers=measured,
        reason_code="duplicate_questions_clean",
        detail=(f"{split.questions} question ki saari jodiyon me se ek bhi "
                f"{split.threshold} overlap tak nahi pahunchi. Ye 'sab sawaal "
                "alag mazmoon ke hain' NAHI kehta — sirf itna ki shabd dohraye "
                "nahi gaye." + _EXAM_TAIL))


def _run_question_solvability(spec: TestSpec, policy: LabPolicy,
                              executor: SafeNumericExecutor) -> TestResult:
    """Ginti wale question ko ASLI me bounded calculator me CHALA kar dekha gaya.

    Calculator lab ka apna nahi hai — `SafeNumericExecutor` (bounded, sandboxed)
    ka `evaluate` bahar se exammodel ko diya jaata hai. Model ka likha koi code
    yahan chalta hi nahi (`model_written_code_executed: False` isi liye sach
    rehta hai).
    """
    material = _exam_of(spec)
    split = exammodel.solvability_split(material.get("questions") or (),
                                        evaluate=executor.evaluate)
    share = split.solved_share
    if not split.ok or share is None:
        return _exam_missing(spec, split.reason_code)
    measured = split.to_dict()
    observed = (f"{split.checked} ginti wale question chalaye gaye, "
                f"{split.solved} bane (hissa {share})")
    expected = (f"chale hue question ka {policy.exam_min_solved_share} hissa "
                "banna chahiye")
    scope = (" Ye naap sirf ITNA kehti hai ki question ka ginti wala hissa "
             "chal jaata hai — jawab sahi hai ya nahi, wo alag baat hai aur "
             "yahan naapi nahi gayi.")
    if share < policy.exam_min_solved_share - 1e-9:
        bad = ", ".join(f"Q{row['number']} ({row['error']})"
                        for row in list(split.failed)[:5])
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=share, numbers=measured,
            reason_code="question_not_solvable",
            detail=(f"{split.reason}: {bad or '—'}. Aise question paper me "
                    "rehne se student wahan atak jaayega, isliye ye FAIL hai."
                    + scope + _EXAM_TAIL))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=share, numbers=measured,
        reason_code="question_solvability_met",
        detail=(f"{split.solved} me se {split.checked} ginti wale hisse "
                "bounded calculator me chal gaye." + scope + _EXAM_TAIL))


def _run_plan_time_budget(spec: TestSpec, policy: LabPolicy,
                          executor: SafeNumericExecutor) -> TestResult:
    """Plan ka jodha hua time vs asli me mila hua time — aur ek din ka bojh.

    "30 din me strong kar do" par sabse aam dhokha ye hai: roz 9 ghante ka
    plan likh dena. Do naap saath chalti hain — kul time fit hota hai ya nahi,
    aur kisi EK din ka bojh insaani hadd me hai ya nahi.
    """
    material = _exam_of(spec)
    split = exammodel.plan_time_split(
        material.get("plan_rows") or (),
        minutes_available=float(material.get("minutes_available") or 0.0))
    fits = split.fits
    if not split.ok or fits is None:
        return _exam_missing(spec, split.reason_code)
    measured = split.to_dict()
    realistic = split.day_realistic
    observed = (f"{split.timed_rows}/{split.rows} line par time likha | kul "
                f"{split.total_minutes:.0f} min vs mila hua "
                f"{split.minutes_available:.0f} min (hissa {split.load_share})"
                + (f" | sabse bhaari {split.worst_day}="
                   f"{split.worst_day_minutes:.0f} min"
                   if split.worst_day else " | din ka label kisi line par nahi"))
    expected = (f"kul time mile hue time ke andar, aur ek din "
                f"{split.daily_ceiling:.0f} min se zyada nahi")
    day_note = ("" if split.worst_day else
                " Kisi line par din/hafte ka label nahi tha, isliye per-day "
                "bojh naapa hi NAHI gaya — sirf kul time naapa gaya.")
    if not fits:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=split.load_share, numbers=measured,
            reason_code="plan_does_not_fit_time",
            detail=(f"{split.reason}. Aisa plan kaagaz par poora dikhta hai "
                    "par asli me chalta nahi." + day_note + _EXAM_TAIL))
    if realistic is False:
        return _result(
            spec, TESTED_FAIL, observed=observed, expected=expected,
            computed=split.load_share, numbers=measured,
            reason_code="plan_day_load_above_ceiling",
            detail=(f"Kul time to fit hai, par {split.reason} — ek din ka bojh "
                    "insaani hadd se bahar hai." + _EXAM_TAIL))
    return _result(
        spec, TESTED_PASS, observed=observed, expected=expected,
        computed=split.load_share, numbers=measured,
        reason_code="plan_time_budget_met",
        detail=(f"Plan ka joda hua time {split.total_minutes:.0f} min hai aur "
                f"mila hua time {split.minutes_available:.0f} min — fit hai."
                + day_note + " Time fit hona 'plan kaam karega' NAHI hai; "
                "seekhne ki raftaar insaan par depend karti hai aur wo yahan "
                "naapi nahi gayi." + _EXAM_TAIL))


RECIPES: Dict[str, Any] = {
    "numeric_formula": _run_numeric_formula,
    "threshold": _run_threshold,
    "direction": _run_direction,
    "proportion_interval": _run_proportion_interval,
    "walk_forward": _run_walk_forward,
    "monte_carlo": _run_monte_carlo,
    "parameter_robustness": _run_parameter_robustness,
    "baseline_tournament": _run_baseline_tournament,
    "trade_expectancy": _run_trade_expectancy,
    "slot_expectancy": _run_slot_expectancy,
    "regime_split": _run_regime_split,
    "event_window": _run_event_window,
    # #171e — exam/padhai ke paanch. Ye hypothesis ke rasta se nahi aate
    # (`plan_exam_specs()` inhe banata hai), isliye science/trading run me
    # inka naam bhi nahi aata.
    "syllabus_coverage": _run_syllabus_coverage,
    "difficulty_mix": _run_difficulty_mix,
    "duplicate_questions": _run_duplicate_questions,
    "question_solvability": _run_question_solvability,
    "plan_time_budget": _run_plan_time_budget,
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


def _why_not_testable(hypothesis: Dict[str, Any],
                      craft_ask: bool = False) -> Tuple[str, str]:
    """Koi test hi nahi ban paayi — wajah teen me se ek, aur wo saaf likhi jaaye."""
    plan = _text_of(hypothesis, "experiment", "how_to_test", "falsification_test")
    # #155e sabse pehle: gaane ki farmaish par insaan/body-signal wali maang ko
    # uske ASLI shabd ke saath likha jaata hai. Ye "idea galat hai" nahi kehta.
    if craft_ask:
        phrase = human_subject_phrase(hypothesis)
        if phrase:
            return (HUMAN_SUBJECT_ON_CRAFT,
                    f"Is daawe ko naapne ke liye INSAAN chahiye — text me "
                    f"\"{phrase}\" likha hai (log, unka body-signal ya unka "
                    f"jawab). Wo naap is machine ke andar ho hi nahi sakti, "
                    f"aur maanga gaya tha banaya hua deliverable — isliye iska "
                    f"koi test banaya hi nahi gaya. Idea galat sabit nahi hua; "
                    f"sirf yahan naapa nahi ja sakta. Bane hue draft ka apna "
                    f"naap SONG LAB alag se karta hai.")
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
            kill_switch: bool = False, craft_ask: bool = False) -> Dict[str, Any]:
    """LAB stage: hypothesis → test spec → asli hisaab → imaandaar nateeja.

    Input dicts ko chhua nahi jaata (copy bhi nahi banate — sirf padhte hain),
    isliye ye stage confidence, validation ya novelty kabhi nahi badalta.

    `craft_ask=True` sirf tab bhejo jab user ne kuch BANWANE ko kaha ho (gaana,
    kavita). Us haalat me insaan par naapi jaane wali hypothesis ka test banta
    hi nahi — default False hai, isliye science/trading run ek akshar nahi
    badalta.
    """
    policy = policy or LabPolicy()
    if craft_ask and not policy.craft_ask:
        # Caller ki di hui policy ko jagah par nahi badalte (wo dobara use ho
        # sakti hai) — uski ek copy banti hai.
        policy = dataclass_replace(policy, craft_ask=True)
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
                code, detail = _why_not_testable(hypothesis, policy.craft_ask)
                block["verdict"] = NOT_TESTABLE_HERE
                block["verdict_reason"] = code
                block["detail"] = detail
                # Jis SHABD par ruke, wo bhi record hota hai — "naapa nahi ja
                # saka" bolna aur ye na batana ki kis wajah se, wahi purana
                # bemaani jumla hota. Reject-list isi field se banti hai.
                if code == HUMAN_SUBJECT_ON_CRAFT:
                    block["human_subject_phrase"] = human_subject_phrase(
                        hypothesis)
                    block["needs_human_subjects"] = True
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


def _ran_count(report: Dict[str, Any], recipe: str) -> int:
    """Kitne test SACH ME chale (PASS ya FAIL). DATA_MISSING yahan nahi ginta."""
    return sum(
        1 for block in report.get("hypotheses") or []
        for test in (block.get("tests") or [])
        if test.get("recipe") == recipe
        and test.get("status") in (TESTED_PASS, TESTED_FAIL))


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
    # bana. Ye seema LAB ke baad bhi sach hai, isliye audit me jaati hai. "Test
    # nahi chala" ko "hypothesis kamzor thi" padhna sabse aasaan galti hai —
    # line khud us farq ko bolti hai.
    # #150e — teen naye test ki apni-apni seema. Ye teeno "chal gaya" ke saath
    # hi likhi jaati hain, kyunki inka pass hona sabse aasaani se over-read hota
    # hai. Ginti asli results se aati hai (declare nahi ki jaati).
    ran_mc = _ran_count(report, "monte_carlo")
    if ran_mc:
        limits.append(
            f"{ran_mc} Monte-Carlo risk test chala, par ye DETERMINISTIC "
            "block-resample hai (held-out ke asli steps ka kram badal kar) — "
            "'thousands of random simulations' NAHI. Risk per trade sirf isi "
            "purane held-out se nikla hai; naya regime aane par ye number "
            "bemaani ho sakta hai.")
    ran_sweep = _ran_count(report, "parameter_robustness")
    if ran_sweep:
        limits.append(
            f"{ran_sweep} parameter-robustness sweep chala, par usme sirf ek "
            "parameter (drift lookback) badla gaya — poora strategy space nahi "
            "chhana gaya. Region me zinda edge bhi live market me chalne ka "
            "waada NAHI hai.")
    ran_tour = _ran_count(report, "baseline_tournament")
    if ran_tour:
        limits.append(
            f"{ran_tour} baseline tournament chala. "
            + market_data.BASELINE_SCOPE_NOTE)
    # #150g — trade-level naap ki seema. Ye SABSE aasaani se over-read hoti hai:
    # "expectancy positive nikli" ko log "paisa banega" padh lete hain. Isliye
    # do baat isi line me hain — sample kitna chhota tha, aur close-only data ki
    # wajah se intrabar SL-vs-TP ka faisla hua hi nahi.
    ran_trade = _ran_count(report, "trade_expectancy")
    if ran_trade:
        limits.append(
            f"{ran_trade} trade-level expectancy test chala (cost ke saath), par "
            "ye sirf CLOSE price par naapa gaya hai. "
            + market_data.CLOSE_ONLY_NOTE
            + " Chhote sample ki positive expectancy ko 'edge mil gaya' nahi "
            "padha jaaye.")
    # #150i — teen nayi naap ki apni-apni seema. Ye teeno IS liye likhi jaati
    # hain ki inka naam hi over-read hota hai: "session expectancy" sun kar log
    # London/New York samajh lete hain, "regime detection" sun kar live regime
    # engine, aur "macro-event windows" sun kar asli news calendar.
    ran_slot = _ran_count(report, "slot_expectancy")
    if ran_slot:
        limits.append(
            f"{ran_slot} slot-wise expectancy test chala, par slot data ke apne "
            "label se bana hai (ghanta / weekday / mahina / quarter). "
            + market_data.SESSION_NAME_NOTE)
    ran_regime = _ran_count(report, "regime_split")
    if ran_regime:
        limits.append(
            f"{ran_regime} regime-split test chala. Label sirf guzre hue bars se "
            "banta hai (yahi leakage se bachne ka tareeqa hai), par iska matlab "
            "ye NAHI ki regime badalne ka pata live me itni jaldi chalega. "
            + market_data.REGIME_RELATIVE_NOTE)
    ran_event = _ran_count(report, "event_window")
    if ran_event:
        limits.append(
            f"{ran_event} macro-event window test chala. "
            + market_data.EVENT_SHOCK_NOTE
            + " Jahan asli calendar mili wahan mode `calendar` likha hota hai — "
            "audit me mode dekh kar hi is naap ko padha jaaye.")
    # Jis hypothesis ka naap INSAAN par hota hai, uska yahan test hi nahi bana
    # (#155e). Ye seema LAB ke baad bhi sach hai, isliye audit me jaati hai.
    # "Test nahi chala" ko "hypothesis kamzor thi" padhna sabse aasaan galti hai —
    # line khud us farq ko bolti hai.
    human_blocked = [
        str(block.get("human_subject_phrase") or "")
        for block in report["hypotheses"] if block.get("needs_human_subjects")]
    if human_blocked:
        named = sorted({phrase for phrase in human_blocked if phrase})
        limits.append(
            f"{len(human_blocked)} hypothesis ka naap ASLI INSAAN par hota hai"
            + (" (" + ", ".join(named) + ")" if named else "")
            + " — app ke paas na insaan hai na uska data, isliye uska koi test "
            "banaya hi nahi gaya. Ye 'hypothesis kamzor thi' NAHI hai; ye "
            "'yahan naapi nahi ja sakti' hai. Gaane ke shabd ka apna naap SONG "
            "LAB alag se karta hai.")
    return limits


# #155e — audit me LAB ki seemaon ki chhat. Pehle ye ginti synthesizer me
# `[:4]` bankar hard-code thi, aur INSAAN wali seema list me SABSE AAKHIR me
# judti hai — 4 par rakhne se theek wahi nayi line kat jaati aur audit us baare
# me chup ho jaata (yahi galti #133b me media ke saath ho chuki hai). Ginti
# usi file me rehti hai jahan line banti hai, taaki naya branch jodte waqt ek
# hi jagah badalni pade. `tests/test_deliverable_guard.py` ise upar ki asli
# append-sites ki ginti se pin karta hai, isliye ye chupchaap purani nahi ho
# sakti.
# #150i — 11 se 14: slot / regime / event window ki teen nayi seema-line judi.
MAX_AUDIT_LIMIT_LINES = 14


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


# ── #171e — EXAM LAB: bana hua PAPER/PLAN khud naapa jaata hai ────────────────
# Ye upar wale hypothesis-lab ka bhai hai, uska badal nahi. Farq ek line me:
#   run_lab()      → HYPOTHESIS ko naapta hai (daawa sach lagta hai ya nahi)
#   run_exam_lab() → BANI HUI CHEEZ ko naapta hai (paper/plan theek bana ya nahi)
# Yahi kram SONG LAB (#141) me bhi hai, aur wajah wahi hai: deliverable ka apna
# naap hypothesis ke naap se alag sawaal hai, aur dono ko ek report me ghol dena
# hi purani galti hai.
EXAM_SUBJECT_ID = "EXAM-DELIVERABLE"
EXAM_RECIPES: Tuple[str, ...] = ("syllabus_coverage", "difficulty_mix",
                                 "duplicate_questions", "question_solvability",
                                 "plan_time_budget")
_EXAM_PAPER_RECIPES: Tuple[str, ...] = EXAM_RECIPES[:4]
_EXAM_PLAN_RECIPES: Tuple[str, ...] = EXAM_RECIPES[4:]

_EXAM_WHAT: Dict[str, str] = {
    "syllabus_coverage": "syllabus ke kitne topic par asli me question bana",
    "difficulty_mix": "question ek hi band me gire ya mix hue (proxy naap)",
    "duplicate_questions": "do question ek jaise nikle ya nahi",
    "question_solvability": "ginti wala hissa bounded calculator me chala ya nahi",
    "plan_time_budget": "plan ka time mile hue time me fit hai ya nahi",
}


def exam_material(text: Any = "", syllabus_text: Optional[Any] = None,
                  plan_text: Optional[Any] = None, ask: Optional[Any] = None,
                  policy: Optional[LabPolicy] = None) -> Dict[str, Any]:
    """Bane hue paper/plan ko EK baar parse karo — har recipe wahi saamaan padhe.

    Ek hi jagah parse hone ki wajah: paanch recipe agar apna-apna parse karein
    to dono ki ginti chupke se alag ho jaati hai, aur phir report kis paper par
    tiki hai ye pata hi nahi chalta (yahi galti #133b me media ke saath ho chuki
    hai — "mila" aur "padha" ki do ginti).

    `syllabus_text`/`plan_text` na do to wahi deliverable text dono ke liye
    padha jaata hai; alag do to sirf wahi padha jaata hai.
    """
    policy = policy or LabPolicy()
    body = str(text or "")
    syllabus_body = body if syllabus_text is None else str(syllabus_text or "")
    plan_body = body if plan_text is None else str(plan_text or "")
    questions = exammodel.questions_from_text(body)
    key = exammodel.answer_key_from_text(body)
    if key:
        questions = exammodel.apply_answer_key(questions, key)
    topics = exammodel.syllabus_topics(syllabus_body)
    plan_rows = exammodel.plan_rows_from_text(plan_body)
    # Kul time ka hisaab exammodel me hi rehta hai (ek hi jagah). Yahan sirf
    # itna dekha jaata hai ki farmaish us shakl ki hai ya nahi — na hone par
    # 0, jiska matlab "time budget naapa hi nahi gaya" (jhoothi 0 nahi).
    minutes = (exammodel.minutes_available_of(ask, policy.exam_daily_minutes)
               if hasattr(ask, "days_available") else 0.0)
    return {
        "questions": questions,
        "topics": topics,
        "plan_rows": plan_rows,
        "answer_key_pairs": len(key),
        "minutes_available": float(minutes),
        "daily_minutes": float(policy.exam_daily_minutes),
        # Ginti wala parichay — yahi report me jaata hai, poora paper nahi.
        "summary": {
            "questions": len(questions),
            "with_answer": sum(1 for q in questions if q.answer),
            "with_solution": sum(1 for q in questions if q.solution),
            "topics": len(topics),
            "plan_rows": len(plan_rows),
            "timed_plan_rows": sum(1 for row in plan_rows
                                   if float(row.get("minutes") or 0) > 0),
            "answer_key_pairs": len(key),
            "minutes_available": float(minutes),
            "daily_minutes": float(policy.exam_daily_minutes),
        },
    }


def plan_exam_specs(material: Optional[Dict[str, Any]] = None,
                    question: str = "", ask: Optional[Any] = None
                    ) -> List[TestSpec]:
    """Kaun-kaun naap banegi — MAANG aur SAAMAAN dono dekh kar.

    Ek zaroori baat: paper maanga gaya ho par ek bhi question na nikla ho, tab
    bhi chaaron paper-naap ki spec BANTI hai. Wo DATA_MISSING dikhengi (wajah
    `no_paper`), aur yahi imaandaar hai — spec hi na banane se report chup ho
    jaati aur "sab theek tha" jaisa lagta.
    """
    rows = material if isinstance(material, dict) else {}
    kind = str(getattr(ask, "kind", "") or "")
    want_paper = bool(rows.get("questions")) or kind in (exammodel.KIND_PAPER,
                                                        exammodel.KIND_BOTH)
    want_plan = bool(rows.get("plan_rows")) or kind in (exammodel.KIND_PLAN,
                                                        exammodel.KIND_BOTH)
    names: List[str] = []
    if want_paper:
        names.extend(_EXAM_PAPER_RECIPES)
    if want_plan:
        names.extend(_EXAM_PLAN_RECIPES)
    specs: List[TestSpec] = []
    for index, recipe in enumerate(names):
        specs.append(TestSpec(
            spec_id=_spec_id(EXAM_SUBJECT_ID, index),
            hypothesis_id=EXAM_SUBJECT_ID, recipe=recipe,
            what=_EXAM_WHAT.get(recipe, recipe),
            origin="exam_deliverable", question=str(question or ""),
            exam=rows))
    return specs


# EXAM LAB ki apni wajah-lines. `_ROLLUP_REASON` idhar jaan-boojh kar use nahi
# hoti: wo "ye hypothesis fail hui" kehti hai, aur yahan hypothesis naapi hi
# nahi ja rahi — BANA HUA paper/plan naapa ja raha hai. Ek hi wording dono
# jagah lagane se report jhooth bolne lagti (deliverable ki kami hypothesis ke
# khaate me chali jaati).
_EXAM_ROLLUP_REASON: Dict[str, str] = {
    TESTED_FAIL: "app ne apne bane paper/plan me khud kami pakdi",
    TESTED_PASS: "bane hue paper/plan ne app ki apni naap paar kar li (ye "
                 "'asli exam jaisa hai' NAHI hai)",
    DATA_MISSING: "naap ki spec bani, par usko chalane ka saamaan nahi mila",
    NOT_TESTABLE_HERE: "is farmaish me naapne layak koi paper/plan nahi tha",
    NOT_RUN: "naap chalayi hi nahi gayi",
}


def run_exam_lab(question: str = "", text: Any = "",
                 ask: Optional[Any] = None, syllabus_text: Optional[Any] = None,
                 plan_text: Optional[Any] = None,
                 policy: Optional[LabPolicy] = None,
                 kill_switch: bool = False,
                 material: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """EXAM LAB stage: bana hua paper/plan → naap → imaandaar nateeja.

    Zero network, zero Gemini call, zero randomness. Sab hisaab yahin hota hai
    aur calculator bounded hai (`SafeNumericExecutor`) — model ka likha koi code
    nahi chalta.
    """
    policy = policy or LabPolicy()
    executor = SafeNumericExecutor(NumericExecutionPolicy())
    if material is None:
        material = exam_material(text, syllabus_text=syllabus_text,
                                 plan_text=plan_text, ask=ask, policy=policy)
    report: Dict[str, Any] = {
        "ran": False,
        "kill_switch": bool(kill_switch),
        "policy": policy.to_dict(),
        "executor": executor.policy_report(),
        "seed": policy.seed,
        "gemini_calls": exammodel.GEMINI_CALLS,
        "provider_cost": 0,
        "material": dict(material.get("summary") or {}),
        "tests": [],
        "counts": {status: 0 for status in LAB_STATUSES},
        "verdict": NOT_RUN,
        "verdict_reason": "",
        "warnings": [],
        "disclaimer": LAB_DISCLAIMER,
        "note": "",
        # Ye flag kabhi badalte nahi — inhe exammodel se MIRROR kiya jaata hai
        # taaki do jagah do sach na ban jaayein.
        "paper_is_practice_only": exammodel.PAPER_IS_PRACTICE_ONLY,
        "is_exam_authority": exammodel.IS_EXAM_AUTHORITY,
        "answer_key_is_app_made": exammodel.ANSWER_KEY_IS_APP_MADE,
        "question_prediction_promised": exammodel.QUESTION_PREDICTION_PROMISED,
        "score_promised": exammodel.SCORE_PROMISED,
        "leaked_paper_used": exammodel.LEAKED_PAPER_USED,
        "difficulty_is_proxy": exammodel.DIFFICULTY_IS_PROXY,
        "network_used": exammodel.NETWORK_USED,
        "not_official_note": exammodel.NOT_OFFICIAL_NOTE,
        "is_established_fact": False,
        "real_world_experiment_pending": True,
    }
    if kill_switch:
        report["verdict_reason"] = "kill_switch"
        report["note"] = ("Exam lab band tha (kill switch), isliye koi naap "
                          "nahi chali — ye 'paper theek tha' NAHI hai.")
        return report
    specs = plan_exam_specs(material, question=question, ask=ask)
    if not specs:
        report["verdict"] = NOT_TESTABLE_HERE
        report["verdict_reason"] = "no_exam_deliverable"
        report["note"] = ("Na koi bana hua paper mila, na koi plan ki line — "
                          "isliye exam lab ke liye koi naap hi nahi bani.")
        return report
    deadline = time.monotonic() + policy.max_wall_seconds
    results = run_specs(specs, policy, executor, deadline)
    report["tests"] = [r.to_dict() for r in results]
    for result in results:
        report["counts"][result.status] += 1
    report["verdict"] = rollup(results)
    report["verdict_reason"] = _EXAM_ROLLUP_REASON[report["verdict"]]
    report["ran"] = any(r.status in (TESTED_PASS, TESTED_FAIL) for r in results)
    if any(r.status == NOT_RUN and r.reason_code == "budget_exhausted"
           for r in results):
        report["warnings"].append(
            "Exam lab ka time budget khatam hua — kuch naap chali hi nahi. "
            "Unhe 'fail' nahi, 'nahi hui' padha jaaye.")
    if not report["ran"]:
        report["note"] = ("Naap ki spec bani, par unme se ek bhi chal nahi "
                          "payi — wajah har row ke saath likhi hai.")
    return report


EXAM_LAB_SUBHEADING = "### App ne apne bane paper/plan ko khud kaise naapa (EXAM LAB)"

# EXAM report ki pehchaan. Hypothesis wali `run_lab()` report me bhi `tests`
# aur `note` hote hain, isliye sirf un key par bharosa karna galat tha: ek
# hypothesis-lab report `exam_lab_section()` me daal dene par jawab me "apne
# bane paper/plan ko naapa" ka block chhap jaata — jo naapa hi nahi gaya tha.
# Ye marker EXAM ki report me hi banta hai (`run_exam_lab` ka base dict), aur
# hypothesis wali report me kabhi nahi.
_EXAM_REPORT_MARKERS: Tuple[str, ...] = ("not_official_note", "material",
                                         "answer_key_is_app_made")


def is_exam_report(report: Optional[Dict[str, Any]] = None) -> bool:
    """Ye EXAM LAB ki report hai ya kisi doosre lab ki — shape se naapa gaya."""
    if not isinstance(report, dict):
        return False
    return any(marker in report for marker in _EXAM_REPORT_MARKERS)


def exam_lab_section(report: Optional[Dict[str, Any]] = None) -> str:
    """EXAM LAB ka nateeja padhne layak Hinglish block. Khaali report par ""."""
    if not is_exam_report(report):
        return ""
    tests = report.get("tests") or []
    if not tests and not report.get("note"):
        return ""
    lines: List[str] = [EXAM_LAB_SUBHEADING, "",
                        report.get("disclaimer") or LAB_DISCLAIMER, "",
                        str(report.get("not_official_note")
                            or exammodel.NOT_OFFICIAL_NOTE), ""]
    material = report.get("material") or {}
    if material:
        lines.append(
            f"- Naapa gaya saamaan: {material.get('questions', 0)} question, "
            f"{material.get('topics', 0)} syllabus topic, "
            f"{material.get('plan_rows', 0)} plan line "
            f"({material.get('timed_plan_rows', 0)} par time likha tha)")
    verdict = str(report.get("verdict") or NOT_RUN)
    lines.append(f"- Kul nateeja: {_VERDICT_LABEL.get(verdict, verdict)}")
    if report.get("verdict_reason"):
        lines.append(f"- Kyun: {report['verdict_reason']}")
    lines.append("")
    for test in tests:
        bits = [f"`{test.get('recipe')}`", str(test.get("status"))]
        if test.get("observed"):
            bits.append(f"naapa: {test['observed']}")
        if test.get("expected"):
            bits.append(f"chahiye tha: {test['expected']}")
        lines.append("- " + " | ".join(bits))
        if test.get("detail"):
            lines.append(f"  {test['detail']}")
    for warning in report.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    if report.get("note"):
        lines.append(f"- {report['note']}")
    return "\n".join(lines).rstrip() + "\n"


def _exam_ran(report: Dict[str, Any], recipe: str) -> int:
    """Ye naap SACH ME kitni baar chali (PASS ya FAIL). DATA_MISSING nahi ginta."""
    return sum(1 for test in report.get("tests") or []
               if test.get("recipe") == recipe
               and test.get("status") in (TESTED_PASS, TESTED_FAIL))


def exam_lab_limits(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Wo seemayein jo EXAM LAB ke baad BHI sach hain — audit me jaati hain.

    Har line NAAPI hui ginti par bani hai (`_exam_ran`), likhe daawe par nahi.
    Jo naap chali hi nahi, uski koi line nahi banti — aur jo chali, uski seema
    zaroor banti hai. Yahan sabse aasaan over-read ye hai: "paper LAB me pass
    ho gaya" ko "ye asli exam jaisa paper hai" padh lena.
    """
    if not is_exam_report(report) or not (report.get("tests") or []):
        return []
    limits: List[str] = [str(report.get("not_official_note")
                             or exammodel.NOT_OFFICIAL_NOTE)]
    counts = report.get("counts") or {}
    if _exam_ran(report, "syllabus_coverage"):
        limits.append(
            "Syllabus coverage naapi gayi hai, par topic ke SHABD milne par "
            "'cover ho gaya' maana jaata hai — question us topic ko theek "
            "gehrai tak poochta hai ya nahi, wo yahan naapa NAHI gaya.")
    if _exam_ran(report, "difficulty_mix"):
        limits.append(
            "Difficulty ka naap PROXY hai (lambai, option, marks, ginti se) — "
            "asli difficulty insaan ke attempt se naapi jaati hai (kitne logon "
            "ne galat kiya), aur wo data app ke paas nahi hai.")
    if _exam_ran(report, "duplicate_questions"):
        limits.append(
            "Duplicate ka naap shabd ke overlap se hua hai. Bilkul alag "
            "shabdon me likha wahi sawaal is naap se bach sakta hai, isliye "
            "'ek bhi duplicate nahi' ko 'sab sawaal alag mazmoon ke hain' nahi "
            "padha jaaye.")
    if _exam_ran(report, "question_solvability"):
        limits.append(
            "Solvability me sirf question ka GINTI wala hissa bounded "
            "calculator me chalaya gaya hai — jawab sahi hai ya nahi, aur "
            "answer key theek hai ya nahi, wo yahan naapa NAHI gaya.")
    if _exam_ran(report, "plan_time_budget"):
        limits.append(
            "Plan ka time-budget naapa gaya hai, par time me fit hona 'plan "
            "kaam karega' NAHI hai — seekhne ki raftaar insaan par depend "
            "karti hai aur wo yahan naapi nahi ja sakti.")
    missing = sorted({str(test.get("reason_code") or "")
                      for test in report.get("tests") or []
                      if test.get("status") == DATA_MISSING
                      and str(test.get("reason_code") or "")})
    if missing:
        limits.append(
            "Kuch naap chal hi nahi payi (" + ", ".join(missing) + ") — inhe "
            "'theek tha' nahi, 'naapa hi nahi gaya' padha jaaye.")
    if counts.get(TESTED_FAIL):
        limits.append(
            f"{counts[TESTED_FAIL]} naap FAIL hui — uski wajah upar row me "
            "likhi hai, aur us kami ko chhupaya nahi gaya hai.")
    if report.get("warnings"):
        limits.append("Exam lab ka time budget khatam hua — kuch naap adhoori "
                      "rah gayi.")
    return limits


# Append-site ki ginti isi file me rehti hai (wahi wajah jo `MAX_AUDIT_LIMIT_LINES`
# ke saath likhi hai): chhat kam rakhne se sabse AAKHIR wali line — FAIL ki
# ginti — chup-chaap kat jaati, aur audit theek us baare me chup ho jaata jo
# sabse zyada batane layak hai.
EXAM_MAX_AUDIT_LIMIT_LINES = 9


def exam_lab_public_record(report: Optional[Dict[str, Any]] = None
                           ) -> Dict[str, Any]:
    """Audit ke liye chhota record — ginti aur imaandaari ke flag, poora paper nahi."""
    if not isinstance(report, dict):
        return {"ran": False, "reason": "no_exam_lab"}
    counts = report.get("counts") or {}
    return {
        "ran": bool(report.get("ran")),
        "verdict": str(report.get("verdict") or NOT_RUN),
        "verdict_reason": str(report.get("verdict_reason") or ""),
        "tests": len(report.get("tests") or []),
        "counts": {status: int(counts.get(status, 0)) for status in LAB_STATUSES},
        "recipes_ran": {recipe: _exam_ran(report, recipe)
                        for recipe in EXAM_RECIPES},
        "material": dict(report.get("material") or {}),
        "gemini_calls": int(report.get("gemini_calls") or 0),
        "provider_cost": report.get("provider_cost", 0),
        "paper_is_practice_only": exammodel.PAPER_IS_PRACTICE_ONLY,
        "is_exam_authority": exammodel.IS_EXAM_AUTHORITY,
        "answer_key_is_app_made": exammodel.ANSWER_KEY_IS_APP_MADE,
        "question_prediction_promised": exammodel.QUESTION_PREDICTION_PROMISED,
        "score_promised": exammodel.SCORE_PROMISED,
        "leaked_paper_used": exammodel.LEAKED_PAPER_USED,
        "difficulty_is_proxy": exammodel.DIFFICULTY_IS_PROXY,
        "network_used": exammodel.NETWORK_USED,
        "randomness_used": False,
        "model_written_code_executed": False,
        "is_established_fact": False,
        "real_world_experiment_pending": True,
    }




