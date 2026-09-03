"""Lock the integrated cross-domain reliability batch into the release branch.

This is intentionally a cheap structural regression: Claude's 8-domain batch may
already be present in a branch whose Git ancestry has not yet recorded the merge.
These checks make sure the important fixes cannot disappear during a future sync.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cross_domain_benchmark_is_present():
    bench = _text("tests/benchmark_cross_domain.py")
    for marker in (
        "medicine", "materials", "energy", "engineering", "cs_ai",
        "archaeology", "economics", "biology",
    ):
        assert marker in bench


def test_cross_domain_root_cause_fixes_are_wired():
    domain = _text("research_engine/domain.py")
    contradiction = _text("research_engine/contradiction.py")
    orchestrator = _text("research_engine/orchestrator.py")
    labels = _text("research_engine/claim_labels.py")
    physics = _text("research_engine/physics_checks.py")
    hypothesis = _text("research_engine/hypothesis.py")
    relevance = _text("research_engine/relevance.py")

    assert "must: bool = False" in domain
    assert "_all_negated" in contradiction
    assert "merge_reports" in labels
    assert "merge_label_reports" in orchestrator
    assert "hypothesis_allowed" in orchestrator
    assert "_restated_from" in physics
    assert "allowed" in hypothesis
    assert "anchor_hits" in relevance and "branch_count" in relevance


def test_pytest_wrappers_exist_for_previously_script_only_suites():
    expected = {
        "tests/test_pdf_chunking.py": "def test_",
        "tests/test_answer_structure.py": "def test_",
        "tests/test_consensus_gate.py": "def test_",
        "tests/test_relevance_domain.py": "def test_",
    }
    for path, marker in expected.items():
        assert marker in _text(path), path
