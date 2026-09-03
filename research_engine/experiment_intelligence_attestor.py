"""Trusted deterministic execution attestor for experiment intelligence.

Covers software execution/reproducibility for:
- #22 Experiment Compiler
- #122 Discriminating Experiment
- #123 Minimum-Cost Experiment
- #124 Active Learning

The attestor executes a fixed Bayesian planning benchmark twice from the exact
tracked engine revision, independently checks closed-form expectations, verifies
safety rejection and selection semantics, and then mints only policy-approved
EXECUTION/REPRODUCIBILITY receipts into the HMAC maturity ledger.

This proves deterministic execution of the software planning engine only. It
never claims that a physical experiment ran, that declared priors/likelihoods
are true, that a recommendation is safe in the real world, or that scientific
truth was established.
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

from . import experiment_intelligence as exp
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


_CAPABILITY_IDS = (22, 122, 123, 124)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "experiment-intelligence-benchmark"
_VERIFIER = "trusted-operator"
_ENGINE_SUBJECT = "research_engine/experiment_intelligence.py"
_BENCHMARK_VERSION = "experiment-intelligence-benchmark-v1"


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


def _binary_entropy(probability: float) -> float:
    p = float(probability)
    if not 0.0 < p < 1.0:
        raise ValueError("analytic entropy benchmark probability must be in (0,1)")
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def _runtime_hypothesis(hypothesis_id: str) -> Mapping[str, Any]:
    return {
        "id": hypothesis_id,
        "experiment": {
            "dataset_or_sample": "locked synthetic benchmark cohort",
            "control_or_baseline": "predeclared control",
            "measured_variables": ["binary_outcome"],
            "parameter_range": {"arm": ["control", "treatment"]},
            "statistical_metric": "posterior entropy",
            "success_threshold": "information_gain_bits >= 0.2",
            "failure_threshold": "information_gain_bits < 0.2",
            "falsification_condition": "predeclared outcome contradicts hypothesis",
        },
    }


def _designs() -> Tuple[exp.ExperimentDesign, ...]:
    return (
        exp.ExperimentDesign(
            experiment_id="diagnostic",
            outcome_likelihoods={
                "H1": {"positive": 0.90, "negative": 0.10},
                "H2": {"positive": 0.10, "negative": 0.90},
            },
            monetary_cost=10.0,
            duration_hours=1.0,
            operational_risk=0.10,
            safety_status="APPROVED",
            feasible=True,
            measurement="binary diagnostic outcome",
        ),
        exp.ExperimentDesign(
            experiment_id="medium",
            outcome_likelihoods={
                "H1": {"positive": 0.80, "negative": 0.20},
                "H2": {"positive": 0.20, "negative": 0.80},
            },
            monetary_cost=3.0,
            duration_hours=1.0,
            operational_risk=0.05,
            safety_status="APPROVED",
            feasible=True,
            measurement="binary medium-strength outcome",
        ),
        exp.ExperimentDesign(
            experiment_id="cheap_weak",
            outcome_likelihoods={
                "H1": {"positive": 0.65, "negative": 0.35},
                "H2": {"positive": 0.35, "negative": 0.65},
            },
            monetary_cost=1.0,
            duration_hours=0.5,
            operational_risk=0.02,
            safety_status="APPROVED",
            feasible=True,
            measurement="binary weak outcome",
        ),
        exp.ExperimentDesign(
            experiment_id="blocked_high_information",
            outcome_likelihoods={
                "H1": {"positive": 0.95, "negative": 0.05},
                "H2": {"positive": 0.05, "negative": 0.95},
            },
            monetary_cost=0.1,
            duration_hours=0.1,
            operational_risk=0.90,
            safety_status="BLOCKED",
            feasible=True,
            measurement="unsafe benchmark design that must never win",
        ),
    )


def run_experiment_intelligence_benchmark() -> Mapping[str, Any]:
    """Execute fixed analytic planning cases and independent expectations."""
    priors = {"H1": 0.5, "H2": 0.5}
    designs = _designs()

    runtime_packet = exp.build_runtime_experiment_packet(
        (_runtime_hypothesis("H1"), _runtime_hypothesis("H2"))
    )
    ranked = exp.rank_discriminating_experiments(priors, designs)
    score_by_id = {row.experiment_id: row for row in ranked}
    diagnostic = score_by_id["diagnostic"]
    medium = score_by_id["medium"]
    blocked = score_by_id["blocked_high_information"]

    discriminating = exp.choose_discriminating_experiment(
        priors,
        designs,
        min_information_gain_bits=0.40,
        min_weakest_pair_separation=0.70,
    )
    minimum_cost = exp.choose_minimum_cost_experiment(
        priors,
        designs,
        min_information_gain_bits=0.20,
        min_weakest_pair_separation=0.50,
        max_operational_risk=0.20,
        max_duration_hours=2.0,
    )
    active = exp.choose_active_learning_step(
        priors,
        designs,
        min_information_gain_bits=0.05,
    )
    update = exp.update_posterior_with_receipt(
        priors,
        designs[0],
        "positive",
    )

    expected_diagnostic_gain = 1.0 - _binary_entropy(0.90)
    expected_medium_gain = 1.0 - _binary_entropy(0.80)
    checks = {
        "runtime_contracts_complete": (
            runtime_packet.get("complete_experiment_contracts") == 2
            and runtime_packet.get("selection_performed") is False
            and runtime_packet.get("truth_proven") is False
        ),
        "runtime_assumptions_fail_closed": (
            runtime_packet.get("status") == "BLOCKED_MISSING_EXPLICIT_ASSUMPTIONS"
            and "explicit_priors_missing" in tuple(runtime_packet.get("blockers") or ())
            and "outcome_likelihoods_missing" in tuple(runtime_packet.get("blockers") or ())
        ),
        "diagnostic_information_gain_closed_form": math.isclose(
            diagnostic.information_gain_bits,
            expected_diagnostic_gain,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "diagnostic_pair_separation_closed_form": math.isclose(
            diagnostic.weakest_pair_separation,
            0.80,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "medium_information_gain_closed_form": math.isclose(
            medium.information_gain_bits,
            expected_medium_gain,
            rel_tol=0.0,
            abs_tol=1e-12,
        ),
        "blocked_design_ineligible": (
            blocked.eligible is False and blocked.safety_status == "BLOCKED"
        ),
        "discriminating_selection": discriminating.experiment_id == "diagnostic",
        "minimum_cost_selection": minimum_cost.experiment_id == "medium",
        "active_learning_selection": active.experiment_id == "medium",
        "posterior_closed_form": (
            math.isclose(update.predictive_probability, 0.5, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(update.posterior["H1"], 0.9, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(update.posterior["H2"], 0.1, rel_tol=0.0, abs_tol=1e-12)
        ),
        "truth_and_execution_boundary": (
            diagnostic.truth_proven is False
            and discriminating.planning_only is True
            and discriminating.real_world_approval_implied is False
            and update.truth_proven is False
            and update.experiment_executed_by_this_function is False
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "runtime_packet": runtime_packet,
        "ranked": [asdict(row) for row in ranked],
        "discriminating": asdict(discriminating),
        "minimum_cost": asdict(minimum_cost),
        "active_learning": asdict(active),
        "posterior_update": asdict(update),
        "declared_priors": priors,
        "declared_likelihoods_are_measured_truth": False,
        "physical_experiment_executed": False,
        "real_world_approval_implied": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class ExperimentIntelligenceExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    physical_experiment_executed: bool = False
    real_world_approval_implied: bool = False
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


def attest_experiment_intelligence_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> ExperimentIntelligenceExecutionAttestation:
    """Run the benchmark and mint only exact policy-approved proof receipts."""
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
        raise ValueError("experiment intelligence attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(exp.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Experiment Intelligence runtime is not loaded from the audited repository")

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
                raise ValueError("run_reference is not allowed by experiment intelligence proof policy")

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

    first = run_experiment_intelligence_benchmark()
    second = run_experiment_intelligence_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("experiment intelligence benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("experiment intelligence benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("experiment intelligence benchmark digest verification failed")

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
            receipt_id = f"experiment-intelligence:{revision[:12]}:c{capability_id}:{kind.value}"
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
                    raise ValueError("deterministic experiment intelligence receipt_id collision")
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
        raise ValueError("trusted maturity audit rejected experiment intelligence attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during experiment intelligence attestation")

    return ExperimentIntelligenceExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
