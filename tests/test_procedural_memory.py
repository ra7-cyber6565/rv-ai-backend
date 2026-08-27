import pytest

from research_engine.procedural_memory import ProceduralMemory


def _memory(tmp_path):
    return ProceduralMemory(str(tmp_path), project_id="P1")


def test_same_recipe_is_deduplicated_with_stable_fingerprint(tmp_path):
    memory = _memory(tmp_path)
    one = memory.add_version("PROC1", name="Backtest", steps=["certify data", "run holdout"])
    two = memory.add_version("PROC1", name="Backtest", steps=["certify data", "run holdout"])
    assert one["version"] == 1
    assert two["version"] == 1
    assert one["fingerprint"] == two["fingerprint"]
    assert len(memory.load()["procedures"]["PROC1"]) == 1


def test_changed_recipe_creates_new_version_instead_of_mutating_old(tmp_path):
    memory = _memory(tmp_path)
    v1 = memory.add_version("PROC1", name="Method", steps=["A", "B"])
    v2 = memory.add_version("PROC1", name="Method", steps=["A", "B", "C"])
    assert v1["version"] == 1
    assert v2["version"] == 2
    assert v1["fingerprint"] != v2["fingerprint"]


def test_procedure_cannot_be_promoted_from_one_lucky_run(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("PROC1", name="Method", steps=["A"])
    memory.record_outcome("PROC1", 1, run_id="R1", context_id="C1", success=True)
    result = memory.evaluate_promotion("PROC1", 1)
    assert result["promoted"] is False
    assert "insufficient successful runs" in result["reasons"]
    assert memory.recommend() == []


def test_repeated_success_across_contexts_promotes_procedure(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("PROC1", name="Method", steps=["A"])
    for run_id, context in [("R1", "C1"), ("R2", "C2"), ("R3", "C1")]:
        memory.record_outcome("PROC1", 1, run_id=run_id, context_id=context, success=True, evidence_ids=[run_id])
    result = memory.evaluate_promotion("PROC1", 1)
    assert result["promoted"] is True
    assert result["summary"]["successes"] == 3
    assert result["summary"]["distinct_contexts"] == 2
    assert memory.recommend()[0]["status"] == "PROMOTED"


def test_failure_rate_blocks_promotion_even_with_multiple_successes(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("PROC1", name="Method", steps=["A"])
    for i in range(3):
        memory.record_outcome("PROC1", 1, run_id=f"S{i}", context_id=f"C{i%2}", success=True)
    memory.record_outcome("PROC1", 1, run_id="F1", context_id="C3", success=False, failure_class="DATA_LEAKAGE")
    memory.record_outcome("PROC1", 1, run_id="F2", context_id="C4", success=False, failure_class="OVERFIT")
    result = memory.evaluate_promotion("PROC1", 1, max_failure_rate=0.25)
    assert result["promoted"] is False
    assert "failure rate exceeds threshold or is unknown" in result["reasons"]
    assert result["summary"]["failure_classes"] == ["DATA_LEAKAGE", "OVERFIT"]


def test_failed_outcome_requires_failure_class_and_duplicate_run_is_rejected(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("PROC1", name="Method", steps=["A"])
    with pytest.raises(ValueError, match="failure_class"):
        memory.record_outcome("PROC1", 1, run_id="F1", context_id="C1", success=False)
    memory.record_outcome("PROC1", 1, run_id="R1", context_id="C1", success=True)
    with pytest.raises(ValueError, match="already recorded"):
        memory.record_outcome("PROC1", 1, run_id="R1", context_id="C2", success=True)


def test_cross_procedure_duplicate_recipe_is_reported_non_destructively(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("P1", name="Same", steps=["A", "B"])
    memory.add_version("P2", name="Same", steps=["A", "B"])
    groups = memory.duplicate_recipe_groups()
    assert len(groups) == 1
    assert groups[0]["members"] == ["P1:v1", "P2:v1"]
    assert "P1" in memory.load()["procedures"] and "P2" in memory.load()["procedures"]


def test_persistence_roundtrip_keeps_promotion_evidence(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("PROC1", name="Method", steps=["A"])
    for run_id, context in [("R1", "C1"), ("R2", "C2"), ("R3", "C2")]:
        memory.record_outcome("PROC1", 1, run_id=run_id, context_id=context, success=True)
    memory.evaluate_promotion("PROC1", 1)
    memory.save()
    reloaded = _memory(tmp_path)
    recommended = reloaded.recommend()
    assert recommended[0]["status"] == "PROMOTED"
    assert recommended[0]["promotion_evidence"]["successes"] == 3


def test_invalid_metrics_and_thresholds_fail_closed(tmp_path):
    memory = _memory(tmp_path)
    memory.add_version("PROC1", name="Method", steps=["A"])
    with pytest.raises(ValueError):
        memory.record_outcome("PROC1", 1, run_id="R1", context_id="C1", success=True, metrics={"x": float("nan")})
    with pytest.raises(ValueError):
        memory.evaluate_promotion("PROC1", 1, min_successes=0)
