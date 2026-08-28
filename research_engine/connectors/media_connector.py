"""MediaArchiveConnector — video/audio DHOONDHNE ka lane (#133b).

intel ki maang: "logo ki recording ya bade singer ki book notes gaane dekhe" —
yaani craft sirf kitaab/paper se nahi, bade logon ki BAAT se bhi padhi jaaye
(lecture, interview, masterclass ki recording).

#133a ne user ke APNE diye hue media ka likhit transcript padhna shuru kiya
(`research_engine/media_study.py`). Par us lane me media aata hi nahi tha jab
tak user khud upload na kare. Ye connector wahi khaali jagah bharta hai: bina
kisi API key ke, sirf archive.org ke APNE official `advancedsearch` endpoint se
(wahi host jo `book_connector` pehle se use karta hai, aur jo `base.py` ki
`DISCOVERY_ALLOWED_HOSTS` me pehle se hai — koi naya host, koi scraping,
koi unofficial mirror nahi). Kharch: ₹0.

CHAAR JHOOTH jo ye file JAAN-BOOJH KAR nahi bolti:

  1. **"Media mil gaya" ≠ "media padha gaya".** Search se sirf uploader ki
     LIKHI HUI description milti hai. Video dekha nahi jaata, aawaz suni nahi
     jaati, transcript aata hi nahi. Isliye har record par
     `read_level="snippet"` (yaani §9 ka `SNIPPET ONLY`), `read_note` me saaf
     shabdon me wahi baat, aur `full_text_available=False` — hamesha. Ye lane
     kabhi `full_text` nahi likh sakta, kyunki uske paas full text hota hi
     nahi.

  2. **`SourceType.TRANSCRIPT` ka matlab "transcript haath me hai" nahi hai.**
     Ye sirf ye kehta hai ki source video/audio family ka hai. Farq `read_level`
     rakhta hai: #133a wale user-transcript par wo `full_text` hota hai, is
     lane par `snippet`. `media_study.media_sources()` inhe media-transcript
     nahi ginti (unka koi media extension aur koi samay-locator nahi hota) —
     aur ye theek hai: parichay padhna transcript padhna nahi hai.

  3. **Server ke filter par bharosa nahi.** `q` me `mediatype:(movies OR audio)`
     jaata hai, par jawab me aaya har item DOBARA yahan check hota hai. Filter
     ek din badal jaaye to hum chup-chaap "ye video hai" nahi likhenge.

  4. **Ye gaane ka download lane NAHI hai.** `songcraft.is_lyrics_hunt()` wali
     query network par jaati hi nahi (yahan bhi, aur `source_discovery` me bhi
     — do deewar jaan-boojh kar), file list kabhi nahi maangi jaati, aur URL
     hamesha item ka `details` page hota hai, koi media file nahi.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .. import songcraft
from ..models import SourceRecord, SourceType
from .base import SLOW_TIMEOUT, BaseConnector, http_get

SEARCH_URL = "https://archive.org/advancedsearch.php"

# archive.org ke apne mediatype naam. "movies" me lecture/interview/talk sab
# aate hain; "audio" me recording/podcast. `texts` yahan JAAN-BOOJH KAR nahi
# hai — kitaab ka lane pehle se `book_connector` ke paas hai, aur do lane ek
# hi cheez laayein to report me ginti do baar ho jaati hai.
MEDIA_TYPES: Tuple[str, ...] = ("movies", "audio")
MEDIATYPE_FILTER = "mediatype:(movies OR audio)"

# Itne se kam likha hua parichay = padhne layak kuch nahi. Aisa record rakhna
# ek khaali daawa hai ("ye source padha") — isliye wo gina jaata hai par bheja
# nahi jaata, aur note me uski ginti saaf likhi hoti hai.
MIN_DESCRIPTION_CHARS = 40

# Sirf yahi read level — is lane ke paas isse zyada kabhi nahi hota.
READ_LEVEL = "snippet"

NOT_READ_NOTE = (
    "Media KHUD nahi padha gaya — sirf archive.org par likha hua parichay "
    "(description) padha gaya. Video dekha nahi gaya, aawaz suni nahi gayi, "
    "transcript mila hi nahi.")

MEDIA_LABELS: Dict[str, str] = {
    "movies": "video/lecture recording — dekha nahi gaya",
    "audio": "aawaz ki recording — suni nahi gayi",
}

LYRICS_BLOCK_NOTE = (
    "ye query kisi maujooda gaane ke bol/file dhoondh rahi thi, isliye ye "
    "lane chali hi nahi — craft padhna aur gaana utha lena do alag baat hai")


def media_label(mediatype: str) -> str:
    """Imaandaar label; anjaan mediatype par khaali (jhootha label nahi)."""
    return MEDIA_LABELS.get(str(mediatype or "").strip().lower(), "")


def build_query(query: str) -> str:
    """Free text + mediatype pabandi. Khaali query par khaali string."""
    clean = " ".join(str(query or "").split())
    if not clean:
        return ""
    return f"{clean} AND {MEDIATYPE_FILTER}"


class MediaArchiveConnector(BaseConnector):
    """archive.org (keyless) — sirf video/audio items ka parichay laata hai."""

    name = "archive_media"
    source_type = SourceType.TRANSCRIPT
    # archive.org ka search pehla byte bhejne me hi 10-30s le sakta hai
    # (book_connector ka naapa hua sabak) — isliye slow window.
    timeout: Tuple[int, int] = SLOW_TIMEOUT

    def search(self, query: str, max_results: int = 3) -> List[SourceRecord]:
        clean = " ".join(str(query or "").split())
        if not clean:
            self.last_reason = "empty_query"
            self.last_note = "query khaali thi — koi call nahi bheji gayi"
            return []
        # Pehli deewar (doosri `source_discovery` me hai): bol/karaoke/mp3
        # dhoondhne wali query network par jaati hi nahi.
        if songcraft.is_lyrics_hunt(clean):
            self.last_reason = "lyrics_hunt_blocked"
            self.last_note = LYRICS_BLOCK_NOTE
            return []

        rows = max(1, min(int(max_results or 1), 20))
        resp = http_get(
            SEARCH_URL,
            params={
                "q": build_query(clean),
                # Sirf metadata field maange jaate hain. File list JAAN-BOOJH KAR
                # nahi maangi jaati — is lane ko kisi media file ki zaroorat hi
                # nahi hai.
                "fl[]": ["identifier", "title", "description", "creator",
                         "year", "date", "publisher", "mediatype", "subject"],
                "rows": rows,
                "page": 1,
                "output": "json",
            },
            timeout=self.timeout,
        )
        docs = (resp.json().get("response") or {}).get("docs", []) or []

        out: List[SourceRecord] = []
        dropped_kind = 0     # server ne bheja par media nahi tha
        dropped_thin = 0     # media tha par padhne layak parichay nahi tha
        for item in docs:
            mediatype = str(item.get("mediatype") or "").strip().lower()
            if mediatype not in MEDIA_TYPES:
                dropped_kind += 1
                continue
            description = item.get("description")
            if isinstance(description, list):
                description = " ".join(str(part) for part in description)
            description = self._clean(description, 1200)
            if len(description) < MIN_DESCRIPTION_CHARS:
                # Parichay hi nahi to yahan padhne layak kuch nahi hai. Aisa
                # record bhejna "ye source padha" ka khaali daawa hota.
                dropped_thin += 1
                continue
            identifier = str(item.get("identifier") or "").strip()
            if not identifier:
                dropped_thin += 1
                continue
            creator = item.get("creator")
            authors = creator if isinstance(creator, list) else (
                [creator] if creator else [])
            subject = item.get("subject")
            if isinstance(subject, list):
                subject = ", ".join(str(s) for s in subject[:5])
            out.append(SourceRecord(
                title=self._clean(item.get("title")),
                # Hamesha `details` page — kabhi koi media/download URL nahi.
                url=f"https://archive.org/details/{identifier}",
                snippet=self._clean(
                    f"{description} [Media: {media_label(mediatype)}] "
                    f"[Subject: {subject or 'n/a'}] [{NOT_READ_NOTE}]", 1600),
                connector=self.name,
                source_type=SourceType.TRANSCRIPT,
                authors=[a for a in authors if a][:8],
                year=self._year(item.get("year") or item.get("date")),
                publisher=self._clean(item.get("publisher"), 200),
                peer_reviewed=None,       # recording peer-review nahi hoti
                is_primary=None,          # pata nahi — jhooth mat bolo
                # Teeno ek hi baat ke teen roop hain, aur teeno zaroori hain:
                # gate (`full_text_available`), label (`read_level`) aur
                # padhne wale ke liye shabd (`read_note`).
                full_text_available=False,
                read_level=READ_LEVEL,
                read_note=NOT_READ_NOTE,
            ))

        if not out:
            # "kuch nahi mila" aur "humne chhaanta" ek jaisa report karna jhooth
            # hai (base.py ka `last_reason` isi ke liye hai).
            if dropped_kind or dropped_thin:
                self.last_reason = "filtered"
            self.last_note = (
                f"0 media source bheje — {dropped_kind} item media nahi tha, "
                f"{dropped_thin} me padhne layak parichay nahi tha "
                f"(kam se kam {MIN_DESCRIPTION_CHARS} akshar chahiye)")
        else:
            self.last_note = (
                f"{len(out)} media source mile (sirf parichay padha gaya, media "
                f"nahi) — {dropped_kind} non-media aur {dropped_thin} bina "
                f"parichay wale hataye gaye")
        return out


class MediaConnector:
    """Media lane ka facade — aaj ek provider, kal aur ho sakte hain."""

    def __init__(self):
        self.connectors: List[BaseConnector] = [MediaArchiveConnector()]

    def by_name(self, name: str) -> Optional[BaseConnector]:
        return next((c for c in self.connectors if c.name == name), None)

    def search(self, query: str, max_per_source: int = 3,
               only: Optional[List[str]] = None) -> Dict:
        records: List[SourceRecord] = []
        log: List[Dict] = []
        for connector in self.connectors:
            if only and connector.name not in only:
                continue
            result = connector.safe_search(query, max_per_source)
            records.extend(result["records"])
            log.append({k: v for k, v in result.items() if k != "records"})
        return {"records": records, "log": log}
