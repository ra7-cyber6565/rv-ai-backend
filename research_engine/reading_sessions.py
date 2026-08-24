"""Durable, project-private, resumable PDF/book ingestion.

This module closes a deliberate gap between one-shot document upload and the
user's request for patient, multi-session book research.  It does not pretend
that text extraction equals comprehension, or that a glossary equals a verified
translation.  Each session records exact page coverage, OCR gaps, edition/source
metadata and translation-review status while preserving the original PDF under
the configured Infinity data root.

Only caller-supplied/legal material is accepted.  No paywall, DRM, password or
copyright control is bypassed and no network/model/paid call is made here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from research_engine.network_safety import UnsafeURL, validate_public_http_url
from research_engine.processing.ocr_processor import OCRProcessor
from research_engine.processing.pdf_processor import PDFProcessor
from research_engine.vector_search import VectorSearch
from utils.process_lock import ExclusiveProcessFileLock


SCHEMA_VERSION = 1
MAX_SESSIONS_PER_PROJECT = 32
MAX_BATCH_PAGES = 100
DEFAULT_BATCH_PAGES = 30
_SESSION_RE = re.compile(r"^read_[A-Za-z0-9_-]{24,80}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,31}$")
_ACCESS_BASES = {
    "user_owned_copy",
    "public_domain",
    "open_license",
    "official_public_record",
    "permission_granted",
    "unknown_user_supplied",
}
_TRANSLATION_STATUSES = {
    "not_required_same_language",
    "pending_semantic_translation_review",
    "machine_assisted_unverified",
    "human_verified",
}


class ReadingSessionError(ValueError):
    """A reading session cannot continue without guessing or unsafe access."""


class ReadingProcessingBlocked(ReadingSessionError):
    """The preserved PDF is resumable, but its processor cannot proceed yet."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[: max(0, int(limit))]


def _safe_name(value: object) -> str:
    name = os.path.basename(str(value or "document.pdf").replace("\\", "/"))
    return _clean(name, 240) or "document.pdf"


def _project_key(project_id: object) -> str:
    raw = str(project_id or "").strip()
    if not raw or len(raw) > 80:
        raise ReadingSessionError("project_id invalid hai")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _session_id(value: object) -> str:
    clean = str(value or "").strip()
    if not _SESSION_RE.fullmatch(clean):
        raise ReadingSessionError("reading session id invalid hai")
    return clean


def _public_url(value: object) -> tuple[str, list[str]]:
    raw = _clean(value, 2048)
    if not raw:
        return "", ["SOURCE_URL_NOT_SUPPLIED"]
    try:
        return validate_public_http_url(raw, resolve_dns=False), []
    except UnsafeURL:
        return "", ["UNSAFE_SOURCE_URL_REMOVED"]


def _language(value: object, field: str, *, default: str = "und") -> str:
    clean = _clean(value, 32) or default
    if not _LANGUAGE_RE.fullmatch(clean):
        raise ReadingSessionError(f"{field} BCP-47 jaisa language tag hona chahiye")
    return clean.lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ranges(pages) -> list[dict[str, int]]:
    """Turn page numbers into compact, stable inclusive ranges."""
    ordered = sorted({int(page) for page in pages or [] if int(page) > 0})
    if not ordered:
        return []
    out: list[dict[str, int]] = []
    start = previous = ordered[0]
    for page in ordered[1:]:
        if page == previous + 1:
            previous = page
            continue
        out.append({"start": start, "end": previous})
        start = previous = page
    out.append({"start": start, "end": previous})
    return out


def _expand_ranges(ranges) -> set[int]:
    out: set[int] = set()
    for row in ranges or []:
        try:
            start = int(row.get("start"))
            end = int(row.get("end"))
        except (AttributeError, TypeError, ValueError):
            raise ReadingSessionError("reading ledger page ranges corrupted") from None
        if start <= 0 or end < start or end - start > 100_000:
            raise ReadingSessionError("reading ledger page ranges corrupted")
        out.update(range(start, end + 1))
    return out


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{secrets.token_hex(6)}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


