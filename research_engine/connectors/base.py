"""
Connector base class — Spec Section 2 + 16

Har source connector (paper / book / web / dataset) isi interface ko follow karta hai,
taaki future mein naya provider add karna sirf ek naya class likhna ho.

Design rules:
    - requests LAZY import hota hai (module import sasta rahe).
    - koi connector exception raise nahi karta — `safe_search()` sab pakad kar
      khaali list deta hai, aur "kya hua" `error` + `reason` + `note` mein
      likhta hai. Pipeline SIRF safe_search() call karta hai.
    - har connector SourceRecord return karta hai, raw dict nahi — isse metadata
      (author/year/publisher/doi/peer-review) pipeline mein zinda rehta hai.

LIVE TEST SE MILE DO SABAK (2026-08-17), dono yahan fix hue:

  1. Timeout ek hi number tha (8s). archive.org ne ReadTimeout diya aur
     openlibrary.org ne ConnectTimeout — dono free aur kaam ke sources hain,
     sirf SLOW hain. Ab timeout (connect, read) tuple hai: connect chhota
     (server zinda hai ya nahi, ye jaldi pata chal jaata hai) aur read bada
     (slow server ko saans lene do). Ek retry backoff ke saath bhi hai.

  2. "0 results" aur "rate limit" ek jaise dikh rahe the. Semantic Scholar bina
     key ke 429 deta hai — usse "0 results mile" batana JHOOTH hai, kyunki
     search hui hi nahi thi. Ab HTTP status ko honest exception mein badla jaata
     hai (RateLimited / AccessBlocked / ConnectorHTTPError) aur wahi reason
     final report tak jaata hai.

SELF-REVIEW SE MILE TEEN AUR SABAK (usi din, code review mein pakde gaye):

  3. `last_note` ek plain instance attribute tha. Par SourceDiscovery EK HI
     connector object ko 3 queries ke liye 3 threads mein bhejta hai — to ek
     query ka note dusri query ki report mein chhap raha tha. Ab note/reason
     thread-local hain (neeche `_NOTES`), object par nahi.

  4. "slow source" ka timeout (15, 45) HARD-CODED tha, jabki error message
     kehta tha "CONNECTOR_READ_TIMEOUT badha do". 60 karne par bhi slow
     connectors 45 par hi atke rehte the — yaani advice jhooth thi. Ab
     SLOW_TIMEOUT usi env knob se banta hai.

  5. CONNECTOR_RETRIES=0 likhne par bhi retry hoti thi (floor 1 tha). Ab
     retries ka floor 0 hai — "retry band karo" ka matlab band hi hai.
"""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from typing import Dict, List, Optional, Tuple, Union

from ..models import SourceRecord, SourceType
from ..network_safety import (
    NetworkSafetyError,
    public_error,
    read_bounded_response,
    require_content_type,
    safe_get_with_redirects,
)

USER_AGENT = "InfinityResearchAI/1.0 (educational research project)"
HEADERS = {"User-Agent": USER_AGENT}


def _env_int(name: str, default: int, floor: int = 1) -> int:
    """floor=0 un knobs ke liye jinke liye 0 ek asli, matlab wali value hai."""
    try:
        return max(floor, int(os.getenv(name, "").strip() or default))
    except Exception:
        return default


# connect chhota rakho, read bada — dono ka kaam alag hai
CONNECT_TIMEOUT = _env_int("CONNECTOR_CONNECT_TIMEOUT", 10)
READ_TIMEOUT = _env_int("CONNECTOR_READ_TIMEOUT", 25)
DEFAULT_TIMEOUT: Tuple[int, int] = (CONNECT_TIMEOUT, READ_TIMEOUT)

# Kuch sources free hain par SLOW (archive.org, openlibrary.org). Unhe extra
# sabr chahiye — PAR ye env knob se hi banna chahiye, warna
# CONNECTOR_READ_TIMEOUT=60 karne par slow connector ka read window (45) default
# se CHHOTA ho jaata hai, aur hum user ko galat salah de rahe hote hain.
SLOW_TIMEOUT: Tuple[int, int] = (max(CONNECT_TIMEOUT, 15), max(READ_TIMEOUT, 45))

