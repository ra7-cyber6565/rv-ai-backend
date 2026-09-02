"""music_study — "kaunsa sur, kaun taal, kaun saaz" ki PADHI HUI samajh (#140b).

intel ki maang (jyun ki tyun): "or to or use music bnana konsa tone bnega music
kaisa bnega use sab knowelege hona chahiye har chej me master tab jaake gaana
bnaye".

#128-#134 tak gaana likhne ka HUNAR (songcraft), recording ka parichay
(media_study) aur SUNNE WALE ka bhaav (listener_study) padha jaata hai. Music
direction ka haal ab bhi patla tha: `songcraft._check_music_direction` sirf itna
naapta hai ki chaar khaane (tempo/feel, scale ya raag, vaadya, aawaz) LIKHE GAYE
ya nahi — unke PEECHE koi padhi hui baat nahi hoti thi. Matlab "dheema rakho,
minor me jao, bansuri daalo" app ke apne muh ki baat thi. Ye module wahi khaali
jagah bharta hai: har khaane ke peeche source id wali padhi hui line. Kharch:
₹0, Gemini call 0, network 0 (ye sirf query BANATA hai aur aaye hue source
PADHTA hai).

CHAAR JHOOTH jo ye file JAAN-BOOJH KAR nahi bolti:

  1. **"Padha" ≠ "suna".** App ne koi dhun nahi bajaayi, koi audio nahi bani,
     kisi ne bajaakar dekha bhi nahi. `AUDIO_GENERATED`/`TUNE_MADE`/`HEARD`/
     `PLAY_TESTED` sab False — hamesha, aur ye baat audit me jaati hai.

  2. **Source ka number app ki sifarish nahi hai.** "ballad 60-80 BPM par
     baithte hain" jaisi baat padhi ja sakti hai, par wo SOURCE-REPORTED rehti
     hai — app khud koi BPM/raag tay nahi karta. Isliye number apne source id
     ke saath jaata hai, aur `reported_numbers` alag ginti hai.

  3. **"minor = sad" ek jhukav hai, niyam nahi.** Research dusre gaanon aur
     dusre sunne walon par naapi gayi thi. Isliye MET ka matlab sirf "baat padhi
     hui source se aayi" hai — "ye dhun kaam karegi" nahi.

  4. **Ye songcraft ki jagah NAHI leta.** `music_direction_present` (khaane
     likhe gaye ya nahi) wahin rehta hai; yahan naya alag naap
     `music_direction_cited` aata hai, apni alag ginti ke saath. Do ginti mila
     dena hi wo jhooth hai jo #133/#134 me bhi rokha gaya tha.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# songcraft ke gates aur music ke chaar khaane DOBARA nahi likhe ja rahe:
# sentence todna, junk shabd, lambai ki hadd, per-source cap, aur khaane
# pehchaanne wali regex — sab wahin se. Do copy hamesha ek din alag ho jaati
# hain, aur tab audit do alag shabd bolne lagta hai.
from . import songcraft
from . import media_study

# ── 1. is lane ka sach (naam se likhi hui naa-kaabiliyat) ────────────────────
TUNE_MADE = False              # koi dhun/melody nahi bani
HEARD = False                  # app ne kuch suna hi nahi (na gaana, na dhun)
PLAY_TESTED = False            # kisi ne bajaakar dekha nahi
NETWORK_USED = False           # ye module query BANATA hai, chalata nahi
GEMINI_CALLS = 0               # ek bhi model call nahi
# Ye do songcraft se aate hain — ek hi sach do jagah likhna hi bug ki jad hai.
AUDIO_GENERATED = songcraft.AUDIO_GENERATED
MUSIC_DIRECTION_IS_SUGGESTION = songcraft.MUSIC_DIRECTION_IS_SUGGESTION

CANNOT_MEASURE_EXTRA = (
    "ye dhun/arrangement bajane par sach me achhi lagegi ya nahi (app ne kuch "
    "suna hi nahi)",
    "is gaane ke liye THEEK BPM/raag kya hai (padhi hui baat dusre gaanon par "
    "naapi gayi thi — wo is gaane ka naap nahi hai)",
    "gaayak ki aawaz aur delivery asli me kaisi lagegi",
)

# ── 2. STUDY QUERY — sirf string, koi call nahi ──────────────────────────────
# Lane ke naam songcraft.STUDY_LANES se aate hain (ek hi vocabulary), warna
# `source_discovery` me routing chup-chaap web par gir jaati. Budget bhi alag
# hai: craft ki 6 aur listener ki 3 slot ye chhuta bhi nahi.
MAX_MUSIC_QUERIES = 3
MIN_QUERY_CHARS = 8

# Query me sirf DO cheezein sawaal se jaati hain: tempo-parivaar ka naam
# (slow/mid/fast) aur style id (jaise "sad_slow"). Dono app ke apne chhote
# ASCII token hain, isliye yahan wahi shakal chalti hai — koi lamba free text
# ("<gaane ka naam> song lyrics") tempo ke bhes me network query me nahi ghus
# sakta. Ye deewar #186e ke baad bhi khadi rehti hai: `songcraft.is_lyrics_hunt()`
# ab NAAM wali bol-talaash bhi pakadta hai, par uski bachi hui seema
# (`songcraft.LYRICS_HUNT_KNOWN_LIMIT` — ek hi anjaan shabd) par ye pehra
# jaan-boojh kar rakha gaya hai.
_SAFE_FAMILY_RE = re.compile(r"^[a-z]{3,6}$")
_SAFE_STYLE_RE = re.compile(r"^[a-z][a-z_]{1,22}$")


def safe_family(family: Any) -> str:
    """`slow`/`mid`/`fast` jaisa naam, warna khaali string."""
    token = " ".join(str(family or "").split()).casefold()
    return token if _SAFE_FAMILY_RE.match(token) else ""


def safe_style(style_id: Any) -> str:
    """`sad_slow` → `sad slow`; shakal galat ho to khaali string."""
    token = " ".join(str(style_id or "").split()).casefold()
    if not _SAFE_STYLE_RE.match(token):
        return ""
    return " ".join(token.replace("_", " ").split())

MUSIC_SEEDS: Tuple[Tuple[str, str, str], ...] = (
    ("music tempo rhythm arousal emotion perception research", "papers",
     "chaal/taal ka bhaav par asar — research se"),
    ("major minor mode valence music emotion listener study", "papers",
     "major/minor (scale) aur bhaav ka rishta — research se"),
    ("raga bhava rasa indian classical music emotion theory", "books",
     "raag-bhaav aur rasa ki parampara — kitaab se"),
    ("instrumentation timbre arrangement density production mood", "books",
     "vaadya, timbre aur arrangement ka bhaarpan — kitaab se"),
    ("producer interview arrangement choices instruments vocal take", "media",
     "banane walon ki apni baat (kaunsa saaz, kaunsi aawaz) — recording se"),
    ("vocal delivery singing style expression emotion research", "papers",
     "gaayki/aawaz se bhaav kaise pahunchta hai"),
)


def study_queries(ask: Optional[Any] = None,
                  limit: int = MAX_MUSIC_QUERIES) -> List[Dict[str, str]]:
    """Music direction padhne ki query list — maang wali query sabse pehle.

    `ask` `songcraft.StyleAsk` hota hai (ya kuch bhi jiske paas `tempo_family`/
    `primary` ho). Na ho to sirf seeds chalti hain — lane khaali nahi baithta.
    """
    out: List[Dict[str, str]] = []
    seen: set = set()
    limit = max(1, int(limit or 1))

    def push(query: str, lane: str, why: str) -> None:
        clean = " ".join(str(query or "").split())
        if len(clean) < MIN_QUERY_CHARS or len(out) >= limit:
            return
        # Bol/karaoke/mp3 wali query yahan se bhi network par nahi jaayegi.
        # songcraft ka wahi guard — teesri deewar, jaan-boojh kar.
        if songcraft.is_lyrics_hunt(clean):
            return
        if lane not in songcraft.STUDY_LANES:
            # Anjaan lane ka matlab hai routing use pehchaanega nahi. Chup-chaap
            # web par daalna label ka jhooth hota, isliye query hi nahi jaati.
            return
        key = clean.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append({"query": clean, "lane": lane, "why": why})

    family = safe_family(getattr(ask, "tempo_family", ""))
    if family:
        push(f"{family} tempo music emotion arousal listener research",
             "papers",
             f"'{family}' chaal ke peeche padhi hui baat — research se")
    style = safe_style(getattr(ask, "primary", ""))
    if style:
        push(f"{style} song arrangement instrumentation production research",
             "books",
             f"'{style}' type ke gaane ka saaz/arrangement — kitaab se")
    for query, lane, why in MUSIC_SEEDS:
        push(query, lane, why)
    return out


def study_plan(ask: Optional[Any] = None,
               limit: int = MAX_MUSIC_QUERIES) -> Dict[str, Any]:
    """planner ke liye ek dict — `music_study` lane isi se banti hai."""
    queries = study_queries(ask, limit=limit)
    return {
        "music_study": queries,
        "music_study_lane": {
            "wanted": bool(queries),
            "query_count": len(queries),
            "lanes": [row["lane"] for row in queries],
            "reasons": [row["why"] for row in queries],
            # Query banana padhna NAHI hai, aur padhna sunna NAHI hai — ye
            # jhande isliye False hi rehte hain, chahe lane chal jaaye.
            "music_evidence_read": False,
            "audio_generated": AUDIO_GENERATED,
            "tune_made": TUNE_MADE,
            "heard": HEARD,
            "play_tested": PLAY_TESTED,
            "lyrics_hunt_blocked": True,
            "network_used_here": NETWORK_USED,
            "gemini_calls": GEMINI_CALLS,
            "note": ("sur/taal/saaz ke peeche ki research dhoondhne ke liye "
                     "query bani — koi dhun nahi bani aur kuch suna nahi gaya"
                     if queries else "koi music-study query nahi bani"),
        },
    }


# ── 3. KHAANE: line kis music-khaane ki baat kar rahi hai ────────────────────
# Chaaron khaane ki pehchaan songcraft ki `_MUSIC_FIELD_RES` se AATI hai (copy
# nahi hai). Faayda: naam aur regex ek jagah rehte hain, isliye report yahan aur
# songcraft ka `music_direction_present` wahan — dono ek hi shabdkosh bolte hain.
SONGCRAFT_FIELD_KEYS: Tuple[str, ...] = tuple(
    name for name, _pattern in songcraft._MUSIC_FIELD_RES)

# Paanchwa khaana SIRF yahan hai: songcraft "arrangement" ko alag naam se nahi
# naapta, par "kitne saaz, kitni khaali jagah" par research asli me hoti hai.
ARRANGEMENT_KEY = "arrangement"
ARRANGEMENT_LABEL = "arrangement — kitne saaz, kitni khaali jagah"
_ARRANGEMENT_RE = re.compile(
    r"\barrangement\b|\barranged\b|\borchestrat\w*|\bproduction\b|\bmix\b"
    r"|\bsparse\b|\bdense\b|\bdensity\b|\blayer\w*|\btexture\b|\bspace\b"
    r"|\bbuild[\s-]?up\b|\bdrop\b|\bintro\b|\bouttro\b|\boutro\b"
    r"|\binterlude\b|\bsilence\b|\bkhaali\s+jagah\b", re.I)

FIELD_KEYS: Tuple[str, ...] = SONGCRAFT_FIELD_KEYS + (ARRANGEMENT_KEY,)
_SONGCRAFT_LABELS: Dict[str, str] = dict(
    zip(SONGCRAFT_FIELD_KEYS, songcraft.MUSIC_DIRECTION_FIELDS))
FIELD_LABELS: Dict[str, str] = {
    key: _SONGCRAFT_LABELS.get(key, key.replace("_", " "))
    for key in SONGCRAFT_FIELD_KEYS}
FIELD_LABELS[ARRANGEMENT_KEY] = ARRANGEMENT_LABEL

# Regex se pehchaan poori nahi hoti aur hogi bhi nahi — isliye ye sach audit me
# jaata hai. "Is khaane par kuch nahi mila" ka matlab "research me nahi tha"
# NAHI hai.
CUE_LIST_IS_NOT_EXHAUSTIVE = True

MAX_MUSIC_LINES = 6

# Source ka number (BPM, "key of C", "60-80") padha ja sakta hai, par wo SOURCE
# ka hai. Isliye line ke saath jhanda lagta hai aur ginti alag jaati hai — app
# khud koi BPM/key tay nahi karta.
REPORTED_NUMBER_LABEL = "SOURCE-REPORTED"
_REPORTED_NUMBER_RE = re.compile(
    r"\b\d{2,3}\s*(?:-|–|to)?\s*\d{0,3}\s*(?:bpm|beats\s+per\s+minute)\b"
    r"|\bkey\s+of\s+[a-g](?:\s*(?:#|b|sharp|flat))?\b"
    r"|\b\d{1,2}\s*/\s*\d{1,2}\s*(?:time|taal|beat)\b", re.I)


def field_of(sentence: str) -> str:
    """Line kis music-khaane me girti hai; kuch na mile to khaali string."""
    text = str(sentence or "")
    for name, pattern in songcraft._MUSIC_FIELD_RES:
        if pattern.search(text):
            return name
    if _ARRANGEMENT_RE.search(text):
        return ARRANGEMENT_KEY
    return ""


def reported_numbers_in(sentence: str) -> List[str]:
    """Source me likhe hue number/key — app ki sifarish nahi, source ki baat."""
    return [" ".join(m.group(0).split())
            for m in _REPORTED_NUMBER_RE.finditer(str(sentence or ""))]


# ── 4. PADHI HUI research me se CITED music direction ────────────────────────
def _read_level(source: Any) -> str:
    return str(getattr(source, "read_level", "") or "").strip().lower()


def music_guidance(sources: Iterable[Any],
                   ask: Optional[Any] = None) -> Dict[str, Any]:
    """Sur/taal/saaz ke peeche ki CITED baatein — bina source id kuch nahi.

    `ran: False` ka matlab "kuch padha hi nahi gaya" hai, "sab theek hai" nahi.
    Aur `lines` khaali hone ka matlab "research me kuch nahi tha" nahi — sirf ye
    ki JO padha gaya usme music ki baat nahi mili.
    """
    sources = list(sources or [])          # generator do baar nahi ghoomta
    lines: List[Dict[str, Any]] = []
    seen_text: set = set()
    contributing: set = set()
    fields: List[str] = []
    numbers: List[Dict[str, str]] = []
    scanned = 0
    claim_dropped = 0
    full_text_sources = 0

    for source in sources:
        source_id = str(getattr(source, "source_id", "") or "").strip()
        text = songcraft._source_text(source)
        if not text:
            continue
        scanned += 1
        if _read_level(source) == "full_text":
            full_text_sources += 1
        if not source_id:
            # id nahi to citation nahi, aur bina citation koi line nahi jaati.
            continue
        taken = 0
        for sentence in songcraft._sentences(text):
            if len(sentence) < songcraft.MIN_GUIDANCE_CHARS:
                continue
            norm = songcraft._norm(sentence)
            if any(songcraft._cue_present(norm, junk)
                   for junk in songcraft._JUNK_CUES):
                continue
            field = field_of(sentence)
            if not field:
                continue
            # "dhun mast banegi" jaisi line hidayat nahi, bina-naap daawa hai —
            # songcraft ka wahi detector, dobara likha nahi gaya.
            if songcraft.music_claims_in(sentence):
                claim_dropped += 1
                continue
            clipped = sentence[:songcraft.MAX_GUIDANCE_CHARS].strip()
            key = clipped.casefold()
            if key in seen_text or taken >= songcraft.MAX_GUIDANCE_PER_SOURCE:
                continue
            if len(lines) >= MAX_MUSIC_LINES:
                break
            seen_text.add(key)
            taken += 1
            contributing.add(source_id)
            if field not in fields:
                fields.append(field)
            found = reported_numbers_in(clipped)
            for value in found:
                numbers.append({"value": value, "source_id": source_id,
                                "label": REPORTED_NUMBER_LABEL})
            lines.append({
                "text": clipped,
                "source_id": source_id,
                "field": field,
                "field_label": FIELD_LABELS.get(field, ""),
                "reported_numbers": found,
                "url": str(getattr(source, "url", "") or ""),
                "connector": str(getattr(source, "connector", "") or ""),
                "read_level": _read_level(source),
                "user_supplied": media_study._user_supplied(source),
            })
        if len(lines) >= MAX_MUSIC_LINES:
            break

    missing = [key for key in FIELD_KEYS if key not in fields]
    note = (f"{len(lines)} baat {len(contributing)} padhi hui source se aayi "
            f"(har line ke saath source id hai) — ye PADHI hui research hai, "
            f"koi dhun bajaakar nahi dekhi gayi"
            if lines else
            "sur/taal/saaz ke baare me kuch padha nahi gaya — isliye koi music "
            "direction cited nahi hai (apne aap se number nahi ghade gaye)")
    return {
        "ran": bool(scanned),
        "lines": lines,
        "source_count": len(contributing),
        "sources_scanned": scanned,
        "full_text_source_count": full_text_sources,
        "fields": list(fields),
        "field_labels": [FIELD_LABELS.get(key, "") for key in fields],
        "missing_fields": missing,
        "missing_field_labels": [FIELD_LABELS.get(key, "") for key in missing],
        "reported_numbers": numbers,
        "reported_number_count": len(numbers),
        "claim_lines_dropped": claim_dropped,
        # Chaar jhande jo kabhi True nahi hote — naam se hi seema dikhe.
        "audio_generated": AUDIO_GENERATED,
        "tune_made": TUNE_MADE,
        "heard": HEARD,
        "play_tested": PLAY_TESTED,
        "music_direction_is_suggestion": MUSIC_DIRECTION_IS_SUGGESTION,
        "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "ask": (ask.to_dict() if hasattr(ask, "to_dict") else {}),
        "note": note,
    }


# ── 5. NAAP: music direction ke peeche koi padhi hui baat hai ya nahi? ────────
# Status ke naam songcraft se aate hain (MET/NOT_MET/NOT_MEASURED) — ek hi
# vocabulary, warna UI/audit do alag shabd dikhane lagte.
#
# Ye naap songcraft ke `music_direction_present` ke SAATH chalta hai, uski jagah
# nahi: wahan sawaal hai "khaane likhe gaye?", yahan sawaal hai "unke peeche
# padhi hui baat hai?". Do alag sawaal, do alag ginti.
CHECK_NAME = "music_direction_cited"
COMPANION_CHECK_NAME = "music_direction_present"     # songcraft ka, chhua nahi

# Ye naam JAAN-BOOJH KAR mana hain: inme se koi bhi is app ke naap me maujood
# nahi hai, aur aisa naam likhna hi jhooth hoga.
FORBIDDEN_CHECK_NAMES: Tuple[str, ...] = (
    "tune_will_work", "dhun_achhi", "sounds_good", "audio_ready",
    "mix_ready", "hit_sound", "music_quality_ok", "melody_tested",
)


def support_row(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ek hi imaandaar row: direction CITED hai, nahi mili, ya naapi hi nahi gayi."""
    report = report or {}
    lines = list(report.get("lines") or [])
    scanned = int(report.get("sources_scanned") or 0)
    if not report.get("ran") or not scanned:
        return {"check": CHECK_NAME, "status": songcraft.NOT_MEASURED,
                "measured": "", "target": "kam se kam 1 cited baat",
                "reason": "koi source padha hi nahi gaya",
                "note": ("music-study chali nahi — ye 'sab theek hai' NAHI hai, "
                         "ye 'naapa hi nahi gaya' hai")}
    if not lines:
        return {"check": CHECK_NAME, "status": songcraft.NOT_MET,
                "measured": f"0 cited baat / {scanned} source padhe",
                "target": "kam se kam 1 cited baat",
                "reason": "",
                "note": ("jo padha gaya usme sur/taal/saaz ki koi baat nahi "
                         "mili — isliye music direction is baar bina padhi hui "
                         "authority ki hai")}
    return {"check": CHECK_NAME, "status": songcraft.MET,
            "measured": (f"{len(lines)} cited baat / "
                         f"{int(report.get('source_count') or 0)} source"),
            "target": "kam se kam 1 cited baat", "reason": "",
            "note": ("MET ka matlab sirf ye hai ki baat PADHI HUI source se "
                     "aayi — ye saboot nahi ki dhun achhi lagegi (app ne kuch "
                     "suna hi nahi)")}