class ReadingSessionStore:
    """Bounded JSON/file store isolated by a one-way project namespace hash."""

    def __init__(self, root: str | Path, max_sessions: int = MAX_SESSIONS_PER_PROJECT):
        self.root = Path(root)
        self.max_sessions = max(1, min(int(max_sessions), 128))
        self._thread_lock = threading.RLock()

    def _project_dir(self, project_id: object) -> Path:
        return self.root / _project_key(project_id)

    def _state_path(self, project_id: object, session_id: object) -> Path:
        return self._project_dir(project_id) / f"{_session_id(session_id)}.json"

    def _document_path(self, project_id: object, session_id: object) -> Path:
        return self._project_dir(project_id) / f"{_session_id(session_id)}.pdf"

    def _lock_path(self, project_id: object, session_id: object = "") -> Path:
        suffix = _session_id(session_id) if session_id else "project"
        return self._project_dir(project_id) / f".{suffix}.lock"

    @staticmethod
    def _read_state(path: Path) -> dict:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ReadingSessionError("reading session nahi mila") from None
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ReadingSessionError("reading session ledger corrupted hai") from None
        if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
            raise ReadingSessionError("reading session ledger schema invalid hai")
        return raw

    def load(self, project_id: object, session_id: object) -> dict:
        return self._read_state(self._state_path(project_id, session_id))

    def list(self, project_id: object) -> list[dict]:
        folder = self._project_dir(project_id)
        if not folder.exists():
            return []
        rows: list[dict] = []
        for path in sorted(folder.glob("read_*.json")):
            rows.append(self._read_state(path))
        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows[: self.max_sessions]

    def create(self, project_id: object, source_path: str | Path, metadata: Mapping[str, object]) -> dict:
        source = Path(source_path)
        if not source.is_file():
            raise ReadingSessionError("uploaded PDF temporary file nahi mili")
        if source.suffix.lower() != ".pdf":
            raise ReadingSessionError("resumable reading abhi PDF ke liye supported hai")

        supplied_provenance = dict(metadata.get("provenance") or {})
        supplied_language = dict(metadata.get("language") or {})
        metadata = build_metadata(
            filename=metadata.get("filename"),
            title=metadata.get("title"),
            author=metadata.get("author"),
            edition=metadata.get("edition"),
            publication_year=metadata.get("publication_year"),
            source_identifier=metadata.get("source_identifier"),
            source_url=supplied_provenance.get("source_url"),
            access_basis=supplied_provenance.get("access_basis"),
            original_language=supplied_language.get("original_language"),
            review_language=supplied_language.get("review_language"),
            translation_status=supplied_language.get("translation_status"),
            translation_evidence_id=supplied_language.get("translation_evidence_id"),
        )
        carried_warnings = {
            str(item) for item in supplied_provenance.get("source_warnings") or []
            if str(item) in {"SOURCE_URL_NOT_SUPPLIED", "UNSAFE_SOURCE_URL_REMOVED"}
        }
        if "UNSAFE_SOURCE_URL_REMOVED" in carried_warnings:
            metadata["provenance"]["source_warnings"] = ["UNSAFE_SOURCE_URL_REMOVED"]

        project_dir = self._project_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, ExclusiveProcessFileLock(str(self._lock_path(project_id))):
            # A hard crash can occur after the atomic PDF move but before its
            # first JSON receipt. Under the project-create lock, a PDF with no
            # matching state can never be a resumable/active session; remove
            # only those exact orphans so they cannot bypass the disk bound.
            for orphan in project_dir.glob("read_*.pdf"):
                if not orphan.with_suffix(".json").exists():
                    orphan.unlink(missing_ok=True)
            for partial in project_dir.glob("read_*.pdf.copying"):
                partial.unlink(missing_ok=True)
            existing = sorted(project_dir.glob("read_*.json"))
            if len(existing) >= self.max_sessions:
                raise ReadingSessionError(
                    f"project reading-session limit reached ({self.max_sessions}); purani session ko archive/remove karna hoga"
                )

            session_id = f"read_{secrets.token_urlsafe(24)}"
            document_path = self._document_path(project_id, session_id)
            temp_copy = document_path.with_suffix(".pdf.copying")
            try:
                with source.open("rb") as incoming, temp_copy.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                os.replace(temp_copy, document_path)
                digest = _sha256(document_path)
                now = _now()
                state = {
                    "schema_version": SCHEMA_VERSION,
                    "session_id": session_id,
                    "created_at": now,
                    "updated_at": now,
                    "status": "CREATED_NOT_INSPECTED",
                    "document": {
                        "filename": _safe_name(metadata.get("filename")),
                        "sha256": digest,
                        "bytes": int(document_path.stat().st_size),
                        "format": "pdf",
                        "title": _clean(metadata.get("title"), 300),
                        "author": _clean(metadata.get("author"), 240),
                        "edition": _clean(metadata.get("edition"), 160),
                        "publication_year": _clean(metadata.get("publication_year"), 12),
                        "source_identifier": _clean(metadata.get("source_identifier"), 160),
                    },
                    "provenance": dict(metadata.get("provenance") or {}),
                    "language": dict(metadata.get("language") or {}),
                    "coverage": {
                        "total_pages": 0,
                        "inspected_page_ranges": [],
                        "native_text_page_ranges": [],
                        "ocr_text_page_ranges": [],
                        "unreadable_page_ranges": [],
                        "pending_translation_page_ranges": [],
                        "indexed_page_ranges": [],
                        "next_page": 1,
                        "next_uninspected_page": 1,
                        "next_index_retry_page": None,
                        "page_inspection_fraction": 0.0,
                        "text_available_fraction": 0.0,
                    },
                    "batches": [],
                    "honesty": {
                        "text_extraction_is_not_comprehension": True,
                        "catalog_or_metadata_is_not_book_read": True,
                        "translation_must_preserve_original": True,
                        "password_drm_paywall_bypass": False,
                        "completion_claim": "NOT_READ_YET",
                    },
                }
                _atomic_json(self._state_path(project_id, session_id), state)
                return state
            except Exception:
                temp_copy.unlink(missing_ok=True)
                document_path.unlink(missing_ok=True)
                raise

    def save_locked(self, project_id: object, session_id: object, state: Mapping[str, object]) -> None:
        """Write while the caller holds the session's process lock."""
        if str(state.get("session_id") or "") != _session_id(session_id):
            raise ReadingSessionError("reading session state mismatch")
        _atomic_json(self._state_path(project_id, session_id), state)

    def session_lock(self, project_id: object, session_id: object):
        return ExclusiveProcessFileLock(str(self._lock_path(project_id, session_id)))


