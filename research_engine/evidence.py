"""
EvidenceEngine — Spec Section 7

Kaam:
    1. User ke documents (ChromaDB retrieval) + external sources ko ek hi
       structured EvidencePack mein laao — dono ko barabar treat karo.
    2. Har source ko quality/independence ke saath score karo.
    3. Reasoning model ke output se claims + unka provenance nikaalo.
    4. Evidence strength grade karo (VERIFIED / STRONG / MIXED / WEAK / UNVERIFIED).

Ye module wo purana bug bhi theek karta hai jahan external search sirf tab hota
tha jab PDF context na ho. Ab documents aur external sources ek saath aate hain,
isliye ContradictionEngine dono ke beech ka conflict bhi pakad sakta hai.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .citation import CitationEngine
from .dedup import DeduplicationEngine
from .models import (
    Claim,
    ClaimType,
    EvidencePack,
    Passage,
    SourceRecord,
    SourceType,
)
from .relevance import RelevanceEngine

# rag/pipeline.py aise headers banata hai: "[Source: file.pdf, Page 12]"
_DOC_HEADER_RE = re.compile(r"\[Source:\s*([^,\]]+),\s*Page\s*(\d+)\]")


class EvidenceEngine:
    def __init__(
        self,
        relevance: Optional[RelevanceEngine] = None,
        citation: Optional[CitationEngine] = None,
        dedup: Optional[DeduplicationEngine] = None,
    ):
        self.dedup = dedup or DeduplicationEngine()
        self.relevance = relevance or RelevanceEngine(dedup=self.dedup)
        self.citation = citation or CitationEngine()

    # ── 1. Documents ko SourceRecords mein badlo ─────────────────────────────
    def records_from_retrieval(self, retrieval: Dict) -> List[SourceRecord]:
        """
        get_context_only() ka output ({"context": str, "sources": [...]}) ko
        per-page SourceRecords mein todo, taaki har page ko apna [S#] mile.
        """
        context = (retrieval or {}).get("context") or ""
        if not context.strip():
            return []

        parts = _DOC_HEADER_RE.split(context)
        records: Dict[str, SourceRecord] = {}
        order: List[str] = []

        # parts = [pre_text, file, page, body, file, page, body, ...]
        for i in range(1, len(parts) - 2, 3):
            filename = parts[i].strip()
            page = parts[i + 1].strip()
            body = (parts[i + 2] or "").strip()
            if not body:
                continue
            key = f"{filename}|{page}"
            if key in records:
                records[key].snippet += "\n" + body
                continue
            records[key] = SourceRecord(
                title=filename,
                url="",
                snippet=body,
                connector="user_pdf",
                source_type=SourceType.DOCUMENT,
                locator=f"Page {page}",
                full_text_available=True,
                is_primary=None,
                # read_level YAHAN explicitly set hota hai, models.py mein guess
                # nahi hota. Wajah imaandaari ki hai: ye file upload ke waqt
                # DocumentProcessor se poori padhi gayi thi (saare pages), aur
                # yahan uske sabse relevant hisse aa rahe hain. Jo code
                # provenance jaanta hai wahi ye label lagata hai.
                read_level="full_text",
            )
            order.append(key)

        if not order:  # header parse fail — poora context ek source ki tarah lo
            files = [s.get("file", "document") for s in (retrieval.get("sources") or [])]
            title = files[0] if files else "uploaded document"
            return [SourceRecord(
                title=title, snippet=context.strip(), connector="user_pdf",
                source_type=SourceType.DOCUMENT, full_text_available=True,
                read_level="full_text",
            )]

        return [records[k] for k in order]

    # ── 2. EvidencePack banao ────────────────────────────────────────────────
    def build_pack(
        self,
        question: str,
        doc_records: List[SourceRecord],
        external_records: List[SourceRecord],
        max_sources: int = 10,
        max_per_origin: int = 3,
        connectors_searched: Optional[List[str]] = None,
        rounds_run: int = 1,
        chars_per_source: int = 1200,
    ) -> EvidencePack:
        all_candidates = list(doc_records) + list(external_records)
        discovered = len(all_candidates)

        ranked = self.relevance.rank(
            all_candidates, question,
            max_sources=max_sources, max_per_origin=max_per_origin,
        )
        self.citation.assign_ids(ranked)

        passages: List[Passage] = []
        for s in ranked:
            text = (s.snippet or "").strip()
            if text:
                passages.append(Passage(
                    source_id=s.source_id,
                    text=text[:chars_per_source],
                    locator=s.locator,
                ))

        return EvidencePack(
            question=question,
            sources=ranked,
            passages=passages,
            rounds_run=rounds_run,
            discovered_count=discovered,
            searched_connectors=sorted(set(connectors_searched or [])),
        )

    # ── 3. Claims + provenance (Spec Section 7) ──────────────────────────────
    def extract_claims(self, text: str, pack: EvidencePack) -> List[Claim]:
        return self.citation.extract_claims(text, pack)

    def evidence_table(self, claims: List[Claim]) -> Dict:
        counts = {ct.value: 0 for ct in ClaimType}
        grounded = 0
        for c in claims:
            counts[c.claim_type.value] = counts.get(c.claim_type.value, 0) + 1
            if c.is_grounded:
                grounded += 1
        return {
            "total_claims": len(claims),
            "grounded_claims": grounded,
            "grounded_ratio": round(grounded / len(claims), 3) if claims else 0.0,
            "by_type": counts,
        }

    # ── 4. Overall evidence grade ────────────────────────────────────────────
    def grade_evidence(self, pack: EvidencePack, claims: Optional[List[Claim]] = None) -> str:
        """
        Purane system ka 'evidence_level' string, par ab real signals se banta hai
        (source count, independence, peer review, grounded ratio) — hardcoded nahi.
        """
        if not pack.sources:
            return "⚠️ UNVERIFIED — koi source retrieve nahi hua (sirf general knowledge)"

        independent = pack.independent_source_count
        peer = sum(1 for s in pack.sources if s.peer_reviewed is True)
        scholarly = sum(1 for s in pack.sources if s.doi or s.source_type == SourceType.PAPER)
        docs = len(pack.document_sources())
        avg_q = sum(s.quality_score for s in pack.sources) / len(pack.sources)
        grounded_ratio = self.evidence_table(claims)["grounded_ratio"] if claims else None

        if grounded_ratio is not None and grounded_ratio < 0.34:
            return (f"⚠️ WEAK — {independent} independent source(s) mile, par answer ke "
                    f"zyadatar claims kisi source se linked nahi hain")
        if peer >= 2 and independent >= 3 and avg_q >= 0.7:
            return f"✅ VERIFIED — {peer} peer-reviewed + {independent} independent sources"
        if (scholarly >= 2 or docs >= 2) and independent >= 3:
            return f"✅ STRONG — {scholarly} scholarly / {docs} document source(s), {independent} independent"
        if independent >= 2:
            return f"🟡 MIXED — {independent} independent source(s), limited scholarly evidence"
        return f"⚠️ WEAK — sirf {independent} independent source (aur verification baaki hai)"

    # ── 5. Round 2/3 chahiye ya nahi (Spec Section 2) ────────────────────────
    def needs_another_round(self, pack: EvidencePack, is_scientific: bool = False) -> Dict:
        return self.relevance.is_evidence_sufficient(
            pack.sources, require_scholarly=is_scientific
        )

    def independence_report(self, pack: EvidencePack) -> Dict:
        return self.dedup.independence_report(pack.sources)
