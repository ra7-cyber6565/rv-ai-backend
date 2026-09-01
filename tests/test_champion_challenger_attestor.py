import hashlib
import hmac
import json
from pathlib import Path

import pytest

import research_engine.champion_challenger_attestor as cc_attestor
from research_engine.capability_registry import ProofKind
from research_engine.champion_challenger_attestor import (
    attest_champion_challenger_live,
    attest_champion_challenger_software,
    run_champion_challenger_benchmark,
    validate_champion_challenger_live_receipt,
)
from research_engine.maturity_proof import ProofLedger
from research_engine.scientific_memory import ScientificMemory
from utils.release_identity import repository_identity


KEY = b"C" * 32
OBSERVER_KEY = b"L" * 32
NOW = 120_000.0


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _live_state(tmp_path):
    directory = tmp_path / "live-memory"
    memory = ScientificMemory("live-project", directory=str(directory))
    memory.register_model(
        "champion-v1",
        metrics={"quality": 0.80, "loss": 0.20},
        holdout_id="holdout-a",
        implementation_hash="implementation-a",
        independent_validation_ids=("validation-a",),
        status="champion",
    )
    memory.register_model(
        "challenger-v2",
        metrics={"quality": 0.90, "loss": 0.10},
        holdout_id="holdout-b",
        implementation_hash="implementation-b",
        independent_validation_ids=("validation-b",),
        status="challenger",
    )
    decision = memory.promote_challenger(
        "champion-v1",
        "challenger-v2",
        objectives={"quality": "max", "loss": "min"},
        require_independent_validation=True,
        require_distinct_holdout=True,
    )
    assert decision.promoted is True
    memory.save()
    state_path = Path(memory.path)
    return memory, state_path


def _signed_live_receipt(tmp_path, state_path, *, mutate=None, created=119_900):
    revision = str(repository_identity(_root())["revision"])
    memory = ScientificMemory("live-project", directory=str(state_path.parent))
    integrity = memory.audit_integrity()
    payload = {
        "schema_version": 1,
        "created_at_epoch": created,
        "implementation_revision": revision,
        "project_id": "live-project",
        "prior_champion_id": "champion-v1",
        "promoted_challenger_id": "challenger-v2",
        "deployment_id": "deployment-1",
        "runtime_instance_id": "runtime-1",
        "observer_id": "observer-1",
        "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "audit_head_hash": integrity["head_hash"],
        "objectives": {"quality": "max", "loss": "min"},
        "observation_window_start_epoch": created - 800,
        "observation_window_end_epoch": created - 100,
        "live_data_source_ids": ["source-1"],
        "evaluation_ids": ["eval-1", "eval-2"],
        "champion_challenger_comparison_observed": True,
        "promotion_decision_observed": True,
        "persistent_state_reloaded": True,
        "runtime_observation_complete": True,
        "live_observation_complete": True,
        "automatic_ungated_promotion_observed": False,
        "truth_proven": False,
    }
    if mutate:
        mutate(payload)
    payload["signature"] = hmac.new(OBSERVER_KEY, _canonical(payload), hashlib.sha256).hexdigest()
    path = tmp_path / f"live-{len(list(tmp_path.glob('live-*.json')))}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path, payload


def test_offline_benchmark_is_logically_reproducible_and_fail_closed(tmp_path):
    first = run_champion_challenger_benchmark(tmp_path)
    second = run_champion_challenger_benchmark(tmp_path)
    assert first["benchmark_passed"] is True
    assert second["benchmark_passed"] is True
    assert first["logical_sha256"] == second["logical_sha256"]
    assert first["checks"] == second["checks"]
    assert first["truth_proven"] is False
    assert first["live_operation_proven"] is False
    assert first["future_superiority_proven"] is False


