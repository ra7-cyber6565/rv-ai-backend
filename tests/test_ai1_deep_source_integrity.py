from research_engine.ai1_research_director import build_ai1_research_packet
from research_engine.deep_source_integrity import (
    CODE_INSPECTION_REQUIRED,
    DATA_INSPECTION_REQUIRED,
    TRANSCRIPT_REQUIRED,
    TRANSLATION_REVIEW_REQUIRED,
    access_depth,
    build_deep_source_integrity_report,
)
from research_engine.connectors import media_connector as media


def test_partial_large_pdf_never_becomes_full_text_from_chars_alone():
    source = {
        "source_id": "S1",
        "source_type": "paper",
        "read_level": "full_text",
        "full_text_chars": 50_000,
        "pages_read": 12,
        "pages_total": 400,
    }
    assert access_depth(source) == "RELEVANT SECTIONS REVIEWED"
    report = build_deep_source_integrity_report({}, [source])
    row = report["sources"][0]
    assert row["deep_status"] == "DEEP TEXT REVIEWED"
    assert row["access_depth"] == "RELEVANT SECTIONS REVIEWED"


def test_dataset_landing_page_is_not_data_inspection_even_with_text():
    source = {
        "source_id": "D1",
        "source_type": "dataset",
        "read_level": "full_text",
        "full_text_chars": 9000,
        "title": "Dataset catalogue page",
    }
    report = build_deep_source_integrity_report({}, [source])
    assert report["deep_evidence_source_count"] == 0
    assert any(gap["code"] == DATA_INSPECTION_REQUIRED for gap in report["gaps"])

    inspected = dict(source)
    inspected["series_meta"] = {"series": "GDP", "observations": 120}
    report2 = build_deep_source_integrity_report({}, [inspected])
    assert report2["sources"][0]["deep_status"] == "DATA INSPECTED"


def test_repository_readme_is_not_code_inspection():
    source = {
        "source_id": "R1",
        "source_type": "web",
        "url": "https://github.com/example/project",
        "read_level": "full_text",
        "title": "README",
    }
    report = build_deep_source_integrity_report({}, [source])
    assert any(gap["code"] == CODE_INSPECTION_REQUIRED for gap in report["gaps"])

    inspected = dict(source)
    inspected["code_files"] = ["src/core.py", "tests/test_core.py"]
    report2 = build_deep_source_integrity_report({}, [inspected])
    assert report2["sources"][0]["deep_status"] == "CODE INSPECTED"


def test_archive_description_is_not_transcript_but_caption_text_is():
    shallow = {
        "source_id": "M1",
        "source_type": "transcript",
        "connector": "archive_media",
        "read_level": "snippet",
        "snippet": "uploader description only",
    }
    report = build_deep_source_integrity_report({}, [shallow])
    assert report["sources"][0]["source_family"] == "media_recording"
    assert any(gap["code"] == TRANSCRIPT_REQUIRED for gap in report["gaps"])

    transcript = dict(shallow)
    transcript.update({
        "read_level": "full_text",
        "full_text_chars": 6000,
        "locator": "12:30–14:30",
    })
    report2 = build_deep_source_integrity_report({}, [transcript])
    assert report2["sources"][0]["source_family"] == "media_transcript"
    assert report2["sources"][0]["deep_status"] == "TRANSCRIPT REVIEWED"


def test_claimed_translation_fails_closed_without_independent_agreement():
    source = {
        "source_id": "T1",
        "source_type": "paper",
        "read_level": "full_text",
        "translated": True,
        "original_language": "ja",
    }
    report = build_deep_source_integrity_report({}, [source])
    assert any(gap["code"] == TRANSLATION_REVIEW_REQUIRED for gap in report["gaps"])

    source["translation_integrity"] = {
        "method": "translation",
        "verification_verdict": "AGREEMENT_OK",
        "review_required": False,
    }
    report2 = build_deep_source_integrity_report({}, [source])
    assert not any(gap["code"] == TRANSLATION_REVIEW_REQUIRED for gap in report2["gaps"])


def test_ai1_packet_exposes_deep_source_audit_without_breaking_15_sections():
    result = {
        "status": "COMPLETE",
        "sources": [{
            "source_id": "D1",
            "title": "Catalogue only",
            "source_type": "dataset",
            "read_level": "full_text",
            "quality_score": 0.8,
            "relevance_score": 0.9,
        }],
        "verification": {},
        "quality_context": {"counter_search_performed": True},
        "source_integrity": {"high_risk": False},
    }
    packet = build_ai1_research_packet("Analyse this dataset", result)
    assert len(packet["sections"]) == 15
    assert packet["validation"]["valid"] is True
    assert packet["deep_source_integrity"]["audited_source_count"] == 1
    missing_codes = {row["code"] for row in packet["sections"]["11. Missing Evidence"]}
    assert DATA_INSPECTION_REQUIRED in missing_codes
    strongest = packet["sections"]["5. Strongest Sources"][0]
    assert strongest["source_family"] == "dataset"
    assert strongest["deep_source_status"] == "SHALLOW"
    assert packet["sections"]["14. Confidence in Research Packet /100"]["deep_source_blocking_gaps"] >= 1


class _Response:
    def __init__(self, *, payload=None, text=""):
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _search_payload():
    return {
        "response": {
            "docs": [{
                "identifier": "item123",
                "title": "Public Lecture",
                "description": "A sufficiently long uploader description about the lecture and its subject.",
                "creator": "Speaker",
                "mediatype": "audio",
                "year": 2024,
            }]
        }
    }


def test_archive_media_connector_upgrades_only_when_public_caption_is_read(monkeypatch):
    vtt = """WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nThis is a public lecture about causal inference and evidence quality.\n\n00:02:10.000 --> 00:02:20.000\nThe speaker explains replication, measurement error, and why counter evidence matters in research. This caption text is intentionally long enough for the safety threshold.\n"""
    responses = [
        _Response(payload=_search_payload()),
        _Response(payload={"files": [{"name": "lecture.vtt", "format": "Web Video Text Tracks"}]}),
        _Response(text=vtt),
    ]

    def fake_get(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(media, "http_get", fake_get)
    rows = media.MediaArchiveConnector().search("causal inference evidence", 1)
    assert len(rows) == 1
    record = rows[0]
    assert record.read_level == "full_text"
    assert record.full_text_available is True
    assert record.full_text_chars >= len(vtt)
    assert record.locator
    assert "Media file" in record.read_note


def test_archive_media_connector_falls_back_to_snippet_without_caption(monkeypatch):
    responses = [
        _Response(payload=_search_payload()),
        _Response(payload={"files": [{"name": "recording.mp3"}]}),
    ]

    def fake_get(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(media, "http_get", fake_get)
    rows = media.MediaArchiveConnector().search("research lecture", 1)
    assert len(rows) == 1
    record = rows[0]
    assert record.read_level == "snippet"
    assert record.full_text_available is False
    assert record.full_text_chars == 0


def test_lyrics_hunt_never_touches_network(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network should not be called")

    monkeypatch.setattr(media, "http_get", explode)
    connector = media.MediaArchiveConnector()
    assert connector.search("latest song lyrics mp3 download", 1) == []
    assert connector.last_reason == "lyrics_hunt_blocked"
