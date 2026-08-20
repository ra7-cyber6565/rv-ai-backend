"""
Jawab kaise SAMJHAYA jaye — Spec Section 14 ka "insaan jaisa" hissa.

Do alag samasyaon ka ek jagah hal, kyunki dono "jawab padhne wale tak pahuncha
ya nahi" par asar daalti hain:

  1. BHASHA MIRROR. Deep/Maximum ka synthesis prompt pehle HAR HAAL mein
     "simple, conversational Hindi/Hinglish" maangta tha. Chat side (chat.py ka
     _SYSTEM) pehle se user ki bhasha mirror karta tha — yaani ek hi app do
     tarah se behave kar rahi thi: QUICK mein English sawaal ka English jawab,
     aur MAXIMUM mein usi sawaal ka Hinglish jawab. Ab dono ek hi rule padhte
     hain: jis bhasha/script mein sawaal aaya, ussi mein jawab.

  2. SAMJHANE KA TARIKA. Purana prompt "simple language" bol deta tha, par ye
     bataata nahi tha ki simple ka matlab kya hai. Model phir bhi
     "stochastic gradient descent optimizes the loss landscape" jaisa likh deta
     tha — technically theek, samajh mein kuch nahi. Neeche ke rules wahi
     tarika likhte hain jo GPT-jaisa lagta hai: pehle ek line ka seedha jawab,
     phir bada shabd aaye to turant uska roz-marra matlab, chhote vaakya, aur
     ek asli zindagi ka example.

HEADINGS KA KHATRA (isliye alag rule hai): synthesizer.assemble() model ke
output ko HEADING ke naam se pehchan kar canonical order mein jodta hai
(`_TITLE_HINTS`). Agar model heading bhi Hindi mein likh de ("## निष्कर्ष"), to
matching fail ho jaati hai aur poora section chup-chaap gum ho jaata hai. Isliye
headings HAMESHA diye gaye roop mein rehti hain — sirf andar ka text user ki
bhasha mein.
"""
from __future__ import annotations

import re
from typing import Dict

# Devanagari block. Sirf isi se "Hindi" maan lena kaafi nahi — Hinglish prompt
# mein bhi ek-do Devanagari shabd ghus sakte hain, isliye neeche ratio dekhte hain.
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")

# Agar itne se zyada akshar Devanagari hain to sawaal Hindi ka hai (technical
# shabd angrezi mein hone par bhi — "nuclear, solar और battery" wala prompt
# Hindi hi hai).
_HINDI_SHARE = 0.25