# ── 6. prompt block, report ki lines, seemaayein aur policy ──────────────────
MAX_PROMPT_LINES = 5
EMPTY_PROMPT_LINE = (
    "Sur/taal/saaz ke baare me is baar kuch padha nahi gaya — isliye BPM, raag, "
    "key ya saaz ka koi number/naam authority ki tarah mat likho; jo likho use "
    "apni pasand kaho.")
PROMPT_RULES: Tuple[str, ...] = (
    "Ye baatein PADHI HUI research se hain — koi dhun nahi bani, kuch suna nahi "
    "gaya (audio_generated=False), isliye \"dhun mast banegi\", \"sunne me "
    "kamaal\" jaisa daawa mat likho.",
    "Source ka number (BPM / key / taal) SOURCE-REPORTED hai — usko apne naap "
    "ki tarah nahi, source id ke saath likho.",
    "Jis khaane ke peeche kuch padha nahi gaya (tempo, scale/raag, vaadya, "
    "aawaz, arrangement) usko apni pasand kaho, authority nahi.",
)


def prompt_block(report: Optional[Dict[str, Any]] = None) -> str:
    """Synthesis prompt ka hissa — songcraft/listener block ke SAATH, jagah nahi.

    Yahan bhi 0 Gemini call: ye sirf padhi hui line ko shabd me rakhta hai.
    """
    report = report or {}
    out: List[str] = ["MUSIC DIRECTION KI PADHI HUI BAAT (koi dhun nahi bani):"]
    lines = list(report.get("lines") or [])[:MAX_PROMPT_LINES]
    if not lines:
        out.append("- " + EMPTY_PROMPT_LINE)
    else:
        for row in lines:
            label = str(row.get("field_label") or "").strip()
            head = f"({label}) " if label else ""
            out.append(f"- {head}{row.get('text')} "
                       f"[{row.get('source_id')}]")
        missing = list(report.get("missing_field_labels") or [])
        if missing:
            out.append("- In khaano par kuch nahi padha gaya: "
                       + ", ".join(missing[:5])
                       + " — inke bare me daawa mat karna.")
        if int(report.get("reported_number_count") or 0):
            out.append(f"- {int(report.get('reported_number_count'))} number "
                       f"source me likhe the ({REPORTED_NUMBER_LABEL}) — unhe "
                       f"apni sifarish ki tarah mat likho.")
    for rule in PROMPT_RULES:
        out.append("- " + rule)
    return "\n".join(out)


