"""lang_bridge — sawaal aur source ek hi bhasha/script me na hon, phir bhi mel ho.

## Kya naapa gaya tha (2026-08-27, asli code par)

Teen bilkul on-topic English papers, aur ek hi baat poochhne wale paanch sawaal:

    "how to improve brain performance and memory"  -> 0.667 / 0.093 / 0.314
    "dimag tej kaise kare"                         -> 0.520 / 0.000 / 0.338
    "दिमाग तेज कैसे करें"                            -> 0.418 / 0.000 / 0.279
    "মস্তিষ্ক কীভাবে তীক্ষ্ণ করা যায়"                  -> 0.000 / 0.000 / 0.000
    "как улучшить память и работу мозга"           -> 0.000 / 0.000 / 0.000

Hindi/Hinglish sirf isliye chalta hai ki `multilingual_research.py` me un shabdon
ki **hath se likhi glossary** maujood hai. Bangla aur Russian par anchor khaali
aata hai, isliye har score 0.0 — yaani sahi source milne ke baad bhi relevance
floor cross nahi kar sakta. Ye wahi "closed list" wali kamzori hai: jo shabd
kisi ne pehle se type nahi kiya, wo bhasha app ke liye maujood hi nahi.

## Yahan ka ilaaj — teen parat, teeno list-free

1. **SCRIPT PUL (offline, deterministic).** Har Indic script Devanagari ke saath
   code-point aligned hai (Bengali +0x80, Gurmukhi +0x100, ... Malayalam +0x400),
   isliye pehle usko Devanagari par fold karte hain aur phir Unicode ke apne
   CHARACTER NAAM se roman banate hain ("DEVANAGARI LETTER KA" -> ka). Koi shabd
   list nahi — sirf script ka gyaan. Cyrillic/Greek/Arabic ke liye chhoti
   phonetic table hai (wo bhi shabd nahi, akshar hain).

2. **SKELETON MEL.** Roman ban jaane ke baad "क्वांटम" -> "kvantam" hai aur
   English me "quantum". Inhe milane ke liye consonant-skeleton nikaalte hain
   (kvntm vs kntm) aur ek galti ki chhoot dete hain. Isse har transliterated
   loanword aur har naam apne aap judta hai: सुपरकंडक्टिविटी=superconductivity,
   श्रोडिंगर=schrodinger, फेनमैन=feynman, রামায়ণ=ramayan — ek bhi entry likhe
   bina.

3. **MATLAB KA PUL (Wikipedia ke apne langlinks).** "মস্তিষ্ক" ka roman "mostisko"
   hai, "brain" nahi — skeleton isse nahi jod sakta. Iske liye hum koi glossary
   nahi likhte; Wikipedia ke official MediaWiki API se poochhte hain ki us shabd
   ke article ka **English naam** kya hai (bina key, bina scraping, ₹0). Duniya
   ki 300+ bhashaon ka mel wahan pehle se likha hai — hamari list me nahi.
   Network na ho to module chup-chaap parat 1-2 par gir jaata hai aur `status`
   me sach likh deta hai.

## Do imaandaar hadd (jaan-boojh kar)

* **Transliteration translation NAHI hai.** "мозга" -> "mozga" hai, "brain"
  nahi. Isliye jahan matlab ka pul chahiye wahan ye module
  `translation_missing` bolta hai, chup nahi rehta (`bridge_report`).
* Ye pul sirf SCORING/SEARCH ke liye hai. Kisi text ko "padh liya" ya
  "translate kar liya" ye kabhi nahi kehta.

Offline, deterministic, zero model call, zero nayi dependency.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Dict, List, Sequence, Set, Tuple

# ── script pehchaan ─────────────────────────────────────────────────────────
# (naam, start, end, wikipedia/wikisource ka language code jo is script me hai)
_SCRIPTS: Tuple[Tuple[str, int, int, str], ...] = (
    ("devanagari", 0x0900, 0x097F, "hi"),
    ("bengali", 0x0980, 0x09FF, "bn"),
    ("gurmukhi", 0x0A00, 0x0A7F, "pa"),
    ("gujarati", 0x0A80, 0x0AFF, "gu"),
    ("odia", 0x0B00, 0x0B7F, "or"),
    ("tamil", 0x0B80, 0x0BFF, "ta"),
    ("telugu", 0x0C00, 0x0C7F, "te"),
    ("kannada", 0x0C80, 0x0CFF, "kn"),
    ("malayalam", 0x0D00, 0x0D7F, "ml"),
    ("sinhala", 0x0D80, 0x0DFF, "si"),
    ("arabic", 0x0600, 0x06FF, "ar"),
    ("hebrew", 0x0590, 0x05FF, "he"),
    ("greek", 0x0370, 0x03FF, "el"),
    ("cyrillic", 0x0400, 0x04FF, "ru"),
    ("thai", 0x0E00, 0x0E7F, "th"),
    ("hiragana_katakana", 0x3040, 0x30FF, "ja"),
    ("hangul", 0xAC00, 0xD7AF, "ko"),
    ("han", 0x4E00, 0x9FFF, "zh"),
)

# Indic scripts jo Devanagari ke saath code-point aligned hain (ISCII se aayi
# ye alignment hi is module ka sabse bada shortcut hai).
_INDIC_ALIGNED = {
    0x0980, 0x0A00, 0x0A80, 0x0B00, 0x0B80, 0x0C00, 0x0C80, 0x0D00,
}
_DEVA_BASE = 0x0900

# In scripts ka roman nahi banta (na alignment, na phonetic table) — inhe
# character-level par hi milaya jaata hai, aur `bridge_report` isko bolta hai.
# Sinhala yahan isliye hai ki wo Devanagari ke saath aligned NAHI hai aur uske
# Unicode naam phonetic nahi hote ("SINHALA LETTER DANTAJA SAYANNA", "VOWEL SIGN
# KETTI IS-PILLA") — usse roman banane ka daawa jhooth hota. Sinhala sawaal ka
# pul parat 3 (si.wikipedia langlinks) se banta hai.
_NO_ROMAN = {"hiragana_katakana", "hangul", "han", "thai", "sinhala"}


def script_counts(text: str) -> Dict[str, int]:
    """Kis script ke kitne akshar — dominant script isse tay hota hai."""
    out: Dict[str, int] = {}
    for ch in str(text or ""):
        if ch.isspace() or not ch.isalpha():
            continue
        point = ord(ch)
        if "a" <= ch.lower() <= "z" or point < 0x0370:
            out["latin"] = out.get("latin", 0) + 1
            continue
        for name, start, end, _lang in _SCRIPTS:
            if start <= point <= end:
                out[name] = out.get(name, 0) + 1
                break
        else:
            out["other"] = out.get("other", 0) + 1
    return out


def dominant_script(text: str) -> str:
    counts = script_counts(text)
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda kv: (kv[1], kv[0] != "latin"))[0]


def wiki_lang_of(script: str) -> str:
    """Script ka wikipedia language code ('bengali' -> 'bn'). Latin -> 'en'."""
    for name, _s, _e, lang in _SCRIPTS:
        if name == script:
            return lang
    return "en"


def _fold_indic(ch: str) -> str:
    """Bengali/Tamil/Telugu... ko Devanagari ke usi akshar par le aao."""
    point = ord(ch)
    for start in _INDIC_ALIGNED:
        if start <= point <= start + 0x7F:
            return chr(point - start + _DEVA_BASE)
    return ch


_DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five",
                "six", "seven", "eight", "nine")


@lru_cache(maxsize=4096)
def _deva_piece(ch: str):
    """Unicode ke apne naam se akshar ka roman tukda: ('LETTER', 'ka')."""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if not name.startswith("DEVANAGARI "):
        return None
    rest = name[len("DEVANAGARI "):]
    for tag in ("LETTER ", "VOWEL SIGN ", "SIGN ", "DIGIT "):
        if rest.startswith(tag):
            return (tag.strip(), rest[len(tag):].strip().lower())
    return None


# Unicode naam ke wo hisse jo phonetic nahi hain — inhe saaf karna padta hai.
_NAME_FIX = (
    ("vocalic rr", "ri"), ("vocalic ll", "li"),
    ("vocalic r", "ri"), ("vocalic l", "li"),
    ("short ", ""), ("candra ", ""), ("long ", ""),
    ("with bar", ""), ("with nukta", ""),
)


def _clean_name(value: str) -> str:
    out = value
    for bad, good in _NAME_FIX:
        out = out.replace(bad, good)
    return re.sub(r"[^a-z]", "", out)


@lru_cache(maxsize=4096)
def _indic_sign(ch: str) -> str:
    """Wo Indic sign jo Devanagari ke khaane par aligned NAHI hai.

    Kyun zaroori: alignment 100% nahi hai — GURMUKHI TIPPI (U+0A70) Devanagari
    me ABBREVIATION SIGN ke khaane par girta hai, isliye `_deva_piece` use
    pehchanta nahi. Aise akshar ko raw chhod dena do nuksaan karta hai: roman
    string me non-ASCII akshar reh jaata hai (report me galat lagta hai) aur
    skeleton me wo bekaar hota hai. Unicode ke apne NAAM se iska kaam pata chal
    jaata hai — yahan bhi koi shabd list nahi. Jo sign bola hi nahi jaata
    (nukta, addak, virama-jaisa) wo khaali laut jaata hai; hum use roman me
    ghusaate nahi.
    """
    if ch.isascii():
        return ch
    if unicodedata.category(ch).startswith("P"):
        return " "                    # danda "।" jaisa viraam — shabd todta hai
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return ""
    if any(key in name for key in ("TIPPI", "BINDI", "ANUSVARA",
                                   "CANDRABINDU", "NASAL")):
        return "n"                    # nasal — har Indic script me yahi kaam
    if "VISARGA" in name:
        return "h"
    return ""


def _roman_devanagari(text: str) -> str:
    """Devanagari (aur uspar fold hui baaki Indic) ka roman.

    Consonant ke naam me implicit 'a' hota hai (KA, KHA), isliye consonant ka
    'a' hataakar alag se lagate hain — virama/matra usko dabaa deti hai. Yahi
    Indic likhawat ka asli niyam hai, aur isi wajah se "क्वांटम" -> "kvantam"
    banta hai (na "kavantama").
    """
    out: List[str] = []
    pending_a = False

    def flush():
        nonlocal pending_a
        if pending_a:
            out.append("a")
            pending_a = False

    for raw in unicodedata.normalize("NFC", str(text or "")):
        ch = _fold_indic(raw)
        piece = _deva_piece(ch)
        if piece is None:
            flush()
            out.append(_indic_sign(raw))
            continue
        kind, value = piece
        value = _clean_name(value)
        if kind == "LETTER":
            flush()
            if len(value) > 1 and value.endswith("a"):    # consonant: KA -> k
                out.append(value[:-1])
                pending_a = True
            else:                                         # svara: A, AA, I...
                out.append(value)
        elif kind == "VOWEL SIGN":
            pending_a = False
            out.append(value)
        elif kind == "DIGIT":
            flush()
            out.append(str(_DIGIT_WORDS.index(value))
                       if value in _DIGIT_WORDS else "")
        else:                                             # SIGN
            if value == "virama":
                pending_a = False
            elif value in ("anusvara", "candrabindu", "inverted candrabindu"):
                flush()
                out.append("n")
            elif value == "visarga":
                flush()
                out.append("h")
            elif value in ("nukta", "avagraha"):
                pass
            else:                                         # danda etc.
                flush()
                out.append(" ")
    flush()
    joined = "".join(out)
    # Hindi ka schwa-lop: shabd ke aakhir ka implicit 'a' bola nahi jaata
    # ("दिमाग" -> dimag, na dimaga). Skeleton par asar nahi padta, par jo roman
    # log/report me dikhta hai wo padhne layak rehta hai.
    return re.sub(r"(?<=[b-df-hj-np-tv-z])a\b", "", joined)


# Cyrillic aur Greek ke Unicode naam phonetic nahi hain ("CYRILLIC SMALL LETTER
# GHE"), isliye inke liye chhoti akshar-table. Ye shabd list nahi hai.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ї": "yi", "і": "i", "є": "ye", "ґ": "g", "ў": "u",
}
_GREEK = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
}


@lru_cache(maxsize=4096)
def _named_letter(ch: str) -> str:
    """Arabic/Hebrew ke liye Unicode naam se consonant ('LETTER MEEM' -> m).

    Ye scripts consonantal hain, isliye naam ka pehla akshar hi kaam ka
    consonant hota hai — skeleton mel ke liye itna kaafi hai, aur ye bhi
    kisi shabd list par nahi tikta.
    """
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return ""
    match = re.search(r"LETTER ([A-Z]+)", name)
    if not match:
        return ""
    word = match.group(1).lower()
    special = {"alef": "a", "ain": "a", "hamza": "", "yeh": "y", "waw": "v",
               "teh": "t", "theh": "t", "jeem": "j", "hah": "h", "khah": "kh",
               "dal": "d", "thal": "z", "reh": "r", "zain": "z", "seen": "s",
               "sheen": "sh", "sad": "s", "dad": "d", "tah": "t", "zah": "z",
               "ghain": "g", "feh": "f", "qaf": "q", "kaf": "k", "lam": "l",
               "meem": "m", "noon": "n", "heh": "h", "beh": "b"}
    return special.get(word, word[:2] if len(word) > 2 else word)


def roman(text: str) -> str:
    """Kisi bhi supported script ka roman roop. Latin waise hi rehta hai."""
    raw = str(text or "")
    if raw.isascii():
        return raw
    out: List[str] = []
    for ch in raw:
        point = ord(ch)
        if ch.isascii():
            out.append(ch)
        elif ch.lower() in _CYRILLIC:
            out.append(_CYRILLIC[ch.lower()])
        elif ch.lower() in _GREEK:
            out.append(_GREEK[ch.lower()])
        elif 0x0900 <= point <= 0x0DFF or point in _INDIC_ALIGNED:
            out.append(_roman_devanagari(ch))
        elif 0x0590 <= point <= 0x06FF:
            out.append(_named_letter(ch))
        else:
            out.append(ch)
    return "".join(out)


# ── skeleton mel — transliterated shabd ko English shabd se milana ──────────
#
# "क्वांटम" -> "kvantam", English "quantum". Vowel aur transliteration ki
# aadatein (c/k/q, v/w, sh/s, ph/f) hata dene par dono ka dhaancha ek ho jaata
# hai: kvntm ~ kntm. Ek galti ki chhoot rakhi hai, par sirf tab jab dhaancha
# itna lamba ho ki ittefaq na ho.
_DIGRAPHS = (("sch", "s"), ("shch", "s"), ("sh", "s"), ("ch", "c"),
             ("ph", "f"), ("th", "t"), ("kh", "k"), ("gh", "g"),
             ("dh", "d"), ("bh", "b"), ("jh", "j"), ("ck", "k"),
             ("qu", "k"), ("ts", "s"))
_LETTER_FOLD = str.maketrans({"q": "k", "c": "k", "w": "v", "x": "k",
                              "z": "j", "f": "p"})
_VOWELS = "aeiouy"
_MIN_FUZZY_SKELETON = 4


@lru_cache(maxsize=8192)
def skeleton(token: str) -> str:
    """Shabd ka consonant dhaancha — script ki aadat hata kar."""
    from .domain import fold_accents

    word = fold_accents(str(token or "")).lower()
    word = re.sub(r"[^a-z0-9]", "", word)
    if not word:
        return ""
    word = re.sub(r"(.)\1+", r"\1", word)          # doubled akshar -> ek
    for big, small in _DIGRAPHS:
        word = word.replace(big, small)
    word = word.translate(_LETTER_FOLD)
    head = word[0]
    body = "".join(ch for ch in word[1:] if ch not in _VOWELS)
    out = (head if head not in _VOWELS else head) + body
    return re.sub(r"(.)\1+", r"\1", out)


def _distance_at_most_one(a: str, b: str) -> bool:
    """Levenshtein <= 1, bina poora matrix banaye."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = sum(1 for x, y in zip(a, b) if x != y)
        return diff <= 1
    long, short = (a, b) if la > lb else (b, a)
    for i in range(len(long)):
        if long[:i] + long[i + 1:] == short:
            return True
    return False


