import os

import pytest

from research_engine.holdout_vault import DoubleBlindCoordinator, HoldoutVault


def test_builder_view_never_exposes_holdout_bytes_token_or_storage_path(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    creation = vault.create(
        "V1", b"secret-final-data", dataset_label="final holdout", metadata={"rows": 1}
    )
    view = vault.builder_view("V1")
    assert view["state"] == "SEALED"
    serialized = repr(view)
    assert "secret-final-data" not in serialized
    assert creation.evaluator_token not in serialized
    assert str(tmp_path) not in serialized
    assert view["dataset_sha256_commitment"] == creation.dataset_sha256


def test_candidate_and_protocol_are_frozen_before_evaluation(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    vault.create("V1", b"1,2,3", dataset_label="holdout")
    frozen = vault.freeze_candidate(
        "V1",
        candidate_id="M1",
        implementation_hash="sha-code-1",
        protocol_hash="sha-protocol-1",
        evaluator_instructions={"metric": "sum"},
    )
    assert frozen["candidate_id"] == "M1"
    assert len(frozen["freeze_hash"]) == 64
    with pytest.raises(ValueError, match="only be frozen once"):
        vault.freeze_candidate(
            "V1",
            candidate_id="M2",
            implementation_hash="sha-code-2",
            protocol_hash="sha-protocol-2",
            evaluator_instructions={"metric": "mean"},
        )


def test_evaluation_requires_capability_token_and_is_one_shot(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    creation = vault.create("V1", b"1,2,3", dataset_label="holdout")
    vault.freeze_candidate(
        "V1",
        candidate_id="M1",
        implementation_hash="code-1",
        protocol_hash="protocol-1",
        evaluator_instructions={"metric": "sum"},
    )
    with pytest.raises(PermissionError):
        vault.evaluate("V1", evaluator_token="wrong", evaluator=lambda data, packet: {"score": 0})

    receipt = vault.evaluate(
        "V1",
        evaluator_token=creation.evaluator_token,
        evaluator=lambda data, packet: {
            "score": sum(int(value) for value in data.decode().split(",")),
            "candidate": packet["candidate"]["candidate_id"],
        },
    )
    assert receipt.result == {"score": 6, "candidate": "M1"}
    assert receipt.dataset_sha256 == creation.dataset_sha256
    assert len(receipt.result_hash) == 64

    with pytest.raises(ValueError):
        vault.evaluate(
            "V1",
            evaluator_token=creation.evaluator_token,
            evaluator=lambda data, packet: {"score": 999},
        )


def test_dataset_tampering_is_detected_before_evaluator_runs(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    creation = vault.create("V1", b"original", dataset_label="holdout")
    vault.freeze_candidate(
        "V1",
        candidate_id="M1",
        implementation_hash="code",
        protocol_hash="protocol",
        evaluator_instructions={},
    )
    with open(os.path.join(str(tmp_path), "V1.holdout"), "wb") as handle:
        handle.write(b"tampered")
    called = {"value": False}

    def evaluator(data, packet):
        called["value"] = True
        return {"score": 1}

    with pytest.raises(ValueError, match="integrity"):
        vault.evaluate("V1", evaluator_token=creation.evaluator_token, evaluator=evaluator)
    assert called["value"] is False
    assert vault.verify_integrity("V1") is False


def test_evaluator_failure_does_not_create_fake_success_receipt(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    creation = vault.create("V1", b"data", dataset_label="holdout")
    vault.freeze_candidate(
        "V1",
        candidate_id="M1",
        implementation_hash="code",
        protocol_hash="protocol",
        evaluator_instructions={},
    )

    def boom(data, packet):
        raise RuntimeError("evaluation crashed")

    with pytest.raises(RuntimeError, match="crashed"):
        vault.evaluate("V1", evaluator_token=creation.evaluator_token, evaluator=boom)
    assert vault.evaluation_receipt("V1") is None
    assert vault.builder_view("V1")["state"] == "FROZEN"


def test_double_blind_evaluator_packet_excludes_builder_theory_until_result_exists():
    coordinator = DoubleBlindCoordinator()
    coordinator.register(
        "E1",
        candidate_id="M1",
        builder_theory="liquidity sweep should reverse because X",
        implementation_hash="code-hash",
        protocol_hash="protocol-hash",
        evaluator_instructions={"metric": "profit_factor"},
    )
    packet = coordinator.evaluator_packet("E1")
    assert packet.candidate_id == "M1"
    assert "theory" not in repr(packet).lower()
    assert "liquidity" not in repr(packet).lower()

    with pytest.raises(ValueError, match="sealed"):
        coordinator.reveal_after_evaluation("E1")
    coordinator.record_result("E1", {"profit_factor": 1.4})
    revealed = coordinator.reveal_after_evaluation("E1")
    assert "liquidity sweep" in revealed["builder_theory"]
    assert revealed["result"]["profit_factor"] == 1.4


def test_duplicate_ids_and_bad_creation_inputs_fail_closed(tmp_path):
    vault = HoldoutVault(str(tmp_path))
    vault.create("V1", b"data", dataset_label="holdout")
    with pytest.raises(ValueError, match="already exists"):
        vault.create("V1", b"other", dataset_label="holdout")
    with pytest.raises(ValueError):
        vault.create("V2", b"", dataset_label="empty")

    coordinator = DoubleBlindCoordinator()
    coordinator.register(
        "E1",
        candidate_id="M1",
        builder_theory="theory",
        implementation_hash="code",
        protocol_hash="protocol",
        evaluator_instructions={},
    )
    with pytest.raises(ValueError, match="already exists"):
        coordinator.register(
            "E1",
            candidate_id="M2",
            builder_theory="other",
            implementation_hash="code2",
            protocol_hash="protocol2",
            evaluator_instructions={},
        )
