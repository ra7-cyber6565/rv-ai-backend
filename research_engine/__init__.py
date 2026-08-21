"""
Deep Research Engine (Spec Section 16 — modular architecture)

Package layout:
    models.py                 shared dataclasses (SourceRecord/Claim/EvidencePack)
    depth.py                  Research Depth Modes (Spec 13)
    planner.py                ResearchPlanner (Spec 1)
    connectors/               BookConnector / PaperConnector / WebConnector (Spec 2,3)
    source_discovery.py       SourceDiscovery (Spec 2)
    dedup.py                  DeduplicationEngine (Spec 6,7)
    relevance.py              RelevanceEngine (Spec 6)
    processing/               Document/PDF/OCR/Transcript processing
    content_fetcher.py        legally-free full-text retrieval + processing
    evidence.py               EvidenceEngine (Spec 7)
    citation.py               CitationEngine (Spec 7,14)
    contradiction.py          ContradictionEngine (Spec 8)
    gemini_reasoning.py       GeminiReasoning (Spec 9)
    critic.py                 Critic
    hypothesis.py             HypothesisEngine (Spec 10)
    verification.py           VerificationEngine (Spec 11)
    research_memory.py        ResearchMemory
    synthesizer.py            FinalSynthesizer
    orchestrator.py           DeepResearchEngine

Heavy modules lazily import so ``import research_engine`` remains cheap. A tiny
pure-Python domain ambiguity guard is installed immediately because every later
planner/relevance/connector caller must share the same domain decision.
"""
from __future__ import annotations

# Install before planner/relevance/connectors bind domain.detect. This module is
# pure Python and has no heavy dependency/network side effect.
from . import domain_detection_guard as _domain_detection_guard  # noqa: F401

from .models import (
    Claim,
    ClaimType,
    EvidencePack,
    Passage,
    ResearchResult,
    SourceRecord,
    SourceType,
    label_to_claim_type,
)
from .depth import DepthConfig, get_depth_config, quota_note

__all__ = [
    "Claim", "ClaimType", "EvidencePack", "Passage", "ResearchResult",
    "SourceRecord", "SourceType", "label_to_claim_type",
    "DepthConfig", "get_depth_config", "quota_note",
    "CitationEngine", "EvidenceEngine", "ContradictionEngine",
    "RelevanceEngine", "DeduplicationEngine", "ResearchPlanner",
    "SourceDiscovery", "DeepResearchEngine", "AgentManager", "manager",
    "VerificationEngine", "HypothesisEngine", "ResearchMemory",
    "FinalSynthesizer", "GeminiReasoning", "Critic", "VectorSearch",
    "KnowledgeGraphAdapter", "DocumentProcessor", "PDFProcessor",
    "OCRProcessor", "TranscriptProcessor", "ContentFetcher",
]

_LAZY = {
    "CitationEngine": ".citation",
    "EvidenceEngine": ".evidence",
    "ContradictionEngine": ".contradiction",
    "RelevanceEngine": ".relevance",
    "DeduplicationEngine": ".dedup",
    "ResearchPlanner": ".planner",
    "SourceDiscovery": ".source_discovery",
    "VerificationEngine": ".verification",
    "HypothesisEngine": ".hypothesis",
    "ResearchMemory": ".research_memory",
    "FinalSynthesizer": ".synthesizer",
    "GeminiReasoning": ".gemini_reasoning",
    "Critic": ".critic",
    "VectorSearch": ".vector_search",
    "KnowledgeGraphAdapter": ".knowledge_graph",
    "DocumentProcessor": ".processing",
    "PDFProcessor": ".processing",
    "OCRProcessor": ".processing",
    "TranscriptProcessor": ".processing",
    "ContentFetcher": ".content_fetcher",
    "DeepResearchEngine": ".orchestrator",
    "AgentManager": ".agent_manager",
    "manager": ".agent_manager",
}


def __getattr__(name: str):
    if name in _LAZY:
        from importlib import import_module
        module = import_module(_LAZY[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
