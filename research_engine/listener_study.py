"""listener_study — "logon ka dil" ki PADHI HUI samajh (#134a).

intel ki maang (jyun ki tyun): "use feeling emosion hona chahiye wo bhi feel kre
logo ka dil pdhe emosion jaane kya psnd h human behviyar ... jaise phycology ka
ya music ka ya pdf ya video ya summary ya logo ki recording ya bade singer ki
book notes".

#128-#133 ne gaane ka HUNAR padhna shuru kiya (songcraft: matra, hook, style,
music direction; media_study: recording ka parichay/transcript). Us hisse me ek
cheez ab bhi patli thi: SUNNE WALA. Bhaav kaise kaam karta hai, log kisi gaane se
kyun judte hain, yaad/nostalgia ka kya role hai, dohraav se pehchaan kaise banti
hai — ye psychology aur human-behaviour ki research ka ilaaka hai, aur uske liye
poori ek alag query lane chahiye thi. Ye module wahi bharta hai. Kharch: ₹0,
Gemini call 0, network 0 (ye sirf query BANATA hai aur pehle se aaye sources
PADHTA hai).

CHAAR JHOOTH jo ye file JAAN-BOOJH KAR nahi bolti:

  1. **"Research padhi" ≠ "logon ka dil padha".** App ne kisi insaan se kuch nahi
     poochha, koi audience test nahi hua, koi play-count nahi dekha. Isliye
     `LISTENER_TESTED = False`, `AUDIENCE_MEASURED = False`, `MIND_READ = False`
     — hamesha, aur ye teen baat audit me jaati hain.

  2. **Research ka nateeja tere sunne wale ka naap nahi hai.** Padhi hui baat
     kisi aur sample (aksar dusre desh/bhasha ke log) par naapi gayi thi. Isliye
     har line source id ke saath jaati hai aur uske saath ye seema bhi.

  3. **Bhaav ek FAISLA hai, vaada nahi.** "log ro denge", "sabka dil jeet lega",
     "pakka hit" — aisi line hidayat nahi, marketing hai. `_PROMISE_RE` unhe
     hataata hai aur ginti (`promise_lines_dropped`) report me jaati hai, chup
     nahi rehti.

  4. **Ye songcraft ki jagah NAHI leta.** Craft ki hidayat (hook/matra/dhaancha)
     wahin rehti hai; yahan sirf sunne wale ki samajh aati hai, apne alag label
     aur apni alag ginti ke saath. Do ginti mila dena hi wo jhooth hai jise
     #133 me bhi rokha gaya tha.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# songcraft ke gates DOBARA nahi likhe ja rahe: sentence todna, junk shabd,
# lambai ki hadd aur per-source cap wahi rehte hain. Do copy hamesha ek din alag
# ho jaati hain — isliye ek hi sach, wahin se.
from . import songcraft
from . import media_study

# ── 1. is lane ka sach (naam se likhi hui naa-kaabiliyat) ────────────────────
LISTENER_TESTED = False        # kisi asli sunne wale par gaana test nahi hua
AUDIENCE_MEASURED = False      # koi play-count / A-B / survey nahi dekha gaya
MIND_READ = False              # kisi ka dil "padha" nahi gaya — research padhi
NETWORK_USED = False           # ye module query BANATA hai, chalata nahi
GEMINI_CALLS = 0               # ek bhi model call nahi

CANNOT_MEASURE_EXTRA = (
    "kya tera sunne wala asli me ye bhaav mehsoos karega (koi insaan par test "
    "nahi hua — sirf research padhi gayi)",
    "kaunsa gaana chalega ya hit hoga (iska koi naap is app ke paas nahi hai)",
)

# ── 2. STUDY QUERY — sirf string, koi call nahi ──────────────────────────────
# Lane ke naam songcraft.STUDY_LANES se aate hain (ek hi vocabulary), warna
# `source_discovery` me routing chup-chaap web par gir jaati.
MAX_LISTENER_QUERIES = 3
MIN_QUERY_CHARS = 8

# Mood ka naam `craft.MOODS` ke label se aata hai — "dukh", "judaai", "yaad"
# jaisa ek chhota ASCII shabd. Mood se query BANTI hai, isliye yahan sirf wahi
# shakal chalti hai; koi bhi lambi/free text (jaise "<gaane ka naam> song
# lyrics") mood ke bhes me network query me nahi ghus sakti. Ye deewar #186e ke
# baad bhi khadi rehti hai: `songcraft.is_lyrics_hunt()` ab NAAM wali bol-talaash
# bhi pakadta hai, par uski bachi hui seema (`songcraft.LYRICS_HUNT_KNOWN_LIMIT`
# — ek hi anjaan shabd) par ye pehra jaan-boojh kar rakha gaya hai.
_SAFE_MOOD_RE = re.compile(r"^[a-z]{2,14}$")


def safe_mood(mood: Any) -> str:
    """Query me daalne laayak mood, warna khaali string (chup-chaap nahi girta:
    mood chhoot jaata hai par seeds phir bhi chalti hain)."""
    token = " ".join(str(mood or "").split()).casefold()
    return token if _SAFE_MOOD_RE.match(token) else ""

LISTENER_SEEDS: Tuple[Tuple[str, str, str], ...] = (
    ("music emotion listener response psychology research", "papers",
     "sunne wale par bhaav kaise asar karta hai — research se"),
    ("nostalgia autobiographical memory in songs listener", "papers",
     "yaad/nostalgia gaane se kaise judti hai"),
    ("psychology of emotion human behaviour appraisal theory", "books",
     "bhaav aur insaani vyavhaar ki buniyaad — kitaab se"),
    ("audience reaction interview what listeners connect with", "media",
     "sunne walon ke bare me gaane walon ki apni baat — recording se"),
    ("repetition familiarity liking earworm listener", "papers",
     "dohraav se pehchaan aur pasand kaise banti hai"),
)


def study_queries(ask: Optional[Any] = None,
                  limit: int = MAX_LISTENER_QUERIES) -> List[Dict[str, str]]:
    """Sunne wale ko samajhne ki query list — mood wali query sabse pehle.

    `ask` `songcraft.StyleAsk` hota hai (ya kuch bhi jiske paas `moods` ho). Na
    ho to sirf seeds chalti hain — lane phir bhi khaali nahi baithta.
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

    for mood in list(getattr(ask, "moods", []) or [])[:1]:
        clean_mood = safe_mood(mood)
        if not clean_mood:
            continue
        push(f"{clean_mood} emotion in music listener response research",
             "papers",
             f"'{clean_mood}' bhaav sunne wale par kaise asar karta hai "
             f"— research se")
    for query, lane, why in LISTENER_SEEDS:
        push(query, lane, why)
    return out


