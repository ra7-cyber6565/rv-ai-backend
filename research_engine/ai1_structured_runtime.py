"""Production wiring for AI-1 structured source discovery and reading.

This adapter is intentionally narrow and additive:

* the existing DeepResearchEngine stays the orchestrator;
* the ordinary SourceDiscovery lanes still run unchanged;
* a public GitHub code-repository lane is added only when the runtime plan/query
  is technically relevant;
* the ordinary ContentFetcher still performs legal document/full-text reading;
* bounded dataset/code inspection runs immediately afterwards, before the core
  engine reaches contradiction detection and model reasoning.

Nothing in this module changes AI-2 validation.  It only makes AI-1's evidence
foundation richer while preserving the same fail-closed truth boundaries.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from . import models as model_vocab
from .connectors.code_repository_connector import CodeRepositoryConnector
from .source_discovery import SourceDiscovery
from .structured_source_reader import (
    StructuredAwareContentFetcher as _BaseStructuredAwareContentFetcher,
    StructuredSourceInspector,
)


_TECHNICAL_DOMAINS = {"cs_ml", "engineering"}
_CODE_QUERY_CUES = (
    "source code", "codebase", "repository", "repo ", "github", "gitlab",
    "implementation", "programming", "software library", "python package",
    "javascript package", "typescript", "algorithm implementation",
)
_CODE_SOURCE_TYPE_CUES = {"code", "repository", "software", "implementation"}


def register_structured_read_level() -> None:
    """Register generic bounded-section depth in the shared read vocabulary.

    ``sections`` existed in AI-1's deep-source auditor before it existed in the
    older SourceRecord display vocabulary.  Registering it here keeps all
    production views aligned: SourceRecord.access_depth(), EvidencePack read
    counts, prompt labels and AI-1 deep-source audit now describe a bounded
    dataset/code read the same way.  This is an access-depth label only; it does
    not promote any claim or change evidence quality.
    """
    order = model_vocab.READ_LEVEL_ORDER
    if "sections" not in order:
        try:
            index = order.index("claims")
        except ValueError:
            index = max(0, len(order) - 1)
        order.insert(index, "sections")
    model_vocab.READ_LEVEL_LABELS.setdefault(
        "sections", "relevant sections / bounded structured subset")
    model_vocab.ACCESS_DEPTH_LABELS["sections"] = model_vocab.ACCESS_SECTIONS


register_structured_read_level()


def code_lane_relevant(plan: Dict, query: str) -> bool:
    """Deterministically decide whether public implementation evidence helps.

    This is a routing decision, never evidence.  A positive result only permits
    GitHub repository discovery; it does not imply that a repository exists or
    that any code was inspected.
    """
    domain = str((plan or {}).get("domain") or "").strip().casefold()
    if domain in _TECHNICAL_DOMAINS:
        return True

    useful = {
        str(item or "").strip().casefold()
        for item in ((plan or {}).get("useful_source_types") or [])
        if str(item or "").strip()
    }
    if any(any(cue in item for cue in _CODE_SOURCE_TYPE_CUES) for item in useful):
        return True

    low = " ".join(str(query or "").casefold().split())
    return any(cue in low for cue in _CODE_QUERY_CUES)


class AI1StructuredSourceDiscovery(SourceDiscovery):
    """Existing discovery plus a bounded, relevance-gated public code lane."""

    def __init__(self, max_workers: int = 6):
        super().__init__(max_workers=max_workers)
        self.code_repositories = CodeRepositoryConnector()

    def _tasks(self, queries: List[str], plan: Dict, max_per_connector: int,
               max_web: int) -> List[Tuple[str, object]]:
        tasks = list(super()._tasks(queries, plan, max_per_connector, max_web))
        primary = str(queries[0] if queries else "").strip()
        if not primary or not code_lane_relevant(plan, primary):
            return tasks

        connector = self.code_repositories.by_name("github_code")
        if connector is None:
            return tasks

        # One bounded task per round.  Unlike paper lanes, we do not fan the
        # repository API out over every query because public GitHub search is
        # rate-limited and the structured reader later makes additional bounded
        # tree/file calls for repositories that survive ranking.
        limit = max(1, min(int(max_per_connector or 1), 3))
        tasks.append((connector.name, self._single(connector, primary, limit)))
        return tasks


class AI1StructuredSourceInspector(StructuredSourceInspector):
    """Structured inspector with a hard access-depth clamp after success.

    A provider series may arrive marked ``full_text`` because the complete
    provider response was read.  Once AI-1 turns that source into a bounded row
    sample/profile, however, the evidence surface used for reasoning is a
    *subset*.  Likewise selected repository files are never a whole-repository
    read.  The postcondition below prevents an inherited full-text marker from
    silently surviving that transformation.
    """

    def enrich(self, pack, *, max_sources: int = 3,
               budget_chars: int = 2400) -> Dict:
        report = super().enrich(
            pack, max_sources=max_sources, budget_chars=budget_chars)
        for source in list(getattr(pack, "sources", []) or []):
            dataset = getattr(source, "dataset_inspection", None)
            code = getattr(source, "code_inspection", None)
            if not dataset and not code:
                continue
            prior_chars = int(getattr(source, "full_text_chars", 0) or 0)
            if dataset and prior_chars:
                dataset.setdefault(
                    "non_structured_text_chars_before_inspection", prior_chars)
            if code and prior_chars:
                code.setdefault(
                    "non_structured_text_chars_before_inspection", prior_chars)

            # These records now represent the bounded structured evidence that
            # actually enters reasoning, not a whole dataset/repository.
            source.read_level = "sections"
            source.full_text_available = False
            source.full_text_chars = 0

            for passage in list(getattr(pack, "passages", []) or []):
                if passage.source_id == source.source_id:
                    passage.read_level_at_capture = "sections"
        return report


class StructuredAwareContentFetcher(_BaseStructuredAwareContentFetcher):
    """Production full-text reader followed by AI-1's clamped inspector."""

    def __init__(self, allow_network=None):
        super().__init__(allow_network=allow_network)
        self.structured = AI1StructuredSourceInspector(
            allow_network=self.allow_network)


def configure_ai1_structured_runtime(engine):
    """Install the AI-1 structured lanes on one DeepResearchEngine instance."""
    register_structured_read_level()
    discovery = getattr(engine, "discovery", None)
    if not isinstance(discovery, AI1StructuredSourceDiscovery):
        workers = int(getattr(discovery, "max_workers", 6) or 6)
        engine.discovery = AI1StructuredSourceDiscovery(max_workers=workers)

    reader = getattr(engine, "reader", None)
    if not isinstance(reader, StructuredAwareContentFetcher):
        allow_network = getattr(reader, "allow_network", None)
        engine.reader = StructuredAwareContentFetcher(allow_network=allow_network)
    return engine


__all__ = [
    "AI1StructuredSourceDiscovery",
    "AI1StructuredSourceInspector",
    "StructuredAwareContentFetcher",
    "code_lane_relevant",
    "configure_ai1_structured_runtime",
    "register_structured_read_level",
]
