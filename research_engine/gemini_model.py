"""
Gemini model chunna — guess ki jagah, server se poochh kar.

Dikkat jo aayi thi: code mein model ka naam hard-code tha ("gemini-flash-latest").
Agar wo naam is API key / is SDK version ke liye maujood na ho, to Google
`InvalidArgument`/`NotFound` (400/404) bhejta hai aur user ko sirf
"Ek dikkat aa gayi (InvalidArgument)" dikhta hai — jo bekaar hai.

Ab hum Google se ek baar poochhte hain ki "kaunse model available hain",
usmein se sabse behtar flash model chunte hain, aur naam yaad rakh lete hain.
Naam kabhi badal jaaye to code badalne ki zaroorat nahi — apne aap chal jaayega.

§7 (2026-08-20 ki live failure ke baad) do cheezein add hui hain:

  1. DYNAMIC DISCOVERY PEHLE, GUESS BAAD MEIN — `list_models()` se aaya naam
     hamesha jeetta hai. Neeche jo `FALLBACKS` hain wo sirf tab use hote hain
     jab list_models hi na chale (network/key issue). Isliye is list mein
     purani generation ke naam (1.5-flash, pro-latest) rakhna nuksaan tha:
     wo naam 404 dete the aur system unhe baar-baar try karta rehta tha.

  2. DEAD-MODEL MEMORY (negative cache) — jo naam ek baar 404/"not supported"
     de chuka, wo poore process ke liye chhod diya jaata hai (`mark_dead`).
     Pehle `candidates()` usi mare hue naam ko har pass mein dobara offer
     karta tha, jisse ek hi galti 3 pass × 3 retry = 9 bekaar HTTP call
     ban jaati thi.

₹0 rule: yahan sirf free-tier Gemini model hi aate hain, koi paid service nahi.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

# LAST RESORT ONLY — agar `list_models()` hi fail ho jaaye (network/key), tab
# inhe try karte hain. Sirf current generation ke naam, kyunki mare hue naam
# rakhne se system 404 par waqt barbaad karta hai. Asli source of truth Google
# ki `list_models()` hai, ye list nahi.
FALLBACKS: tuple = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
)

# jo naam pehle pasand hain (substring match, order matters)
_PREFER = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
)

_cache: Optional[str] = None
_seen: List[str] = []          # jo model asli list mein mile the (yaad rakhe)
# naam -> wajah. Ye process-wide hai: 404 ka matlab hai naam hi galat hai,
# aur wo agle request mein bhi galat hi rahega.
_dead: Dict[str, str] = {}


def _clean(name: str) -> str:
    """`models/gemini-2.0-flash` -> `gemini-2.0-flash`."""
    return name.split("/", 1)[1] if name.startswith("models/") else name


# ── dead-model memory (§7) ───────────────────────────────────────────────────
def mark_dead(name: str, reason: str = "model_not_found") -> None:
    """Is naam ko poore process ke liye chhod do (sirf permanent errors par)."""
    if name:
        _dead.setdefault(_clean(name), reason or "model_not_found")


def is_dead(name: str) -> bool:
    return _clean(name or "") in _dead


def dead_models() -> Dict[str, str]:
    """Audit/diag ke liye — kaun kis wajah se chhoda gaya."""
    return dict(_dead)


def forget_dead() -> None:
    """Sirf test/diag ke liye — memory saaf karo."""
    _dead.clear()


# ── key badalne par memory saaf (§8 backup keys) ─────────────────────────────
def reset_for_new_key() -> None:
    """
    Jab hum doosri free key par shift karte hain to purani key ki model-memory
    bekaar ho jaati hai: "kaunse model available hain" har key/project ke liye
    ALAG hota hai, aur 404 bhi key-specific hota hai.

    Isliye naye key par: chuna hua model, dekhi hui list, aur mare hue naam —
    teeno bhula do. Warna nayi key par bhi wahi purana 404 dohraaya jaayega.

    (Yahan koi key value nahi aati — sirf memory clear hoti hai.)
    """
    global _cache, _seen
    _cache = None
    _seen = []
    _dead.clear()


def configure(genai, key: str) -> bool:
    """
    SDK ko di hui key par set karo. `key` sirf yahan use hoti hai — na log hoti
    hai, na return hoti hai. Khaali key par False (caller ko pata chal jaaye).
    """
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
        # image/audio/embedding/tts wale kaam ke nahi
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
    for n in names:                      # koi bhi flash
        if "flash" in n.lower():
            return n
    return names[0] if names else None


def resolve(genai, force: bool = False) -> str:
    """
    Kaam karne wala model name lautata hai. Ek hi baar list_models chalta hai,
    phir yaad rakh liya jaata hai.

    GEMINI_MODEL env set ho aur wo asli list mein ho to wahi izzat paata hai —
    par agar wo naam mar chuka hai (404 de chuka hai), to uski izzat khatam:
    env ki galti se poora research nahi rukna chahiye (§7).
    """
    global _cache, _seen
    if _cache and not force and not is_dead(_cache):
        return _cache

    wanted = (os.getenv("GEMINI_MODEL") or "").strip()
    if wanted and is_dead(wanted):
        wanted = ""
    try:
        names = available_models(genai)
    except Exception:                    # noqa: BLE001 — list na mile to guess
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
    """
    Try karne ka order: pehle chuna hua model, phir jo model is key ke liye
    SACH MEIN available the, phir aakhir mein andaaze wale fallback naam.

    Kyun: agar pehla model mana kar de to agla try wo hona chahiye jo asli list
    mein tha — na ki koi hard-coded naam jo maujood hi nahi.

    §7: jo naam pehle 404 de chuka hai wo is list mein AATA HI NAHI. Aur agar
    yaad rakhi hui list poori mar chuki ho, to ek baar Google se dobara
    poochhte hain (naam badal gaye ho sakte hain).
    """
    first = resolve(genai)
    order = [first] if not is_dead(first) else []
    for name in _alive(_seen) + _alive(list(FALLBACKS)):
        if name not in order:
            order.append(name)
    if not order:
        # sab naam mar chuke — ho sakta hai Google ne naam badal diye hon.
        # Ek dobara discovery, warna khaali haath.
        try:
            fresh = _alive(available_models(genai))
        except Exception:                # noqa: BLE001
            fresh = []
        order = fresh
    return order


def friendly_error(exc: Exception) -> str:
    """
    Google ki technical error ko insaani Hinglish mein badlo — user ko
    "InvalidArgument" se kuch samajh nahi aata, isliye asli wajah batao.
    """
    text = str(exc).lower()
    if "api key not valid" in text or "api_key_invalid" in text:
        return ("Meri GEMINI_API_KEY galat lag rahi hai. Railway → Variables "
                "mein naya key daalo (aistudio.google.com/apikey se), phir "
                "redeploy. 🙂")
    if "quota" in text or "429" in text or "resource_exhausted" in text:
        return ("Thodi der ke liye free limit khatam ho gayi 😅 ek-do minute "
                "baad phir poochho.")
    if "not found" in text or "is not supported" in text or "404" in text:
        return ("Model ka naam is key ke liye kaam nahi kar raha. Railway → "
                "Variables mein GEMINI_MODEL hata do (ya `gemini-2.0-flash` "
                "daalo), phir redeploy.")
    if "permission" in text or "403" in text:
        return ("Key ke paas is model ki permission nahi hai. AI Studio se naya "
                "key banao aur Railway mein daalo.")
    if "location" in text or "user location is not supported" in text:
        return "Is region se Gemini block hai. Thodi der baad ya doosre key se try karo."
    return "Ek chhoti dikkat aa gayi. Thodi der baad phir try karo — main yahin hoon 🙂"


def diagnose() -> Dict:
    """
    Sach-sach report: key hai ya nahi, kaunse model dikh rahe hain, kaunsa
    chuna gaya, aur ek chhota test call chala ya nahi. /api/v1/chat/diag isko
    use karta hai, taaki andaaza lagane ki zaroorat na pade.
    """
    report: Dict = {"key_present": False, "key_length": 0, "sdk_version": "",
                    "models_found": [], "chosen_model": "", "test_call": "",
                    "dead_models": dead_models(), "error": "",
                    "keys_available": 0, "keys": [], "key_setup": {}}
    # §8 — kitni FREE key mili hain (sirf ginti aur label; value kabhi nahi)
    try:
        from .key_pool import KeyPool, describe
        pool = KeyPool()
        report["keys_available"] = pool.count
        report["keys"] = pool.labels()
        # "variable daal diya par backup chal nahi raha" ka seedha jawab:
        # kaunse NAAM dikhe, kitni duplicate thi, aur key alag hai ya wahi ek.
        # `key_setup` mein bhi kabhi key ki value nahi jaati — sirf naam, ginti
        # aur ek ulta-na-ho-sakne-wala 8-hex nishaan.
        report["key_setup"] = describe()
    except Exception:                    # noqa: BLE001
        pass
    key = os.getenv("GEMINI_API_KEY", "")
    report["key_present"] = bool(key)
    report["key_length"] = len(key)
    if not key:
        report["error"] = "GEMINI_API_KEY set nahi hai (Railway → Variables)."
        return report
    try:
        import google.generativeai as genai
        report["sdk_version"] = getattr(genai, "__version__", "unknown")
        genai.configure(api_key=key)
        try:
            report["models_found"] = available_models(genai)[:25]
        except Exception as exc:  # noqa: BLE001
            report["error"] = f"list_models failed: {type(exc).__name__}: {exc}"
        name = resolve(genai, force=True)
        report["chosen_model"] = name
        try:
            resp = generate(genai.GenerativeModel(name), "Say OK", timeout=30)
            report["test_call"] = (getattr(resp, "text", "") or "")[:80] or "(khaali jawab)"
        except Exception as exc:  # noqa: BLE001
            report["test_call"] = f"FAILED: {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["dead_models"] = dead_models()
    return report
