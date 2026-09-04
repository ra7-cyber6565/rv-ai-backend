import base64

from research_engine.agent_manager import AgentManager
from research_engine.ai1_structured_runtime import (
    AI1StructuredSourceDiscovery,
    AI1StructuredSourceInspector,
    StructuredAwareContentFetcher,
    code_lane_relevant,
)
from research_engine.connectors import code_repository_connector as github_code
from research_engine.content_fetcher import ContentFetcher
from research_engine.deep_source_integrity import build_deep_source_integrity_report
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.structured_source_reader import StructuredSourceRecord


def _plan(**extra):
    base = {
        "web": False,
        "papers": [],
        "books": [],
        "datasets": [],
        "patents": [],
        "markets": [],
        "classics": [],
        "classic_queries": [],
        "summary_queries": [],
        "official_archive_queries": [],
        "book_queries": [],
        "craft_study": [],
        "listener_study": [],
        "music_study": [],
        "trade_study": [],
        "exam_study": [],
        "domain": "generic",
        "useful_source_types": [],
    }
    base.update(extra)
    return base


def test_code_lane_is_relevance_gated_not_global():
    assert code_lane_relevant(_plan(domain="cs_ml"), "attention mechanism") is True
    assert code_lane_relevant(_plan(), "inspect this GitHub repository implementation") is True
    assert code_lane_relevant(
        _plan(domain="archaeology_history", useful_source_types=["archives", "books"]),
        "Harappan chronology evidence",
    ) is False


def test_structured_discovery_adds_github_only_for_technical_plan():
    discovery = AI1StructuredSourceDiscovery(max_workers=1)
    technical = discovery._tasks(
        ["transformer implementation"],
        _plan(domain="cs_ml", useful_source_types=["code", "papers"]),
        2,
        4,
    )
    historical = discovery._tasks(
        ["Harappan chronology evidence"],
        _plan(domain="archaeology_history", useful_source_types=["archives"]),
        2,
        4,
    )
    assert "github_code" in [label for label, _call in technical]
    assert "github_code" not in [label for label, _call in historical]


def test_series_meta_becomes_real_bounded_dataset_passage_without_network():
    source = SourceRecord(
        source_id="D1",
        title="Official indicator series",
        url="https://data.example.invalid/series",
        connector="world_bank_series",
        source_type=SourceType.DATASET,
        read_level="full_text",
        full_text_available=True,
        full_text_chars=1200,
        series_meta={
            "points": [
                {"period": "2021", "value": 10.0},
                {"period": "2022", "value": 12.0},
                {"period": "2023", "value": 11.0},
            ]
        },
    )
    pack = EvidencePack(question="How did this indicator change?", sources=[source])
    report = AI1StructuredSourceInspector(allow_network=False).enrich(
        pack, max_sources=1)

    assert report["dataset_inspected"] == 1
    upgraded = pack.sources[0]
    assert isinstance(upgraded, StructuredSourceRecord)
    assert upgraded.dataset_inspection["rows_inspected"] == 3
    assert upgraded.dataset_inspection["complete_dataset"] is False
    assert upgraded.dataset_inspection["truth_boundary"]
    assert upgraded.dataset_inspection["non_structured_text_chars_before_inspection"] == 1200
    assert upgraded.reading_level() == "sections"
    assert upgraded.access_depth() == "RELEVANT SECTIONS REVIEWED"
    assert upgraded.full_text_available is False
    assert upgraded.full_text_chars == 0
    assert pack.read_level_counts().get("sections") == 1
    assert pack.full_text_read_count == 0
    assert pack.passages
    assert pack.passages[0].provenance == "structured_dataset_rows"
    assert pack.passages[0].read_level_at_capture == "sections"
    assert "Sample row" in pack.passages[0].text

    deep = build_deep_source_integrity_report(
        {"passages": [p.to_dict() for p in pack.passages]},
        [upgraded.to_dict()],
    )
    assert deep["sources"][0]["deep_status"] == "DATA INSPECTED"
    assert deep["sources"][0]["access_depth"] == "RELEVANT SECTIONS REVIEWED"


