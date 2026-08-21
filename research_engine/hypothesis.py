"""
HypothesisEngine — Spec Section 10 (New Hypothesis Generation)

Sabse important rule (spec se): "AI ki generated hypothesis ko established fact
kabhi mat banana." Isliye:

    * har hypothesis ka status HARDCODED hai: "UNTESTED HYPOTHESIS"
    * har hypothesis ke saath test-design maanga jaata hai
    * confidence ko "evidence-backed" nahi, "reasoning-based" likha jaata hai

Hypothesis tab hi generate hoti hai jab sawal genuinely unresolved/creative ho
ya evidence contradictory ho — har chhote sawal pe hypothesis banana bekaar hai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import re as _re_module  # avoid conflict with module-level _FIELD_RE

from .models import EvidencePack

STATUS = "UNTESTED HYPOTHESIS"

_H_SPLIT_RE = re.compile(r"^\s*#{2,4}\s*(?:hypothesis|hypothesis\s*\d+)\b.*$",
                         re.IGNORECASE | re.MULTILINE)
# NOTE: `simple explanation`, `assumptions`, `if true`, `if false` baad mein
# add hue (2026-08-20) — intel ka rule: hypothesis ko aise samjhao jaise samne
# baithe bande ne ye concept pehle kabhi suna hi nahi. Sirf ek-line statement
# dena kaafi nahi hai.
# NOTE 2: `counter-evidence`, `required experiment|simulation` aur
# `falsification test` 2026-08-21 ko add hue (point 11). Wajah: spec har
# hypothesis se CHHE cheezein maangta hai — support, counter-evidence,
# assumptions, falsification test, required experiment/simulation, confidence.
# Pehle experiment aur falsification dono `how to test` ke andar chhipe the,
# isliye report ye alag-alag naap hi nahi sakti thi ki kya missing hai.
# ORDER MATTERS: lamba naam pehle likho ("falsification test" se pehle
# "falsification" likh do to label kabhi match nahi karega).
# Jaan-boojh kar BARE "falsification" label NAHI hai: model "Prediction:" ke
# neeche continuation line mein "Falsification: reject if ..." likhta hai, aur
# use alag field bana dene se prediction ka block toot jaata (aur uska
# falsification_condition gum ho jaata). Wo line prediction ke andar hi rehni
# chahiye — `Hypothesis.falsification_test` wahan se bhi utha leti hai.
_FIELD_NAMES = (
    r"statement|simple explanation|simple|reasoning|supporting evidence|against|"
    r"contradicting evidence|counter[\s\-]?evidence|evidence against|"
    r"novelty|assumptions?|prediction|"
    r"required experiment|required simulation|experimental plan|experiment|"
    r"simulation|"
    r"falsification test|how to falsify|"
    r"how to test|test|"
    r"if true|if false|risks|confidence")
_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**\s*(" + _FIELD_NAMES + r")"
    r"\s*\**\s*[:\-]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

# `_FIELD_RE` sirf EK line uthata hai (`.` newline match nahi karta). Gemini
# aksar multi-line likhta hai — "Reasoning:" ke neeche step-by-step chain, aur
# "Prediction:" ke neeche "Variables: / Expected outcome: / Measurement:" wali
# labelled lines. Purana parser un continuation lines ko chup-chaap phenk deta
# tha, isliye structured prediction kabhi complete nahi banti thi aur reasoning
# chain ki pehli line ke baad sab gum ho jaata tha.
# Isliye ab line-by-line scan hota hai: label mile to naya field shuru, warna
# line pichhle field ke saath jud jaati hai (agli label ya `##` heading tak).
_FIELD_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**\s*(" + _FIELD_NAMES + r")"
    r"\s*\**\s*[:\-]\s*(.*)$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_MAX_FIELD_CHARS = 4000   # runaway continuation se bachne ke liye

# "ye result ise galat sabit kar dega" wali baat pehchanne ke liye. Sirf keyword
# hai — koi model nahi, isliye ₹0 aur deterministic.
_FALSIFY_HINT_RE = re.compile(
    r"falsif|disprove|reject if|refute|null result|no change|no effect|"
    r"galat sabit|galat hogi|khaarij", re.IGNORECASE)

# ── point 11: evidence-sufficiency gate ──────────────────────────────────────
# Kyun: "kam se kam 3 testable hypotheses" ka matlab "har haalat mein 3" nahi
# hai. Do source aur wo bhi sirf snippet — us par 3 hypotheses likhna sirf
# tukka hai, aur tukke ko research kehna is project ka sabse bada mana kaam
# hai. Isliye pehle naapte hain ki evidence kitni hypotheses ka bojh utha
# sakta hai, aur jitna utha sakta hai utna hi maangte hain — baaki ke liye
# wajah likhte hain.
#
# Saare number yahan ek jagah, taaki report inhe naam le kar bata sake.
_GATE_MIN_RELEVANCE = 0.25   # relevance floor (relevance.py ka wahi floor)
_GATE_FULL_TARGET = 3        # 3+ hypotheses ke liye itne relevant source chahiye
_GATE_DEEP_TARGET = 2        # ...aur itne kam se kam abstract-level padhe hue


@dataclass
class EvidenceGate:
    """
    Kitni hypotheses banane layak evidence hai — aur kyun (insaani wajah).

    `allowed` upper limit hai, target nahi: agar user ne 2 maangi aur evidence 5
    ka bojh utha sakta hai, to 2 hi banengi.
    """
    requested: int = 0
    allowed: int = 0
    sufficient: bool = False       # True = 3+ hypotheses ka evidence hai
    relevant_sources: int = 0
    deep_sources: int = 0          # abstract ya full_text tak padhe hue
    full_text_sources: int = 0
    contradictions: int = 0
    total_sources: int = 0
    reason: str = ""

    @property
    def target(self) -> int:
        """Asal mein kitni maangni chahiye (request aur evidence, dono ka lihaaz)."""
        if self.allowed <= 0:
            return 0
        return min(max(1, self.requested or 1), self.allowed)

    @property
    def short_of_request(self) -> bool:
        return bool(self.requested) and self.allowed < self.requested

    def to_dict(self) -> Dict:
        return {
            "requested": self.requested,
            "allowed": self.allowed,
            "target": self.target,
            "sufficient": self.sufficient,
            "relevant_sources": self.relevant_sources,
            "deep_sources": self.deep_sources,
            "full_text_sources": self.full_text_sources,
            "contradictions": self.contradictions,
            "total_sources": self.total_sources,
            "reason": self.reason,
            "short_of_request": self.short_of_request,
        }


def evidence_gate(pack: Optional[EvidencePack], requested: int = 0,
                  contradictions: Optional[List[Dict]] = None) -> EvidenceGate:
    """
    Evidence naapo aur batao ki kitni hypotheses banana imaandaar hai.

    Rule (deterministic, report mein bhi yahi likha jaata hai):
      * relevant source = relevance floor (0.25) paar, reject nahi hua, aur
        retraction ka nishaan nahi
      * deep source = wahi relevant source jise kam se kam abstract level tak
        padha gaya
      * 3+ hypotheses = 3 relevant + 2 deep source (ya evidence mein asli
        takraav ho to 2 relevant + 1 deep — kyunki takraav hi wo jagah hai
        jahan nayi hypothesis ki sabse zyada zaroorat hoti hai)
      * 1 relevant source = sirf 1 hypothesis
      * 0 relevant source = 0 hypothesis (aur wajah saaf likhi jaati hai)
    """
    gate = EvidenceGate(requested=max(0, int(requested or 0)),
                        contradictions=len(contradictions or []))
    sources = list(getattr(pack, "sources", []) or []) if pack is not None else []
    gate.total_sources = len(sources)

    usable = [s for s in sources
              if float(getattr(s, "relevance_score", 0.0) or 0.0) >= _GATE_MIN_RELEVANCE
              and not str(getattr(s, "rejected_reason", "") or "").strip()
              and getattr(s, "retracted", None) is not True]
    gate.relevant_sources = len(usable)
    levels = [(s.reading_level() if hasattr(s, "reading_level") else "") for s in usable]
    gate.deep_sources = len([lvl for lvl in levels if lvl in ("abstract", "full_text")])
    gate.full_text_sources = len([lvl for lvl in levels if lvl == "full_text"])

    if not sources:
        gate.reason = ("ek bhi source retrieve nahi hua, isliye hypothesis banana "
                       "sirf andaza hota — nahi banayi.")
        return gate
    if not usable:
        gate.reason = (f"{len(sources)} source mile par ek bhi sawaal se juda "
                       f"(relevance {_GATE_MIN_RELEVANCE}+) nahi nikla, isliye "
                       f"hypothesis ka koi asli base nahi hai.")
        return gate

    strong = (gate.relevant_sources >= _GATE_FULL_TARGET
              and gate.deep_sources >= _GATE_DEEP_TARGET)
    conflict_route = (gate.contradictions > 0 and gate.relevant_sources >= 2
                      and gate.deep_sources >= 1)

    if strong or conflict_route:
        gate.sufficient = True
        gate.allowed = max(3, gate.requested)
        why = ("evidence mein asli takraav mila, isliye nayi hypothesis ki "
               "zaroorat bhi hai" if conflict_route and not strong
               else "kaafi relevant source hain aur unme se kuch gehrai tak padhe gaye")
        gate.reason = (f"{gate.relevant_sources} relevant source "
                       f"({gate.deep_sources} kam se kam abstract tak padhe, "
                       f"{gate.full_text_sources} ka poora text) — {why}.")
        return gate

    if gate.relevant_sources >= 2 and gate.deep_sources >= 1:
        gate.allowed = 2
        gate.reason = (f"sirf {gate.relevant_sources} relevant source hain aur "
                       f"{gate.deep_sources} gehrai tak padhe gaye — itne par 2 se "
                       f"zyada hypothesis likhna tukka ban jaata.")
        return gate

    gate.allowed = 1
    gate.reason = (f"evidence patla hai ({gate.relevant_sources} relevant source, "
                   f"{gate.deep_sources} gehrai tak padhe) — is par sirf 1 "
                   f"hypothesis imaandaari se ban sakti hai.")
    return gate


def _fields(chunk: str) -> List[tuple]:
    """Ek hypothesis block se (key, multi-line value) nikaalo, order barkarar."""
    found: List[list] = []
    current: Optional[list] = None
    for line in chunk.splitlines():
        if _HEADING_RE.match(line):
            current = None                      # naya section — field khatam
            continue
        match = _FIELD_LINE_RE.match(line)
        if match:
            # label ko normalize karo: "Counter-Evidence" / "counter  evidence"
            # dono ek hi key banein, warna parse() mein teen-teen spelling
            # handle karni padti hai (aur ek chhoot jaati hai).
            key = re.sub(r"[\s\-]+", " ", match.group(1).lower()).strip()
            current = [key, [match.group(2).strip()]]
            found.append(current)
            continue
        if current is not None and line.strip():
            current[1].append(line.strip())
    out = []
    for key, lines in found:
        value = "\n".join(l for l in lines if l).strip().strip("*").strip()
        out.append((key, value[:_MAX_FIELD_CHARS]))
    return out


@dataclass
class PredictionStructure:
    """
    Spec §10 requirement: structured prediction field.

    Ek hypothesis tab falsifiable hoti hai jab ye clear ho ki:
      1. Kaunse variables measure honge
      2. Expected outcome kya hai (numeric ranges, qualitative states)
      3. Measurement method kya hogi
      4. Kya result hypothesis ko reject kar dega
    """
    variables: List[str] = field(default_factory=list)     # ["blood glucose", "insulin sensitivity"]
    expected_outcome: str = ""                              # "30% reduction in fasting glucose"
    measurement_method: str = ""                            # "HOMA-IR index, fasting plasma glucose"
    falsification_condition: str = ""                       # "no significant change after 12 weeks"

    def to_dict(self) -> Dict:
        return {
            "variables": self.variables,
            "expected_outcome": self.expected_outcome,
            "measurement_method": self.measurement_method,
            "falsification_condition": self.falsification_condition,
        }

    @property
    def is_complete(self) -> bool:
        """Structured prediction tabhi complete jab saare fields meaningful hon."""
        return (len(self.variables) > 0
                and len(self.expected_outcome.strip()) >= 10
                and len(self.measurement_method.strip()) >= 10)


@dataclass
class Hypothesis:
    statement: str = ""
    simple: str = ""              # "simple words mein" — user-facing explanation
    reasoning: str = ""
    supporting_evidence: str = ""
    contradicting_evidence: str = ""
    novelty: str = ""
    assumptions: str = ""         # kya maan kar chal rahe hain
    prediction: Optional[PredictionStructure] = None  # spec §10: structured field
    prediction_text: str = ""                          # fallback: agar structured parse na ho
    how_to_test: str = ""
    experiment: str = ""          # point 11: required experiment / simulation
    falsification: str = ""       # point 11: falsification test (alag field)
    if_true: str = ""             # agar sahi nikli to kya badlega
    if_false: str = ""            # agar galat nikli to kya matlab hoga
    risks: str = ""
    confidence: str = ""
    status: str = STATUS          # kabhi override nahi hota

    @property
    def is_testable(self) -> bool:
        # `experiment_plan` = explicit "Required experiment" warna "How to test".
        # Pehle sirf `how_to_test` dekha jaata tha, isliye jis hypothesis ne
        # poora experiment design "Required experiment:" mein diya (jo humne
        # point 11 mein khud maanga hai) wo bhi "untestable" gini jaati thi.
        return len(self.experiment_plan) >= 20

    # ── point 11 ke chhe zaroori hisse ───────────────────────────────────────
    # Spec har hypothesis se maangta hai: support, counter-evidence,
    # assumptions, falsification test, required experiment/simulation,
    # confidence. Pehle in sab ka koi single naap nahi tha, isliye report ye
    # bata hi nahi sakti thi ki hypothesis "poori" hai ya aadhi.
    @property
    def falsification_test(self) -> str:
        """
        Explicit falsification field, warna prediction ka falsification
        condition, warna `how to test` ka wo hissa jisme "galat sabit" ki baat
        hai. Kuch bana kar nahi likhte — jo asal mein aaya wahi lautate hain.
        """
        if self.falsification.strip():
            return self.falsification.strip()
        if self.prediction and self.prediction.falsification_condition.strip():
            return self.prediction.falsification_condition.strip()
        for source in (self.how_to_test, self.prediction_text):
            text = (source or "").strip()
            if not text:
                continue
            if _FALSIFY_HINT_RE.search(text):
                return text
        return ""

    @property
    def experiment_plan(self) -> str:
        """Required experiment/simulation — alag field, warna test design."""
        return (self.experiment.strip() or self.how_to_test.strip())

    @property
    def missing_fields(self) -> List[str]:
        """
        Jo zaroori hisse nahi aaye — user ki bhasha mein. Khaali list = poori
        hypothesis (spec ke chhe requirement ke hisaab se).
        """
        missing: List[str] = []
        if len(self.supporting_evidence.strip()) < 10:
            missing.append("support dene wala evidence")
        if len(self.contradicting_evidence.strip()) < 10:
            missing.append("iske khilaf ka evidence (counter-evidence)")
        if len(self.assumptions.strip()) < 10:
            missing.append("assumptions")
        if len(self.falsification_test) < 15:
            missing.append("falsification test (kaunsa result ise galat karega)")
        if len(self.experiment_plan) < 20:
            missing.append("zaroori experiment/simulation")
        if not self.confidence.strip():
            missing.append("confidence")
        return missing

    @property
    def is_complete(self) -> bool:
        """Poori hypothesis = chhe zaroori hisse + testable + prediction."""
        return (not self.missing_fields
                and self.is_testable and self.has_prediction)

    @property
    def has_prediction(self) -> bool:
        """
        Prediction hi hypothesis ko falsifiable banati hai: agar 'kya observe hoga'
        likha hi nahi, to koi observation use galat sabit nahi kar sakta.
        """
        if self.prediction and self.prediction.is_complete:
            return True
        return len(self.prediction_text.strip()) >= 15

    def to_dict(self) -> Dict:
        """Structured prediction prefer karo, fallback to text."""
        pred = (self.prediction.to_dict()
                if self.prediction and self.prediction.is_complete
                else {"text": self.prediction_text, "structured": False})
        return {
            "status": STATUS,
            "statement": self.statement,
            "simple": self.simple,
            "reasoning": self.reasoning,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "novelty": self.novelty,
            "assumptions": self.assumptions,
            "prediction": pred,
            "has_prediction": self.has_prediction,
            "how_to_test": self.how_to_test,
            # point 11 — ye do alag se report hote hain, kyunki "test kar lenge"
            # aur "kaunsa result ise galat sabit karega" ek baat nahi hai.
            "experiment": self.experiment_plan,
            "falsification_test": self.falsification_test,
            "if_true": self.if_true,
            "if_false": self.if_false,
            "is_testable": self.is_testable,
            "risks": self.risks,
            "confidence_reasoning_based": self.confidence,
            "missing_fields": self.missing_fields,
            "is_complete": self.is_complete,
            "disclaimer": ("UNTESTED HYPOTHESIS — asli validation lab/field test se "
                          "hi hoga, AI-generated assumption ko fact mat maano"),
        }


class HypothesisEngine:
    # ── kab generate karna hai ───────────────────────────────────────────────
    def should_generate(self, plan: Dict, pack: EvidencePack,
                        contradictions: Optional[List[Dict]] = None,
                        evidence_level: str = "") -> bool:
        if plan.get("is_unresolved") or plan.get("is_creative"):
            return True
        if contradictions:
            return True
        if evidence_level in ("MIXED", "WEAK") and plan.get("is_scientific"):
            return True
        return False

    # ── PASS 5 prompt (Spec Section 10) ──────────────────────────────────────
    # `count` baad mein juda (2026-08-20): user ka prompt "kam se kam 3 nayi
    # hypotheses banao" keh sakta hai. Pehle yahan hard-coded "Maximum 2" tha,
    # yaani engine user ki explicit request KABHI poori nahi kar sakta tha.
    # Default 2 hai taaki purani positional call (`prompt(q, a, pack, plan)`)
    # bilkul waise hi chalti rahe.
    def prompt(self, question: str, analysis: str, pack: EvidencePack,
               plan: Dict, contradictions: Optional[List[Dict]] = None,
               count: int = 2, gate: Optional[EvidenceGate] = None) -> str:
        gaps = "\n".join(f"  - {c.get('summary', '')}" for c in (contradictions or [])[:5])
        gap_block = f"\nEVIDENCE CONFLICTS jo mile:\n{gaps}\n" if gaps else ""
        fields = ", ".join(plan.get("relevant_fields", [])[:4]) or "relevant fields"
        count = max(1, min(int(count or 2), 6))
        blocks = "\n\n".join(self._format_block(i) for i in range(1, count + 1))
        gate_block = self._gate_block(gate)

        return f"""Tum ek Hypothesis Generator ho. Tumhara kaam NAYI possibility
