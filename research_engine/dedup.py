"""
DeduplicationEngine — Spec Section 6 + 7

Spec Section 7 ka rule: "ek hi information ki 100 copied websites ko 100
independent sources mat maano."

Isliye ye engine do kaam karta hai:
    1. Exact duplicates hatao (same URL / same DOI / same title).
    2. Jo bache unhe INDEPENDENCE GROUPS mein baanto (same domain ya same DOI =
       ek hi independent voice), taaki evidence strength inflate na ho.

PATENT FAMILY (₹0 patent batch, point 5):
    Ek hi invention ek hi din US, EP aur WO — teen jagah file hoti hai, aur teeno
    ke title/number/URL alag hote hain. Purane teen rules (URL/DOI/title) inhe
    duplicate NAHI pakadte: URL alag, DOI hi nahi hota, aur title translated ya
    thoda badla hua ho sakta hai. Nateeja seedha jhooth hota: "3 independent
    sources is baat par sehmat hain", jabki wo EK hi application ki teen copies
    thi. Isliye patents ke liye ek chautha rule hai — same FAMILY = ek source.
    Family ke andar se wo member bachta hai jiska text sabse gehra padha gaya
    (full text > claims > abstract > metadata), aur baaki members chupchaap gayab
    nahi hote: unke number survivor ke `patent_meta["family_members"]` mein aur
    uske read note mein likhe jaate hain.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .models import SourceRecord, normalize_doi

_STOP = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with",
    "is", "are", "was", "were", "by", "from", "at", "as", "that", "this",
}


def _title_tokens(title: str) -> frozenset:
    words = re.findall(r"\b\w{3,}\b", (title or "").lower())
    return frozenset(w for w in words if w not in _STOP)


# Gehrai ka kram — sirf yahan se aata hai, kahin dobara likha nahi jaata.
_DEPTH_ORDER = ("metadata", "snippet", "abstract", "claims", "full_text")


def _depth_rank(record) -> int:
    """Is record ka read level kitna gehra hai (0 = sirf metadata)."""
    level = ""
    reader = getattr(record, "reading_level", None)
    if callable(reader):
        try:
            level = str(reader() or "")
        except Exception:          # pragma: no cover - defensive
            level = ""
    level = level or str(getattr(record, "read_level", "") or "") or "metadata"
    try:
        return _DEPTH_ORDER.index(level)
    except ValueError:
        return 0


def _text_chars(record) -> int:
    meta = dict(getattr(record, "patent_meta", None) or {})
    chars = 0
    for key in ("description_chars", "claims_chars", "abstract_chars"):
        try:
            chars += int(meta.get(key) or 0)
        except (TypeError, ValueError):
            continue
    if chars:
        return chars
    return len(str(getattr(record, "snippet", "") or "").strip())


def _member_note(record) -> str:
    """Family ke ek member ka chhota, imaandaar descriptor."""
    meta = dict(getattr(record, "patent_meta", None) or {})
    number = str(meta.get("number") or "").strip() or (
        str(getattr(record, "title", "") or "")[:40])
    depth = _DEPTH_ORDER[_depth_rank(record)]
    return f"{number} [{depth}]"


class DeduplicationEngine:
    def __init__(self, title_similarity: float = 0.85):
        self.title_similarity = title_similarity

    # ── duplicate girate waqt uske safety signals BACHAO ─────────────────────
    # LIVE-STYLE BUG jo test ne pakda: ek hi kaam do connectors se aata hai —
    # Crossref se "RETRACTED: Statin therapy..." (retraction flag ke saath) aur
    # OpenAlex se "Statin therapy..." (flag ke bina). Dedup dono ko ek maanta
    # hai (theek hai — ye ek hi kaam hai), par PEHLE wo jo record baad mein
    # aaya use chup-chaap gira deta tha. Agar giraya hua record wahi tha jisme
    # retraction ka signal tha, to warning gaayab ho jaati thi aur retracted
    # paper saaf-suthra dikh kar evidence ban jaata tha.
    #
    # Isliye ab girane se pehle uske signals survivor par merge hote hain.
    # Rule seedha hai: SAFETY signal kabhi kam nahi hota (retracted=True hamesha
    # jeetega), aur khaali jagah bhar di jaati hai — bhari hui jagah chhedte nahi.
    _FILL_IF_EMPTY = ("methodology", "replication")
    _FILL_IF_NONE = ("coi_disclosed", "funding_disclosed")

    @classmethod
    def merge_signals(cls, survivor: SourceRecord, dropped: SourceRecord) -> SourceRecord:
        if getattr(dropped, "retracted", None) is True:
            survivor.retracted = True
        for name in cls._FILL_IF_EMPTY:
            if not getattr(survivor, name, "") and getattr(dropped, name, ""):
                setattr(survivor, name, getattr(dropped, name))
        for name in cls._FILL_IF_NONE:
            if getattr(survivor, name, None) is None and getattr(dropped, name, None) is not None:
                setattr(survivor, name, getattr(dropped, name))
        return survivor

    @classmethod
    def merge_exact_duplicate(cls, survivor: SourceRecord,
                              dropped: SourceRecord) -> SourceRecord:
        """Merge confirmed URL/DOI identity without losing deepest access.

        Title similarity is deliberately excluded: only an exact identity is
        strong enough to move text/read-depth fields between records.
        """
        cls.merge_signals(survivor, dropped)
        for name in (
            "authors", "year", "publisher", "venue", "doi", "locator",
            "connector", "doc_kind", "doc_kind_label", "doc_kind_confidence",
        ):
            current = getattr(survivor, name, None)
            incoming = getattr(dropped, name, None)
            if current in (None, "", []) and incoming not in (None, "", []):
                setattr(survivor, name, incoming)

        prefer_dropped = (
            _depth_rank(dropped) > _depth_rank(survivor)
            or (_depth_rank(dropped) == _depth_rank(survivor)
                and _text_chars(dropped) > _text_chars(survivor))
        )
        if prefer_dropped:
            for name in (
                "snippet", "read_level", "full_text_chars", "full_text_available",
                "pages_read", "pages_total", "locator",
            ):
                setattr(survivor, name, getattr(dropped, name, None))
            if getattr(dropped, "read_note", ""):
                survivor.read_note = str(dropped.read_note)

        connectors = [
            str(value or "").strip()
            for value in (getattr(survivor, "connector", ""),
                          getattr(dropped, "connector", ""))
            if str(value or "").strip()
        ]
        note = (
            "same DOI/URL ke duplicate records merge hue; sabse gehra available "
            "text access rakha gaya"
        )
        if connectors:
            note += f" ({', '.join(dict.fromkeys(connectors))})"
        existing = str(getattr(survivor, "read_note", "") or "").strip()
        if note not in existing:
            survivor.read_note = f"{existing}; {note}" if existing else note
        return survivor

    # ── patent family collapse (₹0 patent batch, point 5 + 6) ────────────────
    # Ek invention US, EP aur WO — teen jagah publish hoti hai. Unke URL alag,
    # DOI kisi ka nahi, aur title translated/badla hua ho sakta hai — isliye
    # upar wale teen rule inhe pakad hi nahi paate. Family key (patents.family_key)
    # se wo teeno EK evidence ban jaate hain.
    #
    # Kaun bachta hai: jiska text sabse gehra padha gaya (full_text > claims >
    # abstract > metadata). Barabari par jiska metadata zyada poora hai, phir
    # jiska text zyada bada hai, phir jo pehle aaya (deterministic).
    #
    # Girne wale chupchaap gayab NAHI hote — point 6 ka "'patent padha' tabhi
    # bolo jab claims/description process hue" tabhi sach reh sakta hai jab har
    # member ka apna read depth likha ho. Isliye survivor ke
    # patent_meta["family_members"] mein har dropped member ka number + uska
    # apna read depth jaata hai, aur read_note mein ek human line.
    @staticmethod
    def _family_rank(pair) -> tuple:
        index, record = pair
        meta = dict(getattr(record, "patent_meta", None) or {})
        missing = len(list(meta.get("missing_fields") or []))
        return (-_depth_rank(record), missing, -_text_chars(record), index)

    def collapse_patent_families(self, sources: List[SourceRecord]) -> List[SourceRecord]:
        """Ek family = ek record. Non-patent aur bina-family patents waise hi rehte."""
        families: Dict[str, List[tuple]] = {}
        for index, s in enumerate(sources):
            if not getattr(s, "is_patent", False):
                continue
            key = getattr(s, "patent_family_key", "") or ""
            if not key:
                # Bilkul unknown patent: family ka pata hi nahi, to do alag
                # inventions ko ek maan lena galat hoga.
                continue
            families.setdefault(key, []).append((index, s))

        collapsible = {k: v for k, v in families.items() if len(v) > 1}
        if not collapsible:
            return list(sources)

        winners: Dict[int, SourceRecord] = {}
        dropped_indexes = set()
        for members in collapsible.values():
            ordered = sorted(members, key=self._family_rank)
            keep_index, survivor = ordered[0]
            notes: List[str] = []
            recorded: List[Dict] = list(
                (getattr(survivor, "patent_meta", None) or {}).get("family_members") or [])
            for index, other in ordered[1:]:
                dropped_indexes.add(index)
                self.merge_signals(survivor, other)
                meta = dict(getattr(other, "patent_meta", None) or {})
                recorded.append({
                    "number": str(meta.get("number") or ""),
                    "jurisdiction": str(meta.get("jurisdiction") or ""),
                    "read_depth": _DEPTH_ORDER[_depth_rank(other)],
                    "url": str(getattr(other, "url", "") or ""),
                })
                notes.append(_member_note(other))
            if isinstance(getattr(survivor, "patent_meta", None), dict):
                survivor.patent_meta["family_members"] = recorded
            if notes:
                line = (f"isi invention ki {len(notes)} aur publication mili "
                        f"({', '.join(notes)}) — same family, isliye alag "
                        f"independent source nahi gina gaya")
                existing = str(getattr(survivor, "read_note", "") or "").strip()
                survivor.read_note = f"{existing}; {line}" if existing else line
            winners[keep_index] = survivor

        out: List[SourceRecord] = []
        for index, s in enumerate(sources):
            if index in dropped_indexes:
                continue
            out.append(winners.get(index, s))
        return out

    def patent_family_report(self, sources: List[SourceRecord]) -> Dict:
        """Kitne patent, kitni families, kitne bina-family — audit ke liye."""
        patents = [s for s in sources if getattr(s, "is_patent", False)]
        keys = [getattr(s, "patent_family_key", "") or "" for s in patents]
        known = [k for k in keys if k]
        return {
            "patent_sources": len(patents),
            "families": len(set(known)),
            "unknown_family": len(keys) - len(known),
            "collapsed": len(known) - len(set(known)),
        }

    # ── exact + near duplicate removal ───────────────────────────────────────
    def deduplicate(self, sources: List[SourceRecord]) -> List[SourceRecord]:
        by_url: Dict[str, SourceRecord] = {}
        by_doi: Dict[str, SourceRecord] = {}
        kept_titles: List[tuple] = []          # [(tokens, record), ...]
        unique: List[SourceRecord] = []

        # Patent family pehle: URL/DOI/title in members ko nahi pakad sakte.
        sources = self.collapse_patent_families(list(sources or []))

        for s in sources:
            url_key = (s.url or "").strip().rstrip("/").lower()
            doi_key = normalize_doi(s.doi)

            if url_key and url_key in by_url:
                self.merge_exact_duplicate(by_url[url_key], s)
                continue
            if doi_key and doi_key in by_doi:
                self.merge_exact_duplicate(by_doi[doi_key], s)
                continue

            # TITLE RULE PATENTS PAR NAHI CHALTA — jaan-boojh kar.
            # Do wajah, dono live traps se:
            #   * Ek hi topic par ek PAPER aur ek PATENT ka title bahut milta-julta
            #     hota hai. Title par gira dene se dono mein se ek gayab ho jaata
            #     aur patent-vs-paper ka disagreement hi chhup jaata — jabki wahi
            #     sabse zaroori signal hai.
            #   * Ek hi assignee ke do ALAG inventions ke title bhi 85% match ho
            #     jaate hain ("...for lithium-ion battery" wale). Patents ka asli
            #     rishta family key batati hai, title nahi — aur wo kaam upar
            #     collapse_patent_families() pehle hi kar chuka hai.
            is_patent = bool(getattr(s, "is_patent", False))
            tokens = _title_tokens(s.title)
            if tokens and len(tokens) >= 3 and not is_patent:
                twin = self._near_duplicate_of(tokens, kept_titles)
                if twin is not None:
                    twin_doi = normalize_doi(getattr(twin, "doi", ""))
                    if doi_key and twin_doi and doi_key != twin_doi:
                        twin = None
                if twin is not None:
                    self.merge_signals(twin, s)
                    continue

            if url_key:
                by_url[url_key] = s
            if doi_key:
                by_doi[doi_key] = s
            if tokens and not is_patent:
                kept_titles.append((tokens, s))
            unique.append(s)

        return unique

    def _near_duplicate_of(self, tokens: frozenset, kept: List[tuple]):
        """Jis record se milta hai wo LAUTAO (sirf True/False nahi) — taaki
        girane se pehle uske signals us record par merge ho sakein."""
        for other, record in kept:
            if not other:
                continue
            overlap = len(tokens & other) / min(len(tokens), len(other))
            if overlap >= self.title_similarity:
                return record
        return None

    def _is_near_duplicate(self, tokens: frozenset, kept: List[frozenset]) -> bool:
        """Purana boolean API — bahar se koi use kare to toote nahi."""
        for other in kept:
            if not other:
                continue
            if len(tokens & other) / min(len(tokens), len(other)) >= self.title_similarity:
                return True
        return False

    # ── independence analysis (Spec Section 7) ───────────────────────────────
    def independence_groups(self, sources: List[SourceRecord]) -> Dict[str, List[SourceRecord]]:
        groups: Dict[str, List[SourceRecord]] = {}
        for s in sources:
            groups.setdefault(s.independence_key, []).append(s)
        return groups

    def independence_report(self, sources: List[SourceRecord]) -> Dict:
        groups = self.independence_groups(sources)
        repeated = {k: len(v) for k, v in groups.items() if len(v) > 1}
        return {
            "total_sources": len(sources),
            "independent_voices": len(groups),
            "repeated_origins": repeated,
            "note": (
                "independent_voices < total_sources ka matlab: kuch sources ek hi "
                "origin (same domain ya same DOI) se hain, isliye unhe evidence "
                "strength mein alag-alag count nahi karna chahiye."
            ),
        }

    def cap_per_origin(self, sources: List[SourceRecord], max_per_origin: int = 3) -> List[SourceRecord]:
        """Ek hi domain/DOI ko poori source list hijack karne se roko."""
        counts: Dict[str, int] = {}
        out: List[SourceRecord] = []
        for s in sources:
            key = s.independence_key
            if counts.get(key, 0) >= max_per_origin:
                continue
            counts[key] = counts.get(key, 0) + 1
            out.append(s)
        return out