def skeletons_match(a: str, b: str) -> bool:
    """Do shabd ka dhaancha ek hai kya (ek galti ki chhoot ke saath)."""
    sa, sb = skeleton(a), skeleton(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    if min(len(sa), len(sb)) < _MIN_FUZZY_SKELETON:
        return False                                # chhote dhaanche par ittefaq
    return _distance_at_most_one(sa, sb)


def skeleton_bag(text: str) -> Set[str]:
    """Text ke saare shabdon ka dhaancha (roman kar ke)."""
    from .domain import tokens

    out: Set[str] = set()
    for tok in tokens(roman(text)):
        shape = skeleton(tok)
        if len(shape) >= 2:
            out.add(shape)
    return out


def roman_tokens(text: str) -> List[str]:
    from .domain import tokens

    return tokens(roman(text))


def needs_bridge(query: str, text: str) -> bool:
    """Pul sirf tab lagta hai jab dono taraf ki script ek na ho.

    Ye shart hi purane English benchmarks ko hilne se rokti hai: English sawaal
    + English source par ye function False deta hai, yaani scoring me ek bit
    bhi farak nahi aata.
    """
    return not (str(query or "").isascii() and str(text or "").isascii())


def bridged_overlap(query: str, text: str) -> Tuple[float, List[str]]:
    """Kitne query-shabd dhaanche ke zariye text me mile (0..1) + wo shabd."""
    from .domain import tokens

    q_tokens = [t for t in roman_tokens(query) if len(t) >= 2]
    if not q_tokens:
        return 0.0, []
    t_bag = skeleton_bag(text)
    if not t_bag:
        return 0.0, []
    hits: List[str] = []
    for tok in q_tokens:
        shape = skeleton(tok)
        if not shape or len(shape) < 2:
            continue
        if shape in t_bag:
            hits.append(tok)
            continue
        if len(shape) >= _MIN_FUZZY_SKELETON and any(
                _distance_at_most_one(shape, other) for other in t_bag):
            hits.append(tok)
    unique_q = {skeleton(t) for t in q_tokens if skeleton(t)}
    if not unique_q:
        return 0.0, []
    score = len({skeleton(h) for h in hits}) / len(unique_q)
    return round(min(1.0, score), 4), sorted(set(hits))[:12]


# ── parat 2: matlab ka pul — Wikipedia ke apne official langlinks se ────────
#
# Transliteration se "মস্তিষ্ক" -> "mostisko" banta hai, "brain" nahi. Matlab ka
# pul banane ke do hi imaandaar raste hain: koi glossary hath se likho (jo
# hamesha adhoori rahegi), ya kisi aisi jagah se poochho jahan duniya ki saari
# bhashaon ka mel PEHLE SE likha hua hai. Wikipedia ke **langlinks** wahi jagah
# hai: har article ka doosri bhasha wala naam, official MediaWiki action API se,
# bina key, bina scraping, ₹0.
#
# Teen hadd jaan-boojh kar:
#   1. Ye SEARCH/SCORING vocabulary hai — "translation ho gaya" ye kabhi nahi
#      kehta (`status` me saaf likha jaata hai).
#   2. Call bounded hai (kuch hi shabd, chhota timeout) aur network na ho to
#      module chup-chaap offline parat par gir jaata hai — pipeline nahi rukti.
#   3. Kuch na mile to `translation_missing` bolta hai. Chup rehna bhi jhooth
#      hai: user ko pata chalna chahiye ki uski bhasha ka pul nahi bana.
_WIKI_TIMEOUT = (4, 8)
_MAX_LOOKUPS = 3
_MIN_LOOKUP_LEN = 3
_english_cache: Dict[Tuple[str, str], List[str]] = {}


def _lookup_terms(text: str) -> List[str]:
    """Kaun se shabd poochhne layak hain — sabse lambe (yaani sabse khaas)."""
    from .domain import tokens

    seen: List[str] = []
    for tok in tokens(text):
        if len(tok) >= _MIN_LOOKUP_LEN and tok not in seen:
            seen.append(tok)
    seen.sort(key=len, reverse=True)
    return seen[:_MAX_LOOKUPS]


def _wiki_english_title(term: str, lang: str, fetch) -> str:
    """Ek term ka English article naam (ya khaali). Kabhi raise nahi karta."""
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrsearch": term, "gsrlimit": 1,
        "gsrnamespace": "0", "prop": "langlinks", "lllang": "en", "lllimit": 1,
    }
    url = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        # `retries=0` jaan-boojh kar: network na ho to backoff sleep research ko
        # der karwa deta hai, aur ye lookup ek bonus hai — koi zaroorat nahi.
        try:
            resp = fetch(url, params=params, timeout=_WIKI_TIMEOUT, retries=0)
        except TypeError:
            resp = fetch(url, params=params, timeout=_WIKI_TIMEOUT)
        payload = resp.json() if hasattr(resp, "json") else {}
        pages = ((payload.get("query") or {}).get("pages") or [])
        if isinstance(pages, dict):
            pages = list(pages.values())
        for page in pages:
            if not isinstance(page, dict):
                continue
            for link in page.get("langlinks") or []:
                title = str((link or {}).get("title") or "").strip()
                if title:
                    return title[:80]
    except Exception:
        return ""
    return ""


