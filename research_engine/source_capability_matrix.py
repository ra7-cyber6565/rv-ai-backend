"""Machine-verifiable source-family capability matrix for AI-1.

The purpose is to prevent architecture theatre: an enum, planner keyword or
integrity warning does not count as a working source capability. Each family is
split into discovery, actual reading/inspection, provenance/locator proof and a
hard limitation. Runtime evidence then shows which implemented paths were
actually exercised in a given research run.

v1.2 hardens the runtime receipt layer itself:
- every declared family must have an explicit runtime classifier;
- generic Archive.org media must not masquerade as an official archive;
- a generic lecture/transcript must not masquerade as a podcast/user-audio run;
- PDF/large-document and historical-primary-text families can actually record
  per-run exercise instead of staying permanently false;
- matrix validity now includes row-contract + classifier coverage, not imports
  alone.
"""
from __future__ import annotations

import importlib.util
from typing import Callable, Dict, List, Mapping, Sequence
from urllib.parse import urlsplit

SCHEMA_VERSION = "ai1-source-capability-matrix-1.2"

DEEP_RUNTIME = "DEEP_RUNTIME"
BOUNDED_RUNTIME = "BOUNDED_RUNTIME"
CONDITIONAL_RUNTIME = "CONDITIONAL_RUNTIME"
DISCOVERY_ONLY = "DISCOVERY_ONLY"
SEARCH_BRIDGE = "SEARCH_BRIDGE"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

_IMPLEMENTATION_STATUSES = {
    DEEP_RUNTIME, BOUNDED_RUNTIME, CONDITIONAL_RUNTIME,
    DISCOVERY_ONLY, SEARCH_BRIDGE, NOT_IMPLEMENTED,
}
_DEEP_LEVELS = {"sections", "claims", "full_text"}

_OFFICIAL_ARCHIVE_HOSTS = {
    "archives.gov",
    "catalog.archives.gov",
    "cia.gov",
    "www.cia.gov",
    "fbi.gov",
    "www.fbi.gov",
    "govinfo.gov",
    "www.govinfo.gov",
    "nsa.gov",
    "www.nsa.gov",
}
_PODCAST_CUES = (
    "podcast", "episode", "rss audio", "audio episode", "podcast transcript",
)
_LOCAL_STT_CUES = (
    "auto-transcrib", "machine transcription", "speech-to-text", "faster-whisper",
    "openai-whisper", "whisper", "audio locally transcribe", "local transcription",
)


def _module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _row(family: str, *, discovery: Sequence[str], reader: Sequence[str],
         provenance: Sequence[str], implementation_status: str,
         limitation: str, condition: str = "", truth_boundary: str = "") -> Dict:
    return {
        "source_family": family,
        "discovery_path": list(discovery),
        "read_or_inspection_path": list(reader),
        "provenance_or_locator_proof": list(provenance),
        "implementation_status": implementation_status,
        "condition": condition,
        "limitation": limitation,
        "truth_boundary": truth_boundary,
    }


