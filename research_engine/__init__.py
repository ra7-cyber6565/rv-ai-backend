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
    reasoning_router.py       quota-resilient ₹0 provider fallback base
    reasoning_router_integrated.py
                              provider fallback + latest pass accounting facade
    source_prompt_guard.py    untrusted source-data / prompt-injection boundary
    critic.py                 Critic
    hypothesis.py             HypothesisEngine (Spec 10)
    verification.py           VerificationEngine (Spec 11)
    research_memory.py        ResearchMemory
    synthesizer.py            FinalSynthesizer
    orchestrator.py           DeepResearchEngine

Most heavy modules lazily import so ``import research_engine`` remains cheap.
Small deterministic routing/guard modules may preload the planner, but perform no
network or model calls. A pure-Python domain ambiguity guard is installed
immediately because every later planner/relevance/connector caller must share
the same domain decision.

The reasoning router is also installed at package-import time, but performs NO
network call then. It simply replaces the exported ``GeminiReasoning`` class
with a backwards-compatible subclass. With no configured fallback provider it
behaves exactly like Claude's Gemini implementation; with a confirmed/free
fallback configured it can finish the same logical pass through Groq,
OpenRouter-free or local Ollama instead of returning a quota error. The
integrated facade preserves Claude's latest pass-level/API accounting even when
a fallback provider completes a pass after Gemini fails.

Retrieved/uploaded source text is untrusted data. The source prompt guard wraps
EvidencePack rendering in a strict evidence-only boundary, quotes every source
line, neutralizes instruction-like source text without deleting research
content, strips hidden bidi/control characters, and bounds hostile metadata.
"""
from __future__ import annotations

from . import domain_detection_guard as _domain_detection_guard  # noqa: F401
from . import domain_focus_guard as _domain_focus_guard  # noqa: F401

from . import gemini_reasoning as _gemini_reasoning
from .reasoning_router_integrated import ResilientReasoning as _ResilientReasoning
_gemini_reasoning.GeminiReasoning = _ResilientReasoning

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

from .source_prompt_guard import install as _install_source_prompt_guard
_install_source_prompt_guard()

from .result_coverage_gate import install as _install_result_coverage_gate
_install_result_coverage_gate()

from .depth import DepthConfig, get_depth_config, quota_note

from .controversial_texts import install as _install_controversial_text_lane
_install_controversial_text_lane()

from .safety_information_boundary import install as _install_safety_information_boundary
_install_safety_information_boundary()

from .advanced_research_quality import install as _install_advanced_research_quality
_install_advanced_research_quality()

from .advanced_semantic_coverage import install as _install_advanced_semantic_coverage
_install_advanced_semantic_coverage()

from .final_stress_hardening import install as _install_final_stress_hardening
_install_final_stress_hardening()

from .source_family_query_fairness import install as _install_source_family_query_fairness
_install_source_family_query_fairness()

from .specialist_lane_quality import install as _install_specialist_lane_quality
_install_specialist_lane_quality()

from .hypothesis_evidence_lineage import install as _install_hypothesis_evidence_lineage
_install_hypothesis_evidence_lineage()

from .causal_chain_quality import install as _install_causal_chain_quality
_install_causal_chain_quality()

# OCR/translation capture integrity is separate from A-E and can only
# downgrade/block accepted support.
from .capture_integrity_wiring import install as _install_capture_integrity_wiring
_install_capture_integrity_wiring()

# The integrated VerificationEngine uses a second A-E facade. Bind the same
# capture-integrity contract there as explicit F_capture_integrity.
from .evidence_capture_integrity import install as _install_evidence_capture_integrity
_install_evidence_capture_integrity()

from .runtime_capability_wiring import install as _install_runtime_capability_wiring
_install_runtime_capability_wiring()

# #103 is an audit-only literature debate over explicit structured
# contradictions. It never invents an opposing view from prose and can only
# expose unresolved/insufficient evidence; it never upgrades result status.
from .literature_debate_wiring import install as _install_literature_debate_wiring
_install_literature_debate_wiring()

# #62-#65 discovery frontier runs only over explicit structured gaps,
# contradictions, unexpected observations and evidence-backed mechanisms. It
# creates research candidates, never facts, and cannot upgrade result status.
from .discovery_frontier_wiring import install as _install_discovery_frontier_wiring
_install_discovery_frontier_wiring()

# #67 Neural+Symbolic audits only caller-supplied model outputs plus explicit
# propositional contracts. It never turns prose into logic, never treats model
# confidence as proof, and never upgrades truth/status.
from .neural_symbolic_wiring import install as _install_neural_symbolic_wiring
_install_neural_symbolic_wiring()

# #68 World Model executes only explicit bounded software dynamics supplied in
# a structured contract. Its rollouts/counterfactuals remain model predictions;
# they do not claim reality or close sim-to-reality by themselves.
from .world_model_wiring import install as _install_world_model_wiring
_install_world_model_wiring()

# #70 Technology Readiness evaluates explicit evidence receipts only. Feature
# names, prose and model confidence cannot manufacture maturity, certification,
# hardware observation or operational evidence.
from .technology_readiness_wiring import install as _install_technology_readiness_wiring
_install_technology_readiness_wiring()

# #104 Historical Context uses only explicit structured chronology transported
# through the existing result/coverage path. It preserves uncertain ranges,
# blocks hindsight/anachronism/impossible causal order, and never infers dates
# or historical actor knowledge from prose.
from .historical_context_wiring import install as _install_historical_context_wiring
_install_historical_context_wiring()

# #85/#95/#110/#119/#120 are explicit structured epistemic-stress contracts.
# The wrapper never infers hidden assumptions, synthetic lineage, conspiracy
# labels or falsifiers from prose; it only audits caller-supplied structures and
# can never upgrade result status/truth.
from .epistemic_stress_wiring import install as _install_epistemic_stress_wiring
_install_epistemic_stress_wiring()

# #100 Economic Reality executes only explicit structured cash-flow/scenario
# assumptions. It never guesses demand/pricing/costs from prose and never turns
# positive model economics into proof of profitability or real-world viability.
from .economic_reality_wiring import install as _install_economic_reality_wiring
_install_economic_reality_wiring()

__all__ = [
    "Claim", "ClaimType", "EvidencePack", "Passage", "ResearchResult",
    "SourceRecord", "SourceType", "label_to_claim_type",
    "DepthConfig", "get_depth_config", "quota_note",
    "CitationEngine", "EvidenceEngine", "ContradictionEngine",
    "RelevanceEngine", "DeduplicationEngine", "ResearchPlanner",
    "SourceDiscovery", "DeepResearchEngine", "AgentManager", "manager",
    "VerificationEngine", "HypothesisEngine", "ResearchMemory",
    "ScientificDiscoveryEngine", "SafeNumericExecutor",
    "ExamIntelligenceEngine", "ExamLedgerStore",
    "ReadingSessionStore", "ResumableReadingManager",
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
    "ScientificDiscoveryEngine": ".advanced_discovery",
    "SafeNumericExecutor": ".advanced_discovery",
    "ExamIntelligenceEngine": ".exam_intelligence",
    "ExamLedgerStore": ".exam_intelligence",
    "ReadingSessionStore": ".reading_sessions",
    "ResumableReadingManager": ".reading_sessions",
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
