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
import time
from typing import Dict, List, Optional

from .gemini_model import (candidates, configure, friendly_error, generate,
                           reset_for_new_key)
from .key_pool import KeyPool
from .local_language import normalize
from .local_reasoning import quick_answer as offline_quick

# Sirf reference ke liye — asli naam runtime par Google se poochh kar chunte hain
# (dekho gemini_model.resolve). Hard-coded naam hi "InvalidArgument" ki wajah tha.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def _seconds(env_name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(env_name, "") or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


# QUICK chat ki do haddein (dono env se badli ja sakti hain):
#   CALL_TIMEOUT   — ek Gemini call zyada se zyada itni der latak sakti hai
#   TOTAL_BUDGET   — saare model milakar itne second se aage nahi jaana
# Ye "feature kaatna" nahi hai — model list, key rotation, offline parat, sab
# waise hi hain. Sirf intezaar ki hadd hai, taaki HTTP connection zinda rahe.
CALL_TIMEOUT_SECONDS = _seconds("GEMINI_CHAT_TIMEOUT", 45, 10, 300)
TOTAL_BUDGET_SECONDS = _seconds("GEMINI_CHAT_BUDGET", 100, 20, 600)

_SYSTEM = """Tum "RV" ho — ek dost jaisa, samajhdaar AI assistant.

# Pehchaan
- Agar koi poochhe "tum kaun ho / who are you / tumhara naam", to seedha bolo
  ki tum RV ho. Kisi company ya model ka naam mat lo. Chhota, garmjoshi bhara
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

# Badi cheez ko chhoti bhasha mein samjhana (yahi asli kaam hai)
- Pehle ek-do line ka SEEDHA jawab do. "Ye ek complex topic hai" jaisi bhoomika
  se shuru mat karo.
- Bhaari shabd pehli baar aaye to usi vaakya mein uska aam matlab bracket mein
  likho: "insulin resistance (jab body insulin ki sunna band kar deti hai)".
- Chhote vaakya. Ek vaakya = ek baat.
- Ek roz-marra ka example ya tulna do — rasoi, paisa, traffic, mobile ki battery
  jaisa. Par example topic se sach mein milta ho, banawati nahi.
- Aankda dete waqt uska matlab bhi: "30% kam" ke saath "yaani 10 mein se 3".
- Bhaari-bharkam lines ("bahu-aayami", "it is important to note that") mat likho.
  Shabd hatane se matlab na badle to hata do.
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


def _one_key_try(genai, prompt: str) -> Dict:
    """
    EK key par jawab lene ki koshish. Lautata hai:
        {"text": str, "tried": [...], "exc": Exception|None, "key_dead": bool}

    `key_dead=True` ka matlab: is KEY ki hadd thi (quota/auth), model ki galti
    nahi — yaani doosri free key try karna sach mein kaam ka hai.

    TIME KA HISAAB (2026-08-21): QUICK chat interactive hai — user screen ke
    saamne baitha hai. Pehle ek latki hui call yahan anaadi kaal tak ruk sakti
    thi, aur 4 model × latakna = browser/gateway ka connection kat jaana. Ab
    do haddein hain: har call ka apna timeout (`CALL_TIMEOUT`) aur poori koshish
    ka wall-clock budget (`TOTAL_BUDGET`). Budget khatam hote hi hum ruk jaate
    hain — par khaali haath nahi lautte: upar wali offline parat phir bhi jawab
    deti hai. Koi model ya feature band nahi hota.
    """
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    tried: List[str] = []
    last_exc: Optional[Exception] = None
    key_dead = False
    for name in candidates(genai):
        if tried and time.monotonic() >= deadline:
            last_exc = last_exc or TimeoutError(
                f"chat ka {TOTAL_BUDGET_SECONDS}s budget khatam ho gaya")
            break
        tried.append(name)
        try:
            # Bandhe hue time ke saath — ek latki hui call poori chat ko rok kar
            # nahi rakh sakti (isi wajah se website par "server se baat nahi ho
            # paayi" aata tha).
            remaining = int(max(10, min(CALL_TIMEOUT_SECONDS,
                                        deadline - time.monotonic())))
            resp = generate(genai.GenerativeModel(name), prompt,
                            timeout=remaining)
            text = (getattr(resp, "text", "") or "").strip()
            if text:
                return {"text": text, "tried": tried, "exc": None,
                        "key_dead": False, "model": name}
            last_exc = RuntimeError("khaali jawab")
        except Exception as exc:  # noqa: BLE001 — agla model try karo
            last_exc = exc
            low = str(exc).lower()
            # key hi galat hai ya quota khatam — is key par aage try karna bekaar
            if ("api key not valid" in low or "api_key_invalid" in low
                    or "quota" in low or "429" in low
                    or "resource_exhausted" in low or "permission" in low):
                key_dead = True
                break
        if len(tried) >= 4:           # bahut der tak mat lagao
            break
    return {"text": "", "tried": tried, "exc": last_exc, "key_dead": key_dead,
            "model": ""}


def quick_chat(message: str, history: Optional[List[Dict]] = None) -> Dict:
    """
    Ek Gemini call, seedha jawab. Kabhi crash nahi karta — aur ab kabhi DEAD-END
    bhi nahi karta.

    Teen parat (₹0, sab free):
      1. pehli free key par Gemini (jaisa pehle tha)
      2. quota/auth marne par BACKUP free key par shift (key_pool)
      3. saari key mar jaayein to engine ka apna offline jawab — free sources
         (Wikipedia/DuckDuckGo) padh kar. Yahan bhi "Failed" jaisa kuch nahi.
    """
    message = (message or "").strip()
    if not message:
        return {"answer": "Kuch likho to sahi 🙂", "mode": "QUICK", "ok": True}

    keys = KeyPool()
    if not keys.has_key():
        # key hi nahi hai — phir bhi jawab dena hai, error page nahi dikhana
        out = offline_quick(message, cause="no-key")
        out["reason"] = ("Server par GEMINI_API_KEY set nahi hai "
                         "(Railway → Variables).")
        return out
    try:
        import google.generativeai as genai  # lazy: import sasta rahe
        prompt = _build_prompt(message, history)

        tried: List[str] = []
        last_exc: Optional[Exception] = None
        switches = 0
        while True:
            configure(genai, keys.active())
            # Pehle wo model jo Google ki asli list se chuna gaya; agar wo bhi
            # mana kar de to jo baaki available the. Isse "InvalidArgument" par
            # baat khatam nahi hoti — jawab phir bhi aata hai.
            res = _one_key_try(genai, prompt)
            tried.extend(n for n in res["tried"] if n not in tried)
            last_exc = res["exc"] or last_exc
            if res["text"]:
                answer = {"answer": res["text"], "mode": "QUICK", "ok": True,
                          "model": res["model"]}
                if switches:
                    # sirf ginti aur label — key ki value kabhi nahi
                    answer["key_switches"] = switches
                    answer["key_used"] = keys.label()
                return answer
            if not res["key_dead"] or not keys.has_backup():
                break
            keys.advance("quota/auth")
            switches += 1
            reset_for_new_key()      # nayi key par model-memory saaf
        # Gemini se kuch nahi mila — ab bhi user ko jawab milega (offline parat)
        out = offline_quick(message)
        out["models_tried"] = tried
        out["key_switches"] = switches
        out["keys_available"] = keys.count
        if last_exc is not None:
            # raw text sirf debug field mein — user ko dikhne wale answer mein nahi
            out["detail"] = f"{type(last_exc).__name__}: {last_exc}"
            out["reason"] = friendly_error(last_exc)
        return out
    except Exception as exc:  # noqa: BLE001 — kabhi crash nahi karna
        out = offline_quick(message)
        out["detail"] = f"{type(exc).__name__}: {exc}"
        out["reason"] = friendly_error(exc)
        return out

