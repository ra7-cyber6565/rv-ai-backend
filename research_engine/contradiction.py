"""
ContradictionEngine — Spec Section 8 (Contradiction Detection) + §11 rebuild

Rule-based hai, zero Gemini call. Kaam:
    1. STANCE conflict  — ek source kehta hai "effective hai", dusra kehta hai
       "no significant effect".
    2. NUMERIC conflict — same cheez ke liye do sources bahut alag numbers dete
       hain (e.g. 12% vs 68%).
    3. RECENCY "conflict" — ye AB CONTRADICTION NAHI hai (neeche dekho).

Honesty: ye detection *possible* contradiction batati hai, proof nahi. Isliye
har finding ke saath "rule-based detection" note jaata hai — Spec Section 7/8 ke
hisaab se overclaim nahi karna.

§11 (2026-08-22) — contradiction rebuild. Live dark-matter report mein "takraav"
un sources ke beech dikhaya gaya tha jinka topic hi alag tha, aur wajah sirf ye
thi ki unke publication years alag the. Isliye ab:

  * Har contradiction ka structured schema hai: `normalized_proposition`,
    `source_a_claim`, `source_b_claim`, `opposing_direction`, `evidence_spans`,
    `method_difference`. Jo cheez in fields mein bhari na ja sake, wo
    contradiction ke naam par report nahi hoti.
  * Chaar tarah ki NAKLI contradiction reject hoti hai: sirf saal ka farq
    (`YEAR_ONLY`), topic hi alag (`TOPIC_MISMATCH`), ulti direction hi nahi
    (`NO_OPPOSING_DIRECTION`), aur "confidence alag hai" jaisi generic baat
    (`GENERIC_CONFIDENCE`).
  * "Naya paper isliye sahi hai" wali line hata di gayi — sirf date se kisi
    evidence ka weight tay nahi hota. Saal ka farq ab neutral context note hai.
  * Rejected findings phenke nahi jaate — `rejection_report()` mein rehte hain,
    taaki audit dekh sake ki kya-kya jaanch kar hataya gaya (jaankari na khoye).
  * `method_difference` khaali ho sakta hai, lekin uski WAJAH ab
    `method_comparison_status` mein likhi jaati hai (`COMPARED` /
    `METHOD_UNKNOWN` / `SAME_LEVEL`) aur report mein dono haalat mein ek line
    chhapti hai — line gayab ho jaana khud ek jhooth tha.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .consensus_gate import CONSENSUS_UNAVAILABLE
from .consensus_gate import evaluate as gate_consensus
from .models import EvidencePack, SourceRecord

_SUPPORT_CUES = (
    "effective", "significant improvement", "significantly improved", "increases",
    "increased", "improves", "improved", "beneficial", "reduces risk", "associated with",
    "supports", "confirmed", "efficacious", "positive effect", "faayda", "labh",
    # 2026-08-21 (cross-domain benchmark): upar ki poori list clinical-trial ki
    # angrezi thi ("efficacious", "reduces risk"). Engineering/archaeology/
    # economics/CS ke sources isi baat ko doosre shabdon mein kehte hain, isliye
    # unka stance NEUTRAL nikalta tha aur contradiction detect hi nahi hoti thi.
    # Ye cue jaan-boojh kar phrase-level hain (akela topic-shabd nahi), warna
    # har paper "SUPPORT" ban jaayega.
    "detected", "demonstrates", "demonstrated", "shows a", "shows that",
    "showed a", "showed that", "consistent with", "successfully reproduced",
    "reproduced the", "replicated", "confirms",
    # 2026-08-22 (§24 dark-matter acceptance): physical sciences apna POSITIVE
    # nateeja bahut baar "doosra option kaat kar" likhti hai, seedhe "supports"
    # se nahi:
    #   "baryon only models are rejected for 168 of the 175 galaxies"
    #   "the peaks cannot be fitted with baryons alone"
    #   "is difficult to explain without non baryonic dark matter"
    # In teenon ka stance NEUTRAL nikal raha tha, isliye rotation-curve paper aur
    # uske khilaaf wala radial-acceleration paper — jo EK HI 175 galaxies par
    # ulta nateeja kehte hain — kabhi pair hi nahi bante the aur report
    # `contradictions: []` chhaap deti thi (live failure #8 ka doosra sira).
    # Phrase-level hi rakha gaya hai; akela "rejected" ya "without" support nahi
    # banta. Negation pehle se `_all_negated()` sambhalta hai, isliye "the halo
    # fits are not required" jaisa ulta vaakya yahan se support nahi ginta.
    "are rejected", "is rejected", "were rejected", "was rejected",
    "ruled out", "rules out", "rule out",
    "cannot be fitted", "cannot be explained", "cannot be accounted for",
    "difficult to explain without", "hard to explain without",
    # 2026-08-26 (#114): naapa hua badlav bhi ek POSITIVE nateeja hai. Cross-
    # domain run mein archaeology ka asli claim-paper — "settlement counts fall
    # by 71% within this window", deurbanisation "overlapping a documented
    # weakening of the summer monsoon" — NEUTRAL nikal raha tha. Isliye uske
    # khilaaf khada paper ("monsoon weakening did not drive deurbanisation")
    # kabhi uske saamne nahi aaya; uski jagah ek speleothem *record* paper
    # (jo koi wajah claim hi nahi karta) khada ho jaata tha — yani report mein
    # nakli takraav aur asli takraav gayab.
    # "by" ke saath hi rakha gaya hai: "fall by 71%" ek naapa hua daawa hai,
    # akela "fall"/"drop" topic ka naam bhi ho sakta hai ("drop test").
    # Negation `_all_negated()` pehle se sambhalta hai ("did not fall by 71%").
    "fall by", "falls by", "fell by", "drop by", "drops by", "dropped by",
    "decline by", "declines by", "declined by",
    "rise by", "rises by", "rose by", "grew by", "grow by",
    "coincides with", "coincided with",
)
_OPPOSE_CUES = (
    "not effective", "ineffective", "no significant", "no effect", "no evidence",
    "failed to", "does not", "did not", "no association", "no benefit", "contradicts",
    # Keep the SUPPORT cue "consistent with" from firing inside this explicit
    # opposite phrase.
    "inconsistent with",
    "refuted", "disproved", "inconclusive", "no difference", "harmful", "adverse",
    "nuksan", "koi fayda nahi",
    # Domain-neutral "null result" ki bhaasha — har field mein milti hai.
    "not reproduced", "could not reproduce", "failed replication", "null result",
    "no detectable", "no measurable", "not preserved", "no useful", "no reduction",
    "no correlation", "no support for", "no improvement", "not statistically",
)
_HEDGE_CUES = ("may", "might", "suggests", "possible", "preliminary", "unclear",
               "further research", "limited evidence", "mixed")

# Neeche wale OPPOSE cue "null finding" ki seedhi ghoshna hain — inka matlab
# saaf hai. Aur _WEAK_SUPPORT_CUES wo shabd hain jo topic ke naam mein bhi aa
# jaate hain (jaise "minimum wage increases" — yahan "increases" claim nahi,
# sirf topic hai). Agar strong-oppose mila ho aur support ke naam par sirf yahi
# kamzor shabd hon, to stance OPPOSE hai — MIXED nahi. Warna ek asli null
# result sirf topic-shabd ki wajah se "mila-jula" ban jaata tha aur
# contradiction chhoot jaati thi.
_STRONG_OPPOSE_CUES = (
    "not effective", "ineffective", "no significant", "no effect", "no evidence",
    "failed to", "does not", "did not", "no association", "no benefit",
    "inconsistent with",
    "no difference", "refuted", "disproved", "not reproduced",
    "could not reproduce", "failed replication", "null result", "no detectable",
    "no measurable", "not preserved", "no useful", "no reduction",
    "no correlation", "no support for", "no improvement", "not statistically",
)
_WEAK_SUPPORT_CUES = ("increases", "increased", "improves", "improved",
                      "associated with")

# Support cue ke aage-peeche negation ho to wo support nahi hai:
# "no measurable improvement" mein "improvement" ko support maanna galat hai.
_NEGATORS = ("no ", "not ", "never ", "without ", "n't ", "neither ", "nor ",
             "failed to ", "unable to ", "cannot ", "could not ", "did not ",
             "does not ", "lack of ", "absence of ", "little ")

# ── #114: "humne ye dekha hi nahi" ≠ "humein ulta nateeja mila" ──────────────
# Live report mein ek calibration manual aur ek measurement paper ke beech
# "takraav" chhap gaya tha. Manual ka vaakya tha "the manual does not cover
# pressure cell maintenance" — usme "does not" hai, isliye stance OPPOSE nikla
# aur measurement paper ke SUPPORT ke saamne khada ho gaya. Lekin "hum ye maapa
# hi nahi" koi ulta nateeja nahi hai; ye scope ki baat hai.
#
# Isliye ek alag stance hai: NOT_EVALUATED. Ye OPPOSE se kamzor nahi, ALAG hai —
# na support ginta hai, na oppose, aur consensus/claim-level gates isse pair
# banane se saaf mana kar dete hain (jaankari phenki nahi jaati, reject list
# mein wajah ke saath rehti hai).
_NOT_EVALUATED_CUES = (
    "does not cover", "did not cover", "do not cover",
    "does not measure", "did not measure", "not measured",
    "does not report", "did not report", "not reported",
    "does not assess", "did not assess", "not assessed",
    "does not evaluate", "did not evaluate", "not evaluated",
    "does not address", "did not address",
    "does not examine", "did not examine", "not examined",
    "does not investigate", "did not investigate",
    "does not test", "did not test", "not tested for",
    "out of scope", "outside the scope", "beyond the scope",
    "no attempt was made", "was not studied", "were not studied",
    # Hinglish/Hindi — wahi baat apni bhasha mein.
    "nahi dekha gaya", "nahi naapa gaya", "nahi maapa gaya",
    "jaanch nahi ki", "shaamil nahi", "daayre se bahar",
)

_NUM_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
_YEAR_GAP = 6          # itne saal ka farq ho to recency conflict dekhte hain
_NUM_GAP = 20.0        # percentage points

# ── #114: sawaal se kitna juda hai, ye naapa jaata hai ───────────────────────
# `_on_same_question` pehle ek shabd match hone par "haan, ek hi sawaal" keh
# deti thi. Dark-matter run mein isi wajah se ek photometry-calibration paper
# (sirf "dark" + "matter" match) rotation-curve paper ke khilaaf khada kar diya
# gaya tha. Ab do raste hain — dono mein se ek poora ho:
#   * sawaal ke kam se kam itne ALAG HISSE chhoote hon (`_question_parts`), YA
#   * sawaal ke stems ka kam se kam 40% chhoota ho (chhote sawaal ke liye).
#
# 40% hi kyun: dark-matter ka nakli jodaa (calibration paper, sirf "dark
# matter") 2/6 = 0.33 par baith raha tha, aur asli chhote sawaal ("vitamin D
# fracture risk" par "fracture risk" wala paper) 2/3 = 0.67 par. Bar in dono
# ke beech hai, kisi ek fixture par nahi.
MIN_QUESTION_COVERAGE = 0.40
# Mile-juli bhasha ka doosra raasta: sawaal ke kam se kam itne alag hisse
# chhoote hon. 2 hi kyun — sirf topic ka naam ("dark matter") ek hissa hota
# hai, aur usi par nakli takraav bante the; do alag hisse chhoona matlab source
# ne sawaal ka topic AUR uska doosra sira dono chhua hai. Ye ginti bhasha par
# nahi tikti, isliye Hinglish sawaal ko saza nahi milti.
MIN_QUESTION_PARTS = 2
# Yahan pehle ek teesra raasta bhi tha: `MIN_QUESTION_STEM_HITS = 3` — "3 alag
# stem chhoo liye to link asli maan lo". 2026-08-27 ke mutation test ne use
# KAAGZI sabit kiya: bar ko 3 se 4 kar dene par ek bhi test red nahi hua, yani
# koi asli behaviour us par tikta hi nahi tha (jo bhi source 3 stem chhoota
# hai, wo ya do hisse chhoo raha hai ya 40% coverage paar kar raha hai). Aur
# wo raasta gate ko KAMZOR kar raha tha: "dark matter evidence in galaxy
# rotation curves" jaise sawaal mein ek hi hisse ke teen shabd ("dark matter
# evidence") echo karne wala junk paper us se pass ho jaata. Isliye raasta
# hataya gaya, dheela nahi kiya gaya — do raste bache, dono naape hue hain.

# ── §11: nakli contradiction ke codes ────────────────────────────────────────
# Ye free-text nahi, ginne-layak codes hain — audit inhe count kar sakta hai.
CONTRA_YEAR_ONLY = "YEAR_ONLY"
CONTRA_TOPIC_MISMATCH = "TOPIC_MISMATCH"
CONTRA_NO_OPPOSITE = "NO_OPPOSING_DIRECTION"
CONTRA_GENERIC_CONFIDENCE = "GENERIC_CONFIDENCE"
CONTRA_NO_PROPOSITION = "NO_SHARED_PROPOSITION"
# #114 ke do naye code — dono ki wajah apni hai, aur dono reject list mein
# ginne-layak hain (chup-chaap skip karna hi purani galti thi).
CONTRA_NOT_EVALUATED = "SOURCE_DID_NOT_EVALUATE"
CONTRA_WEAK_QUESTION_LINK = "WEAK_QUESTION_LINK"
CONTRA_REJECT_CODES = (CONTRA_YEAR_ONLY, CONTRA_TOPIC_MISMATCH, CONTRA_NO_OPPOSITE,
                       CONTRA_GENERIC_CONFIDENCE, CONTRA_NO_PROPOSITION,
                       CONTRA_NOT_EVALUATED, CONTRA_WEAK_QUESTION_LINK)
CONTRA_REJECT_WHY = {
    CONTRA_YEAR_ONLY: ("Farq sirf publication year ka tha. Purana-naya hona takraav "
                       "nahi hai, aur sirf date se kisi evidence ka weight tay nahi "
                       "hota."),
    CONTRA_TOPIC_MISMATCH: ("Dono sources ek hi baat par nahi bol rahe — alag topic "
                            "ke do papers ka 'takraav' banana jhooth hai."),
    CONTRA_NO_OPPOSITE: ("Direction ulti nahi hai — ek 'haan' aur doosra 'na' nahi keh "
                         "raha, isliye ye takraav nahi."),
    CONTRA_GENERIC_CONFIDENCE: ("Wajah sirf 'confidence alag hai' jaisi generic baat "
                                "thi, koi ulta nateeja nahi."),
    CONTRA_NO_PROPOSITION: ("Ek common proposition (kis baat par takraav hai) nikal hi "
                            "nahi paayi — bina proposition contradiction likhna galat "
                            "hai."),
    CONTRA_NOT_EVALUATED: ("Doosre source ne ye cheez maapi hi nahi — 'humne ye nahi "
                           "dekha/report nahi kiya' scope ki baat hai, ulta nateeja "
                           "nahi. Ise takraav kehna jhooth hota."),
    CONTRA_WEAK_QUESTION_LINK: ("Source sawaal se sirf ek-do aam shabd par juda tha "
                                "(jaise topic ka naam), poori baat par nahi — itne "
                                "kam overlap se takraav nahi banta."),
}

# ── §11: method-comparison ke honest status codes ────────────────────────────
# Khaali `method_difference` do bilkul alag baaton ka matlab ho sakta hai:
#   (1) dono sources ka study design pata hi nahi chala  → COMPARE nahi hua
#   (2) dono ka design ek hi level ka tha                → farq hi nahi tha
# Inhe ek jaisa dikhana wahi purani galti hai (None aur False ko mila dena),
# isliye status alag code mein rakha jaata hai.
METHOD_CMP_COMPARED = "COMPARED"
METHOD_CMP_UNKNOWN = "METHOD_UNKNOWN"
METHOD_CMP_SAME_LEVEL = "SAME_LEVEL"
METHOD_CMP_CODES = (METHOD_CMP_COMPARED, METHOD_CMP_UNKNOWN, METHOD_CMP_SAME_LEVEL)
METHOD_CMP_WHY = {
    METHOD_CMP_COMPARED: ("Dono sources ke method/sample ke baare mein kuch "
                          "record mila, isliye farq neeche likha gaya hai."),
    METHOD_CMP_UNKNOWN: ("Method ka farq dekha nahi ja saka — in dono sources ki "
                         "study design (kaise test kiya gaya) ka record nahi mila. "
                         "'Method same tha' likhna jhooth hota."),
    METHOD_CMP_SAME_LEVEL: ("Dono ka study design ek hi level ka nikla, isliye "
                            "method ke naam par koi farq nahi bacha."),
}

# Sentence tod-ne ke liye — passage nikalte waqt poora snippet nahi, sirf wahi
# vaakya chahiye jisme daawa hai.
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


@dataclass
class Contradiction:
    kind: str
    summary: str
    source_ids: List[str] = field(default_factory=list)
    detail: str = ""
    severity: str = "MEDIUM"
    # ── §11 structured schema ────────────────────────────────────────────────
    normalized_proposition: str = ""
    source_a_claim: str = ""
    source_b_claim: str = ""
    opposing_direction: Optional[bool] = None
    evidence_spans: List[Dict] = field(default_factory=list)
    method_difference: str = ""
    # §11 (2026-08-22 self-audit): `method_difference` bahut baar khaali rehta
    # hai (dono sources ka study design record nahi hota). Khaali field ko chup
    # chaap chhod dena galat tha — report se line hi gayab ho jaati thi aur padhne
    # wale ko lagta tha ki method ka farq DEKHA gaya aur kuch nahi mila. Ab wajah
    # alag field mein likhi jaati hai, aur report dono haalat mein ek line
    # chhaapti hai.
    method_comparison_status: str = ""
    context_notes: List[str] = field(default_factory=list)
    valid: bool = True
    reject_code: str = ""
    reject_reason: str = ""

    def schema_complete(self) -> bool:
        """Schema poora hai ya nahi — adhoore record ko takraav nahi maana jaata."""
        return bool(self.normalized_proposition and self.source_a_claim
                    and self.source_b_claim and self.opposing_direction is True
                    and len(self.source_ids) >= 2)

    def method_status(self) -> str:
        """
        Method-comparison ka code — purane records (jinme status set nahi hai)
        ke liye bhi kaam kare, isliye khaali hone par text se guess karte hain.
        """
        if self.method_comparison_status in METHOD_CMP_CODES:
            return self.method_comparison_status
        return METHOD_CMP_COMPARED if self.method_difference.strip() else METHOD_CMP_UNKNOWN

    def method_line(self) -> str:
        """
        Report ke liye ek line — DONO haalat mein kuch kehti hai. Pehle jab
        `method_difference` khaali hota tha to line hi gayab ho jaati thi, aur
        padhne wale ko lagta tha ki method check ho chuka hai.
        """
        status = self.method_status()
        if status == METHOD_CMP_COMPARED and self.method_difference.strip():
            return self.method_difference.strip()
        return METHOD_CMP_WHY.get(status, METHOD_CMP_WHY[METHOD_CMP_UNKNOWN])

    def to_dict(self) -> Dict:
        # `evidence_spans` mein spec ka "S1 page 4" bhi hai (`ref`) aur uske saath
        # asli passage + locator bhi — string se zyada, kam nahi.
        return {
            "type": self.kind,
            "summary": self.summary,
            "sources": self.source_ids,
            "detail": self.detail,
            "severity": self.severity,
            "normalized_proposition": self.normalized_proposition,
            "source_a_claim": self.source_a_claim,
            "source_b_claim": self.source_b_claim,
            "opposing_direction": self.opposing_direction,
            "evidence_spans": list(self.evidence_spans),
            "evidence_span_refs": [str(sp.get("ref") or "") for sp in self.evidence_spans],
            "method_difference": self.method_difference,
            "method_comparison_status": self.method_status(),
            "method_comparison_why": self.method_line(),
            "context_notes": list(self.context_notes),
            "schema_complete": self.schema_complete(),
            "valid": self.valid,
            "reject_code": self.reject_code,
            "reject_reason": self.reject_reason,
            "note": "rule-based detection — automatic hai, manually verify karna zaroori hai",
        }


class ContradictionEngine:
    def __init__(self) -> None:
        # §11 — jaanch kar hataye gaye "takraav" yahan rehte hain (phenke nahi
        # jaate), taaki audit dekh sake ki kya-kya reject hua aur kyun.
        self.last_rejected: List[Contradiction] = []

    # ── stance ───────────────────────────────────────────────────────────────
    def _all_negated(self, low: str, cue: str) -> bool:
        """
        Cue ki HAR jagah negation ke peeche hai ya nahi.

        "no measurable improvement in throughput" — yahan "improvement" ko
        support maanna galat hai. Sirf tab True jab cue ka koi bhi occurrence
        bina negation ke na ho (yani ek jagah bhi seedha daawa ho to support
        maana jaayega).
        """
        hits = 0
        negated = 0
        start = 0
        while True:
            i = low.find(cue, start)
            if i < 0:
                break
            hits += 1
            if any(n in low[max(0, i - 16):i] for n in _NEGATORS):
                negated += 1
            start = i + len(cue)
        return hits > 0 and negated == hits

    def _scope_spans(self, low: str) -> List[Tuple[int, int]]:
        """"Ye humne dekha hi nahi" wale phrase kahan-kahan aaye — unke spans."""
        spans: List[Tuple[int, int]] = []
        for cue in _NOT_EVALUATED_CUES:
            start = 0
            while True:
                i = low.find(cue, start)
                if i < 0:
                    break
                spans.append((i, i + len(cue)))
                start = i + 1
        return spans

    def _only_scope_denial(self, low: str, opposing: Sequence[str]) -> bool:
        """
        Saara "na" sirf scope ki baat hai ya nahi.

        True sirf tab jab HAR oppose cue ka HAR occurrence kisi
        not-evaluated phrase ke andar ho. Yani:
          "the manual does not cover pressure cells"        → True  (scope)
          "the drug did not reduce risk; we did not measure
           bone density"                                    → False (asli null
                                                              result bhi hai)
        Ek bhi seedha null-result bacha ho to ye OPPOSE hi rehta hai — guard
        detection kamzor nahi karta.
        """
        spans = self._scope_spans(low)
        if not spans:
            return False
        for cue in opposing:
            start = 0
            while True:
                i = low.find(cue, start)
                if i < 0:
                    break
                if not any(s <= i and i + len(cue) <= e for s, e in spans):
                    return False
                start = i + 1
        return True

    def stance(self, text: str) -> Tuple[str, List[str]]:
        low = (text or "").lower()
        # Pehle OPPOSE dekho — "not effective" ke andar "effective" bhi aata hai
        opposing = [c for c in _OPPOSE_CUES if c in low]
        supporting = [c for c in _SUPPORT_CUES if c in low and
                      not any(c in o for o in opposing) and
                      not self._all_negated(low, c)]
        hedging = [c for c in _HEDGE_CUES if c in low]

        # #114 — "hum ye maapa hi nahi" na support hai na oppose. Ye check
        # support/oppose ke faisle se PEHLE aata hai, lekin sirf us haalat mein
        # jab koi seedha daawa (support cue) bhi na ho aur saare "na" scope wale
        # phrase ke andar hi hon. Aur agar sirf scope ki baat likhi hai (koi
        # cue hi nahi), tab bhi ye NEUTRAL nahi hai: "hum ye naapa hi nahi"
        # ek naapi hui baat hai, "kuch stance nahi mila" nahi.
        scope_cues = [c for c in _NOT_EVALUATED_CUES if c in low]
        if scope_cues and not supporting:
            if not opposing or self._only_scope_denial(low, opposing):
                return "NOT_EVALUATED", scope_cues

        if opposing and supporting:
            strong = [c for c in opposing if c in _STRONG_OPPOSE_CUES]
            if strong and all(c in _WEAK_SUPPORT_CUES for c in supporting):
                # Saaf null result + support ke naam par sirf topic-shabd →
                # ye MIXED nahi, OPPOSE hai.
                return "OPPOSE", opposing
            return "MIXED", opposing + supporting
        if opposing:
            return "OPPOSE", opposing
        if supporting:
            return "SUPPORT", supporting
        if hedging:
            return "HEDGED", hedging
        return "NEUTRAL", []

    def _percentages(self, text: str) -> List[float]:
        out = []
        for m in _NUM_RE.findall(text or ""):
            try:
                value = float(m)
            except ValueError:
                continue
            if 0.0 <= value <= 100.0:
                out.append(value)
        return out

    _STEM_SUFFIXES = ("ational", "ation", "ically", "ingly", "ities", "ility", "ising",
                      "izing", "ments", "ement", "ness", "ions", "ing", "ies", "ial",
                      "ic", "al", "ed", "es", "s")

    def _stem(self, word: str) -> str:
        """Halka stemmer — 'discrimination'/'discriminatory' ko paas laata hai."""
        for suffix in self._STEM_SUFFIXES:
            if len(word) - len(suffix) >= 5 and word.endswith(suffix):
                return word[: -len(suffix)]
        return word

    def _stems(self, text: str) -> set:
        return {self._stem(w) for w in re.findall(r"[a-z]{4,}", (text or "").lower())}

    def _topic_overlap(self, a: SourceRecord, b: SourceRecord) -> int:
        return len(self._stems(f"{a.title} {a.snippet}") &
                   self._stems(f"{b.title} {b.snippet}"))

    def _question_parts(self, question: str) -> List[set]:
        """
        Sawaal ko uske alag-alag HISSON mein todta hai.

        #114 — coverage ka bhaag (hits/total) mile-juli bhasha ke sawaal ko saza
        deta hai. "Indus valley civilisation ke shehron ka patan monsoon ke
        badlav se hua ya vyapar toot jaane se…" ke 14 stems mein 9 Hindi shabd
        hain (patan, shehron, vyapar, sabooton, badlav, toot…). Koi English
        paper unhe kabhi match nahi karega, isliye uska maximum coverage hi
        0.36 hai — 40% ka darwaza uske liye band tha, chahe wo bilkul isi
        sawaal ka ulta jawab de raha ho.

        Isliye ginti badalti hai: sawaal ke KITNE ALAG HISSE chhoote hain. Hissa
        = lagataar 4+ akshar wale shabdon ka jodaa (chhota function word —
        "ka", "se", "ya", "in", "the" — hissa tod deta hai). "dark matter
        evidence in galaxy rotation curves" ke do hisse hain; sirf topic ka naam
        ("dark matter") chhoone wala source ek hi hissa chhoota hai, aur ab bhi
        reject hota hai. Wahi paper jo sawaal ke do alag hisson par baat karta
        hai (jaise "Indus … monsoon"), pass hota hai — bhasha ki saza khatam.
        """
        parts: List[set] = []
        current: set = set()
        for word in re.findall(r"[a-z]+", (question or "").lower()):
            if len(word) >= 4:
                current.add(self._stem(word))
                continue
            if current:
                parts.append(current)
                current = set()
        if current:
            parts.append(current)
        return parts

    def _question_link(self, a: SourceRecord, b: SourceRecord, question: str,
                       min_shared: int = 1) -> Tuple[bool, str]:
        """
        Dono sources usi sawal ke keywords chhoote hain ya nahi — aur KITNA.

        Zaroori kyun: pehle version pairwise word-overlap maangta tha, jisse do
        aise sources jo *ek hi sawal* ka ulta jawab dete hain lekin alag
        vocabulary use karte hain (ek "bias increased" bole, dusra "no
        association") skip ho jaate the — yani asli contradiction miss.
        Pack ek hi sawal ke liye bana hai, isliye question-level overlap kaafi
        hai; pairwise overlap ab sirf severity/caveat tay karta hai.

        #114 — par "ek shabd chhoo liya" bhi kaafi maan liya gaya tha, aur usse
        topic ke naam par nakli takraav bante the. Ab do raste hain, koi ek
        poora hona chahiye (warna reject code ke saath laut jaata hai):
          * 0 shabd  → `NO_SHARED_PROPOSITION` (purana behaviour, waisa hi)
          * sawaal ke 2 ALAG hisse chhoote hon (`_question_parts` — mile-juli
            bhasha ke lambe sawaal ka imaandaar raasta), YA
          * stems ka 40% chhoota ho (chhote sawaal ke liye).
        Dono mein se koi bhi pura na ho → `WEAK_QUESTION_LINK`.
        """
        topic = {w for w in self._stems(question) if len(w) >= 4}
        if not topic:
            return True, ""
        parts = self._question_parts(question)
        for s in (a, b):
            stems = self._stems(f"{s.title} {s.snippet}")
            hits = len(stems & topic)
            if hits < max(1, min_shared):
                return False, CONTRA_NO_PROPOSITION
            touched = sum(1 for part in parts if part & stems)
            if touched >= MIN_QUESTION_PARTS:
                continue
            if (hits / float(len(topic))) < MIN_QUESTION_COVERAGE:
                return False, CONTRA_WEAK_QUESTION_LINK
        return True, ""

    def _on_same_question(self, a: SourceRecord, b: SourceRecord, question: str,
                          min_shared: int = 1) -> bool:
        """`_question_link` ka haan/na — purane callers ke liye."""
        return self._question_link(a, b, question, min_shared)[0]

    def _shared_topic(self, a: SourceRecord, b: SourceRecord, min_words: int = 3) -> bool:
        """Do sources ek hi baat pe baat kar rahe hain ya nahi — mota andaaza."""
        return self._topic_overlap(a, b) >= min_words

    # ── main ─────────────────────────────────────────────────────────────────
    def _methodology_comparison(self, s1: SourceRecord, s2: SourceRecord) -> Optional[str]:
        """
        Spec §8 enhancement: methodology compare karo conflicting sources ke beech.
        Returns comparison note ya None.
        """
        m1 = s1.methodology or "unknown"
        m2 = s2.methodology or "unknown"
        r1 = s1.methodology_rank
        r2 = s2.methodology_rank

        # Dono unknown — compare nahi kar sakte
        if m1 == "unknown" and m2 == "unknown":
            return None

        # Ek stronger design ka hai
        if r1 > r2:
            from .quality_signals import methodology_label
            return (f"Note: {s1.source_id} stronger design hai ({methodology_label(m1)}) "
                   f"vs {s2.source_id} ({methodology_label(m2)})")
        elif r2 > r1:
            from .quality_signals import methodology_label
            return (f"Note: {s2.source_id} stronger design hai ({methodology_label(m2)}) "
                   f"vs {s1.source_id} ({methodology_label(m1)})")

        return None

    def _method_comparison_status(self, s1: SourceRecord, s2: SourceRecord,
                                  note: str = "") -> str:
        """
        §11 — method compare HUA ya nahi, ye alag baat hai method mein farq
        MILA ya nahi se. Khaali note ki wajah honestly record karte hain.
        """
        if (note or "").strip():
            return METHOD_CMP_COMPARED
        m1 = (getattr(s1, "methodology", "") or "unknown")
        m2 = (getattr(s2, "methodology", "") or "unknown")
        if m1 == "unknown" and m2 == "unknown":
            return METHOD_CMP_UNKNOWN
        # Ek ya dono ka design pata hai, phir bhi note khaali — matlab dono ek
        # hi level ke nikle (rank tie), farq hi nahi tha.
        return METHOD_CMP_SAME_LEVEL

    def _sample_comparison(self, s1: SourceRecord, s2: SourceRecord) -> Optional[str]:
        """Extract sample size hints from snippet (if available)."""
        def _extract_n(text: str) -> Optional[int]:
            # Look for patterns like "N = 500" or "n=500" or "500 participants"
            patterns = [
                r'[Nn]\s*=\s*(\d+)',
                r'(\d+)\s+participants',
                r'sample\s+of\s+(\d+)',
                r'(\d+)\s+patients',
                r'(\d+)\s+subjects'
            ]
            for pattern in patterns:
                match = re.search(pattern, text or "")
                if match:
                    try:
                        return int(match.group(1))
                    except (ValueError, IndexError):
                        continue
            return None

        n1 = _extract_n(s1.snippet)
        n2 = _extract_n(s2.snippet)

        if n1 and n2:
            if n1 > n2 * 2:  # Significantly larger
                return f"Note: {s1.source_id} ki sample size kaafi badi hai (n≈{n1}) vs {s2.source_id} (n≈{n2})"
            elif n2 > n1 * 2:
                return f"Note: {s2.source_id} ki sample size kaafi badi hai (n≈{n2}) vs {s1.source_id} (n≈{n1})"

        return None

    def _temporal_comparison(self, s1: SourceRecord, s2: SourceRecord) -> Optional[str]:
        """
        §11 — saal ka farq sirf CONTEXT hai, weight ka faisla nahi.

        Pehle yahan likha jaata tha "newer evidence ko generally preference milti
        hai" — wahi line live report mein nakli contradictions ki jaan thi. Date
        se kisi evidence ka weight tay nahi hota (chhota naya paper bade purane
        replication ko nahi harata), isliye ab sirf tathya likhte hain.
        """
        if not s1.year or not s2.year:
            return None

        gap = abs(s1.year - s2.year)
        if gap >= _YEAR_GAP:
            newer = s1 if s1.year > s2.year else s2
            older = s2 if s1.year > s2.year else s1
            return (f"Note: dono ka saal alag hai ({older.source_id}: {older.year}, "
                    f"{newer.source_id}: {newer.year}) — ye sirf context hai, sirf "
                    f"naye hone se kisi source ko zyada weight nahi milta")

        return None

    # ── §11 structured contradiction ke tukde ────────────────────────────────
    def _claim_sentence(self, s: SourceRecord, cues: Sequence[str]) -> str:
        """
        Source ka WAHI vaakya jisme daawa hai (poora snippet nahi).

        Kyun: `source_a_claim` mein poora abstract chipka dena audit ke kaam ka
        nahi — "X ne Y badhaya" vs "X ne Y nahi badhaya" saamne dikhna chahiye.
        Cue wala pehla vaakya uthate hain; cue kahin na mile to pehla vaakya.
        """
        text = f"{(s.title or '').strip()}. {(s.snippet or '').strip()}".strip()
        sentences = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
        if not sentences:
            return ""
        for cue in cues:
            for sent in sentences:
                if cue in sent.lower():
                    return sent[:300]
        return sentences[0][:300]

    def _normalized_proposition(self, a: SourceRecord, b: SourceRecord,
                                question: str) -> str:
        """
        Ek hi vaakya jispar dono sources bol rahe hain.

        Sirf shared stems se banti hai — agar kuch shared na nikle to khaali
        string, aur khaali proposition ka matlab hai contradiction reject
        (`NO_SHARED_PROPOSITION`). Yahi cheez "exoplanet paper vs telescope
        calibration paper" wale nakli takraav ko rokti hai.

        #114 — pehle yahan ek fallback tha: agar shared stems mein sawaal ka koi
        shabd na ho, to *koi bhi* shared shabd utha kar proposition bana di
        jaati thi. Usse "in the" jaisi aam bhaasha ya do papers ke common
        boilerplate se bhi "takraav ki baat" ban jaati thi. Ab core sirf
        (shared ∩ sawaal) se banta hai — na bane to proposition khaali, aur
        jodi reject list mein wajah ke saath jaati hai.
        """
        shared = (self._stems(f"{a.title} {a.snippet}") &
                  self._stems(f"{b.title} {b.snippet}"))
        q_stems = self._stems(question)
        core = sorted(shared & q_stems, key=lambda w: (-len(w), w))[:4]
        if not core:
            return ""
        return (f"Takraav is baat par hai — {' / '.join(core)}: iska nateeja/asar "
                f"hota hai ya nahi")

    def _spans_for(self, s: SourceRecord, claim: str) -> Dict:
        """
        §11 — takraav ka saboot bhi wahi tukda ho jo padha gaya.

        `locator` jhooth nahi bolta: full text na pada ho to "abstract/snippet"
        likhte hain, "page 4" nahi.
        """
        locator = (getattr(s, "locator", "") or "").strip() or "abstract/snippet"
        return {
            "source_id": s.source_id,
            "passage": (claim or "")[:300],
            "locator": locator,
            "ref": f"{s.source_id} {locator}",
        }

    def _validate(self, c: Contradiction) -> Contradiction:
        """
        Nakli contradiction chhaanto. Reject hone par record bachta hai (audit ke
        liye), par `valid=False` ho jaata hai aur user ke jawab mein nahi jaata.

        #114 — jodi banane wali jagah pehle se wajah jaanti ho (scope, ya sawaal
        se kamzor jod), to wo `reject_code` set kar deti hai; yahan us code ko
        overwrite nahi karte, sirf uski wajah bhar dete hain.
        """
        if c.reject_code:
            c.valid = False
        elif c.kind == "SCOPE":
            c.valid, c.reject_code = False, CONTRA_NOT_EVALUATED
        elif c.kind == "RECENCY":
            c.valid, c.reject_code = False, CONTRA_YEAR_ONLY
        elif c.kind == "CONFIDENCE":
            c.valid, c.reject_code = False, CONTRA_GENERIC_CONFIDENCE
        elif not c.normalized_proposition:
            c.valid, c.reject_code = False, CONTRA_NO_PROPOSITION
        elif c.opposing_direction is not True:
            c.valid, c.reject_code = False, CONTRA_NO_OPPOSITE
        elif not (c.source_a_claim and c.source_b_claim):
            c.valid, c.reject_code = False, CONTRA_TOPIC_MISMATCH
        if not c.valid:
            c.reject_reason = CONTRA_REJECT_WHY.get(c.reject_code, "")
        return c

    def rejection_report(self) -> Dict:
        """Kitne 'takraav' jaanch kar hataye gaye, aur kis wajah se."""
        counts: Dict[str, int] = {code: 0 for code in CONTRA_REJECT_CODES}
        for c in self.last_rejected:
            if c.reject_code in counts:
                counts[c.reject_code] += 1
        return {
            "rejected": len(self.last_rejected),
            "counts": counts,
            "why": dict(CONTRA_REJECT_WHY),
            "examples": [c.to_dict() for c in self.last_rejected[:5]],
        }

    def detect(self, pack: EvidencePack) -> List[Contradiction]:
        sources = pack.sources
        found: List[Contradiction] = []
        self.last_rejected = []
        if len(sources) < 2:
            return found

        stances: Dict[str, Tuple[str, List[str]]] = {
            s.source_id: self.stance(f"{s.title}. {s.snippet}") for s in sources
        }
        question = pack.question or ""

        for i, a in enumerate(sources):
            for b in sources[i + 1:]:
                # Same origin ke do sources ka "conflict" matlab nahi rakhta
                if a.independence_key == b.independence_key:
                    continue

                overlap = self._topic_overlap(a, b)
                stance_a, cues_a = stances[a.source_id]
                stance_b, cues_b = stances[b.source_id]
                proposition = self._normalized_proposition(a, b, question)
                claim_a = self._claim_sentence(a, cues_a)
                claim_b = self._claim_sentence(b, cues_b)

                # #114 — ek taraf daawa, doosri taraf "humne ye dekha hi nahi".
                # Ye takraav NAHI hai. Chup-chaap skip bhi nahi karte — reject
                # list mein apne code ke saath jaata hai, taaki audit dekh sake.
                if "NOT_EVALUATED" in (stance_a, stance_b):
                    if {stance_a, stance_b} & {"SUPPORT", "OPPOSE", "MIXED"}:
                        skipped, other = ((a, b) if stance_a == "NOT_EVALUATED"
                                          else (b, a))
                        self.last_rejected.append(self._validate(Contradiction(
                            kind="SCOPE",
                            summary=f"{skipped.source_id} ne ye cheez maapi hi nahi "
                                    f"({other.source_id} ke daawe ka ulta nateeja nahi)",
                            source_ids=[a.source_id, b.source_id],
                            detail="Scope ka farq — 'report nahi kiya' aur 'ulta "
                                   "nikla' ek baat nahi hai.",
                            severity="LOW",
                            normalized_proposition=proposition,
                            source_a_claim=claim_a, source_b_claim=claim_b,
                            opposing_direction=False,
                            reject_code=CONTRA_NOT_EVALUATED)))
                    continue

                if {stance_a, stance_b} == {"SUPPORT", "OPPOSE"}:
                    # STANCE ke liye pairwise vocabulary match zaroori nahi —
                    # sawal-level relevance kaafi hai (dono isi pack mein hain).
                    linked, link_code = self._question_link(a, b, question)
                    if not linked:
                        self.last_rejected.append(self._validate(Contradiction(
                            kind="STANCE",
                            summary=f"{a.source_id} vs {b.source_id} — sawaal hi common "
                                    f"nahi nikla",
                            source_ids=[a.source_id, b.source_id],
                            normalized_proposition="", opposing_direction=True,
                            source_a_claim=claim_a, source_b_claim=claim_b,
                            reject_code=link_code)))
                        continue
                    if overlap >= 3:
                        severity = "HIGH" if (a.peer_reviewed and b.peer_reviewed) else "MEDIUM"
                        caveats = []
                    else:
                        severity = "MEDIUM" if (a.peer_reviewed and b.peer_reviewed) else "LOW"
                        caveats = ["Dhyan do: in dono ka wording kaafi alag hai, ho "
                                  "sakta hai ye ek hi cheez na maap rahe hon — pehle "
                                  "scope compare karo."]

                    # Spec §8 enhancements
                    method_note = self._methodology_comparison(a, b)
                    if method_note:
                        caveats.append(method_note)

                    sample_note = self._sample_comparison(a, b)
                    if sample_note:
                        caveats.append(sample_note)

                    temporal_note = self._temporal_comparison(a, b)
                    if temporal_note:
                        caveats.append(temporal_note)

                    detail_parts = [f"{a.source_id}: {', '.join(cues_a[:3])}",
                                   f"{b.source_id}: {', '.join(cues_b[:3])}"]
                    if caveats:
                        detail_parts.append(" | ".join(caveats))

                    # §11 — method ka farq alag field hai. Pata na ho to khaali
                    # rehta hai; "method same tha" likhna jhooth hota, kyunki
                    # humne dono ka poora method padha hi nahi. Lekin khaali
                    # field ki WAJAH ab alag status field mein likhi jaati hai,
                    # taaki report line gayab na ho.
                    method_diff = " | ".join(
                        n for n in (method_note, sample_note) if n)
                    found.append(self._validate(Contradiction(
                        kind="STANCE",
                        summary=f"{a.citation_label()} aur {b.citation_label()} "
                                f"ulti direction mein point kar rahe hain",
                        source_ids=[a.source_id, b.source_id],
                        detail=" | ".join(detail_parts),
                        severity=severity,
                        normalized_proposition=proposition,
                        source_a_claim=claim_a,
                        source_b_claim=claim_b,
                        opposing_direction=True,
                        evidence_spans=[self._spans_for(a, claim_a),
                                        self._spans_for(b, claim_b)],
                        method_difference=method_diff,
                        method_comparison_status=self._method_comparison_status(
                            a, b, method_diff),
                        context_notes=([temporal_note] if temporal_note else []),
                    )))
                    continue

                # NUMERIC/RECENCY ke liye pairwise topic overlap zaroori hai,
                # warna alag-alag cheezon ke numbers compare hone lagenge.
                if overlap < 3:
                    continue

                nums_a = self._percentages(f"{a.title} {a.snippet}")
                nums_b = self._percentages(f"{b.title} {b.snippet}")
                if nums_a and nums_b:
                    gap = abs(max(nums_a) - max(nums_b))
                    if gap >= _NUM_GAP:
                        found.append(self._validate(Contradiction(
                            kind="NUMERIC",
                            summary=f"Numbers match nahi karte: {a.source_id} "
                                    f"{max(nums_a):.0f}% vs {b.source_id} {max(nums_b):.0f}%",
                            source_ids=[a.source_id, b.source_id],
                            detail="Ho sakta hai dono alag cheez maap rahe hon — "
                                   "definitions check karo.",
                            severity="MEDIUM",
                            normalized_proposition=proposition,
                            source_a_claim=claim_a,
                            source_b_claim=claim_b,
                            # Number ka farq "ulti direction" hai — ek hi cheez ke
                            # do bahut alag maap.
                            opposing_direction=True,
                            evidence_spans=[self._spans_for(a, claim_a),
                                            self._spans_for(b, claim_b)],
                            method_difference=(self._methodology_comparison(a, b) or ""),
                            method_comparison_status=self._method_comparison_status(
                                a, b, self._methodology_comparison(a, b) or ""),
                        )))
                        continue

                # §11 — ek taraf pakka daawa, doosri taraf "may/suggests" wali
                # hedged baat. YE CONTRADICTION NAHI HAI. Pehle ye "RECENCY
                # conflict" ban kar report mein chhapta tha; asli mein farq sirf
                # saal ka aur "confidence alag hai" ka tha. Record dono haalat
                # mein rakhte hain (audit ke liye), report kisi mein nahi karte —
                # warna ye jodi chup-chaap gayab ho jaati aur audit ko pata bhi
                # nahi chalta ki ise dekh kar chhoda gaya tha.
                if {stance_a, stance_b} in ({"SUPPORT", "HEDGED"}, {"OPPOSE", "HEDGED"}):
                    if a.year and b.year and abs(a.year - b.year) >= _YEAR_GAP:
                        older, newer = sorted([a, b], key=lambda s: s.year or 0)
                        self.last_rejected.append(self._validate(Contradiction(
                            kind="RECENCY",
                            summary=f"{older.year} ka source aur {newer.year} ka source "
                                    f"alag confidence dikhate hain",
                            source_ids=[a.source_id, b.source_id],
                            detail="Sirf saal/confidence ka farq — takraav nahi.",
                            severity="LOW",
                            normalized_proposition=proposition,
                            source_a_claim=claim_a,
                            source_b_claim=claim_b,
                            opposing_direction=False,
                        )))
                    else:
                        self.last_rejected.append(self._validate(Contradiction(
                            kind="CONFIDENCE",
                            summary=f"{a.source_id} pakka keh raha hai, {b.source_id} "
                                    f"sirf 'ho sakta hai' keh raha hai",
                            source_ids=[a.source_id, b.source_id],
                            detail="Confidence ka farq — koi ulta nateeja nahi mila.",
                            severity="LOW",
                            normalized_proposition=proposition,
                            source_a_claim=claim_a,
                            source_b_claim=claim_b,
                            opposing_direction=False,
                        )))

        # Ek jodi ek hi baar report ho
        unique: List[Contradiction] = []
        seen = set()
        for c in found:
            key = (c.kind, tuple(sorted(c.source_ids)))
            if key in seen:
                continue
            seen.add(key)
            # §11 — invalid finding user tak nahi jaati, par khoti bhi nahi.
            if not c.valid:
                self.last_rejected.append(c)
                continue
            unique.append(c)
        return unique[:10]

    # ── consensus (Spec Section 7 + §11 gate) ────────────────────────────────
    def consensus_report(self, pack: EvidencePack,
                         contradictions: Optional[List[Contradiction]] = None,
                         contradiction_analysis_done: Optional[bool] = None,
                         reasoning_complete: Optional[bool] = None,
                         opposition_searched: Optional[bool] = None,
                         queries: Optional[List[str]] = None) -> Dict:
        """
        Sehmati ka level — par SIRF tab, jab §11 ki chhe shartein poori hon.

        `contradictions=None` = contradiction analysis chali hi nahi.
        `contradictions=[]`   = chali, kuch nahi mila. Dono alag baat hain, aur
        gate inhe alag hi treat karta hai.
        """
        # #114 — `NOT_EVALUATED` ki apni ginti hai. Ise NEUTRAL mein mila dena
        # jhooth hota: "hum ye maapa hi nahi" aur "koi stance nahi mila" alag
        # baatein hain. Ye na support ginta hai na oppose, isliye consensus level
        # par iska koi vote nahi.
        stance_counts = {"SUPPORT": 0, "OPPOSE": 0, "MIXED": 0, "HEDGED": 0,
                         "NEUTRAL": 0, "NOT_EVALUATED": 0}
        keys_by_stance: Dict[str, set] = {k: set() for k in stance_counts}

        for s in pack.sources:
            stance, _ = self.stance(f"{s.title}. {s.snippet}")
            stance_counts[stance] += 1
            keys_by_stance[stance].add(s.independence_key)

        # "Independent" = alag origin, alag URL nahi
        independent_support = len(keys_by_stance["SUPPORT"])
        independent_oppose = len(keys_by_stance["OPPOSE"])

        if independent_support and not independent_oppose and independent_support >= 3:
            level = "APPARENT CONSENSUS"
        elif independent_support and independent_oppose:
            level = "DISPUTED"
        elif not independent_support and not independent_oppose:
            level = "NO CLEAR STANCE"
        else:
            level = "LEANING"

        # §11 — gate. Shartein poori na hon to level chhapta hi nahi. Raw level
        # `level_if_gate_passed` mein rehta hai (developer/audit ke liye), taaki
        # jaankari na khoye — par user ke jawab mein sehmati ka daawa nahi jaata.
        gate = gate_consensus(
            pack, contradictions=contradictions,
            contradiction_analysis_done=contradiction_analysis_done,
            reasoning_complete=reasoning_complete,
            opposition_searched=opposition_searched,
            queries=queries,
            independent_sources=pack.independent_source_count,
        )
        report = {
            "level": level if gate.passed else CONSENSUS_UNAVAILABLE,
            "stance_counts": stance_counts,
            "independent_supporting_origins": independent_support,
            "independent_opposing_origins": independent_oppose,
            "contradictions_found": len(contradictions or []),
            "contradiction_analysis_done": bool(
                contradiction_analysis_done if contradiction_analysis_done is not None
                else contradictions is not None),
            "gate_passed": gate.passed,
            "gate": gate.to_dict(),
            "unmet_conditions": list(gate.unmet_reasons),
            "note": gate.note(),
        }
        if not gate.passed:
            report["level_if_gate_passed"] = level
        return report