RETRIES = _env_int("CONNECTOR_RETRIES", 1, floor=0)   # kul attempts = RETRIES + 1
_BACKOFF_SECONDS = 1.5
# Server "Retry-After: 3600" bhej sakta hai — utna rukna pipeline ko maar dega
_MAX_SLEEP_SECONDS = 8.0

# Discovery never fetches a URL supplied by a search result.  Every endpoint is
# selected by connector code and must stay on this exact-host allowlist.  This
# makes the shared helper fail closed if a future connector accidentally passes
# through a user/source-controlled URL.
# Wikipedia langlinks = bhasha ka pul (`research_engine/lang_bridge.py`). Kisi
# shabd ka doosri bhasha wala naam Wikipedia ke apne langlinks me PEHLE SE likha
# hai, isliye hamein koi glossary hath se nahi likhni padti. Allowlist wildcard
# nahi leti, isliye sirf wahi bhashaayein jinki script `lang_bridge` pehchanta
# hai (+ wo Indian bhashaayein jo Devanagari/Bengali script share karti hain).
_BRIDGE_WIKI_LANGS: Tuple[str, ...] = (
    "en", "hi", "bn", "pa", "gu", "or", "ta", "te", "kn", "ml", "si",
    "ar", "he", "el", "ru", "th", "ja", "ko", "zh",
    "mr", "sa", "ne", "as", "fa", "ur", "uk",
)

DISCOVERY_ALLOWED_HOSTS = frozenset({
    "api.crossref.org",
    "api.data.gov.in",
    "api.openalex.org",
    "api.semanticscholar.org",
    "archive.org",
    "catalog.data.gov",
    "data.gov",
    "datacatalogapi.worldbank.org",
    "doaj.org",
    "en.wikipedia.org",
    "eutils.ncbi.nlm.nih.gov",
    "export.arxiv.org",
    "ghoapi.azureedge.net",
    "huggingface.co",
    "openlibrary.org",
    "www.googleapis.com",
    "zenodo.org",
    # Market/economic TIME SERIES providers (#118) — sabhi official public API.
    # Ye `datasets` lane ke catalogue hosts se alag hain: yahan se period→value
    # aata hai, jispar LAB ka walk-forward test chalta hai. Keyless do
    # (world bank, ECB) + key-gated do (FRED, Alpha Vantage) — key na ho to
    # connector chalta hi nahi, isliye host hone se bhi koi call nahi jaati.
    "api.worldbank.org",
    "data-api.ecb.europa.eu",
    "api.stlouisfed.org",
    "www.alphavantage.co",
    # Wikisource — public-domain mool text lane ka official MediaWiki action API.
    # Har bhasha ka apna exact host hai (allowlist wildcard nahi leti), isliye
    # sirf wahi hosts jo `classic_connector._KNOWN_LANGS` me hain.
    "en.wikisource.org",
    "sa.wikisource.org",
    "hi.wikisource.org",
    "mr.wikisource.org",
    "bn.wikisource.org",
    "ta.wikisource.org",
    "te.wikisource.org",
    "kn.wikisource.org",
    "gu.wikisource.org",
    "pa.wikisource.org",
    "or.wikisource.org",
    "ml.wikisource.org",
    "as.wikisource.org",
    "ne.wikisource.org",
    "fa.wikisource.org",
    "ar.wikisource.org",
    "he.wikisource.org",
    "el.wikisource.org",
    "la.wikisource.org",
    "de.wikisource.org",
    "fr.wikisource.org",
    "es.wikisource.org",
    "it.wikisource.org",
    "ru.wikisource.org",
    "zh.wikisource.org",
    "ja.wikisource.org",
}) | frozenset(f"{lang}.wikipedia.org" for lang in _BRIDGE_WIKI_LANGS)


def _max_response_bytes() -> int:
    """Bound decompressed discovery payloads (default 16 MiB, max 64 MiB)."""
    try:
        mb = float(os.getenv("CONNECTOR_MAX_RESPONSE_MB", "16").strip() or 16)
    except Exception:
        mb = 16.0
    return int(min(64.0, max(1.0, mb)) * 1024 * 1024)


