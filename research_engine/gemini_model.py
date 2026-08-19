"""
Gemini model chunna — guess ki jagah, server se poochh kar.

Dikkat jo aayi thi: code mein model ka naam hard-code tha ("gemini-flash-latest").
Agar wo naam is API key / is SDK version ke liye maujood na ho, to Google
`InvalidArgument`/`NotFound` (400/404) bhejta hai aur user ko sirf
"Ek dikkat aa gayi (InvalidArgument)" dikhta hai — jo bekaar hai.

Ab hum Google se ek baar poochhte hain ki "kaunse model available hain",
usmein se sabse behtar flash model chunte hain, aur naam yaad rakh lete hain.
Naam kabhi badal jaaye to code badalne ki zaroorat nahi — apne aap chal jaayega.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

# Agar list_models na chale (network/key issue), to inhe try karte hain — order
# mein: naye pehle, purane baad mein.
FALLBACKS: tuple = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-pro-latest",
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


def _clean(name: str) -> str:
    """`models/gemini-2.0-flash` -> `gemini-2.0-flash`."""
    return name.split("/", 1)[1] if name.startswith("models/") else name


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

    GEMINI_MODEL env set ho aur wo asli list mein ho to wahi izzat paata hai.
    """
    global _cache, _seen
    if _cache and not force:
        return _cache

    wanted = (os.getenv("GEMINI_MODEL") or "").strip()
    try:
        names = available_models(genai)
    except Exception:                    # noqa: BLE001 — list na mile to guess
        names = []
    _seen = names

    if names:
        if wanted and any(wanted in n for n in names):
            _cache = wanted
        else:
            _cache = _pick(names) or (wanted or FALLBACKS[0])
    else:
        _cache = wanted or FALLBACKS[0]
    return _cache


def candidates(genai) -> List[str]:
    """
    Try karne ka order: pehle chuna hua model, phir jo model is key ke liye
    SACH MEIN available the, phir aakhir mein andaaze wale fallback naam.

    Kyun: agar pehla model mana kar de to agla try wo hona chahiye jo asli list
    mein tha — na ki koi hard-coded naam jo maujood hi nahi.
    """
    first = resolve(genai)
    order = [first]
    for name in _seen + list(FALLBACKS):
        if name not in order:
            order.append(name)
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
                    "error": ""}
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
            resp = genai.GenerativeModel(name).generate_content("Say OK")
            report["test_call"] = (getattr(resp, "text", "") or "")[:80] or "(khaali jawab)"
        except Exception as exc:  # noqa: BLE001
            report["test_call"] = f"FAILED: {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report