def lookup_enabled() -> bool:
    """`LANG_BRIDGE_LOOKUP=0` se network wala pul band — offline run ke liye."""
    import os

    return str(os.getenv("LANG_BRIDGE_LOOKUP", "1")).strip().lower() not in (
        "0", "false", "no", "off")


def english_terms(text: str, lang: str = "", fetch=None) -> Tuple[List[str], str]:
    """``(English search terms, status)`` — sirf search/scoring ke liye.

    `fetch` inject ho sakta hai (test isse bina network ke chalta hai). Default
    project ka apna `connectors.base.http_get` hai — wahi official raasta.
    """
    raw = str(text or "").strip()
    if not raw or raw.isascii():
        return [], "not_needed_latin_script"
    script = dominant_script(raw)
    lang = (lang or wiki_lang_of(script) or "en").strip().lower()
    if fetch is None:
        if not lookup_enabled():
            return [], "lookup_disabled_by_config"
        try:
            from .connectors.base import http_get as fetch  # type: ignore
        except Exception:
            return [], "lookup_unavailable_offline"
    out: List[str] = []
    for term in _lookup_terms(raw):
        key = (lang, term)
        cached = _english_cache.get(key)
        if cached is None:
            title = _wiki_english_title(term, lang, fetch)
            cached = [title] if title else []
            if len(_english_cache) > 512:
                _english_cache.clear()
            _english_cache[key] = cached
        for title in cached:
            if title.casefold() not in {o.casefold() for o in out}:
                out.append(title)
    if out:
        return out[:6], "wikipedia_langlinks_search_vocabulary"
    return [], "translation_missing"


