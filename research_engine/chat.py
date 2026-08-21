"""
Fast conversational chat — QUICK mode without a single-provider quota trap.

The old implementation called Gemini directly. That meant QUICK chat could stop
working as soon as Gemini quota/auth/model availability failed, even though the
research engine already had safer fallback logic. QUICK now uses the same ₹0
reasoning chain as deep research:

    confirmed Gemini -> confirmed Groq free -> OpenRouter free-only ->
    local Ollama -> route-level research/evidence fallback.

Trivial greetings/thanks/identity are answered deterministically first. Besides
being instant, this intentionally spends zero hosted-model quota on messages that
do not need a model.

No raw provider exception/API key is returned to the client.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from .local_language import normalize
from .reasoning_router_integrated import ResilientReasoning
from utils.reasoning_status import reasoning_status

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
_MAX_MESSAGE_CHARS = 20_000
_MAX_HISTORY_CHARS = 18_000

_SYSTEM = """Tum "RV" ho — ek dost jaisa, samajhdaar AI assistant.

# Pehchaan
- Agar koi poochhe "tum kaun ho / who are you / tumhara naam", to seedha bolo
  ki tum RV ho. Kisi company ya model ka naam mat lo.

# Bhasha
- Jis bhasha/script mein user likhe, ussi mein jawab do: Hindi -> Hindi,
  English -> English, Hinglish -> Hinglish.
- User ki spelling par comment/correction mat karo; matlab samajh kar jawab do.

# Mood
- Udaas/pareshaan -> narmi aur useful madad.
- Khush/excited -> matching energy.
- Gussa/frustrated -> shaant, seedha, bina bahaanon ke.
- Casual -> natural dostana tone.

# Jawab
- Pehli line se kaam ki baat; zaroorat na ho to lecture nahi.
- Jargon ka aam matlab saath samjhao.
- Jhooth, fake certainty aur invented source mat do.
- Agar sawal current/deep evidence maangta ho aur is chat pass ke paas sources
  nahi hain, to general knowledge ko verified research mat bolo.