def study_plan(ask: Optional[Any] = None,
               limit: int = MAX_LISTENER_QUERIES) -> Dict[str, Any]:
    """planner ke liye ek dict — `listener_study` lane isi se banti hai."""
    queries = study_queries(ask, limit=limit)
    return {
        "listener_study": queries,
        "listener_study_lane": {
            "wanted": bool(queries),
            "query_count": len(queries),
            "lanes": [row["lane"] for row in queries],
            "reasons": [row["why"] for row in queries],
            # Query banana padhna NAHI hai — ye do jhande isliye False hi rehte
            # hain, chahe lane chal jaaye.
            "listener_evidence_read": False,
            "listener_tested": LISTENER_TESTED,
            "audience_measured": AUDIENCE_MEASURED,
            "lyrics_hunt_blocked": True,
            "network_used_here": NETWORK_USED,
            "gemini_calls": GEMINI_CALLS,
            "note": ("sunne wale ke bhaav/vyavhaar ki research dhoondhne ke liye "
                     "query bani — kisi insaan par koi test nahi hua"
                     if queries else "koi listener-study query nahi bani"),
        },
    }


# ── 3. SUNNE WALE ki baat pehchaanna (craft ke cue se ALAG) ──────────────────
# Ye list adhoori hai aur rahegi — isliye `CUE_LIST_IS_NOT_EXHAUSTIVE` audit me
# jaata hai. Group ka faayda: report bata sakti hai ki kis-kis cheez par kuch
# padha gaya AUR kis par kuch nahi mila (khaali jagah chhupti nahi).
CUE_GROUPS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("bhaav", "bhaav ka utaar-chadhaav (valence/arousal)",
     ("emotion", "emotional", "affect", "affective", "valence", "arousal",
      "mood", "feeling", "bhaav", "sadness", "melancholy", "longing",
      "viraha", "joy", "happiness", "anger", "tension", "release")),
    ("yaad", "yaad aur nostalgia",
     ("nostalgia", "nostalgic", "memory", "memories", "autobiographical",
      "reminisce", "remind", "yaad", "childhood", "past")),
    ("apnapan", "khud se jodna (self-reference, empathy)",
     ("self-reference", "self reference", "self-referential", "identify",
      "identification", "empathy", "empathic", "relatable", "personal",
      "first person", "perspective taking", "apnapan")),
    ("dohraav", "dohraav se pehchaan (familiarity, earworm)",
     ("familiarity", "familiar", "repetition", "repeated", "earworm",
      "mere exposure", "catchy", "recall", "remember the hook", "singalong")),
    ("sanskriti", "sanskriti ka farq (culture-specific asar)",
     ("culture", "cultural", "cross-cultural", "enculturation", "western",
      "non-western", "sample of students", "tradition", "language of the song")),
    ("vyavhaar", "vyavhaar aur pasand (behaviour, preference)",
     ("preference", "preferences", "liking", "listener behaviour",
      "listener behavior", "attention", "engagement", "motivation", "reward",
      "why people listen", "choice")),
)
CUE_LIST_IS_NOT_EXHAUSTIVE = True