def test_code_inspector_reads_source_file_not_readme_and_never_claims_execution(monkeypatch):
    code = (
        "def score_evidence(rows):\n"
        "    total = sum(row['score'] for row in rows)\n"
        "    return total / max(1, len(rows))\n"
    )

    def fake_github_json(url, **kwargs):
        if url.endswith("/repos/example/project"):
            return {"default_branch": "main"}
        if "/git/trees/" in url:
            return {
                "sha": "abc123tree",
                "truncated": False,
                "tree": [
                    {"path": "README.md", "type": "blob", "size": 100},
                    {"path": "src/evidence.py", "type": "blob", "size": len(code)},
                ],
            }
        if "/contents/src/evidence.py" in url:
            return {
                "encoding": "base64",
                "content": base64.b64encode(code.encode("utf-8")).decode("ascii"),
            }
        raise AssertionError(f"unexpected GitHub call: {url}")

    monkeypatch.setattr(github_code, "github_json", fake_github_json)
    source = SourceRecord(
        source_id="R1",
        title="example/project",
        url="https://github.com/example/project",
        connector="github_code",
        source_type=SourceType.WEB,
        read_level="snippet",
        doc_kind="code_repository",
    )
    pack = EvidencePack(question="How is evidence score computed?", sources=[source])
    report = AI1StructuredSourceInspector(allow_network=True).enrich(
        pack, max_sources=1)

    assert report["code_inspected"] == 1
    upgraded = pack.sources[0]
    assert upgraded.code_files == ["src/evidence.py"]
    assert upgraded.code_inspection["executed"] is False
    assert upgraded.code_inspection["tests_run"] is False
    assert upgraded.code_inspection["repository_complete"] is False
    assert upgraded.reading_level() == "sections"
    assert upgraded.access_depth() == "RELEVANT SECTIONS REVIEWED"
    assert all("README" not in path for path in upgraded.code_files)
    assert pack.passages[0].provenance == "public_code_file_excerpt"
    assert pack.passages[0].read_level_at_capture == "sections"
    assert "src/evidence.py:L" in pack.passages[0].locator

    deep = build_deep_source_integrity_report(
        {"passages": [p.to_dict() for p in pack.passages]},
        [upgraded.to_dict()],
    )
    assert deep["sources"][0]["deep_status"] == "CODE INSPECTED"
    assert deep["sources"][0]["access_depth"] == "RELEVANT SECTIONS REVIEWED"


def test_structured_content_fetcher_runs_after_ordinary_reader(monkeypatch):
    calls = []

    def fake_document_enrich(self, pack, max_sources=3, budget_chars=2400):
        calls.append("document")
        return {"attempted": 0, "succeeded": 0, "note": "ordinary reader ran"}

    monkeypatch.setattr(ContentFetcher, "enrich", fake_document_enrich)
    fetcher = StructuredAwareContentFetcher(allow_network=False)

    def fake_structured(pack, max_sources=3, budget_chars=2400):
        calls.append("structured")
        return {
            "attempted": 1,
            "succeeded": 1,
            "dataset_inspected": 1,
            "code_inspected": 0,
            "note": "structured reader ran",
        }

    monkeypatch.setattr(fetcher.structured, "enrich", fake_structured)
    report = fetcher.enrich(EvidencePack(question="q", sources=[]), max_sources=2)

    assert calls == ["document", "structured"]
    assert report["structured"]["dataset_inspected"] == 1
    assert "Structured: structured reader ran" in report["note"]


def test_agent_manager_production_engine_is_structured_aware():
    manager = AgentManager()
    engine = manager.get("ai1-structured-runtime-test")
    assert isinstance(engine.discovery, AI1StructuredSourceDiscovery)
    assert isinstance(engine.reader, StructuredAwareContentFetcher)
    assert isinstance(engine.reader.structured, AI1StructuredSourceInspector)


def test_readme_only_repository_stays_uninspected_when_code_reader_has_no_code(monkeypatch):
    def fake_github_json(url, **kwargs):
        if url.endswith("/repos/example/readme-only"):
            return {"default_branch": "main"}
        if "/git/trees/" in url:
            return {
                "sha": "readme-tree",
                "truncated": False,
                "tree": [{"path": "README.md", "type": "blob", "size": 500}],
            }
        raise AssertionError(f"unexpected GitHub call: {url}")

    monkeypatch.setattr(github_code, "github_json", fake_github_json)
    source = SourceRecord(
        source_id="R2",
        title="example/readme-only",
        url="https://github.com/example/readme-only",
        connector="github_code",
        source_type=SourceType.WEB,
        read_level="full_text",
        full_text_chars=5000,
        doc_kind="code_repository",
    )
    pack = EvidencePack(question="inspect implementation", sources=[source])
    report = AI1StructuredSourceInspector(allow_network=True).enrich(
        pack, max_sources=1)

    assert report["code_inspected"] == 0
    assert report["failed"] == 1
    # Failed inspection may not launder the pre-existing page/full-text marker
    # into code proof. Deep-source family semantics must still block it.
    deep = build_deep_source_integrity_report({}, [pack.sources[0].to_dict()])
    assert deep["sources"][0]["deep_status"] != "CODE INSPECTED"
    assert deep["blocking_gap_count"] >= 1
