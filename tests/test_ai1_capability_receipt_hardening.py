from research_engine import ai1_packet_extensions as packet_ext
from research_engine import source_capability_matrix as scm


def _by_family(matrix):
    return {row["source_family"]: row for row in matrix["families"]}


def _source(source_id, **extra):
    row = {
        "source_id": source_id,
        "title": source_id,
        "url": "",
        "connector": "web",
        "source_type": "web",
        "read_level": "snippet",
        "domain_verdict": {},
    }
    row.update(extra)
    return row


def test_generic_archive_media_is_not_podcast_or_official_archive():
    result = {
        "sources": [
            _source(
                "T1",
                title="Quantum computing lecture transcript",
                url="https://archive.org/details/quantum-lecture",
                connector="archive_media",
                source_type="transcript",
                read_level="full_text",
            )
        ]
    }
    matrix = scm.build_source_capability_matrix(result)
    families = _by_family(matrix)

    assert matrix["valid"] is True
    assert families["video_audio_transcripts_interviews_lectures"]["runtime"]["exercised"] is True
    assert families["podcasts_and_user_audio"]["runtime"]["exercised"] is False
    assert families["official_archives_and_declassified_records"]["runtime"]["exercised"] is False


def test_podcast_and_local_user_audio_require_explicit_signals():
    result = {
        "sources": [
            _source(
                "P1",
                title="Science Weekly Podcast Episode 8",
                url="https://archive.org/details/science-weekly-8",
                connector="archive_media",
                source_type="transcript",
                read_level="full_text",
            ),
            _source(
                "U1",
                title="uploaded recording",
                connector="user_upload",
                source_type="transcript",
                read_level="full_text",
                read_note="Audio locally transcribe hui (faster-whisper, model=base).",
            ),
        ]
    }
    runtime = _by_family(scm.build_source_capability_matrix(result))[
        "podcasts_and_user_audio"
    ]["runtime"]

    assert runtime["exercised"] is True
    assert set(runtime["exercised_source_ids"]) == {"P1", "U1"}
    assert runtime["deep_exercised_count"] == 2


def test_official_archive_classifier_is_provider_or_host_specific():
    result = {
        "sources": [
            _source(
                "N1",
                title="Declassified archival record",
                url="https://catalog.archives.gov/id/123",
                connector="nara_archive",
                source_type="document",
                read_level="sections",
            ),
            _source(
                "C1",
                title="CIA Reading Room document",
                url="https://www.cia.gov/readingroom/document/example",
                connector="web",
                source_type="web",
                read_level="full_text",
            ),
            _source(
                "M1",
                title="Archive.org oral history",
                url="https://archive.org/details/oral-history",
                connector="archive_media",
                source_type="transcript",
                read_level="full_text",
            ),
        ]
    }
    runtime = _by_family(scm.build_source_capability_matrix(result))[
        "official_archives_and_declassified_records"
    ]["runtime"]

    assert set(runtime["exercised_source_ids"]) == {"N1", "C1"}
    assert "M1" not in runtime["exercised_source_ids"]


def test_pdf_and_historical_primary_text_receipts_are_exercisable():
    result = {
        "sources": [
            _source(
                "D1",
                title="Large scanned report",
                url="https://example.org/report.pdf",
                source_type="document",
                read_level="sections",
                pages_read=8,
                pages_total=120,
            ),
            _source(
                "H1",
                title="Historical primary text",
                url="https://hi.wikisource.org/wiki/example",
                connector="wikisource_hi",
                source_type="book",
                read_level="full_text",
            ),
        ]
    }
    families = _by_family(scm.build_source_capability_matrix(result))

    pdfs = families["pdfs_and_large_documents"]["runtime"]
    assert pdfs["exercised_source_ids"] == ["D1"]
    assert pdfs["deep_exercised_count"] == 1

    historical = families["historical_primary_texts"]["runtime"]
    assert historical["exercised_source_ids"] == ["H1"]
    assert historical["deep_exercised_count"] == 1

    books = families["books_and_chapters"]["runtime"]
    assert "H1" in books["exercised_source_ids"]


def test_every_declared_family_has_contract_and_runtime_classifier():
    matrix = scm.build_source_capability_matrix({})

    assert matrix["schema_version"] == "ai1-source-capability-matrix-1.1"
    assert matrix["receipt_hardening_revision"] == 2
    assert matrix["valid"] is True
    assert matrix["contract_errors"] == []
    assert matrix["validation_errors"] == []
    assert matrix["unclassified_families"] == []
    assert matrix["runtime_classifier_count"] == matrix["family_count"]
    assert all(row["runtime"]["classifier_supported"] for row in matrix["families"])


def test_new_declared_family_without_classifier_fails_closed(monkeypatch):
    original = scm.implementation_matrix()
    synthetic = {
        "source_family": "synthetic_unwired_family",
        "discovery_path": ["synthetic discovery"],
        "read_or_inspection_path": ["synthetic reader"],
        "provenance_or_locator_proof": ["synthetic locator"],
        "implementation_status": scm.CONDITIONAL_RUNTIME,
        "condition": "test only",
        "limitation": "test only",
        "truth_boundary": "test evidence != truth",
    }
    monkeypatch.setattr(scm, "implementation_matrix", lambda: original + [synthetic])

    matrix = scm.build_source_capability_matrix({})

    assert matrix["valid"] is False
    assert "synthetic_unwired_family" in matrix["unclassified_families"]
    assert any(
        "synthetic_unwired_family: runtime classifier missing" in error
        for error in matrix["validation_errors"]
    )


def test_packet_reports_non_import_capability_failure_honestly(monkeypatch):
    sections = {
        "5. Strongest Sources": [],
        "11. Missing Evidence": [],
        "13. Highest-Value Second-Pass Research Tasks": [],
        "14. Confidence in Research Packet /100": {"score": 95},
        "15. Exactly What Prevents a Higher Score": [],
    }
    for index in range(10):
        sections[f"dummy-{index}"] = []
    assert len(sections) == 15

    monkeypatch.setattr(
        packet_ext,
        "build_source_capability_matrix",
        lambda result: {
            "valid": False,
            "validation_errors": ["synthetic_unwired_family: runtime classifier missing"],
            "missing_required_modules": [],
        },
    )
    result = {"ai1_research_packet": {"sections": sections}}

    packet_ext.extend_ai1_packet("test", result)

    confidence = sections["14. Confidence in Research Packet /100"]
    blockers = sections["15. Exactly What Prevents a Higher Score"]
    extension = result["ai1_research_packet"]["source_family_extension"]

    assert confidence["score"] == 60
    assert confidence["source_capability_validation_error_count"] == 1
    assert any("runtime classifier missing" in row for row in blockers)
    assert extension["valid"] is False
    assert extension["source_capability_validation_error_count"] == 1