GROUP_KEYS: Tuple[str, ...] = tuple(key for key, _l, _c in CUE_GROUPS)
GROUP_LABELS: Dict[str, str] = {key: label for key, label, _c in CUE_GROUPS}

# Vaada karne wali line hidayat nahi hoti — wo marketing hai. Isse hataayi gayi
# line ki GINTI report me jaati hai (chhupana ek jhooth hoga).
_PROMISE_RE = re.compile(
    r"\b(?:guaranteed|guarantee|sure[\s-]?shot|surefire|"
    r"(?:will|shall)\s+(?:definitely\s+)?make\s+(?:you|them|people|everyone|"
    r"listeners|anyone)|everyone\s+will|every\s+listener\s+will|"
    r"never\s+fails?\s+to\s+make)\b"
    r"|sabka\s+dil|pakka\s+hit|zaroor\s+hit|100%\s*hit|har\s+koi\s+ro",
    re.I)

MAX_LISTENER_LINES = 6


def is_promise(sentence: str) -> bool:
    """"log ro denge / pakka hit" jaisi line — saboot nahi, vaada hai."""
    return bool(_PROMISE_RE.search(str(sentence or "")))


def cue_group(sentence: str) -> str:
    """Line kis samajh ke group me girti hai; koi cue na mile to khaali."""
    norm = songcraft._norm(sentence)
    for key, _label, cues in CUE_GROUPS:
        for cue in cues:
            if songcraft._cue_present(norm, cue):
                return key
    return ""


# ── 4. PADHI HUI research me se CITED samajh ─────────────────────────────────
def _read_level(source: Any) -> str:
    return str(getattr(source, "read_level", "") or "").strip().lower()