def test_offline_roles_are_separate_and_never_mint_runtime_live(tmp_path):
    ledger_path = tmp_path / "proofs.jsonl"
    storage = tmp_path / "storage"
    anchor = ""
    revision = ""
    expected = []
    for index, (kind, reference) in enumerate((
        (ProofKind.EXECUTION, "execution:c89:ci"),
        (ProofKind.REPRODUCIBILITY, "reproducibility:c89:ci"),
        (ProofKind.PERSISTENCE, "persistence:c89:ci"),
    )):
        result = attest_champion_challenger_software(
            repo_root=_root(),
            storage_root=storage,
            ledger_path=ledger_path,
            integrity_key=KEY,
            proof_kind=kind,
            run_reference=reference,
            now=NOW + index,
            prior_anchor_token=anchor,
            prior_revision=revision,
        )
        anchor = result.anchor_token
        revision = result.revision
        expected.append(kind.value)
        assert result.proof_kind == kind.value
        assert result.truth_proven is False
        assert result.future_superiority_proven is False

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert [row["proof_kind"] for row in rows] == expected
    assert ProofKind.RUNTIME.value not in expected
    assert ProofKind.LIVE.value not in expected


def test_software_attestor_refuses_runtime_and_live(tmp_path):
    for kind in (ProofKind.RUNTIME, ProofKind.LIVE):
        with pytest.raises(ValueError, match="only accepts execution/reproducibility/persistence"):
            attest_champion_challenger_software(
                repo_root=_root(),
                storage_root=tmp_path / "storage",
                ledger_path=tmp_path / f"{kind.value}.jsonl",
                integrity_key=KEY,
                proof_kind=kind,
                run_reference=f"{kind.value}:c89:ci",
                now=NOW,
            )


def test_live_receipt_binds_exact_state_and_promotion(tmp_path):
    _memory, state_path = _live_state(tmp_path)
    receipt_path, _payload = _signed_live_receipt(tmp_path, state_path)
    validated = validate_champion_challenger_live_receipt(
        memory_state_path=state_path,
        observer_receipt_path=receipt_path,
        observer_key=OBSERVER_KEY,
        expected_revision=str(repository_identity(_root())["revision"]),
        now=NOW,
    )
    assert validated.prior_champion_id == "champion-v1"
    assert validated.promoted_challenger_id == "challenger-v2"
    assert validated.objectives == {"quality": "max", "loss": "min"}
    assert validated.live_data_source_ids == ("source-1",)
    assert validated.evaluation_ids == ("eval-1", "eval-2")


def test_runtime_and_live_receipts_are_separate_and_expire_from_observer_time(tmp_path):
    _memory, state_path = _live_state(tmp_path)
    receipt_path, _payload = _signed_live_receipt(tmp_path, state_path)
    ledger_path = tmp_path / "live-proofs.jsonl"

    runtime = attest_champion_challenger_live(
        repo_root=_root(),
        memory_state_path=state_path,
        observer_receipt_path=receipt_path,
        observer_key=OBSERVER_KEY,
        ledger_path=ledger_path,
        integrity_key=KEY,
        proof_kind=ProofKind.RUNTIME,
        run_reference="runtime:c89:deployment-1",
        now=NOW,
    )
    live = attest_champion_challenger_live(
        repo_root=_root(),
        memory_state_path=state_path,
        observer_receipt_path=receipt_path,
        observer_key=OBSERVER_KEY,
        ledger_path=ledger_path,
        integrity_key=KEY,
        proof_kind=ProofKind.LIVE,
        run_reference="live:c89:deployment-1",
        now=NOW + 1,
        prior_anchor_token=runtime.anchor_token,
        prior_revision=runtime.revision,
    )
    assert runtime.proof_kind == ProofKind.RUNTIME.value
    assert live.proof_kind == ProofKind.LIVE.value
    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert {row["proof_kind"] for row in rows} == {
        ProofKind.RUNTIME.value,
        ProofKind.LIVE.value,
    }
    assert all(row["valid_until"] == 127100.0 for row in rows)