def build_metadata(
    *,
    filename: object,
    title: object = "",
    author: object = "",
    edition: object = "",
    publication_year: object = "",
    source_identifier: object = "",
    source_url: object = "",
    access_basis: object = "unknown_user_supplied",
    original_language: object = "und",
    review_language: object = "en",
    translation_status: object = "pending_semantic_translation_review",
    translation_evidence_id: object = "",
) -> dict:
    """Validate user-declared provenance without silently upgrading it."""
    basis = _clean(access_basis, 64)
    if basis not in _ACCESS_BASES:
        raise ReadingSessionError("access_basis supported value nahi hai")
    translation = _clean(translation_status, 64)
    if translation not in _TRANSLATION_STATUSES:
        raise ReadingSessionError("translation_status supported value nahi hai")
    original = _language(original_language, "original_language")
    review = _language(review_language, "review_language", default="en")
    if original == review and translation == "pending_semantic_translation_review":
        translation = "not_required_same_language"
    if original != review and translation == "not_required_same_language":
        raise ReadingSessionError(
            "alag original/review language ke liye translation review status required hai"
        )
    translation_reference = _clean(translation_evidence_id, 200)
    if translation == "human_verified" and not translation_reference:
        raise ReadingSessionError(
            "human_verified translation ke liye translation_evidence_id required hai"
        )
    safe_url, warnings = _public_url(source_url)
    year = _clean(publication_year, 12)
    if year and not re.fullmatch(r"[0-9]{4}", year):
        raise ReadingSessionError("publication_year four-digit year hona chahiye")
    return {
        "filename": _safe_name(filename),
        "title": _clean(title, 300),
        "author": _clean(author, 240),
        "edition": _clean(edition, 160),
        "publication_year": year,
        "source_identifier": _clean(source_identifier, 160),
        "provenance": {
            "source_url": safe_url,
            "source_warnings": warnings,
            "access_basis": basis,
            "metadata_status": "USER_DECLARED_NOT_INDEPENDENTLY_VERIFIED",
            "legal_access_only": True,
        },
        "language": {
            "original_language": original,
            "review_language": review,
            "translation_status": translation,
            "translation_evidence_id": translation_reference,
            "translation_evidence_status": "USER_DECLARED_NOT_INDEPENDENTLY_VERIFIED",
            "original_text_preserved": True,
            "glossary_is_not_translation": True,
        },
    }


