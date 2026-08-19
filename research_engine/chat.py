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

from .gemini_model import candidates, friendly_error
from .local_language import normalize

# Sirf reference ke liye — asli naam runtime par Google se poochh kar chunte hain
# (dekho gemini_model.resolve). Hard-coded naam hi "InvalidArgument" ki wajah tha.
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

# Local likhne ka andaaz samajhna (bahut zaroori)
- Asli log shuddh spelling nahi likhte. Tumhe waise hi samajh jaana hai jaise
  ek dost samajh jaata hai. Kabhi ye mat kaho ki "samajh nahi aaya" sirf
  spelling ki wajah se.
- Vowel gire hue shabd kholo: smjna=samajhna, nhi=nahi, jldi=jaldi, krke=karke,
  kon/koun=kaun, kyu=kyun, kese=kaise, bnao=banao, bht=bahut, psnd=pasand,
  h=hai, hu=hoon, mtlb=matlab, kch=kuch, btao=batao, pta=pata, thik=theek.
- Angrezi jo kaan se likhi ho, wo pehchaano: lagvej/legvej=language,
  opsion=option, reserch=research, maxiume=maximum, quek=quick,
  deshbord=dashboard, emosion=emotion, personlty=personality, wbsite=website.
- Ek hi vaakya mein Hindi+English mile ho to normal hai — aage badho.
- Regional bol-chaal (Bhojpuri, Haryanvi, Marwari, Punjabi, Marathi, Bangla,
  Tamil-mixed, jo bhi) aaye to ussi lehje mein, ussi apnepan se jawab do.
- User ki spelling KABHI theek mat karo, uspar comment mat karo, aur grammar ka
  lecture mat do. Tum khud saaf-suthra likho — bas.
- Agar do matlab ban rahe hon, to jo zyada mumkin hai wahi maan kar jawab do.
  Bilkul hi samajh na aaye tabhi chhota sa poochho — ek hi line mein.

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

    # Shorthand khula hua roop ek extra hint ke taur par. Isse mangled likhai
    # (jaise "lokal lagvej bhi smjna chahiye") pakki tarah samajh mein aati hai.
    # User ka asli message hi asli hai — hint sirf madad ke liye hai.
    opened = normalize(message)
    hint = ""
    if opened.strip().lower() != message.strip().lower():
        hint = (f"\n# (Andar ka hint — shorthand khola hua, sirf samajhne ke liye)\n"
                f"{opened}\n")

    return (f"{_SYSTEM}\n{convo_block}\n# User ka naya message\n{message}\n{hint}"
            f"\n# RV ka jawab")


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
        prompt = _build_prompt(message, history)

        # Pehle wo model jo Google ki asli list se chuna gaya; agar wo bhi mana
        # kar de to jo baaki available the. Isse "InvalidArgument" par baat
        # khatam nahi hoti — jawab phir bhi aata hai.
        tried: List[str] = []
        last_exc: Optional[Exception] = None
        for name in candidates(genai):
            tried.append(name)
            try:
                resp = genai.GenerativeModel(name).generate_content(prompt)
                text = (getattr(resp, "text", "") or "").strip()
                if text:
                    return {"answer": text, "mode": "QUICK", "ok": True,
                            "model": name}
                last_exc = RuntimeError("khaali jawab")
            except Exception as exc:  # noqa: BLE001 — agla model try karo
                last_exc = exc
                low = str(exc).lower()
                # key hi galat hai ya quota khatam — aage try karna bekaar
                if ("api key not valid" in low or "api_key_invalid" in low
                        or "quota" in low or "429" in low
                        or "resource_exhausted" in low):
                    break
            if len(tried) >= 4:           # bahut der tak mat lagao
                break

        return {"answer": friendly_error(last_exc or RuntimeError("unknown")),
                "mode": "QUICK", "ok": False,
                "detail": f"{type(last_exc).__name__}: {last_exc}" if last_exc else "",
                "models_tried": tried}
    except Exception as exc:  # noqa: BLE001 — kabhi crash nahi karna
        return {"answer": friendly_error(exc), "mode": "QUICK", "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"}

