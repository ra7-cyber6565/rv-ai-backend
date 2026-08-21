"""
Gemini model chunna — guess ki jagah, server se poochh kar.

Normal REASONING request ke andar hum Google se model list discover kar sakte
hain, phir usable naam cache karte hain. Diagnostics alag hai: diagnostics ko
khud quota/network burn nahi karna chahiye, isliye `diagnose()` default se
**zero-network / zero-generation-call** hai. Explicit `active_discovery=True`
par sirf model-list discovery chal sakti hai, wo bhi ZERO_COST_ONLY mein tabhi
jab Gemini project(s) ko explicitly no-paid-spend confirm kiya gaya ho.
Diagnostic kabhi `generate_content("Say OK")` nahi karta.

§7: dynamic discovery + dead-model memory.
§8: free backup key par shift hone par model/dead-name cache reset hota hai.

₹0 rule: actual Gemini use se pehle startup zero-cost guard har primary/backup
credential ko confirmation policy ke neeche rakhta hai. Ye module billing oracle
hone ka daawa nahi karta aur guard ko bypass nahi karta.
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
    return name.split("/", 1)[1] if name.startswith("models/") else name


def mark_dead(name: str, reason: str = "model_not_found") -> None:
    if name:
        _dead.setdefault(_clean(name), reason or "model_not_found")


def is_dead(name: str) -> bool:
    return _clean(name or "") in _dead


def dead_models() -> Dict[str, str]:
    return dict(_dead)


def forget_dead() -> None:
    _dead.clear()


def reset_for_new_key() -> None:
    """Backup key switch ke baad key-specific model/dead-name memory clear karo."""
    global _cache, _seen
    _cache = None
    _seen = []
    _dead.clear()


def configure(genai, key: str) -> bool:
    """SDK ko key do without logging/returning the credential value."""
    if not key:
        return False
    genai.configure(api_key=key)
    return True


def _alive(names: List[str]) -> List[str]:
    return [n for n in names if not is_dead(n)]


# ── ek call kitni der latak sakti hai ────────────────────────────────────────
# LIVE BUG (2026-08-21, intel ne report kiya): website par sawaal bhejne ke baad
# aakhir mein "Abhi server se baat nahi ho paayi" aa jaata tha. Wajah engine ka
# jawab nahi tha — wajah ye thi ki `generate_content()` par KOI timeout nahi
# lagta. Google ka SDK default mein anaadi kaal tak intezaar kar sakta hai, to
# ek latki hui call poori HTTP request ko rok kar rakhti thi, aur beech mein
# browser/gateway connection kaat deta tha. User ko lagta tha "server down hai",
# jabki server sirf ek hi call par atka hua tha.
#
# Ab har call ki ek hadd hai. Timeout hone par exception aata hai jise
# `model_errors.classify` TRANSIENT maanta hai — yaani wahi purana retry/backoff
# chalta hai, model band nahi hota, aur koi feature nahi jaata. Hadd env se
# badli ja sakti hai (`GEMINI_CALL_TIMEOUT`, seconds).
def call_timeout() -> int:
    try:
        seconds = int(os.getenv("GEMINI_CALL_TIMEOUT", "") or 75)
    except (TypeError, ValueError):
        seconds = 75
    return max(10, min(seconds, 600))


# Purane SDK (aur test ke nakli model) `request_options` nahi lete. Isliye pehle
# poochh kar dekhte hain ki wo kwarg banta hai ya nahi — aur na bane to bina
# timeout wale purane tareeke se call hoti hai. Call fail KABHI nahi karti.
def _accepts_request_options(func) -> bool:
    try:
        import inspect
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):      # C-level / bina signature wala callable
        return True                      # koshish kar lo, TypeError handle hai
    if "request_options" in params:
        return True
    return any(p.kind is p.VAR_KEYWORD for p in params.values())


def generate(model, prompt, timeout: Optional[int] = None):
    """`model.generate_content(prompt)` — par bandhe hue time ke saath."""
    call = getattr(model, "generate_content")
    if _accepts_request_options(call):
        try:
            return call(prompt, request_options={"timeout": timeout or call_timeout()})
        except TypeError as exc:
            if "request_options" not in str(exc):
                raise
    return call(prompt)


def available_models(genai) -> List[str]:
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
    """Raw provider/protobuf details ke bina coarse user-safe reason."""
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
    """Non-secret Gemini readiness diagnostic with zero generation calls.

    Default call makes zero network calls. Active discovery may make exactly one
    model-list request, never a text-generation request, and is blocked in
    ZERO_COST_ONLY until all configured Gemini keys/projects are explicitly
    confirmed no-paid-spend.
    """
    try:
        from .key_pool import KeyPool
        pool = KeyPool()
    except Exception:
        pool = None

    key_count = pool.count if pool is not None else 0
    key = pool.active() if pool is not None else str(os.getenv("GEMINI_API_KEY", "") or "").strip()
    zero_cost = _truthy(os.getenv("ZERO_COST_ONLY", "true"))
    confirmed = _truthy(os.getenv("GEMINI_ZERO_COST_CONFIRMED", ""))
    wanted = str(os.getenv("GEMINI_MODEL", "") or "").strip()
    report: Dict = {
        "key_present": bool(key_count or key),
        "keys_available": key_count or (1 if key else 0),
        "keys": pool.labels() if pool is not None else (["free key #1"] if key else []),
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
        report["error"] = "Gemini key set nahi hai."
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
        configure(genai, key)
        report["network_calls"] = 1
        names = available_models(genai)
        report["models_found"] = names[:25]
        report["chosen_model"] = _pick(names) or wanted or next(
            (n for n in FALLBACKS if not is_dead(n)), FALLBACKS[0]
        )
        report["status"] = "model_list_discovered"
    except Exception as exc:
        report["status"] = "discovery_failed"
        report["error"] = friendly_error(exc)
    report["dead_models"] = dead_models()
    return report
