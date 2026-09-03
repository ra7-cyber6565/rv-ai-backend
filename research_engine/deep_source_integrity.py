"""Fail-closed source-family depth/provenance audit for AI-1.

The research engine already distinguishes metadata, snippets, abstracts,
sections and full text.  This module adds the missing *source-family proof*
layer: a dataset landing page is not inspected data, a repository README is not
code inspection, a media description is not a transcript, patent metadata is
not claims text, and a translated/OCR passage is not automatically trustworthy
just because capture succeeded.

The module is deterministic and provider-free.  It only audits fields already
present in a research result and therefore cannot invent a read, transcript,
dataset inspection, code review, language or translation verification event.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Mapping, Sequence

FULL_TEXT_REQUIRED = "FULL TEXT REQUIRED"
TRANSCRIPT_REQUIRED = "TRANSCRIPT REQUIRED"
DATA_INSPECTION_REQUIRED = "DATA INSPECTION REQUIRED"
CODE_INSPECTION_REQUIRED = "CODE INSPECTION REQUIRED"
PATENT_CLAIMS_REQUIRED = "PATENT CLAIMS REQUIRED"
ARCHIVE_BODY_REQUIRED = "ARCHIVE BODY REQUIRED"
TRANSLATION_REVIEW_REQUIRED = "TRANSLATION REVIEW REQUIRED"
OCR_REVIEW_REQUIRED = "OCR REVIEW REQUIRED"
PROVENANCE_REQUIRED = "PROVENANCE REQUIRED"

DEEP_ACCESS = {"FULL TEXT ACCESSED", "RELEVANT SECTIONS REVIEWED"}
SHALLOW_ACCESS = {"METADATA ONLY", "SNIPPET ONLY", "ABSTRACT ONLY"}

_TIMESTAMP = re.compile(r"(?:^|\s)(?:\d{1,3}:)?[0-5]?\d:[0-5]\d(?:\s|$|[-–—])")
_CODE_HOSTS = ("github.com", "gitlab.com", "codeberg.org", "bitbucket.org")
_ARCHIVE_HOSTS = ("archive.org", "archives.gov", "cia.gov", "fbi.gov", "govinfo.gov")


def _dict(value: object) -> Dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: object) -> List:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def access_depth(source: Mapping) -> str:
    """Return text-access depth without ever upgrading a partial-page read."""
    explicit = _text(source.get("access_depth") or source.get("access_label"), 80).upper()
    if explicit:
        return explicit
    level = _text(source.get("read_level") or source.get("reading_level"), 40).casefold()
    pages_read = _int(source.get("pages_read"))
    pages_total = _int(source.get("pages_total"))
    if pages_total and pages_read and pages_read < pages_total:
        return "RELEVANT SECTIONS REVIEWED"
    if level in {"sections", "claims"}:
        return "RELEVANT SECTIONS REVIEWED"
    if level == "full_text":
        return "FULL TEXT ACCESSED"
    if level == "abstract":
        return "ABSTRACT ONLY"
    if level == "snippet" or source.get("snippet"):
        return "SNIPPET ONLY"
    if source:
        return "METADATA ONLY"
    return "UNKNOWN"


def _source_type(source: Mapping) -> str:
    value = source.get("source_type") or source.get("type") or ""
    if isinstance(value, Mapping):
        value = value.get("value")
    return _text(value, 80).casefold()


def source_family(source: Mapping) -> str:
    """Classify by runtime metadata only; title heuristics never imply a read."""
    kind = _source_type(source)
    doc_kind = _text(source.get("doc_kind"), 100).casefold()
    connector = _text(source.get("connector"), 100).casefold()
    title = _text(source.get("title"), 260).casefold()
    url = _text(source.get("url"), 500).casefold()
    blob = " ".join((kind, doc_kind, connector, title, url))

    if kind == "patent" or "patent" in doc_kind or "patent" in connector:
        return "patent"
    if kind == "dataset" or "dataset" in doc_kind or "dataset" in connector:
        return "dataset"
    if any(host in url for host in _CODE_HOSTS) or any(
        marker in blob for marker in ("repository", "source code", "code_repo", "github")
    ):
        return "code_repository"
    if kind == "transcript":
        if connector == "archive_media" and access_depth(source) in SHALLOW_ACCESS:
            return "media_recording"
        return "media_transcript"
    if any(marker in blob for marker in ("thesis", "dissertation")):
        return "thesis_dissertation"
    if kind == "book" or any(marker in doc_kind for marker in ("book", "chapter", "monograph")):
        return "book_chapter"
    if kind == "paper" or any(marker in doc_kind for marker in (
        "article", "preprint", "review", "paper", "conference"
    )):
        return "paper"
    if kind == "document":
        return "uploaded_document"
    if any(host in url for host in _ARCHIVE_HOSTS) or "archive" in connector:
        return "archive_document"
    if kind in {"web", "encyclopedia"}:
        return "web_document"
    return "unknown"


def _has_structured_dataset_inspection(source: Mapping) -> bool:
    for key in ("series_meta", "dataset_inspection", "dataset_profile", "data_profile"):
        value = source.get(key)
        if isinstance(value, Mapping) and value:
            return True
    for key in ("rows_inspected", "data_rows", "observations", "sample_rows"):
        value = source.get(key)
        if isinstance(value, (list, tuple)) and len(value) > 0:
            return True
        if key == "rows_inspected" and _int(value) > 0:
            return True
    return False


def _has_code_inspection(source: Mapping) -> bool:
    if source.get("code_inspected") is True:
        return True
    for key in ("code_inspection", "repository_analysis"):
        value = source.get(key)
        if isinstance(value, Mapping) and value:
            return True
    for key in ("files_inspected", "code_files"):
        value = source.get(key)
        if isinstance(value, (list, tuple)) and len(value) > 0:
            return True
        if key == "files_inspected" and _int(value) > 0:
            return True
    return False


def _transcript_proof(source: Mapping, access: str) -> bool:
    if access not in DEEP_ACCESS:
        return False
    locator = _text(source.get("locator"), 120)
    chars = _int(source.get("full_text_chars"))
    explicit = source.get("transcript_processed") is True or bool(source.get("transcript_text"))
    return explicit or chars >= 400 or bool(_TIMESTAMP.search(locator))


def _patent_claims_proof(source: Mapping, access: str) -> bool:
    if _text(source.get("read_level") or source.get("reading_level"), 40).casefold() == "claims":
        return True
    meta = _dict(source.get("patent_meta"))
    if _int(meta.get("claim_count")) > 0 or _int(meta.get("claims_chars")) > 0:
        return True
    return access in DEEP_ACCESS and bool(meta.get("read_depth") in {"claims", "full_text"})


def _integrities_for(source: Mapping, result: Mapping) -> List[Dict]:
    out: List[Dict] = []
    for key in ("extraction_integrity", "translation_integrity", "transformation_integrity"):
        value = source.get(key)
        if isinstance(value, Mapping) and value:
            out.append(dict(value))
    sid = _text(source.get("source_id"), 80)
    if sid:
        for bucket in ("passages", "evidence_passages", "citation_passages"):
            for raw in _list(result.get(bucket)):
                passage = _dict(raw)
                if _text(passage.get("source_id"), 80) != sid:
                    continue
                value = passage.get("extraction_integrity") or passage.get("transformation_integrity")
                if isinstance(value, Mapping) and value:
                    out.append(dict(value))
    return out


def _transformation_audit(source: Mapping, result: Mapping) -> Dict:
    integrities = _integrities_for(source, result)
    claimed_translation = bool(
        source.get("translated") is True
        or source.get("translated_text")
        or source.get("translation")
        or source.get("translation_integrity")
    )
    issues: List[Dict] = []
    methods: List[str] = []
    for item in integrities:
        method = _text(item.get("method"), 40).casefold()
        if method:
            methods.append(method)
        if method == "translation":
            verdict = _text(item.get("verification_verdict"), 80).upper()
            if verdict != "AGREEMENT_OK" or bool(item.get("review_required", True)):
                issues.append({
                    "code": TRANSLATION_REVIEW_REQUIRED,
                    "detail": _text(item.get("reason"), 300) or
                              "translation lacks independent agreement proof",
                })
        elif method == "ocr":
            if bool(item.get("review_required", True)) or _text(
                item.get("quality_label"), 40).casefold() not in {"high", "native"
            }:
                issues.append({
                    "code": OCR_REVIEW_REQUIRED,
                    "detail": _text(item.get("reason"), 300) or
                              "OCR capture requires review before strong-claim use",
                })
    if claimed_translation and "translation" not in methods:
        issues.append({
            "code": TRANSLATION_REVIEW_REQUIRED,
            "detail": "translated content is claimed but translation-integrity metadata is absent",
        })
    return {
        "methods_observed": sorted(set(methods)),
        "status": "REVIEW REQUIRED" if issues else ("PASS" if integrities else "NOT EXPOSED"),
        "issues": issues,
        "rule": "capture/translation quality never proves the source claim is true",
    }


def _language_audit(source: Mapping) -> Dict:
    original = _text(source.get("original_language") or source.get("language"), 80)
    detected = _text(source.get("detected_language"), 80)
    return {
        "original_language": original or "UNKNOWN",
        "detected_language": detected or "UNKNOWN",
        "guessed": False,
        "rule": "language is reported only when runtime metadata exposes it",
    }


def audit_source(source: Mapping, result: Mapping) -> Dict:
    family = source_family(source)
    access = access_depth(source)
    sid = _text(source.get("source_id"), 80)
    title = _text(source.get("title"), 260)
    gaps: List[Dict] = []
    status = "SHALLOW"
    proof = ""

    if family == "dataset":
        if _has_structured_dataset_inspection(source):
            status, proof = "DATA INSPECTED", "structured data/series inspection metadata exposed"
        else:
            gaps.append({"code": DATA_INSPECTION_REQUIRED,
                         "detail": "dataset catalogue/landing metadata is not inspected data"})
            proof = "no structured data inspection marker exposed"
    elif family == "code_repository":
        if _has_code_inspection(source):
            status, proof = "CODE INSPECTED", "repository/file inspection metadata exposed"
        else:
            gaps.append({"code": CODE_INSPECTION_REQUIRED,
                         "detail": "repository metadata/README is not source-code inspection"})
            proof = "no code-file inspection marker exposed"
    elif family in {"media_transcript", "media_recording"}:
        if _transcript_proof(source, access):
            status, proof = "TRANSCRIPT REVIEWED", "timestamp/text-depth evidence shows transcript processing"
        else:
            gaps.append({"code": TRANSCRIPT_REQUIRED,
                         "detail": "media description/discovery is not transcript/audio/visual review"})
            proof = "no transcript processing proof exposed"
    elif family == "patent":
        if _patent_claims_proof(source, access):
            status, proof = "PATENT CLAIMS/SECTIONS REVIEWED", "claims/section depth metadata exposed"
        else:
            gaps.append({"code": PATENT_CLAIMS_REQUIRED,
                         "detail": "patent title/abstract/metadata is not claims-text review"})
            proof = "no claims-text proof exposed"
    elif family == "archive_document":
        if access in DEEP_ACCESS:
            status, proof = "ARCHIVE TEXT REVIEWED", access
        else:
            gaps.append({"code": ARCHIVE_BODY_REQUIRED,
                         "detail": "archive catalogue/search record is not the archived document body"})
            proof = access
    else:
        if access in DEEP_ACCESS:
            status, proof = "DEEP TEXT REVIEWED", access
        else:
            gaps.append({"code": FULL_TEXT_REQUIRED,
                         "detail": "source remains below relevant-section/full-text depth"})
            proof = access

    transform = _transformation_audit(source, result)
    gaps.extend(transform["issues"])
    if transform["issues"] and status not in {"SHALLOW"}:
        status += " — TRANSFORM REVIEW REQUIRED"

    for gap in gaps:
        gap["source_id"] = sid
        gap["source_family"] = family
        gap["title"] = title

    return {
        "source_id": sid,
        "title": title,
        "source_family": family,
        "access_depth": access,
        "deep_status": status,
        "proof": proof,
        "pages_read": _int(source.get("pages_read")),
        "pages_total": _int(source.get("pages_total")),
        "language": _language_audit(source),
        "transformation_integrity": transform,
        "gaps": gaps,
        "truth_rule": (
            "searched/discovered != read; transcript != audio/visual analysis; "
            "dataset metadata != data inspection; repo metadata != code inspection; "
            "patent claims != scientific proof"
        ),
    }


def _task_for_gap(gap: Mapping) -> Dict:
    code = _text(gap.get("code"), 100)
    mapping = {
        FULL_TEXT_REQUIRED: ("Obtain and inspect full text / relevant sections", 10, 9),
        TRANSCRIPT_REQUIRED: ("Acquire legally available transcript/captions and inspect timestamps", 9, 9),
        DATA_INSPECTION_REQUIRED: ("Inspect actual dataset rows/series/schema and record provenance", 10, 10),
        CODE_INSPECTION_REQUIRED: ("Inspect relevant repository files/commit state instead of README metadata", 9, 10),
        PATENT_CLAIMS_REQUIRED: ("Read patent claims/description and preserve legal-claim semantics", 8, 8),
        ARCHIVE_BODY_REQUIRED: ("Open and inspect the actual archived document/body", 9, 9),
        TRANSLATION_REVIEW_REQUIRED: ("Verify translation with independent agreement before strong-claim use", 10, 10),
        OCR_REVIEW_REQUIRED: ("Review low/uncertain OCR capture against the source image", 10, 9),
        PROVENANCE_REQUIRED: ("Recover missing source/transformation provenance", 10, 10),
    }
    title, importance, eig = mapping.get(
        code, ("Resolve deep-source provenance gap", 8, 8)
    )
    return {
        "task": title,
        "why": _text(gap.get("detail"), 400),
        "source_id": _text(gap.get("source_id"), 80),
        "source_family": _text(gap.get("source_family"), 80),
        "importance": importance,
        "expected_information_gain": eig,
        "priority_score": importance * eig,
        "priority_formula": "Importance × Expected Information Gain",
        "route_to": "AI-1",
    }


def build_deep_source_integrity_report(result: Mapping, sources: Sequence[Mapping]) -> Dict:
    """Audit every visible source and return gaps/tasks without inventing coverage."""
    result = _dict(result)
    audited = [audit_source(_dict(source), result) for source in sources]
    gaps: List[Dict] = []
    seen_gaps = set()
    for row in audited:
        for gap in row["gaps"]:
            key = (gap.get("code"), gap.get("source_id"), gap.get("detail"))
            if key in seen_gaps:
                continue
            seen_gaps.add(key)
            gaps.append(gap)

    family_counts = Counter(row["source_family"] for row in audited)
    status_counts = Counter(row["deep_status"] for row in audited)
    deep_count = sum(
        1 for row in audited
        if row["deep_status"].startswith((
            "DEEP TEXT REVIEWED", "DATA INSPECTED", "CODE INSPECTED",
            "TRANSCRIPT REVIEWED", "PATENT CLAIMS/SECTIONS REVIEWED",
            "ARCHIVE TEXT REVIEWED",
        )) and "TRANSFORM REVIEW REQUIRED" not in row["deep_status"]
    )

    tasks_by_key: Dict[tuple, Dict] = {}
    for gap in gaps:
        task = _task_for_gap(gap)
        key = (task["task"], task["source_family"])
        old = tasks_by_key.get(key)
        if old is None or task["priority_score"] > old["priority_score"]:
            tasks_by_key[key] = task
    tasks = sorted(tasks_by_key.values(), key=lambda item: (
        item["priority_score"], item["importance"], item["expected_information_gain"]
    ), reverse=True)

    return {
        "schema_version": "deep-source-integrity-1.0",
        "audited_source_count": len(audited),
        "deep_evidence_source_count": deep_count,
        "blocking_gap_count": len(gaps),
        "source_family_counts": dict(sorted(family_counts.items())),
        "deep_status_counts": dict(sorted(status_counts.items())),
        "sources": audited,
        "gaps": gaps,
        "second_pass_tasks": tasks,
        "coverage_claim": (
            "Only visible runtime sources are audited; absent source families are NOT claimed searched/read."
        ),
        "multilingual_rule": (
            "Unicode text may be processed directly, but language/translation status is never guessed. "
            "A claimed translation needs explicit transformation-integrity evidence."
        ),
        "media_rule": (
            "Transcript/captions can support spoken-word claims; they do not prove visuals, tone, melody, "
            "audio performance or anything not encoded in the transcript."
        ),
        "dataset_code_rule": (
            "Dataset/repository landing metadata cannot satisfy data/code inspection without structured proof."
        ),
    }
