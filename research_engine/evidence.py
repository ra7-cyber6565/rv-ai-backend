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
        queries: Optional[List[str]] = None,
    ) -> EvidencePack:
        all_candidates = list(doc_records) + list(external_records)
        discovered = len(all_candidates)

        ranked = self.relevance.rank(
            all_candidates, question,
            max_sources=max_sources, max_per_origin=max_per_origin,
        )
        # Ranking ne kya chhaanta — ye pack ke saath chalta hai. Pehle ye
        # jaankari rank() ke andar hi mar jaati thi, isliye grade_evidence ko
        # pata hi nahi tha ki sources topic ke hain ya nahi.
        filter_info = dict(getattr(self.relevance, "last_filter", {}) or {})
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
            topic_terms=list(filter_info.get("topic_terms") or []),
            retrieval_filter=filter_info,
            # §11 — kaun-kaun query chali, ye pack ke saath chalta hai
            search_queries=[q for q in (queries or []) if str(q or "").strip()],
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
    # Ye teen gate live failure (2026-08-19) ke baad lage. Us test mein report
    # ne "✅ VERIFIED — 2 peer-reviewed + 4 independent sources" chhaapa, jabki:
    #   * saare sources off-topic the (energy ke sawaal par Gagea naam ke phool
    #     ki botany aur WHO ki surgeons-density),
    #   * 5 mein se 0 ka full text pada gaya tha,
    #   * 3 mein se sirf 1 reasoning pass chala tha (Gemini quota 429).
    # Teeno galtiyan ek hi wajah se chhupi: grade sirf GINTI dekhta tha (peer
    # review, independence, average quality), retrieval aur reading ka sach
    # nahi. Ab "VERIFIED"/"STRONG" tab hi mil sakta hai jab ye teen sach saath
    # dein. Sakhti jaan-boojh kar hai: galat "VERIFIED" se "MIXED" bolna hazaar
    # guna behtar hai.
    _MIN_AVG_RELEVANCE = 0.20     # is se neeche = retrieval bharosemand nahi
    _MIN_ON_TOPIC = 2             # kam se kam itne sources sach mein topic ke ho

    @staticmethod
    def _claim_boundary_reason(
        label_report: Optional[Dict] = None,
        claim_checks: Optional[Dict] = None,
    ) -> Optional[str]:
        """Why a source-count grade may not claim VERIFIED/STRONG.

        Source quantity/quality describes the *pack*.  It cannot rescue a
        conclusion whose actual labelled claims failed claim-level A-E.  The
        arguments are optional for backwards-compatible pre-reasoning/source
        diagnostics; the production orchestrator supplies both final reports.
        """
        labels = label_report or {}
        failed_labels = max(
            int(labels.get("a_e_failed") or 0),
            int(labels.get("entailment_blocked") or 0),
            int(labels.get("strict_unverified") or 0),
        )
        if failed_labels:
            return (
                f"{failed_labels} strong claim claim-level A-E gate pass nahi kar saka"
            )
        if int(labels.get("to_unverified") or 0):
            return "ek ya zyada conclusion claim UNVERIFIED reh gaye"

        if claim_checks is not None:
            checks = claim_checks or {}
            total = int(checks.get("total_claims") or 0)
            genuine = int(checks.get("genuine_support") or 0)
            non_genuine = (
                int(checks.get("source_reported") or 0)
                + int(checks.get("cited_only") or 0)
                + int(checks.get("unsupported") or 0)
                + int(checks.get("entailment_not_checkable") or 0)
            )
            if checks.get("overclaims"):
                return "claim verification ne evidence se zyada strong conclusion pakda"
            if total and (genuine < total or non_genuine):
                return (
                    f"claim verification mein sirf {genuine}/{total} labelled claims ko "
                    "genuine full-text support mila"
                )
        return None

    def _honesty_gate(
        self,
        pack: EvidencePack,
        check_reasoning: bool = True,
        label_report: Optional[Dict] = None,
        claim_checks: Optional[Dict] = None,
    ) -> Optional[str]:
        """
        Kya is pack ko "VERIFIED/STRONG" kehne ka haq hai?

        None = haan, aage badho. String = nahi, aur ye us "nahi" ki wajah hai
        (wajah user ko dikhayi jaati hai — chupchaap downgrade nahi hota).

        `check_reasoning=False` SIRF ek jagah ke liye hai: orchestrator reasoning
        se PEHLE ek kaccha grade nikaalta hai (hypothesis chahiye ya nahi, ye
        decide karne ke liye). Us waqt reasoning ka 0/0 hona swabhavik hai, bug
        nahi — usse "adhoora" bolna ek jhoothi wajah hoti aur hypothesis wala
        faisla galat ho jaata. Final grade par ye gate HAMESHA lagta hai.
        """
        if pack.avg_relevance < self._MIN_AVG_RELEVANCE or \
                pack.on_topic_count < self._MIN_ON_TOPIC:
            return (f"sources topic se theek se match nahi karte "
                    f"(average match {pack.avg_relevance:.2f}, "
                    f"{pack.on_topic_count} source topic ke)")
        if pack.full_text_read_count < 1:
            return ("kisi bhi source ka poora text nahi pada ja saka — sirf "
                    "title/abstract par 'verified' kehna galat hoga")
        if check_reasoning and not pack.reasoning_complete:
            return (f"reasoning adhoora raha "
                    f"({pack.reasoning_done}/{pack.reasoning_planned} pass poore)")
        claim_block = self._claim_boundary_reason(label_report, claim_checks)
        if claim_block:
            return claim_block
        return None

    def grade_evidence(self, pack: EvidencePack, claims: Optional[List[Claim]] = None,
                       check_reasoning: bool = True,
                       label_report: Optional[Dict] = None,
                       claim_checks: Optional[Dict] = None) -> str:
        """
        Purane system ka 'evidence_level' string, par ab real signals se banta hai
        (source count, independence, peer review, grounded ratio) — hardcoded nahi.

        Aur sabse zaroori: TOP do labels ("VERIFIED", "STRONG") par honesty gate
        lagta hai — dekho `_honesty_gate`.
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

        deserves_top = (peer >= 2 and independent >= 3 and avg_q >= 0.7)
        deserves_strong = ((scholarly >= 2 or docs >= 2) and independent >= 3)

        if deserves_top or deserves_strong:
            blocked = self._honesty_gate(
                pack,
                check_reasoning=check_reasoning,
                label_report=label_report,
                claim_checks=claim_checks,
            )
            if blocked:
                # ginti se to top label banta tha, par sach usse rok raha hai —
                # aur wajah saath likhi jaati hai, chhupayi nahi jaati.
                return (f"🟡 MIXED — {independent} independent source(s) mile, par "
                        f"'verified' nahi keh sakta: {blocked}")
            if deserves_top:
                return f"✅ VERIFIED — {peer} peer-reviewed + {independent} independent sources"
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
