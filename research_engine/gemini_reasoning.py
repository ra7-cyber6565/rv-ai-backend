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
import time
from typing import Dict, List, Optional

from .citation import CITATION_INSTRUCTION
from .claim_labels import LABEL_RULE_PROMPT
from .explain_style import style_block
from .model_errors import AUTH, DAILY_QUOTA, FailureLedger
from .model_errors import classify as classify_error
from .models import EvidencePack

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# Ye disclaimer har analysis prompt mein jaata hai
_ROLE_HONESTY = (
    "NOTE: tum ek hi AI model ho jo alag-alag reasoning roles nibha raha hai. "
    "In roles ko 'independent human experts' ki tarah pesh mat karo. "
    "Evidence ki asli verification sources se hoti hai, roles se nahi."
)

# ── retry policy (2026-08-20 ki live failure ke baad) ────────────────────────
# Us run mein ek 429 ne TEEN passes ek saath uda diye: critic, hypothesis aur
# synthesis. Wajah ye thi ki `generate()` har exception ko nigal kar "" lauta
# deta tha — na retry, na doosra model. Jabki free tier ka quota PER MODEL hota
# hai, aur `/api/v1/chat/diag` par 25 usable model dikh rahe the. Yaani jawab
# maujood tha, system ne maanga hi nahi.
#
# DUSRI live failure (§7): usi 429 ko "random network error" maan kar 3 baar
# retry kiya gaya, jabki message mein saaf likha tha ki DIN ka quota khatam hai
# (quota_id: ...PerDay...). Ab error ka matlab `model_errors.py` batata hai:
#   * daily quota      -> usi model par dobara NAHI, model is run ke liye band
#   * per-minute limit -> thoda ruk kar dobara
#   * 404/naam galat   -> model permanently chhod do (process-wide memory)
#   * auth failure     -> poori reasoning band, aur koshish bekaar hai
#   * 5xx / network    -> retry
_BACKOFF_SECONDS = (1.5, 4.0)      # ek pass ke andar max ~6s rukte hain
_MAX_SLEEP_SECONDS = 6.0           # server 21s maange to bhi itna hi rukte hain
_MAX_MODELS = 4                    # pehla + teen fallback (quota per model hota hai)


def _classify(exc: Exception) -> str:
    """
    Legacy label — purane callers/tests ke liye. Asli faisla
    `model_errors.classify()` karta hai; ye sirf uska chhota naam hai.
    """
    return classify_error(exc).kind


class QuotaExhausted(RuntimeError):
    pass