# ── honest failure types ─────────────────────────────────────────────────────
class ConnectorError(Exception):
    """Base — iske messages seedhe final report mein jaate hain, isliye saaf likho."""


class RateLimited(ConnectorError):
    """429/503 — search hui hi nahi. Ise 'koi result nahi mila' MAT kehna."""


class AccessBlocked(ConnectorError):
    """403 — server ne mana kiya (aksar country/quota restriction)."""


class ConnectorHTTPError(ConnectorError):
    """
    Baaki 4xx/5xx.

    `status` alag attribute ke roop mein rakha hai kyunki kuch connectors ko
    ek KHAAS code par recover karna padta hai (Crossref 400 par `select` param
    hata kar dobara try karna). Message string parse karke code nikaalna
    (`"400" in str(exc)`) bhagwaan bharose hai — "HTTP 500 ... 400 rows" jaisa
    message bhi match kar jaata. Message ka format jaan-boojh kar nahi badla,
    taaki purane test/log wahi padhein.
    """

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class ConnectorSkipped(ConnectorError):
    """
    Connector chala hi nahi — API key nahi thi / config missing thi.

    Ye 'kuch nahi mila' se BILKUL alag hai, aur pehle ye farak gum ho jaata tha:
    Tavily bina key ke khaali list return karta tha, reason khaali rehta tha, aur
    report mein wo "khaali (search chali, result 0)" bucket mein chala jaata tha —
    yaani hum keh rahe the "Tavily ne dekha aur kuch nahi mila", jabki Tavily
    chala hi nahi tha. Research memory mein bhi wahi jhooth likha ja raha tha.
    """


# ── per-thread connector notes ───────────────────────────────────────────────
class _NoteStore(threading.local):
    """
    Har thread ka apna note/reason.

    Kyun: SourceDiscovery._tasks() EK HI connector object ko har query ke liye
    ek baar submit karta hai (DEEP round 2 mein 3 queries = 3 threads, same
    object). Instance attribute hone par arXiv ki query-1 ka note query-2 ki
    log entry mein chhap raha tha — user ko dikhta ki 3 results relevance guard
    se hate, jabki us call mein kuch hata hi nahi tha.
    """

    note: str = ""
    reason: str = ""


_NOTES = _NoteStore()


def http_get(url: str,
             params: Optional[Dict] = None,
             timeout: Optional[Union[int, Tuple[int, int]]] = None,
             headers: Optional[Dict] = None,
             retries: Optional[int] = None):
    """
    requests ko lazily import karo — isse ye package bina requests ke bhi import hota hai.

    Timeout / retry / HTTP status ki honesty ek hi jagah hai, taaki har connector
    mein wahi logic dobara na likhni pade.
    """
    import requests  # noqa: PLC0415  (lazy on purpose)

    attempts = max(1, (RETRIES if retries is None else retries) + 1)
    request_headers = dict(HEADERS)
    if headers:
        request_headers.update({k: v for k, v in headers.items() if v})

    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp, _final_url = safe_get_with_redirects(
                requests,
                url,
                params=params,
                headers=request_headers,
                timeout=timeout or DEFAULT_TIMEOUT,
                stream=True,
                allowed_hosts=DISCOVERY_ALLOWED_HOSTS,
                # Exact code-owned host allowlisting is the SSRF boundary for
                # discovery.  Full-text URLs use DNS/IP validation separately.
                resolve_dns=False,
            )
        except Exception as exc:
            # Timeout / DNS / connection reset — slow server ko ek mauka aur do
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise

        status = getattr(resp, "status_code", 200)
        if status in (429, 503):
            if attempt + 1 < attempts:
                # Server bata sakta hai kitna rukna hai — usko suno, par cap ke saath
                time.sleep(_retry_sleep(resp, attempt))
                try:
                    resp.close()
                except Exception:
                    pass
                continue
            try:
                resp.close()
            except Exception:
                pass
            raise RateLimited(
                f"HTTP {status} — is API ne rate limit lagayi (search chali hi nahi). "
                f"Ye 'result nahi mila' se alag baat hai."
            )
        if status == 403:
            try:
                resp.close()
            except Exception:
                pass
            raise AccessBlocked(
                f"HTTP 403 — server ne access nahi diya (quota/country restriction ho "
                f"sakti hai)."
            )
        if status >= 400:
            try:
                resp.close()
            except Exception:
                pass
            raise ConnectorHTTPError(f"HTTP {status}", status=status)
        try:
            require_content_type(resp, "discovery")
            read_bounded_response(resp, _max_response_bytes())
        except NetworkSafetyError as exc:
            raise ConnectorHTTPError(public_error(exc)) from None
        return resp

    # yahan pahunchna nahi chahiye, par defensive
    raise ConnectorHTTPError(str(last_error) if last_error else "unknown request failure")


