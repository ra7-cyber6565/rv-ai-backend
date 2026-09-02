import os

import pytest

from research_engine.holdout_vault import DoubleBlindCoordinator, HoldoutVault


def test_invalid_label_never_leaves_orphan_holdout_bytes(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    with pytest.raises(ValueError, match="dataset_label"):
        vault.create("V1", b"secret", dataset_label="   ")
    assert not os.path.exists(tmp_path / "V1.holdout")
    assert not os.path.exists(tmp_path / "V1.json")


def test_non_json_metadata_fails_before_persistence_and_cleans_data(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    with pytest.raises(TypeError):
        vault.create("V1", b"secret", dataset_label="holdout", metadata={"bad": object()})
    assert not os.path.exists(tmp_path / "V1.holdout")
    assert not os.path.exists(tmp_path / "V1.json")


def test_double_blind_registration_requires_frozen_protocol_identity():
    coordinator = DoubleBlindCoordinator()
    with pytest.raises(ValueError, match="implementation_hash"):
        coordinator.register(
            "E1", candidate_id="M1", builder_theory="theory",
            implementation_hash="", protocol_hash="protocol", evaluator_instructions={},
        )
    with pytest.raises(ValueError, match="protocol_hash"):
        coordinator.register(
            "E2", candidate_id="M1", builder_theory="theory",
            implementation_hash="code", protocol_hash="", evaluator_instructions={},
        )


def test_non_finite_blind_result_is_rejected():
    coordinator = DoubleBlindCoordinator()
    coordinator.register(
        "E1", candidate_id="M1", builder_theory="theory",
        implementation_hash="code", protocol_hash="protocol", evaluator_instructions={},
    )
    with pytest.raises(ValueError, match="finite JSON"):
        coordinator.record_result("E1", {"score": float("nan")})
    with pytest.raises(ValueError, match="sealed"):
        coordinator.reveal_after_evaluation("E1")


def test_missing_holdout_file_integrity_returns_false(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    vault.create("V1", b"data", dataset_label="holdout")
    os.remove(tmp_path / "V1.holdout")
    assert vault.verify_integrity("V1") is False
