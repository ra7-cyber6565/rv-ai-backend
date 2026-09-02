"""Trusted software benchmark attestor for #36 Red-Team AI and #38 Falsification Budget.

The attestor executes a fixed adversarial-science campaign twice from the exact
audited revision, validates budget/safety/coverage/execution boundaries, and
mints only EXECUTION and REPRODUCIBILITY receipts.  It cannot mint #36's
INDEPENDENT proof and cannot turn attack survival into scientific truth.
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

from . import adversarial_science as adv
from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger


_CAPABILITY_IDS = (36, 38)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_ENGINE_SUBJECT = "research_engine/adversarial_science.py"
_BENCHMARK_VERSION = "adversarial-science-benchmark-v1"
_VERIFIERS = {
    ProofKind.EXECUTION: "trusted-execution-attestor",
    ProofKind.REPRODUCIBILITY: "trusted-reproducibility-attestor",
}
_NAMESPACES = {
    ProofKind.EXECUTION: "execution",
    ProofKind.REPRODUCIBILITY: "reproducibility",
}
_SUFFIX = {
    ProofKind.EXECUTION: "execution-run",
    ProofKind.REPRODUCIBILITY: "reproducibility-run",
}


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


def _subject(capability_id: int, kind: ProofKind) -> str:
    return f"capability-{capability_id}-{_SUFFIX[kind]}"


def _reference(capability_id: int, kind: ProofKind, observation_id: str) -> str:
    return f"{_NAMESPACES[kind]}:c{capability_id}:{observation_id}"


def _safe_observation_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        raise ValueError("observation_id is invalid")
    if any(not (ch.isalnum() or ch in "_.@/+~-") for ch in text):
        raise ValueError("observation_id is invalid")
    return text


def _targets() -> Tuple[adv.AttackTarget, ...]:
    return (
        adv.AttackTarget(
            "H1",
            "Champion mechanism explains the registered benchmark observation",
            1.0,
            0.45,
            True,
        ),
        adv.AttackTarget(
            "H2",
            "Alternative mechanism explains the same registered benchmark observation",
            0.75,
            0.60,
            False,
        ),
    )


def _proposals() -> Tuple[adv.AttackProposal, ...]:
    return (
        adv.AttackProposal(
            "A1", "H1", "COUNTEREXAMPLE", 2.0, 0.95, "counter-group",
            "registered counterexample is measured",
            "counterexample crosses the predeclared rejection boundary",
        ),
        adv.AttackProposal(
            "A2", "H1", "ASSUMPTION_BREAK", 2.0, 0.85, "assumption-group",
            "strongest assumption is removed",
            "effect collapses after the registered assumption removal",
        ),
        adv.AttackProposal(
            "A3", "H2", "NEGATIVE_CONTROL", 2.0, 0.80, "control-group",
            "registered negative control is measured",
            "negative control reproduces the alternative effect",
        ),
        adv.AttackProposal(
            "A4", "H2", "OOD_STRESS", 2.0, 0.75, "ood-group",
            "locked OOD case is evaluated",
            "effect reverses outside the predeclared regime",
        ),
        adv.AttackProposal(
            "A5", "H1", "PLACEBO_CONTROL", 1.0, 0.90, "unsafe-group",
            "blocked placebo proposal would run",
            "blocked placebo would satisfy a falsifier",
            safety_status="BLOCKED",
        ),
    )


def run_adversarial_science_benchmark() -> Mapping[str, Any]:
    policy = adv.FalsificationPolicy(
        total_budget=8.0,
        champion_reserve_fraction=0.30,
        max_target_budget_fraction=0.70,
        min_attacks_per_target=1,
        min_attack_type_diversity=3,
        min_independent_groups=3,
        allow_review_required=False,
    )
    plan = adv.plan_falsification_campaign(_targets(), _proposals(), policy)
    coverage = adv.red_team_coverage(plan)
    observations = []
    first_h1 = next(row.attack_id for row in plan.selected_attacks if row.target_id == "H1")
    for row in plan.selected_attacks:
        observations.append(
            adv.AttackObservation(
                attack_id=row.attack_id,
                status="FALSIFIED" if row.attack_id == first_h1 else "NOT_FALSIFIED",
                measured_result="frozen benchmark observation completed",
                observer_id="software-benchmark-observer",
            )
        )
    execution = adv.execute_registered_attacks(plan, observations)
    rejected = {row.attack_id: row.reason for row in plan.rejected_attacks}
    checks = {
        "plan_ready": plan.status == "READY" and not plan.blockers,
        "champion_reserve_met": coverage.get("champion_reserve_met") is True,
        "target_coverage_complete": coverage.get("target_coverage") == 1.0,
        "attack_diversity": len(plan.attack_types) >= 3,
        "independent_group_diversity": len(plan.independent_groups) >= 3,
        "unsafe_attack_rejected": rejected.get("A5") == "safety_blocked",
        "budget_respected": plan.spent_budget <= plan.total_budget,
        "execution_complete": execution.execution_complete is True,
        "falsification_detected": "H1" in execution.falsified_target_ids,
        "survival_is_limited": "H2" in execution.survived_target_ids,
        "truth_boundary": (
            plan.truth_proven is False
            and plan.survival_is_truth is False
            and execution.truth_proven is False
            and execution.survival_is_truth is False
            and execution.scientific_verification_implied is False
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "plan": asdict(plan),
        "coverage": dict(coverage),
        "execution": asdict(execution),
        "software_execution_only": True,
        "external_independence_proven": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class AdversarialScienceAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    external_independence_proven: bool = False
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
        "subject": _subject(capability_id, kind),
        "subject_sha256": digest,
        "verifier": _VERIFIERS[kind],
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_adversarial_science_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    observation_id: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> AdversarialScienceAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    observation = _safe_observation_id(observation_id)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "").strip().lower()
    if not identity_before.get("available") or not identity_before.get("clean") or len(revision) != 40:
        raise ValueError("adversarial science attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    imported_engine = Path(str(adv.__file__)).resolve(strict=True)
    audited_engine = (root / _ENGINE_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("adversarial science runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    references = {}
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            subject = _subject(capability_id, kind)
            verifier = _VERIFIERS[kind]
            reference = _reference(capability_id, kind, observation)
            matches = tuple(
                rule for rule in policy.rules
                if rule.capability_id == capability_id
                and rule.proof_kind is kind
                and subject in rule.subjects
                and verifier in rule.verifiers
            )
            if not matches:
                raise ValueError(
                    f"committed proof policy has no trusted c{capability_id} {kind.value} route"
                )
            if not any(
                not rule.reference_prefixes
                or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
                for rule in matches
            ):
                raise ValueError("generated reference is not allowed by adversarial proof policy")
            references[(capability_id, kind)] = reference

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or len(prior) != 40:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_adversarial_science_benchmark()
    second = run_adversarial_science_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("adversarial science benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("adversarial science benchmark is not deterministic")
    if first.get("external_independence_proven") is not False:
        raise ValueError("software benchmark must not claim external independence")
    if first.get("truth_proven") is not False:
        raise ValueError("software benchmark must not claim scientific truth")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("adversarial science benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "capability_ids": _CAPABILITY_IDS,
        "proof_kinds": [kind.value for kind in _REQUIRED],
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            reference = references[(capability_id, kind)]
            receipt_id = f"adversarial-science:{revision[:12]}:c{capability_id}:{kind.value}"
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
                    raise ValueError("deterministic adversarial science receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=_subject(capability_id, kind),
                subject_sha256=receipt_digest,
                verifier=_VERIFIERS[kind],
                observed_at=current_time,
                reference=reference,
                implementation_revision=revision,
            )
            added += 1

    if added + reused != len(_CAPABILITY_IDS) * len(_REQUIRED):
        raise ValueError("adversarial science attestation did not account for every proof route")

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
        raise ValueError("trusted maturity audit rejected adversarial science attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during adversarial science attestation")

    return AdversarialScienceAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