def implementation_matrix() -> List[Dict]:
    """Static implementation contract; no network call and no source claims."""
    return [
        _row(
            "research_papers",
            discovery=["OpenAlex", "arXiv", "Crossref", "DOAJ", "PubMed", "Semantic Scholar"],
            reader=["ContentFetcher: arXiv OA PDF / Europe PMC OA / direct open PDF"],
            provenance=["source_id", "DOI/URL", "page/section locator", "Passage provenance"],
            implementation_status=DEEP_RUNTIME,
            limitation="Paywalled/ToS-restricted full text remains abstract/metadata only.",
            truth_boundary="paper access != claim truth; methodology/entailment gates still apply",
        ),
        _row(
            "pdfs_and_large_documents",
            discovery=["paper/book/web/document routes"],
            reader=["DocumentProcessor", "PDFProcessor", "page-by-page large-PDF sampling", "OCR fallback"],
            provenance=["pages_read/pages_total", "page locator", "read_note"],
            implementation_status=DEEP_RUNTIME,
            limitation="Large documents may be relevant-section reads rather than whole-document reads.",
            truth_boundary="partial pages are RELEVANT SECTIONS REVIEWED, never FULL TEXT ACCESSED",
        ),
        _row(
            "books_and_chapters",
            discovery=["Internet Archive", "Open Library", "Google Books metadata", "Wikisource classic lane"],
            reader=["Internet Archive public djvu text", "Project Gutenberg", "Wikisource/Wikibooks plaintext"],
            provenance=["edition/source URL", "text excerpt locator", "copyright stance"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="deep reading only when legally/publicly accessible",
            limitation="Copyright-likely books stay summary/metadata lane; no paywall bypass.",
            truth_boundary="book metadata/summary != original book text",
        ),
        _row(
            "theses_and_dissertations",
            discovery=["Crossref type-specific dissertation lane"],
            reader=["ordinary ContentFetcher when an explicitly open-licensed PDF is exposed"],
            provenance=["DOI", "institution", "thesis doc_kind", "open-licence gate"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="open PDF must be explicitly licensed and pass ContentFetcher safety",
            limitation="Crossref metadata/abstract alone is not thesis-body reading.",
            truth_boundary="dissertation metadata != dissertation body",
        ),
        _row(
            "patents",
            discovery=["EPO linked open data", "optional USPTO ODP"],
            reader=["PatentMeta abstract/claims/description depth"],
            provenance=["patent number", "jurisdiction", "family key", "claim count/read depth"],
            implementation_status=BOUNDED_RUNTIME,
            limitation="Provider may expose only metadata/abstract; legal status coverage is incomplete.",
            truth_boundary="patent claims are legal claims, not scientific proof",
        ),
        _row(
            "datasets_and_time_series",
            discovery=["Zenodo", "data.gov", "WHO GHO", "World Bank", "Hugging Face", "data.gov.in", "market series providers"],
            reader=["StructuredSourceInspector CSV/TSV/JSON/JSONL", "series_meta row inspection"],
            provenance=["rows_inspected", "columns/schema", "sample rows", "numeric profile", "source locator"],
            implementation_status=BOUNDED_RUNTIME,
            limitation="Bounded samples/profiles do not validate the complete dataset or causality.",
            truth_boundary="dataset landing metadata != inspected rows; sample != whole dataset",
        ),
        _row(
            "documentation_manuals_technical_notes",
            discovery=["web search", "official/specialist web queries", "direct document links"],
            reader=[
                "direct open PDF/uploaded-document readers",
                "PublicDocumentationReader bounded public HTML page inspection",
            ],
            provenance=[
                "requested/final URL", "bytes read", "parsed/selected blocks",
                "documentation page locator", "public_documentation_page_excerpt Passage provenance",
            ],
            implementation_status=BOUNDED_RUNTIME,
            condition="HTML page must be public, SSRF-safe, redirect-safe and docs/manual/reference-like",
            limitation="Only selected public pages are read; authentication/paywalls and whole-site crawling are not attempted.",
            truth_boundary="one documentation page != whole manual/site; docs text != runtime correctness proof",
        ),
        _row(
            "code_repositories",
            discovery=["public GitHub repository search"],
            reader=["bounded GitHub tree/file inspector"],
            provenance=["repository", "tree identity", "file path", "line range"],
            implementation_status=BOUNDED_RUNTIME,
            limitation="Selected files do not represent the whole repository and code is not executed.",
            truth_boundary="README/repo metadata != code inspection; code read != tests run",
        ),
        _row(
            "video_audio_transcripts_interviews_lectures",
            discovery=["general AI-1 media-intent route", "Internet Archive media search"],
            reader=["public VTT/SRT caption reader", "TranscriptProcessor"],
            provenance=["timestamp locator", "caption source URL", "transcript read note"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="public captions/transcript must exist",
            limitation="No visual-frame or audio-signal analysis is claimed from transcript text.",
            truth_boundary="description != transcript; transcript != watched/listened AV analysis",
        ),
        _row(
            "podcasts_and_user_audio",
            discovery=["general podcast/interview transcript route", "user-provided file"],
            reader=["public caption/transcript when exposed", "optional local faster-whisper/openai-whisper STT", "TranscriptProcessor"],
            provenance=["machine-transcription disclaimer", "timestamp blocks", "backend/model note"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="remote source needs public transcript/captions; raw user audio needs optional local STT backend",
            limitation="Remote raw media is not downloaded merely to create a transcript; machine transcription can be wrong.",
            truth_boundary="transcription quality != spoken claim truth",
        ),
        _row(
            "official_archives_and_declassified_records",
            discovery=["official archive web queries", "NARA Catalog API v2"],
            reader=["NARA API-exposed OCR/extracted/transcription text"],
            provenance=["NAID", "official catalog URL", "transformation method/read note"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="NARA_CATALOG_API_KEY/CATALOG_API_KEY required for NARA API lane",
            limitation="Catalog description without extracted/transcribed body remains shallow.",
            truth_boundary="official archive provenance/release != truth of claims inside document",
        ),
        _row(
            "historical_primary_texts",
            discovery=["Wikisource multilingual classic lane", "Internet Archive/Open Library catalogue"],
            reader=["Wikisource public-domain plaintext", "Internet Archive public text", "Project Gutenberg"],
            provenance=["work/edition URL", "language/project", "excerpt locator"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="public-domain/open text required",
            limitation="Historical text establishes what was written, not modern empirical truth.",
            truth_boundary="historical primary source != present-day scientific validation",
        ),
        _row(
            "multilingual_sources",
            discovery=["script-aware lang_bridge", "Wikipedia langlinks", "multilingual search plan"],
            reader=["Unicode original text through document/PDF/transcript/documentation readers"],
            provenance=[
                "multilingual_source_provenance receipt", "observed scripts/script counts",
                "original_text_preserved flag", "translation verification state",
            ],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="original-language text must be legally/readably accessible; verified translation is a separate optional transformation",
            limitation="Script detection does not infer language and the search/transliteration bridge is not a translation engine.",
            truth_boundary="original multilingual text read != translation; claimed translation still requires provenance/review",
        ),
        _row(
            "ocr_scanned_documents",
            discovery=["document/PDF routes"],
            reader=["OCRProcessor fallback"],
            provenance=["OCR integrity/quality/review markers when exposed"],
            implementation_status=CONDITIONAL_RUNTIME,
            condition="OCR dependencies/image quality must permit extraction",
            limitation="Low/uncertain OCR requires review against source image.",
            truth_boundary="OCR capture quality != claim truth",
        ),
    ]


def _runtime_sources(result: Mapping) -> List[Mapping]:
    out: List[Mapping] = []
    seen = set()
    for bucket in ("sources", "citations", "uncited_sources"):
        for raw in result.get(bucket) or []:
            if not isinstance(raw, Mapping):
                continue
            key = str(raw.get("source_id") or raw.get("url") or raw.get("title") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(raw)
    return out


def _verdict_map(source: Mapping) -> Dict:
    value = source.get("domain_verdict")
    return dict(value) if isinstance(value, Mapping) else {}


def _host(source: Mapping) -> str:
    try:
        return (urlsplit(str(source.get("url") or "")).hostname or "").rstrip(".").casefold()
    except ValueError:
        return ""


def _text_surface(source: Mapping) -> str:
    return " ".join(
        str(source.get(key) or "")
        for key in ("title", "doc_kind", "doc_kind_label", "snippet", "read_note", "connector")
    ).casefold()


def _reading_level(source: Mapping) -> str:
    return str(source.get("reading_level") or source.get("read_level") or "").casefold()


def _match_research_paper(source: Mapping) -> bool:
    return str(source.get("source_type") or "").casefold() == "paper"


def _match_pdf_or_large_document(source: Mapping) -> bool:
    source_type = str(source.get("source_type") or "").casefold()
    url = str(source.get("url") or "").casefold().split("?", 1)[0].split("#", 1)[0]
    return (
        source_type == "document"
        or url.endswith(".pdf")
        or int(source.get("pages_total") or 0) > 0
        or int(source.get("pages_read") or 0) > 0
    )


def _match_book(source: Mapping) -> bool:
    connector = str(source.get("connector") or "").casefold()
    kind = str(source.get("doc_kind") or "").casefold()
    source_type = str(source.get("source_type") or "").casefold()
    return (
        source_type == "book"
        or "book" in kind
        or "chapter" in kind
        or connector in {"internet_archive", "open_library", "google_books"}
        or connector.startswith("wikisource")
    )


def _match_thesis(source: Mapping) -> bool:
    connector = str(source.get("connector") or "").casefold()
    kind = str(source.get("doc_kind") or "").casefold()
    return connector == "crossref_dissertation" or "thesis" in kind or "dissertation" in kind


def _match_patent(source: Mapping) -> bool:
    return str(source.get("source_type") or "").casefold() == "patent"


def _match_dataset(source: Mapping) -> bool:
    return (
        str(source.get("source_type") or "").casefold() == "dataset"
        or isinstance(source.get("dataset_inspection"), Mapping)
        or isinstance(source.get("series_meta"), Mapping)
    )


def _match_documentation(source: Mapping) -> bool:
    return isinstance(_verdict_map(source).get("documentation_inspection"), Mapping)


def _match_code(source: Mapping) -> bool:
    connector = str(source.get("connector") or "").casefold()
    kind = str(source.get("doc_kind") or "").casefold()
    return (
        connector == "github_code"
        or "code_repository" in kind
        or isinstance(source.get("code_inspection"), Mapping)
    )


def _match_media_transcript(source: Mapping) -> bool:
    return (
        str(source.get("connector") or "").casefold() == "archive_media"
        or str(source.get("source_type") or "").casefold() == "transcript"
    )


def _match_podcast_or_user_audio(source: Mapping) -> bool:
    text = _text_surface(source)
    connector = str(source.get("connector") or "").casefold()
    if connector in {"user_audio", "uploaded_audio", "audio_upload", "speech_to_text"}:
        return True
    if any(cue in text for cue in _LOCAL_STT_CUES):
        return True
    return any(cue in text for cue in _PODCAST_CUES)


def _match_official_archive(source: Mapping) -> bool:
    connector = str(source.get("connector") or "").casefold()
    host = _host(source)
    return connector == "nara_archive" or host in _OFFICIAL_ARCHIVE_HOSTS


def _match_historical_primary_text(source: Mapping) -> bool:
    connector = str(source.get("connector") or "").casefold()
    host = _host(source)
    kind = str(source.get("doc_kind") or "").casefold()
    return (
        connector.startswith("wikisource")
        or host.endswith("wikisource.org")
        or host.endswith("gutenberg.org")
        or "historical_primary" in kind
        or "primary_text" in kind
    )


def _match_multilingual(source: Mapping) -> bool:
    receipt = _verdict_map(source).get("multilingual_source_provenance")
    return isinstance(receipt, Mapping) and bool(receipt.get("text_observed"))


def _match_ocr(source: Mapping) -> bool:
    return bool(source.get("extraction_integrity")) or "ocr" in str(source.get("read_note") or "").casefold()


_RUNTIME_CLASSIFIERS: Dict[str, Callable[[Mapping], bool]] = {
    "research_papers": _match_research_paper,
    "pdfs_and_large_documents": _match_pdf_or_large_document,
    "books_and_chapters": _match_book,
    "theses_and_dissertations": _match_thesis,
    "patents": _match_patent,
    "datasets_and_time_series": _match_dataset,
    "documentation_manuals_technical_notes": _match_documentation,
    "code_repositories": _match_code,
    "video_audio_transcripts_interviews_lectures": _match_media_transcript,
    "podcasts_and_user_audio": _match_podcast_or_user_audio,
    "official_archives_and_declassified_records": _match_official_archive,
    "historical_primary_texts": _match_historical_primary_text,
    "multilingual_sources": _match_multilingual,
    "ocr_scanned_documents": _match_ocr,
}


def _family_exercised(row: Mapping, sources: Sequence[Mapping]) -> Dict:
    family = str(row.get("source_family") or "")
    matcher = _RUNTIME_CLASSIFIERS.get(family)
    if matcher is None:
        return {
            "exercised_source_ids": [],
            "deep_exercised_count": 0,
            "exercised": False,
            "classifier_supported": False,
        }

    matched: List[str] = []
    deep = 0
    for source in sources:
        try:
            hit = bool(matcher(source))
        except (TypeError, ValueError):
            hit = False
        if not hit:
            continue
        sid = str(source.get("source_id") or source.get("title") or "")
        if sid:
            matched.append(sid)
        if _reading_level(source) in _DEEP_LEVELS:
            deep += 1
    return {
        "exercised_source_ids": matched[:20],
        "deep_exercised_count": deep,
        "exercised": bool(matched),
        "classifier_supported": True,
    }


def _matrix_contract_errors(rows: Sequence[Mapping]) -> List[str]:
    errors: List[str] = []
    seen = set()
    for index, row in enumerate(rows):
        family = str(row.get("source_family") or "").strip()
        prefix = family or f"row[{index}]"
        if not family:
            errors.append(f"{prefix}: source_family missing")
            continue
        if family in seen:
            errors.append(f"{family}: duplicate source_family")
        seen.add(family)
        if not row.get("discovery_path"):
            errors.append(f"{family}: discovery_path missing")
        if not row.get("read_or_inspection_path"):
            errors.append(f"{family}: read_or_inspection_path missing")
        if not row.get("provenance_or_locator_proof"):
            errors.append(f"{family}: provenance_or_locator_proof missing")
        if str(row.get("implementation_status") or "") not in _IMPLEMENTATION_STATUSES:
            errors.append(f"{family}: implementation_status invalid")
        if not str(row.get("limitation") or "").strip():
            errors.append(f"{family}: limitation missing")
        if not str(row.get("truth_boundary") or "").strip():
            errors.append(f"{family}: truth_boundary missing")
        if family not in _RUNTIME_CLASSIFIERS:
            errors.append(f"{family}: runtime classifier missing")
    extra = sorted(set(_RUNTIME_CLASSIFIERS) - seen)
    for family in extra:
        errors.append(f"{family}: classifier has no declared family row")
    return errors


def build_source_capability_matrix(result: Mapping | None = None) -> Dict:
    rows = implementation_matrix()
    sources = _runtime_sources(result or {})
    for row in rows:
        row["runtime"] = _family_exercised(row, sources)

    import_proof = {
        "ai1_structured_runtime": _module("research_engine.ai1_structured_runtime"),
        "structured_source_reader": _module("research_engine.structured_source_reader"),
        "public_documentation_reader": _module("research_engine.public_documentation_reader"),
        "multilingual_source_provenance": _module("research_engine.multilingual_source_provenance"),
        "thesis_connector": _module("research_engine.connectors.thesis_connector"),
        "archive_connector": _module("research_engine.connectors.archive_connector"),
        "code_repository_connector": _module("research_engine.connectors.code_repository_connector"),
        "critical_source_anatomy": _module("research_engine.critical_source_anatomy"),
        "media_connector": _module("research_engine.connectors.media_connector"),
        "transcript_processor": _module("research_engine.processing.transcript_processor"),
        "speech_to_text": _module("research_engine.processing.speech_to_text"),
        "ocr_processor": _module("research_engine.processing.ocr_processor"),
        "lang_bridge": _module("research_engine.lang_bridge"),
    }
    missing_modules = [name for name, ok in import_proof.items() if not ok]
    contract_errors = _matrix_contract_errors(rows)
    unclassified = [
        str(row.get("source_family") or "")
        for row in rows
        if not bool((row.get("runtime") or {}).get("classifier_supported"))
    ]
    counts: Dict[str, int] = {}
    for row in rows:
        status = str(row["implementation_status"])
        counts[status] = counts.get(status, 0) + 1

    validation_errors = [
        *(f"missing module: {name}" for name in missing_modules),
        *contract_errors,
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "families": rows,
        "family_count": len(rows),
        "implementation_status_counts": counts,
        "module_import_proof": import_proof,
        "missing_required_modules": missing_modules,
        "runtime_classifier_count": len(_RUNTIME_CLASSIFIERS),
        "unclassified_families": unclassified,
        "contract_errors": contract_errors,
        "validation_errors": validation_errors,
        "valid": not validation_errors and not unclassified,
        "completion_rule": (
            "A family is never called deep merely because it is planned/classified. "
            "Deep/bounded status requires a real reader/inspector plus provenance; "
            "every declared family must also have an explicit runtime classifier, "
            "and per-run exercise remains separate from implementation availability."
        ),
        "absolute_scope_disclaimer": (
            "This matrix proves implemented legal/public/user-provided paths, not access "
            "to the entire internet, every paywalled source, or every media object."
        ),
    }


__all__ = [
    "BOUNDED_RUNTIME", "CONDITIONAL_RUNTIME", "DEEP_RUNTIME", "DISCOVERY_ONLY",
    "NOT_IMPLEMENTED", "SCHEMA_VERSION", "SEARCH_BRIDGE",
    "build_source_capability_matrix", "implementation_matrix",
]
