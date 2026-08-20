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
_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\**\s*(statement|reasoning|supporting evidence|against|"
    r"contradicting evidence|novelty|prediction|how to test|test|risks|confidence)"
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
    r"^\s*(?:[-*]\s*)?\**\s*(statement|reasoning|supporting evidence|against|"
    r"contradicting evidence|novelty|prediction|how to test|test|risks|confidence)"
    r"\s*\**\s*[:\-]\s*(.*)$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_MAX_FIELD_CHARS = 4000   # runaway continuation se bachne ke liye


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
            current = [match.group(1).lower().strip(), [match.group(2).strip()]]
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
    reasoning: str = ""
    supporting_evidence: str = ""
    contradicting_evidence: str = ""
    novelty: str = ""
    prediction: Optional[PredictionStructure] = None  # spec §10: structured field
    prediction_text: str = ""                          # fallback: agar structured parse na ho
    how_to_test: str = ""
    risks: str = ""
    confidence: str = ""
    status: str = STATUS          # kabhi override nahi hota

    @property
    def is_testable(self) -> bool:
        return len(self.how_to_test.strip()) >= 20

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
            "reasoning": self.reasoning,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "novelty": self.novelty,
            "prediction": pred,
            "has_prediction": self.has_prediction,
            "how_to_test": self.how_to_test,
            "is_testable": self.is_testable,
            "risks": self.risks,
            "confidence_reasoning_based": self.confidence,
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
    def prompt(self, question: str, analysis: str, pack: EvidencePack,
               plan: Dict, contradictions: Optional[List[Dict]] = None) -> str:
        gaps = "\n".join(f"  - {c.get('summary', '')}" for c in (contradictions or [])[:5])
        gap_block = f"\nEVIDENCE CONFLICTS jo mile:\n{gaps}\n" if gaps else ""
        fields = ", ".join(plan.get("relevant_fields", [])[:4]) or "relevant fields"

        return f"""Tum ek Hypothesis Generator ho. Tumhara kaam NAYI possibility
propose karna hai — literature ka summary dohrana nahi.

SAWAL: {question}

CURRENT EVIDENCE-BASED ANALYSIS:
{analysis[:4000]}
{gap_block}
SOURCES (sirf inhi ko cite karo, [S#] format mein):
{pack.to_prompt_block(max_chars_per_source=500)}

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

Maximum 2 hypotheses do. Format exactly aise:

## Hypothesis 1
- Statement: (ek line, testable)
- Reasoning: (step-by-step chain)
- Supporting evidence: ([S#] ke saath)
- Contradicting evidence: (kya iske khilaf jaata hai)
- Novelty: (ye existing literature se kaise different hai; agar pehle se known
  ho sakta hai to saaf likho)
- Prediction: (agar hypothesis sach hai to kya measurable cheez dikhegi — aur
  kya dikhna hypothesis ko galat sabit kar dega)
- How to test: (concrete experiment/analysis + falsification condition)
- Risks: (safety, ethical, practical)
- Confidence: (LOW/MEDIUM/HIGH — aur ye reasoning-based hai, proof nahi)

Ab hypothesis do:"""

    def prompt_appendix(self) -> str:
        """
        Jab call budget kam ho (DEEP/MAXIMUM = 2-3 calls), tab hypothesis ke liye
        alag call nahi bachti. Ye chhota block critic prompt ke saath jod diya
        jaata hai, taaki ek hi response mein critique + hypothesis dono aa jaayein.
        """
        return f"""
---
ISI RESPONSE MEIN, critique ke baad, maximum 2 nayi hypotheses bhi do.
Rules: hypothesis ko fact ki tarah mat likho; status "{STATUS}" hai; test design
concrete ho; prediction measurable ho; medical/chemical ho to risks likho;
[S#] se cite karo, warna [NO-SOURCE] लगाओ.

Format exactly aise:

## Hypothesis 1
- Statement:
- Reasoning:
- Supporting evidence:
- Contradicting evidence:
- Novelty:
- Prediction: (agar sach hai to kya observe hoga — measurable)
- How to test:
- Risks:
- Confidence: (LOW/MEDIUM/HIGH — reasoning-based, proof nahi)
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

    def parse(self, text: str) -> List[Hypothesis]:
        if not text or not text.strip():
            return []

        blocks = _H_SPLIT_RE.split(text)
        chunks = [b for b in blocks[1:] if b and b.strip()] if len(blocks) > 1 else [text]

        out: List[Hypothesis] = []
        for chunk in chunks[:3]:
            h = Hypothesis()
            for key, value in _fields(chunk):
                if key == "statement":
                    h.statement = value
                elif key == "reasoning":
                    h.reasoning = value
                elif key == "supporting evidence":
                    h.supporting_evidence = value
                elif key in ("against", "contradicting evidence"):
                    h.contradicting_evidence = value
                elif key == "novelty":
                    h.novelty = value
                elif key == "prediction":
                    h.prediction_text = value
                    # Try structured parse
                    h.prediction = self._parse_prediction(value)
                elif key in ("how to test", "test"):
                    h.how_to_test = value
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
    def honesty_check(self, hypotheses: List[Hypothesis]) -> List[str]:
        """Spec Section 10/11 — jo hypothesis untestable hai, usko flag karo."""
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
        return warnings
