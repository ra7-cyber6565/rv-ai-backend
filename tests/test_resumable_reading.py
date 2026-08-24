"""Offline adversarial checks for durable multi-session book/PDF reading."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_engine.reading_sessions import (
    ReadingSessionError,
    ReadingSessionStore,
    ResumableReadingManager,
    build_metadata,
    public_session,
)
from research_engine.vector_search import VectorSearch
from utils.body_limit import request_body_limit


class FakePDF:
    def __init__(self, pages):
        self.pages = list(pages)

    def page_count(self, _path):
        return len(self.pages)

    def iter_pages(self, _path, max_pages=0, start_page=0):
        end = len(self.pages) if max_pages <= 0 else min(len(self.pages), start_page + max_pages)
        for index in range(start_page, end):
            text = self.pages[index]
            yield {
                "page": index + 1,
                "text": text,
                "scanned": text is None,
                "chars": len(text or ""),
            }


class FakeOCR:
    def __init__(self, texts=None):
        self.texts = dict(texts or {})
        self.calls = []

    def ocr_pdf_pages(self, _path, pages, max_pages=0):
        self.calls.append(list(pages))
        return {
            "pages": [
                {"page": page, "text": self.texts[page]}
                for page in pages
                if self.texts.get(page)
            ]
        }


class FakeVectors:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def ingest_chunks(self, chunks, filename, project_id, id_namespace=""):
        self.calls.append({
            "chunks": list(chunks),
            "filename": filename,
            "project_id": project_id,
            "id_namespace": id_namespace,
        })
        return {
            "ok": self.ok,
            "chunks": len(chunks) if self.ok else 0,
            "error": "" if self.ok else "synthetic index failure",
        }


def _pdf(tmp_path: Path, content: bytes = b"synthetic-pdf") -> Path:
    path = tmp_path / "book.pdf"
    path.write_bytes(content)
    return path


def _metadata(**overrides):
    values = {
        "filename": "book.pdf",
        "title": "A Test Book",
        "author": "Research Author",
        "edition": "2nd",
        "publication_year": "2024",
        "source_identifier": "ISBN-test",
        "source_url": "https://archive.example.org/book",
        "access_basis": "user_owned_copy",
        "original_language": "hi",
        "review_language": "en",
        "translation_status": "pending_semantic_translation_review",
    }
    values.update(overrides)
    return build_metadata(**values)


def test_metadata_preserves_declared_edition_language_and_honest_translation_status():
    metadata = _metadata()
    assert metadata["edition"] == "2nd"
    assert metadata["provenance"]["metadata_status"] == \
        "USER_DECLARED_NOT_INDEPENDENTLY_VERIFIED"
    assert metadata["language"]["original_text_preserved"] is True
    assert metadata["language"]["translation_status"] == \
        "pending_semantic_translation_review"
    assert metadata["language"]["glossary_is_not_translation"] is True


def test_private_source_url_is_removed_and_cross_language_no_review_is_rejected():
    metadata = _metadata(source_url="http://127.0.0.1/private")
    assert metadata["provenance"]["source_url"] == ""
    assert "UNSAFE_SOURCE_URL_REMOVED" in metadata["provenance"]["source_warnings"]
    with pytest.raises(ReadingSessionError, match="translation review status"):
        _metadata(translation_status="not_required_same_language")
    with pytest.raises(ReadingSessionError, match="translation_evidence_id"):
        _metadata(translation_status="human_verified")


def test_store_is_project_isolated_bounded_and_corruption_fails_closed(tmp_path):
    store = ReadingSessionStore(tmp_path / "sessions", max_sessions=1)
    one = store.create("project-one", _pdf(tmp_path), _metadata())
    assert store.load("project-one", one["session_id"])["session_id"] == one["session_id"]
    with pytest.raises(ReadingSessionError, match="nahi mila"):
        store.load("project-two", one["session_id"])
    with pytest.raises(ReadingSessionError, match="limit"):
        store.create("project-one", _pdf(tmp_path, b"second"), _metadata())

    state_path = store._state_path("project-one", one["session_id"])
    state_path.write_text("{bad json", encoding="utf-8")
    with pytest.raises(ReadingSessionError, match="corrupted"):
        store.load("project-one", one["session_id"])
    assert state_path.read_text(encoding="utf-8") == "{bad json"


def test_resume_advances_sequentially_and_never_calls_partial_book_fully_read(tmp_path):
    store = ReadingSessionStore(tmp_path / "sessions")
    pdf = FakePDF(["page one", None, "page three", "page four", None])
    ocr = FakeOCR({2: "OCR page two"})
    vectors = FakeVectors()
    manager = ResumableReadingManager(store, pdf=pdf, ocr=ocr, vectors=vectors)

    first = manager.start(
        "project-one", _pdf(tmp_path), _metadata(), batch_pages=3, use_ocr=True,
    )
    assert first["status"] == "IN_PROGRESS"
    assert first["coverage"]["inspected_page_ranges"] == [{"start": 1, "end": 3}]
    assert first["coverage"]["ocr_text_page_ranges"] == [{"start": 2, "end": 2}]
    assert first["coverage"]["next_page"] == 4
    assert first["honesty"]["completion_claim"] == "PARTIAL_PAGE_INSPECTION"
    assert vectors.calls[0]["id_namespace"].endswith(":1")

    second = manager.resume("project-one", first["session_id"], batch_pages=3, use_ocr=True)
    assert second["coverage"]["inspected_page_ranges"] == [{"start": 1, "end": 5}]
    assert second["coverage"]["unreadable_page_ranges"] == [{"start": 5, "end": 5}]
    assert second["coverage"]["next_page"] is None
    assert second["status"] == "PAGE_INSPECTION_COMPLETE_WITH_UNREADABLE_GAPS"
    assert second["honesty"]["completion_claim"] == "NOT_FULL_TEXT"
    assert ocr.calls == [[2], [5]]


def test_full_native_text_ingestion_is_not_mislabeled_comprehension(tmp_path):
    store = ReadingSessionStore(tmp_path / "sessions")
    manager = ResumableReadingManager(
        store,
        pdf=FakePDF(["one", "two", "three"]),
        ocr=FakeOCR(),
        vectors=FakeVectors(),
    )
    state = manager.start(
        "project-one",
        _pdf(tmp_path),
        _metadata(
            original_language="en",
            review_language="en",
            translation_status="not_required_same_language",
        ),
        batch_pages=3,
    )
    assert state["status"] == "FULL_DOCUMENT_TEXT_INGESTED"
    assert state["coverage"]["page_inspection_fraction"] == 1.0
    assert state["coverage"]["text_available_fraction"] == 1.0
    assert state["honesty"]["completion_claim"] == \
        "TEXT_INGESTED_NOT_AUTOMATICALLY_COMPREHENSION_VERIFIED"


def test_translation_pending_and_index_failure_are_both_visible(tmp_path):
    store = ReadingSessionStore(tmp_path / "sessions")
    vectors = FakeVectors(ok=False)
    manager = ResumableReadingManager(
        store,
        pdf=FakePDF(["मूल पाठ", "दूसरा पृष्ठ"]),
        ocr=FakeOCR(),
        vectors=vectors,
    )
    state = manager.start("project-one", _pdf(tmp_path), _metadata(), batch_pages=2)
    # Translation incompleteness is the stronger, earlier honesty boundary;
    # indexing failure remains separately preserved in the batch receipt.
    assert state["status"] == "TEXT_INGESTED_TRANSLATION_REVIEW_PENDING"
    assert state["coverage"]["pending_translation_page_ranges"] == [{"start": 1, "end": 2}]
    assert state["coverage"]["indexed_page_ranges"] == []
    assert state["coverage"]["next_index_retry_page"] == 1
    assert state["batches"][-1]["index_status"] == "INDEXING_FAILED"

    vectors.ok = True
    recovered = manager.resume(
        "project-one", state["session_id"], batch_pages=2,
    )
    assert recovered["coverage"]["indexed_page_ranges"] == [{"start": 1, "end": 2}]
    assert recovered["coverage"]["next_index_retry_page"] is None
    assert recovered["coverage"]["next_page"] is None
    assert recovered["batches"][-1]["mode"] == "INDEX_RETRY"


def test_preserved_pdf_tampering_fails_integrity_check(tmp_path):
    store = ReadingSessionStore(tmp_path / "sessions")
    manager = ResumableReadingManager(
        store, pdf=FakePDF(["one"]), ocr=FakeOCR(), vectors=FakeVectors(),
    )
    created = store.create("project-one", _pdf(tmp_path, b"abcd"), _metadata())
    preserved = store._document_path("project-one", created["session_id"])
    preserved.write_bytes(b"wxyz")  # same length; only SHA-256 detects this
    with pytest.raises(ReadingSessionError, match="integrity"):
        manager.resume("project-one", created["session_id"], batch_pages=1)


def test_start_returns_resumable_blocked_session_when_pdf_processor_is_unavailable(tmp_path):
    store = ReadingSessionStore(tmp_path / "sessions")
    manager = ResumableReadingManager(
        store, pdf=FakePDF([]), ocr=FakeOCR(), vectors=FakeVectors(),
    )
    state = manager.start("project-one", _pdf(tmp_path), _metadata(), batch_pages=1)
    assert state["session_id"].startswith("read_")
    assert state["status"] == "PROCESSING_BLOCKED"
    assert state["processing_blocker"] == \
        "PDF_PROCESSOR_UNAVAILABLE_OR_FILE_UNREADABLE"
    assert store.load("project-one", state["session_id"])["status"] == \
        "PROCESSING_BLOCKED"


def test_public_session_and_raw_body_limit_never_expose_storage_paths(tmp_path):
    store = ReadingSessionStore(tmp_path / "private-root")
    state = store.create("project-one", _pdf(tmp_path), _metadata())
    public = public_session(state)
    assert "private-root" not in repr(public)
    assert "project-one" not in repr(public)
    assert request_body_limit("POST", "/api/v1/reading-sessions/start") == 64 * 1024 * 1024


def test_resumed_vector_batches_use_stable_upsert_ids_not_random_hashes():
    class Collection:
        def __init__(self):
            self.upserts = []

        def upsert(self, **kwargs):
            self.upserts.append(kwargs)

        def add(self, **_kwargs):
            raise AssertionError("resumable namespace must use idempotent upsert")

    class Embeddings:
        def encode(self, documents):
            class Encoded:
                def tolist(self):
                    return [[0.1] for _ in documents]
            return Encoded()

    class Pipeline:
        def __init__(self):
            self.collection = Collection()
            self.client = self
            self.embedding_model = Embeddings()

        @staticmethod
        def split_text(text, chunk_size=500):  # noqa: ARG004
            return [text]

        def get_or_create_collection(self, name):  # noqa: ARG002
            return self.collection

    vector = VectorSearch()
    vector._pipeline = Pipeline()
    chunk = {"locator": "p.7", "text": "same stable passage"}
    first = vector.ingest_chunks([chunk], "book.pdf", "p_valid", id_namespace="read_x:7")
    second = vector.ingest_chunks([chunk], "book.pdf", "p_valid", id_namespace="read_x:7")
    assert first["ok"] and second["ok"]
    ids = [call["ids"] for call in vector._pipeline.collection.upserts]
    assert ids[0] == ids[1]
    assert ids[0][0].startswith("chunk_") and len(ids[0][0]) == len("chunk_") + 32