propose karna hai — literature ka summary dohrana nahi.

SAWAL: {question}

CURRENT EVIDENCE-BASED ANALYSIS:
{analysis[:4000]}
{gap_block}
SOURCES (sirf inhi ko cite karo, [S#] format mein):
{pack.to_prompt_block(max_chars_per_source=500)}
{gate_block}
Rules — ye tod'ne par output reject ho jaayega:
1. Hypothesis ko FACT ki tarah mat likho. Har hypothesis ka status
   "{STATUS}" hai.
2. Reasoning chain step-by-step likho: kaun se evidence se kaun sa step nikla.
3. Jo baat kisi source se supported nahi hai, use [NO-SOURCE] mark karo.
4. Test design REAL hona chahiye (kya measure karoge, control kya hoga,
   kitna sample, kya result hypothesis ko galat sabit karega).
5. Medical/chemical/biological hypothesis ho to risks aur safety concerns
   likhna zaroori hai. "Ye ilaj hai" jaisa dawa mat karo.
6. {fields} ko cross-connect karke sochne ki koshish karo.
7. Prediction concrete honi chahiye: "agar ye hypothesis sach hai to KYA
   observe hoga" — measurable, aur aisi ki galat nikle to pata chal jaaye.
8. "Simple explanation" line har hypothesis mein ZAROORI hai: ekdum aam bhasha
   mein, jaise samne baithe bande ne ye concept pehle kabhi suna hi na ho.
   Jargon aaye to bracket mein uska matlab likho.
9. Har hypothesis mein ye CHHE cheezein zaroori hain, warna wo adhoori maani
   jayegi (aur report mein "adhoori" likha jayega): supporting evidence,
   contradicting evidence, assumptions, falsification test, required
   experiment/simulation, confidence.
10. Evidence patla ho to hypotheses ki GINTI ghata do, quality nahi. Bina base
   ki hypothesis likhne se behtar hai ek line likh dena: "sirf N ban sakti,
   kyunki ...".

{count} hypotheses do (isse kam nahi — agar {count} banane layak material nahi hai
to jitni bani utni do aur alag line mein saaf likho: "sirf N ban sakti, kyunki ...").
Format exactly aise:

{blocks}

Ab hypothesis do:"""

    @staticmethod
    def _gate_block(gate: Optional[EvidenceGate]) -> str:
        """
        Model ko evidence ki asli haalat batao. Kyun: patle evidence par 3
        hypotheses maangne se model fabricate karta hai — usi ko point 11 rokta
        hai. Ye block "jhoothi confidence" ka sabse sasta ilaj hai (₹0).
        """
        if gate is None:
            return ""
        line = (f"\nEVIDENCE KI HAALAT (system ne gini hai): "
                f"{gate.relevant_sources} relevant source, {gate.deep_sources} kam "
                f"se kam abstract tak padhe, {gate.full_text_sources} ka poora text, "
                f"{gate.contradictions} takraav.")
        if not gate.sufficient:
            line += ("\nYaani evidence patla hai: kam hypotheses do, par jo do "
                     "unka base saaf dikhao. Base na ho to saaf likho.")
        return line + "\n"

    @staticmethod
    def _format_block(index: int) -> str:
        """Ek hypothesis ka maanga hua format. Fields ke labels PARSER se match
        karte hain (`_FIELD_NAMES`) — inhe badalna hai to dono jagah badlo."""
        return f"""## Hypothesis {index}
- Statement: (ek line, testable)
- Simple explanation: (2-4 line, ekdum aam bhasha mein — "humara idea ye hai ki
  ..."; koi jargon nahi, aur ek roz-marra ka example do)
- Reasoning: (step-by-step chain: kis evidence se kaun sa step nikla)
- Supporting evidence: ([S#] ke saath, aur ek line mein ye bhi ki wo source kya
  kehta hai)
- Contradicting evidence: (kya iske khilaf jaata hai — "kuch nahi mila" likhne se
  pehle sach mein dhoondo)
- Novelty: (existing literature se kaise different hai; pehle se known ho sakta
  hai to saaf likho)
- Assumptions: (kya maan kar chal rahe hain — jo maan liya wo galat ho sakta hai)
- Prediction: (agar sach hai to kya measurable cheez dikhegi — aur kya dikhna ise
  galat sabit kar dega)
- Required experiment: (wo asli experiment ya simulation jo ise test karega:
  kya setup, kya control, kitna sample/kitne runs, kaunsa measurement)
- Falsification test: (ek line — KAUNSA result aane par ye hypothesis khatam
  maani jayegi; "kuch nahi" likhna allowed nahi)
- How to test: (concrete experiment/analysis + falsification condition)
- If true: (sahi nikli to practically kya badlega)
- If false: (galat nikli to kya seekhne ko milega)
- Risks: (safety, ethical, practical)
- Confidence: (LOW/MEDIUM/HIGH — reasoning-based hai, proof nahi)"""

    def prompt_appendix(self, count: int = 2) -> str:
        """
        Jab call budget kam ho (DEEP/MAXIMUM = 2-3 calls), tab hypothesis ke liye
        alag call nahi bachti. Ye chhota block critic prompt ke saath jod diya
        jaata hai, taaki ek hi response mein critique + hypothesis dono aa jaayein.

        2026-08-20: `count` add hua. Live run mein user ne 3 hypotheses maangi
        thi aur quota ki wajah se hypothesis pass hi nahi chala — ab ye appendix
        ANALYSIS pass ke saath bhi jud sakta hai, isliye count honour karna
        zaroori hai.
        """
        count = max(1, min(int(count or 2), 6))
        blocks = "\n\n".join(self._format_block(i) for i in range(1, count + 1))
        return f"""
---
ISI RESPONSE MEIN, aakhir mein, {count} nayi hypotheses bhi do (isse kam nahi).
Rules: hypothesis ko fact ki tarah mat likho; status "{STATUS}" hai; test design
concrete ho; prediction measurable ho; medical/chemical ho to risks likho;
[S#] se cite karo, warna [NO-SOURCE] likho. "Simple explanation" line skip mat
karo — wahi line user asal mein padhta hai.

Format exactly aise:

{blocks}
"""

    # ── structured prediction parser (Spec §10) ──────────────────────────────
    # YAHAN EK ASLI BUG THA (2026-08-19 ko pakda gaya): is class mein
    # `_parse_prediction` DO baar define tha. Python mein doosri definition pehli
    # ko chup-chaap kha jaati hai, aur doosri `(PredictionStructure, text)` ka
    # TUPLE lautati thi. `parse()` us tuple ko `h.prediction` mein rakh deta tha,
    # aur `Hypothesis.to_dict()` mein `self.prediction.is_complete` par poora
    # pipeline crash karta tha:
    #     AttributeError: 'tuple' object has no attribute 'is_complete'
    # Ye MAXIMUM mode ka asli raasta hai (hypothesis ban kar answer mein jaati
    # hai), isliye ye live crash tha — sirf test ka issue nahi.
    #
    # Dono purani strategies bachi hui hain, ek hi function mein:
    #   1. LABELLED lines ("Variables: x, y" / "Measurement: HOMA-IR") — Gemini
    #      se hum yahi format maangte hain, isliye pehle ye.
    #   2. Free-text heuristic (keywords + percentage regex) — jab model ne
    #      labels na likhe ho.
    # Jaan-boojh kar hataayi gayi sirf ek cheez: placeholder bharna
    # ("expected_outcome = 'change expected'", "measurement = 'to be
    # determined'"). Us se khaali prediction bhi `is_complete` ban jaati thi,
    # yaani report jhooth bolti ki structured prediction maujood hai.
    @staticmethod
    def _parse_prediction(text: str) -> Optional[PredictionStructure]:
        """
        Free-text prediction se structured prediction nikaalo (mile to).

        Kuch na mile to None — tab `Hypothesis.prediction_text` (asli text) hi
        aage jaata hai. Khaali structure banana mana hai.
        """
        if not text or len(text.strip()) < 20:
            return None

        pred = PredictionStructure()
        lower = text.lower()

        # ── 1. labelled lines ────────────────────────────────────────────────
        for line in [l.strip() for l in text.split("\n") if l.strip()]:
            low = line.lower()
            if any(k in low for k in ("variable", "parameter", "factor")):
                items = re.findall(r'["\']([^"\']+)["\']|:\s*([^,\n]+)', line)
                for a, b in items:
                    value = (a or b or "").strip()
                    if value and value not in pred.variables:
                        pred.variables.append(value)
            if any(k in low for k in ("expect", "outcome", "result")):
                match = re.search(
                    r"(\d+%|\d+\.\d+|\d+\s*(?:fold|times|unit|point|level))[^.]*",
                    line)
                if match and not pred.expected_outcome:
                    pred.expected_outcome = match.group(0).strip()
            if any(k in low for k in ("measur", "assess", "index", "scale", "method")):
                match = re.search(r"(?:using|via|through|with|by)\s+([^,.\n]+)",
                                  line, re.IGNORECASE)
                if match and not pred.measurement_method:
                    pred.measurement_method = match.group(1).strip()
                elif (":" in line and not pred.measurement_method
                      # sirf tab jab LABEL hi measurement ka ho. Warna
                      # "Variables: fasting glucose, HOMA-IR index" wali line
                      # ("index" ki wajah se) measurement ban jaati thi.
                      and any(k in low.split(":", 1)[0]
                              for k in ("measur", "assess", "method"))):
                    pred.measurement_method = line.split(":", 1)[1].strip()
            if any(k in low for k in ("falsif", "disprove", "reject", "null",
                                      "no change", "no effect")):
                if not pred.falsification_condition:
                    pred.falsification_condition = line.strip()

        # ── 2. free-text heuristic (labels na mile ho to) ────────────────────
        if not pred.variables:
            var_keywords = ["glucose", "insulin", "pressure", "weight",
                            "temperature", "level", "rate", "count", "score",
                            "index", "concentration", "gap", "error"]
            pred.variables = [kw for kw in var_keywords if kw in lower]
        if not pred.expected_outcome:
            for pattern in (
                r"(increase|decrease|reduction|rise|drop|change).*?(\d+[-–]?\d*%?)",
                r"(significant|no significant|positive|negative|elevated|reduced)",
            ):
                match = _re_module.search(pattern, lower)
                if match:
                    pred.expected_outcome = match.group(0)
                    break
        if not pred.measurement_method:
            match = re.search(
                r"measur\w*\s+(?:via|by|using|with)\s+([^;,\.]+)", lower)
            if match:
                pred.measurement_method = match.group(1).strip()
        if not pred.falsification_condition:
            match = re.search(
                r"(?:if no|if opposite|reject\w* if|falsif\w* if)\s+([^;,\.]+)",
                lower)
            if match:
                pred.falsification_condition = match.group(0).strip()

        # kuch asli mila tabhi lautao — warna text fallback behtar hai
        if pred.variables or pred.expected_outcome:
            return pred
        return None

    def parse(self, text: str, max_count: Optional[int] = None) -> List[Hypothesis]:
        """
        Model ke text se hypotheses nikaalo.

        `max_count` pehle hard-coded 3 tha. User "kam se kam 3" maange aur model
        4 de de, to chauthi chup-chaap phenki jaati thi — isliye cap request ke
        hisaab se BADH sakta hai.

        2026-08-21 (cross-domain benchmark): cap mein `max(3, ...)` ka floor tha,
        yaani neeche kabhi nahi ja sakta tha. Nateeja: 2 patle snippet-only
        sources par evidence gate `allowed=1` kehta tha, orchestrator 1 hi
        maangta tha, par model ke bheje 3 blocks poore parse ho jaate the aur
        report mein teen hypotheses chhap jaati thi — gate ka faisla kaagaz par
        reh jaata tha. Ab explicit cap ki izzat hoti hai (1 bhi), aur cap na
        bheja jaaye to purana default 3 hi rehta hai.
        """
        if not text or not text.strip():
            return []

        asked = int(max_count or 0)
        cap = max(1, asked) if asked > 0 else 3
        blocks = _H_SPLIT_RE.split(text)
        chunks = [b for b in blocks[1:] if b and b.strip()] if len(blocks) > 1 else [text]

        out: List[Hypothesis] = []
        for chunk in chunks[:cap]:
            h = Hypothesis()
            for key, value in _fields(chunk):
                if key == "statement":
                    h.statement = value
                elif key in ("simple", "simple explanation"):
                    h.simple = value
                elif key == "reasoning":
                    h.reasoning = value
                elif key == "supporting evidence":
                    h.supporting_evidence = value
                elif key in ("against", "contradicting evidence",
                             "counter evidence", "evidence against"):
                    h.contradicting_evidence = value
                elif key == "novelty":
                    h.novelty = value
                elif key in ("assumption", "assumptions"):
                    h.assumptions = value
                elif key == "prediction":
                    h.prediction_text = value
                    # Try structured parse
                    h.prediction = self._parse_prediction(value)
                elif key in ("required experiment", "required simulation",
                             "experimental plan", "experiment", "simulation"):
                    h.experiment = value
                elif key in ("falsification test", "how to falsify"):
                    h.falsification = value
                elif key in ("how to test", "test"):
                    h.how_to_test = value
                elif key == "if true":
                    h.if_true = value
                elif key == "if false":
                    h.if_false = value
                elif key == "risks":
                    h.risks = value
                elif key == "confidence":
                    h.confidence = value
            if not h.statement:
                # Field format na mila — pehli meaningful line ko statement maan lo
                lines = [l.strip("-*# ").strip() for l in chunk.splitlines() if l.strip()]
                h.statement = next((l for l in lines if len(l) > 25), "")
            if h.statement:
                out.append(h)
        return out

    # ── report ───────────────────────────────────────────────────────────────
    # Ye do warnings pehle se apni alag line mein chhapti hain, isliye
    # `missing_fields` wali consolidated line mein dobara nahi aani chahiye —
    # warna user ko ek hi kami do baar dikhti hai.
    _ALREADY_REPORTED = {"iske khilaf ka evidence (counter-evidence)"}

    def honesty_check(self, hypotheses: List[Hypothesis]) -> List[str]:
        """Spec Section 10/11 — jo hypothesis untestable/adhoori hai, usko flag karo."""
        warnings: List[str] = []
        for i, h in enumerate(hypotheses, 1):
            if not h.is_testable:
                warnings.append(
                    f"Hypothesis {i} ke saath concrete test design nahi hai — "
                    "isliye ye sirf speculation ke level pe hai.")
            if not h.has_prediction:
                warnings.append(
                    f"Hypothesis {i} ke saath testable prediction nahi hai — "
                    "'agar sach hai to kya dikhega' ke bina ise galat sabit "
                    "karna bhi possible nahi.")
            if not h.contradicting_evidence:
                warnings.append(
                    f"Hypothesis {i} ke against koi evidence list nahi hui — "
                    "self-falsification adhoora hai.")
            if len((h.simple or "").strip()) < 40:
                # Ye "galti" nahi hai, par user-facing quality ki kami hai:
                # sirf ek-line statement se padhne wale ko idea samajh nahi aata.
                warnings.append(
                    f"Hypothesis {i} ka simple-language explanation nahi aaya — "
                    "isliye ise aam bhasha mein samjhaya nahi ja saka, sirf "
                    "technical statement hai.")
            # point 11: spec ki CHHE zaroori cheezein. Jo bachi hui kami hai wo
            # ek hi line mein, naam le kar — "adhoori hai" bolna kaafi nahi,
            # user ko pata hona chahiye KYA missing hai.
            rest = [m for m in h.missing_fields if m not in self._ALREADY_REPORTED]
            if rest:
                warnings.append(
                    f"Hypothesis {i} adhoori hai — ye cheezein nahi aayi: "
                    f"{', '.join(rest)}.")
        return warnings

    # ── evidence gate wrapper ────────────────────────────────────────────────
    def gate(self, pack: Optional[EvidencePack], requested: int = 0,
             contradictions: Optional[List[Dict]] = None) -> EvidenceGate:
        """
        `evidence_gate()` ka convenience wrapper, taaki orchestrator ko module
        se alag function import na karna pade (aur test bhi engine ke through
        hi ho jaaye).
        """
        return evidence_gate(pack, requested=requested,
                             contradictions=contradictions)

    # ── point 10: LLM ke BINA bhi kaam ka output ──────────────────────────────
    # Purana behaviour: quota khatam ho jaaye to hypothesis section mein khaali
    # template chala jaata tha ("## Hypothesis 1 - Statement:" jaisa dhaancha
    # bina content). Wo do tarah se bura tha — dikhta jhootha tha, aur user ko
    # kuch kaam ka nahi milta tha.
    #
    # Ab, LLM na ho to system KHUD ek research plan banata hai — sirf usi cheez
    # se jo asal mein retrieve hui: open questions, kaun source kis level tak
    # padha gaya, kaun takraav khula reh gaya. Ye hypothesis NAHI hai aur khud
    # ko hypothesis bolta bhi nahi. Koi API, koi model, ₹0.
    def open_questions(self, question: str, pack: Optional[EvidencePack] = None,
                       contradictions: Optional[List[Dict]] = None,
                       plan: Optional[Dict] = None) -> List[str]:
        """Wo sawaal jo retrieve hui cheezon se HAL nahi hue (deterministic)."""
        out: List[str] = []
        conflicts = list(contradictions or [])
        for c in conflicts[:4]:
            summary = str(c.get("summary") or "").strip()
            if summary:
                out.append(f"{summary} — ye takraav evidence se tay nahi hua.")

        sources = list(getattr(pack, "sources", []) or []) if pack is not None else []
        usable = [s for s in sources
                  if float(getattr(s, "relevance_score", 0.0) or 0.0) >= _GATE_MIN_RELEVANCE
                  and not str(getattr(s, "rejected_reason", "") or "").strip()]
        shallow = [s for s in usable
                   if (s.reading_level() if hasattr(s, "reading_level") else "")
                   in ("metadata", "snippet")]
        if shallow:
            names = ", ".join((getattr(s, "title", "") or "")[:60]
                              for s in shallow[:3])
            out.append(
                f"{len(shallow)} relevant source ka poora text nahi mil paaya "
                f"(sirf title/snippet tak pahunch bani): {names} — inka full "
                "text padhe bina inke andar ka data claim nahi kiya ja sakta.")
        if not usable and sources:
            out.append(
                f"{len(sources)} result mile par ek bhi is sawaal se juda nahi "
                "nikla — matlab search terms ya connectors badalne padenge.")
        if not sources:
            out.append("Is sawaal par ek bhi source retrieve nahi hua — "
                       "pehla kaam retrieval theek karna hai, hypothesis nahi.")

        for sub in list((plan or {}).get("sub_questions") or [])[:4]:
            sub = str(sub).strip()
            if sub and sub.lower() != (question or "").strip().lower():
                out.append(f"Ye hissa khula hai: {sub}")

        # duplicate hatao, order rakho
        seen, unique = set(), []
        for item in out:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique[:8]

    def fallback_plan(self, question: str, pack: Optional[EvidencePack] = None,
                      contradictions: Optional[List[Dict]] = None,
                      gate: Optional[EvidenceGate] = None,
                      plan: Optional[Dict] = None) -> Dict:
        """
        LLM available na ho (quota/network/error) tab ka deterministic output.

        Lautata hai: `questions` (khule sawaal), `steps` (agla kaam), `note`
        (evidence ki asli ginti) aur `text` (report mein chhapne layak block).
        `is_hypothesis` hamesha False — isse synthesizer galti se ise hypothesis
        ki jagah nahi rakh sakta.
        """
        gate = gate if gate is not None else evidence_gate(
            pack, contradictions=contradictions)
        questions = self.open_questions(question, pack, contradictions, plan)

        steps: List[str] = []
        if gate.total_sources and not gate.relevant_sources:
            steps.append(
                "Search dobara chalao — is baar sawaal ke asli technical terms "
                "aur field-specific sources par, kyunki jo mile wo topic se "
                "match hi nahi kar rahe.")
        if gate.relevant_sources and gate.full_text_sources == 0:
            steps.append(
                "Kam se kam 2 relevant sources ka POORA text nikaalo "
                "(preprint/open-access version, ya PDF ka page-by-page read) — "
                "abstract se claim confirm nahi hota.")
        if gate.contradictions:
            steps.append(
                f"{gate.contradictions} takraav wale sources ka method "
                "side-by-side rakho: sample, condition aur measurement compare "
                "karo — aksar takraav method ka hota hai, nateeje ka nahi.")
        fields = ", ".join(list((plan or {}).get("relevant_fields") or [])[:3])
        if fields:
            steps.append(f"Jo fields is sawaal se jude hain ({fields}) — unme se "
                         "har ek ka ek strong source alag se dhoondo, taaki ek "
                         "hi angle par poora jawab na tike.")
        steps.append(
            "Jab evidence itna ho jaaye ki dono taraf ki baat saamne ho, tab "
            "hypothesis banao — usse pehle banayi hui hypothesis andaaza hoti hai.")

        note = (f"Ginti: {gate.relevant_sources} relevant source, "
                f"{gate.deep_sources} abstract-ya-usse-gehre, "
                f"{gate.full_text_sources} full text, "
                f"{gate.contradictions} takraav.")

        return {
            "is_hypothesis": False,
            "reason": gate.reason,
            "questions": questions,
            "steps": steps[:6],
            "note": note,
            "gate": gate.to_dict(),
            "text": self._render_fallback(questions, steps[:6], note, gate),
        }

    @staticmethod
    def _render_fallback(questions: List[str], steps: List[str], note: str,
                         gate: EvidenceGate) -> str:
        # Do bilkul alag haalat hain, aur inhe mila dena jhooth ban jaata hai:
        #   * evidence hi patla tha  -> wajah gate ki ginti hai
        #   * evidence theek tha par model/quota ne saath nahi diya -> tab gate
        #     ki "kaafi source hain" wali line ko WAJAH ki tarah likhna galat
        #     hoga (upar section pehle se asli wajah bata raha hota hai).
        if gate.sufficient:
            head = ("**Nayi hypothesis is run mein nahi ban paayi** — evidence "
                    "iske layak tha, kami reasoning pass mein rahi.")
        else:
            head = ("**Nayi hypothesis is baar nahi banayi gayi.** "
                    + (gate.reason or "Evidence itna nahi tha ki nayi hypothesis "
                                      "banayi ja sake."))
        lines = [
            head,
            "",
            "Iski jagah system ne khud ek research plan banaya hai — ye AI ki "
            "hypothesis NAHI hai, sirf wahi baat hai jo mile hue sources se "
            "seedha nikalti hai:",
        ]
        if questions:
            lines.append("")
            lines.append("**Ab tak jo sawaal khule hain:**")
            lines.extend(f"- {q}" for q in questions)
        if steps:
            lines.append("")
            lines.append("**Aage ka kaam (isi kram mein):**")
            lines.extend(f"{i}. {s}" for i, s in enumerate(steps, 1))
        lines.append("")
        lines.append(f"_{note}_")
        return "\n".join(lines)