# Roman Hindi ke pakke nishaan. Ye poore shabd ke roop mein match hote hain
# (substring se nahi — warna "this" ke andar "hi" mil jaata).
_HINGLISH_MARKERS = {
    "hai", "hain", "hoga", "hogi", "tha", "thi", "kya", "kyun", "kyu", "kaise",
    "kaun", "kitna", "kitne", "nahi", "nhi", "mein", "me", "ka", "ki", "ke",
    "ko", "se", "aur", "par", "batao", "bta", "btao", "bataiye", "samjhao",
    "smjao", "karo", "kro", "karna", "banao", "bnao", "chahiye", "mujhe",
    "muje", "yaar", "bhai", "matlab", "mtlb", "thoda", "bahut", "bht", "acha",
    "accha", "jawab", "sawaal", "sawal", "abhi", "abi", "jaldi", "jldi",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def detect_language(text: str) -> str:
    """
    "hindi" (Devanagari) / "hinglish" (Roman Hindi) / "english".

    Ye guess hai, faisla nahi — isliye prompt mein bhi likha jaata hai ki
    "agar guess galat lage to user ke likhe hue par jao". Model ke paas asli
    sawaal hai, uska judgement is regex se behtar hoga.
    """
    body = str(text or "")
    devanagari = len(_DEVANAGARI.findall(body))
    latin = len(_LATIN.findall(body))
    total = devanagari + latin
    if total == 0:
        return "hinglish"
    if devanagari and devanagari / total >= _HINDI_SHARE:
        return "hindi"
    words = {w.lower() for w in _WORD_RE.findall(body)}
    if devanagari or (words & _HINGLISH_MARKERS):
        return "hinglish"
    return "english"


_LANGUAGE_LINE: Dict[str, str] = {
    "hindi": ("User ne HINDI (Devanagari) mein poochha hai — poora jawab Hindi "
              "(Devanagari) mein likho. Technical shabd (DNA, battery, quantum) "
              "jaise hain waise rakho, par unka matlab Hindi mein samjhao."),
    "hinglish": ("User ne HINGLISH (Roman Hindi) mein poochha hai — poora jawab "
                 "Hinglish (Roman script) mein likho. Devanagari mat use karo."),
    "english": ("The user asked in ENGLISH — write the whole answer in simple "
                "English. Do not switch to Hindi or Hinglish."),
}


def language_rule(question: str) -> str:
    """Prompt ka bhasha-block. Har reasoning/synthesis prompt mein jaata hai."""
    lang = detect_language(question)
    return (f"# BHASHA (sabse zaroori)\n"
            f"- {_LANGUAGE_LINE[lang]}\n"
            f"- Ye detection automatic hai. Agar user ka likha hua isse alag "
            f"lagta hai, to user ke likhe hue ko maano — apni marzi se bhasha "
            f"badalna sirf tab galat hai jab user ne khud nahi badli.\n"
            f"- User ki spelling/shorthand par comment MAT karo aur use theek "
            f"karne ki koshish mat karo. Jo likha hai use izzat se samjho.")


# ── samjhane ka tarika ───────────────────────────────────────────────────────
# Ye rules jaan-boojh kar "kya karo" ke roop mein hain, "achha likho" ke roop
# mein nahi — "write simply" wala nirdesh pehle se tha aur kaam nahi kar raha tha.
PLAIN_STYLE_RULES = """# SAMJHANE KA TARIKA (jaise ek samajhdaar dost samjhata hai)
- SABSE PEHLE ek-do line ka SEEDHA jawab do. Bhoomika, "ye ek complex topic hai",
  ya definition se shuru mat karo.
- Bada/technical shabd pehli baar aaye to usi vaakya mein uska roz-marra matlab
  bracket mein likho. Jaise: "mitochondria (cell ka power house)".
- Chhote vaakya. Ek vaakya = ek baat. 25 shabd se lamba vaakya na ho.
- Kam se kam ek roz-marra ka example ya tulna do (rasoi, paisa, traffic, mobile
  battery — jo topic se sach mein milta ho). Example banawati mat banao.
- Numbers ka matlab bhi likho: "40% zyada" ke saath "yaani 10 mein se 4 case"
  jaisa. Sirf aankda dena samjhana nahi hai.
- Jo baat pakki nahi hai, use ghol-mol shabdon mein nahi, saaf bolo: "ye pakka
  nahi hai", "ispar sources aapas mein sehmat nahi hain".
- Ghisi-piti bhaari lines mat likho ("bahu-aayami vishleshan", "it is important
  to note that", "in conclusion"). Seedhi baat karo.
- Buzzword se izzat kamane ki koshish mat karo. Agar ek shabd hatane se matlab
  nahi badalta, to hata do."""


def heading_rule(section_titles) -> str:
    """
    Headings ko jaisa diya hai waisa hi rakhna — ye cosmetic nahi, PARSER ki
    zaroorat hai (dekho is file ka docstring).
    """
    sample = section_titles[0] if section_titles else "1. Seedha Jawab"
    return (f"# HEADINGS\n"
            f"- Section heading BILKUL jaisi di gayi hai waisi hi likho "
            f"(jaise `## {sample}`) — number aur shabd badle bina, translate "
            f"kiye bina. System headings se hi sections pehchanta hai; badalne "
            f"par wo section jawab se gayab ho jaata hai.\n"
            f"- Heading ke NEECHE ka text user ki bhasha mein likho.")


def style_block(question: str, section_titles=None) -> str:
    """Bhasha + samjhane ka tarika (+ heading rule agar sections chahiye)."""
    parts = [language_rule(question), PLAIN_STYLE_RULES]
    if section_titles:
        parts.append(heading_rule(section_titles))
    return "\n\n".join(parts)
