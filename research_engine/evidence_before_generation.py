"""Deterministic evidence-before-generation prompt boundary.

The post-generation A-E verifier remains authoritative.  This module adds an
EARLIER fail-closed boundary: before the synthesis model drafts critical factual
claims, it only receives a reduced prompt pack whose excerpts are exact,
preselected evidence spans with source IDs and locators.

Nothing here claims that a future sentence is already verified.  A span can be
`strong_eligible` only when source-side prerequisites are present; check C still
has to compare the final drafted claim against that exact span afterwards.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, replace
from typing import Dict, List, Tuple

from .models import EvidencePack, Passage, SourceRecord, SourceType
from .semantic import similarity

# These mirror the existing P0-A source-side floors; they are deliberately not
# lower.  Final claim verification still uses its own authoritative constants.
_MIN_RELEVANCE = 0.25
_MIN_QUALITY = 0.35
_MIN_SPAN_SIMILARITY = 0.25
_MIN_CANDIDATE_SIMILARITY = 0.12
_MIN_SPAN_CHARS = 40


@dataclass(frozen=True)
class EvidenceSeed:
    source_id: str
    locator: str
    passage: str
    semantic_score: float
    relevance_score: float
    quality_score: float
    read_level: str
    strong_eligible: bool
    passage_hash: str

    def audit_dict(self) -> Dict:
        return {
            "source_id": self.source_id,
            "locator": self.locator,
            "semantic_score": self.semantic_score,
            "relevance_score": self.relevance_score,
            "quality_score": self.quality_score,
            "read_level": self.read_level,
            "strong_eligible": self.strong_eligible,
            "passage_hash": self.passage_hash,
        }


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _source_candidates(pack: EvidencePack) -> List[Tuple[SourceRecord, Passage]]:
    """One exact candidate stream: real passages first, snippet fallback second."""
    out: List[Tuple[SourceRecord, Passage]] = []
    seen_sources = set()
    for passage in list(getattr(pack, "passages", None) or []):
        source = pack.by_id(str(passage.source_id or ""))
        text = str(passage.text or "").strip()
        if source is None or len(text) < _MIN_SPAN_CHARS:
            continue
        out.append((source, Passage(
            source_id=source.source_id,
            text=text,
            locator=str(passage.locator or source.locator or "").strip(),
        )))
        seen_sources.add(source.source_id)

    # Some connectors only provide the selected source excerpt in snippet.
    # That excerpt can seed drafting, but it remains subject to read-level rules.
    for source in list(getattr(pack, "sources", None) or []):
        if not source.source_id or source.source_id in seen_sources:
            continue
        text = str(source.snippet or "").strip()
        if len(text) < _MIN_SPAN_CHARS:
            continue
        out.append((source, Passage(
            source_id=source.source_id,
            text=text,
            locator=str(source.locator or "source excerpt").strip(),
        )))
    return out


def _strong_eligible(source: SourceRecord, semantic_score: float) -> bool:
    """Source-side prerequisites only; this is NOT final claim verification."""
    if getattr(source, "retracted", None) is True:
        return False
    if str(getattr(source, "rejected_reason", "") or "").strip():
        return False
    if getattr(source, "source_type", None) == SourceType.PATENT:
        return False
    if semantic_score < _MIN_SPAN_SIMILARITY:
        return False
    if float(getattr(source, "relevance_score", 0.0) or 0.0) < _MIN_RELEVANCE:
        return False
    if float(getattr(source, "quality_score", 0.0) or 0.0) < _MIN_QUALITY:
        return False
    try:
        if source.reading_level() != "full_text":
            return False
    except Exception:
        return False
    return True


def select_evidence_seeds(question: str, pack: EvidencePack,
                          max_spans: int = 8) -> List[EvidenceSeed]:
    """Select at most one exact span per source, deterministically."""
    question = str(question or "").strip()
    if not question or pack is None or max_spans <= 0:
        return []

    best_by_source: Dict[str, EvidenceSeed] = {}
    for source, passage in _source_candidates(pack):
        if getattr(source, "retracted", None) is True:
            continue
        if str(getattr(source, "rejected_reason", "") or "").strip():
            continue

        semantic_score = float(similarity(question, passage.text) or 0.0)
        relevance = float(getattr(source, "relevance_score", 0.0) or 0.0)
        quality = float(getattr(source, "quality_score", 0.0) or 0.0)
        # Do not feed a completely off-topic excerpt merely because it exists.
        if semantic_score < _MIN_CANDIDATE_SIMILARITY and relevance < _MIN_RELEVANCE:
            continue
        try:
            read_level = str(source.reading_level() or "metadata")
        except Exception:
            read_level = "metadata"

        seed = EvidenceSeed(
            source_id=source.source_id,
            locator=str(passage.locator or "").strip(),
            passage=passage.text,
            semantic_score=round(semantic_score, 4),
            relevance_score=round(relevance, 4),
            quality_score=round(quality, 4),
            read_level=read_level,
            strong_eligible=_strong_eligible(source, semantic_score),
            passage_hash=_hash(passage.text),
        )
        previous = best_by_source.get(seed.source_id)
        rank = (seed.strong_eligible, seed.semantic_score,
                seed.relevance_score, seed.quality_score,
                seed.locator, seed.passage_hash)
        if previous is None:
            best_by_source[seed.source_id] = seed
        else:
            old_rank = (previous.strong_eligible, previous.semantic_score,
                        previous.relevance_score, previous.quality_score,
                        previous.locator, previous.passage_hash)
            if rank > old_rank:
                best_by_source[seed.source_id] = seed

    seeds = list(best_by_source.values())
    seeds.sort(key=lambda s: (
        -int(s.strong_eligible),
        -s.semantic_score,
        -s.relevance_score,
        -s.quality_score,
        s.source_id,
        s.locator,
        s.passage_hash,
    ))
    return seeds[:max_spans]


def _reduced_pack(pack: EvidencePack, seeds: List[EvidenceSeed]) -> EvidencePack:
    """Shallow-copy the pack and replace source excerpts with selected spans."""
    reduced = copy.copy(pack)
    selected_sources: List[SourceRecord] = []
    selected_passages: List[Passage] = []
    for seed in seeds:
        source = pack.by_id(seed.source_id)
        if source is None:
            continue
        selected_sources.append(replace(
            source,
            snippet=seed.passage,
            locator=seed.locator or source.locator,
        ))
        selected_passages.append(Passage(
            source_id=seed.source_id,
            text=seed.passage,
            locator=seed.locator,
        ))
    reduced.sources = selected_sources
    reduced.passages = selected_passages
    return reduced


def render_evidence_first_block(seeds: List[EvidenceSeed]) -> str:
    """System-owned instructions inserted before the model-facing source block."""
    lines = [
        "EVIDENCE-FIRST DRAFTING CONTRACT (SYSTEM-OWNED):",
        "- Critical factual claims must be drafted FROM one exact span below first; do not invent a claim and search for a citation afterwards.",
        "- Put that SAME span's [S#] citation in the same bounded claim block.",
        "- Do not use discarded source text, titles, metadata, memory notes, hypotheses, or analysis prose as evidence for a critical factual claim.",
        "- strong_eligible=yes is only a PRE-DRAFT source/span prerequisite, not final verification. The final drafted claim still must pass A-E on this same source and exact span afterwards.",
        "- If no listed span has strong_eligible=yes, do NOT write [ESTABLISHED FACT] or [STRONG EVIDENCE]; use SOURCE-REPORTED / WEAK EVIDENCE / UNVERIFIED as appropriate.",
    ]
    if not seeds:
        lines.append("- NO ELIGIBLE EVIDENCE SPAN WAS PRESELECTED. Strong factual claims are prohibited for this synthesis call.")
        return "\n".join(lines)

    for index, seed in enumerate(seeds, 1):
        loc = seed.locator or "locator unavailable"
        lines.extend([
            "",
            f"[E{index}] source=[{seed.source_id}] locator={loc}",
            f"strong_eligible={'yes' if seed.strong_eligible else 'no'} | read={seed.read_level} | semantic={seed.semantic_score:.4f} | relevance={seed.relevance_score:.4f} | quality={seed.quality_score:.4f} | span_hash={seed.passage_hash}",
            f"EXACT SPAN: {seed.passage}",
        ])
    return "\n".join(lines)


def prepare_evidence_first_prompt(question: str, pack: EvidencePack,
                                  max_spans: int = 8
                                  ) -> Tuple[EvidencePack, str, Dict]:
    """Return reduced prompt pack, system block, and text-free audit metadata."""
    seeds = select_evidence_seeds(question, pack, max_spans=max_spans)
    reduced = _reduced_pack(pack, seeds)
    audit = {
        "applied": True,
        "selection_method": "question_semantic_plus_existing_source_signals",
        "original_source_count": len(list(getattr(pack, "sources", None) or [])),
        "selected_span_count": len(seeds),
        "selected_source_count": len({s.source_id for s in seeds}),
        "strong_eligible_count": len([s for s in seeds if s.strong_eligible]),
        "strong_claims_pre_draft_allowed": any(s.strong_eligible for s in seeds),
        "selected": [s.audit_dict() for s in seeds],
        "final_same_source_ae_still_required": True,
        "original_pack_mutated": False,
    }
    return reduced, render_evidence_first_block(seeds), audit
