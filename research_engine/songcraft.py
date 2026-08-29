"""#128-#131 — SONGCRAFT: gaana likhne se PEHLE craft padho, phir bhaav/style naapo.

CRAFT (#121) ne ek khaali jagah bhari thi: draft ka DHAANCHA (matra, tuk,
dohraav, hook) khud naapa jaane laga. Par intel ki maang usse aage ki hai —
"gaana likhne ka bhi style hota hai... me sad bolu to sad likhe, danceing type
punjabi ya gangstar, jo type bolu usi prkar sochna read krna sab aana chahiye,
or use music bnana konsa tone bnega".

Isliye ye module teen kaam karta hai, teeno deterministic aur ₹0:

    1. STYLE ASK padho  — kaunsa lehja/genre maanga gaya, kaunsi bhasha, kaunsa
       register (shudh vs galli ki zubaan), kaunsa tempo-parivaar.
    2. CRAFT PADHO      — songwriting/prosody ki kitaab, music theory, aur
       emotion/affect ki research ke liye SEARCH QUERY banao (discovery lane
       chalata hai, ye module network nahi chhoota) aur jo padha gaya usme se
       CITED hidayat nikaalo (har line ke saath source id).
    3. NAAP             — bhaav ka failaav, thos (concrete) shabd, register ka
       nibhna, gaaye jaane laayak line, padhi hui convention se milaan, aur
       music direction ka hona. Har naap MET / NOT_MET / NOT_MEASURED.

JO YE MODULE JAAN-BOOJH KAR NAHI KARTA (aur report me naam se likhta hai):

  * "sunne wale ko feeling aayegi" — ye naapa hi nahi ja sakta. Shabd ginna
    bhaav ka saboot nahi; isliye check ka naam bhi `mood_spread` hai,
    `emotion_achieved` nahi.
  * Koi AUDIO nahi banta (`AUDIO_GENERATED = False`). Music direction ek LIKHI
    HUI salaah hai — "dhun achhi banegi" ka daawa nahi. Aisa daawa mile to wo
    khud ek FAIL check hai.
  * Kisi maujooda gaane ke BOL nahi laaye jaate. Craft ke BAARE me padhna aur
    kisi ka gaana utha lena do alag baat hain — `is_lyrics_hunt()` har banayi
    hui query par lagta hai aur lyrics-download jaisi query banne hi nahi deta.
  * Style ki list adhoori hai (`STYLE_LIST_IS_NOT_EXHAUSTIVE`). Table sirf
    ADDRESSING hai — "user ne kis cheez ka naam liya". Us style ka asli taqaza
    padhi hui source se aata hai; kuch padha na gaya to convention wala naap
    `NOT_MEASURED` rehta hai (`style_conventions_not_read`), "sab theek" nahi.
  * Thos/abstract shabd ki list bhi adhoori hai (`IMAGE_LIST_IS_NOT_EXHAUSTIVE`).

Ek hi draft par wahi number, har baar — koi randomness nahi, koi model call
nahi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import lang_bridge

# ── naap ki zubaan ────────────────────────────────────────────────────────────
# Ye teen literal JAAN-BOOJH KAR craft.py se import NAHI kiye jaate: craft
# songcraft ko import karta hai, ulta import karne se circular ho jaata. Test
# `songcraft.MET == craft.MET` ko pin karta hai, taaki dono kabhi alag na hon.
MET = "MET"
NOT_MET = "NOT_MET"
NOT_MEASURED = "NOT_MEASURED"
CHECK_STATUSES = (MET, NOT_MET, NOT_MEASURED)

# Sach jo report me har baar likha jaata hai
AUDIO_GENERATED = False               # yahan koi dhun/audio nahi banti
MUSIC_DIRECTION_IS_SUGGESTION = True  # music wali baat salaah hai, saboot nahi
STYLE_LIST_IS_NOT_EXHAUSTIVE = True   # neeche ki style table adhoori hai
IMAGE_LIST_IS_NOT_EXHAUSTIVE = True   # thos/abstract shabd ki list adhoori hai
NETWORK_USED = False                  # query BANATA hai, chalata nahi
GEMINI_CALLS = 0                      # style/guidance me ek bhi model call nahi

# craft.CANNOT_MEASURE ke SAATH judne wali list (usse replace nahi karti)
CANNOT_MEASURE_EXTRA = (
    "sunne wale ko sach me feeling aayegi ya nahi (shabd ginna bhaav ka saboot nahi)",
    "dhun/melody achhi banegi ya nahi (yahan koi audio bana hi nahi)",
    "gaayak ki aawaz aur delivery kaisi lagegi",
    "music direction bajane par sach me kaam karegi ya nahi (ye likhi hui salaah hai)",
    "kisi maujooda gaane/bol se milta-julta hai ya nahi (copyright/originality)",
    "kis style ka asli taqaza kya hai, jab tak wo kisi padhi hui source me na mile",
)

# ── STYLE TABLE — ye ADDRESSING hai, KNOWLEDGE nahi ──────────────────────────
# #118 ke `_WB_INDICATORS` ka wahi niyam: haath se likhi cue-table sirf itna bata
# sakti hai ki "user ne kis cheez ka NAAM liya". Us style me sach me kya hota hai
# (kitni line ka mukhda, kaunsa taal, kaisa bhaav) wo YAHAN NAHI likha — wo padhi
# hui source se aata hai. Isliye:
#   * kisi bhi MET/NOT_MET check ka faisla is table ke `tempo_family` par NAHI
#     tikta — wo sirf prompt/music-direction ki salaah me jaata hai,
#   * `style_fit_structure` tab tak NOT_MEASURED rehta hai jab tak kisi padhi hui
#     source me asli number na mile.
@dataclass(frozen=True)
class Style:
    style_id: str
    label: str
    cues: Tuple[str, ...]
    tempo_family: str = ""          # sirf maang ka naam: slow / mid / fast
    study_terms: Tuple[str, ...] = ()


STYLES: Tuple[Style, ...] = (
    Style("sad_slow", "sad / dard bhara (dheema)",
          ("sad", "sadd", "dukh", "dukhi", "dard", "gham", "gam", "udaas",
           "udas", "rula", "rulane", "rone", "breakup", "break-up", "judai",
           "judaai", "bewafa", "bewafai", "heartbreak", "tanha", "tanhai",
           "viraha", "melancholy", "emotional"),
          "slow",
          ("sad ballad songwriting", "melancholy lyric writing craft")),
    Style("dance_party", "dance / party (tez)",
          ("dance", "dancing", "danceing", "dancig", "nach", "naach",
           "nachne", "thumka", "party", "club", "dj", "remix", "banger",
           "dhamaka", "bhangra", "bhangda", "garba", "dandiya", "festive"),
          "fast",
          ("dance song structure hook writing", "groove rhythm songwriting")),
    Style("rap_street", "rap / hip-hop / gangster street",
          ("rap", "rapp", "rapper", "hiphop", "hip-hop", "hip hop", "gangster",
           "gangsta", "gangstar", "gangster type", "drill", "trap", "bars",
           "diss", "cypher", "street", "gully", "desi hip hop", "flow"),
          "mid",
          ("rap lyric writing flow rhyme craft",
           "hip hop songwriting technique")),
    Style("devotional", "bhajan / kirtan / bhakti",
          ("bhajan", "bhjn", "kirtan", "keertan", "aarti", "arti", "bhakti",
           "devotional", "satsang", "hymn", "stuti", "chalisa"),
          "slow",
          ("bhajan kirtan composition tradition",
           "devotional song lyric structure")),
    Style("sufi_ghazal", "sufi / ghazal / qawwali",
          ("sufi", "sufiyana", "ghazal", "gazal", "gjl", "qawwali", "qawali",
           "kawwali", "nazm", "sher", "shayarana", "khayal"),
          "slow",
          ("ghazal radif qafiya form rules",
           "qawwali sufi poetry composition")),
    Style("romantic", "romantic / pyaar bhara",
          ("romantic", "romance", "pyaar", "pyar", "ishq", "mohabbat",
           "muhabbat", "love song", "love-song", "valentine", "chahat",
           "aashiqui", "aashiqi"),
          "mid",
          ("romantic song lyric imagery craft",)),
    Style("patriotic", "deshbhakti",
          ("deshbhakti", "desh bhakti", "patriotic", "patriotism", "vatan",
           "watan", "tiranga", "fauji", "army", "jawan", "shaheed", "desh ka"),
          "mid",
          ("patriotic song lyric tradition",)),
    Style("motivational", "motivation / himmat",
          ("motivation", "motivational", "motivate", "himmat", "hausla",
           "josh", "struggle", "hustle", "gym", "workout", "jeet", "winner",
           "inspire", "inspirational"),
          "fast",
          ("motivational anthem songwriting",)),
    Style("folk_regional", "folk / lok geet",
          ("folk", "lokgeet", "lok geet", "loksangeet", "boliyan", "birha",
           "sohar", "teej", "lavani", "baul", "rajasthani folk", "dhol geet"),
          "mid",
          ("folk song oral tradition structure",)),
    Style("lofi_indie", "lofi / indie / soft pop",
          ("lofi", "lo-fi", "lo fi", "indie", "acoustic", "soft pop",
           "chill", "aesthetic", "coffee shop"),
          "slow",
          ("indie songwriting minimal arrangement",)),
    Style("kids_simple", "bachchon ka / simple",
          ("bachcho", "bachchon", "bacho", "kids", "nursery", "rhyme for kids",
           "children", "balgeet", "bal geet"),
          "mid",
          ("children song writing repetition rhyme",)),
    Style("comedy_masti", "comedy / masti",
          ("comedy", "funny", "mazak", "majak", "masti", "hasane", "hasi wala",
           "parody", "satire", "vyang"),
          "fast",
          ("comic song parody lyric writing",)),
)

# REGISTER = lehja. "sudh hindi me mat likho" intel ki saaf maang thi, isliye
# register alag se padha jaata hai. Sirf un register ka NUMERIC niyam hai jinka
# naap ho sakta hai; baaki `register_consistency` me NOT_MEASURED rehte hain
# (kyunki "aasan shabd" ka koi imaandaar counter humare paas nahi hai).
@dataclass(frozen=True)
class Register:
    register_id: str
    label: str
    cues: Tuple[str, ...]
    max_english_share: Optional[float] = None   # None = naap ka niyam nahi
    max_devanagari_share: Optional[float] = None


REGISTERS: Tuple[Register, ...] = (
    Register("shudh", "shudh / khaalis Hindi",
             ("shudh", "shuddh", "sudh", "sudhh", "pure hindi", "pura hindi",
              "sirf hindi", "khaalis", "khalis", "sanskritnishth", "tatsam",
              "saaf hindi"),
             max_english_share=0.08),
    Register("street", "galli / tapori zubaan",
             ("street", "tapori", "galli", "gali ki", "gully", "slang",
              "desi slang", "raw", "kaccha", "thug", "roadside"),
             None),
    Register("urdu_heavy", "Urdu-heavy / shayarana",
             ("urdu", "urdoo", "shayarana", "nazm", "sher-o-shayari",
              "farsi", "adabi"),
             None),
    Register("simple", "aasan / aam bol-chaal",
             ("aasan", "aasaan", "asan", "simple", "saral", "easy words",
              "aam bol chaal", "bolchaal", "seedha", "sidha"),
             None),
    Register("english_only", "sirf English",
             ("english only", "only english", "in english", "english me",
              "english mein", "pure english"),
             max_devanagari_share=0.02),
    Register("mixed", "Hinglish / mila-jula",
             ("hinglish", "mix", "mixed", "mila jula", "half english",
              "english mix"),
             None),
)
REGISTER_LIST_IS_NOT_EXHAUSTIVE = True

# BHASHA ki maang. "punjabi" ek style nahi, bhasha hai — intel ne "danceing type
# punjabi" kaha tha, yaani dono ek saath aa sakte hain. Isliye do alag axis.
# Ye table bhi sirf ADDRESSING hai: bhasha ka naam pakadta hai, us bhasha ke
# gaane ka niyam nahi jaanta.
LANGUAGE_ASKS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("punjabi", "Punjabi", ("punjabi", "panjabi", "pnjbi", "punjbi",
                            "bhangra", "boliyan", "sardar")),
    ("haryanvi", "Haryanvi", ("haryanvi", "hariyanvi", "haryanavi", "ragni")),
    ("bhojpuri", "Bhojpuri", ("bhojpuri", "bhojpuri me", "birha")),
    ("rajasthani", "Rajasthani", ("rajasthani", "marwari", "mand")),
    ("marathi", "Marathi", ("marathi", "marathi me", "lavani")),
    ("gujarati", "Gujarati", ("gujarati", "garba geet")),
    ("bengali", "Bengali", ("bengali", "bangla", "baul")),
    ("tamil", "Tamil", ("tamil", "tamizh")),
    ("telugu", "Telugu", ("telugu",)),
    ("kannada", "Kannada", ("kannada",)),
    ("malayalam", "Malayalam", ("malayalam",)),
    ("urdu", "Urdu", ("urdu", "urdoo")),
    ("english", "English", ("english", "angrezi", "angreji")),
    ("hindi", "Hindi", ("hindi", "hindi me", "hindi mein", "hindustani")),
)
LANGUAGE_LIST_IS_NOT_EXHAUSTIVE = True

# tempo-parivaar ke naam. Ye SIRF salaah ke liye hai — koi check ispar nahi
# tikta, kyunki "kis gaane ka kaunsa BPM hona chahiye" ek knowledge claim hai
# jo padhi hui source se aana chahiye, cue-table se nahi.
TEMPO_FAMILIES: Dict[str, str] = {
    "slow": "dheema (ballad jaisa) — maang ke naam se lagaya gaya, padha hua "
            "number nahi",
    "mid": "madhyam chaal — maang ke naam se lagaya gaya, padha hua number nahi",
    "fast": "tez (dance jaisa) — maang ke naam se lagaya gaya, padha hua "
            "number nahi",
}

# ── cue milaan (shabd poora milna chahiye) ───────────────────────────────────
# "sad" cue ko "sadak" me match NAHI hona chahiye (warna thos-shabd wala naap
# hi ulta ho jaata). Isliye pehle text ko shabdon me toda jaata hai, phir poora
# shabd/phrase dhoondha jaata hai.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _norm(text: Any) -> str:
    words = _WORD_RE.findall(str(text or "").lower())
    return " " + " ".join(words) + " " if words else " "


def _cue_present(norm_text: str, cue: str) -> bool:
    phrase = " ".join(_WORD_RE.findall(str(cue or "").lower()))
    return bool(phrase) and f" {phrase} " in norm_text


def _matched_cues(norm_text: str, cues: Iterable[str]) -> List[str]:
    return [cue for cue in cues if _cue_present(norm_text, cue)]


@dataclass
class StyleAsk:
    """User ne kya NAAM liya — iska matlab "us style ka gyaan aa gaya" nahi hai."""
    styles: List[str] = field(default_factory=list)
    style_labels: List[str] = field(default_factory=list)
    primary: str = ""
    primary_label: str = ""
    tempo_family: str = ""
    registers: List[str] = field(default_factory=list)
    register_labels: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    language_labels: List[str] = field(default_factory=list)
    moods: List[str] = field(default_factory=list)
    form: str = ""
    question_script: str = ""
    matched_cues: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def asked_anything(self) -> bool:
        return bool(self.styles or self.registers or self.languages or self.moods)

    def study_terms(self) -> List[str]:
        terms: List[str] = []
        for style in STYLES:
            if style.style_id in self.styles:
                terms.extend(style.study_terms)
        return terms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "styles": list(self.styles),
            "style_labels": list(self.style_labels),
            "primary": self.primary,
            "primary_label": self.primary_label,
            "tempo_family": self.tempo_family,
            "tempo_note": TEMPO_FAMILIES.get(self.tempo_family, ""),
            "registers": list(self.registers),
            "register_labels": list(self.register_labels),
            "languages": list(self.languages),
            "language_labels": list(self.language_labels),
            "moods": list(self.moods),
            "form": self.form,
            "question_script": self.question_script,
            "matched_cues": list(self.matched_cues),
            "notes": list(self.notes),
            # ye chaar line har baar jaati hain — inhe hataana ek jhooth hoga
            "style_table_is_addressing_only": True,
            "style_list_is_not_exhaustive": STYLE_LIST_IS_NOT_EXHAUSTIVE,
            "tempo_is_ask_name_only": True,
            "audio_generated": AUDIO_GENERATED,
        }


def style_of(question: str, form: str = "",
             moods: Sequence[str] = ()) -> StyleAsk:
    """Sawaal me se style/register/bhasha ki MAANG nikaalo (koi network, koi model).

    `moods` craft ke `mood_hints()` se aata hai — songcraft usse dobara nahi
    ginta, taaki ek hi cheez do jagah alag na nikle.
    """
    text = str(question or "")
    norm = _norm(text)
    roman_norm = _norm(lang_bridge.roman(text)) if text else " "
    ask = StyleAsk(form=str(form or ""),
                   moods=[str(m) for m in (moods or ()) if str(m).strip()],
                   question_script=lang_bridge.dominant_script(text) if text else "unknown")

    for style in STYLES:
        hits = _matched_cues(norm, style.cues) or _matched_cues(roman_norm, style.cues)
        if hits:
            ask.styles.append(style.style_id)
            ask.style_labels.append(style.label)
            ask.matched_cues.extend(hits)

    if ask.styles:
        ask.primary = ask.styles[0]
        ask.primary_label = ask.style_labels[0]
        for style in STYLES:
            if style.style_id == ask.primary:
                ask.tempo_family = style.tempo_family
                break
    else:
        ask.notes.append(
            "style ka naam nahi mila — is table me jo naam hain unme se koi "
            "nahi bola gaya (table adhoori bhi hai)")

    for register in REGISTERS:
        hits = (_matched_cues(norm, register.cues)
                or _matched_cues(roman_norm, register.cues))
        if hits:
            ask.registers.append(register.register_id)
            ask.register_labels.append(register.label)
            ask.matched_cues.extend(hits)

    for lang_id, label, cues in LANGUAGE_ASKS:
        hits = _matched_cues(norm, cues) or _matched_cues(roman_norm, cues)
        if hits:
            ask.languages.append(lang_id)
            ask.language_labels.append(label)
            ask.matched_cues.extend(hits)

    # "shudh hindi mat likho" ULTA hai — mana kiya gaya hai, maanga nahi.
    # Ise pakadna zaroori hai warna register ka naap ulta lag jaata.
    if "shudh" in ask.registers and _NEGATED_SHUDH_RE.search(text):
        ask.registers = [r for r in ask.registers if r != "shudh"]
        ask.register_labels = [
            r.label for r in REGISTERS if r.register_id in ask.registers]
        ask.notes.append(
            "'shudh hindi' mana kiya gaya tha (maanga nahi) — isliye shudh ka "
            "naap nahi lagaya")

    seen: set = set()
    ask.matched_cues = [c for c in ask.matched_cues
                        if not (c in seen or seen.add(c))]
    return ask


# "aese nhi sudh hindi me" = MANA kiya gaya, MAANGA nahi. Bare "na" jaan-boojh
# kar list me nahi hai ("banao na" ko mana samajh lena ek naya jhooth hota).
_NEGATED_SHUDH_RE = re.compile(
    r"\b(?:nahi|nhi|mat|bina|avoid|without|don'?t|no)\b[^.\n]{0,24}?"
    r"\b(?:shudh|shuddh|sudh|sudhh|khaalis|khalis|pure\s+hindi)\b"
    r"|\b(?:shudh|shuddh|sudh|sudhh|khaalis|khalis|pure\s+hindi)\b"
    r"[^.\n]{0,24}?\b(?:nahi|nhi|mat|avoid)\b", re.I)


# ── #129 CRAFT PADHO: query banao (network yahan nahi chhoota) ────────────────
# Craft ke BAARE me padhna (songwriting kitaab, prosody, music-emotion research)
# aur kisi ka gaana utha lena DO ALAG BAAT hain. Neeche ka guard doosri baat ko
# structurally rokta hai: koi bhi banayi hui query is regex par giri to wo list
# me hi nahi jaati (aur test isi baat ko pin karta hai).
_LYRICS_HUNT_RE = re.compile(
    r"\blyrics?\s+(?:of|for|from|download|pdf|mp3|copy|sheet)\b"
    r"|\b(?:full|complete|original|entire|all)\s+lyrics?\b"
    r"|\blyrics?\s*[-:–]\s*\w"
    r"|\bkaraoke\b|\bmp3\b|\btorrent\b"
    r"|\bgaane?\s+ke\s+bol\b|\bgeet\s+ke\s+bol\b|\bbol\s+download\b"
    r"|\bsong\s+download\b|\bfree\s+download\b", re.I)


def is_lyrics_hunt(query: str) -> bool:
    """True = ye query kisi maujooda gaane ke BOL/file dhoondh rahi hai."""
    return bool(_LYRICS_HUNT_RE.search(str(query or "")))


# Har seed ke saath `why` jaata hai, taaki report me dikhe "ye query kis liye
# chali". Lane ke naam planner/source_discovery ke tier naam hain.
#
# Lane ka poora vocabulary EK hi jagah (ye list), taaki naya lane jodte waqt
# test aur code do alag sach na bolein. `source_discovery._tasks()` inhi naamon
# par route karta hai; is list se bahar ka lane wahan koi connector nahi paata
# aur web fallback par chala jaata hai (chup-chaap gum nahi hota).
STUDY_LANES: Tuple[str, ...] = ("web", "books", "papers", "media")

CRAFT_STUDY_SEEDS: Tuple[Tuple[str, str, str], ...] = (
    # Media seed PEHLA hai jaan-boojh kar. Wajah naapi hui hai: dynamic queries
    # (style + bhasha + mood) 4 slot le sakti hain, isliye jo seed peeche hai wo
    # bure haalat me chalta hi nahi. intel ki maang me "logo ki recording" bhi
    # hai, sirf kitaab nahi — to us lane ko pehla slot milta hai. Ye media
    # DEKHNE/SUNNE ka daawa nahi hai: lane sirf recording ka LIKHA HUA parichay
    # padhta hai (`connectors/media_connector.py`).
    ("songwriting masterclass interview lecture recording", "media",
     "gaana likhne walon ki apni baat — lecture/interview recording se"),
    ("songwriting craft lyric writing guide", "books",
     "gaana likhne ka hunar — kitaab se"),
    ("prosody meter syllable stress in song lyrics", "papers",
     "matra/stress ka niyam — research se"),
    ("music and emotion listener affect research", "papers",
     "kaunsi cheez sunne wale ke bhaav se judti hai — research se"),
    ("melody rhythm tempo composition basics", "books",
     "dhun/taal ki buniyaad — music theory kitaab se"),
    ("verse chorus hook song structure conventions", "web",
     "mukhda-antara-hook ka dhaancha"),
)


# 5 se 6 kiya gaya (#133b): ek naya lane (media) juda hai, aur purane paanch me
# se kisi ki jagah lena galat hota — kitaab/paper/web ki coverage waisi hi rehni
# chahiye jaisi #129 me naapi gayi thi. Chhat phir bhi chhoti hai: har query par
# `craft_limit` 1-2 hi hai (source_discovery), yaani ye tier asli sawaal ka
# budget nahi kha sakta.
MAX_STUDY_QUERIES = 6
MIN_STUDY_QUERY_CHARS = 8


def study_queries(ask: StyleAsk,
                  limit: int = MAX_STUDY_QUERIES) -> List[Dict[str, str]]:
    """Craft padhne ke liye query list — sabse tez (style-specific) pehle.

    Ye function SIRF string banata hai. Network `source_discovery` chhoota hai,
    isliye yahan koi cost, koi rate limit, koi randomness nahi.
    """
    out: List[Dict[str, str]] = []
    seen: set = set()
    limit = max(1, int(limit or 1))

    def push(query: str, lane: str, why: str) -> None:
        clean = " ".join(str(query or "").split())
        if len(clean) < MIN_STUDY_QUERY_CHARS or len(out) >= limit:
            return
        if is_lyrics_hunt(clean):       # bol/file dhoondhne wali query kabhi nahi
            return
        key = clean.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append({"query": clean, "lane": lane, "why": why})

    for term in ask.study_terms()[:2]:
        push(term, "books",
             f"{ask.primary_label or 'is style'} ka hunar — kitaab/paper se")
    for label in ask.language_labels[:1]:
        push(f"{label} song lyric writing tradition structure", "web",
             f"{label} gaane ki apni reet")
    for mood in ask.moods[:1]:
        # NOTE: yahan "gaane ke bol" jaisa shabd jaan-boojh kar nahi hai — humara
        # apna `is_lyrics_hunt` guard use blocked kar deta (aur wo theek karta).
        push(f"{mood} bhaav gaane me kaise likha jaata hai", "web",
             f"'{mood}' bhaav likhne ka tareeqa")
    for query, lane, why in CRAFT_STUDY_SEEDS:
        push(query, lane, why)
    return out


def study_plan(ask: StyleAsk, limit: int = MAX_STUDY_QUERIES) -> Dict[str, Any]:
    """planner ke liye ek hi dict — `craft_study` lane isi se banti hai."""
    queries = study_queries(ask, limit=limit)
    return {
        "craft_study": bool(queries),
        "craft_study_queries": [row["query"] for row in queries],
        "craft_study_reasons": [row["why"] for row in queries],
        "craft_study_lanes": [row["lane"] for row in queries],
        "craft_study_note": (
            "gaana likhne ka hunar padhne ke liye query banayi gayi — kisi "
            "maujooda gaane ke bol NAHI dhoondhe ja rahe"
            if queries else "koi craft-study query nahi bani"),
        "lyrics_hunt_blocked": True,
        "network_used_here": NETWORK_USED,
        "gemini_calls_here": GEMINI_CALLS,
    }


# ── #130 JO PADHA GAYA USME SE HIDAYAT (har line ke saath source id) ──────────
# Niyam: BINA source id koi line nahi. Agar kuch padha hi nahi gaya to block
# saaf-saaf kehta hai "kuch padha nahi gaya" — apne aap se salaah GHADI nahi
# jaati. Isi wajah se `guidance_source_count: 0` bhi report me jaata hai.
CRAFT_CUES: Tuple[str, ...] = (
    "hook", "chorus", "refrain", "mukhda", "antara", "verse", "bridge",
    "rhyme", "rhyming", "qafiya", "radif", "tuk", "syllable", "syllables",
    "matra", "meter", "metre", "prosody", "stress", "scansion",
    "imagery", "image", "concrete", "specific detail", "show don't tell",
    "sensory", "metaphor", "simile",
    "melody", "melodic", "tempo", "bpm", "beat", "rhythm", "groove",
    "scale", "raag", "raga", "taal", "tala", "key", "minor", "major",
    "emotion", "emotional", "affect", "mood", "feeling", "bhaav",
    "story", "narrative", "point of view", "repetition", "contrast",
    "climax", "structure", "line length", "singable", "singability",
)
# Web page ka kachra — ye shabd milne par line hidayat nahi maani jaati
_JUNK_CUES: Tuple[str, ...] = (
    "cookie", "cookies", "subscribe", "newsletter", "click here", "sign in",
    "log in", "advertisement", "privacy policy", "terms of service",
    "all rights reserved", "copyright", "buy now", "add to cart",
)
MIN_GUIDANCE_CHARS = 30
MAX_GUIDANCE_CHARS = 240
MAX_GUIDANCE_LINES = 8
MAX_GUIDANCE_PER_SOURCE = 2
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+|\n+|\s{3,}")


def _sentences(text: str) -> List[str]:
    return [" ".join(piece.split())
            for piece in _SENTENCE_SPLIT_RE.split(str(text or ""))
            if piece and piece.strip()]


def _is_guidance(sentence: str) -> bool:
    norm = _norm(sentence)
    if any(_cue_present(norm, junk) for junk in _JUNK_CUES):
        return False
    return any(_cue_present(norm, cue) for cue in CRAFT_CUES)


# Padhi hui source me se ASLI NUMBER — yahi ek cheez hai jo `style_fit_structure`
# ko naapne laayak banati hai. Number source se aaye to naap chalta hai; na aaye
# to check NOT_MEASURED rehta hai. Cue-table se number GHADA nahi jaata.
_STANZA_CONTEXT = ("verse", "stanza", "antara", "mukhda", "chorus", "couplet",
                   "sher", "pankti", "quatrain")
_CONV_STANZA_RE = re.compile(
    r"\b(\d{1,2})[\s-]*(?:line|lines|pankti|panktiyan|bar|bars)\b", re.I)
_CONV_REPEAT_RE = re.compile(
    r"\b(?:chorus|hook|refrain|mukhda)\b[^.]{0,60}?\b(\d{1,2})\s*"
    r"(?:times|time|baar)\b", re.I)
CONVENTION_MIN = 1
CONVENTION_MAX = 24


def _conventions_in(sentence: str, source_id: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    norm = _norm(sentence)
    if any(_cue_present(norm, cue) for cue in _STANZA_CONTEXT):
        match = _CONV_STANZA_RE.search(sentence)
        if match:
            value = int(match.group(1))
            if CONVENTION_MIN <= value <= CONVENTION_MAX:
                found.append({"kind": "lines_per_stanza", "value": value,
                              "source_id": source_id, "line": sentence})
    match = _CONV_REPEAT_RE.search(sentence)
    if match:
        value = int(match.group(1))
        if CONVENTION_MIN <= value <= CONVENTION_MAX:
            found.append({"kind": "refrain_times", "value": value,
                          "source_id": source_id, "line": sentence})
    return found


def _source_text(source: Any) -> str:
    # SourceRecord me `full_text` field NAHI hai (models.py) — isliye duck-typed
    # padhna, warna AttributeError se poora naap gir jaata.
    pieces: List[str] = []
    for attr in ("title", "snippet", "full_text"):
        token = str(getattr(source, attr, "") or "").strip()
        if token:
            pieces.append(token)
    return " ".join(pieces)


def guidance_from(sources: Iterable[Any],
                  ask: Optional[StyleAsk] = None) -> Dict[str, Any]:
    """Padhi hui source me se CITED hidayat — bina source id koi line nahi."""
    lines: List[Dict[str, str]] = []
    conventions: List[Dict[str, Any]] = []
    seen_text: set = set()
    contributing: set = set()
    scanned = 0

    for source in list(sources or []):
        scanned += 1
        source_id = str(getattr(source, "source_id", "") or "").strip()
        if not source_id:
            # id nahi to citation nahi, aur bina citation line nahi jaati
            continue
        text = _source_text(source)
        if not text:
            continue
        taken = 0
        for sentence in _sentences(text):
            if len(sentence) < MIN_GUIDANCE_CHARS:
                continue
            if not _is_guidance(sentence):
                continue
            clipped = sentence[:MAX_GUIDANCE_CHARS].strip()
            key = clipped.casefold()
            for record in _conventions_in(clipped, source_id):
                conventions.append(record)
            if key in seen_text or taken >= MAX_GUIDANCE_PER_SOURCE:
                continue
            if len(lines) >= MAX_GUIDANCE_LINES:
                break
            seen_text.add(key)
            taken += 1
            contributing.add(source_id)
            lines.append({
                "text": clipped,
                "source_id": source_id,
                "url": str(getattr(source, "url", "") or ""),
                "connector": str(getattr(source, "connector", "") or ""),
            })
        if len(lines) >= MAX_GUIDANCE_LINES:
            break


    # convention list bhi bounded aur dedup — ek hi line se ek hi record
    conv_seen: set = set()
    unique_conventions: List[Dict[str, Any]] = []
    for record in conventions:
        key = (record["kind"], record["value"], record["source_id"])
        if key in conv_seen:
            continue
        conv_seen.add(key)
        unique_conventions.append(record)
        if len(unique_conventions) >= MAX_GUIDANCE_LINES:
            break

    read_note = (
        f"{len(lines)} hidayat {len(contributing)} padhi hui source se aayi "
        f"(har line ke saath source id hai)"
        if lines else
        "craft ke baare me kuch padha nahi gaya — isliye koi hidayat nahi di "
        "gayi (apne aap se salaah nahi ghadi)")

    return {
        "ran": True,
        "lines": lines,
        "guidance_source_count": len(contributing),
        "sources_scanned": scanned,
        "numeric_conventions": unique_conventions,
        "style_conventions_read": bool(unique_conventions),
        "read_note": read_note,
        "ask": ask.to_dict() if ask is not None else {},
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "guidance_is_quoted_not_invented": True,
        "audio_generated": AUDIO_GENERATED,
    }


EMPTY_GUIDANCE_LINE = (
    "Craft ke baare me is baar kuch padha nahi gaya — isliye neeche koi "
    "\"kitaab kehti hai\" wali baat nahi hai. Jo likhoge use bina padhi hui "
    "authority ke likho, aur report me ye kami saaf rehti hai.")


MUSIC_DIRECTION_FIELDS = ("tempo/feel", "scale ya raag", "vaadya (instruments)",
                          "aawaz (kaun gaayega)")


def guidance_prompt_block(guidance: Optional[Dict[str, Any]] = None,
                          ask: Optional[StyleAsk] = None) -> str:
    """Synthesis prompt me jaane wala block — 0 Gemini call yahan bhi.

    craft.DRAFT_INSTRUCTION (dhaancha + fence) ke SAATH jaata hai, uski jagah
    nahi leta.
    """
    guidance = guidance or {}
    rows = list(guidance.get("lines") or [])
    out: List[str] = ["GAANA LIKHNE KI HIDAYAT (songcraft):"]

    if ask is not None and ask.asked_anything():
        if ask.style_labels:
            out.append(f"- Maanga gaya style: {', '.join(ask.style_labels)}. "
                       f"Isi lehje me likho, kisi doosre lehje me nahi.")
        if ask.language_labels:
            out.append(f"- Bhasha ki maang: {', '.join(ask.language_labels)}.")
        if ask.register_labels:
            out.append(f"- Zubaan/lehja: {', '.join(ask.register_labels)}.")
        elif "shudh" not in ask.registers:
            out.append("- Zubaan wahi rakho jo sawaal me bola gaya — bina "
                       "kahe shudh/kitaabi Hindi me mat badlo.")
        if ask.moods:
            out.append(f"- Bhaav: {', '.join(ask.moods)}. Ye bhaav har antare "
                       f"me dikhna chahiye, sirf ek line me nahi. Ulta bhaav "
                       f"(jaise dukh ke gaane me khushi) mat milao.")
        if ask.tempo_family:
            out.append(f"- Chaal ka andaza: {ask.tempo_family} "
                       f"({TEMPO_FAMILIES.get(ask.tempo_family, '')}).")

    out.append("- Thos cheezein likho (aankh, chai, station, baarish jaisi "
               "dikhne wali cheez), sirf 'dard/pyaar/zindagi' jaise bade "
               "abstract shabd se kaam mat chalao.")
    out.append("- MUSIC DIRECTION alag se likho aur usme ye chaar cheez "
               "naam se aani chahiye: " + ", ".join(MUSIC_DIRECTION_FIELDS) +
               ". Ye ek SALAAH hai — yahan koi audio/dhun nahi banti.")
    out.append("- \"dhun mast banegi\", \"hit/viral hoga\", \"sab ko pasand "
               "aayega\" jaisa koi daawa mat likho. Aisa daawa ek naapa hua "
               "FAIL hai.")
    out.append("- Kisi maujooda gaane ke bol copy mat karo.")


    if rows:
        out.append("")
        out.append("PADHI HUI SOURCE SE (har line ke saath uska source id — "
                   "in lines ko apne shabdon me barto, jaisa ka waisa copy "
                   "mat karo):")
        for row in rows:
            out.append(f"  [{row['source_id']}] {row['text']}")
        for record in list(guidance.get("numeric_conventions") or [])[:4]:
            out.append(f"  [{record['source_id']}] padha hua number — "
                       f"{record['kind']} = {record['value']}")
    else:
        out.append("")
        out.append(EMPTY_GUIDANCE_LINE)

    return "\n".join(out)


def study(question: str, sources: Iterable[Any] = (), form: str = "",
          moods: Sequence[str] = ()) -> Dict[str, Any]:
    """Ek hi jagah se sab: style ask + query list + cited guidance.

    craft/orchestrator isi ko bulate hain. Yahan bhi 0 network, 0 model call.
    """
    ask = style_of(question, form=form, moods=moods)
    guidance = guidance_from(sources, ask)
    queries = study_queries(ask)
    return {
        "ran": True,
        "ask": ask,
        "ask_dict": ask.to_dict(),
        "queries": queries,
        "plan": study_plan(ask),
        "guidance": guidance,
        "prompt_block": guidance_prompt_block(guidance, ask),
        "guidance_source_count": guidance.get("guidance_source_count", 0),
        "style_conventions_read": guidance.get("style_conventions_read", False),
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "audio_generated": AUDIO_GENERATED,
        "cannot_measure": list(CANNOT_MEASURE_EXTRA),
    }


# ── #131 NAAP ─────────────────────────────────────────────────────────────────
# Ulta bhaav. Sirf wahi jode jo sach me aapas me katte hain: "judaai + pyaar"
# ek hi sad gaane me normal hai, isliye wo jodi YAHAN NAHI hai.
MOOD_OPPOSITES: Dict[str, Tuple[str, ...]] = {
    "dukh": ("khushi", "hasi"),
    "khushi": ("dukh",),
    "hasi": ("dukh",),
    "gussa": ("shanti",),
    "shanti": ("gussa",),
    "dar": ("himmat",),
    "himmat": ("dar",),
    "tanhai": ("dosti",),
    "dosti": ("tanhai",),
}

# THOS (dikhne/chhoone wali) cheezein vs BADE ABSTRACT shabd. Ye list ADHOORI
# HAI (`IMAGE_LIST_IS_NOT_EXHAUSTIVE`) — isliye check ka naam bhi
# `concrete_image_words` hai, "imagery achhi hai" nahi. Milaan roman tokens par
# hota hai, taaki Devanagari draft bhi gina jaaye.
IMAGE_WORDS: Tuple[str, ...] = (
    "aankh", "ankh", "aansu", "haath", "ungli", "baal", "hoth", "kandha",
    "chai", "cigarette", "sutta", "roti", "namak", "doodh", "mithai",
    "sadak", "gali", "chhat", "khidki", "darwaza", "seedhi", "diwar",
    "train", "rail", "bus", "station", "platform", "rickshaw", "auto",
    "bazaar", "chowk", "school", "college", "kitaab", "kalam", "kaagaz",
    "phone", "ghadi", "chaabi", "sikka", "note", "bank",
    "baarish", "dhoop", "hawa", "chand", "taare", "raat", "subah", "shaam",
    "dhool", "mitti", "pahaad", "nadi", "samundar", "jhil", "rait",
    "ghar", "aangan", "tulsi", "diya", "chudi", "dupatta", "kurta", "juta",
    "pul", "bench", "park", "ped", "pedh", "phool", "patta", "kanta",
    "aag", "paani", "dhuaan", "barf", "kohra", "chappal", "bistar", "takiya",
)
ABSTRACT_WORDS: Tuple[str, ...] = (
    "pyaar", "pyar", "prem", "ishq", "mohabbat", "chahat",
    "dard", "gham", "dukh", "khushi", "zindagi", "jindagi", "jeevan",
    "kismat", "takdeer", "muqaddar", "naseeb", "rooh", "aatma",
    "umeed", "aasha", "yaad", "tanhai", "judaai", "viraha", "sapna", "khwab",
    "bharosa", "vishwas", "izzat", "imaan", "jazbaat", "ehsaas", "bhaav",
    "feeling", "emotion", "love", "pain", "life", "destiny", "soul", "hope",
    "dream", "truth", "sach", "jhooth",
)
MIN_CONCRETE_SHARE = 0.30
MIN_MOOD_STANZA_SHARE = 0.50
MIN_STANZAS_FOR_SPREAD = 2
SING_OUTLIER_TOL = 4            # median se itni matra ka farak chalta hai
MAX_OUTLIER_SHARE = 0.25
MIN_LINES_FOR_SING = 4
MAX_ENGLISH_SHARE_DEFAULT = 0.08
MIN_MUSIC_FIELDS = 3            # chaar me se teen naam se aane chahiye


# MUSIC DIRECTION ke chaar khaane. Ye SIRF itna naapte hain ki "likha gaya ya
# nahi" — "sahi likha gaya" ya "bajane par acha lagega" ka koi naap nahi hai.
_MUSIC_TEMPO_RE = re.compile(
    r"\bbpm\b|\btempo\b|\bdheem\w*|\btez\b|\bslow\b|\bfast\b|\bmid[\s-]?tempo\b"
    r"|\btaal\b|\btala\b|\bbeat\b|\bgroove\b|\blaya\b|\bchaal\b", re.I)
_MUSIC_SCALE_RE = re.compile(
    r"\braag\b|\braaga\b|\braga\b|\bthaat\b|\bscale\b|\bkey\s+of\b"
    r"|\bminor\b|\bmajor\b|\bsur\b|\bswar\b|\bnotes?\b", re.I)
_MUSIC_INSTRUMENT_RE = re.compile(
    r"\btabla\b|\bdholak\b|\bdhol\b|\bguitar\b|\bpiano\b|\bsitar\b|\bflute\b"
    r"|\bbansuri\b|\bharmonium\b|\bsynth\w*|\b808\b|\bstrings\b|\bsarangi\b"
    r"|\bveena\b|\bdrum\w*|\bbass\b|\bpad\b|\btumbi\b|\balgoza\b|\bcajon\b"
    r"|\bvaadya\b|\bbaaja\b", re.I)
_MUSIC_VOICE_RE = re.compile(
    r"\bmale\b|\bfemale\b|\baawaz\b|\bawaaz\b|\bvocal\w*|\bsinger\b|\bgaayak\b"
    r"|\bgayak\b|\bduet\b|\bfalsetto\b|\bchorus\s+voice\w*|\brap\s+flow\b"
    r"|\bbhaari\s+aawaz\b", re.I)
_MUSIC_FIELD_RES: Tuple[Tuple[str, Any], ...] = (
    ("tempo", _MUSIC_TEMPO_RE),
    ("scale_or_raag", _MUSIC_SCALE_RE),
    ("instruments", _MUSIC_INSTRUMENT_RE),
    ("voice", _MUSIC_VOICE_RE),
)

# "dhun mast banegi" = ek aisa daawa jo naapa hi nahi gaya. Ye khud ek FAIL hai.
# craft ka `appeal_claims_in` sirf DRAFT ke andar dekhta hai; ye jaanch draft ke
# BAHAR ki baat par bhi lagti hai, kyunki music direction bahar likhi jaati hai.
_MUSIC_CLAIM_RE = re.compile(
    r"\b(?:dhun|tune|melody|music|arrangement|beat)\b[^.\n]{0,40}?"
    r"\b(?:mast|superhit|super\s*hit|hit|zabardast|zaberdast|best|amazing|"
    r"perfect|chartbuster|blockbuster|kamaal|gajab|ghazab)\b"
    r"|\b(?:mast|zabardast|kamaal|perfect|best)\b[^.\n]{0,20}?"
    r"\b(?:dhun|tune|melody)\b"
    r"|\bchartbuster\b|\bguaranteed\s+hit\b"
    r"|\bsunne\s+me\s+(?:maza|mast|kamaal)\b"
    r"|\bhar\s+koi\s+(?:pasand|gaayega|sunega)\b"
    # "Iski dhun bahut sureeli LAGEGI" — ye bhi bina-naap daawa hai, sirf narm
    # shabd me. Isko pakadne ke liye do cheez chahiye: music ka noun + tareef ka
    # shabd + AANE WALE waqt ka kriya. Aakhri shart jaan-boojh kar hai: "dhun
    # sureeli rakhein" ek hidaayat hai (kya banana hai), daawa nahi (kaisa
    # banega) — hidaayat ko FAIL karna khud ek galat naap hoga.
    r"|\b(?:dhun|tune|melody|music|arrangement|beat|awaaz)\b[^.\n]{0,40}?"
    r"\b(?:sureeli|sureela|surili|surila|madhur|melodious|soulful|catchy|"
    r"dilkash|rooh|magical|jaadui)\w*\b[^.\n]{0,20}?"
    r"\b(?:lagegi|lagega|lagenge|banegi|banega|hogi|hoga|rahegi|rahega|"
    r"aayegi|aayega|niklegi|will\s+(?:be|sound))\b"
    # Angrezi me kram ulta hota hai: "the melody WILL BE soulful".
    r"|\b(?:dhun|tune|melody|music|arrangement|beat)\b[^.\n]{0,30}?"
    r"\b(?:will\s+(?:be|sound)|is\s+going\s+to\s+(?:be|sound)|sounds)\b"
    r"[^.\n]{0,20}?"
    r"\b(?:sureeli|sureela|surili|surila|madhur|melodious|soulful|catchy|"
    r"dilkash|magical|jaadui|mast|zabardast|amazing|perfect|best)\w*\b", re.I)


def music_claims_in(text: str) -> List[str]:
    """Music/dhun ke bare me kiye gaye bina-naap daawe."""
    return [" ".join(m.group(0).split())
            for m in _MUSIC_CLAIM_RE.finditer(str(text or ""))]


def context_facts(draft: str, spec: Any = None,
                  study: Optional[Dict[str, Any]] = None,
                  context: str = "",
                  stanza_moods: Sequence[Sequence[str]] = (),
                  stanza_line_counts: Sequence[int] = ()) -> Dict[str, Any]:
    """Naye naapon ke liye kachche number — craft ke `draft_facts` ke saath juda.

    `stanza_moods` craft se aata hai (uska mood table, uska stanza split), taaki
    ek hi cheez do jagah alag na nikle.
    """
    body = str(draft or "")
    ask = getattr(spec, "style", None)
    if not isinstance(ask, StyleAsk):
        ask = (study or {}).get("ask")
    if not isinstance(ask, StyleAsk):
        ask = None

    guidance = (study or {}).get("guidance") or {}
    try:
        tokens = [t.lower() for t in lang_bridge.roman_tokens(body) if t]
    except Exception:
        tokens = [t.lower() for t in _WORD_RE.findall(body)]
    try:
        counts = lang_bridge.script_counts(body)
    except Exception:
        counts = {}

    return {
        "ask": ask.to_dict() if ask is not None else {},
        "styles": list(ask.styles) if ask is not None else [],
        "registers": list(ask.registers) if ask is not None else [],
        "languages": list(ask.languages) if ask is not None else [],
        "moods_asked": list(getattr(spec, "mood_asked", ()) or
                            (ask.moods if ask is not None else [])),
        "form": str(getattr(spec, "form", "") or
                    (ask.form if ask is not None else "")),
        "context": str(context or ""),
        "stanza_moods": [list(row or []) for row in (stanza_moods or ())],
        "stanza_line_counts": [int(n) for n in (stanza_line_counts or ())],
        "roman_tokens": tokens,
        "script_counts": dict(counts),
        "numeric_conventions": list(guidance.get("numeric_conventions") or []),
        "guidance_source_count": int(guidance.get("guidance_source_count") or 0),
        "style_conventions_read": bool(guidance.get("style_conventions_read")),
        "audio_generated": AUDIO_GENERATED,
    }


def _sc(facts: Dict[str, Any]) -> Dict[str, Any]:
    """facts["songcraft"] — na ho to khaali dict (naap NOT_MEASURED ho jaayega)."""
    block = facts.get("songcraft")
    return block if isinstance(block, dict) else {}


# craft ke literal — yahan dobara likhe gaye (circular import se bachne ke liye).
# Test dono ki barabari pin karta hai.
SONG_FORM = "song"
MATRA_RULE_ROMAN = "roman_vowel_approx"


def _row(check: str, status: str, measured: Any = "", target: Any = "",
         reason: str = "", note: str = "", approx: bool = False) -> Dict[str, Any]:
    assert status in CHECK_STATUSES, status
    return {"check": check, "status": status, "measured": measured,
            "target": target, "reason": reason, "note": note, "approx": approx}


def _unmeasured(check: str, reason: str, note: str) -> Dict[str, Any]:
    return _row(check, NOT_MEASURED, reason=reason, note=note)


def _vocab_hits(tokens: Sequence[str], vocab: Iterable[str]) -> List[str]:
    """Chhote shabd (<=3 akshar) exact milte hain — "aag" ko "aage" me nahi ginna."""
    found: List[str] = []
    for token in tokens:
        for word in vocab:
            if token == word:
                found.append(word)
                break
            if (len(word) >= 4 and token.startswith(word)
                    and len(token) - len(word) <= 3):
                found.append(word)
                break
    return found


def _check_mood_spread(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    rows = _sc(facts).get("stanza_moods") or []
    if len(rows) < MIN_STANZAS_FOR_SPREAD:
        return _unmeasured("mood_spread", "too_few_stanzas",
                           "Band (stanza) itne nahi hain ki bhaav ka failaav "
                           "naapa ja sake.")
    with_mood = sum(1 for row in rows if row)
    share = round(with_mood / len(rows), 4)
    ok = share >= MIN_MOOD_STANZA_SHARE
    return _row("mood_spread", MET if ok else NOT_MET,
                measured=f"{with_mood}/{len(rows)} band ({share})",
                target=f">= {MIN_MOOD_STANZA_SHARE}",
                reason="" if ok else "mood_only_in_few_stanzas",
                note=("Bhaav wale shabd zyadatar bandon me hain — par isse ye "
                      "saabit nahi hota ki sunne wale ko feeling aayegi."
                      if ok else
                      "Bhaav wale shabd sirf thode bandon me hain, baaki band "
                      "sapaat hain."))


def _check_mood_conflict(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    asked = [str(m) for m in (_sc(facts).get("moods_asked") or [])]
    if not asked:
        return _unmeasured("mood_conflict_absent", "no_mood_asked",
                           "Koi bhaav maanga hi nahi tha, isliye ulta bhaav "
                           "bhi naapa nahi ja sakta.")
    opposites: set = set()
    for mood in asked:
        opposites.update(MOOD_OPPOSITES.get(mood, ()))
    if not opposites:
        return _unmeasured("mood_conflict_absent", "no_opposite_known",
                           f"'{', '.join(asked)}' ka koi ulta bhaav is (adhoori) "
                           f"table me nahi hai — is par kuch nahi kaha ja sakta.")
    clash = sorted(set(facts.get("moods") or []) & opposites)
    ok = not clash
    return _row("mood_conflict_absent", MET if ok else NOT_MET,
                measured=", ".join(clash) if clash else "koi ulta bhaav nahi",
                target=f"in me se koi nahi: {', '.join(sorted(opposites))}",
                reason="" if ok else "opposite_mood_present",
                note=("Maange gaye bhaav ka ulta bhaav draft me nahi mila."
                      if ok else
                      f"'{', '.join(asked)}' maanga tha par draft me ulta bhaav "
                      f"({', '.join(clash)}) bhi hai — feel bat jaata hai."))


def _check_concrete_images(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    tokens = _sc(facts).get("roman_tokens") or []
    if not tokens:
        return _unmeasured("concrete_image_words", "no_tokens",
                           "Draft se shabd nahi nikle — naap nahi chala.")
    concrete = _vocab_hits(tokens, IMAGE_WORDS)
    abstract = _vocab_hits(tokens, ABSTRACT_WORDS)
    total = len(concrete) + len(abstract)
    if not total:
        return _unmeasured("concrete_image_words", "no_image_or_abstract_cue",
                           "Is draft me na thos cheezon ke shabd mile na bade "
                           "abstract shabd — list adhoori hai, isliye is par "
                           "kuch nahi kaha ja sakta.")
    share = round(len(concrete) / total, 4)
    ok = share >= MIN_CONCRETE_SHARE
    return _row("concrete_image_words", MET if ok else NOT_MET,
                measured=f"{len(concrete)} thos / {len(abstract)} abstract "
                         f"({share})",
                target=f">= {MIN_CONCRETE_SHARE}",
                reason="" if ok else "too_abstract",
                note=("Dikhne wali thos cheezein kaafi hain (shabd-list adhoori "
                      "hai, isliye ye poora hisaab nahi)." if ok else
                      "Gaana zyadatar bade abstract shabdon (dard/pyaar/"
                      "zindagi) par tika hai, dikhne wali cheez kam hai."),
                approx=True)


def _check_register(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    block = _sc(facts)
    asked = list(block.get("registers") or [])
    if not asked:
        return _unmeasured("register_consistency", "no_register_asked",
                           "Zubaan/lehja ki koi saaf maang nahi thi.")
    rule: Optional[Register] = None
    for register in REGISTERS:
        if register.register_id in asked and (
                register.max_english_share is not None
                or register.max_devanagari_share is not None):
            rule = register
            break
    if rule is None:
        return _unmeasured(
            "register_consistency", "no_numeric_register_rule",
            f"'{', '.join(asked)}' jaisi maang ka koi imaandaar counter humare "
            f"paas nahi hai — isliye ise naapa nahi gaya (jhootha MET dene se "
            f"behtar hai ye kehna).")
    counts = dict(block.get("script_counts") or {})
    total = sum(int(v) for v in counts.values())
    if total <= 0:
        return _unmeasured("register_consistency", "no_letters",
                           "Draft me akshar hi nahi gine ja sake.")
    if rule.max_english_share is not None:
        share = round(int(counts.get("latin", 0)) / total, 4)
        ok = share <= rule.max_english_share
        return _row("register_consistency", MET if ok else NOT_MET,
                    measured=f"English/Latin akshar {share}",
                    target=f"<= {rule.max_english_share} ({rule.label})",
                    reason="" if ok else "english_share_too_high",
                    note=("Maange gaye lehje ke hisaab se English akshar kam "
                          "hain." if ok else
                          f"{rule.label} maanga tha par English shabd is se "
                          f"zyada hain."))
    share = round(int(counts.get("devanagari", 0)) / total, 4)
    ok = share <= (rule.max_devanagari_share or 0.0)
    return _row("register_consistency", MET if ok else NOT_MET,
                measured=f"Devanagari akshar {share}",
                target=f"<= {rule.max_devanagari_share} ({rule.label})",
                reason="" if ok else "devanagari_share_too_high",
                note=("Maange gaye lehje ke hisaab se theek hai." if ok else
                      f"{rule.label} maanga tha par Devanagari is se zyada hai."))


def _median(values: Sequence[int]) -> float:
    ordered = sorted(int(v) for v in values)
    size = len(ordered)
    middle = size // 2
    if size % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _check_singability(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    per_line = [int(v) for v in (facts.get("matra_per_line") or [])]
    rule = str(facts.get("matra_rule") or "")
    if not rule or len(per_line) < MIN_LINES_FOR_SING:
        return _unmeasured("singability_line_outliers", "matra_not_measurable",
                           "Matra ka niyam nahi laga ya line itni nahi — "
                           "gaaye jaane laayak lambai naapi nahi ja saki.")
    middle = _median(per_line)
    outliers = [value for value in per_line
                if abs(value - middle) > SING_OUTLIER_TOL]
    share = round(len(outliers) / len(per_line), 4)
    ok = share <= MAX_OUTLIER_SHARE
    return _row("singability_line_outliers", MET if ok else NOT_MET,
                measured=f"{len(outliers)}/{len(per_line)} line baahar "
                         f"(median {middle}, farak > {SING_OUTLIER_TOL})",
                target=f"<= {MAX_OUTLIER_SHARE}",
                reason="" if ok else "line_length_outliers",
                note=("Lines ki lambai ek jaisi hai — dhun par baithane me "
                      "aasaani hoti hai (par dhun yahan bani nahi)." if ok else
                      "Kuch line baaki se bahut lambi/chhoti hain — gaate waqt "
                      "wo line todni padegi."),
                approx=rule == MATRA_RULE_ROMAN)


def _check_style_fit(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    """SIRF tab naapta hai jab kisi PADHI HUI source me asli number mila ho."""
    block = _sc(facts)
    conventions = list(block.get("numeric_conventions") or [])
    if not conventions:
        read = int(block.get("guidance_source_count") or 0)
        return _unmeasured(
            "style_fit_structure",
            "style_conventions_not_read" if not read
            else "no_numeric_convention_read",
            "Is style ka koi asli number (kitni line ka band, hook kitni baar) "
            "kisi padhi hui source me nahi mila — isliye style se milaan nahi "
            "kiya gaya. Ye 'sab theek hai' NAHI hai.")
    stanza_counts = [int(n) for n in (block.get("stanza_line_counts") or [])]
    refrain_times = int((facts.get("refrain") or {}).get("times") or 0)
    verdicts: List[str] = []
    failed: List[str] = []
    for record in conventions[:4]:
        kind = str(record.get("kind") or "")
        value = int(record.get("value") or 0)
        tag = str(record.get("source_id") or "")
        if kind == "lines_per_stanza":
            hit = value in stanza_counts
            verdicts.append(f"[{tag}] band {value} line: "
                            f"{'mila' if hit else 'nahi mila'}")
            if not hit:
                failed.append(f"[{tag}] {value} line ka band")
        elif kind == "refrain_times":
            hit = refrain_times >= value
            verdicts.append(f"[{tag}] hook {value} baar: "
                            f"{'mila' if hit else f'sirf {refrain_times} baar'}")
            if not hit:
                failed.append(f"[{tag}] hook {value} baar")
    if not verdicts:
        return _unmeasured("style_fit_structure", "convention_kind_unknown",
                           "Padhe hue number ka kism samajh nahi aaya — naap "
                           "nahi chala.")
    ok = not failed
    return _row("style_fit_structure", MET if ok else NOT_MET,
                measured="; ".join(verdicts),
                target="padhi hui source ke number",
                reason="" if ok else "read_convention_not_followed",
                note=("Draft padhi hui convention par utar raha hai."
                      if ok else
                      "Padhi hui convention se farak hai: " + ", ".join(failed)))


def _check_music_direction(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    block = _sc(facts)
    if str(block.get("form") or "") != SONG_FORM:
        return _unmeasured("music_direction_present", "not_a_song",
                           "Ye gaana nahi hai — music direction ki maang hi "
                           "nahi banti.")
    context = str(block.get("context") or "")
    if not context.strip():
        return _unmeasured("music_direction_present", "no_answer_text",
                           "Draft ke bahar ka jawab yahan nahi mila, isliye "
                           "music direction dhoondhi nahi ja saki.")
    present = [name for name, pattern in _MUSIC_FIELD_RES
               if pattern.search(context)]
    missing = [name for name, _p in _MUSIC_FIELD_RES if name not in present]
    ok = len(present) >= MIN_MUSIC_FIELDS
    return _row("music_direction_present", MET if ok else NOT_MET,
                measured=f"{len(present)}/4 khaane: "
                         f"{', '.join(present) if present else 'koi nahi'}",
                target=f">= {MIN_MUSIC_FIELDS} khaane "
                       f"({', '.join(MUSIC_DIRECTION_FIELDS)})",
                reason="" if ok else "music_direction_incomplete",
                note=("Music direction likhi gayi hai — ye ek SALAAH hai, "
                      "yahan koi audio/dhun nahi bani." if ok else
                      "Music direction adhoori hai, ye khaane nahi likhe gaye: "
                      + ", ".join(missing)))


def _check_no_music_claim(spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    block = _sc(facts)
    text = str(block.get("context") or "")
    if not text.strip():
        return _unmeasured("no_music_quality_claim", "no_answer_text",
                           "Jawab ka text yahan nahi mila — daawe dhoondhe "
                           "nahi ja sake.")
    claims = music_claims_in(text)
    ok = not claims
    return _row("no_music_quality_claim", MET if ok else NOT_MET,
                measured=len(claims),
                target="0",
                reason="" if ok else "unmeasured_music_claim",
                note=("Dhun/music ke bare me koi bina-naap daawa nahi kiya "
                      "gaya." if ok else
                      "Ye daawe naape nahi ja sakte (yahan audio bana hi nahi): "
                      + "; ".join(claims[:3])))


# Kram maayne rakhta hai — report isi kram me chhapti hai. craft.CHECKS ke AAGE
# jud jaate hain, kisi purane check ki jagah nahi lete.
CHECK_RUNNERS: Tuple[Tuple[str, Any], ...] = (
    ("mood_spread", _check_mood_spread),
    ("mood_conflict_absent", _check_mood_conflict),
    ("concrete_image_words", _check_concrete_images),
    ("register_consistency", _check_register),
    ("singability_line_outliers", _check_singability),
    ("style_fit_structure", _check_style_fit),
    ("music_direction_present", _check_music_direction),
    ("no_music_quality_claim", _check_no_music_claim),
)
CHECK_NAMES: Tuple[str, ...] = tuple(name for name, _r in CHECK_RUNNERS)

# Ye naam JAAN-BOOJH KAR aise rakhe gaye hain. `mood_spread` ka matlab "bhaav ke
# shabd kitne bandon me faile" hai — "emotion aa gaya" nahi. Isliye in me se koi
# bhi naam `emotion_achieved` / `music_quality_ok` / `style_mastered` NAHI hai.
FORBIDDEN_CHECK_NAMES: Tuple[str, ...] = (
    "emotion_achieved", "feeling_achieved", "music_quality_ok",
    "tune_quality_ok", "style_mastered", "audio_generated_ok",
    "listener_will_like",
)


def run_check(name: str, spec: Any, facts: Dict[str, Any]) -> Dict[str, Any]:
    """Ek naap chalao. Galat naam par KeyError — chup-chaap MET kabhi nahi."""
    for check_name, runner in CHECK_RUNNERS:
        if check_name == name:
            return runner(spec, facts)
    raise KeyError(name)


def measure_song(spec: Any, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Saare naye naap — fail-closed (koi toote to NOT_MEASURED, MET nahi)."""
    rows: List[Dict[str, Any]] = []
    for name, runner in CHECK_RUNNERS:
        try:
            rows.append(runner(spec, facts))
        except Exception:
            rows.append(_unmeasured(
                name, "check_error",
                "Ye naap andar ki galti se chal nahi paaya — is par kuch bhi "
                "nahi kaha ja sakta."))
    return rows

