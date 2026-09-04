"""Production wiring for AI-1 structured and specialist source families.

This adapter stays additive: the core DeepResearchEngine and all ordinary
SourceDiscovery lanes remain intact. AI-1 adds relevance-gated public code,
dissertation and official-archive lanes, performs bounded dataset/code
inspection, and records critical full-text anatomy before contradiction analysis
and model reasoning.

Nothing here changes AI-2 validation semantics or promotes evidence quality.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from . import models as model_vocab
from .connectors.archive_connector import ArchiveConnector
from .connectors.code_repository_connector import CodeRepositoryConnector
from .connectors.thesis_connector import ThesisConnector
from .critical_source_anatomy import extract_critical_source_anatomy
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

_THESIS_QUERY_CUES = (
    "thesis", "dissertation", "doctoral", "phd", "master's thesis", "masters thesis",
    "doctoral research", "doctoral dissertation",
)
_THESIS_RESEARCH_CUES = (
    "research", "evidence", "literature", "study", "studies", "review",
    "history", "mechanism", "theory", "experiment", "empirical",
)
_THESIS_DOMAINS = {
    "superconductivity", "materials_physics", "medicine_health",
    "biology_genetics", "cs_ml", "energy_climate", "economics", "chemistry",
    "space", "engineering", "archaeology_history",
}

_ARCHIVE_QUERY_CUES = (
    "declassified", "cia document", "cia documents", "cia reading room", "foia",
    "national archives", "nara", "fbi vault", "official archive", "archival record",
    "government archive", "project stargate", "gateway process", "remote viewing",
)


def register_structured_read_level() -> None:
    """Register generic bounded-section depth in the shared read vocabulary."""
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


def thesis_lane_relevant(plan: Dict, query: str) -> bool:
    low = " ".join(str(query or "").casefold().split())
    if any(cue in low for cue in _THESIS_QUERY_CUES):
        return True
    domain = str((plan or {}).get("domain") or "").strip().casefold()
    return domain in _THESIS_DOMAINS and any(cue in low for cue in _THESIS_RESEARCH_CUES)


def archive_lane_relevant(plan: Dict, query: str) -> bool:
    if list((plan or {}).get("official_archive_queries") or []):
        return True
    low = " ".join(str(query or "").casefold().split())
    return any(cue in low for cue in _ARCHIVE_QUERY_CUES)


class AI1StructuredSourceDiscovery(SourceDiscovery):
    """Ordinary discovery plus bounded, auditable AI-1 family lanes."""

    def __init__(self, max_workers: int = 6):
        super().__init__(max_workers=max_workers)
        self.code_repositories = CodeRepositoryConnector()
        self.theses = ThesisConnector()
        self.archives = ArchiveConnector()

    def _tasks(self, queries: List[str], plan: Dict, max_per_connector: int,
               max_web: int) -> List[Tuple[str, object]]:
        tasks = list(super()._tasks(queries, plan, max_per_connector, max_web))
        primary = str(queries[0] if queries else "").strip()
        if not primary:
            return tasks

        if code_lane_relevant(plan, primary):
            connector = self.code_repositories.by_name("github_code")
            if connector is not None:
                limit = max(1, min(int(max_per_connector or 1), 3))
                tasks.append((connector.name, self._single(connector, primary, limit)))

        if thesis_lane_relevant(plan, primary):
            connector = self.theses.by_name("crossref_dissertation")
            if connector is not None:
                limit = max(1, min(int(max_per_connector or 1), 3))
                tasks.append((connector.name, self._single(connector, primary, limit)))

        if archive_lane_relevant(plan, primary):
            connector = self.archives.by_name("nara_archive")
            if connector is not None:
                archive_queries = [
                    str(item or "").strip()
                    for item in list((plan or {}).get("official_archive_queries") or [])
                    if str(item or "").strip()
                ]
                archive_query = archive_queries[0] if archive_queries else primary
                limit = max(1, min(int(max_per_connector or 1), 3))
                tasks.append((connector.name,
                              self._single(connector, archive_query, limit)))
        return tasks


class AI1StructuredSourceInspector(StructuredSourceInspector):
    """Structured inspector with a hard section-depth clamp after success."""

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
            source.read_level = "sections"
            source.full_text_available = False
            source.full_text_chars = 0
            for passage in list(getattr(pack, "passages", []) or []):
                if passage.source_id == source.source_id:
                    passage.read_level_at_capture = "sections"
        return report


class StructuredAwareContentFetcher(_BaseStructuredAwareContentFetcher):
    """Full-text reader + anatomy receipt + bounded structured reader."""

    def __init__(self, allow_network=None):
        super().__init__(allow_network=allow_network)
        self.structured = AI1StructuredSourceInspector(
            allow_network=self.allow_network)

    @classmethod
    def signals_from_text(cls, text: str) -> Dict:
        signals = dict(super().signals_from_text(text))
        signals["critical_source_anatomy"] = extract_critical_source_anatomy(text)
        return signals

    def enrich(self, pack, max_sources: int = 3,
               budget_chars: int = 2400) -> Dict:
        report = super().enrich(
            pack, max_sources=max_sources, budget_chars=budget_chars)
        anatomy_count = 0
        complete_count = 0
        for entry in list(report.get("entries") or []):
            if not isinstance(entry, dict) or not entry.get("ok"):
                continue
            anatomy = ((entry.get("signals") or {}).get("critical_source_anatomy")
                       if isinstance(entry.get("signals"), dict) else None)
            if not isinstance(anatomy, dict) or not anatomy.get("ran"):
                continue
            source = pack.by_id(str(entry.get("source_id") or ""))
            if source is None:
                continue
            verdict = dict(getattr(source, "domain_verdict", {}) or {})
            verdict["critical_source_anatomy"] = anatomy
            source.domain_verdict = verdict
            anatomy_count += 1
            complete_count += int(anatomy.get("complete") is True)
        report["critical_source_anatomy"] = {
            "sources_analyzed": anatomy_count,
            "complete_anatomy": complete_count,
            "rule": (
                "full-text access does not imply methods/sample/assumptions/findings/"
                "limitations/replication were all exposed; missing fields stay UNKNOWN"
            ),
        }
        return report


def configure_ai1_structured_runtime(engine):
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
    "AI1StructuredSourceDiscovery", "AI1StructuredSourceInspector",
    "StructuredAwareContentFetcher", "archive_lane_relevant", "code_lane_relevant",
    "configure_ai1_structured_runtime", "register_structured_read_level",
    "thesis_lane_relevant",
]