def test_stale_or_wrong_signature_live_receipt_is_rejected(tmp_path):
    _memory, state_path = _live_state(tmp_path)
    stale_path, _ = _signed_live_receipt(tmp_path, state_path, created=NOW - 7200)
    with pytest.raises(ValueError, match="stale"):
        validate_champion_challenger_live_receipt(
            memory_state_path=state_path,
            observer_receipt_path=stale_path,
            observer_key=OBSERVER_KEY,
            expected_revision=str(repository_identity(_root())["revision"]),
            now=NOW,
        )

    good_path, payload = _signed_live_receipt(tmp_path, state_path)
    payload["signature"] = "0" * 64
    good_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="signature verification failed"):
        validate_champion_challenger_live_receipt(
            memory_state_path=state_path,
            observer_receipt_path=good_path,
            observer_key=OBSERVER_KEY,
            expected_revision=str(repository_identity(_root())["revision"]),
            now=NOW,
        )


def test_ungated_or_nonlive_observation_cannot_support_live_proof(tmp_path):
    _memory, state_path = _live_state(tmp_path)
    cases = (
        lambda row: row.__setitem__("automatic_ungated_promotion_observed", True),
        lambda row: row.__setitem__("live_observation_complete", False),
        lambda row: row.__setitem__("persistent_state_reloaded", False),
    )
    for mutate in cases:
        receipt_path, _ = _signed_live_receipt(tmp_path, state_path, mutate=mutate)
        with pytest.raises(ValueError):
            validate_champion_challenger_live_receipt(
                memory_state_path=state_path,
                observer_receipt_path=receipt_path,
                observer_key=OBSERVER_KEY,
                expected_revision=str(repository_identity(_root())["revision"]),
                now=NOW,
            )


def test_state_tamper_after_receipt_invalidates_live_evidence(tmp_path):
    _memory, state_path = _live_state(tmp_path)
    receipt_path, _ = _signed_live_receipt(tmp_path, state_path)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["models"]["challenger-v2"]["metrics"]["quality"] = 0.01
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="exact ScientificMemory state"):
        validate_champion_challenger_live_receipt(
            memory_state_path=state_path,
            observer_receipt_path=receipt_path,
            observer_key=OBSERVER_KEY,
            expected_revision=str(repository_identity(_root())["revision"]),
            now=NOW,
        )


def test_cross_capability_reference_is_rejected_before_ledger_creation(tmp_path):
    target = tmp_path / "wrong-ref.jsonl"
    with pytest.raises(ValueError, match="not capability-bound|not allowed"):
        attest_champion_challenger_software(
            repo_root=_root(),
            storage_root=tmp_path / "storage",
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.EXECUTION,
            run_reference="execution:c88:ci",
            now=NOW,
        )
    assert not target.exists()


def test_failed_or_nonreproducible_benchmark_cannot_mint(monkeypatch, tmp_path):
    original = cc_attestor.run_champion_challenger_benchmark
    target = tmp_path / "failed.jsonl"

    def failed(storage):
        payload = dict(original(storage))
        payload["benchmark_passed"] = False
        return payload

    monkeypatch.setattr(cc_attestor, "run_champion_challenger_benchmark", failed)
    with pytest.raises(ValueError, match="benchmark failed"):
        attest_champion_challenger_software(
            repo_root=_root(),
            storage_root=tmp_path / "storage",
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.EXECUTION,
            run_reference="execution:c89:ci",
            now=NOW,
        )
    assert not target.exists()

    counter = {"n": 0}

    def changing(storage):
        payload = dict(original(storage))
        counter["n"] += 1
        payload["logical_sha256"] = hashlib.sha256(str(counter["n"]).encode()).hexdigest()
        return payload

    monkeypatch.setattr(cc_attestor, "run_champion_challenger_benchmark", changing)
    with pytest.raises(ValueError, match="not reproducible"):
        attest_champion_challenger_software(
            repo_root=_root(),
            storage_root=tmp_path / "storage2",
            ledger_path=target,
            integrity_key=KEY,
            proof_kind=ProofKind.REPRODUCIBILITY,
            run_reference="reproducibility:c89:ci",
            now=NOW,
        )
    assert not target.exists()