def _retry_sleep(resp, attempt: int) -> float:
    """Retry-After header ka aadar karo, par _MAX_SLEEP_SECONDS se aage na jao."""
    backoff = _BACKOFF_SECONDS * (attempt + 1)
    try:
        raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
        if raw is None:
            return backoff
        wanted = float(str(raw).strip())
    except Exception:
        return backoff
    if wanted <= 0:
        return backoff
    return min(max(wanted, backoff), _MAX_SLEEP_SECONDS)


# ── query helpers ────────────────────────────────────────────────────────────
# Kuch APIs (arXiv) natural-language sentence ko theek se handle nahi karti —
# poori line ko ek dhili "koi bhi word mil jaye" search maan leti hain, jisse
# bilkul unrelated paper aa jaata hai. Isliye query se content words nikaal kar
# AND-join karte hain, aur wahi words local relevance guard mein reuse hote hain.
#
# Is list mein SIRF function words hain. "research", "paper", "review", "study"
# pehle yahan the — galat tha: "peer review bias" jaisi query ka asli topic hi
# ud jaata tha, aur planner jo steering words jodta hai ("systematic review")
# wo bhi. Filler shabd AND karne se thoda kam result aa sakta hai, par galat
# topic aane se kam aana behtar hai — aur ladder khaali hone par relax kar deta hai.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for",
    "from", "has", "have", "how", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "their", "there", "these", "this", "to", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will", "with",
    "about", "between", "vs", "versus", "kya", "hai", "ka", "ke", "ki", "me",
    "mein", "aur", "par", "se", "ko", "kaise", "kyun",
    # Devanagari function words. Ye pehle chhoot gaye the: Hinglish (roman)
    # stopwords list mein the, par Hindi script wale nahi. Jab tokenizer Hindi
    # padhne laga to "क्या"/"में" jaise shabd asli terms ban gaye — AND query
    # bekaar ho jaati aur relevance guard ko muft ka match mil jaata ("में" to
    # har Hindi text mein hai). Yaani guard sirf dikhne mein kaam karta.
    "क्या", "है", "हैं", "था", "थी", "थे", "का", "के", "की", "को", "में", "पर",
    "से", "और", "यह", "वह", "ये", "वे", "इस", "उस", "जो", "तो", "ही", "भी",
    "कि", "नहीं", "ने", "एक", "लिए", "कैसे", "क्यों", "कौन", "कब", "कहाँ",
    "होता", "होती", "होते", "करना", "करने", "किया", "अपने", "बारे",
}

