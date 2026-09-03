"""Trusted deterministic execution attestor for the statistical validation lab.

Covers software execution/reproducibility for:
- #29 Monte Carlo Universe
- #30 Sensitivity Analysis
- #31 Ablation Testing
- #32 Placebo Tests
- #33 Leakage Detector
- #34 Overfitting Detector
- #35 Out-of-Distribution Testing
- #99 Multiple Hypothesis Correction

The benchmark uses fixed synthetic fixtures and repeated byte-identical execution.
It proves the tracked software primitives executed as specified for those fixtures.
It does NOT prove that a future data distribution is stationary, that an ablated
component is universally causal, that a suspicious generalization gap is caused
by overfitting, or that a real scientific/trading claim is true.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple

from utils.release_identity import repository_identity

from . import statistical_validation as stat
from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo, _safe_reference
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_IDS = (29, 30, 31, 32, 33, 34, 35, 99)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "statistical-validation-benchmark"
_VERIFIER = "trusted-operator"
_ENGINE_SUBJECT = "research_engine/statistical_validation.py"
_BENCHMARK_VERSION = "statistical-validation-benchmark-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def run_statistical_validation_benchmark() -> Mapping[str, Any]:
    """Execute fixed statistical fixtures and independently check invariants."""
    bh = stat.benjamini_hochberg([0.001, 0.01, 0.04, 0.20], alpha=0.05)
    holm = stat.holm_bonferroni([0.001, 0.01, 0.04, 0.20], alpha=0.05)

    placebo = stat.paired_placebo_permutation_test(
        [1.20, 1.10, 1.30, 1.25, 1.15, 1.35, 1.18, 1.28, 1.22, 1.31, 1.17, 1.27],
        [1.00] * 12,
        permutations=4096,
        seed=20260831,
        alternative="greater",
    )

    monte_carlo = stat.monte_carlo_return_paths(
        [0.010, -0.005, 0.020, -0.010, 0.015, 0.002],
        paths=1000,
        horizon=24,
        seed=20260831,
        initial_equity=1.0,
        ruin_equity=0.50,
    )

    sensitivity = stat.sensitivity_plateau(
        {1.0: 80.0, 2.0: 94.0, 3.0: 100.0, 4.0: 95.0, 5.0: 79.0},
        acceptable_fraction_of_best=0.90,
        cliff_drop_fraction=0.25,
    )

    ablation = stat.ablation_analysis(
        1.0,
        {
            "core_signal": 0.62,
            "risk_filter": 0.84,
            "decorative_feature": 1.02,
        },
        min_relative_degradation=0.10,
    )

    overfit = stat.overfit_diagnostic(
        [0.96, 0.95, 0.97, 0.94],
        [0.68, 0.66, 0.69, 0.65],
        max_relative_gap=0.10,
    )

    leakage = stat.detect_temporal_leakage(
        [
            {"event_time": 1.0, "feature_available_time": 1.0, "target_time": 2.0},
            {"event_time": 2.0, "feature_available_time": 2.5, "target_time": 3.0},
            {"event_time": 3.0, "feature_available_time": 3.0, "target_time": 3.0},
        ]
    )

    walk_forward = stat.walk_forward_splits(
        30,
        min_train=10,
        test_size=5,
        step=5,
        expanding=True,
    )

    reference = [float(index) for index in range(1, 101)]
    psi_same = stat.population_stability_index(reference, list(reference), bins=10)
    psi_shifted = stat.population_stability_index(
        reference,
        [float(index + 80) for index in range(1, 101)],
        bins=10,
    )

    leakage_kinds = tuple(sorted({row.kind for row in leakage}))
    checks = {
        "bh_known_rejections": bh.rejected == (True, True, False, False),
        "holm_known_rejections": holm.rejected == (True, True, False, False),
        "multiple_testing_adjustments_monotone_bounds": (
            all(0.0 <= value <= 1.0 for value in bh.adjusted_p_values)
            and all(0.0 <= value <= 1.0 for value in holm.adjusted_p_values)
            and bh.adjusted_p_values[0] <= bh.adjusted_p_values[-1]
            and holm.adjusted_p_values[0] <= holm.adjusted_p_values[-1]
        ),
        "placebo_detects_locked_positive_effect": (
            placebo.observed_effect > 0.0
            and placebo.p_value < 0.05
            and placebo.permutations == 4096
            and placebo.seed == 20260831
        ),
        "monte_carlo_distribution_is_ordered": (
            monte_carlo.paths == 1000
            and monte_carlo.horizon == 24
            and monte_carlo.seed == 20260831
            and monte_carlo.terminal_equity_p05
            <= monte_carlo.median_terminal_equity
            <= monte_carlo.terminal_equity_p95
            and 0.0 <= monte_carlo.ruin_probability <= 1.0
            and 0.0 <= monte_carlo.median_max_drawdown <= monte_carlo.max_drawdown_p95
        ),
        "sensitivity_finds_declared_peak_and_plateau": (
            math.isclose(sensitivity.best_parameter, 3.0, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(sensitivity.best_score, 100.0, rel_tol=0.0, abs_tol=1e-12)
            and sensitivity.plateau_min == 2.0
            and sensitivity.plateau_max == 4.0
        ),
        "ablation_preserves_noncausal_boundary": (
            set(ablation.critical_components) == {"core_signal", "risk_filter"}
            and any(
                item.component == "decorative_feature" and item.improved_when_removed
                for item in ablation.effects
            )
            and ablation.causal_importance_proven is False
            and ablation.truth_proven is False
        ),
        "overfit_is_warning_not_proof": (
            overfit.suspicious is True
            and overfit.relative_gap > overfit.max_relative_gap
            and overfit.overfitting_proven is False
            and overfit.distribution_shift_ruled_out is False
            and overfit.truth_proven is False
        ),
        "leakage_detects_two_distinct_temporal_failures": (
            leakage_kinds == ("INVALID_TARGET_CHRONOLOGY", "LOOKAHEAD_FEATURE")
        ),
        "walk_forward_never_overlaps_train_and_test": (
            len(walk_forward) == 4
            and all(train[1] <= test[0] for train, test in walk_forward)
            and all(test[0] < test[1] for _, test in walk_forward)
        ),
        "ood_shift_diagnostic_separates_locked_fixture": (
            math.isclose(psi_same, 0.0, rel_tol=0.0, abs_tol=1e-12)
            and psi_shifted > 0.10
        ),
    }

    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "multiple_testing": {
            "benjamini_hochberg": asdict(bh),
            "holm_bonferroni": asdict(holm),
        },
        "placebo": asdict(placebo),
        "monte_carlo": asdict(monte_carlo),
        "sensitivity": asdict(sensitivity),
        "ablation": asdict(ablation),
        "overfit": asdict(overfit),
        "leakage": [asdict(row) for row in leakage],
        "walk_forward": walk_forward,
        "ood": {"psi_same": psi_same, "psi_shifted": psi_shifted},
        "real_world_dataset_observed": False,
        "future_distribution_guaranteed": False,
        "causality_proven": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class StatisticalValidationExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    real_world_dataset_observed: bool = False
    future_distribution_guaranteed: bool = False
    causality_proven: bool = False
    truth_proven: bool = False


def _same_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_statistical_validation_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> StatisticalValidationExecutionAttestation:
    """Execute benchmark and mint only exact policy-approved proof receipts."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("statistical validation attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(stat.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("statistical validation runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            matching = tuple(
                rule for rule in policy.rules
                if rule.capability_id == capability_id
                and rule.proof_kind is kind
                and _SUBJECT in rule.subjects
                and _VERIFIER in rule.verifiers
            )
            if not matching:
                raise ValueError(
                    f"committed proof policy has no trusted c{capability_id} {kind.value} rule"
                )
            if not any(
                not rule.reference_prefixes
                or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
                for rule in matching
            ):
                raise ValueError("run_reference is not allowed by statistical validation proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_statistical_validation_benchmark()
    second = run_statistical_validation_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("statistical validation benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("statistical validation benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("statistical validation benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capabilities": _CAPABILITY_IDS,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            receipt_id = f"statistical-validation:{revision[:12]}:c{capability_id}:{kind.value}"
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_receipt(
                    previous,
                    capability_id=capability_id,
                    kind=kind,
                    digest=receipt_digest,
                    reference=reference,
                    revision=revision,
                ):
                    raise ValueError("deterministic statistical validation receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=_SUBJECT,
                subject_sha256=receipt_digest,
                verifier=_VERIFIER,
                observed_at=current_time,
                reference=reference,
                implementation_revision=revision,
            )
            added += 1

    anchor = ledger.create_anchor(current_revision=revision, issued_at=current_time)
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=integrity_key,
        anchor_token=anchor,
        now=current_time,
        policy_path=policy_path,
    )
    if not audit.audit_valid:
        raise ValueError("trusted maturity audit rejected statistical validation attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during statistical validation attestation")

    return StatisticalValidationExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
