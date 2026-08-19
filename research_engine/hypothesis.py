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

    # ── structured prediction parser ─────────────────────────────────────────
    @staticmethod
    def _parse_prediction(text: str) -> Optional[PredictionStructure]:
        """
        Try to extract structured prediction from free-text.

        Example input:
        "blood glucose will decrease by 20-30%, measured via HOMA-IR;
         if no change after 12 weeks, hypothesis is rejected"
        """
        if not text or len(text) < 20:
            return None

        pred = PredictionStructure()
        lower = text.lower()

        # Variables: common measurement keywords
        var_keywords = ["glucose", "insulin", "pressure", "weight", "temperature",
                        "level", "rate", "count", "score", "index", "concentration"]
        pred.variables = [kw for kw in var_keywords if kw in lower]

        # Expected outcome: look for percentages, ranges, qualitative change
        outcome_patterns = [
            r"(increase|decrease|reduction|rise|drop|change).*?(\d+[-–]?\d*%?)",
            r"(significant|no significant|positive|negative|elevated|reduced)",
        ]
        for pattern in outcome_patterns:
            match = _re_module.search(pattern, lower)
            if match:
                pred.expected_outcome = match.group(0)
                break

        # Measurement: look for "measured via/by/using"
        measure_match = re.search(r"measur\w*\s+(?:via|by|using|with)\s+([^;,\.]+)",
                                  lower)
        if measure_match:
            pred.measurement_method = measure_match.group(1).strip()

        # Falsification: "if no/if opposite/rejected if"
        false_match = re.search(r"(?:if no|if opposite|reject\w* if|falsif\w* if)\s+([^;,\.]+)",
                                lower)
        if false_match:
            pred.falsification_condition = false_match.group(0).strip()

        # Only return if somewhat complete
        if pred.variables or pred.expected_outcome:
            return pred
        return None

    # ── parse ────────────────────────────────────────────────────────────────
    def _parse_prediction(self, text: str) -> tuple[Optional[PredictionStructure], str]:
        """
        Parse structured prediction from text.
        Returns: (PredictionStructure | None, fallback_text)

        Looks for patterns like:
        - Variables: x, y
        - Expected outcome: 30% reduction
        - Measurement: HOMA-IR index
        - Falsification: no change after 12 weeks
        """
        lines = [l.strip() for l in (text or "").split("\n") if l.strip()]

        variables = []
        outcome = ""
        measurement = ""
        falsification = ""

        for line in lines:
            lower = line.lower()
            # Extract variables
            if any(kw in lower for kw in ["variable", "measure", "parameter", "factor"]):
                # Extract comma-separated items or quoted items
                items = re.findall(r'["\']([^"\']+)["\']|:\s*([^,\n]+)', line)
                variables.extend([i[0] or i[1] for i in items if i[0] or i[1]])

            # Expected outcome
            if any(kw in lower for kw in ["expect", "outcome", "result", "change", "effect"]):
                # Extract percentage or numeric patterns
                match = re.search(r'(\d+%|\d+\.\d+|\d+\s*(?:fold|times|unit|point|level))[^.]*', line)
                if match:
                    outcome = match.group(0).strip()

            # Measurement method
            if any(kw in lower for kw in ["measur", "assess", "index", "scale", "test", "method"]):
                # Extract the measurement tool/method
                match = re.search(r'(?:using|via|through|with|by)\s+([^,.\n]+)', line, re.IGNORECASE)
                if match:
                    measurement = match.group(1).strip()
                elif ":" in line:
                    measurement = line.split(":", 1)[1].strip()

            # Falsification condition
            if any(kw in lower for kw in ["falsif", "disprove", "reject", "null", "no change", "no effect"]):
                falsification = line.strip()

        # Clean up extracted data
        variables = [v.strip() for v in variables if v.strip()][:5]  # max 5

        # If we got structured data, create PredictionStructure
        if variables or outcome or measurement or falsification:
            return (
                PredictionStructure(
                    variables=variables,
                    expected_outcome=outcome or "change expected",
                    measurement_method=measurement or "to be determined",
                    falsification_condition=falsification or "no observable change"
                ),
                text  # also keep original text
            )

        # No structure found, return text only
        return None, text

    def parse(self, text: str) -> List[Hypothesis]:
        if not text or not text.strip():
            return []

        blocks = _H_SPLIT_RE.split(text)
        chunks = [b for b in blocks[1:] if b and b.strip()] if len(blocks) > 1 else [text]

        out: List[Hypothesis] = []
        for chunk in chunks[:3]:
            h = Hypothesis()
            for raw_key, value in _FIELD_RE.findall(chunk):
                key = raw_key.lower().strip()
                value = value.strip().strip("*").strip()
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
