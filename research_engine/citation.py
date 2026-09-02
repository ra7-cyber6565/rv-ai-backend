"""
CitationEngine — Spec Section 7 + 14

Ye module wo purani gandi trick hata deta hai jahan citations aise nikalte the:
    cited = [r for r in web_results if r["url"] in final_text]
Gemini apne answer mein exact URL kabhi-kabhi hi likhta hai, isliye wo list
zyadatar khaali aati thi — matlab system research karke bhi "sources: []" dikhata tha.

Naya tareeka (structural, prompt ki request pe bharosa nahi):
    1. Har source ko ek ID milta hai — [S1], [S2], ...
    2. Gemini ko bola jaata hai ki har claim ke saath uska source ID likhe.
    3. Ye engine answer se IDs nikaalta hai aur unhe asli sources se verify karta hai.
    4. Jo ID exist nahi karta (Gemini ne bana diya) — wo INVALID mark hota hai.
    5. Jo source use hi nahi hua — wo bhi honestly report hota hai.

Koi heavy dependency nahi — offline test ho sakta hai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Claim, ClaimType, EvidencePack, SourceRecord, label_to_claim_type

# [S1] / [S1, S3] / [S1][S2] / [s4] — sab handle karo
_BRACKET_RE = re.compile(r"\[([^\[\]]{1,60})\]")
_SID_RE = re.compile(r"\bS\s?(\d{1,3})\b", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-_]?SOURCE\s*\]", re.IGNORECASE)
_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE|SOURCE[\s\-]?REPORTED|"
    r"MIXED\s+EVIDENCE|"
    r"WEAK\s+EVIDENCE|EVIDENCE|INFERENCE|HYPOTHESIS|SPECULATION|UNVERIFIED|UNKNOWN)\s*\]",
    re.IGNORECASE,
)
# Ye labels bina source ke nahi hone chahiye
_MUST_BE_GROUNDED = {ClaimType.FACT, ClaimType.EVIDENCE}

# A model often wraps one labelled claim across two or three Markdown lines.
# Citation/verification code must treat that as one bounded block, but must not
# borrow a citation from the next bullet/section.  Keep these boundaries
# deliberately structural and deterministic (no model/API call).
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d{1,3}[.)]\s+)")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_PLAIN_SOURCE_HEADING_RE = re.compile(
    r"^\s*(?:sources?|references?|bibliography|citations?)\s*:?\s*$",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def labelled_claim_spans(
    text: str,
    max_continuation_lines: int = 5,
) -> List[Tuple[int, int, str]]:
    """Return ``(start, end, block)`` for each bounded labelled claim.

    ``start`` is inclusive and ``end`` exclusive in ``text.splitlines()``.
    A citation on a short continuation line belongs to the claim.  A blank
    line, heading, code fence, new label, or new Markdown list item ends it, so
    one claim can never steal a later bullet's citation.  The continuation cap
    also prevents malformed model output from swallowing the rest of an answer.
    """
    lines = (text or "").splitlines()
    cap = max(0, int(max_continuation_lines))
    spans: List[Tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        if not _LABEL_RE.search(lines[index]):
            index += 1
            continue

        start = index
        end = start + 1
        continuation_count = 0
        while end < len(lines) and continuation_count < cap:
            candidate = lines[end]
            stripped = candidate.strip()
            if (
                not stripped
                or _LABEL_RE.search(candidate)
                or _LIST_ITEM_RE.match(candidate)
                or _HEADING_RE.match(candidate)
                or _PLAIN_SOURCE_HEADING_RE.match(candidate)
                or _FENCE_RE.match(candidate)
            ):
                break
            end += 1
            continuation_count += 1

        spans.append((start, end, "\n".join(lines[start:end]).strip()))
        index = end
    return spans


@dataclass
class CitationReport:
    cited: List[Dict] = field(default_factory=list)
    uncited: List[Dict] = field(default_factory=list)
    invalid_ids: List[str] = field(default_factory=list)
    ungrounded_claims: List[str] = field(default_factory=list)
    no_source_markers: int = 0
    used_legacy_url_match: bool = False

    @property
    def grounded_ratio(self) -> float:
        total = len(self.cited) + len(self.invalid_ids)
        return len(self.cited) / total if total else 0.0

    def to_dict(self) -> Dict:
        return {
            "cited": self.cited,
            "uncited": self.uncited,
            "invalid_ids": self.invalid_ids,
            "ungrounded_claims": self.ungrounded_claims,
            "no_source_markers": self.no_source_markers,
            "used_legacy_url_match": self.used_legacy_url_match,
        }


class CitationEngine:
    """Source IDs assign karta hai, citations verify karta hai, bibliography banata hai."""

    def __init__(self, prefix: str = "S"):
        self.prefix = prefix

    # ── 1. IDs assign karo ───────────────────────────────────────────────────
    def assign_ids(self, sources: List[SourceRecord]) -> List[SourceRecord]:
        for i, s in enumerate(sources, start=1):
            s.source_id = f"{self.prefix}{i}"
        return sources

    # ── 2. Answer se IDs nikaalo ─────────────────────────────────────────────
    def extract_ids(self, text: str) -> List[str]:
        """Answer mein jitne [S#] mile, unki ordered unique list."""
        found: List[str] = []
        for match in _BRACKET_RE.finditer(text or ""):
            inner = match.group(1)
            for num in _SID_RE.findall(inner):
                sid = f"{self.prefix}{int(num)}"
                if sid not in found:
                    found.append(sid)
        return found

    # ── 3. Verify ────────────────────────────────────────────────────────────
    def verify(self, text: str, pack: EvidencePack) -> CitationReport:
        report = CitationReport()
        text = text or ""
        valid = set(pack.valid_ids)
        referenced = self.extract_ids(text)

        for sid in referenced:
            if sid in valid:
                src = pack.by_id(sid)
                if src:
                    report.cited.append(self._citation_dict(src))
            else:
                report.invalid_ids.append(sid)

        # Legacy fallback: Gemini ne ek bhi ID nahi likha to URL/title match try karo
        if not referenced and pack.sources:
            legacy = self._legacy_match(text, pack)
            if legacy:
                report.cited.extend(legacy)
                report.used_legacy_url_match = True

        cited_ids = {c["source_id"] for c in report.cited}
        report.uncited = [
            self._citation_dict(s) for s in pack.sources if s.source_id not in cited_ids
        ]
        report.no_source_markers = len(_NO_SOURCE_RE.findall(text))
        report.ungrounded_claims = self.find_ungrounded_claims(text)
        return report

    # ── 4. Ungrounded claims dhoondo ─────────────────────────────────────────
    def find_ungrounded_claims(self, text: str, max_items: int = 12) -> List[str]:
        """
        Wo bounded claim blocks jinhe FACT/EVIDENCE label kiya gaya hai lekin
        koi [S#] nahi diya.
        Yahi source-honesty ka structural check hai.
        """
        out: List[str] = []
        for _, _, block in labelled_claim_spans(text):
            if len(block) < 25:
                continue
            labels = _LABEL_RE.findall(block)
            if not labels:
                continue
            types = {label_to_claim_type(lbl) for lbl in labels}
            if not (types & _MUST_BE_GROUNDED):
                continue
            if self.extract_ids(block) or _NO_SOURCE_RE.search(block):
                continue
            clean = _LABEL_RE.sub("", block)
            clean = re.sub(r"^[#\s\-\*\d\.]+", "", clean)
            clean = " ".join(clean.split())
            out.append(clean[:220])
            if len(out) >= max_items:
                break
        return out

    # ── 5. Claims + provenance nikaalo (Spec Section 7) ──────────────────────
    def extract_claims(self, text: str, pack: Optional[EvidencePack] = None) -> List[Claim]:
        claims: List[Claim] = []
        valid = set(pack.valid_ids) if pack else None
        for _, _, block in labelled_claim_spans(text):
            if len(block) < 25:
                continue
            labels = _LABEL_RE.findall(block)
            if not labels:
                continue
            ctype = label_to_claim_type(labels[0])
            ids = self.extract_ids(block)
            if valid is not None:
                ids = [i for i in ids if i in valid]
            body = _LABEL_RE.sub("", block)
            body = re.sub(r"^[#\s\-\*\d\.]+", "", body).strip()
            body = " ".join(body.split())
            claims.append(Claim(text=body[:400], claim_type=ctype, source_ids=ids))
        return claims

    # ── 6. Answer ko annotate karo ───────────────────────────────────────────
    def annotate(self, text: str, pack: EvidencePack) -> str:
        """
        Valid [S#] ko clickable bana do, invalid ko clearly mark kar do
        (chupao mat — user ko dikhna chahiye ki AI ne galat citation di).
        """
        valid = set(pack.valid_ids)

        def _replace(match: re.Match) -> str:
            inner = match.group(1)
            nums = _SID_RE.findall(inner)
            if not nums:
                return match.group(0)
            parts = []
            for num in nums:
                sid = f"{self.prefix}{int(num)}"
                src = pack.by_id(sid) if sid in valid else None
                if src and src.url:
                    parts.append(f"[{sid}]({src.url})")
                elif src:
                    loc = f" — {src.locator}" if src.locator else ""
                    parts.append(f"[{sid}: {src.title[:40]}{loc}]")
                else:
                    parts.append(f"[{sid} ⚠️ INVALID CITATION]")
            return "".join(parts)

        return _BRACKET_RE.sub(_replace, text or "")

    # ── 7. Bibliography ──────────────────────────────────────────────────────
    def render_bibliography(self, citations, cited_ids: Optional[List[str]] = None) -> str:
        """
        Teen tarah ka input chalta hai, kyunki callers alag-alag cheez paas karte hain:
            * EvidencePack        -> saare sources (section 12 ke liye)
            * List[SourceRecord]  -> jaise ka taisa
            * List[Dict]          -> report.cited jaisi already-dict list
        `cited_ids` de do to jo actually cite hue unpe ✓ lag jaata hai — isse
        pata chalta hai kaun source sirf screen hua tha, kaun use hua.
        """
        rows: List[Dict] = []
        if citations is None:
            rows = []
        elif hasattr(citations, "sources"):                       # EvidencePack
            rows = [s.to_dict() for s in citations.sources]
        else:
            for item in citations:
                rows.append(item if isinstance(item, dict) else item.to_dict())

        if not rows:
            return "_Koi verified citation nahi mila._"

        marked = set(cited_ids or [])
        lines = []
        for c in rows:
            sid = c.get("source_id") or "S?"
            tick = " ✓cited" if sid in marked else ""
            bits = [f"**[{sid}]**{tick}"]
            if c.get("title"):
                bits.append(c["title"])
            if c.get("authors"):
                bits.append(f"— {', '.join(c['authors'][:3])}")
            if c.get("year"):
                bits.append(f"({c['year']})")
            if c.get("publisher"):
                bits.append(c["publisher"])
            if c.get("locator"):
                bits.append(c["locator"])
            if c.get("url"):
                bits.append(f"<{c['url']}>")
            tag = c.get("source_type", "")
            if c.get("peer_reviewed") is True:
                tag += ", peer-reviewed"
            if tag:
                bits.append(f"_({tag})_")
            lines.append("- " + " ".join(str(b) for b in bits if b))
        return "\n".join(lines)

    # ── 8. Honesty report (Spec Section 2 + 7) ───────────────────────────────
    def honesty_report(self, report: CitationReport, pack: EvidencePack) -> str:
        lines = [
            f"- Sources retrieved: **{len(pack.sources)}** "
            f"(independent: **{pack.independent_source_count}**, "
            f"candidates screened: **{pack.discovered_count}**)",
            f"- Citations verified against real sources: **{len(report.cited)}**",
            # §13 (2026-08-21) — is number ka matlab OVER-claim na ho. Upar wali
            # ginti sirf itna kehti hai ki likhi hui [S#] asli source par point
            # karti hai. "Us source ka text ye claim keh raha hai" ek ALAG check
            # hai (C), aur wo report ke A–E block mein alag chhapta hai.
            "  - Iska matlab: citation asli source par point karti hai. "
            "\"Us source ka text ye baat keh raha hai\" ye alag check hai — "
            "wo neeche A–E block mein alag likha gaya hai.",
        ]
        if report.invalid_ids:
            lines.append(
                f"- ⚠️ Invalid/hallucinated citation IDs detected and marked: "
                f"**{', '.join(report.invalid_ids)}**"
            )
        if report.ungrounded_claims:
            lines.append(
                f"- ⚠️ Claims labeled as fact/evidence but with no source attached: "
                f"**{len(report.ungrounded_claims)}**"
            )
        if report.uncited:
            lines.append(
                f"- Sources retrieved but not used in the answer: **{len(report.uncited)}**"
            )
        if report.used_legacy_url_match:
            lines.append(
                "- ⚠️ Reasoning model ne source IDs use nahi kiye; citations URL/title "
                "match se nikaali gayi hain (kam reliable)."
            )
        if not pack.sources:
            lines.append(
                "- ⚠️ Is sawal ke liye koi relevant source retrieve nahi hua — "
                "jawab sirf model ki general knowledge par hai."
            )
        else:
            # Pehle yahan ek FIXED line thi: "system ne in sources ka poora full
            # text nahi padha". Jab se ContentFetcher sach mein full text
            # download karta hai, wo line jhooth ban sakti thi. Ab ye line asli
            # read-level counts se banti hai (models.reading_note), isliye ye
            # kabhi over-claim bhi nahi karegi aur kabhi under-claim bhi nahi.
            lines.append(f"- Reading depth (asli ginti): {pack.reading_note()}")
            total_citations = len(report.cited) + len(report.invalid_ids)
            if total_citations:
                # grounded_ratio = valid citations / (valid + hallucinated IDs).
                # Ye percentage banaya hua nahi hai — ID matching se gini gayi hai.
                lines.append(
                    f"- Citations jo asli source par point karti hain: "
                    f"**{int(round(report.grounded_ratio * 100))}%** "
                    f"({len(report.cited)} valid / {total_citations} total)"
                )
        return "\n".join(lines)

    # ── internals ────────────────────────────────────────────────────────────
    @staticmethod
    def _citation_dict(src: SourceRecord) -> Dict:
        return {
            "source_id": src.source_id,
            "title": src.title,
            "url": src.url,
            "authors": src.authors,
            "year": src.year,
            "publisher": src.publisher,
            "locator": src.locator,
            "source_type": src.source_type.value,
            "connector": src.connector,
            "peer_reviewed": src.peer_reviewed,
            # purane API consumers (Android app) ke liye compatibility
            "file": src.title if src.source_type.value == "document" else "",
            "page": src.locator.replace("Page ", "") if src.locator.startswith("Page ") else "",
        }

    def _legacy_match(self, text: str, pack: EvidencePack) -> List[Dict]:
        """Purana behaviour — sirf fallback ke liye."""
        out = []
        low = text.lower()
        for s in pack.sources:
            if s.url and s.url.lower() in low:
                out.append(self._citation_dict(s))
            elif s.title and len(s.title) > 18 and s.title.lower() in low:
                out.append(self._citation_dict(s))
        return out


# Prompt ke andar daalne wala instruction — ek hi jagah rakho taaki
# saare passes same citation format use karein.
CITATION_INSTRUCTION = """CITATION RULES (inhe follow karna zaroori hai):
- Sources ko upar diye gaye IDs se cite karo: [S1], [S2], [S1][S4] — is format mein.
- Har factual claim ke turant baad uska source ID likho.
- Jo ID list mein nahi hai use MAT likho. Naya ID invent karna galti maani jayegi.
- Agar koi baat kisi bhi diye gaye source mein nahi hai, to uske saath [NO-SOURCE] likho
  aur usko [INFERENCE] ya [HYPOTHESIS] label karo — use fact ki tarah pesh mat karo.
- Agar sources sawal ke liye relevant nahi hain, to saaf likho: "diye gaye sources is
  sawal ke liye relevant nahi hain" — irrelevant source cite mat karo.
- Label rule: `[ESTABLISHED]` sirf tab jab us source ka POORA text padha gaya ho
  (source block mein "Read: full_text" likha hoga). Sirf abstract/snippet mila ho
  to `[SOURCE-REPORTED]` likho — matlab "source ye report karta hai", confirmed
  fact nahi. Ye rule todne par system label khud neeche kar dega.

CITATION KO PADHNE LAYAK RAKHO:
- Ek line mein 1-2 se zyada [S#] mat thoso. Poora URL, DOI ya lamba ID kabhi
  answer ke andar mat likho — sirf [S1] jaisa chhota ID.
- Har vaakya ke peeche citation ki zaroorat nahi. Har labelled claim/bullet ke
  mool factual dave ko usi bounded block mein cite karo; ho sake to usi line par.
  Agle bullet ya door ke paragraph ki citation pichhle claim ko support nahi karegi.
- Jahan explanation chal rahi hai (example, "simple words mein" wala hissa),
  wahan citation se vaakya todo mat."""
