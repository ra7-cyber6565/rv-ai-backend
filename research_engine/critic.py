"""
Critic — Spec Section 9 (PASS 5 Critical + PASS 6 Red Team) aur Section 12 se
"Counter-Evidence" wala section.

Do kaam:
    1. Prompt banao jo analysis ko attack kare (self-falsification).
    2. Critic ke output ko parse karke structured weaknesses nikaalo, taaki
       final answer mein "Counter-Evidence & Weaknesses" section bhara ja sake.

Ye module Gemini ko *khud* call nahi karta — GeminiReasoning karta hai, taaki
call budget ek hi jagah se control ho.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from .explain_style import style_block
from .models import EvidencePack

_SECTION_RE = re.compile(r"^\s*#{1,4}\s*(.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.{8,})$", re.MULTILINE)


@dataclass
class CritiqueReport:
    weaknesses: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)
    alternative_explanations: List[str] = field(default_factory=list)
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.weaknesses or self.missing_evidence or self.alternative_explanations)

    def to_dict(self) -> Dict:
        return {
            "weaknesses": self.weaknesses,
            "missing_evidence": self.missing_evidence,
            "alternative_explanations": self.alternative_explanations,
        }


class Critic:
    # ── PASS 5 + 6 prompt ────────────────────────────────────────────────────
    def prompt(self, question: str, analysis: str, pack: EvidencePack,
               red_team: bool = True) -> str:
        red_team_block = ""
        if red_team:
            red_team_block = """
## Red Team Attack
Ab role badal kar is analysis ke sabse kade critic ban jao:
- Sabse kamzor claim kaun sa hai aur kyun?
- Kaun sa alternative explanation same evidence ko explain kar sakta hai?
- Kaun sa single naya data point poore conclusion ko girado dega?
"""
        return f"""Tum ab CRITIC role mein ho. Tumhara kaam neeche diye gaye analysis ko
tod-tod kar dekhna hai — tareef karna NAHI.

SAWAL: {question}

ANALYSIS jise criticise karna hai:
{analysis[:6000]}

AVAILABLE SOURCES (inke bahar ka koi source cite mat karo):
{pack.to_prompt_block(max_chars_per_source=600)}

{style_block(question, ["Weaknesses"])}

Rules:
1. Har weakness specific ho — "aur research chahiye" jaisi generic baat nahi.
2. Jo claim sources se supported NAHI hai, usko naam lekar batao.
3. Correlation ko causation bataya gaya ho to pakdo.
4. Sample size, methodology, ya recency ki problem ho to likho.
5. Agar ek hi information ke multiple copies ko alag-alag evidence maana gaya
   hai, to ye saaf batao.

Output exactly in ye sections:

## Weaknesses
- (bullet list)

## Missing Evidence
- (kaun sa data/study hoti to jawab pakka hota)

## Alternative Explanations
- (dusri wajah jo same evidence explain kar sakti hai)
{red_team_block}
Ab critique do:"""

    # ── output parse ─────────────────────────────────────────────────────────
    def parse(self, text: str) -> CritiqueReport:
        report = CritiqueReport(raw=text or "")
        if not text:
            return report

        buckets = {
            "weaknesses": report.weaknesses,
            "missing evidence": report.missing_evidence,
            "alternative explanations": report.alternative_explanations,
            "red team attack": report.weaknesses,
        }

        current: List[str] | None = None
        for line in text.splitlines():
            heading = _SECTION_RE.match(line)
            if heading:
                key = heading.group(1).strip().lower()
                current = None
                for name, bucket in buckets.items():
                    if name in key:
                        current = bucket
                        break
                continue
            if current is None:
                continue
            bullet = _BULLET_RE.match(line)
            if bullet:
                item = bullet.group(1).strip()
                if item and item not in current:
                    current.append(item)

        # Headings hi na aayi ho to poore text ke bullets ko weakness maan lo
        if report.is_empty:
            report.weaknesses = [m.strip() for m in _BULLET_RE.findall(text)][:8]
        return report
