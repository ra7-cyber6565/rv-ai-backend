"""Fail-closed production wiring for #85/#95/#110/#119/#120.

Only an explicit top-level ``epistemic_stress_contracts`` mapping is consumed.
No assumption, synthetic lineage, conspiracy label, falsifier or evidence group
is inferred from natural-language prose.  The wrapper adds audit coverage only;
it cannot upgrade status, confidence, truth or real-world validation.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Mapping, Sequence

from .belief_sandbox import CandidateBelief, assess_sandbox_belief
from .claim_insurance import ClaimInsuranceInput, assess_claim_insurance
from .conspiracy_discipline import (
    ConspiracyHypothesisInput,
    HypothesisEvidence,
    assess_conspiracy_hypothesis,
)
from .synthetic_data_boundary import DataArtifact, enforce_synthetic_boundary
from .unknown_unknown_hunter import (
    AnomalyProbe,
    AssumptionProbe,
    CoverageDimension,
    hunt_unknown_unknowns,
)

_INSTALLED = False
_MAX_CONTRACTS = 1000


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_CONTRACTS:
            raise ValueError(f"{field} exceeds runtime contract budget")
        return value
    raise ValueError(f"{field} must be a bounded sequence")


def _unknown_unknown(contract: Mapping[str, Any]) -> Dict[str, Any]:
    dimensions = [
        CoverageDimension(
            dimension_id=str(row.get("dimension_id") or ""),
            expected_states=tuple(row.get("expected_states") or ()),
            observed_states=tuple(row.get("observed_states") or ()),
        )
        for row in (
            _mapping(item, "coverage_dimension")
            for item in _sequence(contract.get("coverage_dimensions", ()), "coverage_dimensions")
        )
    ]
    assumptions = [
        AssumptionProbe(
            assumption_id=str(row.get("assumption_id") or ""),
            statement=str(row.get("statement") or ""),
            tested=bool(row.get("tested")),
            falsifier=str(row.get("falsifier") or ""),
        )
        for row in (
            _mapping(item, "assumption")
            for item in _sequence(contract.get("assumptions", ()), "assumptions")
        )
    ]
    anomalies = [
        AnomalyProbe(
            anomaly_id=str(row.get("anomaly_id") or ""),
            description=str(row.get("description") or ""),
            severity=row.get("severity", 0.0),
            explained_by=tuple(row.get("explained_by") or ()),
        )
        for row in (
            _mapping(item, "anomaly")
            for item in _sequence(contract.get("anomalies", ()), "anomalies")
        )
    ]
    return asdict(hunt_unknown_unknowns(
        coverage_dimensions=dimensions,
        assumptions=assumptions,
        anomalies=anomalies,
    ))


def _claim_insurance(contracts: Sequence[Any]) -> Dict[str, Any]:
    rows = []
    for raw in contracts:
        item = _mapping(raw, "claim_insurance")
        assessment = assess_claim_insurance(ClaimInsuranceInput(
            claim_id=str(item.get("claim_id") or ""),
            statement=str(item.get("statement") or ""),
            impact_if_wrong=item.get("impact_if_wrong", 1.0),
            supporting_evidence_ids=tuple(item.get("supporting_evidence_ids") or ()),
            independent_groups=tuple(item.get("independent_groups") or ()),
            uncertainty_upper_bound=item.get("uncertainty_upper_bound", 1.0),
            falsifier=str(item.get("falsifier") or ""),
            revalidation_trigger=str(item.get("revalidation_trigger") or ""),
            monitoring_signal=str(item.get("monitoring_signal") or ""),
            rollback_plan=str(item.get("rollback_plan") or ""),
            strong_label_requested=bool(item.get("strong_label_requested", True)),
        ))
        rows.append(asdict(assessment))
    return {
        "assessments": rows,
        "all_operational_reliance_eligible": bool(rows) and all(
            row["eligible_for_operational_reliance"] for row in rows
        ),
        "truth_guaranteed": False,
    }


def _synthetic_data(contract: Mapping[str, Any]) -> Dict[str, Any]:
    artifacts = []
    for raw in _sequence(contract.get("artifacts", ()), "artifacts"):
        row = _mapping(raw, "data_artifact")
        artifacts.append(DataArtifact(
            artifact_id=str(row.get("artifact_id") or ""),
            declared_lineage=str(row.get("declared_lineage") or ""),
            role=str(row.get("role") or ""),
            parent_ids=tuple(row.get("parent_ids") or ()),
            generator_id=str(row.get("generator_id") or ""),
            source_ref=str(row.get("source_ref") or ""),
        ))
    return asdict(enforce_synthetic_boundary(artifacts))


def _beliefs(contracts: Sequence[Any]) -> Dict[str, Any]:
    rows = []
    for raw in contracts:
        item = _mapping(raw, "belief_sandbox")
        rows.append(asdict(assess_sandbox_belief(CandidateBelief(
            belief_id=str(item.get("belief_id") or ""),
            statement=str(item.get("statement") or ""),
            evidence_ids=tuple(item.get("evidence_ids") or ()),
            independent_groups=tuple(item.get("independent_groups") or ()),
            falsifier=str(item.get("falsifier") or ""),
            preregistered_predictions=tuple(item.get("preregistered_predictions") or ()),
            resolved_predictions=item.get("resolved_predictions", 0),
            falsification_attempts=item.get("falsification_attempts", 0),
            contradictions=tuple(item.get("contradictions") or ()),
        ))))
    return {
        "assessments": rows,
        "promotion_proposals_eligible": sum(
            1 for row in rows if row["promotion_proposal_eligible"]
        ),
        "canonical_state_mutated": False,
    }


def _conspiracy(contracts: Sequence[Any]) -> Dict[str, Any]:
    rows = []
    for raw in contracts:
        item = _mapping(raw, "conspiracy_hypothesis")
        evidence = []
        for raw_evidence in _sequence(item.get("evidence", ()), "hypothesis_evidence"):
            evidence_row = _mapping(raw_evidence, "hypothesis_evidence")
            evidence.append(HypothesisEvidence(
                evidence_id=str(evidence_row.get("evidence_id") or ""),
                source_id=str(evidence_row.get("source_id") or ""),
                independence_group=str(evidence_row.get("independence_group") or ""),
                supports=bool(evidence_row.get("supports")),
                direct_observation=bool(evidence_row.get("direct_observation")),
                absence_of_expected_evidence=bool(
                    evidence_row.get("absence_of_expected_evidence")
                ),
                provenance_complete=bool(
                    evidence_row.get("provenance_complete", True)
                ),
            ))
        rows.append(asdict(assess_conspiracy_hypothesis(ConspiracyHypothesisInput(
            hypothesis_id=str(item.get("hypothesis_id") or ""),
            statement=str(item.get("statement") or ""),
            mechanism=str(item.get("mechanism") or ""),
            falsifier=str(item.get("falsifier") or ""),
            preregistered_predictions=tuple(item.get("preregistered_predictions") or ()),
            evidence=tuple(evidence),
            disconfirming_search_performed=bool(
                item.get("disconfirming_search_performed")
            ),
            alternative_explanations_considered=tuple(
                item.get("alternative_explanations_considered") or ()
            ),
        ))))
    return {
        "assessments": rows,
        "strong_label_eligible": sum(1 for row in rows if row["eligible_for_strong_label"]),
        "absence_of_evidence_treated_as_proof": False,
    }


def build_epistemic_stress_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    raw = result.get("epistemic_stress_contracts")
    if raw is None:
        return {
            "ran": True,
            "status": "NO_STRUCTURED_CONTRACT",
            "contracts_present": [],
            "natural_language_inference_performed": False,
            "result_status_upgraded": False,
            "truth_proven": False,
        }
    contracts = _mapping(raw, "epistemic_stress_contracts")
    allowed = {
        "unknown_unknown",
        "claim_insurance",
        "synthetic_data",
        "belief_sandbox",
        "conspiracy_hypotheses",
    }
    unknown_keys = sorted(set(contracts) - allowed)
    if unknown_keys:
        raise ValueError("unknown epistemic stress contract keys: " + ", ".join(unknown_keys))

    packet: Dict[str, Any] = {
        "ran": True,
        "status": "AUDITED",
        "contracts_present": sorted(contracts),
        "natural_language_inference_performed": False,
        "result_status_upgraded": False,
        "truth_proven": False,
    }
    if "unknown_unknown" in contracts:
        packet["unknown_unknown"] = _unknown_unknown(
            _mapping(contracts["unknown_unknown"], "unknown_unknown")
        )
    if "claim_insurance" in contracts:
        packet["claim_insurance"] = _claim_insurance(
            _sequence(contracts["claim_insurance"], "claim_insurance")
        )
    if "synthetic_data" in contracts:
        packet["synthetic_data"] = _synthetic_data(
            _mapping(contracts["synthetic_data"], "synthetic_data")
        )
    if "belief_sandbox" in contracts:
        packet["belief_sandbox"] = _beliefs(
            _sequence(contracts["belief_sandbox"], "belief_sandbox")
        )
    if "conspiracy_hypotheses" in contracts:
        packet["conspiracy_hypotheses"] = _conspiracy(
            _sequence(contracts["conspiracy_hypotheses"], "conspiracy_hypotheses")
        )
    return packet


def apply_epistemic_stress_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_epistemic_stress_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "contracts_present": [],
            "natural_language_inference_performed": False,
            "result_status_upgraded": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["epistemic_stress"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_epistemic_stress(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_epistemic_stress_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_epistemic_stress