def bridge_report(question: str, fetch=None,
                  lookup: bool = True) -> Dict[str, object]:
    """Ek sawaal ka poora bhasha-pul ka haal — report me likhne ke liye.

    Isme jhooth ki jagah nahi: agar matlab ka pul nahi bana to `status`
    `translation_missing` rehta hai aur `note` user ko saaf batata hai ki isse
    kam evidence mil sakta hai.
    """
    raw = str(question or "").strip()
    script = dominant_script(raw)
    romanised = roman(raw) if script not in _NO_ROMAN else ""
    terms: List[str] = []
    status = "not_needed_latin_script"
    if raw and not raw.isascii():
        if lookup:
            terms, status = english_terms(raw, fetch=fetch)
        else:
            status = "lookup_skipped"
    note = ""
    if status == "translation_missing":
        note = ("Tumhara sawaal English ke alawa kisi script me hai aur uske "
                "shabdon ka English mel nahi mil paaya — isliye English "
                "sources se kam mel ho sakta hai. Jo mila wo hi likha hai.")
    elif status == "lookup_unavailable_offline":
        note = ("Bhasha ka pul is waqt bana nahi ja saka (network nahi mila), "
                "isliye sirf script-level mel lagaya gaya hai.")
    elif status == "lookup_disabled_by_config":
        note = ("Bhasha ka pul settings se band hai (LANG_BRIDGE_LOOKUP=0), "
                "isliye sirf script-level mel lagaya gaya hai.")
    return {
        "script": script,
        "wiki_lang": wiki_lang_of(script),
        "roman": romanised[:200],
        "english_terms": terms,
        "status": status,
        "romanisation_is_not_translation": True,
        "note": note,
    }


def scoring_anchor(question: str, fetch=None, lookup: bool = True) -> str:
    """Scoring ke liye English anchor string (khaali = koi pul nahi mila)."""
    report = bridge_report(question, fetch=fetch, lookup=lookup)
    terms = [str(t) for t in (report.get("english_terms") or [])]
    return " ".join(terms)[:200]
