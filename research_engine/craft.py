"""#121 — CRAFT stage: "bana kar do" wali maang par app apna draft KHUD naapta hai.

Aaj tak pipeline sirf *jaankari* ke sawaal par imaandaar tha. "gaana banao",
"kavita likho", "letter likho" par wo research karta tha, draft likh deta tha —
aur bas. Draft ko koi naapta nahi tha, isliye "acha bana hai" sirf model ka apna
daawa reh jaata tha.

Ye module us khaali jagah ko bharta hai, LAB (#116) ke usi tareeqe se:

    research  →  SPEC (kya banana hai, naap ke saath)
              →  DRAFT (model likhta hai)
              →  NAAP (yahan — deterministic, ₹0, bina internet)
              →  reject + wajah  →  DOBARA draft (ek bounded round)
              →  deliver, ye likh kar ki KYA naapa gaya aur kya naapa hi nahi ja sakta

Jo cheezein ye module JAAN-BOOJH KAR nahi karta:
  * "viral hoga", "sabko pasand aayega", "hit hai" — aisa koi daawa nahi. Ye
    naapa hi nahi ja sakta; `CANNOT_MEASURE` me saaf likha hai. Draft khud aisa
    daawa kare to wo ek FAIL check hai.
  * Matra/tuk ka naap "gaana acha hai" nahi kehta. Ye sirf **structure** ka naap
    hai (kitni matra, tuk milti hai ya nahi, hook kahan hai) — feeling ka nahi.
  * Cliché list chhoti aur adhoori hai (`CLICHE_LIST_IS_NOT_EXHAUSTIVE`). "0
    cliché mile" ka matlab "bilkul fresh hai" nahi hota.
  * Koi network, koi paid provider, koi randomness. Dobara draft banwane ke liye
    bhi ye module KHUD koi model nahi bulata — caller `reviser` de to hi ek round
    chalta hai, warna saaf "revise chala hi nahi" likha jaata hai.
  * Copyright/originality check nahi hota. "Ye kisi ke gaane se milta hai ya
    nahi" — ye yahan naapa nahi jaata aur claim bhi nahi kiya jaata.

Naap ka poora hisaab deterministic hai: wahi draft → wahi number, har baar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import lang_bridge

# ── check status vocabulary (LAB se alag rakha gaya hai jaan-boojh kar) ───────
# LAB hypothesis ke SACH ke baare me bolta hai; CRAFT sirf draft ke DHAANCHE ke
# baare me. Dono ke shabd ek kar dene se report me "TESTED_PASS" padh kar lagta
# ki gaana sach sabit ho gaya — isliye alag vocabulary.
MET = "MET"                    # naap target par hai
NOT_MET = "NOT_MET"            # naapa gaya, target par nahi hai
NOT_MEASURED = "NOT_MEASURED"  # naapne ke liye zaroori cheez nahi mili

CHECK_STATUSES: Tuple[str, ...] = (MET, NOT_MET, NOT_MEASURED)

# ── poore draft ka nateeja ───────────────────────────────────────────────────
DRAFT_OK = "DRAFT_MEASURED_OK"        # jitne check chale, sab MET
DRAFT_WEAK = "DRAFT_MEASURED_WEAK"    # ek ya zyada check NOT_MET
DRAFT_UNMEASURED = "DRAFT_NOT_MEASURABLE_HERE"   # ek bhi check chala hi nahi
NO_DRAFT = "NO_DRAFT_FOUND"           # draft hi nahi mila
NOT_RUN = "NOT_RUN"                   # stage chalaya hi nahi gaya

DRAFT_STATUSES: Tuple[str, ...] = (DRAFT_OK, DRAFT_WEAK, DRAFT_UNMEASURED,
                                   NO_DRAFT, NOT_RUN)

CRAFT_DISCLAIMER = (
    "Neeche ka naap app ne KHUD apne andar chalaya hai (structure ka hisaab — "
    "matra, tuk, dohraav, hook ki jagah; ₹0, bina internet). Ye naap \"gaana/"
    "likhawat acha hai\" ya \"logon ko pasand aayega\" NAHI kehta — wo naapa hi "
    "nahi ja sakta."
)

# Jo cheezein ye stage naap hi nahi sakta — report me naam se likhi jaati hain,
# taaki chuppi ko koi "sab theek hai" na padh le.
CANNOT_MEASURE: Tuple[str, ...] = (
    "kisi ko pasand aayega ya nahi",
    "viral/hit hoga ya nahi",
    "sunne par kaisa feel hoga (emotion ka asar)",
    "dhun/sur par baithega ya nahi (koi audio nahi bana)",
    "kisi maujooda gaane se milta-julta hai ya nahi (copyright/originality)",
)

# ── maang padhne ke cue ──────────────────────────────────────────────────────
# Ye cue *format* pehchaante hain ("kya banana hai"), *vishay* nahi. Vishay ka
# faisla ab bhi lenses.py karta hai — wahan closed keyword list mana hai, aur ye
# table us niyam ko nahi todta: "gaana" shabd se ye tay nahi hota ki gaana kis
# baare me hai, sirf itna tay hota ki ek draft naapna padega.
#
# Milaan do tarah se hota hai (dekho `_cue_hit`):
#   1. romanised token exact/prefix — Hinglish ("gaana") aur Devanagari
#      (`roman("गाना") == "gaanaa"`) dono cover ho jaate hain.
#   2. consonant skeleton — sirf tab jab skeleton 3+ ka ho. "gn" (gaana) jaisa
#      chhota skeleton "gyan"/"gaon" se takra jaata hai, isliye chhote shabd
#      sirf parat 1 se milte hain.
_MIN_CUE_SKELETON = 3

# Jaan-boojh kar BAAHAR rakhe gaye shabd. Ye "aam research deliverable" ke naam
# hain — pipeline har sawaal ka jawaab isi shakal me deti hai. "superconductivity
# par ek report banao" / "ek summary banao" ek research farmaish hai, likhawat
# banane ki farmaish nahi; agar CRAFT inpar chal jaaye to (a) model se draft ko
# fence me maanga jaayega aur poore structured jawaab ki shakal bigdegi, (b) usi
# prose par doosri, kamzor naap chadh jaayegi jise structured_answer /
# result_coverage_gate / final_quality_gate pehle se naapte hain.
# Isliye ye shabd kisi Form ki `romans` me NAHI hain — aur ye tuple isliye likha
# hai ki ye chhoot chupi na rahe (test isi ko pin karta hai).
PROSE_DELIVERABLE_WORDS: Tuple[str, ...] = (
    "report", "note", "notes", "summary", "saransh", "brief", "blog", "post",
    "column", "article", "writeup", "overview",
)

_MAKE_CUES: Tuple[str, ...] = (
    "likho", "likh", "likhkar", "likhna", "likhiye", "likhdo", "likhde",
    "lkho", "banao", "bnao", "banado", "bnado", "banakar", "bnaakr", "bana",
    "bnaa", "banaiye", "banaye", "bnaye", "tayaar", "tayar", "draft",
    "write", "writing", "compose", "create", "make", "generate", "craft",
    "rachna", "rckhnaa", "sunao", "gao", "gaao",
)
_MAKE_SKELETONS: Tuple[str, ...] = ("bnd", "kmps", "krft", "drft", "gnrt")


@dataclass(frozen=True)
class Form:
    """Ek kism ki likhawat aur uske dhaanche ki default umeed."""

    form_id: str
    label: str
    romans: Tuple[str, ...]
    skeletons: Tuple[str, ...] = ()
    verse: bool = False          # line-by-line dhaancha maayne rakhta hai
    rhyme_default: bool = False  # tuk ki umeed (user ulta bol sakta hai)
    hook_default: bool = False   # dohraaya jaane wala mukhda/refrain chahiye
    min_lines: int = 0
    min_words: int = 0


FORMS: Tuple[Form, ...] = (
    Form("song", "gaana (lyrics)",
         ("gaana", "gaanaa", "gaane", "gana", "gaan", "geet", "giit", "gazal",
          "gjl", "ghazal", "song", "songs", "lyric", "lyrics", "bhajan",
          "qawwali", "rap", "mukhda", "mkhd", "antara", "antraa"),
         ("bhjn", "kvl", "lrk"),
         verse=True, rhyme_default=True, hook_default=True, min_lines=6),
    Form("poem", "kavita/shayari",
         ("kavita", "kvita", "kvitaa", "kavitaa", "poem", "poetry", "shayari",
          "shaayrii", "shayri", "sher", "nazm", "nzm", "haiku", "dohaa",
          "doha", "chhand", "chnd", "verse"),
         ("kvt", "pym", "sr", "nzm", "hk"),
         verse=True, rhyme_default=True, min_lines=4),
    Form("slogan", "slogan/tagline/caption",
         ("slogan", "slgn", "naara", "naaraa", "nara", "tagline", "caption",
          "punchline", "jingle", "headline"),
         ("slgn", "tgln", "kpsn", "pnkln", "jngl", "hdln"),
         verse=True, min_lines=1),
    Form("story", "kahani",
         ("kahani", "khaanii", "kahaani", "kahanii", "story", "kissa", "qissa",
          "kathaa", "katha", "novel", "afsana"),
         ("khn", "str", "ks", "ktn", "nvl", "afsn"),
         min_words=180),
    Form("letter", "patra/letter",
         ("letter", "patra", "ptr", "chitthi", "chithi", "citttthii", "email",
          "mail", "application", "arji", "arzi", "prarthna", "resume",
          "cover"),
         ("ltr", "kt", "ml", "aplkn", "arj", "prtn", "rsm"),
         min_words=70),
    Form("speech", "bhashan/speech",
         ("bhashan", "bhaassnn", "bhasan", "speech", "sambodhan", "lecture",
          "monologue", "pitch"),
         ("bsn", "spk", "snbdn", "lktr", "mnlg"),
         min_words=140),
    Form("essay", "nibandh/lekh",
         ("nibandh", "nibndh", "niband", "nibandhan", "essay", "essays",
          "lekh", "lekhan"),
         ("nbnd", "nbndn", "lkn"),
         min_words=220),
    Form("dialogue", "samvaad/script",
         ("samvaad", "snvaad", "sambad", "dialogue", "script", "screenplay",
          "skit", "natak", "naatak", "drama"),
         ("snvd", "dlg", "skrpt", "skt", "ntk", "drm"),
         min_words=120),
)

# ── ginti (requested.py wali aadat: shabd, Devanagari ank, ya digit) ─────────
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMS: Dict[str, int] = {
    "ek": 1, "एक": 1, "one": 1, "do": 2, "दो": 2, "two": 2,
    "teen": 3, "तीन": 3, "three": 3, "char": 4, "chaar": 4, "चार": 4,
    "four": 4, "panch": 5, "paanch": 5, "पांच": 5, "पाँच": 5, "five": 5,
    "chah": 6, "chhah": 6, "chhe": 6, "छह": 6, "six": 6,
    "saat": 7, "सात": 7, "seven": 7, "aath": 8, "आठ": 8, "eight": 8,
    "nau": 9, "नौ": 9, "nine": 9, "das": 10, "दस": 10, "ten": 10,
    "barah": 12, "बारह": 12, "twelve": 12, "solah": 16, "सोलह": 16,
    "sixteen": 16, "bees": 20, "बीस": 20, "twenty": 20, "sau": 100,
    "सौ": 100, "hundred": 100,
    # Devanagari ginti ki romanised shakal (lang_bridge.roman ka output) — ye
    # roman-fallback pass ke liye hai, taaki "सोलह मात्रा" spelling ki wajah se
    # na chhoote.
    "tiin": 3, "caar": 4, "paanc": 5, "chh": 6, "aatth": 8, "ds": 10,
    "baarh": 12, "solh": 16, "biis": 20, "sau": 100,
}
_NUM_WORD = "|".join(sorted((re.escape(k) for k in _NUMS), key=len,
                            reverse=True))
_NUM_TOKEN = r"(?:\d{1,4}|[०-९]{1,4}|" + _NUM_WORD + r")"


def _num(token: str) -> int:
    """"solah" / "१६" / "16" → 16. Samajh na aaye to 0."""
    raw = (token or "").strip().translate(_DEV_DIGITS).lower()
    if raw.isdigit():
        try:
            return int(raw)
        except ValueError:
            return 0
    return int(_NUMS.get(raw, _NUMS.get(token.strip(), 0)))


def _count_near(question: str, unit: str) -> int:
    """
    "8 line ka gaana" / "gaana 8 line ka" — dono taraf dekhte hain, requested.py
    ke usi proximity tareeqe se. Na mile to 0 (matlab: user ne nahi bataya —
    andaza NAHI lagate).

    Dono taraf shabd ki seema (`(?<!\\w)` / `(?!\\w)`) lagana zaroori hai:
    bina iske "loneliness" ke andar ka "one" + "line" mil kar `line_target = 1`
    bana deta tha.

    Devanagari sawaal seedha match hota hai (unit list me Devanagari shakal bhi
    hai). Fir bhi na mile to ek baar romanised shakal par dekhte hain, taaki
    "आठ पंक्ति" jaisi likhawat sirf spelling ki wajah se na chhoote.
    """
    raw = str(question or "")
    for text in (raw, _roman_or_empty(raw)):
        if not text:
            continue
        head = re.search(r"(?<!\w)(" + _NUM_TOKEN + r")\s*(?:[-–—]\s*)?(?:"
                         + unit + r")(?!\w)", text, re.IGNORECASE)
        if head:
            return _num(head.group(1))
        tail = re.search(r"(?<!\w)(?:" + unit + r")(?!\w)"
                         r"\s*(?:me|mein|of|:|=|ki|ke|ka)?\s*(?<!\w)("
                         + _NUM_TOKEN + r")(?!\w)", text, re.IGNORECASE)
        if tail:
            return _num(tail.group(1))
    return 0


def _roman_or_empty(text: str) -> str:
    """Romanised shakal — lang_bridge na chale to khaali (chup se fail nahi)."""
    try:
        out = lang_bridge.roman(str(text or ""))
    except Exception:
        return ""
    return "" if out == text else out


# ── cue milaan ───────────────────────────────────────────────────────────────
def _romans(text: str) -> List[str]:
    """Sawaal ke tokens, roman kar ke (Devanagari/Bangla bhi isi raste aate)."""
    try:
        return [t for t in lang_bridge.roman_tokens(text) if t]
    except Exception:
        return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _cue_hit(tokens: Sequence[str], romans: Sequence[str],
             skels: Sequence[str] = ()) -> str:
    """
    Pehla cue jo mila, wahi lauta do (deterministic: FORMS ke kram me).

    Parat 1 — token exact ya prefix (Hinglish + romanised Devanagari).
    Parat 2 — consonant skeleton, sirf 3+ lambe skeleton par (chhote skeleton
    par ittefaq ho jaata hai: "gaana" ka skeleton "gn" hai, aur "gyan"/"gaon"
    ka bhi wahi).
    """
    for want in romans:
        for tok in tokens:
            if tok == want or (len(want) >= 4 and tok.startswith(want)):
                return want
    for want in skels:
        if len(want) < _MIN_CUE_SKELETON:
            continue
        for tok in tokens:
            try:
                if lang_bridge.skeleton(tok) == want:
                    return want
            except Exception:
                continue
    return ""


def detect(question: str) -> Dict[str, Any]:
    """
    Sawaal "kuch bana kar do" hai ya nahi — aur kya banana hai.

    Do cheezein DONO chahiye: ek banane wala verb (likho/banao/write) aur ek
    kism ka naam (gaana/kavita/letter). Sirf "kavita" par ye stage nahi chalta —
    "Kabir ki kavita ke baare me batao" research hai, farmaish nahi.
    """
    tokens = _romans(question)
    make = _cue_hit(tokens, _MAKE_CUES, _MAKE_SKELETONS)
    hit_form: Optional[Form] = None
    form_cue = ""
    for form in FORMS:
        cue = _cue_hit(tokens, form.romans, form.skeletons)
        # Dohri deewar: agar kabhi galti se koi aam-deliverable shabd kisi Form
        # me chala jaaye, to bhi ye stage us par nahi chalega.
        if cue and cue.lower() in PROSE_DELIVERABLE_WORDS:
            cue = ""
        if cue:
            hit_form, form_cue = form, cue
            break
    if not make or hit_form is None:
        return {"is_request": False, "form": "", "label": "",
                "make_cue": make, "form_cue": form_cue,
                "reason": "no_make_verb" if not make else "no_form_word"}
    return {"is_request": True, "form": hit_form.form_id,
            "label": hit_form.label, "make_cue": make, "form_cue": form_cue,
            "reason": ""}


# ── matra ka hisaab (laghu = 1, guru = 2) ────────────────────────────────────
# Ye chhand-shastra ka BUNIYAADI niyam set hai, poora nahi:
#   * lambi swar (आ ई ऊ ए ऐ ओ औ aur unki matra) → guru
#   * anusvara / candrabindu / visarga lage akshar → guru
#   * jis akshar ke baad sanyukt vyanjan (cluster) aaye, wo laghu → guru
#   * baaki → laghu
# JO NAHI KIYA: line ke aakhiri laghu ki chhoot (chhand me wo guru gina ja
# sakta hai), aur half-consonant ke ucchaaran ke apwaad. Isliye report me
# `matra_rule` ka naam jaata hai — number ko "sahi chhand" ka sabooti mat samjho.
_DEVA = 0x0900
_ALIGNED_BASES: Tuple[int, ...] = (0x0980, 0x0A00, 0x0A80, 0x0B00, 0x0B80,
                                   0x0C00, 0x0C80, 0x0D00)
_VIRAMA = "्"
_NASAL_SIGNS = {"ँ", "ं", "ः"}      # candrabindu, anusvara, visarga
_SKIP_SIGNS = {"़", "ऽ", "॑", "॒", "॓", "॔",
               "‌", "‍"}                 # nukta, avagraha, svara, ZW*
_LONG_INDEP = {"आ", "ई", "ऊ", "ऍ", "ए", "ऐ",
               "ऑ", "ओ", "औ", "ॠ", "ॡ"}
_SHORT_INDEP = {"अ", "इ", "उ", "ऋ", "ऌ", "ऎ",
                "ऒ"}
_LONG_MATRA = {"ा", "ी", "ू", "ॄ", "ॅ", "े",
               "ै", "ॉ", "ो", "ौ", "ॣ"}
_SHORT_MATRA = {"ि", "ु", "ृ", "ॆ", "ॊ", "ॢ"}

MATRA_RULE_INDIC = "indic_laghu_guru_basic"
MATRA_RULE_ROMAN = "roman_vowel_approx"


def _fold_to_deva(ch: str) -> str:
    """Bangla/Gurmukhi/Tamil… ko Devanagari ke khaane par le aao.

    Ye scripts ISCII se aayi code-point alignment share karti hain (lang_bridge
    isi par khada hai). Alignment 100% nahi hai — isliye Devanagari ke alawa
    doosri Indic script ka matra number *approx* hai, aur report me rule ka naam
    likha jaata hai.
    """
    point = ord(ch)
    for base in _ALIGNED_BASES:
        if base <= point <= base + 0x7F:
            return chr(_DEVA + (point - base))
    return ch


def _is_deva_consonant(ch: str) -> bool:
    point = ord(ch)
    return (0x0915 <= point <= 0x0939) or (0x0958 <= point <= 0x095F)


@dataclass
class Akshara:
    """Ek akshar (syllable) — onset ke kitne vyanjan, kaunsa swar, weight."""

    text: str = ""
    onset: int = 0
    vowel: str = ""
    has_vowel: bool = False
    nasal: bool = False
    closed: bool = False   # aage virama-wala vyanjan chipka hai
    weight: int = 1


def aksharas(word: str) -> List[Akshara]:
    """Ek Devanagari (ya aligned Indic) shabd ko akshar me todo, weight ke saath.

    Khaali list matlab: is shabd me Indic akshar nahi mila — jhoothi ginti karne
    se accha hai kuch na ginna.
    """
    chars = [_fold_to_deva(c) for c in str(word or "")]
    units: List[Akshara] = []
    cur: Optional[Akshara] = None
    for ch in chars:
        if ch in _SKIP_SIGNS:
            continue
        if ch in _LONG_INDEP or ch in _SHORT_INDEP:
            cur = Akshara(text=ch, vowel=ch, has_vowel=True)
            units.append(cur)
            continue
        if _is_deva_consonant(ch):
            if cur is None or cur.has_vowel:
                cur = Akshara()
                units.append(cur)
            cur.text += ch
            cur.onset += 1
            cur.vowel = "अ"          # inherent swar — matra aaye to badal jaata
            cur.has_vowel = True
            continue
        if ch == _VIRAMA:
            if cur is not None:
                cur.text += ch
                cur.vowel = ""
                cur.has_vowel = False   # abhi swar nahi — cluster chal raha hai
            continue
        if ch in _NASAL_SIGNS:
            if cur is not None:
                cur.text += ch
                cur.nasal = True
            continue
        if ch in _LONG_MATRA or ch in _SHORT_MATRA:
            if cur is not None:
                cur.text += ch
                cur.vowel = ch
                cur.has_vowel = True
            continue
    return _weigh(units)


def _weigh(units: List[Akshara]) -> List[Akshara]:
    """Har akshar ka bhaar (1 ya 2) tay karo — upar likhe chaar niyam se."""
    # Aakhir me lataka hua virama-wala vyanjan (jaise "सत्") apna akshar nahi
    # hai — wo pichhle akshar ko band karta hai (aur usse guru banata hai).
    while units and not units[-1].has_vowel:
        tail = units.pop()
        if units:
            units[-1].text += tail.text
            units[-1].closed = True
    for index, unit in enumerate(units):
        heavy = (unit.vowel in _LONG_MATRA or unit.vowel in _LONG_INDEP
                 or unit.nasal or unit.closed)
        unit.weight = 2 if heavy else 1
        if unit.weight == 1 and index + 1 < len(units):
            if units[index + 1].onset >= 2:
                unit.weight = 2      # sanyukt vyanjan se pehle laghu → guru
    return units


# ── roman/Hinglish ka approx hisaab ──────────────────────────────────────────
# Hinglish me "pyaar" aur "pyar" ek hi shabd hai par spelling se weight badal
# jaata hai. Isliye roman line par jo nikalta hai wo **approx** hai; ye number
# sirf "line-to-line ek jaisa hai ya nahi" ke liye kaam ka hai, "chhand sahi
# hai" ke liye NAHI. Report me rule ka naam (`roman_vowel_approx`) jaata hai.
_ROMAN_VOWEL_RE = re.compile(r"[aeiou]+", re.IGNORECASE)


def _roman_syllables(word: str) -> List[str]:
    """Roman shabd ke swar-guchhe. Angrezi ka chup 'e' nahi ginte ("time")."""
    word = str(word or "")
    found = list(_ROMAN_VOWEL_RE.finditer(word))
    out: List[str] = []
    for index, match in enumerate(found):
        group = match.group(0).lower()
        if index and group == "e" and match.end() == len(word):
            continue
        out.append(group)
    return out


def matra_roman(text: str) -> int:
    """Roman line ka approx matra: do-ya-zyada swar wala guchha 2, warna 1."""
    total = 0
    for word in re.findall(r"[A-Za-z]+", str(text or "")):
        for group in _roman_syllables(word):
            total += 2 if len(group) >= 2 else 1
    return total


def matra_indic(text: str) -> int:
    """Indic line ka matra — laghu/guru jod kar."""
    return sum(unit.weight for word in str(text or "").split()
               for unit in aksharas(word))


def syllables(text: str) -> int:
    """Line me kitne akshar (Indic) ya swar-guchhe (roman) hain."""
    script = lang_bridge.dominant_script(text)
    if script == "latin" or script == "unknown":
        return sum(len(_roman_syllables(w))
                   for w in re.findall(r"[A-Za-z]+", str(text or "")))
    return sum(len(aksharas(word)) for word in str(text or "").split())


def matra_rule_for(text: str) -> str:
    """Is text par kaunsa matra niyam lagega — ya khaali (lag hi nahi sakta)."""
    script = lang_bridge.dominant_script(text)
    if script in ("latin", "unknown"):
        return MATRA_RULE_ROMAN if re.search(r"[A-Za-z]", text or "") else ""
    if script in ("devanagari", "bengali", "gurmukhi", "gujarati", "odia",
                  "tamil", "telugu", "kannada", "malayalam"):
        return MATRA_RULE_INDIC
    return ""      # Arabic/Cyrillic/Han… inka chhand yahan naapa nahi jaata


def matra_of(text: str, rule: str = "") -> int:
    """Line ka matra, diye gaye rule se (rule khaali → khud tay karo)."""
    rule = rule or matra_rule_for(text)
    if rule == MATRA_RULE_INDIC:
        return matra_indic(text)
    if rule == MATRA_RULE_ROMAN:
        return matra_roman(text)
    return 0


# ── line / stanza / tuk ──────────────────────────────────────────────────────
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_EDGE_PUNCT = " \t\"'`.,;:!?—–-…()[]{}«»“”‘’|/\\।॥"


def lines_of(draft: str) -> List[str]:
    """Draft ki wo lines jinme kuch likha hai (bullet/number ka nishaan hata ke)."""
    out: List[str] = []
    for raw in str(draft or "").splitlines():
        line = _BULLET_RE.sub("", raw).strip()
        if line:
            out.append(line)
    return out


def stanzas_of(draft: str) -> List[List[str]]:
    """Khaali line se bante hisse (antara/paragraph)."""
    groups: List[List[str]] = []
    current: List[str] = []
    for raw in str(draft or "").splitlines():
        line = _BULLET_RE.sub("", raw).strip()
        if line:
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _last_word(line: str) -> str:
    parts = [p.strip(_EDGE_PUNCT) for p in str(line or "").split()]
    parts = [p for p in parts if p]
    return parts[-1] if parts else ""


def rhyme_key(line: str, depth: int = 1) -> str:
    """
    Line ke aakhiri shabd ka tuk-hissa: aakhiri swar se aage ka sab.

    "jaan" → "aan", "pehchaan" → "aan" (tuk milti hai), "man" → "an" (nahi
    milti — Hindi me theek yahi hota hai). Devanagari pehle roman hota hai,
    isliye "जान" aur "jaan" ka key ek hi nikalta hai.
    """
    word = _last_word(line)
    if not word:
        return ""
    if lang_bridge.dominant_script(word) not in ("latin", "unknown"):
        word = lang_bridge.roman(word)
    word = re.sub(r"[^A-Za-z]", "", word).lower()
    found = list(_ROMAN_VOWEL_RE.finditer(word))
    if not found:
        return ""
    index = max(0, len(found) - max(1, int(depth)))
    return word[found[index].start():]


def scheme_of(stanza: Sequence[str]) -> str:
    """Ek antara ka tuk-naksha: "aabb", "abab", "aaaa"; "-" = tuk pakdi nahi."""
    seen: Dict[str, str] = {}
    letters = "abcdefghijklmnopqrstuvwxyz"
    out = ""
    for line in stanza:
        key = rhyme_key(line)
        if not key:
            out += "-"
            continue
        if key not in seen:
            seen[key] = letters[len(seen)] if len(seen) < len(letters) else "?"
        out += seen[key]
    return out


def rhyme_coverage(draft: str) -> Tuple[float, List[str]]:
    """
    Kitni line kisi doosri line se tuk milaati hai (0.0–1.0), aur har antara ka
    naksha. Sirf 2+ line wale antare ginte hain — ek line ka tuk kis se milega.
    """
    schemes: List[str] = []
    rhymed = 0
    total = 0
    for stanza in stanzas_of(draft):
        scheme = scheme_of(stanza)
        schemes.append(scheme)
        if len(stanza) < 2:
            continue
        counts: Dict[str, int] = {}
        for mark in scheme:
            if mark != "-":
                counts[mark] = counts.get(mark, 0) + 1
        total += len(stanza)
        rhymed += sum(n for n in counts.values() if n >= 2)
    if not total:
        return 0.0, schemes
    return round(rhymed / total, 4), schemes


def _norm_line(line: str) -> str:
    body = str(line or "").strip(_EDGE_PUNCT).lower()
    return re.sub(r"\s+", " ", body)


def refrain_of(draft: str) -> Dict[str, Any]:
    """
    Sabse zyada dohraayi gayi line (mukhda/hook), aur wo pehli baar kahan aayi.

    `position` = pehli baar aane wali line ka hissa (0.0 = shuruaat). Gaane me
    hook aage hona chahiye — par ye sirf JAGAH ka naap hai, "hook pakdega ya
    nahi" ka nahi.
    """
    lines = lines_of(draft)
    if not lines:
        return {"line": "", "times": 0, "position": 0.0, "total_lines": 0}
    counts: Dict[str, int] = {}
    first: Dict[str, int] = {}
    for index, line in enumerate(lines):
        key = _norm_line(line)
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, index)
    best = max(counts.items(), key=lambda kv: (kv[1], -first[kv[0]]))
    key, times = best
    return {"line": key, "times": times,
            "position": round(first[key] / max(1, len(lines) - 1), 4),
            "total_lines": len(lines)}


# ── ghisi-piti baat (cliché) ─────────────────────────────────────────────────
# YE LIST JAAN-BOOJH KAR CHHOTI HAI AUR ADHOORI HAI. "0 cliché mile" ka matlab
# "likhawat fresh hai" NAHI hota — sirf itna ki in gine-chune ghise phrase me se
# koi nahi mila. Report me ye baat `cliche_list_is_not_exhaustive: True` se
# jaati hai.
CLICHE_LIST_IS_NOT_EXHAUSTIVE = True

CLICHES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("dil ke armaan", ("dil ke armaan", "दिल के अरमान")),
    ("chaand sitare", ("chand sitare", "chaand sitaare", "चाँद सितारे",
                       "चांद सितारे")),
    ("tere bina", ("tere bina", "tere bin", "तेरे बिना", "तेरे बिन")),
    ("dil toot gaya", ("dil toot", "dil tut", "दिल टूट")),
    ("aankhon me aansu", ("aankhon me aansu", "aankhon mein aansu",
                          "आँखों में आँसू", "आंखों में आंसू")),
    ("bewafa sanam", ("bewafa sanam", "बेवफा सनम")),
    ("zindagi ki raah", ("zindagi ki raah", "जिंदगी की राह",
                         "ज़िंदगी की राह")),
    ("sapno ka rajkumar", ("sapno ka rajkumar", "सपनों का राजकुमार")),
    ("broken heart", ("broken heart",)),
    ("tears in my eyes", ("tears in my eyes",)),
    ("light in the darkness", ("light in the darkness",)),
    ("against all odds", ("against all odds",)),
    ("at the end of the day", ("at the end of the day",)),
    ("deep down inside", ("deep down inside",)),
    ("time will tell", ("time will tell",)),
    ("last but not least", ("last but not least",)),
    ("each and every", ("each and every",)),
    ("burning desire", ("burning desire",)),
    ("shining star", ("shining star",)),
    ("journey of a lifetime", ("journey of a lifetime",)),
)


def cliches_in(draft: str) -> List[str]:
    """Kaunse ghise phrase mile — naam se, taaki wajah dikhayi ja sake."""
    plain = re.sub(r"\s+", " ", str(draft or "").lower())
    roman = re.sub(r"\s+", " ", lang_bridge.roman(str(draft or "")).lower())
    found: List[str] = []
    for label, variants in CLICHES:
        for variant in variants:
            needle = variant.lower()
            if needle in plain or needle in roman:
                found.append(label)
                break
    return found


# ── "hit hoga" jaisa daawa — ye ek FAIL hai ─────────────────────────────────
# App khud kabhi ye daawa nahi karta (dekho CANNOT_MEASURE). Agar DRAFT me hi
# aisa daawa aa jaaye to wo bhi jhooth hai, isliye usko naapa jaata hai.
_APPEAL_CLAIM_RE = re.compile(
    r"(viral\s*(?:hoga|hogi|ho\s*jayega|guaranteed)?|chart[\s\-]?buster|"
    r"chart\s*top|blockbuster|superhit|super\s*hit|hit\s*(?:hoga|hogi|guarantee)"
    r"|sabko\s*pasand\s*aayega|everyone\s*will\s*love|guaranteed\s*hit|"
    r"million\s*views|trend\s*(?:karega|karegi)|best\s*song\s*ever|"
    r"वायरल|सुपरहिट|सबको\s*पसंद)", re.IGNORECASE)


def appeal_claims_in(text: str) -> List[str]:
    """Draft me "viral/hit/sabko pasand" jaisa naapa-na-ja-sakne wala daawa."""
    body = str(text or "")
    found = [m.group(0).strip().lower() for m in _APPEAL_CLAIM_RE.finditer(body)]
    out: List[str] = []
    for item in found:
        if item not in out:
            out.append(item)
    return out


# ── mood/bhaav ke cue ───────────────────────────────────────────────────────
# YE LIST BHI ADHOORI HAI (`MOOD_LIST_IS_NOT_EXHAUSTIVE`). Aur sabse zaroori
# baat: mood ka SHABD mil jaana "feeling aa gayi" nahi hota. Check ka naam bhi
# isliye `mood_words_present` hai, `mood_achieved` nahi.
MOOD_LIST_IS_NOT_EXHAUSTIVE = True

MOODS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("dukh", ("dukh", "dukhi", "sad", "gham", "gam", "udaas", "दुख", "दुःख",
              "दुखी", "उदास", "ग़म")),
    ("khushi", ("khushi", "khush", "happy", "joy", "खुशी", "खुश")),
    ("pyaar", ("pyaar", "pyar", "prem", "ishq", "love", "mohabbat", "प्यार",
               "प्रेम", "इश्क", "मोहब्बत")),
    ("judaai", ("judaai", "juda", "bichhad", "separation", "breakup",
                "जुदाई", "बिछड़")),
    ("gussa", ("gussa", "krodh", "anger", "angry", "गुस्सा", "क्रोध")),
    ("dar", ("dar", "bhay", "fear", "afraid", "डर", "भय")),
    ("umeed", ("umeed", "aasha", "hope", "hopeful", "उम्मीद", "आशा")),
    ("tanhai", ("tanhai", "akela", "akelapan", "lonely", "loneliness",
                "तनहाई", "अकेला", "अकेलापन")),
    ("yaad", ("yaad", "nostalgia", "memories", "याद", "यादें")),
    ("himmat", ("himmat", "hausla", "courage", "motivation", "josh", "हिम्मत",
                "हौसला", "जोश")),
    ("shanti", ("shanti", "sukoon", "peace", "calm", "शांति", "सुकून")),
    ("maa", ("maa", "mother", "ammi", "माँ", "मां")),
    ("dosti", ("dosti", "friendship", "yaari", "दोस्ती", "यारी")),
    ("desh", ("desh", "deshbhakti", "patriotic", "vatan", "देश",
              "देशभक्ति", "वतन")),
    ("bhakti", ("bhakti", "bhajan", "devotional", "ishwar", "bhagwan",
                "भक्ति", "भजन", "भगवान")),
    ("hasi", ("hasi", "funny", "comedy", "majak", "mazak", "हँसी", "मज़ाक")),
)


def _cue_present(needle: str, *haystacks: str) -> bool:
    """
    Shabd maujood hai ya nahi — seema ke saath.

    Chhote needle (3 ya kam akshar) exact milte hain, warna "maa" ko
    "maatraa" ke andar mil jaata tha aur sawaal me maa ka gaana ban jaata tha.
    Lambe needle par 3 akshar tak ka suffix chalta hai, taaki "yaad" → "yaadein"
    aur "dukh" → "dukhi" jaisi Hinglish shakal na chhoote.
    """
    core = re.escape(needle)
    tail = r"[a-zऀ-ॿ]{0,3}" if len(needle) >= 4 else ""
    pattern = re.compile(r"(?<!\w)" + core + tail + r"(?!\w)", re.IGNORECASE)
    return any(pattern.search(h or "") for h in haystacks)


def mood_hints(text: str) -> List[str]:
    """Text me kaunse bhaav ke shabd mile (naam se — adhoori list se)."""
    plain = re.sub(r"\s+", " ", str(text or "").lower())
    roman = re.sub(r"\s+", " ", lang_bridge.roman(str(text or "")).lower())
    out: List[str] = []
    for label, variants in MOODS:
        for variant in variants:
            if _cue_present(variant.lower(), plain, roman):
                out.append(label)
                break
    return out


# ── SPEC: banane se PEHLE tay karo ki kya naapa jayega ──────────────────────
_RHYME_OFF_RE = re.compile(
    r"(bina\s*tuk|tuk\s*(?:ke\s*)?bina|bina\s*tukbandi|no\s*rhyme|"
    r"without\s*rhyme|non[\s\-]?rhym|free\s*verse|blank\s*verse|"
    r"बिना\s*तुक|तुक\s*के\s*बिना)", re.IGNORECASE)
_RHYME_ON_RE = re.compile(
    r"(tuk\b|tukbandi|tukband|rhyme|rhyming|qaafiya|qafiya|kafiya|"
    r"तुक|तुकबंदी|क़ाफ़िया|काफिया)", re.IGNORECASE)

_UNIT_LINE = (r"line|lines|pankti|panktiyan|panktiyaan|panktiyon|pnkti|"
              r"पंक्ति|पंक्तियाँ|पंक्तियां|पंक्तियों")
_UNIT_STANZA = (r"antara|antaraa|antare|antre|antron|antraa|stanza|stanzas|"
                r"verse|verses|sher|paragraph|para|अंतरा|अंतरे|छंद|पैराग्राफ")
_UNIT_MATRA = (r"matra|maatra|matraa|maatraa|matrayen|maatraayen|beats|"
               r"मात्रा|मात्राएँ|मात्राएं")
_UNIT_WORD = r"word|words|shabd|shabdon|shabdo|शब्द|शब्दों"


@dataclass
class Spec:
    """Kya banana hai — aur us par kaunsa naap chalega. Sab explicit."""

    form: str = ""
    label: str = ""
    verse: bool = False
    target_script: str = ""      # khaali = script check chalega hi nahi
    line_target: int = 0
    stanza_target: int = 0
    matra_target: int = 0
    word_target: int = 0
    min_lines: int = 0
    min_words: int = 0
    rhyme_required: bool = False
    hook_required: bool = False
    mood_asked: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "form": self.form, "label": self.label, "verse": self.verse,
            "target_script": self.target_script,
            "line_target": self.line_target,
            "stanza_target": self.stanza_target,
            "matra_target": self.matra_target,
            "word_target": self.word_target,
            "min_lines": self.min_lines, "min_words": self.min_words,
            "rhyme_required": self.rhyme_required,
            "hook_required": self.hook_required,
            "mood_asked": list(self.mood_asked),
            "notes": list(self.notes),
            # Ye do line kabhi badalti nahi: SPEC banane ka matlab ye nahi ki
            # draft acha hoga, aur naap "pasand aayega" nahi bolta.
            "quality_claim": False,
            "appeal_claim": False,
        }


def build_spec(question: str, detection: Optional[Dict[str, Any]] = None,
               form: Optional[Form] = None) -> Optional[Spec]:
    """
    Sawaal se SPEC banao — sirf jo SAAF maanga gaya ho.

    "shayad 8 line chahta hoga" wala andaza nahi lagate (requested.py ka wahi
    niyam). Jo user ne nahi bataya, uska target 0 rehta hai aur us par check
    `NOT_MEASURED` jaata hai — chuppi ko "sab theek" nahi padha jaana chahiye.
    """
    found = detection if detection is not None else detect(question)
    if not found.get("is_request"):
        return None
    picked = form
    if picked is None:
        for candidate in FORMS:
            if candidate.form_id == found.get("form"):
                picked = candidate
                break
    if picked is None:
        return None

    text = str(question or "")
    roman = lang_bridge.roman(text)
    spec = Spec(form=picked.form_id, label=picked.label, verse=picked.verse,
                min_lines=picked.min_lines, min_words=picked.min_words)

    spec.line_target = _count_near(text, _UNIT_LINE)
    spec.stanza_target = _count_near(text, _UNIT_STANZA)
    spec.matra_target = _count_near(text, _UNIT_MATRA)
    spec.word_target = _count_near(text, _UNIT_WORD)

    # tuk: form ka default, par user ki baat upar hai (mana karna bhi ginta hai)
    spec.rhyme_required = picked.rhyme_default
    if _RHYME_OFF_RE.search(text) or _RHYME_OFF_RE.search(roman):
        spec.rhyme_required = False
        spec.notes.append("User ne tuk se mana kiya — tuk ka check band.")
    elif _RHYME_ON_RE.search(text) or _RHYME_ON_RE.search(roman):
        spec.rhyme_required = True
    spec.hook_required = picked.hook_default

    # script: sirf tab naapenge jab sawaal khud kisi non-latin script me ho.
    # "hindi me likho" roman me likha ho to user Devanagari maang raha hai ya
    # Hinglish — ye pata nahi, aur andaza laga kar draft ko fail karna galat hai.
    script = lang_bridge.dominant_script(text)
    if script not in ("latin", "unknown"):
        spec.target_script = script
    else:
        spec.notes.append("Sawaal roman me hai, isliye script ka check nahi "
                          "chalega (Devanagari ya Hinglish — dono chal sakte).")

    spec.mood_asked = mood_hints(text)
    if not spec.mood_asked:
        spec.notes.append("User ne mood/bhaav naam se nahi bataya — mood ka "
                          "check nahi chalega.")
    if spec.line_target and spec.line_target < picked.min_lines:
        spec.notes.append("User ki gini hui line form ke default se kam hai — "
                          "user ki ginti hi maani gayi.")
    return spec


# ── naap ki haden (ek jagah, taaki badalna aur test karna aasaan ho) ────────
MATRA_TARGET_TOLERANCE = 2      # user ne 16 maanga to 14–18 chalega
MATRA_SPREAD_MAX_INDIC = 4      # ek antare me line-to-line farak
MATRA_SPREAD_MAX_ROMAN = 6      # roman approx hai, isliye dhili had
MIN_RHYME_COVERAGE = 0.5        # aadhi line kisi se tuk milaaye
MAX_HOOK_POSITION = 0.5         # mukhda pehle aadhe hisse me aa jaaye
MIN_UNIQUE_WORD_RATIO = 0.25    # isse neeche = ek hi baat baar baar
MAX_CLICHE_PER_100_WORDS = 1.0
MAX_CLICHES = 2
WORD_TARGET_TOLERANCE = 0.2     # 150 word maanga to 120–180


@dataclass
class Check:
    """Ek naap ka nateeja — number, target, aur wajah, teeno saath."""

    check: str
    status: str
    measured: Any = ""
    target: Any = ""
    reason: str = ""
    note: str = ""
    approx: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check, "status": self.status,
            "measured": self.measured, "target": self.target,
            "reason": self.reason, "note": self.note, "approx": self.approx,
            # Har check ke saath ye do line jaati hain: naap "acha hai" ka
            # sabooti nahi, aur asli sunne/padhne wale ka test baaki hai.
            "quality_proven": False,
            "human_reaction_untested": True,
        }


def _check(name: str, status: str, **kwargs: Any) -> Check:
    """Ek hi darwaza — status galat ho to yahin pakda jaayega."""
    assert status in CHECK_STATUSES, status
    return Check(check=name, status=status, **kwargs)


def _skip(name: str, reason: str, note: str) -> Check:
    return _check(name, NOT_MEASURED, reason=reason, note=note)


def _words(text: str) -> List[str]:
    """Draft ke shabd — kisi bhi script ke (punctuation hata kar)."""
    return [w for w in re.split(r"[\s।॥]+", str(text or ""))
            if w.strip(_EDGE_PUNCT)]


def draft_facts(draft: str) -> Dict[str, Any]:
    """
    Draft ke saare kachche number ek jagah — checks isi par chalte hain.

    Ek hi jagah se number nikaalne ka fayda: report me jo number dikhta hai wahi
    check ne bhi use kiya. Do jagah alag-alag hisaab = do alag sach.
    """
    lines = lines_of(draft)
    stanzas = stanzas_of(draft)
    rule = matra_rule_for(draft)
    per_line = [matra_of(line, rule) for line in lines] if rule else []
    coverage, schemes = rhyme_coverage(draft)
    words = _words(draft)
    roman_tokens: List[str] = []
    try:
        roman_tokens = [t for t in lang_bridge.roman_tokens(draft) if t]
    except Exception:
        roman_tokens = [w.lower() for w in words]
    unique_ratio = (round(len(set(roman_tokens)) / len(roman_tokens), 4)
                    if roman_tokens else 0.0)
    return {
        "lines": lines,
        "line_count": len(lines),
        "stanza_count": len(stanzas),
        "word_count": len(words),
        "matra_rule": rule,
        "matra_per_line": per_line,
        "matra_spread": (max(per_line) - min(per_line)) if per_line else 0,
        "rhyme_coverage": coverage,
        "rhyme_schemes": schemes,
        "refrain": refrain_of(draft),
        "unique_word_ratio": unique_ratio,
        "cliches": cliches_in(draft),
        "appeal_claims": appeal_claims_in(draft),
        "script": lang_bridge.dominant_script(draft),
        "moods": mood_hints(draft),
    }


# ── ek-ek check ─────────────────────────────────────────────────────────────
def _check_line_count(spec: Spec, facts: Dict[str, Any]) -> Check:
    got = facts["line_count"]
    if spec.line_target:
        ok = got == spec.line_target
        return _check("line_count", MET if ok else NOT_MET, measured=got,
                      target=spec.line_target,
                      reason="" if ok else "line_count_off",
                      note=("Line ginti maang ke barabar hai." if ok else
                            f"{spec.line_target} line maangi thi, {got} mili."))
    if spec.min_lines:
        ok = got >= spec.min_lines
        return _check("line_count", MET if ok else NOT_MET, measured=got,
                      target=f">={spec.min_lines}",
                      reason="" if ok else "too_few_lines",
                      note=("Itni line kaafi hain." if ok else
                            f"Kam se kam {spec.min_lines} line chahiye thi, "
                            f"{got} mili."))
    return _skip("line_count", "no_line_target",
                 "User ne line ki ginti nahi maangi, form ka default bhi nahi.")


def _check_stanza_count(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.stanza_target:
        return _skip("stanza_count", "no_stanza_target",
                     "Antara/paragraph ki ginti maangi hi nahi gayi.")
    got = facts["stanza_count"]
    ok = got == spec.stanza_target
    return _check("stanza_count", MET if ok else NOT_MET, measured=got,
                  target=spec.stanza_target,
                  reason="" if ok else "stanza_count_off",
                  note=("Antare ki ginti theek hai." if ok else
                        f"{spec.stanza_target} antare maange the, {got} mile."))


def _check_word_count(spec: Spec, facts: Dict[str, Any]) -> Check:
    got = facts["word_count"]
    if spec.word_target:
        slack = max(1, int(round(spec.word_target * WORD_TARGET_TOLERANCE)))
        low, high = spec.word_target - slack, spec.word_target + slack
        ok = low <= got <= high
        return _check("word_count", MET if ok else NOT_MET, measured=got,
                      target=f"{spec.word_target} (±{slack})",
                      reason="" if ok else "word_count_off",
                      note=("Shabd ginti maang ke daayre me hai." if ok else
                            f"{spec.word_target} shabd maange the, {got} mile."))
    if spec.min_words:
        ok = got >= spec.min_words
        return _check("word_count", MET if ok else NOT_MET, measured=got,
                      target=f">={spec.min_words}",
                      reason="" if ok else "too_few_words",
                      note=("Lambaai kaafi hai." if ok else
                            f"Is kism ke liye kam se kam {spec.min_words} "
                            f"shabd chahiye, {got} mile."))
    return _skip("word_count", "no_word_target",
                 "Shabd ginti maangi hi nahi gayi.")


def _check_matra_target(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.matra_target:
        return _skip("matra_target", "no_matra_target",
                     "User ne matra ki ginti nahi bataayi — sirf line-to-line "
                     "ek jaisi hai ya nahi, wahi naapa gaya.")
    per_line = facts["matra_per_line"]
    if not per_line:
        return _skip("matra_target", "matra_rule_unavailable",
                     "Is script par matra ka niyam yahan nahi lagta.")
    off = [i + 1 for i, value in enumerate(per_line)
           if abs(value - spec.matra_target) > MATRA_TARGET_TOLERANCE]
    ok = not off
    return _check("matra_target", MET if ok else NOT_MET,
                  measured=per_line, target=spec.matra_target,
                  approx=facts["matra_rule"] == MATRA_RULE_ROMAN,
                  reason="" if ok else "matra_off_target",
                  note=("Har line matra ke daayre me hai "
                        f"(±{MATRA_TARGET_TOLERANCE})." if ok else
                        f"Line {off} ki matra {spec.matra_target} se "
                        f"{MATRA_TARGET_TOLERANCE} se zyada hat gayi."))


def _check_matra_consistency(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.verse:
        return _skip("matra_consistency", "not_verse_form",
                     "Ye line-by-line likhawat nahi hai, isliye matra ka "
                     "hisaab nahi chala.")
    per_line = facts["matra_per_line"]
    if len(per_line) < 2:
        return _skip("matra_consistency", "matra_rule_unavailable",
                     "Do se kam line, ya is script par matra ka niyam nahi "
                     "lagta — farak naapa hi nahi ja sakta.")
    roman = facts["matra_rule"] == MATRA_RULE_ROMAN
    limit = MATRA_SPREAD_MAX_ROMAN if roman else MATRA_SPREAD_MAX_INDIC
    spread = facts["matra_spread"]
    ok = spread <= limit
    return _check("matra_consistency", MET if ok else NOT_MET,
                  measured=spread, target=f"<={limit}", approx=roman,
                  reason="" if ok else "matra_spread_wide",
                  note=("Line-to-line matra ka farak had ke andar hai."
                        if ok else
                        f"Sabse chhoti aur sabse badi line me {spread} matra "
                        f"ka farak hai (had {limit}) — gaate waqt latakna "
                        f"padega."))


def _check_rhyme(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.rhyme_required:
        return _skip("rhyme", "rhyme_not_required",
                     "Is farmaish me tuk zaroori nahi thi.")
    if facts["line_count"] < 2:
        return _skip("rhyme", "too_few_lines_for_rhyme",
                     "Ek line me tuk kis se milegi.")
    coverage = facts["rhyme_coverage"]
    ok = coverage >= MIN_RHYME_COVERAGE
    naksha = "/".join(facts["rhyme_schemes"])
    if ok:
        note = f"Tuk milti hai — naksha: {naksha}"
    else:
        note = (f"Sirf {int(coverage * 100)}% line kisi doosri line se tuk "
                f"milaati hai (naksha: {naksha}).")
    return _check("rhyme", MET if ok else NOT_MET, measured=coverage,
                  target=f">={MIN_RHYME_COVERAGE}",
                  reason="" if ok else "rhyme_coverage_low", note=note)


def _check_refrain(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.hook_required:
        return _skip("refrain_hook", "hook_not_required",
                     "Is kism me dohraaya jaane wala mukhda zaroori nahi.")
    if facts["line_count"] < 4:
        return _skip("refrain_hook", "too_few_lines_for_hook",
                     "Char se kam line me mukhda-antara ka farak nahi banta.")
    refrain = facts["refrain"]
    times = int(refrain.get("times") or 0)
    position = float(refrain.get("position") or 0.0)
    if times < 2:
        return _check("refrain_hook", NOT_MET, measured="0 dohraav",
                      target=">=2 baar, pehle aadhe hisse me",
                      reason="no_repeated_line",
                      note="Koi line dohraayi hi nahi gayi — gaane me mukhda "
                           "wahi hota hai jo laut kar aata hai.")
    ok = position <= MAX_HOOK_POSITION
    return _check("refrain_hook", MET if ok else NOT_MET,
                  measured=f"{times} baar, position {position}",
                  target=f">=2 baar, position <={MAX_HOOK_POSITION}",
                  reason="" if ok else "hook_too_late",
                  note=("Mukhda hai aur shuru me hi aa jaata hai." if ok else
                        "Dohraayi jaane wali line bahut baad me pehli baar "
                        "aati hai — mukhda aage laana padega."))


def _check_over_repetition(spec: Spec, facts: Dict[str, Any]) -> Check:
    ratio = facts["unique_word_ratio"]
    if not ratio:
        return _skip("over_repetition", "no_words",
                     "Shabd hi nahi mile — dohraav naapa nahi ja sakta.")
    ok = ratio >= MIN_UNIQUE_WORD_RATIO
    return _check("over_repetition", MET if ok else NOT_MET, measured=ratio,
                  target=f">={MIN_UNIQUE_WORD_RATIO}",
                  reason="" if ok else "unique_word_ratio_low",
                  note=("Dohraav had ke andar hai (gaane me dohraav bura nahi "
                        "hota)." if ok else
                        "Poora draft ek hi baat ke dohraav par khada hai — "
                        "naye shabd chahiye."))


def _check_cliche(spec: Spec, facts: Dict[str, Any]) -> Check:
    found = facts["cliches"]
    words = facts["word_count"]
    if not words:
        return _skip("cliche_density", "no_words",
                     "Shabd hi nahi mile.")
    per_100 = round(len(found) * 100.0 / words, 3)
    ok = len(found) <= MAX_CLICHES and per_100 <= MAX_CLICHE_PER_100_WORDS
    note = ("Is chhoti list ka koi ghisa phrase nahi mila — iska matlab "
            "\"bilkul fresh hai\" NAHI hai." if not found else
            "Ghise phrase mile: " + ", ".join(found) + ".")
    return _check("cliche_density", MET if ok else NOT_MET,
                  measured=f"{len(found)} ({per_100}/100 shabd)",
                  target=f"<={MAX_CLICHES} aur <={MAX_CLICHE_PER_100_WORDS}"
                         f"/100 shabd",
                  reason="" if ok else "cliche_heavy", note=note)


def _check_script(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.target_script:
        return _skip("script_match", "no_script_target",
                     "Sawaal roman me tha — script ka target hi nahi bana.")
    got = facts["script"]
    ok = got == spec.target_script
    return _check("script_match", MET if ok else NOT_MET, measured=got,
                  target=spec.target_script,
                  reason="" if ok else "script_mismatch",
                  note=("Jis script me sawaal tha, usi me jawab hai." if ok
                        else f"Sawaal {spec.target_script} me tha par draft "
                             f"{got} me hai."))


def _check_appeal_claim(spec: Spec, facts: Dict[str, Any]) -> Check:
    claims = facts["appeal_claims"]
    ok = not claims
    return _check("no_appeal_claim", MET if ok else NOT_MET,
                  measured=", ".join(claims) if claims else "koi nahi",
                  target="koi nahi",
                  reason="" if ok else "unsupported_appeal_claim",
                  note=("Draft khud koi \"hit/viral\" wala daawa nahi karta."
                        if ok else
                        "Draft me \"hit/viral/sabko pasand\" jaisa daawa hai — "
                        "ye naapa hi nahi ja sakta, isliye hata do."))


def _check_mood_words(spec: Spec, facts: Dict[str, Any]) -> Check:
    if not spec.mood_asked:
        return _skip("mood_words_present", "no_mood_asked",
                     "User ne bhaav naam se nahi maanga.")
    got = facts["moods"]
    hit = [m for m in spec.mood_asked if m in got]
    ok = bool(hit)
    return _check("mood_words_present", MET if ok else NOT_MET,
                  measured=", ".join(got) if got else "koi nahi",
                  target=", ".join(spec.mood_asked),
                  reason="" if ok else "mood_words_missing",
                  note=("Maange gaye bhaav ke shabd draft me hain. Dhyaan do: "
                        "shabd milna \"feeling aa gayi\" nahi hota — wo naapa "
                        "hi nahi ja sakta." if ok else
                        "Jo bhaav maanga tha, uske shabd draft me nahi mile."))


# Kram maayne rakhta hai: report isi kram me chhapti hai.
CHECKS: Tuple[Tuple[str, Callable[[Spec, Dict[str, Any]], Check]], ...] = (
    ("line_count", _check_line_count),
    ("stanza_count", _check_stanza_count),
    ("word_count", _check_word_count),
    ("matra_target", _check_matra_target),
    ("matra_consistency", _check_matra_consistency),
    ("rhyme", _check_rhyme),
    ("refrain_hook", _check_refrain),
    ("over_repetition", _check_over_repetition),
    ("cliche_density", _check_cliche),
    ("script_match", _check_script),
    ("no_appeal_claim", _check_appeal_claim),
    ("mood_words_present", _check_mood_words),
)


def measure(draft: str, spec: Optional[Spec]) -> Dict[str, Any]:
    """
    Draft par saare check chalao — fail-closed.

    Koi check andar se toot jaaye to wo `NOT_MEASURED` hota hai, `MET` kabhi
    nahi. "Naap chala hi nahi" aur "naap pass ho gaya" ek nahi hain.
    """
    if spec is None:
        return {"status": NOT_RUN, "checks": [], "measured": {},
                "note": "Farmaish jaisi koi baat nahi mili — CRAFT chala hi "
                        "nahi."}
    body = str(draft or "").strip()
    if not body:
        return {"status": NO_DRAFT, "checks": [], "measured": {},
                "note": "Naapne ke liye draft hi nahi mila."}
    facts = draft_facts(body)
    checks: List[Check] = []
    for name, runner in CHECKS:
        try:
            result = runner(spec, facts)
        except Exception:
            result = _skip(name, "check_error",
                           "Ye naap andar ki galti se chal nahi paaya — isliye "
                           "is par kuch bhi nahi kaha ja sakta.")
        checks.append(result)
    counts = {status: sum(1 for c in checks if c.status == status)
              for status in CHECK_STATUSES}
    if counts[NOT_MET]:
        status = DRAFT_WEAK
    elif counts[MET]:
        status = DRAFT_OK
    else:
        status = DRAFT_UNMEASURED
    return {
        "status": status,
        "checks": [c.to_dict() for c in checks],
        "counts": counts,
        "measured": {
            "lines": facts["line_count"],
            "stanzas": facts["stanza_count"],
            "words": facts["word_count"],
            "matra_rule": facts["matra_rule"],
            "matra_per_line": facts["matra_per_line"],
            "matra_spread": facts["matra_spread"],
            "rhyme_coverage": facts["rhyme_coverage"],
            "rhyme_schemes": facts["rhyme_schemes"],
            "refrain_times": facts["refrain"].get("times"),
            "refrain_position": facts["refrain"].get("position"),
            "unique_word_ratio": facts["unique_word_ratio"],
            "cliches": facts["cliches"],
            "script": facts["script"],
            "moods_in_draft": facts["moods"],
        },
        "note": "",
    }


# ── draft kahan hai ─────────────────────────────────────────────────────────
DRAFT_FENCE = "rv-draft"

DRAFT_INSTRUCTION = (
    "AGAR ye farmaish kuch BANANE ki hai (gaana/kavita/letter/kahani/nibandh/"
    "slogan), to us likhawat ko theek is tarah alag block me do:\n"
    "```" + DRAFT_FENCE + "\n<sirf wahi likhawat, koi explanation nahi>\n```\n"
    "Block ke bahar apni baat kaho. Block ke andar \"hit hoga\", \"viral "
    "hoga\", \"sabko pasand aayega\" jaisa koi daawa MAT likho — ye naapa hi "
    "nahi ja sakta."
)

_FENCE_RE = re.compile(r"```[ \t]*" + DRAFT_FENCE +
                       r"[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*[ \t]*\r?\n(.*?)```", re.DOTALL)


def extract_draft(text: str, spec: Optional[Spec] = None) -> Tuple[str, str]:
    """
    Jawab me se sirf DRAFT nikaalo (draft, source) ke roop me.

    Pehli pasand: `rv-draft` wala marked block — usme koi shak nahi rehta.
    Doosri: koi bhi fenced block. Teesri (sirf line-wali kism par): jawab ka wo
    hissa jo verse jaisa dikhta hai.

    Naapne ke liye AUDIT/explanation ka text uthana sabse bada khatra hai —
    tab number sahi hota hai par kisi galat cheez ka. Isliye jab kuch pakka na
    mile to khaali lauta dete hain aur report me "draft nahi mila" likhte hain.
    """
    body = str(text or "")
    match = _FENCE_RE.search(body)
    if match and match.group(1).strip():
        return match.group(1).strip("\r\n"), "marked_block"
    other = _ANY_FENCE_RE.search(body)
    if other and other.group(1).strip():
        return other.group(1).strip("\r\n"), "code_block"
    if spec is not None and spec.verse:
        guess = _verse_block(body)
        if guess:
            return guess, "verse_shape_guess"
    return "", ""


_VERSE_MIN_RUN = 3
_VERSE_MAX_LINE_CHARS = 70
_NOT_VERSE_RE = re.compile(r"^\s*(?:#{1,6}\s|>|\||\d{1,2}[.)]\s|[-*•]\s|\*\*|"
                           r"https?://|Sources\b|VERIFIED\b|PARTIAL\b)")


def _verse_block(text: str) -> str:
    """
    Jawab me verse jaisa dikhne wala sabse lamba hissa.

    Ye ANDAAZA hai, isliye source `verse_shape_guess` likha jaata hai aur report
    me saaf bola jaata hai ki draft marked block me nahi tha. Heading, bullet,
    quote, link aur status shabd (VERIFIED/PARTIAL) wali line verse nahi maani
    jaati — warna audit ka text hi naapa jaane lagta hai.
    """
    best: List[str] = []
    current: List[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        ok = (line and len(line) <= _VERSE_MAX_LINE_CHARS
              and not _NOT_VERSE_RE.match(raw))
        if ok:
            current.append(line)
            continue
        if len(current) > len(best):
            best = current
        current = []
    if len(current) > len(best):
        best = current
    if len(best) < _VERSE_MIN_RUN:
        return ""
    return "\n".join(best)


# ── reject + dobara likhwana (ek hi round, bounded) ─────────────────────────
MAX_REVISION_ROUNDS = 1


def revision_notes(measured: Optional[Dict[str, Any]]) -> List[str]:
    """Jo check pass nahi hua, uski naapi hui wajah — yahi reject-list hai."""
    out: List[str] = []
    for check in (measured or {}).get("checks", []) or []:
        if check.get("status") != NOT_MET:
            continue
        out.append(f"{check.get('check')}: {check.get('note')} "
                   f"(naapa: {check.get('measured')}, "
                   f"chahiye: {check.get('target')})")
    return out


def revision_prompt_block(spec: Optional[Spec],
                          measured: Optional[Dict[str, Any]]) -> str:
    """
    Dobara likhne ke liye seedha, naapa hua feedback.

    Isme koi "acha likho" jaisi khaali baat nahi hai — sirf wahi baat jo naapi
    ja chuki hai, number ke saath. Jo cheez naapi nahi ja sakti (pasand, viral)
    uska zikr yahan bhi nahi hota.
    """
    notes = revision_notes(measured)
    if spec is None or not notes:
        return ""
    lines = ["DOBARA LIKHO — pehle draft ka naap poora nahi utra.", ""]
    lines.append("Kya banana hai: " + spec.label)
    if spec.line_target:
        lines.append(f"Line: theek {spec.line_target}")
    elif spec.min_lines:
        lines.append(f"Line: kam se kam {spec.min_lines}")
    if spec.matra_target:
        lines.append(f"Matra per line: {spec.matra_target} "
                     f"(±{MATRA_TARGET_TOLERANCE})")
    if spec.word_target:
        lines.append(f"Shabd: lagbhag {spec.word_target}")
    lines.append("Tuk: " + ("chahiye" if spec.rhyme_required else "zaroori nahi"))
    if spec.hook_required:
        lines.append("Mukhda: ek line laut kar aaye, aur shuru ke aadhe hisse "
                     "me pehli baar aaye")
    if spec.target_script:
        lines.append("Script: " + spec.target_script)
    if spec.mood_asked:
        lines.append("Bhaav: " + ", ".join(spec.mood_asked))
    lines.append("")
    lines.append("Naap me ye cheezein pass nahi hui:")
    for note in notes:
        lines.append("- " + note)
    lines.append("")
    lines.append("Sirf naya draft bhejo, isi shakal me (koi explanation nahi):")
    lines.append("```" + DRAFT_FENCE)
    lines.append("<naya draft>")
    lines.append("```")
    return "\n".join(lines)


# ── policy: is stage me kya hota hi nahi ────────────────────────────────────
@dataclass(frozen=True)
class CraftPolicy:
    """
    Naap kaise hui, iska pakka record.

    Har number is file ke andar, offline, bina kisi model ke banta hai. Isliye
    ye teen jhoot yahan structurally mumkin nahi: (1) "internet se check kiya",
    (2) "random tha isliye agli baar badal jaayega", (3) "model ne code likha
    aur humne chala diya".
    """
    network_used: bool = False
    randomness_used: bool = False
    model_written_code_executed: bool = False
    deterministic: bool = True
    provider_cost: str = "₹0"
    revision_rounds_max: int = MAX_REVISION_ROUNDS
    measured_by: str = "offline_rules_in_craft_py"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "network_used": self.network_used,
            "randomness_used": self.randomness_used,
            "model_written_code_executed": self.model_written_code_executed,
            "deterministic": self.deterministic,
            "provider_cost": self.provider_cost,
            "revision_rounds_max": self.revision_rounds_max,
            "measured_by": self.measured_by,
            "structure_only": True,
            "quality_proven": False,
            "human_reaction_untested": True,
        }


POLICY = CraftPolicy()


def _score(measured: Optional[Dict[str, Any]]) -> Tuple[int, int]:
    """(kitne fail, kitne pass-nahi-hue) — chhota behtar."""
    counts = (measured or {}).get("counts") or {}
    return (int(counts.get(NOT_MET, 0)), -int(counts.get(MET, 0)))


def _unmeasured_count(measured: Optional[Dict[str, Any]]) -> int:
    counts = (measured or {}).get("counts") or {}
    return int(counts.get(NOT_MEASURED, 0))


def _revision_is_better(new_measured: Optional[Dict[str, Any]],
                        old_measured: Optional[Dict[str, Any]]) -> bool:
    """
    Naya draft sirf tab rakha jaata hai jab NAAP me sach me behtar ho.

    Barabari par purana hi rehta hai. "Dobara likha isliye acha ho gaya" ek
    aasaan jhoot hai — usse bachne ke liye faisla sirf gini hui failures par
    hota hai, na ki is baat par ki revision hui thi ya nahi.

    Ek aur chori yahan bandh hai: draft ko chhota/adhoora kar dene se kuch check
    naapne laayak hi nahi rehte (NOT_MEASURED badh jaata hai) aur fail ki ginti
    khud-b-khud gir jaati hai. Isliye pehle ye dekha jaata hai ki naye draft par
    NAAP kam nahi hui — warna ye "behtar" nahi, sirf chhup jaana hai.
    """
    if not new_measured:
        return False
    if new_measured.get("status") not in (DRAFT_OK, DRAFT_WEAK,
                                          DRAFT_UNMEASURED):
        return False
    if _unmeasured_count(new_measured) > _unmeasured_count(old_measured):
        return False
    return _score(new_measured) < _score(old_measured)



def _warnings(spec: Optional[Spec], draft_source: str,
              measured: Optional[Dict[str, Any]]) -> List[str]:
    """Naap ke saath jo sach hamesha jaana chahiye."""
    out: List[str] = []
    if draft_source == "verse_shape_guess":
        out.append("Draft alag block me nahi tha — jawab me se shakal dekh kar "
                   "andaza lagaya gaya, isliye naap galat hisse par bhi ho "
                   "sakti hai.")
    if (measured or {}).get("measured", {}).get("matra_rule") == MATRA_RULE_ROMAN:
        out.append("Matra roman (Hinglish) akshar par gini gayi hai — ye "
                   "approx hai, sahi chhand ka saboot nahi.")
    if CLICHE_LIST_IS_NOT_EXHAUSTIVE:
        out.append("Ghise-pite shabd ki list poori nahi hai — 0 mila to iska "
                   "matlab \"naya hai\" nahi hota.")
    if MOOD_LIST_IS_NOT_EXHAUSTIVE:
        out.append("Bhaav sirf shabd dekh kar ginte hain — shabd hone ka matlab "
                   "bhaav aa gaya nahi hota.")
    return out


def _empty_report(reason: str, note: str) -> Dict[str, Any]:
    """CRAFT chala hi nahi — aur ye baat dabai nahi jaati."""
    return {
        "ran": False,
        "status": NOT_RUN,
        "reason": reason,
        "spec": {},
        "draft_found": False,
        "draft_source": "",
        "final_draft": "",
        "checks": [],
        "measured": {},
        "revision": {"attempted": False, "ran": False, "rounds": 0,
                     "kept": "", "notes": [], "reason": "stage_not_run"},
        "gemini_calls": 0,
        "provider_cost": POLICY.provider_cost,
        "policy": POLICY.to_dict(),
        "cannot_measure": list(CANNOT_MEASURE),
        "disclaimer": CRAFT_DISCLAIMER,
        "warnings": [],
        "note": note,
    }


def run_craft(question: str, answer_text: str,
              reviser: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """
    Poora CRAFT stage: farmaish pehchaano → SPEC → draft dhoondo → naapo →
    (zaroorat par) ek baar dobara likhwao → sach ke saath lauta do.

    `reviser` caller deta hai (bounded, ek hi call). Nahi diya to report me
    saaf likha jaata hai ki dobara likhwaya hi nahi gaya — "revision ki zarurat
    nahi thi" aur "revision ho hi nahi paayi" alag alag baat hai.

    Ye function khud kabhi model ko call nahi karta, network nahi chhoota, aur
    kisi bhi haal me ye nahi kehta ki likhawat acchi hai ya logon ko pasand
    aayegi.
    """
    detection = detect(question)
    if not detection.get("is_request"):
        return _empty_report(
            str(detection.get("reason") or "not_a_craft_request"),
            "Ye kuch banane ki farmaish nahi lagi, isliye CRAFT ka naap chala "
            "hi nahi.")
    spec = build_spec(question, detection=detection)
    if spec is None:
        return _empty_report("no_spec",
                             "Farmaish se koi naapne laayak SPEC nahi bana.")

    draft, source = extract_draft(answer_text, spec)
    first_draft = draft
    measured = measure(draft, spec)
    revision: Dict[str, Any] = {"attempted": False, "ran": False, "rounds": 0,
                                "kept": "pehla", "notes": [], "reason": ""}
    gemini_calls = 0
    notes = revision_notes(measured)
    revision["notes"] = notes

    if measured.get("status") == DRAFT_WEAK and notes:
        if reviser is None:
            revision["reason"] = "reviser_not_available"
        else:
            revision["attempted"] = True
            prompt = revision_prompt_block(spec, measured)
            new_text = ""
            try:
                new_text = str(reviser(prompt) or "")
                gemini_calls = 1
            except Exception:
                revision["reason"] = "reviser_error"
            if new_text.strip():
                revision["ran"] = True
                revision["rounds"] = 1
                new_draft, new_source = extract_draft(new_text, spec)
                new_measured = measure(new_draft, spec)
                revision["second_status"] = new_measured.get("status")
                if _revision_is_better(new_measured, measured):
                    draft, source, measured = new_draft, new_source, new_measured
                    revision["kept"] = "doosra"
                else:
                    revision["kept"] = "pehla"
                    # Do alag wajah: "behtar nahi tha" aur "naya draft par naap
                    # hi kam ho gayi" — doosri wali chhupni nahi chahiye.
                    revision["reason"] = (
                        "second_draft_measured_less"
                        if _unmeasured_count(new_measured)
                        > _unmeasured_count(measured)
                        else "second_draft_not_better")

            elif not revision["reason"]:
                revision["reason"] = "reviser_returned_nothing"
    elif measured.get("status") == NO_DRAFT:
        revision["reason"] = "no_draft_to_revise"
    else:
        revision["reason"] = "no_measured_failure"

    return {
        "ran": True,
        "status": measured.get("status", NOT_RUN),
        "reason": "",
        "form": spec.form,
        "spec": spec.to_dict(),
        "draft_found": bool(draft.strip()),
        "draft_source": source,
        "final_draft": draft,
        "original_draft": first_draft,
        "checks": measured.get("checks", []),
        "measured": measured.get("measured", {}),
        "counts": measured.get("counts", {}),
        "revision": revision,
        "gemini_calls": gemini_calls,
        "provider_cost": POLICY.provider_cost,
        "policy": POLICY.to_dict(),
        "cannot_measure": list(CANNOT_MEASURE),
        "disclaimer": CRAFT_DISCLAIMER,
        "warnings": _warnings(spec, source, measured),
        "note": measured.get("note", ""),
    }


def apply_final_draft(answer_text: str,
                      report: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
    """
    Agar dobara likhwane par NAYA draft jeeta hai, to jawab me bhi wahi dikhna
    chahiye — warna user ek gaana padhta hai aur naap doosre ka bata rahi hoti.

    Ye badlaav sirf tab hota hai jab purana draft jawab me hu-ba-hu mila ho.
    Kuch bhi kaata nahi jaata: sirf utna hissa badalta hai jo draft tha.
    Lauta hua doosra value batata hai ki badla ya nahi — report usi sach ko
    likhti hai.
    """
    text = str(answer_text or "")
    if not isinstance(report, dict) or not report.get("ran"):
        return text, False
    if (report.get("revision") or {}).get("kept") != "doosra":
        return text, False
    old = str(report.get("original_draft") or "")
    new = str(report.get("final_draft") or "")
    if not old.strip() or not new.strip() or old == new or old not in text:
        return text, False
    return text.replace(old, new, 1), True


# ── jawab me kya likha jaayega ──────────────────────────────────────────────
# Ye `##` wali koi nayi heading NAHI banata (wo answer_order ka contract hai) —
# ye `## APP ORIGINAL RESEARCH LAB` ke andar jaane wala `###` block deta hai.
CRAFT_SUBHEADING = "### Jo bana kar diya, uska naap (CRAFT)"

_STATUS_LABEL: Dict[str, str] = {
    DRAFT_OK: "DRAFT_MEASURED_OK — jitne naap chale, sab target par "
              "(achha hone ka saboot nahi)",
    DRAFT_WEAK: "DRAFT_MEASURED_WEAK — kuch naap target par nahi utre",
    DRAFT_UNMEASURED: "DRAFT_NOT_MEASURABLE_HERE — naapne laayak kuch maanga "
                      "hi nahi gaya tha",
    NO_DRAFT: "NO_DRAFT_FOUND — naapne ke liye draft hi nahi mila",
    NOT_RUN: "NOT_RUN — ye stage chalaya hi nahi gaya",
}

_CHECK_MARK: Dict[str, str] = {MET: "✅", NOT_MET: "❌", NOT_MEASURED: "➖"}


def craft_section(report: Optional[Dict[str, Any]]) -> str:
    """CRAFT ka nateeja padhne layak Hinglish block. Na chala ho to ""."""
    if not isinstance(report, dict) or not report.get("ran"):
        return ""
    status = str(report.get("status") or NOT_RUN)
    spec = report.get("spec") or {}
    lines: List[str] = [CRAFT_SUBHEADING, "",
                        str(report.get("disclaimer") or CRAFT_DISCLAIMER), "",
                        f"**Kya banaya:** {spec.get('label') or spec.get('form')}",
                        f"**Naap ka nateeja:** {_STATUS_LABEL.get(status, status)}"]
    source = str(report.get("draft_source") or "")
    if source:
        lines.append(f"**Draft kahan se liya:** `{source}`")
    lines.append("")
    for check in report.get("checks") or []:
        mark = _CHECK_MARK.get(str(check.get("status")), "•")
        bits = [f"{mark} `{check.get('check')}`"]
        if check.get("measured") != "":
            bits.append(f"naapa: {check.get('measured')}")
        if check.get("target") != "":
            bits.append(f"chahiye: {check.get('target')}")
        if check.get("approx"):
            bits.append("approx")
        lines.append("- " + " | ".join(str(bit) for bit in bits))
        if check.get("note"):
            lines.append(f"  {check['note']}")
    lines.append("")
    revision = report.get("revision") or {}
    if revision.get("ran"):
        lines.append("**Dobara likhwaya:** haan, ek baar — "
                     + ("naya draft naap me behtar tha, wahi rakha gaya."
                        if revision.get("kept") == "doosra"
                        else "naya draft naap me behtar NAHI tha, isliye pehla "
                             "hi rakha gaya."))
    elif revision.get("attempted"):
        lines.append("**Dobara likhwaya:** koshish hui par chal nahi paayi "
                     f"(`{revision.get('reason')}`) — isliye pehla draft hi hai.")
    elif status == DRAFT_WEAK:
        lines.append("**Dobara likhwaya:** nahi "
                     f"(`{revision.get('reason') or 'reviser_not_available'}`) — "
                     "upar ke fail naap waise ke waise hain.")
    lines.append("")
    lines.append("**Ye naapa hi nahi ja sakta:** " + ", ".join(
        str(item) for item in (report.get("cannot_measure")
                               or CANNOT_MEASURE)) + ".")
    for warning in report.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    if report.get("note"):
        lines.append(f"- {report['note']}")
    return "\n".join(lines).rstrip() + "\n"


def craft_limits(report: Optional[Dict[str, Any]]) -> List[str]:
    """
    Wo seemayein jo naap ke BAAD bhi sach hain — audit me jaati hain.

    Yahan har line naapi hui haalat se aati hai, taaki audit me ek generic
    "creative cheez verify nahi hoti" wali line na lage jo aadhi galat ho.
    """
    if not isinstance(report, dict) or not report.get("ran"):
        return []
    limits: List[str] = []
    status = str(report.get("status") or NOT_RUN)
    counts = report.get("counts") or {}
    if status in (DRAFT_OK, DRAFT_WEAK):
        limits.append(
            f"Jo likhawat banai gayi, uske {int(counts.get(MET, 0))} dhaanche "
            f"wale naap target par the aur {int(counts.get(NOT_MET, 0))} nahi. "
            "Ye sirf STRUCTURE ka naap hai — likhawat acchi hai ya logon ko "
            "pasand aayegi, ye naapa hi nahi gaya.")
    if status == NO_DRAFT:
        limits.append(
            "Banane ki farmaish thi, par jawab me alag se naapne laayak draft "
            "nahi mila — isliye us likhawat par koi naap nahi hui.")
    if status == DRAFT_UNMEASURED:
        limits.append(
            "Farmaish me koi naapne laayak sharat (line/matra/tuk/shabd) nahi "
            "thi, isliye draft par ek bhi naap chala hi nahi.")
    if str(report.get("draft_source")) == "verse_shape_guess":
        limits.append(
            "Draft ko shakal se pehchana gaya tha (alag block me nahi tha) — "
            "mumkin hai naap jawab ke thode alag hisse par hui ho.")
    if (report.get("measured") or {}).get("matra_rule") == MATRA_RULE_ROMAN:
        limits.append(
            "Matra Hinglish/roman akshar par gini gayi (approx) — ise sahi "
            "chhand ka saboot mat maano.")
    revision = report.get("revision") or {}
    if status == DRAFT_WEAK and not revision.get("ran"):
        limits.append(
            "Fail naap ke baad dobara likhwaya nahi ja saka "
            f"(`{revision.get('reason') or 'reviser_not_available'}`) — jo "
            "kami upar likhi hai, wo draft me abhi bhi hai.")
    limits.append(
        "Yahan koi audio nahi bana aur kisi maujooda gaane se milaan nahi kiya "
        "gaya — dhun par baithega ya kisi ke kaam se milta hai, dono is naap "
        "se bahar hain.")
    return limits
