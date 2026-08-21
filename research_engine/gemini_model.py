"""
Gemini model chunna — guess ki jagah, server se poochh kar.

Dikkat jo aayi thi: code mein model ka naam hard-code tha ("gemini-flash-latest").
Agar wo naam is API key / is SDK version ke liye maujood na ho, to Google
`InvalidArgument`/`NotFound` (400/404) bhejta hai aur user ko sirf
"Ek dikkat aa gayi (InvalidArgument)" dikhta hai — jo bekaar hai.

Normal REASONING request ke andar hum Google se model list discover kar sakte
hain, phir usable naam cache karte hain. Diagnostics alag hai: diagnostics ko
khud quota/network burn nahi karna chahiye, isliye `diagnose()` default se
**zero-network / zero-generation-call** hai. Explicit `active_discovery=True`
par sirf model-list discovery chal sakti hai, wo bhi ZERO_COST_ONLY mein tabhi
jab Gemini project ko explicitly no-paid-spend confirm kiya gaya ho. Diagnostic
kabhi `generate_content("Say OK")` nahi karta.

§7 (2026-08-20 ki live failure ke baad):
  1. DYNAMIC DISCOVERY PEHLE, GUESS BAAD MEIN.
  2. DEAD-MODEL MEMORY — permanent 404/not-supported naam repeat nahi hote.

₹0 rule: Gemini access ko project-level billing oracle samajhna galat hoga.
Actual use se pehle `utils.zero_cost_guard` ka explicit confirmation gate lagta
hai; ye module us guard ko bypass nahi karta.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

FALLBACKS: tuple = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
)

_PREFER = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
)

_cache: Optional[str] = None
_seen: List[str] = []
_dead: Dict[str, str] = {}
_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _clean(name: str) -> str:
    """`models/gemini-2.0-flash` -> `gemini-2.0-flash`."""
    return name.split("/", 1)[1] if name.startswith("models/") else name


def mark_dead(name: str, reason: str = "model_not_found") -> None:
    """Is naam ko poore process ke liye chhod do (sirf permanent errors par)."""
    if name:
        _dead.setdefault(_clean(name), reason or "model_not_found")


def is_dead(name: str) -> bool:
    return _clean(name or "") in _dead


def dead_models() -> Dict[str, str]:
    return dict(_dead)


def forget_dead() -> None:
    _dead.clear()


def _alive(names: List[str]) -> List[str]:
    return [n for n in names if not is_dead(n)]


def available_models(genai) -> List[str]:
    """Jo model is key ke liye generateContent support karte hain."""
    out: List[str] = []
    for m in genai.list_models():
        methods = getattr(m, "supported_generation_methods", []) or []
        if "generateContent" not in methods:
            continue
        name = _clean(getattr(m, "name", "") or "")
        if not name:
            continue
        low = name.lower()
        if any(bad in low for bad in ("embedding", "aqa", "image", "vision",
                                      "tts", "audio", "live")):
            continue
        out.append(name)
    return out


def _pick(names: List[str]) -> Optional[str]:
    names = _alive(names)
    for want in _PREFER:
        for n in names:
            if want in n.lower():
                return n
    for n in names:
        if "flash" in n.lower():
            return n
    return names[0] if names else None


def resolve(genai, force: bool = False) -> str:
    """Normal reasoning ke liye usable model name resolve karo."""
    global _cache, _seen
    if _cache and not force and not is_dead(_cache):
        return _cache

    wanted = (os.getenv("GEMINI_MODEL") or "").strip()
    if wanted and is_dead(wanted):
        wanted = ""
    try:
        names = available_models(genai)
    except Exception:
        names = []
    _seen = names

    alive = _alive(names)
    guess = next((n for n in FALLBACKS if not is_dead(n)), FALLBACKS[0])
    if alive:
        if wanted and any(wanted in n for n in alive):
            _cache = wanted
        else:
            _cache = _pick(alive) or (wanted or guess)
    else:
        _cache = wanted or guess
    return _cache


def candidates(genai) -> List[str]:
    """Try order: resolved model -> discovered alive models -> safe name guesses."""
    first = resolve(genai)
    order = [first] if not is_dead(first) else []
    for name in _alive(_seen) + _alive(list(FALLBACKS)):
        if name not in order:
            order.append(name)
    if not order:
        try:
            fresh = _alive(available_models(genai))
        except Exception:
            fresh = []
        order = fresh
    return order


def friendly_error(exc: Exception) -> str:
    """Legacy human-readable mapping; provider router handles production fallback."""
    text = str(exc).lower()
    if "api key not valid" in text or "api_key_invalid" in text:
        return "Gemini key valid nahi lag rahi; app doosra configured free fallback try karega."
    if "quota" in text or "429" in text or "resource_exhausted" in text:
        return "Gemini free limit available nahi hai; app doosra free/local fallback try karega."
    if "not found" in text or "is not supported" in text or "404" in text:
        return "Configured Gemini model available nahi hai; app doosra model/provider try karega."
    if "permission" in text or "403" in text:
        return "Gemini permission available nahi hai; app doosra configured fallback try karega."
    if "location" in text or "user location is not supported" in text:
        return "Gemini is region mein available nahi hai; app doosra configured fallback try karega."
    return "Primary reasoning provider available nahi hua; fallback chain continue hogi."


def diagnose(active_discovery: bool = False) -> Dict:
    """Non-secret Gemini readiness diagnostic.

    Default call performs **zero network calls** and never generates text. It
    intentionally does not expose API-key length/value. `active_discovery=True`
    may call `list_models()` only; in ZERO_COST_ONLY it refuses even that unless
    GEMINI_ZERO_COST_CONFIRMED=true. No diagnostic path performs generateContent.
    """
    key = str(os.getenv("GEMINI_API_KEY", "") or "").strip()
    zero_cost = _truthy(os.getenv("ZERO_COST_ONLY", "true"))
    confirmed = _truthy(os.getenv("GEMINI_ZERO_COST_CONFIRMED", ""))
    wanted = str(os.getenv("GEMINI_MODEL", "") or "").strip()
    report: Dict = {
        "key_present": bool(key),
        "zero_cost_only": zero_cost,
        "zero_cost_confirmed": confirmed,
        "active_discovery_requested": bool(active_discovery),
        "network_calls": 0,
        "generation_calls": 0,
        "models_found": [],
        "chosen_model": wanted or (_cache or ""),
        "dead_models": dead_models(),
        "status": "not_configured" if not key else "configured_not_probed",
        "error": "",
    }
    if not active_discovery:
        return report
    if not key:
        report["status"] = "not_configured"
        report["error"] = "GEMINI_API_KEY set nahi hai."
        return report
    if zero_cost and not confirmed:
        report["status"] = "blocked_by_zero_cost_policy"
        report["error"] = (
            "ZERO_COST_ONLY mein active Gemini discovery blocked hai jab tak "
            "GEMINI_ZERO_COST_CONFIRMED=true na ho."
        )
        return report

    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        report["network_calls"] = 1
        names = available_models(genai)
        report["models_found"] = names[:25]
        report["chosen_model"] = _pick(names) or wanted or next(
            (n for n in FALLBACKS if not is_dead(n)), FALLBACKS[0]
        )
        report["status"] = "model_list_discovered"
    except Exception as exc:
        # Keep raw SDK/protobuf text out of diagnostic response.
        report["status"] = "discovery_failed"
        report["error"] = friendly_error(exc)
    report["dead_models"] = dead_models()
    return report
