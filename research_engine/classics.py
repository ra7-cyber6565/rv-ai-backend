"""Classic/primary-text lane + copyright-safe summary lane. ₹0, model-free.

Do alag raaste, dono deterministic (ek bhi model call nahi):

  LANE A — PUBLIC-DOMAIN TEXT: granth, purane classic, mahan logon ka apna
  likha hua jo ab public domain me hai. Ye ASLI ME padha ja sakta hai
  (Gutenberg ka apna plain-text, Wikisource ka apna API, archive.org ka public
  scan). Iska matlab hai "text padha".

  LANE B — COPYRIGHT BOOK: intel ki shart thi — "jo book copyright ho uski
  summary dekh lo ya kahi or explane de rkha ho usko dekh lo, ignore chhodo
  mt". Isliye copyright book ko CHHODA nahi jaata, par uska mool text kabhi
  fetch nahi hota: uski summary/vyakhya/review/author ke apne free lekh padhe
  jaate hain, aur label par saaf likha rehta hai ki **book padhi nahi gayi**.

Do hard rule jo yahan se kabhi nahi tootenge:
  1. ``copyright_likely`` source ka full text kabhi fetch nahi hoga, aur uska
     read level ``read_ceiling`` se aage nahi badh sakta — yaani
     ``access_depth()`` uspar "FULL TEXT ACCESSED" kabhi nahi likh sakti.
  2. Bina-ijazat copy wale host (shadow library) kabhi nahi chhue jaate —
     na search, na fetch. Ye §2 ka "unofficial API/scraping bypass nahi" hai.

Aur teesra, isi module ki imaandaari: yahan ka output sirf SEARCH PLAN hai.
Kisi granth ka naam le lena use padh lena nahi hai — isliye har plan par
``verified=False`` aur ``evidence_status`` saaf rehta hai.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlparse

from . import lenses as L

try:                                        # models pehle se har jagah hai,
    from .models import READ_LEVEL_ORDER    # par ye module uske bina bhi chale
except Exception:                           # pragma: no cover - defensive
    READ_LEVEL_ORDER = ["metadata", "snippet", "abstract", "claims", "full_text"]


# ── verdict naam (string, taaki JSON/report me seedha ja sake) ───────────────
PUBLIC_DOMAIN = "public_domain_likely"
OPEN_LICENSED = "open_licensed"
COPYRIGHT_LIKELY = "copyright_likely"
UNKNOWN = "unknown"

# Public-domain ka conservative saal. US rule (pre-1929 publications) ka
# roughly safe kinara. Ye "iske baad sab copyright hai" nahi kehta — iske baad
# hum PUBLIC DOMAIN ka DAAVA nahi karte. Faisla hamesha kam-daave wali taraf.
PD_YEAR_MAX = 1928

SUMMARY_LANE_NOTE = (
    "book ka mool text nahi padha gaya — sirf uski summary/vyakhya/review "
    "padhi gayi (ye 'book padh li' nahi hai)"
)
EVIDENCE_STATUS = (
    "search_plan_only__classic_lane_names_are_not_citations_and_no_text_was_read"
)


# ── host niyam ──────────────────────────────────────────────────────────────
# Ye topic/book ki list NAHI hai — ye host-level licence ka faisla hai, isliye
# jis granth/lekhak ka naam intel ne kabhi bataya hi nahi wo bhi isi rule se
# guzarta hai.
_PUBLIC_DOMAIN_HOSTS = ("gutenberg.org", "gutenberg.net.au", "gutenberg.ca")
_OPEN_LICENSED_HOSTS = ("wikisource.org", "wikipedia.org", "wikibooks.org",
                        "wikimedia.org", "wikidata.org")
# Ye host apna access control KHUD lagate hain: jo item public hai uska plain
# text wahi khud serve karte hain, restricted item par khud 403 dete hain.
# Isliye inka published URL maangna bypass nahi hai.
_HOST_GATED_ARCHIVES = ("archive.org", "openlibrary.org")
# Bookstore / subscription — inka full text kabhi nahi.
_COMMERCIAL_TEXT_HOSTS = (
    "books.google.com", "books.google.co.in", "play.google.com", "amazon.com",
    "amazon.in", "audible.com", "scribd.com", "everand.com", "kobo.com",
    "perlego.com", "oreilly.com", "learning.oreilly.com", "chegg.com",
    "coursehero.com", "studocu.com", "bookshop.org", "flipkart.com",
    "barnesandnoble.com", "gumroad.com",
)
# Bina ijazat copy baantne wale host. Inke bahut TLD hote hain (libgen.is /
# .rs / .li), isliye ye SUBSTRING tag hain, exact host nahi.
_UNAUTHORISED_TAGS = (
    "libgen", "sci-hub", "scihub", "annas-archive", "annasarchive", "z-lib",
    "zlibrary", "b-ok", "1lib", "pdfdrive", "oceanofpdf", "dokumen.pub",
    "epdf.", "ebin.pub", "vdoc.pub", "bookfi", "bookzz", "kickass", "piratebay",
)
# Khuli licence ka DAAVA jo source ke apne metadata me milta hai (publisher
# line, snippet, ya connector ka licence field). Ye bhi kisi book/topic ki list
# nahi hai — kisi bhi vishay ka OER textbook, CC-BY monograph, ya lekhak ka khud
# free kiya hua granth isi se pass hota hai. Marker milne par bhi rule ORDER
# maayne rakhta hai: pirate/commercial host pehle reject ho jaate hain, isliye
# wahan "public domain" likh dene se chhoot nahi milti.
_OPEN_LICENCE_MARKERS = (
    "creative commons", "creativecommons.org", "cc by", "cc-by", "cc0",
    "public domain", "publicdomain", "open access", "open-access",
    "openly licensed", "open licence", "open license", "gnu free documentation",
    "gfdl", "copyleft", "oer",
)


def _licence_marker(text: str) -> str:
    """Khuli licence ka marker — SHABD ki seema ke saath.

    Substring se match karna khatarnaak tha: "oer" to "coerce"/"Boer" ke andar
    bhi mil jaata, aur ek galat match modern book ka mool text khol deta. Isliye
    yahan word-boundary lagti hai.
    """
    low = str(text or "").casefold()
    for marker in _OPEN_LICENCE_MARKERS:
        if re.search(r"(?<![a-z0-9])" + re.escape(marker) + r"(?![a-z0-9])", low):
            return marker
    return ""


def _host(url: str) -> str:
    try:
        netloc = urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(":")[0]


def _host_matches(host: str, names: Sequence[str]) -> bool:
    return any(host == name or host.endswith("." + name) for name in names)


def is_unauthorised_host(url: str) -> bool:
    """Shadow library / bina-ijazat copy wala host? (search bhi nahi, fetch bhi nahi)"""
    host = _host(url)
    if not host:
        return False
    return any(tag in host for tag in _UNAUTHORISED_TAGS)


# ── text-lane ka intent: sawaal kisi LIKHE HUE text ki taraf ishara kar raha? ─
# Ye granthon/kitabon ke NAAM ki list nahi hai — ye "likhi hui cheez" ke generic
# shabd hain. Isliye jis book ka naam intel ne kabhi bataya hi nahi, uske liye
# bhi lane khul jaati hai.
_TEXT_WORDS = {
    "book", "books", "kitab", "kitaab", "kitabe", "kitaben", "granth",
    "granths", "granthon", "shastra", "shastras", "shastron", "sutra", "sutras",
    "pustak", "pustaken", "pustakein", "pustakon", "pothi",
    "notebook", "notebooks", "diary", "diaries", "journal", "letters",
    "manuscript", "manuscripts", "scripture", "scriptures", "text", "texts",
    "verse", "verses", "shlok", "shloka", "shlokas", "mantra", "mantras",
    "adhyay", "adhyaya", "chapter", "chapters", "translation", "translations",
    "anuvad", "anuvaad", "commentary", "commentaries", "bhashya", "tika",
    "teeka", "essay", "essays", "treatise", "epic", "hymn", "hymns", "poem",
    "poems", "canto", "edition", "volume", "memoir", "autobiography",
    "biography", "lecture", "lectures", "speech", "sermon", "upadesh",
}
# "asli text chahiye" wale cue. Ye sirf signal mazboot karte hain; akele me
# lane nahi kholte (warna har "read this" wala sawaal text-lane ban jaata).
_READ_CUES = {
    "padh", "padhna", "padho", "padhe", "padha", "padhi", "padhkar", "likha",
    "likhi", "likhe", "likhta", "verbatim", "quote", "quotes", "original",
    "originally", "mool", "asli", "exact", "excerpt", "passage", "fulltext",
    "wording",
}
_SUMMARY_CUES = {
    "summary", "summarise", "summarize", "saransh", "samjhao", "samjha",
    "explain", "explained", "explanation", "vyakhya", "gist", "overview",
    "review", "notes", "takeaways", "seekh", "matlab",
}
# Hinglish/English ke sawaal-shabd. Ye kisi topic ki list nahi — bhasha ke
# sawaal poochne wale shabd hain. Kriti ke naam me ye kabhi nahi aate, isliye
# "muqaddimah kis saal likhi" me naam "muqaddimah" par ruk jaata hai (probe me
# pakda gaya: pehle "muqaddimah kis" ek naam ban kar search bhi ho raha tha aur
# ledger me yaad bhi ho raha tha).
_QUESTION_WORDS = {
    "kya", "kyu", "kyun", "kyon", "kaise", "kaisa", "kaisi", "kab", "kahan",
    "kaha", "kaun", "kaun-sa", "kis", "kisne", "kiska", "kiski", "kiske",
    "kitna", "kitni", "kitne", "konsa", "kaunsa", "what", "why", "how", "when",
    "where", "who", "whom", "whose", "which",
}


def is_question_word(word: str) -> bool:
    """Ye bhasha ka sawaal-shabd hai (kis/kya/kaise/what/why)?"""
    return str(word or "").strip().casefold() in _QUESTION_WORDS


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


# Teen generic set ek jagah — concept_ledger isse poochta hai ki koi shabd
# "aam" hai ya nahi.
_GENERIC_LANE_WORDS = set(_TEXT_WORDS) | set(_READ_CUES) | set(_SUMMARY_CUES)


def is_generic_text_word(word: str) -> bool:
    """Ye shabd "likhi hui cheez" ka AAM shabd hai (granth/book/padho/summary)?

    Ledger isse yaad-rakhne se pehle poochta hai. Warna wo "granth" ko hi ek
    kriti samajh kar yaad kar leta hai aur phir har sawaal par galat lane
    kholta hai — list se azaadi ke naam par ledger khud ko zeher de leta.
    """
    return str(word or "").strip().casefold() in _GENERIC_LANE_WORDS


def _uniq(items: Sequence[str], limit: int = 8) -> List[str]:
    """Order-preserving dedupe (case-insensitive), khaali hata kar."""
    out: List[str] = []
    seen = set()
    for item in items or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _words(question: str) -> List[str]:
    return [w.strip("-") for w in L.tokens(question) if w.strip("-")]


def text_intent(question: str) -> Dict:
    """Sawaal ko text-lane chahiye ya nahi — poori wajah ke saath.

    Galat guess ka nuksaan sirf itna hai ki ek extra search query 0 result
    laati hai (lens ka wahi niyam). Isliye faisla udaar hai, par wajah hamesha
    traceable rehti hai: ``reasons`` me marker/shabd likha jaata hai.
    """
    words = _words(question)
    have = set(words)
    traditions = L.tradition_hits(question)
    text_words = [w for w in words if w in _TEXT_WORDS]
    read_cues = sorted(have & _READ_CUES)
    summary_cues = sorted(have & _SUMMARY_CUES)
    people = L.thinker_candidates(question)

    reasons: List[str] = []
    if traditions:
        reasons.append("tradition_marker:" + ",".join(traditions[:3]))
    if text_words:
        reasons.append("text_word:" + ",".join(_uniq(text_words, limit=3)))
    if read_cues:
        reasons.append("read_cue:" + ",".join(read_cues[:3]))
    if summary_cues:
        reasons.append("summary_cue:" + ",".join(summary_cues[:3]))

    wants = bool(traditions) or bool(text_words)
    return {
        "wants_primary_text": wants,
        "traditions": traditions,
        "text_words": _uniq(text_words, limit=4),
        "people": people,
        "read_cue": bool(read_cues),
        "summary_cue": bool(summary_cues),
        "reasons": reasons,
    }


def work_candidates(question: str, limit: int = 5) -> List[str]:
    """Sambhavit text/kriti ke naam — bina kisi book-list ke.

    Paanch cue, SABSE SPECIFIC pehle: (1) quotes me likha naam, (2) text-shabd
    ke turant baad ka naam ("book raja yoga" → "raja yoga"), (3) hyphen-joda naam
    ("psycho-cybernetics"), (4) "<vyakti> ka <text-shabd>" jod ("ramanujan
    notebooks"), (5) tradition marker se mila user ka apna shabd ("upanishadon").
    Aakhri parat sirf tab judti hai jab wo kisi lambe candidate ke andar na ho —
    "raja yoga" mil gaya to akela "yoga" search karne ka koi fayda nahi.

    Ye naam DAAVA nahi hai — sirf search string hai.
    """
    words = _words(question)
    people = L.thinker_candidates(question)
    text_words = [w for w in words if w in _TEXT_WORDS]

    out: List[str] = []
    out += L.quoted_phrases(question)
    # "book raja yoga", "granth vigyan bhairav" — text-shabd ke TURANT BAAD aane
    # wale 1-2 shabd aksar kriti ka naam hote hain. Stop-word par ruk jaate hain,
    # isliye "notebooks me kya tha" se kuch nahi banta.
    for index, word in enumerate(words):
        if word not in _TEXT_WORDS:
            continue
        tail: List[str] = []
        for follow in words[index + 1:index + 3]:
            # cue-shabd naam ka hissa nahi hote: "text padhna hai" me "padhna"
            # kriti ka naam nahi, kaam ka naam hai (probe me pakda gaya).
            if (L.is_stopword(follow) or follow in _TEXT_WORDS
                    or follow in _READ_CUES or follow in _SUMMARY_CUES
                    or follow in _QUESTION_WORDS):
                break
            tail.append(follow)
        if tail:
            out.append(" ".join(tail))
        # Hinglish aksar ulta chalti hai — naam PEHLE, text-shabd BAAD me
        # ("muqaddimah granth", "gita granth me"). Isliye peeche ke 1-2 shabd
        # bhi dekhe jaate hain, wahi rukne ke niyam ke saath. (Probe: "muqaddimah
        # granth me ..." par pehle ek bhi kriti-naam nahi banta tha.)
        lead: List[str] = []
        for back in reversed(words[max(0, index - 2):index]):
            if (L.is_stopword(back) or back in _TEXT_WORDS
                    or back in _READ_CUES or back in _SUMMARY_CUES
                    or back in _QUESTION_WORDS):
                break
            lead.insert(0, back)
        if lead:
            out.append(" ".join(lead))
    out += L.hyphenated_compounds(question)
    for person in people[:2]:
        person_tail = person.split()[-1].casefold()
        for word in _uniq(text_words, limit=2):
            # "ramanujan ke notebooks" → "ramanujan notebooks". Agar text-shabd
            # naam ka hissa hi hai to dobara nahi jodna.
            if word.casefold() == person_tail:
                continue
            out.append(f"{person} {word}")
    kept = _uniq(out, limit=limit)
    for hit in L.tradition_hits(question):
        # Akela marker-shabd sabse aakhir me, aur tab hi jab wo kisi lambe
        # candidate ke andar mojood na ho ("raja yoga" ke baad akela "yoga" nahi).
        low = hit.casefold()
        if any(f" {low} " in f" {name.casefold()} " for name in kept):
            continue
        kept.append(hit)
    return _uniq(kept, limit=limit)


# ── copyright ka faisla: kis source ka full text chhua ja sakta hai ─────────

def _pick(source: object, field: str, given):
    if given not in (None, "", []):
        return given
    if source is None:
        return given
    value = getattr(source, field, None)
    if value is None:
        return given
    return value


def copyright_stance(source: object = None, *, url: str = "",
                     year: Optional[int] = None, publisher: str = "",
                     title: str = "", source_type: str = "",
                     licence: str = "",
                     full_text_available: Optional[bool] = None) -> Dict:
    """Ek source ka licence-stance. Har faisla ek NAAMIT rule se aata hai.

    Wapas: ``verdict``, ``full_text_allowed``, ``read_ceiling`` (isse aage read
    level nahi badh sakta), ``summary_lane`` (iski summary bhi dhoondhni chahiye
    kya), ``rule`` aur Hinglish ``reason``.

    Default JAAN-BOOJHKAR "kuch mat badlo" hai: jo source book-jaisa nahi hai
    (paper, dataset, webpage) uspar ye module koi nayi rok nahi lagata — warna
    pehle se chal rahi poori pipeline ka behaviour badal jaata, jo is kaam ka
    maqsad nahi hai.
    """
    url = str(_pick(source, "url", url) or "")
    year = _pick(source, "year", year)
    publisher = str(_pick(source, "publisher", publisher) or "")
    title = str(_pick(source, "title", title) or "")
    raw_type = _pick(source, "source_type", source_type)
    kind = str(getattr(raw_type, "value", raw_type) or "").casefold()
    # Licence ka DAAVA source ke apne metadata se aata hai (koi title/topic ki
    # list nahi): publisher line, snippet, ya explicit `licence=`.
    declared = " ".join(str(part or "") for part in (
        licence, publisher, _pick(source, "snippet", ""))).casefold()
    host = _host(url)

    try:
        year = int(year) if year not in (None, "") else None
    except Exception:
        year = None

    def out(verdict: str, allowed: bool, ceiling: str, rule: str,
            reason: str, summary_lane: bool) -> Dict:
        return {"verdict": verdict, "full_text_allowed": allowed,
                "read_ceiling": ceiling, "summary_lane": summary_lane,
                "rule": rule, "reason": reason, "host": host, "year": year,
                "title": title}

    if host and any(tag in host for tag in _UNAUTHORISED_TAGS):
        return out(COPYRIGHT_LIKELY, False, "metadata", "unauthorised_host",
                   "bina ijazat copy baantne wala host — na search, na fetch "
                   "(spec: koi bypass nahi)", True)
    if host and _host_matches(host, _COMMERCIAL_TEXT_HOSTS):
        return out(COPYRIGHT_LIKELY, False, "snippet", "commercial_host",
                   "bookstore/subscription host — mool text nahi liya; iski "
                   "summary/vyakhya wali lane chalegi", True)
    if host and _host_matches(host, _PUBLIC_DOMAIN_HOSTS):
        return out(PUBLIC_DOMAIN, True, "full_text", "public_domain_library",
                   "public-domain library ka apna plain-text — poora padha ja "
                   "sakta hai", False)
    if host and _host_matches(host, _OPEN_LICENSED_HOSTS):
        return out(OPEN_LICENSED, True, "full_text", "open_licensed_host",
                   "khuli licence wala Wikimedia project — apna official API "
                   "se poora text milta hai", False)
    if year is not None and year <= PD_YEAR_MAX:
        return out(PUBLIC_DOMAIN, True, "full_text", "old_publication",
                   f"prakashan saal {year} ({PD_YEAR_MAX} se pehle) — public "
                   "domain maana ja sakta hai", False)
    # Naya (ya bina-saal) book bhi khuli licence ka ho sakta hai — OER textbook,
    # CC-BY monograph, lekhak ka khud free kiya hua granth. Wo daava source ke
    # apne metadata me likha hota hai. Ye check unauthorised/commercial host ke
    # BAAD aata hai, isliye pirate site "public domain" likh kar chhoot nahi le
    # sakti.
    marker = _licence_marker(declared)
    if marker:
        return out(OPEN_LICENSED, True, "full_text", "declared_open_licence",
                   f"source ke apne metadata me khuli licence likhi hai "
                   f"(\"{marker}\") — isliye mool text padhna jaayaz hai", False)
    if host and _host_matches(host, _HOST_GATED_ARCHIVES):
        # Archive khud tay karta hai kaun item publicly downloadable hai;
        # restricted par wahi 403 deta hai. Isliye rok hum nahi lagate, par
        # naya item hone par summary lane BHI saath chalti hai.
        newer = year is not None and year > PD_YEAR_MAX
        return out(UNKNOWN, True, "full_text", "host_gated_archive",
                   "archive apna access control khud lagata hai (restricted "
                   "item par download khud fail hota hai) — jo public hai wahi "
                   "padha jaata hai", newer)
    # book_like ka faisla SIRF source_type par: pehle isme `or bool(publisher)`
    # bhi tha, aur wo ek chupa hua regression tha — bahut se open-access PAPER
    # records par publisher bhara hota hai, to unka legal full text bhi band ho
    # jaata. Ye module kisi paper/dataset/user-PDF par nayi rok nahi lagata.
    book_like = kind == "book"
    if book_like and year is not None and year > PD_YEAR_MAX:
        return out(COPYRIGHT_LIKELY, False, "abstract", "modern_book",
                   f"{year} ki book — copyright maana; mool text nahi liya, "
                   "summary/vyakhya wali lane chalegi", True)
    if book_like:
        return out(UNKNOWN, False, "abstract", "book_unknown_year",
                   "book jaisa source par saal pata nahi"
                   + (f" (publisher: {publisher[:60]})" if publisher else "")
                   + " — kam-daave wala faisla: mool text nahi, summary lane "
                     "chalegi", True)
    return out(UNKNOWN, True, "full_text", "not_book_like",
               "book jaisa source nahi — iske liye purane hi route/rule lagte "
               "hain, ye module koi nayi rok nahi lagata", False)


def full_text_allowed(source: object = None, **kwargs) -> bool:
    """Chhota wrapper: is source ka full text fetch kar sakte hain ya nahi."""
    return bool(copyright_stance(source, **kwargs).get("full_text_allowed"))


def cap_read_level(level: str, stance: Dict) -> str:
    """Read level ko ``read_ceiling`` se aage jaane hi na do.

    Yahi wo ek line hai jo "copyright book ka full text padh liya" jaisa jhooth
    structurally namumkin banati hai: label ``access_depth()`` isi level se
    banta hai, isliye ceiling lagne ke baad "FULL TEXT ACCESSED" aa hi nahi
    sakta.
    """
    current = str(level or "").strip().casefold()
    ceiling = str((stance or {}).get("read_ceiling") or "").strip().casefold()
    if ceiling not in READ_LEVEL_ORDER:
        return current
    if current not in READ_LEVEL_ORDER:
        return ceiling if current else current
    if READ_LEVEL_ORDER.index(current) <= READ_LEVEL_ORDER.index(ceiling):
        return current
    return ceiling


def read_note(stance: Dict, reached: str = "") -> str:
    """Source par likhi jaane wali imaandaar line (khaali = kuch extra nahi).

    ``reached`` = jo level asal me mila (``cap_read_level()`` ke baad). Agar
    licence ne padhne ki ijazat di thi par ceiling ne level neeche kar diya, to
    chuppi galat hai — line me saaf likha jaata hai kitna hi padha gaya.
    """
    stance = stance or {}
    if stance.get("full_text_allowed"):
        level = str(reached or "").strip().casefold()
        ceiling = str(stance.get("read_ceiling") or "").strip().casefold()
        if level and level != "full_text" and level == ceiling:
            return (f"is source par sirf {level} level tak padha gaya — licence "
                    f"stance ne isse aage jaane nahi diya")
        return ""
    if stance.get("verdict") == COPYRIGHT_LIKELY:
        return SUMMARY_LANE_NOTE
    return ("mool text tak bharosemand free raasta nahi mila — sirf itna hi "
            "padha gaya jitna khule me mojood tha")



# ── dono lane ki search queries ─────────────────────────────────────────────
# Query me host ka naam JAAN-BOOJHKAR aata hai ("wikisource", "gutenberg",
# "archive"), kyunki free full-text isi jagah milta hai. Ye scraping nahi hai —
# search engine/connector ko sirf ishara hai kahan dekhna hai.

def classic_text_queries(question: str = "", works: Optional[Sequence[str]] = None,
                         people: Optional[Sequence[str]] = None,
                         limit: int = 4) -> List[str]:
    """LANE A — public-domain mool text dhoondhne wali queries."""
    names = list(works if works is not None else work_candidates(question))
    folks = list(people if people is not None else L.thinker_candidates(question))
    out: List[str] = []
    for name in names[:2]:
        out.append(f"{name} full text public domain")
        out.append(f"{name} english translation full text")
    for person in folks[:2]:
        out.append(f"{person} collected works full text public domain")
    if not out and _clean(question):
        out.append(f"{_clean(question)} public domain full text")
    return _uniq(out, limit=limit)


def summary_lane_queries(question: str = "", works: Optional[Sequence[str]] = None,
                         people: Optional[Sequence[str]] = None,
                         limit: int = 4) -> List[str]:
    """LANE B — copyright book ko IGNORE nahi karna: uski summary/vyakhya.

    intel ki line: "jo book copyright ho uski summary dekh lo ya ... explane de
    rkha ho usko dekh lo, ignore chhodo mt". Ye queries book ke BAARE me hain,
    book khud nahi — isliye inse aane wale source par ``SUMMARY_LANE_NOTE``
    lagta hai.
    """
    names = list(works if works is not None else work_candidates(question))
    folks = list(people if people is not None else L.thinker_candidates(question))
    out: List[str] = []
    for name in names[:2]:
        out.append(f"{name} summary key ideas chapter")
        out.append(f"{name} explained critical review analysis")
    for person in folks[:2]:
        out.append(f"{person} own essays lectures free to read")
    if not out and L._clean(question):
        out.append(f"{L._clean(question)} summary explained")
    return _uniq(out, limit=limit)


def lane_plan(question: str, limit: int = 4) -> Dict:
    """Dono lane ka poora plan — ek bhi model call ya network hit ke bina.

    ``verified`` hamesha False: yahan tak app ne kuch padha nahi hai, sirf tay
    kiya hai ki KAHAN dekhna hai. Granth ka naam le lena use padh lena nahi hai.
    """
    intent = text_intent(question)
    works = work_candidates(question)
    people = intent.get("people") or []
    wants = bool(intent.get("wants_primary_text"))
    classic = classic_text_queries(question, works=works, people=people,
                                  limit=limit) if wants else []
    # Summary lane tab bhi chalti hai jab mool text mil sakta hai: vyakhya se
    # nuksaan kuch nahi, aur copyright book par yahi ek hi imaandaar raasta hai.
    summary = summary_lane_queries(question, works=works, people=people,
                                   limit=limit) if wants else []
    return {
        "wants_primary_text": wants,
        "works": works,
        "people": list(people),
        "traditions": intent.get("traditions") or [],
        "reasons": intent.get("reasons") or [],
        "classic_queries": classic,
        "summary_queries": summary,
        "method": "deterministic_classics",
        "model_used": False,
        "verified": False,
        "evidence_status": EVIDENCE_STATUS,
    }

