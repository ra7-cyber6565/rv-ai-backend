"""Open-ended lens selection — app khud tay kare kaun sa framework lagega.

Kyun ye file bani (naapa hua karan, 2026-08-23):
``specialist_domains.detect_profiles()`` ek **closed keyword list** hai. intel ke
apne 12 example sawaal chalaye gaye the aur 10 par kuch nahi mila — "psycho-
cybernetics", "default mode network", "flow state", "game theory", "naval
ravikant", "ramanujan", "einstein", "picasso", aur "ved puran rishi muni" tak
`specialist=False, domain=generic` par gir gaye. List me 500 shabd jodne se
deewar sirf khisakti hai, hatti nahi: **mechanism galat hai.**

Isliye yahan ulta sawaal poocha jaata hai — "is sawaal par kaun se discipline /
framework / thinker / source-family lagti hai" — aur uska jawab teen raaste se
aata hai:

  1. DETERMINISTIC (hamesha chalta hai, ₹0, koi network nahi): sawaal me se
     concept phrases khud nikaalo — hyphenated compound, capitalised naam,
     concept-suffix wale shabd, aur glossary se mapped English vocabulary. Iske
     upar SHABD KI BANAWAT ka gyaan (prefix/suffix/tradition marker) aur
     head-noun framework pattern, taaki anjaan shabd bhi sahi field tak jaaye.
  2. CORPUS-DERIVED (round 1 ke baad, ₹0): jo sources ASLI ME mile unke author,
     venue aur dohraye gaye phrase se naye lens — yaani app padhte-padhte seekhta
     hai. Ye sabse "advanced" parat hai aur ek bhi model call nahi leti.
  3. MODEL (optional, bounded, DEFAULT SE BAND): ek chhoti structured call jo
     lens list deti hai. Pipeline me `ResearchPlanner.lens_generate = None` hai —
     intel ki shart: "gimini ka use hi naa ho sochne me … quota bhi khatam na ho".
     Isliye ye raasta code me maujood hai par chalta nahi.

HONESTY (§2 non-negotiables):
Lens list **evidence nahi hai**. Ye sirf search plan aur scoring vocabulary hai.
Model ne kisi thinker ya framework ka naam le liya — iska matlab ye NAHI ki wo
source padha gaya, ya us thinker ne aisa kaha. Citation sirf asli mile hue
source se banti hai. Isliye har lens plan me `verified=False` aur
`evidence_status` saaf likha jaata hai.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .domain import fold_accents, stem, tokens
from .local_language import normalize
from . import multilingual_research as ml

_MAX_ITEMS = 12
_MAX_CHARS = 120

# Sawaal ke dhaanche wale shabd — ye concept nahi hote.
_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "what", "how", "why",
    "when", "which", "who", "does", "can", "will", "should", "would", "about",
    "into", "than", "then", "there", "their", "them", "have", "has", "had",
    "are", "was", "were", "been", "being", "its", "it's", "not", "but", "all",
    "any", "some", "more", "most", "such", "also", "very", "much", "many",
    "give", "tell", "explain", "please", "help", "need", "want", "make",
    "kya", "kaise", "kyun", "kyu", "kaun", "kahan", "kab", "hai", "hain", "ho",
    "hoga", "karo", "kare", "karna", "krna", "kro", "kar", "mujhe", "mera",
    "meri", "mere", "app", "aap", "wo", "ye", "yeh", "usme", "isme", "bhi",
    "aur", "or", "sab", "koi", "kuch", "batao", "btao", "samjhao", "bata",
    "chahiye", "sakta", "sakti", "liye", "ka", "ki", "ke", "se", "me", "mein",
    "par", "pe", "ek", "do", "jo", "to", "na", "nahi", "nhi", "abhi", "phir",
    "research", "study", "topic", "question", "answer", "book", "books",
}

# Concept-jaise shabd ka aakhri hissa. Ye bilkul generic hai — kisi field ka
# naam yahan hard-code nahi hai, isliye naya concept (jo kisi list me nahi)
# bhi pakda jaata hai: "psycho-cybernetics", "neuroplasticity", "hermeticism",
# "individuation", "epigenetics", "phenomenology"...
_CONCEPT_SUFFIXES = (
    "ology", "ologies", "onomics", "onomy", "netics", "netic", "plasticity",
    "icity", "ism", "isms", "ist", "ists", "graphy", "metrics", "metry",
    "sophy", "genesis", "pathy", "therapy", "dynamics", "statics", "osis",
    "ation", "ations", "ability", "ivity", "ance", "ence", "hood", "ship",
)


def _clean(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:_MAX_CHARS].strip()


def _unique(values: Iterable[str], limit: int = _MAX_ITEMS) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        clean = _clean(value)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


def _is_stop(word: str) -> bool:
    low = word.casefold()
    return low in _STOP or len(low) <= 2


def is_stopword(word: str) -> bool:
    """Public roop — doosre deterministic module (classics) isi list par chalein,
    apni alag stop-list na banayein (do list ek din alag ho jaati hain)."""
    return _is_stop(str(word or ""))


def hyphenated_compounds(question: str) -> List[str]:
    """"psycho-cybernetics", "value-maxing" — hyphen khud concept ka signal hai."""
    text = fold_accents(question)
    found = re.findall(r"\b[A-Za-z][A-Za-z]+(?:-[A-Za-z][A-Za-z]+)+\b", text)
    return _unique(item for item in found if not _is_stop(item.replace("-", "")))


def suffix_concepts(question: str) -> List[str]:
    """Concept-suffix wale shabd — kisi field list ke bina."""
    out: List[str] = []
    for token in tokens(question):
        word = token.strip("-")
        if len(word) < 7 or _is_stop(word):
            continue
        if word.endswith(_CONCEPT_SUFFIXES):
            out.append(word)
    return _unique(out)


def quoted_phrases(question: str) -> List[str]:
    found = re.findall(r"[\"'“‘]([^\"'”’]{3,60})[\"'”’]", str(question or ""))
    return _unique(found)


def content_phrases(question: str, max_run: int = 4) -> List[str]:
    """Lagataar non-stopword tokens ke run aur unke bigram.

    Ye jaan-boojh kar capitalisation par depend NAHI karta. intel chhote akshar
    me likhta hai ("naval ravikant", "pablo picasso"), isliye "Capitalised Name"
    wala purana tarika uske sawaalon par kaam hi nahi karta. Run-based tarika
    "naval ravikant" aur "permissionless leverage" dono nikaal deta hai. Kuch
    bekaar bigram ("ravikant permissionless") bhi banega — wo search par 0
    result deta hai aur chup-chaap gir jaata hai, kisi claim me nahi jaata.
    """
    runs: List[List[str]] = []
    current: List[str] = []
    for token in tokens(question):
        word = token.strip("-")
        if not word or _is_stop(word):
            if len(current) >= 1:
                runs.append(current)
            current = []
            continue
        current.append(word)
    if current:
        runs.append(current)

    out: List[str] = []
    for run in runs:
        if 2 <= len(run) <= max_run:
            out.append(" ".join(run))
        for a, b in zip(run, run[1:]):
            out.append(f"{a} {b}")
    for run in runs:
        for word in run:
            if len(word) >= 4:
                out.append(word)
    return _unique(out, limit=_MAX_ITEMS + 6)


def english_vocabulary(question: str) -> List[str]:
    """Glossary se English scoring vocabulary — phrase AUR token dono.

    ``multilingual_research.controlled_english_terms()`` phrase match hone par
    us hisse ko consume kar deta hai, isliye "dimag tej" → sirf
    "cognitive performance" milta tha aur "brain"/"performance" gir jaate the.
    Scoring ke liye poora union chahiye (search query ke liye wahan ka behaviour
    jaisa hai waisa hi rehta hai).
    """
    text = unicodedata.normalize("NFKC", normalize(question or ""))
    low = text.casefold()
    out: List[str] = []
    for original, english in ml._PHRASE_GLOSSARY:
        if english and original.casefold() in low:
            out.append(english)
    for token in tokens(text):
        mapped = ml._TOKEN_GLOSSARY.get(token)
        if mapped:
            out.append(mapped)
    return _unique(out)


# --------------------------------------------------------------------------
# MORPHEME REASONING — shabd ki BANAWAT se discipline nikaalna.
#
# Ye topic list NAHI hai. Ye shabd-rachna (word formation) ka gyaan hai, jo un
# shabdon par bhi chalta hai jo yahan likhe hi nahi:
#   "psycho-cybernetics" → psycho- (psychology) + -netics (cybernetics)
#   "neuroplasticity"    → neuro- (neuroscience) + -plasticity
#   "epigenetics"        → -genetics (genetics)
#   "hermeticism"        → -ism (tradition / history of ideas)
#   "phenomenology"      → -ology (khud ek field ka naam hai)
# Isliye intel ki di hui list se bahar ke shabd bhi lens paate hain, aur Gemini
# ki ek bhi call kharch nahi hoti.
# --------------------------------------------------------------------------

_PREFIX_FIELDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("neuro", ("neuroscience", "cognitive neuroscience")),
    ("psycho", ("psychology",)),
    ("psych", ("psychology",)),
    ("cogni", ("cognitive science",)),
    ("socio", ("sociology",)),
    ("anthro", ("anthropology",)),
    ("econo", ("economics",)),
    ("bio", ("biology",)),
    ("physio", ("physiology",)),
    ("patho", ("pathology",)),
    ("pharma", ("pharmacology",)),
    ("immuno", ("immunology",)),
    ("endocrin", ("endocrinology",)),
    ("cardio", ("cardiology", "physiology")),
    ("astro", ("astronomy", "astrophysics")),
    ("cosmo", ("cosmology",)),
    ("geo", ("earth science",)),
    ("quantum", ("quantum physics",)),
    ("thermo", ("thermodynamics",)),
    ("electro", ("physics", "electrical engineering")),
    ("cyber", ("cybernetics", "systems theory")),
    ("info", ("information theory",)),
    ("crypto", ("cryptography",)),
    ("linguist", ("linguistics",)),
    ("theolog", ("theology",)),
    ("philo", ("philosophy",)),
    ("epistem", ("epistemology", "philosophy")),
    ("meta", ("metaphysics", "philosophy")),
    ("ethno", ("ethnography", "anthropology")),
    ("archae", ("archaeology",)),
    ("histor", ("history",)),
    ("statist", ("statistics",)),
    ("mathemat", ("mathematics",)),
    ("algebra", ("mathematics", "algebra")),
    ("geometr", ("mathematics", "geometry")),
    ("topolog", ("mathematics", "topology")),
    ("chemi", ("chemistry",)),
    ("genet", ("genetics",)),
    ("evolu", ("evolutionary biology",)),
    ("ecolog", ("ecology",)),
    ("nutri", ("nutrition science",)),
)

# Suffix → field. `""` matlab "shabd khud field ka naam hai" (jaise
# "phenomenology", "cosmology") — us case me shabd hi discipline ban jaata hai.
_SUFFIX_FIELDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("ology", ("",)),
    ("ologies", ("",)),
    ("onomics", ("economics",)),
    ("onomy", ("systematic study",)),
    ("netics", ("cybernetics", "systems theory")),
    ("netic", ("cybernetics", "systems theory")),
    ("plasticity", ("neuroscience", "developmental biology")),
    ("genetics", ("genetics", "molecular biology")),
    ("therapy", ("clinical practice", "medicine")),
    ("pathy", ("medicine",)),
    ("dynamics", ("physics", "systems theory")),
    ("statics", ("physics",)),
    ("metrics", ("measurement science", "statistics")),
    ("metry", ("measurement science",)),
    ("sophy", ("philosophy",)),
    ("graphy", ("documentary study",)),
    ("ism", ("history of ideas", "philosophy")),
    ("isms", ("history of ideas", "philosophy")),
    ("osis", ("biology", "medicine")),
)

# Tradition / classical-text markers. Ye bhi list nahi, MARKER hain: substring
# match karte hain isliye "vedanta", "puranon", "upanishadon", "shastron",
# "sutras" jaise roop bhi pakde jaate hain. Inka kaam sirf itna hai ki sawaal
# ko sahi source-family (public-domain granth + critical translation) tak
# pahunchaya jaaye — kya likha hai wo padhne par hi pata chalega.
_TRADITION_MARKERS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("ved", ("Indology", "Sanskrit studies", "history of religion"),
     ("public-domain Sanskrit texts and critical translations",
      "peer-reviewed Indology journals")),
    ("puran", ("Indology", "Sanskrit studies", "mythology studies"),
     ("public-domain Sanskrit texts and critical translations",)),
    ("upanishad", ("Indian philosophy", "Sanskrit studies"),
     ("public-domain Sanskrit texts and critical translations",)),
    ("granth", ("Indology", "textual studies"),
     ("public-domain scanned manuscripts and critical editions",)),
    ("shastra", ("Indology", "textual studies"), ()),
    ("rishi", ("history of religion", "Indology"), ()),
    ("muni", ("history of religion", "Indology"), ()),
    ("sutra", ("Sanskrit studies", "textual studies"), ()),
    ("gita", ("Indian philosophy", "Sanskrit studies"), ()),
    ("yoga", ("yoga studies", "physiology"), ()),
    ("tantra", ("religious studies", "Indology"), ()),
    ("dharm", ("religious studies", "philosophy"), ()),
    ("karma", ("religious studies", "philosophy"), ()),
    ("sufi", ("religious studies", "history"), ()),
    ("bible", ("biblical studies", "history of religion"), ()),
    ("quran", ("Islamic studies", "history of religion"), ()),
    ("buddh", ("Buddhist studies", "philosophy"), ()),
    ("jain", ("Jain studies", "philosophy"), ()),
    ("hermet", ("history of esotericism", "history of ideas"), ()),
    ("occult", ("history of esotericism", "religious studies"), ()),
    ("alchem", ("history of science", "history of esotericism"), ()),
    # Doosri parampara ke naamit granth-roop. Ye bhi marker hain: kisi ek dharm
    # ki taraf jhukav na ho, isliye Indic ke saath Semitic/Iranian text-families
    # bhi yahan hain.
    ("samhita", ("Indology", "Sanskrit studies"),
     ("public-domain Sanskrit texts and critical translations",)),
    ("aranyak", ("Indology", "Sanskrit studies"), ()),
    ("smriti", ("Indology", "history of law"), ()),
    ("mimamsa", ("Indian philosophy",), ()),
    ("nikaya", ("Buddhist studies", "Pali studies"), ()),
    ("sutta", ("Buddhist studies", "Pali studies"), ()),
    ("hadith", ("Islamic studies", "history of religion"), ()),
    ("torah", ("Jewish studies", "biblical studies"), ()),
    ("talmud", ("Jewish studies", "history of law"), ()),
    ("avesta", ("Iranian studies", "history of religion"), ()),
    ("gospel", ("biblical studies", "history of religion"), ()),
    ("psalm", ("biblical studies",), ()),
)


def _marker_hit(token: str, marker: str) -> bool:
    """Marker token se juda hai ya nahi — bina ``in`` ke andhe substring match.

    Andha ``marker in token`` ek asli bug tha: "proved", "solved", "involved"
    sab me "ved" chhupa hai, to physics ka sawaal Indology ban jaata. Isliye:
      * prefix match, aur token marker se 4 se zyada lamba na ho
        ("vedanta", "vedic", "puranon" haan; "municipal" nahi — ye collision
        probe me pakda gaya tha),
      * ya marker khud 5+ akshar ka ho tab hi beech me match
        ("upanishadon", "bhagavadgita", "vedantasara").
    Seema imaandaari se: "rigveda" jaise sandhi-compound tab hi milte hain jab
    unka apna marker ho — isliye upar "samhita" jaise roop alag likhe hain.
    """
    if len(token) < len(marker):
        return False
    if token.startswith(marker) and len(token) <= len(marker) + 4:
        return True
    return len(marker) >= 5 and marker in token


def morpheme_disciplines(question: str) -> Tuple[List[str], List[str]]:
    """(disciplines, source_families) — shabd ki banawat se.

    Har hit ka karan traceable hai: prefix, suffix ya tradition marker. Koi
    "yeh topic mujhe pehle se pata hai" wali list nahi — isliye naya shabd bhi
    (jo kisi list me nahi) apni banawat se sahi field tak pahunch jaata hai.
    """
    disciplines: List[str] = []
    families: List[str] = []
    all_tokens = [w.strip("-") for w in tokens(question) if w.strip("-")]
    words = [w for w in all_tokens if len(w) >= 4 and not _is_stop(w)]
    parts: List[str] = []
    for word in words:
        parts.append(word)
        parts.extend(piece for piece in word.split("-") if len(piece) >= 4)

    for word in parts:
        # SABSE LAMBA suffix jeetta hai. Warna "epigenetics" ka "netics"
        # cybernetics le aata tha jabki uska asli matlab "genetics" hai —
        # ye galti probe me pakdi gayi thi.
        best: Tuple[int, Tuple[str, ...]] = (0, ())
        for suffix, fields in _SUFFIX_FIELDS:
            if not word.endswith(suffix) or len(word) <= len(suffix) + 2:
                continue
            if len(suffix) > best[0]:
                best = (len(suffix), fields)
        for field in best[1]:
            disciplines.append(word if field == "" else field)
        for prefix, fields in _PREFIX_FIELDS:
            if word.startswith(prefix) and len(word) >= len(prefix) + 2:
                disciplines.extend(fields)

    for marker, fields, fams in _TRADITION_MARKERS:
        if any(_marker_hit(token, marker) for token in all_tokens):
            disciplines.extend(fields)
            families.extend(fams)
    return _unique(disciplines, limit=8), _unique(families, limit=6)


def tradition_hits(question: str) -> List[str]:
    """Sawaal ke apne wo shabd jo kisi granth/parampara marker se mile.

    ``morpheme_disciplines`` marker se FIELD banata hai; ye function marker se
    mila hua ASLI shabd wapas deta hai ("upanishadon", "bhagavadgita",
    "talmud"), kyunki text-lane ki search query me user ka apna shabd hi kaam
    aata hai — koi granth-naam ki list yahan nahi hai.
    """
    out: List[str] = []
    for token in (w.strip("-") for w in tokens(question)):
        if len(token) < 3:
            continue
        for marker, _fields, _fams in _TRADITION_MARKERS:
            if _marker_hit(token, marker):
                out.append(token)
                break
    return _unique(out, limit=6)


# Framework ka HEAD NOUN. Ye scientific/analytic bhasha ka dhaancha hai, kisi
# field ka naam nahi — isliye "game theory", "dopamine loops", "attention
# residue", "flow state", "default mode network", "hedonic treadmill",
# "prisoner's dilemma", "Bayes theorem" sab ek hi pattern se nikal aate hain.
_FRAMEWORK_HEADS = (
    "theory", "theories", "theorem", "theorems", "effect", "effects", "law",
    "laws", "principle", "principles", "paradox", "paradoxes", "hypothesis",
    "model", "models", "equation", "equations", "conjecture", "framework",
    "loop", "loops", "cycle", "cycles", "bias", "biases", "fallacy",
    "paradigm", "network", "networks", "state", "states", "residue",
    "dilemma", "problem", "criterion", "constant", "constants", "ratio",
    "distribution", "function", "method", "methods", "technique", "protocol",
    "axiom", "lemma", "identity", "series", "formula", "formulas", "formulae",
    "notebook", "notebooks", "treadmill", "bets", "leverage", "curve",
    "threshold", "feedback", "effectiveness", "mechanism", "pathway",
)


def framework_phrases(question: str) -> List[str]:
    """"<kuch> + head noun" wale naam. Head noun list generic bhasha hai."""
    # 1-akshar ke tukde hata diye jaate hain: "prisoner's dilemma" tokenizer se
    # ["prisoner", "s", "dilemma"] banta hai, aur beech ka "s" pehle poore
    # phrase ko reject kar deta tha (probe me pakdi gayi galti).
    words = [w for w in (t.strip("-") for t in tokens(question)) if len(w) > 1]
    out: List[str] = []
    for index, word in enumerate(words):
        if word not in _FRAMEWORK_HEADS or index == 0:
            continue
        for span in (3, 2, 1):
            start = index - span
            if start < 0:
                continue
            chunk = words[start:index + 1]
            if any(_is_stop(part) for part in chunk[:-1]):
                continue
            out.append(" ".join(chunk))
            break
    return _unique(out, limit=10)


# Aadmi ka naam pehchanne ke CUE. Ye naamon ki list nahi hai — ye bhasha ke
# wo hisse hain jo naam ke aas-paas aate hain. Isliye jis vyakti ka naam intel
# ne kabhi bataya hi nahi, uska naam bhi pakda jaata hai.
_HONORIFICS = {
    "dr", "prof", "professor", "sir", "swami", "acharya", "rishi", "maharishi",
    "guru", "shri", "sri", "pandit", "maharshi", "bhagwan", "saint", "mahatma",
    "srila", "lama", "imam", "rabbi", "father",
}
# "<naam> ke/ki/ka <ye cheez>" — Hinglish possessive ke baad aane wale shabd.
_OWNED_THINGS = {
    "book", "books", "kitab", "kitabe", "kitaab", "theory", "theories",
    "formula", "formulas", "formulae", "notebook", "notebooks", "granth",
    "sutra", "sutras", "niyam", "siddhant", "siddhanth", "vichar", "kaam",
    "research", "paper", "papers", "law", "laws", "equation", "equations",
    "quote", "quotes", "teaching", "teachings", "upadesh", "method", "tarika",
    "philosophy", "darshan", "lecture", "lectures", "diary", "letters",
}
_POSSESSIVE = {"ke", "ki", "ka", "kaa", "kii", "kee"}
# "according to X", "as per X", "X ne kaha"
_BEFORE_NAME = ("according to", "as per", "as told by", "in the words of")


def thinker_candidates(question: str) -> List[str]:
    """Sambhavit vyakti ke naam — bina kisi naam-list ke.

    Teen tarah ke cue: (1) honorific ke baad ka naam, (2) Hinglish possessive
    "<naam> ke/ki/ka book|theory|formula...", (3) "according to <naam>" aur
    capitalised naam-run. Ye SIRF search lens hai — plan par ``verified`` hamesha
    False rehta hai, aur in naamon se koi claim nahi banti.
    """
    raw = str(question or "")
    words = [w.strip("-") for w in tokens(raw)]
    out: List[str] = []

    for index, word in enumerate(words):
        if word in _HONORIFICS:
            chunk = [w for w in words[index + 1:index + 3]
                     if w and not _is_stop(w) and w not in _HONORIFICS]
            if chunk:
                out.append(" ".join(chunk))
        if word in _POSSESSIVE and index >= 1:
            nxt = words[index + 1] if index + 1 < len(words) else ""
            if nxt in _OWNED_THINGS:
                start = max(0, index - 2)
                chunk = [w for w in words[start:index]
                         if w and not _is_stop(w) and w not in _OWNED_THINGS]
                if chunk:
                    out.append(" ".join(chunk))

    low = fold_accents(raw).casefold()
    for cue in _BEFORE_NAME:
        pos = 0
        while True:
            found = low.find(cue, pos)
            if found < 0:
                break
            pos = found + len(cue)
            tail = re.findall(r"[A-Za-z][A-Za-z.'-]+", fold_accents(raw)[pos:pos + 48])
            chunk = [w for w in tail[:2] if not _is_stop(w)]
            if chunk:
                out.append(" ".join(chunk))

    # Capitalised naam-run: jab user bade akshar likhta hai to wo pakka signal
    # hai. intel chhote akshar likhta hai, isliye ye sirf extra hai — iske bharose
    # kuch nahi chhoda gaya.
    for match in re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2}\b",
                            fold_accents(raw)):
        if not any(_is_stop(part) for part in match.split()):
            out.append(match)

    return _unique(out, limit=6)


def deterministic_lenses(question: str) -> Dict:
    """Gemini ki ek bhi call ke bina lens plan.

    Chaar deterministic parat: (1) question ke apne shabd/phrase, (2) shabd ki
    banawat se discipline (``morpheme_disciplines``), (3) head-noun se framework
    ke naam (``framework_phrases``), (4) cue se sambhavit vyakti
    (``thinker_candidates``). Koi bhi parat "ye topic mujhe bataya gaya tha" par
    nahi chalti, isliye anjaan topic bhi lens paata hai — aur quota kharch 0.
    """
    concepts = _unique([
        *quoted_phrases(question),
        *hyphenated_compounds(question),
        *suffix_concepts(question),
        *content_phrases(question),
    ], limit=_MAX_ITEMS + 6)
    disciplines, families = morpheme_disciplines(question)
    thinkers = thinker_candidates(question)
    if thinkers:
        # Vyakti ka naam mila to unka apna likha hua/uspar hui study dhoondhni
        # chahiye — ye source family hai, koi claim nahi.
        families = _unique([*families,
                            "primary writings and collected papers",
                            "scholarly biographies and critical studies"],
                           limit=6)
    return {
        "concepts": concepts,
        "english_terms": english_vocabulary(question),
        "disciplines": disciplines,
        "frameworks": _unique([*framework_phrases(question),
                               *hyphenated_compounds(question),
                               *suffix_concepts(question)]),
        "thinkers": thinkers,
        "source_families": families,
        "method": "deterministic",
    }


# --------------------------------------------------------------------------
# Model raasta (optional, bounded). Ek chhoti call, sirf JSON, koi prose nahi.
# --------------------------------------------------------------------------

_LENS_PROMPT = """You are selecting RESEARCH LENSES for a question. You are NOT answering it.

