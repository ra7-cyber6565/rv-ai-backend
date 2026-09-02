from types import SimpleNamespace

import research_engine.orchestrator as orchestrator_module
from research_engine.depth import get_depth_config
from research_engine.orchestrator import DeepResearchEngine


class _Discovery:
    def __init__(self):
        self.rounds = []

    def discover(self, **kwargs):
        round_no = int(kwargs["round_no"])
        self.rounds.append(round_no)
        return {
            "records": [object()],
            "log": [],
            "connectors_searched": ["fake"],
            "seen_urls": {f"https://example.test/{round_no}"},
        }


class _Evidence:
    def build_pack(self, **kwargs):
        return SimpleNamespace(
            sources=[object(), object(), object()],
            independent_source_count=3,
            on_topic_count=3,
            document_sources=lambda: [],
        )

    def needs_another_round(self, pack, is_scientific=False):
        return {"sufficient": True, "reasons": []}


class _Planner:
    def __init__(self):
        self.absorbed = 0

    def search_queries(self, question, plan, round_no=1):
        return [f"query round {round_no}"]

    def clean_query(self, question):
        return question

    def absorb_corpus_lenses(self, question, records):
        self.absorbed += 1
        return {}


def test_marathon_runs_every_round_even_when_round_one_is_sufficient(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "axes_for", lambda question: [
        SimpleNamespace(mandatory=True, to_dict=lambda: {
            "axis_id": "counter_evidence", "mandatory": True,
        })
    ])
    rows = [{"axis_id": "counter_evidence", "mandatory": True,
             "status": "COVERED"}]
    monkeypatch.setattr(orchestrator_module, "axis_coverage",
                        lambda axes, sources, searched=None: rows)
    monkeypatch.setattr(orchestrator_module, "coverage_summary",
                        lambda records: {"mandatory_missing": 0})
    monkeypatch.setattr(orchestrator_module, "counter_search_done",
                        lambda records: True)
    monkeypatch.setattr(orchestrator_module, "axes_next_queries",
                        lambda *args, **kwargs: [])

    engine = DeepResearchEngine(enable_kg=False, enable_memory=False)
    discovery = _Discovery()
    planner = _Planner()
    engine.discovery = discovery
    engine.evidence = _Evidence()
    engine.planner = planner
    result = engine._discover(
        "question", {"connectors": {}}, get_depth_config("MARATHON"), [], None,
    )

    assert discovery.rounds == [1, 2, 3, 4, 5]
    assert result["rounds_run"] == 5
    assert len(result["round_metrics"]) == 5
    assert result["counter_search_performed"] is True
    assert planner.absorbed == 4