# Unicode-aware: `[^\W_]` = letter ya digit (underscore chhod kar). Pehle regex
# `[A-Za-z0-9...]` tha, to Hindi/Devanagari query par content_terms KHAALI aati
# thi — aur khaali hone par arXiv wahi purani buggy "poori sentence" query bhej
# deta tha AUR relevance guard bhi band ho jaata tha. Yaani Hindi mein poochne
# par dono safety net gayab.
#
# Par sirf `[^\W_]` bhi KAAFI NAHI tha, aur ye galti pakadna mushkil thi:
# Devanagari ki matra/nukta/virama (ु े ा ् ़) Unicode mein "combining mark"
# (category Mn/Mc) hain, aur Python ka `\w` unhe word character NAHI maanta.
# Nateeja: "मधुमेह" tootkar ["मध", "म", "ह"] ban jaata tha, aur 3-letter ke
# minimum filter mein wo teeno gir jaate the — yaani terms phir bhi KHAALI.
# Isliye marks ko word ka hissa maanna zaroori hai. Ranges hand-type karne ke
# bajaye unicodedata se banate hain (0300-0DFF = combining diacritics + saare
# Indic scripts), taaki Bangla/Gurmukhi/Tamil par bhi apne aap sahi rahe.
_MARKS = "".join(
    chr(cp) for cp in range(0x0300, 0x0E00)
    if unicodedata.category(chr(cp)) in ("Mn", "Mc")
)
_WORD_CHAR = r"[^\W_]"
_TERM_CHAR = f"(?:{_WORD_CHAR}|[{re.escape(_MARKS)}])"
_TERM_RE = f"{_WORD_CHAR}{_TERM_CHAR}*(?:[-']{_WORD_CHAR}{_TERM_CHAR}*)*"

# Itne se zyada tokens = ye search query nahi, poora prompt hai. Aise text par
# "pehle N terms" lena galat jawab deta hai (dekho content_terms ka comment).
_LONG_QUERY_TOKENS = 25


def content_terms(query: str, limit: Optional[int] = 6) -> List[str]:
    """
    Query se matlab wale shabd — stopwords aur 2-letter tokens hata kar.

    limit=None = sab terms do (select_terms() ko poori list chahiye hoti hai,
    kyunki usse aakhir wale steering words chunne hote hain).

    LAMBI QUERY KA SPECIAL RAASTA (live failure, 2026-08-19):
    Ye function query ke PEHLE N terms leta hai — document order mein. Chhoti
    query par ye theek hai. Par jab poora 2000-character instruction prompt
    connector tak pahunch gaya, to pehle 6 terms filler nikle:
        मान, मानव, सभ्यता, अगले, वर्षों, ऐसी
    yaani arXiv/OpenAlex ki AND-query "human civilization next years" par chali
    aur relevance guard bhi inhi shabdon par match dhoondhta raha — energy ka
    zikr hi nahi. Planner ab chhoti topic-query bhejta hai, par ye DUSRI safety
    net hai: agar kabhi koi lamba text seedha connector tak pahunch jaye, to
    pehle-N ke bajaye scoring wale topic terms use hote hain.
    """
    tokens = re.findall(_TERM_RE, str(query or ""), flags=re.UNICODE)
    if len(tokens) > _LONG_QUERY_TOKENS:
        from ..query_builder import topic_terms  # lazy: circular import se bachne ke liye
        scored = topic_terms(query, limit=limit or 8)
        if scored:
            return scored

    seen: List[str] = []
    for raw in tokens:
        token = raw.strip("-'").lower()
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.append(token)
        if limit is not None and len(seen) >= limit:
            break
    return seen


def select_terms(query: str, max_terms: int = 5) -> List[str]:
    """
    AND-join ke liye terms chuno: shuru ke terms + SABSE AAKHIR wala term.

    Sirf `content_terms(limit=5)` lena ek chhupa bug tha. planner round 2/3 mein
    steering words query ke AAKHIR mein jodta hai:
        round 1: "algorithmic bias in healthcare risk prediction"
        round 2: "... systematic review"
        round 3: "... contradictory findings"
    Pehle 5 terms lene par teeno rounds ka arXiv query BILKUL EK JAISA banta tha —
    yaani round 2 aur 3 ki extra API calls bilkul bekaar ja rahi thi (aur naye
    sources dhoondne ka poora maqsad hi khatam). Aakhir wala term rakh kar rounds
    ab sach mein alag search karte hain.
    """
    terms = content_terms(query, limit=None)
    if max_terms <= 0:
        return []
    if len(terms) <= max_terms:
        return terms
    if max_terms == 1:
        return terms[:1]
    return terms[:max_terms - 1] + [terms[-1]]


