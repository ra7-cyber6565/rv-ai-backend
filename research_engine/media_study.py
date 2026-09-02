"""#133 — MEDIA STUDY: video/audio ke LIKHE HUE transcript se craft padhna.

intel ki maang (jyon ki tyon): "...ya pdf ya video ya summary ya logo ki
recording ya bade singer ki book notes gaane dekhe wo ye sab cheeje procec
krke phir use smj aana chahiye..."

#120 ne backend ke teen media raaste website par laaye the (audio upload,
YouTube captions, bounded book reading) — par wo content sirf "uploaded
document" ban kar baithta tha. Do asli kamiyan thi:

  1. Timestamp wala citation TOOT jaata tha. `rag/pipeline.py` header
     `[Source: talk.vtt, Page 12:30]` banata hai, par purani parse `Page (\\d+)`
     maangti thi — "12:30" match hi nahi hota, isliye poora transcript EK
     source me chipak jaata tha aur locator KHAALI reh jaata tha. Naap kar
     dekha gaya: 2 timestamped block -> 1 record, locator "".
  2. Gaane ka craft-study (#129/#130) sirf kitaab/paper/web se padhta tha.
     User ka apna diya hua transcript craft ki hidayat ke liye padha hi nahi
     jaata tha.

Ye module teeno kaam deterministic aur ₹0 me karta hai:

    1. LOCATOR ka kism pehchano — page / samay (timestamp) / hissa. Timestamp
       ko "Page" kehna JHOOTH hai, aur wahi jhooth citation me chhap raha tha.
    2. MEDIA kism pehchano — captions, aawaz se bana transcript, ya sirf
       "samay-mohar wala" (jab kism ka pata na ho). Andaza nahi: faisla sirf
       file ke extension aur locator ke kism se hota hai.
    3. CRAFT GUIDANCE — media transcript me se craft ki baat, #130 ke wahi
       gates (citation zaroori, junk filter, bounded lines) se guzaar kar,
       par HAR line par media ka imaandaar label chipka kar.
    4. DHOONDHA HUA media alag ginna (#133b) — `connectors/media_connector.py`
       archive.org se lecture/interview/recording DHOONDHTA hai, par uska
       transcript humein milta hi nahi: sirf uploader ka likha hua parichay
       milta hai. "Mila" aur "padha" ek nahi hain, isliye unka hisaab
       `discovered_media()` me ALAG rehta hai aur report me alag line jaati
       hai. Wo items kabhi craft-hidayat ke source nahi bante.

JO YE MODULE JAAN-BOOJH KAR NAHI KARTA (aur naam se likhta hai):

  * Video ka FRAME, scene ya visual kabhi nahi padha jaata (`FRAMES_READ`).
    "video dekh liya" ek jhooth hai — sirf likha hua text padha jaata hai.
  * Aawaz SUNI nahi jaati (`AUDIO_LISTENED`): sur, dhun, gaayki, lehja — inme
    se kuch bhi naapa nahi jaata, chahe transcript aawaz se hi bana ho.
  * Search se mile media ko "padha hua" nahi ginta: unka `read_level`
    "snippet" hota hai, aur `media_sources()` unhe uthata hi nahi (unke paas
    na media extension hota hai na samay-mohar). Isliye unke naam par koi
    craft-hidayat nahi banti.
  * User ki di hui copy se kuch VERIFIED nahi hota
    (`USER_MEDIA_CAN_VERIFY = False`) — #91 ka wahi niyam yahan bhi.
  * Ye module network nahi chhoota aur ek bhi model call nahi karta.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import songcraft

# ── sach jo har baar report/audit me jaata hai ────────────────────────────────
NETWORK_USED = False            # yahan se koi request nahi jaati
GEMINI_CALLS = 0                # ek bhi model call nahi
FRAMES_READ = False             # frame/scene/visual kabhi nahi padha jaata
AUDIO_LISTENED = False          # aawaz suni nahi jaati, sirf likha hua text
USER_MEDIA_CAN_VERIFY = False   # apni di hui copy se VERIFIED nahi hota
TRANSCRIPT_IS_TEXT_ONLY = True  # jo padha gaya wo text hai, media nahi

CANNOT_MEASURE = (
    "video ka frame/scene/visual (padha hi nahi jaata)",
    "aawaz, sur, dhun ya gaayki (transcript sirf shabd deta hai)",
    "transcript kitna sahi bana (captions/STT ki apni galtiyan rehti hain)",
    "bolne wale ka asli matlab, jab shabd adhoore hon",
    "user ki di hui copy asli hai ya nahi — isliye isse VERIFIED nahi banta",
    "search se mile video/audio ke ANDAR kya kaha gaya (unka transcript "
    "milta hi nahi, sirf parichay milta hai)",
)

# ── 1. LOCATOR ka kism ───────────────────────────────────────────────────────
# Ye "sirf naam ka" farq nahi hai. Citation me "Page 12:30" likhna do jhooth
# bolta hai: (a) ye page nahi hai, (b) is source me page number hi nahi hote.
# Naap yahan bhi wahi hai jo baaki jagah: kism PATA na chale to andaza nahi
# lagate — `LOCATOR_UNKNOWN` lautta hai aur locator jaisa aaya tha waisa hi
# chhapta hai (galat prefix lagane se accha hai).
LOCATOR_PAGE = "page"
LOCATOR_TIME = "timestamp"
LOCATOR_PART = "part"
LOCATOR_UNKNOWN = ""
LOCATOR_KINDS: Tuple[str, ...] = (LOCATOR_PAGE, LOCATOR_TIME, LOCATOR_PART,
                                  LOCATOR_UNKNOWN)

_STAMP = r"\d{1,3}:[0-5]\d(?::[0-5]\d)?"
# range me en-dash (transcript_processor ka `–`), em-dash, hyphen aur "to" —
# teeno shakalein asli data me milti hain.
_TIME_RE = re.compile(r"^" + _STAMP + r"(?:\s*(?:[-–—]|to)\s*" + _STAMP +
                      r")?$", re.I)
_PAGE_RE = re.compile(r"^(?:page|pannaa?|pg\.?|p\.?)?\s*(\d{1,6})"
                      r"(?:\s*[-–—]\s*\d{1,6})?$", re.I)
# Kram lamba-se-chhota: `p\.?` pehle rakha jaaye to "page 12" ka sirf "p" kat
# kar "age 12" bach jaata hai (`locator_label` ke `re.sub` me anchor nahi hota,
# isliye backtracking bacha nahi paati). Naap kar dekha gaya: "Page age 12".
_PAGE_PREFIX_RE = re.compile(r"^(?:page|pannaa?|pg\.?|p\.?)\s*", re.I)
_PART_RE = re.compile(r"^(?:part|hissa|hisaa|section|chunk|block)\s*(\d{1,6})$",
                      re.I)


def locator_kind(raw: Any) -> str:
    """"12:30–14:30" -> timestamp, "12" -> page, "part 3" -> part, warna ""."""
    token = " ".join(str(raw or "").split())
    if not token:
        return LOCATOR_UNKNOWN
    # Kram maayne rakhta hai: timestamp pehle, warna "12:30" ka "12" page ban
    # jaata (yahi purani parse ki galti thi).
    if _TIME_RE.match(token):
        return LOCATOR_TIME
    if _PART_RE.match(token):
        return LOCATOR_PART
    if _PAGE_RE.match(token):
        return LOCATOR_PAGE
    return LOCATOR_UNKNOWN


def locator_label(raw: Any) -> str:
    """Citation me chhapne wala imaandaar locator.

    Timestamp par "Samay" jaata hai, page par "Page", hisse par "Hissa". Kism
    pata na ho to raw token hi lautta hai — koi prefix nahi, kyunki galat
    prefix se khaali locator bhi behtar hai.
    """
    token = " ".join(str(raw or "").split())
    if not token:
        return ""
    kind = locator_kind(token)
    if kind == LOCATOR_TIME:
        return "Samay " + token
    if kind == LOCATOR_PAGE:
        # Prefix hataate hain par RANGE nahi — "7-9" ko "Page 7" likhna teesre
        # aur aathve page ka jhooth bol dega. Sirf shabd wala prefix jaata hai.
        return "Page " + _PAGE_PREFIX_RE.sub("", token).strip()
    if kind == LOCATOR_PART:
        match = _PART_RE.match(token)
        return "Hissa " + (match.group(1) if match else token)
    return token



# `rag/pipeline.py` ka header: "[Source: file, Page <locator>]". Purani parse
# `Page\s*(\d+)` thi — timestamp us par match hi nahi karta tha, isliye poora
# transcript ek record me chipak jaata tha. Ab locator KOI bhi token ho sakta
# hai (`]` aur newline chhod kar), aur kism `locator_kind()` tay karta hai.
HEADER_RE = re.compile(r"\[Source:\s*([^,\]\n]+),\s*Page\s*([^\]\n]{1,40})\]")

# ── 2. MEDIA ka kism ─────────────────────────────────────────────────────────
# Faisla sirf DO naapi hui cheezon se hota hai: file ka extension aur locator
# ka kism. Title me "video" likha hona kaafi nahi — user file ka naam kuch bhi
# rakh sakta hai, aur naam se kism tay karna andaza hai.
KIND_CAPTIONS = "captions"              # .vtt/.srt — likhe hue captions
KIND_AUDIO_TEXT = "audio_transcript"    # aawaz se banaya gaya likhit
KIND_TIMESTAMPED = "timestamped_media"  # samay-mohar hai, kism ka pata nahi
MEDIA_KINDS: Tuple[str, ...] = (KIND_CAPTIONS, KIND_AUDIO_TEXT,
                                KIND_TIMESTAMPED)

CAPTION_EXTENSIONS: Tuple[str, ...] = (".vtt", ".srt", ".sbv", ".ttml", ".dfxp")
# Video file bhi isi list me hai, JAAN-BOOJH KAR: humne uska sirf AUDIO padha
# hai. Isliye kind "audio_transcript" hi rehta hai, "video" kabhi nahi.
AV_EXTENSIONS: Tuple[str, ...] = (".mp3", ".wav", ".m4a", ".flac", ".ogg",
                                  ".opus", ".aac", ".wma", ".mp4", ".mkv",
                                  ".webm", ".mov", ".avi", ".m4v", ".3gp")
# YouTube ingest ka default naam `youtube_<id>` hai (api/routes.py) — uska
# extension nahi hota, isliye ye ek naapi hui pehchaan hai, andaza nahi.
CAPTION_TITLE_PREFIXES: Tuple[str, ...] = ("youtube_", "yt_")
# Ye extension NAAP kar bataate hain ki file media nahi hai. Bina iske ek .pdf
# ka ajeeb locator (jaise "12:30") use "timestamped_media" bana deta tha — wo
# ek anaapa daawa hai. Kitaab/notes par media ka label kabhi nahi lagta.
TEXT_EXTENSIONS: Tuple[str, ...] = (".pdf", ".txt", ".md", ".doc", ".docx",
                                    ".rtf", ".odt", ".epub", ".mobi", ".djvu",
                                    ".htm", ".html", ".csv", ".json", ".xml")


def _ext_of(title: Any) -> str:
    token = str(title or "").strip().lower()
    dot = token.rfind(".")
    return token[dot:] if dot > 0 and len(token) - dot <= 6 else ""


def media_kind(title: Any = "", locator: Any = "") -> str:
    """Media ka kism, ya "" (matlab: ye media nahi lag raha)."""
    token = str(title or "").strip().lower()
    ext = _ext_of(token)
    if ext in CAPTION_EXTENSIONS:
        return KIND_CAPTIONS
    if any(token.startswith(prefix) for prefix in CAPTION_TITLE_PREFIXES):
        return KIND_CAPTIONS
    if ext in AV_EXTENSIONS:
        return KIND_AUDIO_TEXT
    if ext in TEXT_EXTENSIONS:
        # Kitaab/notes/webpage — locator kuch bhi ho, ye media nahi hai.
        return ""
    # Extension kuch na bataye par locator samay ka ho — to itna kehna sach hai
    # ki ye samay-mohar wala transcript hai. Kism (video/audio) ka daawa nahi.
    if locator_kind(locator) == LOCATOR_TIME:
        return KIND_TIMESTAMPED
    return ""


# ── 3. IMAANDAAR label ───────────────────────────────────────────────────────
# Har label me wo baat hai jo NAHI hui. #120 ka `NO_FRAME_NOTE` wala sabak:
# sirf "transcript padha" likhna kaafi nahi — padhne wala apne aap maan leta hai
# ki video dekh liya gaya.
KIND_LABELS: Dict[str, str] = {
    KIND_CAPTIONS: ("video/audio ke LIKHIT captions padhe gaye — frame, scene "
                    "ya visual ka koi analysis nahi, aawaz bhi suni nahi gayi"),
    KIND_AUDIO_TEXT: ("aawaz se bana LIKHIT transcript padha gaya — dhun, sur "
                      "aur gaayki naapi nahi gayi; video ka sirf audio padha "
                      "jaata hai"),
    KIND_TIMESTAMPED: ("samay-mohar wala LIKHIT transcript padha gaya — ye "
                       "video ka tha ya audio ka, iska pata nahi"),
}
USER_COPY_NOTE = ("Ye copy user ne khud di hai — isse koi baat VERIFIED nahi "
                  "hoti aur ye consensus me nahi ginti.")


def kind_label(kind: Any) -> str:
    """Kism ka imaandaar label; anjaan kism par khaali (jhootha label nahi)."""
    return KIND_LABELS.get(str(kind or ""), "")


def document_note(title: Any = "", locator: Any = "",
                  user_supplied: bool = True) -> str:
    """Report/citation ke saath jaane wali ek line — ya khaali, agar media nahi."""
    kind = media_kind(title, locator)
    if not kind:
        return ""
    parts = [kind_label(kind)]
    if user_supplied:
        parts.append(USER_COPY_NOTE)
    return " ".join(part for part in parts if part)


# ── 4. CRAFT GUIDANCE — media transcript se, #130 ke wahi gates ──────────────
# Yahan hidayat nikaalne ka niyam DOBARA nahi likha ja raha. `songcraft`
# (#130) ke paas pehle se citation-zaroori, junk-filter aur bounded-lines wale
# gate hain; media source unhi me se guzarte hain. Is module ka kaam sirf do
# hai: (a) media sources CHUNNA, (b) har line par imaandaar media label lagana.
# Isse ek bhi gate do jagah nahi rehta (do copy hamesha alag ho jaati hain).
def media_sources(sources: Iterable[Any]) -> List[Any]:
    """Sirf wo sources jinka media kism naapa ja saka."""
    out: List[Any] = []
    for source in list(sources or []):
        kind = media_kind(getattr(source, "title", ""),
                          getattr(source, "locator", ""))
        if kind:
            out.append(source)
    return out


def _user_supplied(source: Any) -> bool:
    # Sirf naapi hui baat: uploaded document ka connector `user_pdf` hota hai
    # (evidence.py) aur source_type DOCUMENT. Baaki sab bahar ka maana jaata
    # hai — aur bahar ke media par "user ne di" likhna jhooth hoga.
    connector = str(getattr(source, "connector", "") or "").strip().lower()
    if connector in ("user_pdf", "user_document", "upload"):
        return True
    kind = str(getattr(getattr(source, "source_type", None), "value", "")
               or getattr(source, "source_type", "") or "").lower()
    return "document" in kind


def not_asked(reason: str = "kuch banane ki farmaish nahi thi") -> Dict[str, Any]:
    """#155c — lane ka taala: craft ki farmaish hi nahi thi.

    Kyun zaroori hai: ye lane pehle HAR sawaal par chalti thi. Trading ka model
    ya physics ka sawaal poochne par bhi, agar kisi lecture-video ka transcript
    sources me aa gaya, to jawab me "user ke video/audio se craft padha" wala
    block chipak jaata tha. `wanted: False` ka matlab "maanga hi nahi gaya" hai
    — "media mila nahi" nahi. `discovered` yahan jaan-boojh kar khaali hai,
    taaki `media_section()` khaali laut aaye aur audit me koi seema-line na jude.
    """
    return {
        "ran": False,
        "wanted": False,
        "lines": [],
        "media_source_count": 0,
        "sources_scanned": 0,
        "discovered": {},
        "kinds": [],
        "user_supplied_count": 0,
        "style_conventions_read": False,
        "numeric_conventions": [],
        "frames_read": FRAMES_READ,
        "audio_listened": AUDIO_LISTENED,
        "verified_allowed": USER_MEDIA_CAN_VERIFY,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "note": str(reason or ""),
    }


def craft_guidance(sources: Iterable[Any],
                   ask: Optional[Any] = None) -> Dict[str, Any]:
    """Media transcript me se CITED craft-hidayat + media ka imaandaar label.

    `ran: False` ka matlab hai "media padha hi nahi gaya" — "sab theek hai"
    nahi. Ek bhi media source na mile to yahi haalat normal hai.
    """
    # Ek hi baar list banate hain: `sources` generator ho to neeche dobara
    # ghoomne par khaali milta aur "0 media mile" jhooth ban jaata.
    sources = list(sources or [])
    # DHOONDHA hua media (#133b) dono haalat me report me jaata hai — chahe koi
    # transcript padha gaya ho ya nahi. "ran" sirf PADHNE ke baare me hai.
    found = discovered_media(sources)
    picked = media_sources(sources)
    if not picked:
        return {"ran": False, "lines": [], "media_source_count": 0,
                "sources_scanned": len(list(sources or [])),
                "discovered": found,
                "kinds": [], "user_supplied_count": 0,
                "style_conventions_read": False,
                "numeric_conventions": [],
                "frames_read": FRAMES_READ, "audio_listened": AUDIO_LISTENED,
                "verified_allowed": USER_MEDIA_CAN_VERIFY,
                "gemini_calls": GEMINI_CALLS, "network_used": NETWORK_USED,
                "note": ("koi video/audio transcript nahi mila — media se kuch "
                         "padha nahi gaya")}

    inner = songcraft.guidance_from(picked, ask=ask)
    by_id = {}
    for source in picked:
        source_id = str(getattr(source, "source_id", "") or "").strip()
        if source_id:
            by_id[source_id] = source

    lines: List[Dict[str, Any]] = []
    kinds: List[str] = []
    for row in list(inner.get("lines") or []):
        source = by_id.get(str(row.get("source_id") or ""))
        kind = media_kind(getattr(source, "title", ""),
                          getattr(source, "locator", "")) if source else ""
        supplied = _user_supplied(source) if source is not None else False
        row = dict(row)
        row["media_kind"] = kind
        row["locator"] = locator_label(getattr(source, "locator", ""))
        row["media_label"] = kind_label(kind)
        row["user_supplied"] = supplied
        lines.append(row)
        if kind and kind not in kinds:
            kinds.append(kind)

    supplied_count = sum(1 for source in picked if _user_supplied(source))
    note = (f"{len(lines)} hidayat {len(picked)} media transcript me se aayi "
            f"(har line ke saath source id aur samay/locator hai)"
            if lines else
            "media transcript padha gaya par craft ki koi baat nahi mili — "
            "isliye koi hidayat nahi di gayi")
    return {
        "ran": True,
        "lines": lines,
        "media_source_count": len(picked),
        "sources_scanned": int(inner.get("sources_scanned") or 0),
        "discovered": found,
        "kinds": kinds,
        "user_supplied_count": supplied_count,
        # Convention (asli number) media se bhi aa sakti hai — wo #130 ke wahi
        # gate se nikli hai, isliye seedha aage bhejte hain, dobara nahi ginte.
        "numeric_conventions": list(inner.get("numeric_conventions") or []),
        "style_conventions_read": bool(inner.get("style_conventions_read")),
        "frames_read": FRAMES_READ,
        "audio_listened": AUDIO_LISTENED,
        "verified_allowed": USER_MEDIA_CAN_VERIFY,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "note": note,
    }


# ── 5. prompt block, policy aur seemaayein ───────────────────────────────────
MAX_PROMPT_LINES = 6
EMPTY_PROMPT_LINE = ("Koi video/audio transcript nahi padha gaya — isliye "
                     "\"video me suna tha\" jaisi koi baat mat likho.")


def prompt_block(guidance: Optional[Dict[str, Any]] = None) -> str:
    """Synthesis prompt me jaane wala block — songcraft ke block ke SAATH.

    Iski jagah nahi leta: songcraft kitaab/paper wali hidayat laata hai, ye
    media wali. Dono ke apne label rehte hain taaki report me pata rahe kaunsi
    baat kahan se aayi.
    """
    guidance = guidance or {}
    rows = list(guidance.get("lines") or [])
    # Dhoondhe hue media ki chetavni DONO haalat me jaati hai. Sirf "rows
    # bharey hain" waale raste me daalna galti hoti: jab transcript ek bhi na
    # padha ho, tab hi model ke paas sirf naam hote hain — chetavni us waqt
    # sabse zyada zaroori hai.
    warn = discovered_prompt_line(discovered_report(guidance))
    out: List[str] = ["MEDIA SE PADHA HUA (video/audio ka likhit transcript):"]
    if not rows:
        out.append("- " + EMPTY_PROMPT_LINE)
        if warn:
            out.append(warn)
        return "\n".join(out)
    for row in rows[:MAX_PROMPT_LINES]:
        stamp = str(row.get("locator") or "").strip()
        cite = str(row.get("source_id") or "")
        where = f"[{cite}{', ' + stamp if stamp else ''}]"
        out.append(f"- {str(row.get('text') or '').strip()} {where}")
    out.append("- Ye sab LIKHE HUE transcript se aaya hai: frame/scene padha "
               "nahi gaya aur aawaz suni nahi gayi. \"Video dekh kar\" ya "
               "\"sun kar\" jaisa daawa mat likho.")
    if int(guidance.get("user_supplied_count") or 0) > 0:
        out.append("- " + USER_COPY_NOTE)
    if warn:
        out.append(warn)
    return "\n".join(out)


def policy() -> Dict[str, Any]:
    """Audit ke liye ek hi jagah se sach — naam se, taaki chhup na sake."""
    return {
        "lane": "media_study",
        "network_used": NETWORK_USED,
        "gemini_calls": GEMINI_CALLS,
        "frames_read": FRAMES_READ,
        "audio_listened": AUDIO_LISTENED,
        "transcript_is_text_only": TRANSCRIPT_IS_TEXT_ONLY,
        "user_media_can_verify": USER_MEDIA_CAN_VERIFY,
        "media_kinds": list(MEDIA_KINDS),
        "locator_kinds": [kind for kind in LOCATOR_KINDS if kind],
        # Dhoondhe hue media ka sach bhi naam se, taaki audit me chhup na sake:
        # us lane me transcript kabhi nahi aata (#133b).
        "discovered_read_level": DISCOVERED_READ_LEVEL,
        "discovered_transcript_available": False,
        "cannot_measure": list(CANNOT_MEASURE),
    }


def limits() -> List[str]:
    """Report ke neeche jaane wali seemaayein (kami chhupti nahi)."""
    out = ["Media lane ne video/audio ka sirf LIKHIT transcript padha — "
           "frame, scene aur visual ka koi analysis nahi hua "
           f"(frames_read = {FRAMES_READ})."]
    out.append("Aawaz suni nahi gayi: sur, dhun, gaayki aur lehja naapa nahi "
               f"gaya (audio_listened = {AUDIO_LISTENED}).")
    out.append("Transcript me captions/STT ki apni galtiyan reh sakti hain — "
               "shabd jyon ke tyon sach nahi maane jaate.")
    out.append("User ki di hui copy se koi baat VERIFIED nahi hoti "
               f"(user_media_can_verify = {USER_MEDIA_CAN_VERIFY}).")
    return out


def section_lines(guidance: Optional[Dict[str, Any]] = None) -> List[str]:
    """Answer me chhapne wala hissa — khaali haalat par bhi imaandaar line."""
    guidance = guidance or {}
    found = discovered_report(guidance)
    extra: List[str] = []
    if int(found.get("count") or 0):
        extra.append("- " + str(found.get("note") or "")
                     + " — " + str(found.get("limit_line")
                                   or DISCOVERED_LIMIT_LINE))
    if not guidance.get("ran"):
        return ["Media (video/audio) se kuch padha nahi gaya — "
                + str(guidance.get("note") or "koi transcript nahi mila")
                + "."] + extra
    out: List[str] = []
    for row in list(guidance.get("lines") or []):
        stamp = str(row.get("locator") or "").strip()
        cite = str(row.get("source_id") or "")
        tail = f" [{cite}{', ' + stamp if stamp else ''}]"
        out.append("- " + str(row.get("text") or "").strip() + tail)
    if not out:
        out.append("- " + str(guidance.get("note") or ""))
    out.extend(extra)
    for line in limits():
        out.append("- " + line)
    return out


# ── 6. answer/audit me chhapne wale block ────────────────────────────────────
# `craft.craft_section` / `craft_limits` ka wahi dhaancha, taaki report ek jaisi
# padhe. Do alag function jaan-boojh kar: section tab chhapta hai jab media
# PADHA gaya ho YA sirf DHOONDHA gaya ho (#133b), aur audit ki seemaayein bhi
# usi haalat me jaati hain — warna har report me "video nahi padha" wali 4 line
# bekaar chipakti rahegi. Do wajah alag likhi jaati hain: "padha" waali seema
# kehti hai transcript tha par aawaz/frame nahi; "dhoondha" waali kehti hai
# transcript hi nahi tha, sirf parichay tha.
MEDIA_SUBHEADING = "### Media (video/audio) se kya padha gaya"


def media_section(report: Optional[Dict[str, Any]] = None) -> str:
    """Media study ka padhne layak block. Media na padha ho to "" (khaali)."""
    if not isinstance(report, dict):
        return ""
    found = discovered_report(report)
    if not report.get("ran") and not int(found.get("count") or 0):
        return ""
    out: List[str] = [MEDIA_SUBHEADING, ""]
    if report.get("ran"):
        rows = list(report.get("lines") or [])
        kinds = [kind_label(kind) for kind in (report.get("kinds") or [])]
        out.append(f"**Kitne transcript padhe:** "
                   f"{int(report.get('media_source_count') or 0)}")
        for label in kinds:
            if label:
                out.append(f"- {label}")
        if int(report.get("user_supplied_count") or 0) > 0:
            out.append("- " + USER_COPY_NOTE)
        out.append("")
        if not rows:
            out.append("- " + str(report.get("note") or ""))
        for row in rows:
            stamp = str(row.get("locator") or "").strip()
            cite = str(row.get("source_id") or "")
            tail = f" [{cite}{', ' + stamp if stamp else ''}]"
            out.append("- " + str(row.get("text") or "").strip() + tail)
    for line in discovered_lines(found):
        if out and out[-1] and line.startswith("**"):
            out.append("")     # padhe hue hisse se ek khaali line ka farq
        out.append(line)
    return "\n".join(out)


def media_limits(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit ki seemaayein — sirf tab jab media sach me padha ya mila ho."""
    if not isinstance(report, dict):
        return []
    out: List[str] = []
    if report.get("ran"):
        out.extend(limits())
    found = discovered_report(report)
    if int(found.get("count") or 0):
        # Ye seema PADHNE waali seemaon se ALAG hai: wahan transcript tha par
        # aawaz nahi; yahan transcript hi nahi tha. Dono ek line me likhna do
        # alag kami ko ek dikha dega.
        out.append(str(found.get("limit_line") or DISCOVERED_LIMIT_LINE))
    return out


