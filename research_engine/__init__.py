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

# Install before planner/relevance/connectors bind domain.detect. This module is
# pure Python and has no heavy dependency/network side effect.
from . import domain_detection_guard as _domain_detection_guard  # noqa: F401

# Focus guard sc-guard ke BAAD lagti hai (isliye ye sabse bahar ki parat hai):
# ek-do ittefaqiya shabd se poora multi-domain sawaal kisi ek strict field ka
# nahi ban jaata. Naapa gaya: 1617-token sawaal "economics" (strict) ban gaya
# tha aur 15 me se 13 sahi sources hard-reject ho gaye the.
from . import domain_focus_guard as _domain_focus_guard  # noqa: F401

# Preserve Claude's Gemini implementation as the primary, but let every normal
# import (including orchestrator's direct module import) see the resilient
# subclass. reasoning_router captures the original class before this assignment;
# the integrated facade then adds the latest pass-log/accounting compatibility.
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
# Every normal package import receives the same source-data trust boundary.
# Installation is deterministic and performs no network/model call.
from .source_prompt_guard import install as _install_source_prompt_guard
_install_source_prompt_guard()

# Prompt-level structured coverage is useful but not enforcement.  Install a
# final serialization gate so a long explicit outline cannot leave the engine
# as COMPLETE when one of the user's high-level requested parts is absent.
# This is delivery-only: it never upgrades evidence/truth/confidence.
from .result_coverage_gate import install as _install_result_coverage_gate
_install_result_coverage_gate()

from .depth import DepthConfig, get_depth_config, quota_note

# Relevant banned/censored/controversial books are a research lane, not a truth
# shortcut. The deterministic wrapper only adds bounded legal-access search
# directions and synthesis rules; it never marks a source verified/relevant.
from .controversial_texts import install as _install_controversial_text_lane
_install_controversial_text_lane()

# Illegal/high-risk subject matter is not blanket-hidden.  Keep contextual,
# historical, legal, defensive and harm-reduction research visible, but seal a
# deterministic prompt/output boundary against operational wrongdoing or serious
# harm.  This does not weaken authentication, network safety, source trust or
# evidence gates and performs no network/model call at install time.
from .safety_information_boundary import install as _install_safety_information_boundary
_install_safety_information_boundary()

# Stress-test hardening: long multi-domain questions get facet-wise evidence
# axes, distinctive proposition relevance, same-proposition contradiction
# checks, substantive section coverage, conservative hypothesis confidence and
# a stricter synthesis contract.  This layer is deterministic and can only
# reject/downgrade/require more evidence; it never upgrades a truth claim.
from .advanced_research_quality import install as _install_advanced_research_quality
_install_advanced_research_quality()

# Keep the legacy outline-delivery API stable while preserving PR #51's stricter
# semantic coverage as a separate evidence-first production gate. This avoids
# false 0/N coverage on fully surfaced answers without letting heading-only
# stress-test answers pass as substantively complete.
from .advanced_semantic_coverage import install as _install_advanced_semantic_coverage
_install_advanced_semantic_coverage()

# Final stress-test closure: classify specialist evidence lanes from each source
# itself (not from unrelated active facets), expose missing required source
# families, fail COMPLETE closed when evidence-first specialist lanes are empty,
# and require sensitivity/scenario analysis for explicit optimization/simulation
# models. This layer only tightens completion; it never upgrades evidence.
from .final_stress_hardening import install as _install_final_stress_hardening
_install_final_stress_hardening()

# A giant multi-profile question must not spend the bounded specialist-query
# budget only on the first profiles in the taxonomy. Rotate explicit source
# families across rounds and scope archive/book leads to the profile that asked
# for them. This is search planning only; scheduled queries never count as
# evidence until normal relevance/verification gates accept retrieved sources.
from .source_family_query_fairness import install as _install_source_family_query_fairness
_install_source_family_query_fairness()

# A searched/retrieved source is still only a candidate. Required specialist
# lanes count as covered only when their candidates pass relevance, access-depth
# and source-role qualification (plus proposition support for empirical lanes).
# Weak candidates remain visible but can only downgrade/block COMPLETE.
from .specialist_lane_quality import install as _install_specialist_lane_quality
_install_specialist_lane_quality()

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