# ── report ke liye ────────────────────────────────────────────────────────────
def policy() -> Dict[str, Any]:
    """Kaise naapa gaya — audit me jaata hai."""
    return {
        "network_used": NETWORK_USED,
        "randomness_used": False,
        "gemini_calls": GEMINI_CALLS,
        "deterministic": True,
        "provider_cost": "₹0",
        "measured_by": "offline_rules_in_songcraft_py",
        "audio_generated": AUDIO_GENERATED,
        "music_direction_is_suggestion": MUSIC_DIRECTION_IS_SUGGESTION,
        "style_table_is_addressing_only": True,
        "style_list_is_not_exhaustive": STYLE_LIST_IS_NOT_EXHAUSTIVE,
        "image_list_is_not_exhaustive": IMAGE_LIST_IS_NOT_EXHAUSTIVE,
        "register_list_is_not_exhaustive": REGISTER_LIST_IS_NOT_EXHAUSTIVE,
        "existing_song_lyrics_fetched": False,
        "quality_proven": False,
        "human_reaction_untested": True,
    }


def section_lines(study: Optional[Dict[str, Any]] = None) -> List[str]:
    """Report me dikhane wali chhoti si sach-batao list."""
    study = study or {}
    ask = study.get("ask")
    guidance = study.get("guidance") or {}
    lines: List[str] = []

    labels = (list(ask.style_labels) if isinstance(ask, StyleAsk)
              else list((study.get("ask_dict") or {}).get("style_labels") or []))
    langs = (list(ask.language_labels) if isinstance(ask, StyleAsk)
             else list((study.get("ask_dict") or {}).get("language_labels") or []))
    regs = (list(ask.register_labels) if isinstance(ask, StyleAsk)
            else list((study.get("ask_dict") or {}).get("register_labels") or []))

    lines.append("Style ki maang: " + (", ".join(labels) if labels else
                 "naam se koi style nahi mili (table adhoori bhi hai)"))
    if langs:
        lines.append("Bhasha: " + ", ".join(langs))
    if regs:
        lines.append("Zubaan/lehja: " + ", ".join(regs))
    lines.append("Padha gaya (craft): " + str(guidance.get("read_note") or
                 "kuch padha nahi gaya"))
    if guidance.get("numeric_conventions"):
        lines.append("Padhe hue number: " + "; ".join(
            f"[{r.get('source_id')}] {r.get('kind')}={r.get('value')}"
            for r in list(guidance.get("numeric_conventions"))[:4]))
    lines.append("Yahan koi audio/dhun NAHI bani — music wali baat sirf likhi "
                 "hui salaah hai, saboot nahi.")
    return lines


def limits() -> Tuple[str, ...]:
    """Audit me jaane wali seemaayein — inhe chhupana ek jhooth hoga."""
    return (
        "Songcraft ne koi audio/dhun nahi banayi (AUDIO_GENERATED = False); "
        "music direction ek likhi hui salaah hai.",
        "Bhaav ke shabd ginna 'feeling aa gayi' nahi hota — sunne wale ka asar "
        "naapa hi nahi ja sakta.",
        "Style/register/bhasha ki table sirf ADDRESSING hai (user ne kya naam "
        "liya); us style ka asli taqaza sirf padhi hui source se aata hai.",
        # Lafz "approx" jaan-boojh kar nahi likha: audit me "approx" sirf matra
        # ke roman-akshar niyam ke liye reserved hai (craft.craft_limits), warna
        # padhne wala samajhega ki matra roman se gini gayi hai.
        "Thos/abstract shabd ki list adhoori hai, isliye wo naap sirf ek "
        "andaza hai — poora saboot nahi.",
        "Kisi maujooda gaane ke bol na dhoondhe gaye na copy kiye gaye.",
    )