QUESTION (keep original wording in mind; it may be Hindi, Hinglish or English):
{question}

Return ONLY a JSON object, no prose, no markdown fence, with these keys:
{{
  "disciplines": [up to 6 academic/professional fields that study this],
  "frameworks": [up to 8 named theories, models, effects or concepts that apply],
  "thinkers": [up to 6 people whose documented work is directly relevant],
  "source_families": [up to 6 kinds of sources to search, e.g. "peer-reviewed neuroscience journals", "public-domain Sanskrit texts on archive.org", "author's own free essays"],
  "english_terms": [up to 10 short English search/scoring terms],
  "concepts": [up to 10 short concept phrases from or implied by the question]
}}

Rules:
- Every entry must be a short plain string (max {maxchars} chars), no explanation.
- Name only real, documented disciplines/frameworks/people. If unsure, omit it.
- Do NOT quote or summarise any source. Do NOT state findings or conclusions.
- Do NOT invent citations, page numbers, dates or quotes.
- Empty list is a valid answer for any key.
"""


def build_prompt(question: str) -> str:
    return _LENS_PROMPT.format(
        question=_clean(question)[:400] or "(empty)",
        maxchars=_MAX_CHARS,
    )


_LENS_KEYS = (
    "disciplines", "frameworks", "thinkers", "source_families",
    "english_terms", "concepts",
)


def _extract_json(raw: str) -> Optional[dict]:
    """Model kabhi ```json fence ya thoda prose laga deta hai — pehla balanced
    object nikaalo. Kuch bhi galat ho to ``None`` (silently fallback hoga)."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:index + 1])
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _lens_items(value: object, limit: int = 8) -> List[str]:
    """Model ki ek list ko safe short strings me badlo.

    Sentence-jaisi entry (8+ shabd, ya sentence punctuation) jaan-boojh kar
    girayi jaati hai: lens list search plan hai, jagah claim ke liye nahi.
    Isse model ka koi conclusion galti se prompt/report me nahi pahunchta.
    """
    if isinstance(value, str):
        raw_items: Sequence[object] = [value]
    elif isinstance(value, (list, tuple)):
        raw_items = value
    else:
        return []
    out: List[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            item = item.get("name") or item.get("title") or ""
        if not isinstance(item, (str, int, float)):
            continue
        text = _clean(item)
        if not text or len(text.split()) > 8:
            continue
        if re.search(r"[.;!?]\s+\S", text):
            continue
        out.append(text.rstrip(".;"))
    return _unique(out, limit=limit)


def parse_model_lenses(raw: str) -> Optional[Dict]:
    """Strict-ish parse. Kuch bhi shaq wala ho to ``None`` — fallback chalega."""
    data = _extract_json(raw)
    if not data:
        return None
    plan = {
        "disciplines": _lens_items(data.get("disciplines"), 6),
        "frameworks": _lens_items(data.get("frameworks"), 8),
        "thinkers": _lens_items(data.get("thinkers"), 6),
        "source_families": _lens_items(data.get("source_families"), 6),
        "english_terms": _lens_items(data.get("english_terms"), 10),
        "concepts": _lens_items(data.get("concepts"), 10),
    }
    if not any(plan[key] for key in _LENS_KEYS):
        return None
    plan["method"] = "model"
    return plan


def _merge(base: Dict, extra: Dict) -> Dict:
    """Deterministic pehle (wo sawaal ke asli shabd hain), model uske baad."""
    limits = {
        "concepts": _MAX_ITEMS + 6, "english_terms": 14, "disciplines": 6,
        "frameworks": 10, "thinkers": 6, "source_families": 6,
    }
    out: Dict = {}
    for key, limit in limits.items():
        out[key] = _unique([*base.get(key, []), *extra.get(key, [])], limit=limit)
    return out


def build_lens_plan(
    question: str,
    base_query: str = "",
    generate: Optional[Callable[..., str]] = None,
    allow_model: bool = True,
) -> Dict:
    """Question → lens plan. Model optional, deterministic hamesha.

    ``generate`` ek callable hai (``GeminiReasoning.generate`` jaisa) jo prompt
    le kar text deta hai. Inject kiya jaata hai taaki ye module offline test ho
    sake aur ``lenses.py`` ko provider ka pata na rakhna pade.

    Model fail (quota, network, kharab JSON, koi bhi exception) → chup-chaap
    deterministic plan, ``model_used=False`` aur ``model_status`` me karan.
    Lens list kabhi evidence nahi — ``verified`` hamesha ``False``.
    """
    determ = deterministic_lenses(question)
    plan = dict(determ)
    model_status = "not_attempted"
    model_used = False

    if allow_model and generate is not None and _clean(question):
        try:
            raw = generate(build_prompt(question), "lens_selection")
            parsed = parse_model_lenses(raw if isinstance(raw, str) else "")
            if parsed:
                plan = _merge(determ, parsed)
                model_used = True
                model_status = "ok"
            else:
                model_status = "unusable_response_fell_back_to_deterministic"
        except Exception as exc:  # quota, network, provider — sab yahin
            model_status = f"{type(exc).__name__}_fell_back_to_deterministic"

    plan["method"] = "model_plus_deterministic" if model_used else "deterministic"
    plan["model_used"] = model_used
    plan["model_status"] = model_status
    plan["question_preserved"] = _clean(question)
    plan["base_query"] = _clean(base_query)
    plan["verified"] = False
    plan["evidence_status"] = (
        "search_plan_only__lens_names_are_not_citations_and_no_source_was_read"
    )
    return plan


# --------------------------------------------------------------------------
# Plan ka upyog: scoring vocabulary, search queries, prompt text.
# --------------------------------------------------------------------------

def scoring_vocabulary(plan: Dict) -> List[str]:
    """Relevance scoring ke liye sirf wo shabd jo sawaal me MOJOOD NAHI hain.

    Jaan-boojh kar deterministic ``concepts`` yahan se bahar hain — wo sawaal ke
    apne shabd hain, unhe dobara jodna sirf noise hai. Isliye ek pure-English
    sawaal par (jahan glossary aur model kuch nahi jodte) ye list **khaali**
    aati hai, aur scoring bilkul pehle jaisi rehti hai — yaani purane English
    benchmarks par ye change provably no-op hai.

    ``disciplines`` aur ``thinkers`` bhi jaan-boojh kar bahar hain. Wo
    morpheme/cue se BANAYE gaye anumaan hain (guess), aur relevance scoring wo
    jagah nahi jahan anumaan ka wazan pade — ek galat discipline off-topic source
    ko andar khinch sakta hai. Un dono ka istemaal sirf SEARCH query banane me
    hota hai (``lens_queries``), jahan galat guess ka natija sirf 0 result hai.

    Corpus-derived phrase (``corpus_frameworks``) bhi bahar hain: wo un sources
    se aaye hain jinhe hum ISI run me score kar rahe hain. Unhe scoring me
    wapas daalna apne hi retrieval ko inaam dena hoga (feedback loop), aur ek
    run ke beech me scoring badal jaane se round-1 aur round-2 ke score
    tulnaayog hi nahi rehte.
    """
    if not isinstance(plan, dict):
        return []
    have = {word for word in tokens(plan.get("question_preserved") or "")}
    have |= {stem(word) for word in have}
    from_corpus = {str(item).casefold()
                   for item in (plan.get("corpus_frameworks") or [])}
    out: List[str] = []
    for key in ("english_terms", "frameworks"):
        for item in plan.get(key) or []:
            if str(item).casefold() in from_corpus:
                continue
            item_tokens = tokens(item)
            if not item_tokens:
                continue
            if all(tok in have or stem(tok) in have for tok in item_tokens):
                continue
            out.append(item)
    return _unique(out, limit=14)


def scoring_query(plan: Dict) -> str:
    """English/lens anchor query — relevance ise SECOND query ki tarah use kare.

    Sawaal ke saath jod kar ek hi string banane se score girta hai (Hinglish
    tokens denominator badha dete hain aur kisi English source se match nahi
    karte). Isliye ye alag string deta hai; caller best-of le.
    """
    vocab = scoring_vocabulary(plan)
    if not vocab:
        return ""
    return _bounded(" ".join(vocab))


def _bounded(value: str, limit: int = 200) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].strip()


# --------------------------------------------------------------------------
# CORPUS-DERIVED LENSES — jo sources ASLI ME mile, unse aage ka soch.
#
# Ye wo parat hai jo app ko "padhte-padhte seekhne" wala banati hai, aur iske
# liye ek bhi model call nahi lagti:
#   * thinker  → author metadata (jo naam 2+ sources me aaya wo us baat ka
#                kendra hai; ye naam KISI list me nahi hai)
#   * discipline → venue/journal ka naam ("Journal of Cognitive Neuroscience"
#                  → "cognitive neuroscience")
#   * framework → wo phrase jo 2+ ALAG sources me dohraya gaya (ek source ki
#                 apni bhasha nahi, field ki saanjhi bhasha)
# Sab kuch sirf LENS hai: iska matlab ye NAHI ki wo baat sach hai ya wo source
# padh liya gaya. `verified` plan par False hi rehta hai.
# --------------------------------------------------------------------------

_VENUE_NOISE = {
    "journal", "journals", "of", "the", "international", "proceedings",
    "annual", "review", "reviews", "letters", "letter", "transactions",
    "advances", "frontiers", "in", "and", "for", "society", "american",
    "european", "british", "royal", "national", "academy", "sciences",
    "science", "nature", "plos", "one", "open", "access", "research",
    "reports", "report", "bulletin", "acta", "archives", "series", "new",
    "conference", "symposium", "workshop", "press", "university", "college",
    "publishing", "publishers", "ltd", "inc", "elsevier", "springer", "wiley",
    "taylor", "francis", "sage", "volume", "annals", "current", "trends",
    "quarterly", "monthly", "weekly", "online", "preprint", "arxiv", "biorxiv",
    "medrxiv", "ssrn", "wikipedia", "encyclopedia", "blog", "news", "times",
    "post", "magazine", "com", "org", "net",
}

# Phrase ke kinare par ye shabd concept ka naam nahi, kisi paper ka NATEEJA
# batate hain ("reduced sustained attention" → concept "sustained attention").
_PHRASE_EDGE_NOISE = {
    "reduced", "reduces", "reducing", "increased", "increases", "increasing",
    "improved", "improves", "improving", "impaired", "impairs", "degraded",
    "degrades", "higher", "lower", "greater", "smaller", "larger", "significant",
    "significantly", "showed", "shows", "shown", "found", "finds", "measured",
    "measures", "predicted", "predicts", "observed", "observes", "associated",
    "correlated", "using", "used", "based", "during", "across", "within",
    "overall", "however", "whether", "compared", "versus", "study", "studies",
    "paper", "papers", "article", "results", "result", "data", "evidence",
    "these", "those", "their", "there", "here", "also", "than", "such",
    "more", "most", "less", "least", "very", "many", "much", "both", "each",
    "new", "novel", "recent", "current", "present", "previous", "first",
    "second", "third", "healthy", "adults", "adult", "participants", "subjects",
}


def _trim_edges(words: Sequence[str]) -> List[str]:
    """Phrase ke aage-peechhe ke nateeja/bharti shabd kaato."""
    out = list(words)
    while out and out[0] in _PHRASE_EDGE_NOISE:
        out.pop(0)
    while out and out[-1] in _PHRASE_EDGE_NOISE:
        out.pop()
    return out


def venue_disciplines(records: Sequence[object], limit: int = 6) -> List[str]:
    """Venue/publisher naam se field ka anumaan (noise shabd hata kar).

    Jo venue ZYADA sources me aaya wo pehle — ek akele off-topic source ka
    journal peechhe chala jaata hai.
    """
    counts: Dict[str, int] = {}
    shown: Dict[str, str] = {}
    order: Dict[str, int] = {}
    for index, record in enumerate(records or []):
        for raw in (getattr(record, "venue", "") or "",
                    getattr(record, "publisher", "") or ""):
            words = [w for w in tokens(raw) if len(w) > 2
                     and w not in _VENUE_NOISE and not _is_stop(w)]
            if not words:
                continue
            phrase = " ".join(words[:3])
            if not phrase:
                continue
            key = phrase.casefold()
            counts[key] = counts.get(key, 0) + 1
            shown.setdefault(key, phrase)
            order.setdefault(key, index)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], order[kv[0]]))
    return _unique([shown[key] for key, _ in ordered], limit=limit)


def author_thinkers(records: Sequence[object], min_repeat: int = 2,
                    limit: int = 5) -> List[str]:
    """Jo author 2+ mile hue sources me hai — us baat ka kendra."""
    counts: Dict[str, int] = {}
    shown: Dict[str, str] = {}
    for record in records or []:
        seen_here = set()
        for name in (getattr(record, "authors", None) or [])[:6]:
            clean = _clean(name)
            if len(clean) < 4 or len(clean.split()) > 4:
                continue
            key = clean.casefold()
            if key in seen_here:
                continue
            seen_here.add(key)
            counts[key] = counts.get(key, 0) + 1
            shown.setdefault(key, clean)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return _unique([shown[key] for key, count in ordered if count >= min_repeat],
                   limit=limit)


def repeated_phrases(records: Sequence[object], question: str = "",
                     min_repeat: int = 2, limit: int = 8) -> List[str]:
    """2-3 shabd ke wo phrase jo 2+ ALAG sources me aaye.

    Ek hi source ka dohraav nahi ginte — warna ek blog ka apna takiya-kalaam
    "framework" ban jaata. Sawaal me pehle se maujood phrase bhi chhod dete hain
    (usse nayi disha nahi milti).

    Do safai ki parat, dono probe se aayi hain:
      * kinare ke "nateeja" shabd hata dete hain — "reduced sustained attention"
        ka concept "sustained attention" hai; "reduced" us paper ka result hai,
        field ka naam nahi.
      * jo chhota phrase kisi bade rakhe hue phrase ke ANDAR hai wo nahi jodte —
        warna "slow wave sleep", "wave sleep", "slow wave" teen queries kha
        jaate hain aur teeno ek hi cheez hai.
    """
    have = {word for word in tokens(question or "")}
    have |= {stem(word) for word in have}
    counts: Dict[str, int] = {}
    shown: Dict[str, str] = {}
    for record in records or []:
        text = f"{getattr(record, 'title', '') or ''}. " \
               f"{(getattr(record, 'snippet', '') or '')[:600]}"
        here: Dict[str, str] = {}
        words = [w for w in (t.strip("-") for t in tokens(text)) if len(w) > 2]
        for size in (2, 3):
            for index in range(len(words) - size + 1):
                chunk = _trim_edges(words[index:index + size])
                if len(chunk) < 2 or any(_is_stop(word) for word in chunk):
                    continue
                if all(word in have or stem(word) in have for word in chunk):
                    continue
                phrase = " ".join(chunk)
                here.setdefault(phrase.casefold(), phrase)
        for key, phrase in here.items():
            counts[key] = counts.get(key, 0) + 1
            shown.setdefault(key, phrase)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    out: List[str] = []
    for key, count in ordered:
        if count < min_repeat:
            continue
        if any(f" {key} " in f" {kept.casefold()} " for kept in out):
            continue        # bade phrase ke andar ka tukda — dobara nahi
        out.append(shown[key])
    return _unique(out, limit=limit)


def lenses_from_sources(records: Sequence[object], question: str = "",
                        min_repeat: int = 2) -> Dict:
    """Mile hue sources se naye lens. Koi model call nahi, koi network nahi."""
    rows = list(records or [])
    return {
        "disciplines": venue_disciplines(rows),
        "thinkers": author_thinkers(rows, min_repeat=min_repeat),
        "frameworks": repeated_phrases(rows, question=question,
                                       min_repeat=min_repeat),
        "concepts": [],
        "english_terms": [],
        "source_families": [],
        "sources_seen": len(rows),
    }


def merge_corpus_lenses(plan: Dict, corpus: Dict) -> Dict:
    """Corpus lens ko plan me jodo — plan ki honesty fields chhue bina.

    Scoring anchor JAAN-BOOJHKAR nahi badalta: ek hi run ke beech me scoring
    hilne se pehle wale round ke scores baad wale se compare hi nahi kiye ja
    sakte. Corpus lens sirf AGLI QUERIES banata hai.
    """
    if not isinstance(plan, dict):
        return plan
    out = dict(plan)
    corpus = corpus if isinstance(corpus, dict) else {}
    merged = _merge(plan, corpus)
    for key, value in merged.items():
        out[key] = value
    # Kaun-kaun se phrase corpus se aaye — scoring_vocabulary ise dekh kar unhe
    # scoring se bahar rakhti hai (apne hi retrieval ko inaam na mile).
    out["corpus_frameworks"] = _unique(
        [*(plan.get("corpus_frameworks") or []), *(corpus.get("frameworks") or [])],
        limit=20)
    out["corpus_sources_seen"] = int(corpus.get("sources_seen") or 0)
    out["corpus_derived"] = True
    method = str(plan.get("method") or "deterministic")
    if "corpus" not in method:
        out["method"] = f"{method}_plus_corpus"
    out["verified"] = False
    return out


def lens_queries(plan: Dict, base: str = "", round_no: int = 1,
                 limit: int = 4) -> List[str]:
    """Lens-driven search queries. Round badhne par lens gehre jaate hain.

    Round 1 = sabse specific (concept + framework), round 2 = thinker ka apna
    likha, round 3+ = discipline/source-family. Base query hamesha pehli rehti
    hai taaki lens galat nikle to bhi normal search chalti rahe.
    """
    if not isinstance(plan, dict):
        return _unique([base], limit=limit)
    base_clean = _bounded(base or plan.get("base_query") or
                          plan.get("question_preserved") or "")
    concepts = plan.get("concepts") or []
    frameworks = plan.get("frameworks") or []
    thinkers = plan.get("thinkers") or []
    disciplines = plan.get("disciplines") or []
    families = plan.get("source_families") or []
    english = plan.get("english_terms") or []
    anchor = " ".join(english[:3])

    out: List[str] = [base_clean] if base_clean else []
    if round_no <= 1:
        out += [f"{item} {anchor}".strip() for item in frameworks[:2]]
        out += [f"{item} {anchor}".strip() for item in concepts[:2]]
    elif round_no == 2:
        out += [f"{name} {anchor}".strip() for name in thinkers[:2]]
        out += [f"{item} evidence review" for item in frameworks[:1]]
    else:
        out += [f"{field} {anchor}".strip() for field in disciplines[:2]]
        out += [f"{family} {anchor}".strip() for family in families[:2]]
    if round_no >= 2 and base_clean:
        out.append(f"{base_clean} criticism limitations counter evidence")
    return _unique([_bounded(item) for item in out if _clean(item)], limit=limit)


def prompt_block(plan: Dict) -> str:
    """Reasoning prompt ke liye text. Honesty line hamesha saath jaati hai."""
    if not isinstance(plan, dict):
        return ""
    rows = [
        ("Disciplines", plan.get("disciplines")),
        ("Frameworks / concepts", plan.get("frameworks")),
        ("Thinkers (documented work only)", plan.get("thinkers")),
        ("Source families to prefer", plan.get("source_families")),
        ("English search vocabulary", plan.get("english_terms")),
        ("Concept phrases from the question", plan.get("concepts")),
    ]
    lines = [line for line in
             (f"- {label}: {', '.join(values)}" for label, values in rows if values)]
    if not lines:
        return ""
    head = "LENS PLAN (search plan only, NOT evidence):"
    tail = (
        "These lens names were selected before reading anything. They are NOT "
        "citations and do NOT show that any thinker said this. Use them only to "
        "decide what to look for. Every claim must still come from a source that "
        "was actually retrieved and read."
    )
    method = (
        f"Selected by: {plan.get('method', 'deterministic')} "
        f"(model_used={bool(plan.get('model_used'))}, "
        f"status={plan.get('model_status', 'not_attempted')})"
    )
    return "\n".join([head, *lines, method, tail])


def lens_summary(plan: Dict) -> Dict:
    """Report/UI ke liye chhota, honest snapshot."""
    if not isinstance(plan, dict):
        return {"lens_selected": False}
    counts = {key: len(plan.get(key) or []) for key in _LENS_KEYS}
    return {
        "lens_selected": any(counts.values()),
        "method": plan.get("method", "deterministic"),
        "model_used": bool(plan.get("model_used")),
        "model_status": plan.get("model_status", "not_attempted"),
        "counts": counts,
        "disciplines": list(plan.get("disciplines") or [])[:6],
        "frameworks": list(plan.get("frameworks") or [])[:8],
        "thinkers": list(plan.get("thinkers") or [])[:6],
        "verified": False,
        "evidence_status": plan.get("evidence_status", "search_plan_only"),
    }
