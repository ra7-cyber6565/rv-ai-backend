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
    processing/               DocumentProcessor / PDFProcessor / OCRProcessor /
                              TranscriptProcessor (Spec 4,5)
    content_fetcher.py        ContentFetcher — legally-free full text laata hai
                              aur processing/ ko pipeline se jodta hai (Spec 3,4,5)
    vector_search.py          VectorSearch (Spec 4,6)
    evidence.py               EvidenceEngine (Spec 7)
    citation.py               CitationEngine (Spec 7,14)
    contradiction.py          ContradictionEngine (Spec 8)
    gemini_reasoning.py       GeminiReasoning (Spec 9)
    critic.py                 Critic (Spec 9 Pass 4/6)
    hypothesis.py             HypothesisEngine (Spec 10)
    verification.py           VerificationEngine (Spec 11)
    knowledge_graph.py        KnowledgeGraph adapter (Spec 16)
    research_memory.py        ResearchMemory (Spec 16)
    synthesizer.py            FinalSynthesizer (Spec 14)
    orchestrator.py           DeepResearchEngine — poora pipeline
    agent_manager.py          AgentManager — per-project engines

NOTE: heavy modules (chromadb / sentence-transformers / google-generativeai)
lazily import hote hain, taaki `import research_engine` sasta rahe aur pure
logic offline test ho sake.
"""
from __future__ import annotations

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
    # lazy — har naam _LAZY mein bhi hona chahiye, warna
    # `from research_engine import *` AttributeError deta hai.
    # ("agent_manager" pehle yahan tha par _LAZY mein nahi — wo bug tha;
    #  singleton ka asli naam "manager" hai.)
    "CitationEngine", "EvidenceEngine", "ContradictionEngine",
    "RelevanceEngine", "DeduplicationEngine", "ResearchPlanner",
    "SourceDiscovery", "DeepResearchEngine", "AgentManager", "manager",
    "VerificationEngine", "HypothesisEngine", "ResearchMemory",
    "FinalSynthesizer", "GeminiReasoning", "Critic", "VectorSearch",
    "KnowledgeGraphAdapter", "DocumentProcessor", "PDFProcessor",
    "OCRProcessor", "TranscriptProcessor", "ContentFetcher",
]

# PEP 562 — heavy cheezein tabhi load karo jab maangi jayen
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
    # ready-to-use singleton (routes isse import karti hain)
    "manager": ".agent_manager",
}


def __getattr__(name: str):
    if name in _LAZY:
        from importlib import import_module
        module = import_module(_LAZY[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
