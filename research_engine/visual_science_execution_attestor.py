"""Trusted deterministic execution attestor for visual-science capabilities.

Covers #107 Visual Reasoning and #108 Misleading Visualization Detector using a
locked corpus of *normalized structured chart specifications*.  It does not run
computer vision/OCR, does not infer deceptive intent, and does not turn a chart
risk flag into evidence of fraud.  Image extraction quality remains an upstream
boundary and is represented explicitly in the fixture specs.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from utils.release_identity import repository_identity

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
from .visual_science import AxisSpec, ChartSeries, ChartSpec, VisualScienceEngine


_CAPABILITIES = (107, 108)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "visual-science-benchmark"
_VERIFIER = "trusted-operator"
_ENGINE_SUBJECT = "research_engine/visual_science.py"
_BENCHMARK_VERSION = "visual-science-benchmark-v1"


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


def _axis(axis_id: str, minimum: float, maximum: float, **kwargs: Any) -> AxisSpec:
    return AxisSpec(
        axis_id=axis_id,
        label=axis_id,
        minimum=minimum,
        maximum=maximum,
        **kwargs,
    )


def _series(series_id: str, x, y, **kwargs: Any) -> ChartSeries:
    return ChartSeries(
        series_id=series_id,
        label=series_id,
        x=tuple(float(value) for value in x),
        y=tuple(float(value) for value in y),
        **kwargs,
    )


def _audit_payload(report) -> Mapping[str, Any]:
    return asdict(report)


def run_visual_science_benchmark() -> Mapping[str, Any]:
    """Execute a fixed deterministic corpus spanning safe and risky charts."""
    engine = VisualScienceEngine()
    x = _axis("x", 0.0, 10.0)

    clean = engine.audit(ChartSpec(
        figure_id="clean-line",
        chart_type="line",
        x_axis=x,
        y_axes=(_axis("y", 0.0, 10.0),),
        series=(_series("clean", (0, 1, 2), (1, 2, 3)),),
    ))
    truncated = engine.audit(ChartSpec(
        figure_id="truncated-bar",
        chart_type="bar",
        x_axis=x,
        y_axes=(_axis("y", 90.0, 110.0),),
        series=(_series("bars", (0, 1, 2), (99, 100, 101)),),
    ))
    low_extraction = engine.audit(ChartSpec(
        figure_id="low-extraction",
        chart_type="line",
        x_axis=x,
        y_axes=(_axis("y", 0.0, 10.0),),
        series=(_series("ocr", (0, 1, 2), (1, 2, 3)),),
        extracted_from_image=True,
        extraction_confidence=0.60,
    ))
    undisclosed_axes = engine.audit(ChartSpec(
        figure_id="undisclosed-axes",
        chart_type="line",
        x_axis=x,
        y_axes=(_axis(
            "y", 1.0, 1000.0,
            scale="log10", scale_disclosed=False,
            direction="reversed", direction_disclosed=False,
        ),),
        series=(_series("scaled", (0, 1, 2), (10, 100, 1000)),),
    ))
    cherry = engine.audit(ChartSpec(
        figure_id="window-sign-flip",
        chart_type="line",
        x_axis=x,
        y_axes=(_axis("y", 0.0, 12.0),),
        series=(_series(
            "window",
            (0, 1, 2),
            (3, 2, 1),
            full_x=tuple(float(value) for value in range(11)),
            full_y=tuple(float(value) for value in range(11)),
        ),),
    ))
    inferential = engine.audit(ChartSpec(
        figure_id="missing-uncertainty",
        chart_type="line",
        x_axis=x,
        y_axes=(_axis("y", 0.0, 10.0),),
        series=(_series("infer", (0, 1, 2), (1, 2, 3)),),
        inferential_claim=True,
    ))

    reports = {
        "clean": _audit_payload(clean),
        "truncated": _audit_payload(truncated),
        "low_extraction": _audit_payload(low_extraction),
        "undisclosed_axes": _audit_payload(undisclosed_axes),
        "cherry_window": _audit_payload(cherry),
        "missing_uncertainty": _audit_payload(inferential),
    }
    codes = {
        name: tuple(sorted(risk["code"] for risk in payload["risks"]))
        for name, payload in reports.items()
    }
    checks = {
        "clean_chart_has_no_detected_risk": (
            clean.status == "NO_DETECTED_VISUAL_RISK"
            and clean.strong_claim_allowed is True
            and clean.high_risk is False
        ),
        "truncated_bar_is_high_risk": (
            "TRUNCATED_BAR_BASELINE" in codes["truncated"]
            and truncated.high_risk is True
            and truncated.strong_claim_allowed is False
        ),
        "low_extraction_fails_closed": (
            "LOW_EXTRACTION_CONFIDENCE" in codes["low_extraction"]
            and low_extraction.status == "UNVERIFIED_EXTRACTION"
            and low_extraction.strong_claim_allowed is False
        ),
        "undisclosed_axis_transformations_are_detected": (
            "UNDISCLOSED_LOG_SCALE" in codes["undisclosed_axes"]
            and "UNDISCLOSED_REVERSED_AXIS" in codes["undisclosed_axes"]
            and undisclosed_axes.high_risk is True
        ),
        "cherry_picked_window_sign_flip_is_detected": (
            "CHERRY_PICKED_WINDOW_SIGN_FLIP" in codes["cherry_window"]
            and cherry.high_risk is True
        ),
        "inferential_chart_without_uncertainty_requires_review": (
            "MISSING_UNCERTAINTY" in codes["missing_uncertainty"]
            and inferential.status == "REVIEW_REQUIRED"
        ),
        "risk_never_authorizes_intent_inference": all(
            payload["intent_inference_allowed"] is False for payload in reports.values()
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "reports": reports,
        "normalized_structured_specs_only": True,
        "computer_vision_executed": False,
        "ocr_executed": False,
        "author_fraud_inferred": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class VisualScienceExecutionAttestation:
    revision: str
    engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    normalized_structured_specs_only: bool = True
    computer_vision_executed: bool = False
    ocr_executed: bool = False
    author_fraud_inferred: bool = False
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


def attest_visual_science_execution(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> VisualScienceExecutionAttestation:
    """Mint only EXECUTION/REPRODUCIBILITY receipts for #107/#108."""
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("visual-science attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    engine_digest = _hash_tracked_regular(root, tracked, _ENGINE_SUBJECT)
    import research_engine.visual_science as loaded_visual
    if Path(str(loaded_visual.__file__)).resolve(strict=True) != (root / _ENGINE_SUBJECT).resolve(strict=True):
        raise ValueError("visual-science runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for capability_id in _CAPABILITIES:
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
                    f"committed policy has no visual-science c{capability_id} {kind.value} rule"
                )
            if not any(
                not rule.reference_prefixes
                or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
                for rule in matching
            ):
                raise ValueError("run_reference is not allowed by visual-science proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(anchor_token=prior_anchor_token, current_revision=prior):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_visual_science_benchmark()
    second = run_visual_science_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("visual-science benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("visual-science benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    digest_payload = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(digest_payload):
        raise ValueError("visual-science benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "engine_sha256": engine_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capabilities": _CAPABILITIES,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITIES:
        for kind in _REQUIRED:
            receipt_id = f"visual-science:{revision[:12]}:c{capability_id}:{kind.value}"
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
                    raise ValueError("deterministic visual-science receipt_id collision")
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
        raise ValueError("trusted maturity audit rejected visual-science attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during visual-science attestation")

    return VisualScienceExecutionAttestation(
        revision=revision,
        engine_sha256=engine_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
