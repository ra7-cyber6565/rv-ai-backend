"""
Fast conversational chat — "QUICK" ka asli matlab.

Deep-research engine (papers/books/datasets, connectors, chromadb, embeddings)
bhaari hai aur free server par slow/risky. Aam baat-cheet ke liye uski zaroorat
nahi. Ye module SIRF Gemini ko seedha call karta hai — koi torch, koi chromadb,
koi network connector nahi — isliye ye turant jawab deta hai aur crash-proof hai.

Do cheezein spec/user ke hisaab se yahan zaroori hain:
    1. LANGUAGE MIRROR — jis bhasha/script mein user likhe, ussi mein jawab.
       (Hindi -> Hindi, English -> English, Hinglish -> Hinglish.)
    2. EMOTION MIRROR — user ke mood ke hisaab se tone. Dukhi ho to narmi,
       excited ho to gth same energy. ChatGPT jaisi insaani vibe.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

_SYSTEM = """Tum "RV" ho — ek dost jaisa, samajhdaar AI assistant.

# Pehchaan
- Agar koi poochhe "tum kaun ho / who are you / tumhara naam", to seedha bolo
  ki tum RV ho. Kisi company ya model ka naam mat lo. Chhota, garmजोshi bhara
  jawab: jaise "Main RV hoon 🙂".

# Bhasha (bahut zaroori)
- Jis bhasha aur script mein user ne likha hai, THEEK ussi mein jawab do.
  - User Hindi (Devanagari) mein -> tum bhi Hindi (Devanagari) mein.
  - User English mein -> tum English mein.
  - User Hinglish (Roman Hindi) mein -> tum bhi Hinglish (Roman) mein.
- Apni marzi se bhasha mat badlo.

# Mood match karo (bahut zaroori)
- User ke shabdon se uska mood padho aur ussi hisaab se baat karo:
  - Udaas / pareshaan / dukhi -> pehle narmi aur hamdardi dikhao, phir madad.
  - Khush / excited -> ussi energy aur josh ke saath.
  - Gussa / frustrated -> shaant, seedhi, bina bahaanon ke madad.
  - Casual / masti -> halka-phulka, dostana.
- Insaan jaisi vibe rakho — robotic ya ratti-rataayi nahi.

# Jawab kaisa ho
- Saaf, simple aur samajhne mein aasaan. Zaroorat na ho to lambe-chaude lecture
  mat do. ChatGPT jaise natural baat-cheet.
- Zaroori ho tabhi points/steps use karo, warna normal baat-cheet.
- Emoji tabhi jab mood match kare — zabardasti nahi.
- Jhooth mat bolo. Agar kisi cheez ka pakka jawab poori tarah pakka nahi, to
  imaandaari se bolo, aur agar wo gehri research maangta hai to user ko batao ki
  wo "Deep" ya "Max" mode se poochh sakte hain jahan tum sources padhkar jawab
  dete ho.
"""


def _history_block(history: Optional[List[Dict]]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-8:]:
        role = (turn.get("role") or "").lower()
        text = (turn.get("content") or turn.get("text") or "").strip()
        if not text:
            continue
        who = "User" if role in ("user", "human") else "RV"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _build_prompt(message: str, history: Optional[List[Dict]]) -> str:
    convo = _history_block(history)
    convo_block = f"\n# Ab tak ki baat-cheet\n{convo}\n" if convo else ""
    return f"{_SYSTEM}\n{convo_block}\n# User ka naya message\n{message}\n\n# RV ka jawab"


def quick_chat(message: str, history: Optional[List[Dict]] = None) -> Dict:
    """
    Ek Gemini call, seedha jawab. Kabhi crash nahi karta — error aane par bhi
    ek imaandaar message lautata hai taaki UI par "Failed" na dikhe.
    """
    message = (message or "").strip()
    if not message:
        return {"answer": "Kuch likho to sahi 🙂", "mode": "QUICK", "ok": True}

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return {
            "answer": ("Abhi main jawab nahi de pa raha — server par meri "
                       "GEMINI_API_KEY set nahi hai. (Railway → Variables mein "
                       "GEMINI_API_KEY daalo.)"),
            "mode": "QUICK", "ok": False,
        }
    try:
        import google.generativeai as genai  # lazy: import sasta rahe
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(_build_prompt(message, history))
        text = (getattr(resp, "text", "") or "").strip()
        if not text:
            return {"answer": "Hmm, is baar jawab khaali aaya. Ek baar phir poochho? 🙂",
                    "mode": "QUICK", "ok": False}
        return {"answer": text, "mode": "QUICK", "ok": True}
    except Exception as exc:  # noqa: BLE001 — kabhi crash nahi karna
        name = type(exc).__name__
        if "quota" in str(exc).lower() or "429" in str(exc):
            msg = ("Thodi der ke liye free limit khatam ho gayi 😅 ek-do minute "
                   "baad phir poochho.")
        else:
            msg = f"Ek dikkat aa gayi ({name}). Thodi der baad phir try karo."
        return {"answer": msg, "mode": "QUICK", "ok": False}