"""


def _history_block(history: Optional[List[Dict]]) -> str:
    if not history:
        return ""
    lines: List[str] = []
    used = 0
    # Recent turns matter most. Build from newest backwards, then restore order.
    selected: List[str] = []
    for turn in reversed(history[-12:]):
        if not isinstance(turn, dict):
            continue
        role = (turn.get("role") or "").lower()
        text = str(turn.get("content") or turn.get("text") or "").strip()
        if not text:
            continue
        who = "User" if role in ("user", "human") else "RV"
        row = f"{who}: {text}"
        if used + len(row) > _MAX_HISTORY_CHARS:
            break
        selected.append(row)
        used += len(row)
    lines.extend(reversed(selected))
    return "\n".join(lines)


def _build_prompt(message: str, history: Optional[List[Dict]]) -> str:
    convo = _history_block(history)
    convo_block = f"\n# Ab tak ki baat-cheet\n{convo}\n" if convo else ""
    opened = normalize(message)
    hint = ""
    if opened.strip().lower() != message.strip().lower():
        hint = ("\n# Andar ka shorthand hint — sirf samajhne ke liye\n"
                f"{opened[:4000]}\n")
    return (f"{_SYSTEM}\n{convo_block}\n# User ka naya message\n{message}\n{hint}"
            "\n# RV ka jawab")


def _style(message: str) -> str:
    text = message or ""
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    low = text.lower()
    roman_hindi = ("bhai", "kya", "kaise", "kyu", "kyun", "nhi", "nahi",
                   "bta", "bata", "mera", "mujhe", "haan", "ha ", "theek")
    return "hinglish" if any(token in low for token in roman_hindi) else "en"


def _smalltalk(message: str) -> str:
    """Zero-model answers for trivial conversation; empty means not small-talk."""
    low = " ".join((message or "").lower().strip().split())
    plain = re.sub(r"[^\w\u0900-\u097F ]+", "", low).strip()
    style = _style(message)

    identity = ("who are you", "what are you", "tum kaun", "aap kaun", "naam kya",
                "तुम कौन", "आप कौन", "नाम क्या")
    if any(x in low for x in identity):
        if style == "hi":
            return "मैं RV हूँ 🙂 बताओ, किस चीज़ में मदद चाहिए?"
        if style == "en":
            return "I'm RV 🙂 What can I help you with?"
        return "Main RV hoon 🙂 Batao, kis cheez mein help chahiye?"

    greetings = {
        "hi", "hello", "hey", "hii", "hiii", "hello bhai", "hi bhai", "hey bhai",
        "namaste", "नमस्ते", "हेलो", "हाय",
    }
    if plain in greetings:
        if style == "hi":
            return "नमस्ते 🙂 बताओ, क्या करना है?"
        if style == "en":
            return "Hey 🙂 What do you want to work on?"
        return "Haan bhai 🙂 batao, kya karna hai?"

    thanks = ("thanks", "thank you", "thx", "shukriya", "dhanyavad", "धन्यवाद", "शुक्रिया")
    if any(plain == x or plain.startswith(x + " ") for x in thanks):
        if style == "hi":
            return "बिलकुल 🙂"
        if style == "en":
            return "Anytime 🙂"
        return "Bilkul bhai 🙂"

    wellbeing = ("how are you", "kaise ho", "kese ho", "कैसे हो")
    if any(x in low for x in wellbeing) and len(low) < 80:
        if style == "hi":
            return "मैं बढ़िया हूँ 🙂 बताओ, आज क्या करना है?"
        if style == "en":
            return "Doing well 🙂 What are we working on today?"
        return "Badhiya bhai 🙂 batao, aaj kya kaam karna hai?"
    return ""


def _safe_accounting(brain: ResilientReasoning) -> Dict:
    try:
        acc = dict(brain.api_accounting())
    except Exception:
        return {}
    # Keep diagnostics useful but compact. No keys/tokens are present in this
    # schema; technical provider exception text is deliberately not returned.
    allowed = (
        "logical_reasoning_calls", "passes_requested", "passes_with_output",
        "actual_http_attempts", "same_model_retries", "model_switches",
        "provider_fallbacks", "blocked_models", "blocked_providers",
    )
    return {key: acc[key] for key in allowed if key in acc}


def quick_chat(message: str, history: Optional[List[Dict]] = None) -> Dict:
    """Fast chat through the resilient ₹0 model chain.

    `fallback_required=True` means no model layer could produce text. The API
    route then hands the same user message to QUICK research, which can still
    retrieve evidence and use the deterministic evidence reasoner. This is a
    graceful capability fallback, not an exception path.
    """
    message = (message or "").strip()
    if not message:
        return {"answer": "Kuch likho to sahi 🙂", "mode": "QUICK", "ok": True,
                "degraded": False}
    if len(message) > _MAX_MESSAGE_CHARS:
        return {
            "answer": ("Message bahut bada hai. Isse document ke roop mein upload karo ya "
                       "Deep/Maximum research mein bhejo, taaki content chup-chaap truncate na ho."),
            "mode": "QUICK", "ok": True, "degraded": True,
            "fallback_required": False, "reason": "message_too_large_for_quick_chat",
        }

    # Don't burn any hosted quota on greetings/thanks/identity.
    local = _smalltalk(message)
    if local:
        return {
            "answer": local, "mode": "QUICK", "ok": True, "degraded": False,
            "reasoning_layer": "deterministic_smalltalk", "api_attempts": 0,
        }

    status = reasoning_status()
    if int(status.get("model_layers_configured", 0) or 0) <= 0:
        return {
            "answer": "",
            "mode": "QUICK",
            "ok": False,
            "degraded": True,
            "fallback_required": True,
            "reason": "no_model_layer_configured",
        }

    brain = ResilientReasoning(budget=1, model_name=MODEL_NAME)
    try:
        text = brain.generate(_build_prompt(message, history), "quick_chat")
    except Exception:
        # Never leak SDK/provider exception to UI. QUICK research fallback below
        # remains available even if an unexpected provider adapter error occurs.
        text = ""

    if text.strip():
        accounting = _safe_accounting(brain)
        return {
            "answer": text.strip(),
            "mode": "QUICK",
            "ok": True,
            "degraded": bool(accounting.get("provider_fallbacks")),
            "fallback_required": False,
            "reasoning_accounting": accounting,
        }

    return {
        "answer": "",
        "mode": "QUICK",
        "ok": False,
        "degraded": True,
        "fallback_required": True,
        "reason": "all_configured_model_layers_unavailable",
        "reasoning_accounting": _safe_accounting(brain),
    }
