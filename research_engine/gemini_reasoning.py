"""
GeminiReasoning — Spec Section 9 (Multi-Angle Reasoning)

Gemini = REASONING ENGINE. Knowledge base nahi.
Isliye har prompt mein evidence pack jaata hai aur model ko bola jaata hai ki
sirf diye gaye sources se cite kare.

Do zaroori cheezein ye module handle karta hai:
    1. CALL BUDGET — free tier ~20 calls/din. Budget khatam hone pe engine
       aage ki pass silently skip karta hai, crash nahi karta.
    2. HONESTY — Spec Section 9: "ek hi Gemini model ke alag passes ko
       'independent human experts' mat batana." Prompt mein yahi likha hai.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from .citation import CITATION_INSTRUCTION
from .models import EvidencePack

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# Ye disclaimer har analysis prompt mein jaata hai
_ROLE_HONESTY = (
    "NOTE: tum ek hi AI model ho jo alag-alag reasoning roles nibha raha hai. "
    "In roles ko 'independent human experts' ki tarah pesh mat karo. "
    "Evidence ki asli verification sources se hoti hai, roles se nahi."
)


class QuotaExhausted(RuntimeError):
    pass


class GeminiReasoning:
    def __init__(self, budget: int = 2, model_name: str = MODEL_NAME):
        self.budget = max(1, budget)
        self.model_name = model_name
        self.calls_used = 0
        self.errors: List[str] = []
        self._model = None

    # ── model access (lazy) ──────────────────────────────────────────────────
    def model(self):
        if self._model is None:
            import google.generativeai as genai  # lazy — import sasta rahe
            from dotenv import load_dotenv

            from .gemini_model import resolve

            load_dotenv()
            genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
            # Hard-coded naam ("gemini-flash-latest") kai keys par maujood nahi
            # hota aur Google InvalidArgument/NotFound bhej deta hai. Isliye
            # naam Google ki asli list se chunte hain. GEMINI_MODEL env set ho
            # aur valid ho to wahi use hota hai.
            if self.model_name == MODEL_NAME:
                self.model_name = resolve(genai)
            self._model = genai.GenerativeModel(self.model_name)
        return self._model

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.calls_used)

    def generate(self, prompt: str, label: str = "") -> str:
        """Ek Gemini call. Budget khatam ho to QuotaExhausted raise karta hai."""
        if self.remaining <= 0:
            raise QuotaExhausted(f"call budget ({self.budget}) khatam — '{label}' skip hua")
        self.calls_used += 1
        try:
            response = self.model().generate_content(prompt)
            return (getattr(response, "text", "") or "").strip()
        except Exception as exc:
            message = f"{label or 'gemini'} failed: {type(exc).__name__}: {exc}"
            self.errors.append(message)
            return ""

    # ── PASS 1/2/3 + evidence audit (Spec Section 9) ─────────────────────────
    def prompt_analysis(self, question: str, pack: EvidencePack, plan: Dict) -> str:
        fields = ", ".join(plan.get("relevant_fields", [])) or "General"
        subs = "\n".join(f"  - {s}" for s in plan.get("sub_questions", [])[:5])
        return f"""Tum ek Research Analyst ho. {_ROLE_HONESTY}

SAWAL: {question}

RELEVANT FIELDS: {fields}

SUB-QUESTIONS jinka jawab chahiye:
{subs}

RETRIEVED SOURCES (sirf inhi ka istemal karo):
{pack.to_prompt_block()}

{CITATION_INSTRUCTION}

Ab ye passes karo:

PASS 1 — FACTUAL: sirf wo facts jo in sources se supported hain. Har fact ke saath
  label [ESTABLISHED] ya [STRONG EVIDENCE] aur source ID.
PASS 2 — CONTEXT: background, mechanism, relationships. Jahan source nahi hai
  wahan [INFERENCE] + [NO-SOURCE] likho.
PASS 3 — CROSS-DISCIPLINARY: {fields} ko aapas mein connect karo. Har connection
  evidence ya clearly-labelled inference par based ho.
PASS 4 — EVIDENCE AUDIT: har major claim ko label karo:
  [ESTABLISHED] [STRONG EVIDENCE] [MIXED EVIDENCE] [INFERENCE] [HYPOTHESIS]
  [SPECULATION] [UNKNOWN]

Output format:
## Factual Findings
## Context & Mechanisms
## Cross-Disciplinary Connections
## Evidence Audit
## Source Relevance Check
   (Agar diye gaye sources sawal ke liye relevant NAHI hain, to yahan saaf likho.)

Ab analysis do:"""

    # ── fallback: koi source hi nahi mila ────────────────────────────────────
    def prompt_no_sources(self, question: str, plan: Dict) -> str:
        return f"""Tum ek research assistant ho. Is sawal ke liye system ko koi
relevant source NAHI mila (na document, na web, na academic database).

SAWAL: {question}

Rules:
1. Shuru mein hi saaf likho: "Ye jawab retrieved sources se nahi, model ki
   general knowledge se hai."
2. Har claim ko [INFERENCE] ya [UNKNOWN] label karo — [ESTABLISHED] mat likho,
   kyunki verify karne ke liye koi source nahi hai.
3. Koi URL ya citation invent MAT karo.
4. Aakhir mein batao ki is sawal ka jawab verify karne ke liye kaun se
   sources/data chahiye honge.

Jawab do:"""