def term_overlap(terms: List[str], text: str) -> int:
    """Kitne query terms is text mein hain (prefix match, halka stemming)."""
    low = (text or "").lower()
    hits = 0
    for term in terms:
        stem = term[:-1] if len(term) > 4 and term.endswith("s") else term
        if stem in low:
            hits += 1
    return hits


class BaseConnector:
    name: str = "base"
    source_type: SourceType = SourceType.WEB
    # Kya ye connector bina API key ke free hai?
    free: bool = True
    # Free hone par bhi rate limit hai?
    rate_limited: bool = False
    # Is connector ka default timeout (slow sources ise SLOW_TIMEOUT se badalte hain)
    timeout: Tuple[int, int] = DEFAULT_TIMEOUT

    # ── honest per-call commentary (thread-local, object par NAHI) ────────────
    # `self.last_note = "..."` likhna aaram se kaam karta hai, par value object
    # mein nahi, current thread mein jaati hai — parallel queries ek dusre ka
    # note overwrite na karein.
    @property
    def last_note(self) -> str:
        return getattr(_NOTES, "note", "") or ""

    @last_note.setter
    def last_note(self, value: str) -> None:
        _NOTES.note = value or ""

    @property
    def last_reason(self) -> str:
        """
        Connector khud reason set kar sakta hai bina exception ke.
        Example: search chali, results aaye, par relevance guard ne sab hata diye —
        wo "khaali" nahi hai, wo "humne chhaanta" hai. Dono ek jaise report karna
        jhooth hoga.
        """
        return getattr(_NOTES, "reason", "") or ""

    @last_reason.setter
    def last_reason(self, value: str) -> None:
        _NOTES.reason = value or ""

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        raise NotImplementedError

    # ── safe wrapper — pipeline isi ko call karta hai ────────────────────────
    def safe_search(self, query: str, max_results: int = 3) -> Dict:
        started = time.time()
        skipped_reason = ""
        # har call apna note/reason khud likhti hai (thread-local reset)
        self.last_note = ""
        self.last_reason = ""
        try:
            records = self.search(query, max_results) or []
            error = ""
            # connector ne khud koi reason bataya ho to wahi rakho ("filtered")
            skipped_reason = self.last_reason
        except ConnectorSkipped as exc:  # key/config nahi thi — search hui hi nahi
            records, error = [], f"skipped: {exc}"
            skipped_reason = "no_key"
        except RateLimited as exc:      # sabse zaroori farak
            records, error = [], f"rate limited: {exc}"
            skipped_reason = "rate_limited"
        except AccessBlocked as exc:
            records, error = [], f"access blocked: {exc}"
            skipped_reason = "blocked"
        except ConnectorHTTPError as exc:
            # HTTP status/type/size messages are generated locally.  Never add
            # a raw response body or requests exception string here.
            records, error = [], f"connector HTTP error: {exc}"
            skipped_reason = "error"
        except Exception as exc:  # connector kabhi pipeline ko na girae
            records, error = [], public_error(exc)
            skipped_reason = "error"
            if "timeout" in type(exc).__name__.lower():
                error += (" — ye source free hai par slow; CONNECTOR_READ_TIMEOUT "
                          "badha kar dobara try kar sakte ho")
                skipped_reason = "timeout"
        return {
            "connector": self.name,
            "records": records,
            "count": len(records),
            "error": error,
            # "0 results" aur "search hi nahi hui" ko alag rakhna zaroori hai
            "reason": skipped_reason,
            # connector ka apna honest comment (e.g. "2 result relevance guard se hate")
            "note": self.last_note,
            "seconds": round(time.time() - started, 2),
        }

    # ── helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _year(value) -> Optional[int]:
        """'2019-04-01' / 2019 / '2019' — sab se saal nikaalo."""
        if value is None:
            return None
        try:
            text = str(value)
            for i in range(len(text) - 3):
                chunk = text[i:i + 4]
                if chunk.isdigit() and 1400 <= int(chunk) <= 2100:
                    return int(chunk)
        except Exception:
            pass
        return None

    @staticmethod
    def _clean(text: Optional[str], limit: int = 1500) -> str:
        if not text:
            return ""
        return " ".join(str(text).split())[:limit]