class ResumableReadingManager:
    """Sequentially inspect/index bounded batches and resume from the ledger."""

    def __init__(
        self,
        store: ReadingSessionStore,
        *,
        pdf: PDFProcessor | None = None,
        ocr: OCRProcessor | None = None,
        vectors: VectorSearch | None = None,
    ):
        self.store = store
        self.pdf = pdf or PDFProcessor()
        self.ocr = ocr or OCRProcessor()
        self.vectors = vectors or VectorSearch()

    def start(
        self,
        project_id: object,
        source_path: str | Path,
        metadata: Mapping[str, object],
        *,
        batch_pages: int = DEFAULT_BATCH_PAGES,
        use_ocr: bool = True,
    ) -> dict:
        try:
            count = int(batch_pages or DEFAULT_BATCH_PAGES)
        except (TypeError, ValueError):
            raise ReadingSessionError("batch_pages integer hona chahiye") from None
        if not (1 <= count <= MAX_BATCH_PAGES):
            raise ReadingSessionError(f"batch_pages 1..{MAX_BATCH_PAGES} hona chahiye")
        state = self.store.create(project_id, source_path, metadata)
        try:
            return self.resume(
                project_id,
                state["session_id"],
                batch_pages=count,
                use_ocr=use_ocr,
            )
        except ReadingProcessingBlocked:
            # The legal PDF has already been safely preserved.  Keep its opaque
            # session id resumable when PyMuPDF/OCR setup or file readability is
            # the only blocker; otherwise the caller would receive an error but
            # have no handle with which to continue after fixing the dependency.
            sid = state["session_id"]
            with self.store._thread_lock, self.store.session_lock(project_id, sid):
                current = self.store.load(project_id, sid)
                current["status"] = "PROCESSING_BLOCKED"
                current["updated_at"] = _now()
                current["processing_blocker"] = \
                    "PDF_PROCESSOR_UNAVAILABLE_OR_FILE_UNREADABLE"
                current["honesty"]["completion_claim"] = "NOT_READ_YET"
                self.store.save_locked(project_id, sid, current)
                return current

    def resume(
        self,
        project_id: object,
        session_id: object,
        *,
        batch_pages: int = DEFAULT_BATCH_PAGES,
        use_ocr: bool = True,
    ) -> dict:
        sid = _session_id(session_id)
        try:
            count = int(batch_pages or DEFAULT_BATCH_PAGES)
        except (TypeError, ValueError):
            raise ReadingSessionError("batch_pages integer hona chahiye") from None
        if not (1 <= count <= MAX_BATCH_PAGES):
            raise ReadingSessionError(f"batch_pages 1..{MAX_BATCH_PAGES} hona chahiye")

        with self.store._thread_lock, self.store.session_lock(project_id, sid):
            state = self.store.load(project_id, sid)
            path = self.store._document_path(project_id, sid)
            if not path.is_file():
                raise ReadingSessionError("reading session ka preserved PDF missing hai")
            expected_size = int((state.get("document") or {}).get("bytes") or 0)
            if expected_size <= 0 or path.stat().st_size != expected_size:
                raise ReadingSessionError("preserved PDF integrity check fail hua")
            expected_hash = str((state.get("document") or {}).get("sha256") or "")
            if len(expected_hash) != 64 or _sha256(path) != expected_hash:
                raise ReadingSessionError("preserved PDF integrity check fail hua")

            coverage = dict(state.get("coverage") or {})
            inspected = _expand_ranges(coverage.get("inspected_page_ranges"))
            native = _expand_ranges(coverage.get("native_text_page_ranges"))
            ocr_pages = _expand_ranges(coverage.get("ocr_text_page_ranges"))
            unreadable = _expand_ranges(coverage.get("unreadable_page_ranges"))
            pending_translation = _expand_ranges(coverage.get("pending_translation_page_ranges"))
            indexed = _expand_ranges(coverage.get("indexed_page_ranges"))

            total = int(coverage.get("total_pages") or self.pdf.page_count(str(path)) or 0)
            if total <= 0:
                raise ReadingProcessingBlocked(
                    "PDF page count nahi mila; file encrypted/corrupt ho sakti hai ya PyMuPDF unavailable hai"
                )
            valid_pages = set(range(1, total + 1))
            for label, pages in (
                ("inspected", inspected), ("native", native),
                ("ocr", ocr_pages), ("unreadable", unreadable),
                ("pending_translation", pending_translation), ("indexed", indexed),
            ):
                if not pages.issubset(valid_pages):
                    raise ReadingSessionError(f"reading ledger {label} page range invalid hai")
            pending_index_before = (native | ocr_pages) - indexed
            next_uninspected_before = min(
                (page for page in range(1, total + 1) if page not in inspected),
                default=total + 1,
            )
            index_retry = bool(pending_index_before)
            next_page = min(pending_index_before) if index_retry else next_uninspected_before
            if next_page > total:
                return state

            rows = list(self.pdf.iter_pages(str(path), max_pages=count, start_page=next_page - 1))
            if not rows:
                raise ReadingProcessingBlocked("PDF batch inspect nahi ho saka")
            batch_numbers = [int(row.get("page") or 0) for row in rows]
            expected_pages = list(range(next_page, min(total, next_page + count - 1) + 1))
            if batch_numbers != expected_pages:
                raise ReadingSessionError("PDF processor ne non-sequential/invalid page batch diya")
            scanned = [int(row["page"]) for row in rows if row.get("scanned")]
            chunks = [
                {
                    "locator": f"p.{int(row['page'])}",
                    "text": str(row.get("text") or "").strip(),
                    "header": f"[Source: {state['document']['filename']}, Page {int(row['page'])}]",
                }
                for row in rows
                if not row.get("scanned") and str(row.get("text") or "").strip()
            ]
            native.update(int(row["page"]) for row in rows if not row.get("scanned") and str(row.get("text") or "").strip())

            ocr_attempted: list[int] = []
            if scanned and use_ocr:
                ocr_attempted = list(scanned)
                ocr_result = self.ocr.ocr_pdf_pages(str(path), scanned, max_pages=len(scanned))
                for row in ocr_result.get("pages") or []:
                    page = int(row.get("page") or 0)
                    text = str(row.get("text") or "").strip()
                    if page > 0 and text:
                        ocr_pages.add(page)
                        chunks.append({
                            "locator": f"p.{page} (OCR)",
                            "text": text,
                            "header": f"[Source: {state['document']['filename']}, Page {page}, OCR]",
                        })

            text_pages = native | ocr_pages
            unreadable.update(page for page in scanned if page not in text_pages)
            unreadable.difference_update(text_pages)
            inspected.update(page for page in batch_numbers if page > 0)

            language = state.get("language") or {}
            translation_pending = language.get("translation_status") in {
                "pending_semantic_translation_review", "machine_assisted_unverified",
            }
            if translation_pending:
                pending_translation.update(page for page in batch_numbers if page in text_pages)
            else:
                pending_translation.difference_update(batch_numbers)

            index_report = {"ok": True, "chunks": 0, "error": ""}
            if chunks:
                namespace = f"{sid}:{next_page}"
                index_report = self.vectors.ingest_chunks(
                    chunks,
                    state["document"]["filename"],
                    str(project_id),
                    id_namespace=namespace,
                )
                if index_report.get("ok"):
                    indexed.update(
                        int(re.search(r"p\.(\d+)", str(chunk["locator"])).group(1))
                        for chunk in chunks
                    )

            next_unread = min((page for page in range(1, total + 1) if page not in inspected), default=total + 1)
            pending_index_after = text_pages - indexed
            next_index_retry = min(pending_index_after) if pending_index_after else None
            next_action = next_index_retry or (next_unread if next_unread <= total else None)
            page_fraction = round(min(len(inspected), total) / total, 4)
            text_fraction = round(min(len(text_pages), total) / total, 4)
            all_inspected = len(inspected) >= total
            all_text = len(text_pages) >= total and not unreadable
            all_indexed = text_pages.issubset(indexed)

            if not all_inspected:
                status = "IN_PROGRESS"
                completion = "PARTIAL_PAGE_INSPECTION"
            elif unreadable:
                status = "PAGE_INSPECTION_COMPLETE_WITH_UNREADABLE_GAPS"
                completion = "NOT_FULL_TEXT"
            elif pending_translation:
                status = "TEXT_INGESTED_TRANSLATION_REVIEW_PENDING"
                completion = "NOT_SEMANTICALLY_REVIEWED_IN_TARGET_LANGUAGE"
            elif not all_indexed:
                status = "TEXT_EXTRACTED_INDEXING_INCOMPLETE"
                completion = "NOT_FULLY_INDEXED"
            elif all_text:
                status = "FULL_DOCUMENT_TEXT_INGESTED"
                completion = "TEXT_INGESTED_NOT_AUTOMATICALLY_COMPREHENSION_VERIFIED"
            else:
                status = "PAGE_INSPECTION_COMPLETE_WITH_GAPS"
                completion = "NOT_FULL_TEXT"

            coverage.update({
                "total_pages": total,
                "inspected_page_ranges": _ranges(inspected),
                "native_text_page_ranges": _ranges(native),
                "ocr_text_page_ranges": _ranges(ocr_pages),
                "unreadable_page_ranges": _ranges(unreadable),
                "pending_translation_page_ranges": _ranges(pending_translation),
                "indexed_page_ranges": _ranges(indexed),
                "next_page": next_action,
                "next_uninspected_page": next_unread if next_unread <= total else None,
                "next_index_retry_page": next_index_retry,
                "page_inspection_fraction": page_fraction,
                "text_available_fraction": text_fraction,
            })
            state["coverage"] = coverage
            state["status"] = status
            state.pop("processing_blocker", None)
            state["updated_at"] = _now()
            state["honesty"]["completion_claim"] = completion
            batches = list(state.get("batches") or [])
            batches.append({
                "started_at_page": next_page,
                "ended_at_page": max(batch_numbers),
                "mode": "INDEX_RETRY" if index_retry else "NEW_PAGE_INSPECTION",
                "pages_inspected": len(batch_numbers),
                "native_text_pages": len([page for page in batch_numbers if page in native]),
                "ocr_attempted_pages": _ranges(ocr_attempted),
                "ocr_text_pages": len([page for page in batch_numbers if page in ocr_pages]),
                "unreadable_pages": len([page for page in batch_numbers if page in unreadable]),
                "translation_review_pending": translation_pending,
                "index_status": "INDEXED" if index_report.get("ok") else "INDEXING_FAILED",
                "indexed_chunks": int(index_report.get("chunks") or 0),
            })
            state["batches"] = batches[-256:]
            self.store.save_locked(project_id, sid, state)
            return state


def public_session(state: Mapping[str, object]) -> dict:
    """Return only user-facing provenance/progress; never filesystem paths."""
    return {
        "schema_version": state.get("schema_version"),
        "session_id": state.get("session_id"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "status": state.get("status"),
        "processing_blocker": state.get("processing_blocker"),
        "document": dict(state.get("document") or {}),
        "provenance": dict(state.get("provenance") or {}),
        "language": dict(state.get("language") or {}),
        "coverage": dict(state.get("coverage") or {}),
        "batches": list(state.get("batches") or []),
        "honesty": dict(state.get("honesty") or {}),
    }


__all__ = [
    "DEFAULT_BATCH_PAGES",
    "MAX_BATCH_PAGES",
    "ReadingSessionError",
    "ReadingProcessingBlocked",
    "ReadingSessionStore",
    "ResumableReadingManager",
    "build_metadata",
    "public_session",
]