class GeminiReasoning:
    def __init__(self, budget: int = 2, model_name: str = MODEL_NAME):
        self.budget = max(1, budget)
        self.model_name = model_name
        self.calls_used = 0
        self.errors: List[str] = []
        self._model = None
        # retry ka hisaab — ye audit section mein imaandaari se dikhta hai
        self.attempts = 0                    # asli HTTP attempts (retry ke saath)
        self.successes = 0                   # kitne pass sach mein jawab laaye
        self.notes: List[str] = []           # "critique: model X par safal (retry 2)"
        self.models_tried: List[str] = []
        self.switched_models = 0
        # §7 — kaun kis wajah se gira, aur kaun is run mein band hai
        self.ledger = FailureLedger()
        self.blocked: Dict[str, str] = {}    # model -> kind (is run ke liye)
        self.stopped = False                 # auth failure: aage koshish bekaar

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

    def _model_order(self) -> List[str]:
        """Pehla = abhi ka model, uske baad gemini_model ke fallbacks."""
        order = [self.model_name] if self.model_name else []
        try:
            import google.generativeai as genai

            from .gemini_model import candidates

            for name in candidates(genai):
                if name not in order:
                    order.append(name)
        except Exception:                       # noqa: BLE001 — offline/no key
            pass
        return order[:_MAX_MODELS] or [self.model_name or MODEL_NAME]

    def _usable_models(self) -> List[str]:
        """
        Order mein se wo model hataao jo is run mein pehle hi gir chuke hain.

        Yahi §7 ka asli fayda hai: pehle pass mein jis model ka DIN ka quota
        khatam mila, agle pass mein us par dobara jaana sirf waqt aur attempts
        barbaad karta tha (aur user ko lagta tha "system atak gaya").
        """
        out: List[str] = []
        for name in self._model_order():
            if name in self.blocked:
                continue
            try:
                from .gemini_model import is_dead
                if is_dead(name):
                    continue
            except Exception:                   # noqa: BLE001
                pass
            out.append(name)
        return out

    def _build(self, name: str):
        """Naye naam ka model object banao (aur usse hi aage kaam karo)."""
        import google.generativeai as genai

        model = genai.GenerativeModel(name)
        self.model_name = name
        self._model = model
        return model

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.calls_used)

    # ── §9/§25: user ko batane layak wajah (raw error NAHI) ──────────────────
    def failure_kind(self) -> str:
        return self.ledger.worst_kind()

    def failure_reason(self) -> str:
        """Ek Hinglish line — kyun reasoning poori nahi hui."""
        kind = self.failure_kind()
        if not kind:
            return ""
        from .model_errors import HUMAN
        return HUMAN.get(kind, "")

    def technical_details(self, limit: int = 5) -> List[str]:
        """Report ke sabse NEECHE dikhane ke liye — upar kabhi nahi (§9)."""
        return [f"{e['model']} / {e['label']}: {e['kind']} — {e['detail']}"
                for e in self.ledger.events[:limit]]

    def generate(self, prompt: str, label: str = "") -> str:
        """
        Ek logical Gemini call — par andar retry + model fallback ke saath.

        Budget LOGICAL calls ka hai (pass ka), retry us budget ko nahi khaata:
        warna ek 429 phir se poora pass kha jaata. Budget khatam ho to
        QuotaExhausted raise hota hai (ye behaviour purana hi hai, orchestrator
        isi par depend karta hai).

        §7 ke baad: kitni koshish honi hai, ye error ka MATLAB decide karta hai
        (model_errors.classify), andha 3-retry loop nahi.
        """
        if self.remaining <= 0:
            raise QuotaExhausted(f"call budget ({self.budget}) khatam — '{label}' skip hua")
        self.calls_used += 1
        tag = label or "gemini"

        if self.stopped:
            # auth fail ho chuka hai — dobara maangna sirf waqt kharab karna hai
            self.errors.append(f"{tag} skip: API key/permission failure ke baad "
                               f"aur koshish nahi ki gayi")
            return ""

        first_model = self.model_name
        try:
            self.model()                        # lazy resolve, taaki naam asli ho
        except Exception as exc:                # noqa: BLE001
            self.errors.append(f"{tag} failed: model setup: "
                               f"{type(exc).__name__}: {exc}")
            return ""

        order = self._usable_models()
        if not order:
            self.errors.append(f"{tag} skip: is run mein koi model bacha hi nahi "
                               f"(band: {', '.join(sorted(self.blocked)) or '-'})")
            return ""

        for model_index, name in enumerate(order):
            if name not in self.models_tried:
                self.models_tried.append(name)
            if name != self.model_name:
                try:
                    self._build(name)
                except Exception as exc:        # noqa: BLE001
                    self.errors.append(f"{tag}: model '{name}' banaya nahi ja saka: "
                                       f"{type(exc).__name__}: {exc}")
                    continue
            for attempt in range(len(_BACKOFF_SECONDS) + 1):
                self.attempts += 1
                try:
                    response = self._model.generate_content(prompt)
                    text = (getattr(response, "text", "") or "").strip()
                    if not text:
                        # khaali jawab bhi failure hai — chup-chaap "" lautana
                        # hi purana bug tha
                        raise RuntimeError("model ne khaali response diya")
                    self.successes += 1
                    if name != first_model:
                        self.switched_models += 1
                        self.notes.append(
                            f"{tag}: '{first_model}' par nahi chala, "
                            f"'{name}' par chala")
                    elif attempt:
                        self.notes.append(f"{tag}: {attempt + 1} koshish ke baad chala")
                    return text
                except Exception as exc:        # noqa: BLE001
                    v = classify_error(exc)
                    self.ledger.add(name, tag, v, attempt=attempt + 1)
                    self.errors.append(
                        f"{tag} failed (model={name}, try={attempt + 1}, "
                        f"{v.kind}): {type(exc).__name__}: {exc}")

                    if v.stop_all:              # auth — sab band
                        self.stopped = True
                        self.notes.append(f"{tag}: {v.human} — aage koshish rok di")
                        return ""
                    if v.permanent:
                        try:
                            from .gemini_model import mark_dead
                            mark_dead(name, v.kind)
                        except Exception:       # noqa: BLE001
                            pass
                    if v.disable_model:
                        self.blocked[name] = v.kind
                        self.notes.append(
                            f"{tag}: '{name}' {v.human} — is run mein isse "
                            f"dobara nahi poochha jaayega")
                        break                   # seedha agla model
                    if v.retry_same_model and attempt < len(_BACKOFF_SECONDS):
                        wait = v.retry_after or _BACKOFF_SECONDS[attempt]
                        if v.retry_after and v.retry_after > _MAX_SLEEP_SECONDS:
                            # server 21s maang raha hai — itna rukna user ke liye
                            # atak jaana hai; agle model par jaana behtar hai
                            self.notes.append(
                                f"{tag}: '{name}' ne {v.retry_after:.0f}s wait "
                                f"maanga — itna rukne se behtar agla model")
                            break
                        time.sleep(min(wait, _MAX_SLEEP_SECONDS))
                        continue
                    break                       # is model par bas — agla model
        return ""

    def usage_note(self) -> str:
        """Audit ke liye ek line — jitna hua utna, bina saja-sanwaar ke."""
        bits = [f"{self.calls_used}/{self.budget} reasoning pass"]
        if self.successes:
            bits.append(f"{self.successes} pass safal")
        if self.attempts > self.calls_used:
            bits.append(f"{self.attempts} actual API attempts (retry lage)")
        if self.switched_models:
            bits.append(f"{self.switched_models} baar doosre model par shift karna pada")
        if self.errors:
            bits.append(f"{len(self.errors)} error aaye")
        if self.blocked:
            bits.append("band model: " + ", ".join(
                f"{n} ({k})" for n, k in sorted(self.blocked.items())))
        return ", ".join(bits)

    def api_accounting(self) -> Dict:
        """
        §14 — honest API accounting. Logical pass, asli HTTP attempts, safal,
        fail, retry, aur kaun kis wajah se gira.
        """
        return {
            "logical_reasoning_calls": self.calls_used,
            "budget": self.budget,
            "actual_http_attempts": self.attempts,
            "successful_calls": self.successes,
            "failed_attempts": max(0, self.attempts - self.successes),
            "retries": max(0, self.attempts - self.calls_used),
            "models_tried": list(self.models_tried),
            "model_switches": self.switched_models,
            "blocked_models": dict(self.blocked),
            "failure_kinds": self.ledger.kinds(),
            "failure_summary": self.ledger.summary(),
            "stopped_early": self.stopped,
        }

    # ── PASS 1/2/3 + evidence audit (Spec Section 9) ─────────────────────────
    def prompt_analysis(self, question: str, pack: EvidencePack, plan: Dict) -> str:
        fields = ", ".join(plan.get("relevant_fields", [])) or "General"
        subs = "\n".join(f"  - {s}" for s in plan.get("sub_questions", [])[:5])
        # Bhasha + samjhane ka tarika yahan bhi zaroori hai, sirf synthesis mein
        # nahi: jab quota synthesis tak nahi pahunchti (2 mein se 1 call, ya
        # 429), tab YAHI analysis seedha final answer ban jaata hai
        # (orchestrator: `passes["final"] or passes["analysis"]`). Pehle us
        # halat mein user ko bilkul kaccha, jargon-bhara text milta tha.
        style = style_block(question, ["Factual Findings"])
        # Explicit requests (math model, chain, hypothesis count) plan ke andar
        # aate hain — planner ne `requests` daala hoga. Na ho to ye khaali string
        # ban jaata hai, isliye purane callers bhi chalte rehte hain.
        from .requested import prompt_block

        extras = prompt_block(plan.get("requests") if isinstance(plan, dict) else None)
        return f"""Tum ek Research Analyst ho. {_ROLE_HONESTY}

SAWAL: {question}

RELEVANT FIELDS: {fields}

SUB-QUESTIONS jinka jawab chahiye:
{subs}

RETRIEVED SOURCES (sirf inhi ka istemal karo):
{pack.to_prompt_block()}

{CITATION_INSTRUCTION}

{LABEL_RULE_PROMPT}

{style}

Ab ye passes karo:

PASS 1 — FACTUAL: sirf wo facts jo in sources se supported hain. Har fact ke saath
  source ID, aur label upar diye gaye LABEL RULE ke hisaab se:
  jis source ka "Read: full_text" hai usse verify hui baat par [ESTABLISHED],
  aur sirf abstract/snippet/metadata wali baat par [SOURCE-REPORTED].
PASS 2 — CONTEXT: background, mechanism, relationships. Jahan source nahi hai
  wahan [INFERENCE] + [NO-SOURCE] likho.
PASS 3 — CROSS-DISCIPLINARY: {fields} ko aapas mein connect karo. Har connection
  evidence ya clearly-labelled inference par based ho.
PASS 4 — EVIDENCE AUDIT: har major claim ko label karo:
  [ESTABLISHED] [SOURCE-REPORTED] [MIXED EVIDENCE] [INFERENCE] [HYPOTHESIS]
  [SPECULATION] [UNKNOWN]
{extras}

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

{style_block(question)}

Rules:
1. Shuru mein hi saaf likho: "Ye jawab retrieved sources se nahi, model ki
   general knowledge se hai."
2. Har claim ko [INFERENCE] ya [UNKNOWN] label karo — [ESTABLISHED] mat likho,
   kyunki verify karne ke liye koi source nahi hai.
3. Koi URL ya citation invent MAT karo.
4. Aakhir mein batao ki is sawal ka jawab verify karne ke liye kaun se
   sources/data chahiye honge.

Jawab do:"""
