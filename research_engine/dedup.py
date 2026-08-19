"""
DeduplicationEngine — Spec Section 6 + 7

Spec Section 7 ka rule: "ek hi information ki 100 copied websites ko 100
independent sources mat maano."

Isliye ye engine do kaam karta hai:
    1. Exact duplicates hatao (same URL / same DOI / same title).
    2. Jo bache unhe INDEPENDENCE GROUPS mein baanto (same domain ya same DOI =
       ek hi independent voice), taaki evidence strength inflate na ho.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .models import SourceRecord

_STOP = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with",
    "is", "are", "was", "were", "by", "from", "at", "as", "that", "this",
}


def _title_tokens(title: str) -> frozenset:
    words = re.findall(r"\b\w{3,}\b", (title or "").lower())
    return frozenset(w for w in words if w not in _STOP)


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

    # ── exact + near duplicate removal ───────────────────────────────────────
    def deduplicate(self, sources: List[SourceRecord]) -> List[SourceRecord]:
        by_url: Dict[str, SourceRecord] = {}
        by_doi: Dict[str, SourceRecord] = {}
        kept_titles: List[tuple] = []          # [(tokens, record), ...]
        unique: List[SourceRecord] = []

        for s in sources:
            url_key = (s.url or "").strip().rstrip("/").lower()
            doi_key = (s.doi or "").strip().lower()

            if url_key and url_key in by_url:
                self.merge_signals(by_url[url_key], s)
                continue
            if doi_key and doi_key in by_doi:
                self.merge_signals(by_doi[doi_key], s)
                continue

            tokens = _title_tokens(s.title)
            if tokens and len(tokens) >= 3:
                twin = self._near_duplicate_of(tokens, kept_titles)
                if twin is not None:
                    self.merge_signals(twin, s)
                    continue

            if url_key:
                by_url[url_key] = s
            if doi_key:
                by_doi[doi_key] = s
            if tokens:
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
