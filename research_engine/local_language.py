"""
Local likhne ka andaaz samajhna — "smjna", "lagvej", "jldi", "krke", "kon".

Asli log poore-shuddh shabd nahi likhte. Vowel gira dete hain (samajhna ->
smjna), angrezi ko kaan se likhte hain (language -> lagvej, option -> opsion),
aur Hindi-English ek hi vaakya mein milaa dete hain. Insaan ye turant samajh
jaata hai; keyword-matching code nahi.

Ye module do jagah kaam aata hai:
  1. planner (Deep/Max) — question classify karne aur search query banane se
     pehle shabd khol diye jaate hain, warna "reserch" kisi keyword se match
     nahi karta aur search engine par bhi galat spelling chali jaati hai.
  2. chat prompt — Gemini ko alag se bola jaata hai ki aise likhe hue ko samajh
     le (dekho chat.py ka _SYSTEM).

Zaroori: ye SIRF andar ke samajhne ke liye hai. User ko kabhi ye nahi bola
jaata ki "aapki spelling galat hai" — uska likha hua jaisa hai waisa hi izzat
ke saath chalta hai.
"""
from __future__ import annotations

import re
from typing import Dict

# Roman-Hindi shorthand -> poora shabd.
# Sirf wahi shabd jinka matlab saaf hai. Do-teen akshar wale khatre wale shabd
# (jaise "km" = kaam ya kilometre?) jaan-boojh kar chhode gaye hain.
SHORTHAND: Dict[str, str] = {
    # samajhna / batana
    "smj": "samajh", "smjh": "samajh", "smjna": "samajhna", "smjhna": "samajhna",
    "smjao": "samjhao", "smjhao": "samjhao", "smja": "samjha", "smjh_gya": "samajh gaya",
    "btao": "batao", "bta": "bata", "btana": "batana", "btaya": "bataya",
    "bol": "bol", "bolo": "bolo",
    # sawaal wale shabd
    "kon": "kaun", "koun": "kaun", "kn": "kaun",
    "kyu": "kyun", "kyo": "kyun", "kyoki": "kyunki", "kynki": "kyunki",
    "kese": "kaise", "kse": "kaise", "kaise": "kaise",
    "ktna": "kitna", "ktne": "kitne", "kitni": "kitni",
    "kb": "kab",
    # "kha"/"khan" nahi rakhe: "kha liya" (khaana) aur "Khan" (naam) galat khul
    # jaate. Aise dhokhe wale shabd add karne se bachna hai.
    # karna
    "krna": "karna", "krke": "karke", "kro": "karo", "krta": "karta",
    "krti": "karti", "krte": "karte", "kiya": "kiya", "krdo": "kar do",
    # banana
    "bnao": "banao", "bnana": "banana", "bna": "bana", "bnaya": "banaya",
    "bnaye": "banaye", "bnae": "banaye", "bnate": "banate",
    # aam bol-chaal
    # NOTE: "nai" jaan-boojh kar nahi hai — wo "nahi" bhi ho sakta hai aur "naya/nai
    # dawa" bhi. Aisa shabd kholna matlab badal deta hai, isliye chhod diya.
    "nhi": "nahi", "nh": "nahi",
    "h": "hai", "hn": "hain", "hu": "hoon", "hun": "hoon",
    "jldi": "jaldi", "abi": "abhi", "bht": "bahut", "bhut": "bahut",
    "thik": "theek", "thk": "theek", "tik": "theek",
    "acha": "accha", "achha": "accha", "achi": "acchi",
    "psnd": "pasand", "pta": "pata", "mtlb": "matlab", "mtlab": "matlab",
    "kch": "kuch", "sb": "sab", "sbhi": "sabhi", "sth": "saath", "sath": "saath",
    "zada": "zyada", "jyada": "zyada", "jada": "zyada", "zyda": "zyada",
    "phle": "pehle", "phla": "pehla", "wle": "wale",
    "muje": "mujhe", "mje": "mujhe", "mjhe": "mujhe",
    "tm": "tum", "tmko": "tumko", "tmhara": "tumhara", "tumhra": "tumhara",
    "apko": "aapko",
    "chaiye": "chahiye", "chahye": "chahiye", "chiye": "chahiye",
    "dkho": "dekho", "dkhna": "dekhna", "pdhna": "padhna", "pdho": "padho",
    "jsa": "jaisa", "jese": "jaise", "jse": "jaise",
    "prkar": "prakar", "trh": "tarah", "trha": "tarah",
    "lgta": "lagta", "lgti": "lagti", "hogya": "ho gaya", "hogaya": "ho gaya",
    "gya": "gaya", "gyi": "gayi", "rha": "raha", "rhi": "rahi", "rhe": "rahe",
    "krwana": "karwana", "dena": "dena", "lena": "lena",
    # angrezi jo kaan se likhi jaati hai
    "lagvej": "language", "legvej": "language", "langvej": "language",
    "lngvej": "language", "languge": "language",
    "reserch": "research", "resarch": "research", "researh": "research",
    "serch": "search", "sarch": "search",
    "opsion": "option", "opson": "option", "opsn": "option", "opstion": "option",
    "maxiume": "maximum", "maximam": "maximum", "maxium": "maximum",
    "quek": "quick", "quik": "quick",
    "deshbord": "dashboard", "dashbord": "dashboard",
    "emosion": "emotion", "emoshin": "emotion", "emotin": "emotion",
    "emosnal": "emotional", "emosional": "emotional",
    "personlty": "personality", "persnalty": "personality", "personality": "personality",
    "prsnal": "personal",
    "wbsite": "website", "websit": "website", "webiste": "website",
    "prblm": "problem", "problm": "problem", "pblm": "problem",
    # "prob" nahi — research mein wo "probability" hota hai.
    "cmpny": "company", "compny": "company",
    "mesg": "message", "msg": "message", "mesage": "message",
    "pic": "picture", "pics": "pictures",
    "info": "information", "infrmation": "information",
    "ansr": "answer", "answr": "answer", "jawab": "jawab",
    "sikhna": "sikhna", "sikho": "sikho",
    "pls": "please", "plz": "please", "thx": "thanks",
    "lokal": "local", "lokl": "local",
    "vdo": "video", "vid": "video",
    "num": "number", "nmbr": "number",
    "yr": "yaar", "yrr": "yaar", "bhai": "bhai",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def normalize(text: str) -> str:
    """
    Shorthand ko poore shabd mein khol do. Devanagari, numbers, aur jo shabd
    dictionary mein nahi hain — sab jaise hain waise rehte hain.

    Sirf andar ke samajhne ke liye. User ka asli message kabhi badla nahi jaata.
    """
    if not text:
        return ""

    def swap(match: "re.Match") -> str:
        word = match.group(0)
        full = SHORTHAND.get(word.lower())
        if not full:
            return word
        # THEEK hai / Theek hai — jaisa case tha, waisa hi rakho
        if word.isupper() and len(word) > 1:
            return full.upper()
        if word[0].isupper():
            return full[:1].upper() + full[1:]
        return full

    return _WORD.sub(swap, text)