def listener_guidance(sources: Iterable[Any],
                      ask: Optional[Any] = None) -> Dict[str, Any]:
    """Sunne wale ke bhaav/vyavhaar ki CITED baatein — bina source id kuch nahi.

    `ran: False` ka matlab "kuch padha hi nahi gaya" hai, "sab theek hai" nahi.
    Aur `lines` khaali hone ka matlab "research me kuch nahi tha" nahi — sirf ye
    ki JO padha gaya usme sunne wale ki baat nahi mili.
    """
    sources = list(sources or [])          # generator do baar nahi ghoomta
    lines: List[Dict[str, Any]] = []
    seen_text: set = set()
    contributing: set = set()
    groups: List[str] = []
    scanned = 0
    promise_dropped = 0
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
            group = cue_group(sentence)
            if not group:
                continue
            if is_promise(sentence):
                promise_dropped += 1
                continue
            clipped = sentence[:songcraft.MAX_GUIDANCE_CHARS].strip()
            key = clipped.casefold()
            if key in seen_text or taken >= songcraft.MAX_GUIDANCE_PER_SOURCE:
                continue
            if len(lines) >= MAX_LISTENER_LINES:
                break
            seen_text.add(key)
            taken += 1
            contributing.add(source_id)
            if group not in groups:
                groups.append(group)
            lines.append({
                "text": clipped,
                "source_id": source_id,
                "group": group,
                "group_label": GROUP_LABELS.get(group, ""),
                "url": str(getattr(source, "url", "") or ""),
                "connector": str(getattr(source, "connector", "") or ""),
                "read_level": _read_level(source),
                "user_supplied": media_study._user_supplied(source),
            })
        if len(lines) >= MAX_LISTENER_LINES:
            break

    missing = [key for key in GROUP_KEYS if key not in groups]
    note = (f"{len(lines)} baat {len(contributing)} padhi hui source se aayi "
            f"(har line ke saath source id hai) — ye research ka nateeja hai, "
            f"tere sunne wale ka naap nahi"
            if lines else
            "sunne wale ke bhaav/vyavhaar ke baare me kuch padha nahi gaya — "
            "isliye koi baat nahi di gayi (apne aap se salaah nahi ghadi)")
    return {
        "ran": bool(scanned),
        "lines": lines,
        "source_count": len(contributing),
        "sources_scanned": scanned,
        "full_text_source_count": full_text_sources,
        "groups": list(groups),
        "group_labels": [GROUP_LABELS.get(key, "") for key in groups],
        "missing_groups": missing,
        "missing_group_labels": [GROUP_LABELS.get(key, "") for key in missing],
        "promise_lines_dropped": promise_dropped,
        # Teen jhande jo kabhi True nahi hote — naam se hi seema dikhe.
        "listener_tested": LISTENER_TESTED,
        "audience_measured": AUDIENCE_MEASURED,
        "mind_read": MIND_READ,
        "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "ask": (ask.to_dict() if hasattr(ask, "to_dict") else {}),
        "note": note,
    }


# ── 5. NAAP: kya bhaav ke peeche koi padhi hui baat hai? ─────────────────────
# Status ke naam songcraft se aate hain (MET/NOT_MET/NOT_MEASURED) — ek hi
# vocabulary, warna UI/audit do alag shabd dikhane lagte.
CHECK_NAME = "listener_understanding_cited"

# Ye naam JAAN-BOOJH KAR mana hain: inme se koi bhi is app ke naap me maujood
# nahi hai, aur aisa naam likhna hi jhooth hoga.
FORBIDDEN_CHECK_NAMES: Tuple[str, ...] = (
    "listener_will_feel_it", "audience_tested", "hit_probability",
    "emotion_guaranteed", "dil_jeeta",
)