# ── 7. DHOONDHA hua media (#133b) — "mila" aur "padha" ek nahi ───────────────
# #133b me ek naya lane juda: `connectors/media_connector.py` archive.org se
# lecture/interview/recording DHOONDHTA hai. Us lane ke paas transcript NAHI
# hota — sirf uploader ka likha hua parichay. Us farq ko report me likhna
# zaroori hai, warna "media source mila" padhne wala "video dekh liya" samajh
# leta hai (yehi galti #120 me `NO_FRAME_NOTE` se pehle ho rahi thi).
#
# Chunne ka niyam NAAPA hua hai, andaza nahi:
#   * source_type == transcript  → source video/audio family ka hai
#   * media_kind() khaali        → iska koi transcript humne padha hi nahi
#                                  (padha hua transcript #133a ke raste se
#                                  aata hai aur uska kism naapa jaata hai)
#   * user ki di hui copy nahi   → user ke upload ka apna label pehle se hai
DISCOVERED_READ_LEVEL = "snippet"
DISCOVERED_LABEL = ("search se mila video/audio — sirf uska LIKHA HUA parichay "
                    "padha gaya; media na dekha gaya na suna gaya, transcript "
                    "mila hi nahi")
DISCOVERED_LIMIT_LINE = (
    "Kuch video/audio sirf DHOONDHE gaye: unka parichay padha gaya, transcript "
    "nahi mila — unke andar kya kaha gaya, ye is report me naapa nahi gaya.")
