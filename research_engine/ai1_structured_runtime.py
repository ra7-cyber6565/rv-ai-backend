"""Production wiring for AI-1 structured and specialist source families.

The core DeepResearchEngine and ordinary SourceDiscovery lanes stay intact.
AI-1 adds relevance-gated code, dissertation, official-archive and general
transcript/media lanes, then performs bounded dataset/code/documentation reads,
critical-source anatomy and multilingual original-text provenance before the
result leaves the evidence foundation.

Nothing here changes AI-2 validation semantics or promotes evidence quality.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from . import models as model_vocab
from .connectors.archive_connector import ArchiveConnector
from .connectors.code_repository_connector import CodeRepositoryConnector
from .connectors.thesis_connector import ThesisConnector
from .critical_source_anatomy import extract_critical_source_anatomy
from .multilingual_source_provenance import annotate_multilingual_provenance
from .public_documentation_reader import PublicDocumentationReader
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

_MEDIA_QUERY_CUES = (
    "podcast", "interview", "lecture", "talk", "speech", "keynote",
    "video transcript", "audio transcript", "transcript", "captions", "subtitles",
    "recorded lecture", "recorded interview", "oral history", "press conference",
)
_MEDIA_SOURCE_TYPE_CUES = {
    "media", "video", "audio", "transcript", "podcast", "interview", "lecture",
}


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


def _useful_source_types(plan: Dict) -> set[str]:
    return {
        str(item or "").strip().casefold()
        for item in ((plan or {}).get("useful_source_types") or [])
        if str(item or "").strip()
    }


def code_lane_relevant(plan: Dict, query: str) -> bool:
    """Whether public implementation evidence is relevant; routing != evidence."""
    domain = str((plan or {}).get("domain") or "").strip().casefold()
    if domain in _TECHNICAL_DOMAINS:
        return True
    useful = _useful_source_types(plan)
    if any(any(cue in item for cue in _CODE_SOURCE_TYPE_CUES) for item in useful):
        return True
    low = " ".join(str(query or "").casefold().split())
    return any(cue in low for cue in _CODE_QUERY_CUES)


def thesis_lane_relevant(plan: Dict, query: str) -> bool:
    """Use the dissertation lane only for explicit or research-heavy asks."""
    low = " ".join(str(query or "").casefold().split())
    if any(cue in low for cue in _THESIS_QUERY_CUES):
        return True
    domain = str((plan or {}).get("domain") or "").strip().casefold()
    return domain in _THESIS_DOMAINS and any(cue in low for cue in _THESIS_RESEARCH_CUES)


def archive_lane_relevant(plan: Dict, query: str) -> bool:
    """Official archive API lane is only for actual archival/declassified intent."""
    if list((plan or {}).get("official_archive_queries") or []):
        return True
    low = " ".join(str(query or "").casefold().split())
    return any(cue in low for cue in _ARCHIVE_QUERY_CUES)


def media_lane_relevant(plan: Dict, query: str) -> bool:
    """Route public transcript/caption evidence for general media-source asks."""
    useful = _useful_source_types(plan)
    if any(any(cue in item for cue in _MEDIA_SOURCE_TYPE_CUES) for item in useful):
        return True
    low = " ".join(str(query or "").casefold().split())
    return any(cue in low for cue in _MEDIA_QUERY_CUES)


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

        # The core media facade used to be reachable mainly through craft-study.
        # AI-1 needs interviews/lectures/podcasts as evidence sources too. This
        # general route remains transcript-first: the Archive connector reads a
        # public VTT/SRT when present and otherwise returns only a labelled
        # description; it never downloads or claims to hear/watch media.
        if media_lane_relevant(plan, primary):
            connector = self.media.by_name("archive_media")
            if connector is not None:
                limit = max(1, min(int(max_per_connector or 1), 2))
                tasks.append(("ai1_media_transcript",
                              self._single(connector, primary, limit)))
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


class _CapturingProcessor:
    """Proxy that exposes processed text to AI-1 without retaining it in results."""

    def __init__(self, delegate, owner):
        self._delegate = delegate
        self._owner = owner

    def process(self, *args, **kwargs):
        result = self._delegate.process(*args, **kwargs)
        if isinstance(result, dict) and result.get("ok"):
            self._owner._last_processed_text = str(result.get("text") or "")
        else:
            self._owner._last_processed_text = ""
        return result


class StructuredAwareContentFetcher(_BaseStructuredAwareContentFetcher):
    """Production readers + inspectors + anatomy + multilingual provenance."""

    def __init__(self, allow_network=None):
        super().__init__(allow_network=allow_network)
        self.structured = AI1StructuredSourceInspector(
            allow_network=self.allow_network)
        self.documentation = PublicDocumentationReader(
            allow_network=self.allow_network)
        self._last_processed_text = ""

    def _processor(self):
        # ContentFetcher.read_source() calls this polymorphically. The proxy
        # captures only the in-memory processed text long enough to build the
        # deterministic anatomy receipt; raw text is not persisted in the
        # receipt or source metadata.
        return _CapturingProcessor(super()._processor(), self)

    def read_source(self, source, question: str, budget_chars: int = 2400) -> Dict:
        self._last_processed_text = ""
        entry = super().read_source(source, question, budget_chars)
        if isinstance(entry, dict) and entry.get("ok") and self._last_processed_text:
            entry["critical_source_anatomy"] = extract_critical_source_anatomy(
                self._last_processed_text)
        self._last_processed_text = ""
        return entry

    def enrich(self, pack, max_sources: int = 3, budget_chars: int = 2400) -> Dict:
        report = super().enrich(
            pack, max_sources=max_sources, budget_chars=budget_chars)
        anatomy_by_source = {
            str(entry.get("source_id") or ""): entry.get("critical_source_anatomy")
            for entry in list(report.get("entries") or [])
            if isinstance(entry, dict) and isinstance(entry.get("critical_source_anatomy"), dict)
        }
        attached = 0
        for source in list(getattr(pack, "sources", []) or []):
            anatomy = anatomy_by_source.get(str(getattr(source, "source_id", "") or ""))
            if not anatomy:
                continue
            verdict = getattr(source, "domain_verdict", None)
            verdict = dict(verdict) if isinstance(verdict, dict) else {}
            verdict["critical_source_anatomy"] = anatomy
            source.domain_verdict = verdict
            attached += 1
        report["critical_source_anatomy"] = {
            "attached": attached,
            "raw_full_text_retained": False,
            "rule": (
                "Anatomy records explicit headings/cues only; missing cues remain UNKNOWN "
                "and anatomy completeness is not study validity or claim truth."
            ),
        }

        # Ordinary ContentFetcher intentionally avoids arbitrary HTML. AI-1's
        # documentation reader is a narrower second pass over sources that
        # already carry strong docs/manual/reference signals, with SSRF, redirect,
        # content-type and byte guards. One page is always clamped to sections.
        doc_limit = max(0, min(2, int(max_sources or 0)))
        documentation = self.documentation.enrich(pack, max_sources=doc_limit)
        report["documentation"] = documentation

        # This runs after every text transformation above so the receipt reflects
        # the actual evidence surface entering reasoning. It detects Unicode
        # scripts only, does not guess languages and never calls a search bridge a
        # translation.
        report["multilingual_provenance"] = annotate_multilingual_provenance(pack)
        return report


def configure_ai1_structured_runtime(engine):
    """Install the AI-1 source-family lanes on one DeepResearchEngine instance."""
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
    "archive_lane_relevant",
    "code_lane_relevant",
    "configure_ai1_structured_runtime",
    "media_lane_relevant",
    "register_structured_read_level",
    "thesis_lane_relevant",
]