def section_lines(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Report me dikhne wali chhoti si list (jawab ke andar)."""
    report = report or {}
    lines = list(report.get("lines") or [])
    out: List[str] = []
    if not report.get("ran"):
        out.append("Music direction ki research: kuch padha nahi gaya (koi "
                   "source nahi mila) — ye naap 'pass' nahi hua, chala hi nahi.")
        return out
    out.append(f"**Music direction ke peeche padhi hui baat:** "
               f"{len(lines)} baat, "
               f"{int(report.get('source_count') or 0)} source se")
    for row in lines[:4]:
        label = str(row.get("field_label") or "").strip()
        head = f"{label} — " if label else ""
        out.append(f"- {head}{row.get('text')} [{row.get('source_id')}]")
    if report.get("missing_field_labels"):
        out.append("- In par is baar kuch nahi mila: "
                   + ", ".join(list(report.get("missing_field_labels"))[:5]))
    if int(report.get("reported_number_count") or 0):
        out.append(f"- {int(report.get('reported_number_count'))} number source "
                   f"ke hain ({REPORTED_NUMBER_LABEL}) — app ne khud koi BPM/"
                   f"key tay nahi kiya.")
    if int(report.get("claim_lines_dropped") or 0):
        out.append(f"- {int(report.get('claim_lines_dropped'))} line hataayi "
                   f"gayi kyunki wo \"dhun mast banegi\" jaisa bina-naap daawa "
                   f"kar rahi thi")
    out.append("- Koi dhun/audio yahan NAHI bani aur app ne kuch suna nahi — ye "
               "likhi hui salaah hai, bajaakar naapa hua nateeja nahi.")
    return out


# Ye chaar seema HAMESHA jaati hain — inhe haalat par nahi chhoda gaya, kyunki
# "app ne suna nahi" wali baat tab bhi sach hai jab research bahut achhi mile.
_ALWAYS_LIMITS: Tuple[str, ...] = (
    "Yahan koi dhun/audio NAHI bani "
    f"(audio_generated={AUDIO_GENERATED}, tune_made={TUNE_MADE}) — music "
    "direction likhi hui salaah hai, bajaaya hua nateeja nahi.",
    f"App ne kuch SUNA nahi (heard={HEARD}) aur kisi ne bajaakar test nahi kiya "
    f"(play_tested={PLAY_TESTED}) — isliye 'achhi lagegi' ka koi naap nahi hai.",
    "Padhi hui research DUSRE gaanon/sunne walon par naapi gayi thi — "
    "\"minor = sad\" jaisa rishta ek jhukav hai, niyam nahi.",
    "Music ke khaane pehchaanne wali list adhoori hai, isliye 'is khaane par "
    "kuch nahi mila' ka matlab 'research me kuch nahi tha' nahi hota.",
)


def limits(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit me jaane wali seemaayein. Pehli chaar HAMESHA jaati hain.

    Report do to usme se ginti wali seema bhi jud jaati hai (kitne khaane khaali
    rahe, kitne number source ke the, kitni daawa-line hataayi gayi, poora text
    padha gaya ya sirf snippet). Ye lines chhupana hi wo jhooth hai jise ye
    module rokta hai.
    """
    out: List[str] = list(_ALWAYS_LIMITS)
    if report is None:
        return out
    report = report or {}
    if not report.get("ran"):
        out.append("Is baar music-study chali hi nahi (koi source padha nahi "
                   "gaya) — ye naap 'pass' nahi hua, hua hi nahi.")
        return out
    if not list(report.get("lines") or []):
        out.append(f"{int(report.get('sources_scanned') or 0)} source padhe gaye "
                   f"par sur/taal/saaz ki ek bhi cited baat nahi mili — music "
                   f"direction is baar bina padhi hui authority ki hai.")
    missing = list(report.get("missing_field_labels") or [])
    if missing:
        out.append("In khaano par is baar kuch nahi padha gaya: "
                   + ", ".join(missing) + " — inke bare me koi daawa nahi.")
    numbers = int(report.get("reported_number_count") or 0)
    if numbers:
        out.append(f"{numbers} number/key SOURCE ke hain "
                   f"({REPORTED_NUMBER_LABEL}) — app ne khud koi BPM, key ya "
                   f"taal tay nahi kiya.")
    dropped = int(report.get("claim_lines_dropped") or 0)
    if dropped:
        out.append(f"{dropped} line hataayi gayi kyunki wo \"dhun mast banegi\" "
                   f"jaisa bina-naap daawa kar rahi thi.")
    if not int(report.get("full_text_source_count") or 0):
        out.append("Jo padha gaya wo sirf snippet/abstract tha, poora text "
                   "nahi — isliye baat adhoori ho sakti hai.")
    return out


# Audit me `limits()` ki POORI list jaani chahiye. Chhat yahan DERIVE hoti hai
# (hard-coded number nahi) taaki nayi seema jodne par purana number chup-chaap
# jhooth na bol de — #134 me exactly yahi bug pakda gaya tha.
ALWAYS_LIMIT_LINES = len(_ALWAYS_LIMITS)     # 4 — hamesha jaati hain
SITUATIONAL_LIMIT_LINES = 5                  # 0-cited, khaali khaane, number,
#                                              hataayi hui daawa-line, snippet-only
MAX_AUDIT_LIMIT_LINES = ALWAYS_LIMIT_LINES + SITUATIONAL_LIMIT_LINES


def policy() -> Dict[str, Any]:
    """Kaise kaam hua — audit ke policy khaane me jaata hai."""
    return {
        "network_used": NETWORK_USED,
        "randomness_used": False,
        "gemini_calls": GEMINI_CALLS,
        "deterministic": True,
        "provider_cost": "₹0",
        "measured_by": "offline_rules_in_music_study_py",
        "audio_generated": AUDIO_GENERATED,
        "tune_made": TUNE_MADE,
        "heard": HEARD,
        "play_tested": PLAY_TESTED,
        "music_direction_is_suggestion": MUSIC_DIRECTION_IS_SUGGESTION,
        "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
        "reported_numbers_are_source_reported": True,
        "claim_lines_dropped_not_hidden": True,
        "merged_into_craft_guidance": False,
        "replaces_music_direction_present": False,
        "hit_predicted": False,
        "sound_quality_measured": False,
    }


# ── 7. ek hi darwaza (orchestrator/craft yahi bulate hain) ───────────────────
def study(question: str = "", sources: Iterable[Any] = (),
          ask: Optional[Any] = None, wanted: bool = True) -> Dict[str, Any]:
    """Query list + cited music direction + prompt block, ek dict me. 0 Gemini.

    `ask` na do to `songcraft.style_of(question)` se ban jaata hai — tempo/style
    wali pehli query isi se aati hai. `sources` khaali ho to `guidance["ran"]`
    False rehta hai: ye "sab theek hai" nahi, "padha hi nahi gaya" hai.

    `wanted` caller (orchestrator) ka faisla hai: ye lane sirf gaane wali
    farmaish par chalti hai. Isse report me `music_section`/`music_limits` chup
    rehte hain jab sawaal gaane ka hi nahi tha — warna physics ke jawab me bhi
    "kaunsa raag lagao" chipakne lagta.
    """
    if ask is None:
        try:
            ask = songcraft.style_of(str(question or ""))
        except Exception:
            ask = None
    guidance = music_guidance(sources, ask=ask)
    queries = study_queries(ask)
    return {
        "ran": True,                      # module chala; padhna alag baat hai
        "wanted": bool(wanted),
        "reason": "",
        "ask": ask,
        "ask_dict": (ask.to_dict() if hasattr(ask, "to_dict") else {}),
        "queries": queries,
        "plan": study_plan(ask),
        "guidance": guidance,
        "support_row": support_row(guidance),
        "prompt_block": prompt_block(guidance),
        "section_lines": section_lines(guidance),
        "limits": limits(guidance),
        "policy": policy(),
        "music_line_count": len(list(guidance.get("lines") or [])),
        "music_source_count": int(guidance.get("source_count") or 0),
        "music_evidence_read": bool(guidance.get("lines")),
        "reported_number_count": int(guidance.get("reported_number_count") or 0),
        "audio_generated": AUDIO_GENERATED,
        "tune_made": TUNE_MADE,
        "heard": HEARD,
        "play_tested": PLAY_TESTED,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "cannot_measure": list(CANNOT_MEASURE_EXTRA),
    }


NOT_ASKED_REASON = ("farmaish gaane jaisi nahi lagi, isliye music direction ki "
                    "research padhi hi nahi gayi")


def not_asked(reason: str = NOT_ASKED_REASON) -> Dict[str, Any]:
    """Lane chali hi nahi — par imaandaar shakal me, khaali dict ki tarah nahi.

    `wanted: False` aur `ran: False` alag baat kehte hain: pehla "maangi nahi
    gayi", doosra "padhi nahi gayi". Dono jhande report ko chup rakhte hain.
    """
    empty = {"ran": False, "lines": [], "source_count": 0,
             "sources_scanned": 0, "full_text_source_count": 0,
             "fields": [], "field_labels": [],
             "missing_fields": list(FIELD_KEYS),
             "missing_field_labels": [FIELD_LABELS[key] for key in FIELD_KEYS],
             "reported_numbers": [], "reported_number_count": 0,
             "claim_lines_dropped": 0,
             "audio_generated": AUDIO_GENERATED,
             "tune_made": TUNE_MADE,
             "heard": HEARD,
             "play_tested": PLAY_TESTED,
             "music_direction_is_suggestion": MUSIC_DIRECTION_IS_SUGGESTION,
             "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
             "gemini_calls": GEMINI_CALLS, "network_used": NETWORK_USED,
             "ask": {}, "note": str(reason or NOT_ASKED_REASON)}
    return {"ran": False, "wanted": False, "reason": str(reason
                                                         or NOT_ASKED_REASON),
            "ask": None, "ask_dict": {}, "queries": [], "plan": {},
            "guidance": empty, "support_row": support_row({}),
            "prompt_block": "", "section_lines": [], "limits": [],
            "policy": policy(),
            "music_line_count": 0, "music_source_count": 0,
            "music_evidence_read": False,
            "reported_number_count": 0,
            "audio_generated": AUDIO_GENERATED,
            "tune_made": TUNE_MADE,
            "heard": HEARD,
            "play_tested": PLAY_TESTED,
            "gemini_calls": GEMINI_CALLS, "network_used": NETWORK_USED,
            "cannot_measure": list(CANNOT_MEASURE_EXTRA),
            "note": str(reason or NOT_ASKED_REASON)}


# ── 8. report ke block (media_study/listener_study ka wahi dhaancha) ─────────
# Do alag function jaan-boojh kar: section tab chhapta hai jab lane MAANGI gayi
# ho, aur audit ki seemaayein bhi usi haalat me jaati hain — warna har report me
# "koi dhun nahi bani" wali line bekaar chipakti rehti (aur bekaar chipki hui
# seema padhna band kar deti hai, yehi asli nuksaan hai).
#
# Heading me "padhi hui research" aur "koi dhun nahi bani" — dono jaan-boojh kar,
# kyunki heading hi sabse pehle padhi jaati hai aur jhooth wahin se shuru hota
# hai (#134 ka D13 sabaq).
MUSIC_SUBHEADING = ("### Music direction ke peeche padhi hui research "
                    "(koi dhun nahi bani)")


def music_section(pack: Optional[Dict[str, Any]] = None) -> str:
    """Answer me chhapne wala block. Lane maangi na gayi ho to "" (khaali)."""
    if not isinstance(pack, dict) or not pack.get("wanted"):
        return ""
    guidance = pack.get("guidance") or {}
    out: List[str] = [MUSIC_SUBHEADING, ""]
    rows = list(guidance.get("lines") or [])
    if not guidance.get("ran"):
        # Note khud hi poori baat kehta hai ("kuch padha nahi gaya…") — usko
        # dobara apne shabdon me nahi likhte, warna line do baar wahi kehti hai.
        out.append("- " + (str(guidance.get("note") or "").strip()
                           or "music direction ke baare me kuch padha nahi gaya"))
        return "\n".join(out)
    out.append(f"**Kitni baat padhi gayi:** {len(rows)} "
               f"({int(guidance.get('source_count') or 0)} source se)")
    out.append("")
    if not rows:
        out.append("- " + str(guidance.get("note") or ""))
    for row in rows:
        label = str(row.get("field_label") or "").strip()
        head = f"{label} — " if label else ""
        out.append(f"- {head}{str(row.get('text') or '').strip()} "
                   f"[{row.get('source_id')}]")
    missing = list(guidance.get("missing_field_labels") or [])
    if missing:
        out.append("")
        out.append("**In khaano par is baar kuch nahi mila:** "
                   + ", ".join(missing))
    numbers = list(guidance.get("reported_numbers") or [])
    if numbers:
        out.append("")
        out.append(f"**Source ke number ({REPORTED_NUMBER_LABEL}, app ki "
                   f"sifarish nahi):** "
                   + ", ".join(f"{str(row.get('value') or '')} "
                               f"[{row.get('source_id')}]" for row in numbers))
    dropped = int(guidance.get("claim_lines_dropped") or 0)
    if dropped:
        out.append(f"- {dropped} line hataayi gayi kyunki wo \"dhun mast "
                   f"banegi\" jaisa bina-naap daawa kar rahi thi.")
    return "\n".join(out)


def music_limits(pack: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit ki seemaayein — sirf tab jab ye lane sach me maangi gayi ho."""
    if not isinstance(pack, dict) or not pack.get("wanted"):
        return []
    return limits(pack.get("guidance") or {})


# Result model / API ke liye JSON-safe record. `study()` ke andar `ask` ek object
# hai (usme se query banti hai) — wo API par nahi jaana chahiye, warna serialize
# karte waqt tootta hai. Isliye yahan sirf naapi hui ginti aur naam se likhe hue
# jhande jaate hain, aur chaar jhande hamesha False rehte hain.
def public_record(pack: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """UI/API ke liye chhota, JSON-safe record (koi object, koi raw ask nahi)."""
    if not isinstance(pack, dict):
        return {}
    guidance = pack.get("guidance") or {}
    return {
        "wanted": bool(pack.get("wanted")),
        "ran": bool(guidance.get("ran")),
        "reason": str(pack.get("reason") or ""),
        "note": str(guidance.get("note") or pack.get("note") or ""),
        "ask": dict(pack.get("ask_dict") or {}),
        "query_count": len(list(pack.get("queries") or [])),
        "line_count": len(list(guidance.get("lines") or [])),
        "source_count": int(guidance.get("source_count") or 0),
        "sources_scanned": int(guidance.get("sources_scanned") or 0),
        "full_text_source_count": int(guidance.get("full_text_source_count")
                                      or 0),
        "fields": list(guidance.get("fields") or []),
        "field_labels": list(guidance.get("field_labels") or []),
        "missing_fields": list(guidance.get("missing_fields") or []),
        "missing_field_labels": list(guidance.get("missing_field_labels") or []),
        "reported_numbers": [dict(row) for row in
                             (guidance.get("reported_numbers") or [])],
        "reported_number_count": int(guidance.get("reported_number_count") or 0),
        "reported_numbers_are_source_reported": True,
        "claim_lines_dropped": int(guidance.get("claim_lines_dropped") or 0),
        "claim_lines_dropped_not_hidden": True,
        "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
        "support_row": dict(pack.get("support_row") or support_row(guidance)),
        "limits": list(music_limits(pack)),
        # Ye chaar jhande naam se hi seema batate hain — kabhi True nahi hote.
        "audio_generated": AUDIO_GENERATED,
        "tune_made": TUNE_MADE,
        "heard": HEARD,
        "play_tested": PLAY_TESTED,
        "music_direction_is_suggestion": MUSIC_DIRECTION_IS_SUGGESTION,
        "merged_into_craft_guidance": False,
        "replaces_music_direction_present": False,
        "companion_check": COMPANION_CHECK_NAME,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
    }
