import pytest

from research_engine.synthetic_data_boundary import DataArtifact, enforce_synthetic_boundary


def test_real_holdout_with_real_lineage_is_eligible_but_not_truth_proof():
    report = enforce_synthetic_boundary([
        DataArtifact("raw", "REAL", "REFERENCE", source_ref="dataset://raw-v1"),
        DataArtifact("train", "REAL", "TRAIN", parent_ids=("raw",)),
        DataArtifact("holdout", "REAL", "HOLDOUT", parent_ids=("raw",)),
    ])
    assert report.violations == ()
    assert report.real_world_validation_eligible is True
    assert report.synthetic_evidence_can_prove_real_world_effect is False
    assert report.truth_proven is False


def test_synthetic_training_is_allowed_when_real_holdout_remains_real():
    report = enforce_synthetic_boundary([
        DataArtifact("raw", "REAL", "REFERENCE", source_ref="dataset://raw"),
        DataArtifact("synthetic-train", "SYNTHETIC", "TRAIN", parent_ids=("raw",), generator_id="gen-v1"),
        DataArtifact("holdout", "REAL", "HOLDOUT", parent_ids=("raw",)),
    ])
    assert report.real_world_validation_eligible is True
    synthetic = next(item for item in report.artifacts if item.artifact_id == "synthetic-train")
    assert synthetic.effective_lineage == "SYNTHETIC"


def test_synthetic_to_real_relabel_laundering_is_detected_and_blocks_validation():
    report = enforce_synthetic_boundary([
        DataArtifact("real-seed", "REAL", "REFERENCE", source_ref="dataset://seed"),
        DataArtifact("generated", "SYNTHETIC", "TRAIN", parent_ids=("real-seed",), generator_id="gen"),
        DataArtifact("laundered", "REAL", "HOLDOUT", parent_ids=("generated",)),
    ])
    row = next(item for item in report.artifacts if item.artifact_id == "laundered")
    assert row.effective_lineage == "MIXED"
    assert "synthetic lineage cannot be relabelled REAL" in row.violations
    assert report.real_world_validation_eligible is False


def test_unknown_lineage_cannot_become_real_through_transformation():
    report = enforce_synthetic_boundary([
        DataArtifact("mystery", "UNKNOWN", "REFERENCE"),
        DataArtifact("derived", "REAL", "VALIDATION", parent_ids=("mystery",)),
    ])
    derived = next(item for item in report.artifacts if item.artifact_id == "derived")
    assert derived.effective_lineage == "UNKNOWN"
    assert derived.unknown_ancestor is True
    assert report.real_world_validation_eligible is False


def test_validation_or_holdout_must_exist_for_real_world_validation():
    report = enforce_synthetic_boundary([
        DataArtifact("raw", "REAL", "REFERENCE", source_ref="dataset://raw"),
        DataArtifact("train", "REAL", "TRAIN", parent_ids=("raw",)),
    ])
    assert report.real_world_validation_eligible is False
    assert "no REAL validation or holdout artifact was declared" in report.violations


def test_cycle_and_unknown_parent_fail_closed():
    with pytest.raises(ValueError, match="cycle"):
        enforce_synthetic_boundary([
            DataArtifact("a", "REAL", "REFERENCE", parent_ids=("b",), source_ref="x"),
            DataArtifact("b", "REAL", "REFERENCE", parent_ids=("a",), source_ref="y"),
        ])
    with pytest.raises(ValueError, match="unknown parents"):
        enforce_synthetic_boundary([
            DataArtifact("a", "REAL", "VALIDATION", parent_ids=("missing",), source_ref="x")
        ])


def test_synthetic_root_requires_generator_and_real_root_requires_source():
    with pytest.raises(ValueError, match="generator_id"):
        enforce_synthetic_boundary([DataArtifact("s", "SYNTHETIC", "TRAIN")])
    with pytest.raises(ValueError, match="source_ref"):
        enforce_synthetic_boundary([DataArtifact("r", "REAL", "HOLDOUT")])


def test_report_hash_is_deterministic_under_input_order_changes():
    rows = [
        DataArtifact("raw", "REAL", "REFERENCE", source_ref="dataset://raw"),
        DataArtifact("train", "SYNTHETIC", "TRAIN", parent_ids=("raw",), generator_id="gen"),
        DataArtifact("holdout", "REAL", "HOLDOUT", parent_ids=("raw",)),
    ]
    first = enforce_synthetic_boundary(rows)
    second = enforce_synthetic_boundary(list(reversed(rows)))
    assert first.report_hash == second.report_hash
    assert first.real_world_validation_eligible == second.real_world_validation_eligible