def support_row(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ek hi imaandaar row: samajh CITED hai, nahi mili, ya naapi hi nahi gayi."""
    report = report or {}
    lines = list(report.get("lines") or [])
    scanned = int(report.get("sources_scanned") or 0)
    if not report.get("ran") or not scanned:
        return {"check": CHECK_NAME, "status": songcraft.NOT_MEASURED,
                "measured": "", "target": "kam se kam 1 cited baat",
                "reason": "koi source padha hi nahi gaya",
                "note": ("listener-study chali nahi — ye 'sab theek hai' NAHI "
                         "hai, ye 'naapa hi nahi gaya' hai")}
    if not lines:
        return {"check": CHECK_NAME, "status": songcraft.NOT_MET,
                "measured": f"0 cited baat / {scanned} source padhe",
                "target": "kam se kam 1 cited baat",
                "reason": "",
                "note": ("jo padha gaya usme sunne wale ke bhaav/vyavhaar ki "
                         "koi baat nahi mili — isliye bhaav ka faisla bina "
                         "padhi hui authority ka hai")}
    return {"check": CHECK_NAME, "status": songcraft.MET,
            "measured": (f"{len(lines)} cited baat / "
                         f"{int(report.get('source_count') or 0)} source"),
            "target": "kam se kam 1 cited baat", "reason": "",
            "note": ("MET ka matlab sirf ye hai ki baat PADHI HUI source se "
                     "aayi — ye saboot nahi ki sunne wale ko waisa mehsoos "
                     "hoga (koi insaan par test nahi hua)")}


# ── 6. prompt block, report ki lines, seemaayein aur policy ──────────────────
MAX_PROMPT_LINES = 5
EMPTY_PROMPT_LINE = (
    "Sunne wale ke bhaav/vyavhaar ke baare me is baar kuch padha nahi gaya — "
    "isliye \"log aisa mehsoos karenge\" jaisi koi baat mat likho.")
PROMPT_RULES: Tuple[str, ...] = (
    "Ye baatein RESEARCH se padhi gayi hain, kisi asli sunne wale se nahi — "
    "\"log ro denge\", \"sabka dil jeet lega\", \"pakka hit\" jaisa vaada mat "
    "likho.",
    "Bhaav ka faisla likhte waqt uske peeche ki padhi hui baat ka source id "
    "saath rakho; jiske peeche kuch padha nahi gaya use apni pasand kaho, "
    "authority nahi.",
)


def prompt_block(report: Optional[Dict[str, Any]] = None) -> str:
    """Synthesis prompt ka hissa — songcraft/media block ke SAATH, jagah nahi.

    Yahan bhi 0 Gemini call: ye sirf padhi hui line ko shabd me rakhta hai.
    """
    report = report or {}
    out: List[str] = ["SUNNE WALE KI SAMAJH (padhi hui research se):"]
    lines = list(report.get("lines") or [])[:MAX_PROMPT_LINES]
    if not lines:
        out.append("- " + EMPTY_PROMPT_LINE)
    else:
        for row in lines:
            label = str(row.get("group_label") or "").strip()
            head = f"({label}) " if label else ""
            out.append(f"- {head}{row.get('text')} "
                       f"[{row.get('source_id')}]")
        missing = list(report.get("missing_group_labels") or [])
        if missing:
            out.append("- In cheezon par kuch nahi padha gaya: "
                       + ", ".join(missing[:4])
                       + " — inke bare me daawa mat karna.")
    for rule in PROMPT_RULES:
        out.append("- " + rule)
    return "\n".join(out)


def section_lines(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Report me dikhne wali chhoti si list (jawab ke andar)."""
    report = report or {}
    lines = list(report.get("lines") or [])
    out: List[str] = []
    if not report.get("ran"):
        out.append("Sunne wale ki samajh: kuch padha nahi gaya (koi source "
                   "nahi mila) — ye naap 'pass' nahi hua, chala hi nahi.")
        return out
    out.append(f"**Sunne walon ke bhaav ki samajh (padhi hui research se):** "
               f"{len(lines)} baat, "
               f"{int(report.get('source_count') or 0)} source se")
    for row in lines[:4]:
        label = str(row.get("group_label") or "").strip()
        head = f"{label} — " if label else ""
        out.append(f"- {head}{row.get('text')} [{row.get('source_id')}]")
    if report.get("missing_group_labels"):
        out.append("- Is baar in par kuch nahi mila: "
                   + ", ".join(list(report.get("missing_group_labels"))[:4]))
    if int(report.get("promise_lines_dropped") or 0):
        out.append(f"- {int(report.get('promise_lines_dropped'))} line hataayi "
                   f"gayi kyunki wo vaada kar rahi thi (\"pakka hit\" jaisi "
                   f"baat saboot nahi hoti)")
    out.append("- Kisi asli sunne wale par ye gaana test NAHI hua — ye samajh "
               "research se hai, tere shrota ka naap nahi.")
    return out


def limits(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit me jaane wali seemaayein. Pehli teen HAMESHA jaati hain.

    Report do to usme se ginti wali seema bhi jud jaati hai (kitne group par
    kuch nahi padha, kitni vaada-line hataayi gayi). Ye lines chhupana hi wo
    jhooth hoga jise ye module rokta hai.
    """
    out: List[str] = [
        "Sunne wale ki samajh RESEARCH se padhi gayi hai — kisi asli insaan "
        f"par gaana test nahi hua (listener_tested={LISTENER_TESTED}).",
        "Koi play-count, A/B test ya survey nahi dekha gaya "
        f"(audience_measured={AUDIENCE_MEASURED}); kisi ka dil 'padha' nahi "
        f"gaya (mind_read={MIND_READ}).",
        "Padhi hui research kisi DUSRE sample par naapi gayi thi (aksar dusri "
        "bhasha/desh ke log) — wo tere sunne wale ka naap nahi hai.",
        "Bhaav ki cue-list adhoori hai, isliye 'kuch nahi mila' ka matlab "
        "'research me kuch nahi tha' nahi hota.",
    ]
    if report is None:
        return out
    report = report or {}
    if not report.get("ran"):
        out.append("Is baar listener-study chali hi nahi (koi source padha "
                   "nahi gaya) — ye naap 'pass' nahi hua, hua hi nahi.")
        return out
    if not list(report.get("lines") or []):
        out.append(f"{int(report.get('sources_scanned') or 0)} source padhe "
                   f"gaye par sunne wale ke bhaav/vyavhaar ki ek bhi cited "
                   f"baat nahi mili — bhaav ka faisla is baar bina padhi hui "
                   f"authority ka hai.")
    missing = list(report.get("missing_group_labels") or [])
    if missing:
        out.append("In cheezon par is baar kuch nahi padha gaya: "
                   + ", ".join(missing) + " — inke bare me koi daawa nahi.")
    dropped = int(report.get("promise_lines_dropped") or 0)
    if dropped:
        out.append(f"{dropped} line hataayi gayi kyunki wo vaada kar rahi thi "
                   f"(\"pakka hit\" / \"sabka dil\" jaisi baat saboot nahi "
                   f"hoti).")
    if not int(report.get("full_text_source_count") or 0):
        out.append("Jo padha gaya wo sirf snippet/abstract tha, poora text "
                   "nahi — isliye baat adhoori ho sakti hai.")
    return out


# Audit me `limits()` ki POORI list jaani chahiye. Ginti yahan likhi hai taaki
# report/audit ka slice isi module ke sach se bandha rahe: 4 line hamesha aati
# hain + 4 haalat wali (ek bhi cited baat nahi mili, kaun se bhaav chhoot gaye,
# kitni vaada wali line hataayi gayi, sirf snippet padha gaya). Isse chhoti
# chhat rakhna = ek naapi hui seema chup-chaap kaat dena.
MAX_AUDIT_LIMIT_LINES = 8


def policy() -> Dict[str, Any]:
    """Kaise kaam hua — audit ke policy khaane me jaata hai."""
    return {
        "network_used": NETWORK_USED,
        "randomness_used": False,
        "gemini_calls": GEMINI_CALLS,
        "deterministic": True,
        "provider_cost": "₹0",
        "measured_by": "offline_rules_in_listener_study_py",
        "listener_tested": LISTENER_TESTED,
        "audience_measured": AUDIENCE_MEASURED,
        "mind_read": MIND_READ,
        "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
        "promise_lines_dropped_not_hidden": True,
        "merged_into_craft_guidance": False,
        "hit_predicted": False,
        "emotion_guaranteed": False,
    }


# ── 7. ek hi darwaza (orchestrator/craft yahi bulate hain) ───────────────────
def study(question: str = "", sources: Iterable[Any] = (),
          ask: Optional[Any] = None, wanted: bool = True) -> Dict[str, Any]:
    """Query list + cited samajh + prompt block, ek hi dict me. 0 Gemini call.

    `ask` na do to `songcraft.style_of(question)` se ban jaata hai — mood wali
    pehli query isi se aati hai. `sources` khaali ho to `guidance["ran"]` False
    rehta hai: ye "sab theek hai" nahi, "padha hi nahi gaya" hai.

    `wanted` caller (orchestrator) ka faisla hai: ye lane sirf gaane wali
    farmaish par chalti hai. Isse report me `listener_section`/`listener_limits`
    chup rehte hain jab sawaal gaane ka hi nahi tha — warna physics ke jawab me
    bhi "sunne wale ka bhaav" chipakne lagta.
    """
    if ask is None:
        try:
            ask = songcraft.style_of(str(question or ""))
        except Exception:
            ask = None
    guidance = listener_guidance(sources, ask=ask)
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
        "listener_line_count": len(list(guidance.get("lines") or [])),
        "listener_source_count": int(guidance.get("source_count") or 0),
        "listener_evidence_read": bool(guidance.get("lines")),
        "listener_tested": LISTENER_TESTED,
        "audience_measured": AUDIENCE_MEASURED,
        "mind_read": MIND_READ,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "cannot_measure": list(CANNOT_MEASURE_EXTRA),
    }


NOT_ASKED_REASON = ("farmaish gaane jaisi nahi lagi, isliye sunne wale ki "
                    "research padhi hi nahi gayi")


def not_asked(reason: str = NOT_ASKED_REASON) -> Dict[str, Any]:
    """Lane chali hi nahi — par imaandaar shakal me, khaali dict ki tarah nahi.

    `wanted: False` aur `ran: False` alag baat kehte hain: pehla "maangi nahi
    gayi", doosra "padhi nahi gayi". Dono jhande report ko chup rakhte hain.
    """
    empty = {"ran": False, "lines": [], "source_count": 0,
             "sources_scanned": 0, "full_text_source_count": 0,
             "groups": [], "group_labels": [],
             "missing_groups": list(GROUP_KEYS),
             "missing_group_labels": [GROUP_LABELS[key] for key in GROUP_KEYS],
             "promise_lines_dropped": 0,
             "listener_tested": LISTENER_TESTED,
             "audience_measured": AUDIENCE_MEASURED,
             "mind_read": MIND_READ,
             "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
             "gemini_calls": GEMINI_CALLS, "network_used": NETWORK_USED,
             "ask": {}, "note": str(reason or NOT_ASKED_REASON)}
    return {"ran": False, "wanted": False, "reason": str(reason
                                                         or NOT_ASKED_REASON),
            "ask": None, "ask_dict": {}, "queries": [], "plan": {},
            "guidance": empty, "support_row": support_row({}),
            "prompt_block": "", "section_lines": [], "limits": [],
            "policy": policy(),
            "listener_line_count": 0, "listener_source_count": 0,
            "listener_evidence_read": False,
            "listener_tested": LISTENER_TESTED,
            "audience_measured": AUDIENCE_MEASURED,
            "mind_read": MIND_READ,
            "gemini_calls": GEMINI_CALLS, "network_used": NETWORK_USED,
            "cannot_measure": list(CANNOT_MEASURE_EXTRA),
            "note": str(reason or NOT_ASKED_REASON)}


# ── 8. report ke block (media_study.media_section/media_limits ka dhaancha) ───
# Do alag function jaan-boojh kar: section tab chhapta hai jab lane MAANGI gayi
# ho, aur audit ki seemaayein bhi usi haalat me jaati hain — warna har report me
# "sunne wale par test nahi hua" wali line bekaar chipakti rehti (aur bekaar
# chipki hui seema padhna band kar deti hai, yehi asli nuksaan hai).
LISTENER_SUBHEADING = "### Sunne wale ke bhaav ki samajh (padhi hui research se)"


def listener_section(pack: Optional[Dict[str, Any]] = None) -> str:
    """Answer me chhapne wala block. Lane maangi na gayi ho to "" (khaali)."""
    if not isinstance(pack, dict) or not pack.get("wanted"):
        return ""
    guidance = pack.get("guidance") or {}
    out: List[str] = [LISTENER_SUBHEADING, ""]
    rows = list(guidance.get("lines") or [])
    if not guidance.get("ran"):
        # Note khud hi poori baat kehta hai ("kuch padha nahi gaya…") — usko
        # dobara apne shabdon me nahi likhte, warna line do baar wahi kehti hai.
        out.append("- " + (str(guidance.get("note") or "").strip()
                           or "sunne wale ke baare me kuch padha nahi gaya"))
        return "\n".join(out)
    out.append(f"**Kitni baat padhi gayi:** {len(rows)} "
               f"({int(guidance.get('source_count') or 0)} source se)")
    out.append("")
    if not rows:
        out.append("- " + str(guidance.get("note") or ""))
    for row in rows:
        label = str(row.get("group_label") or "").strip()
        head = f"{label} — " if label else ""
        out.append(f"- {head}{str(row.get('text') or '').strip()} "
                   f"[{row.get('source_id')}]")
    missing = list(guidance.get("missing_group_labels") or [])
    if missing:
        out.append("")
        out.append("**In par is baar kuch nahi mila:** " + ", ".join(missing))
    dropped = int(guidance.get("promise_lines_dropped") or 0)
    if dropped:
        out.append(f"- {dropped} line hataayi gayi kyunki wo vaada kar rahi thi "
                   f"(\"pakka hit\" jaisi baat saboot nahi hoti).")
    return "\n".join(out)


def listener_limits(pack: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit ki seemaayein — sirf tab jab ye lane sach me maangi gayi ho."""
    if not isinstance(pack, dict) or not pack.get("wanted"):
        return []
    return limits(pack.get("guidance") or {})


# Result model / API ke liye JSON-safe record. `study()` ke andar `ask` ek
# object hai (usme se query banti hai) — wo API par nahi jaana chahiye, warna
# serialize karte waqt tootta hai. Isliye yahan sirf naapi hui ginti aur naam se
# likhe hue jhande jaate hain, aur teen jhande hamesha False rehte hain.
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
        "groups": list(guidance.get("groups") or []),
        "group_labels": list(guidance.get("group_labels") or []),
        "missing_groups": list(guidance.get("missing_groups") or []),
        "missing_group_labels": list(guidance.get("missing_group_labels")
                                     or []),
        "promise_lines_dropped": int(guidance.get("promise_lines_dropped")
                                     or 0),
        "promise_lines_dropped_not_hidden": True,
        "cue_list_is_not_exhaustive": CUE_LIST_IS_NOT_EXHAUSTIVE,
        "support_row": dict(pack.get("support_row") or support_row(guidance)),
        "limits": list(listener_limits(pack)),
        # Ye teen jhande naam se hi seema batate hain — kabhi True nahi hote.
        "listener_tested": LISTENER_TESTED,
        "audience_measured": AUDIENCE_MEASURED,
        "mind_read": MIND_READ,
        "merged_into_craft_guidance": False,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
    }
