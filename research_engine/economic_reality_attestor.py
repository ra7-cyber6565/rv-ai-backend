"""Trusted EXECUTION/REPRODUCIBILITY attestation for capability #100.

The attestor does not trust a caller-supplied economics report.  It requires a
clean Git checkout, confirms that the imported Economic Reality engine is the
tracked engine file from that checkout, executes a fixed analytic benchmark
twice, independently checks closed-form expectations, requires byte-equivalent
deterministic report content, and only then mints policy-approved execution and
reproducibility receipts into the HMAC proof ledger.

Passing this benchmark proves deterministic execution of the economic model; it
does not prove any real business is profitable or viable.
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

from . import economic_reality as econ
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


_CAPABILITY_ID = 100
_SUBJECT = "economic-reality-benchmark"
_VERIFIER = "trusted-operator"
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_MODEL_SUBJECT = "research_engine/economic_reality.py"


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


def _basis() -> Mapping[str, str]:
    return {
        "initial_capex": "MEASURED",
        "revenues": "MEASURED",
        "operating_costs": "MEASURED",
        "discount_rate": "CONTRACTED",
        "unit_economics": "CONTRACTED",
        "starting_cash": "MEASURED",
    }


def run_economic_reality_benchmark() -> Mapping[str, Any]:
    """Execute a closed-form benchmark whose expected values are independent."""
    base = econ.EconomicScenario(
        scenario_id="analytic_base",
        probability=1.0,
        currency="USD",
        discount_rate=0.0,
        initial_capex=100.0,
        revenues=(70.0, 70.0),
        operating_costs=(10.0, 10.0),
        provenance_ref="benchmark:analytic-base",
        input_basis=_basis(),
        starting_cash=150.0,
        unit_price=10.0,
        unit_variable_cost=6.0,
        fixed_cost_per_period=100.0,
    )
    report = econ.assess_economic_reality((base,))
    audit = report.scenario_audits[0]

    expected_npv = -100.0 + 60.0 + 60.0
    expected_payback = 1.0 + 40.0 / 60.0
    expected_break_even = 100.0 / (10.0 - 6.0)
    checks = {
        "npv_closed_form": math.isclose(audit.npv, expected_npv, rel_tol=0.0, abs_tol=1e-10),
        "expected_npv_closed_form": math.isclose(
            report.expected_npv, expected_npv, rel_tol=0.0, abs_tol=1e-10
        ),
        "payback_closed_form": math.isclose(
            float(audit.payback_period), expected_payback, rel_tol=0.0, abs_tol=1e-10
        ),
        "break_even_closed_form": math.isclose(
            float(audit.break_even_units_per_period),
            expected_break_even,
            rel_tol=0.0,
            abs_tol=1e-10,
        ),
        "liquidity_no_breach": audit.liquidity_breach is False,
        "sensitivity_complete": len(report.sensitivities) == 8,
        "truth_boundary": (
            report.profitability_proven is False
            and report.real_world_viability_proven is False
            and report.market_demand_proven is False
            and report.truth_proven is False
        ),
    }
    payload = {
        "benchmark_version": "economic-reality-benchmark-v1",
        "checks": checks,
        "report": asdict(report),
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class EconomicRealityExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    profitability_proven: bool = False
    real_world_viability_proven: bool = False
    truth_proven: bool = False


def _same_receipt(
    row: Mapping[str, Any],
    *,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": _CAPABILITY_ID,
        "proof_kind": kind.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_economic_reality_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> EconomicRealityExecutionAttestation:
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
        raise ValueError("economic execution attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _MODEL_SUBJECT)
    imported_engine = Path(str(econ.__file__)).resolve(strict=True)
    audited_engine = (root / _MODEL_SUBJECT).resolve(strict=True)
    if imported_engine != audited_engine:
        raise ValueError("Economic Reality runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for kind in _REQUIRED:
        matching = tuple(
            rule for rule in policy.rules
            if rule.capability_id == _CAPABILITY_ID
            and rule.proof_kind is kind
            and _SUBJECT in rule.subjects
            and _VERIFIER in rule.verifiers
        )
        if not matching:
            raise ValueError(f"committed proof policy has no trusted {kind.value} rule")
        if not any(
            not rule.reference_prefixes
            or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
            for rule in matching
        ):
            raise ValueError("run_reference is not allowed by economic proof policy")

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

    first = run_economic_reality_benchmark()
    second = run_economic_reality_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("economic reality analytic benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("economic reality benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    if len(benchmark_digest) != 64 or benchmark_digest != _sha({
        "benchmark_version": first["benchmark_version"],
        "checks": first["checks"],
        "report": first["report"],
    }):
        raise ValueError("economic reality benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for kind in _REQUIRED:
        receipt_id = f"economic:{revision[:12]}:{kind.value}"
        previous = existing.get(receipt_id)
        if previous is not None:
            if not _same_receipt(
                previous,
                kind=kind,
                digest=receipt_digest,
                reference=reference,
                revision=revision,
            ):
                raise ValueError("deterministic economic receipt_id collision")
            reused += 1
            continue
        ledger.add(
            receipt_id=receipt_id,
            capability_id=_CAPABILITY_ID,
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
        raise ValueError("trusted maturity audit rejected economic execution attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during economic execution attestation")

    return EconomicRealityExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