MAX_DISCOVERED_ITEMS = 6


def _source_type_name(source: Any) -> str:
    kind = getattr(source, "source_type", "")
    return str(getattr(kind, "value", kind) or "").strip().lower()


def _read_level_of(source: Any) -> str:
    """Record ka apna read level; method ho to wahi (wo hi asli sach hai)."""
    getter = getattr(source, "reading_level", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:
            pass
    return str(getattr(source, "read_level", "") or "")


def discovered_media(sources: Iterable[Any]) -> Dict[str, Any]:
    """Search se mile video/audio ka imaandaar hisaab (padha nahi gaya)."""
    items: List[Dict[str, Any]] = []
    text_read = 0
    for source in list(sources or []):
        if _source_type_name(source) != "transcript":
            continue
        if media_kind(getattr(source, "title", ""),
                      getattr(source, "locator", "")):
            continue                      # ye padha hua transcript hai (#133a)
        if _user_supplied(source):
            continue                      # user ke upload ka label alag hai
        level = _read_level_of(source)
        if level == "full_text":
            # Kal koi lane sach me poora transcript le aaye to ye line jhooth
            # ban jaati — isliye ginti alag rakhi jaati hai, chhupayi nahi.
            text_read += 1
            continue
        items.append({
            "title": str(getattr(source, "title", "") or "").strip(),
            "url": str(getattr(source, "url", "") or "").strip(),
            "source_id": str(getattr(source, "source_id", "") or "").strip(),
            "connector": str(getattr(source, "connector", "") or "").strip(),
            "read_level": level or DISCOVERED_READ_LEVEL,
        })
    return {
        "count": len(items),
        "items": items[:MAX_DISCOVERED_ITEMS],
        "full_transcript_count": text_read,
        "label": DISCOVERED_LABEL,
        "limit_line": DISCOVERED_LIMIT_LINE,
        "frames_read": FRAMES_READ,
        "audio_listened": AUDIO_LISTENED,
        "transcript_available": False,
        "note": (f"{len(items)} video/audio search se mile — sirf parichay "
                 f"padha gaya, media nahi"
                 if items else "search se koi video/audio nahi mila"),
    }


def discovered_report(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`craft_guidance()` ke report me se `discovered` hissa — ya khaali hisaab."""
    if isinstance(report, dict):
        found = report.get("discovered")
        if isinstance(found, dict):
            return found
    return {"count": 0, "items": [], "full_transcript_count": 0,
            "label": DISCOVERED_LABEL, "limit_line": DISCOVERED_LIMIT_LINE,
            "frames_read": FRAMES_READ, "audio_listened": AUDIO_LISTENED,
            "transcript_available": False,
            "note": "search se koi video/audio nahi mila"}


def discovered_lines(found: Optional[Dict[str, Any]] = None) -> List[str]:
    """Answer me jaane wali line — media mila par padha nahi, ye saaf likho."""
    found = found if isinstance(found, dict) else {}
    count = int(found.get("count") or 0)
    if not count:
        return []
    out: List[str] = [f"**Search se mile video/audio (padhe NAHI gaye):** "
                      f"{count}",
                      "- " + str(found.get("label") or DISCOVERED_LABEL)]
    for item in list(found.get("items") or []):
        title = str(item.get("title") or "").strip() or "(bina naam)"
        cite = str(item.get("source_id") or "").strip()
        out.append(f"- {title}" + (f" [{cite}]" if cite else ""))
    return out


def discovered_prompt_line(found: Optional[Dict[str, Any]] = None) -> str:
    """Prompt ke liye ek line — model in items ko "dekha/suna" na maan le."""
    count = int((found or {}).get("count") or 0)
    if not count:
        return ""
    return (f"- {count} video/audio sirf SEARCH me mile: unka sirf likha hua "
            f"parichay padha gaya hai. Unke andar kya kaha gaya, wo humein "
            f"pata NAHI hai — unke naam par koi baat mat likho.")








