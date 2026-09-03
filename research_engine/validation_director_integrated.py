"""Strict fail-closed facade for the AI-2 quantitative validation director.

The base director deliberately accepts caller supplied execution packets so it can
recompute metrics.  This facade adds the epistemic boundary that a validation
system needs in production:

* a contaminated/invalid evaluation cannot *falsify* a hypothesis -- it becomes
  INCONCLUSIVE because the experiment no longer identifies the tested claim;
* self-reported aggregate metrics cannot become an unconditional PASS unless
  independently verified/recomputed;
* trading/predictive PASS requires auditable out-of-sample evidence, not merely
  a profitable/accurate number;
* a bare boolean saying "baseline beaten" is not quantitative baseline proof;
* an unsealed/reused/tuned final holdout cannot support promotion.

The facade only downgrades.  It never upgrades a status emitted by the base
implementation and performs no network/model/API calls.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .validation_director import QuantitativeValidationDirector as _BaseDirector
from .validation_guard import audit_holdout
from .validation_types import HypothesisStatus, TestState, mapping, number, text


def _raw_observations_present(execution: Mapping[str, Any]) -> bool:
    """True only when metrics can be recomputed from supplied observations."""
    if execution.get("trades"):
        return True
    if execution.get("y_true") is not None and execution.get("y_pred") is not None:
        return True
    if execution.get("group_a") is not None and execution.get("group_b") is not None:
        return True
    return False


def _baseline_quantitatively_evidenced(execution: Mapping[str, Any], metrics: Mapping[str, Any], domain: str) -> bool:
    """Reject a bare self-attested baseline boolean as quantitative evidence."""
    candidate = number(execution.get("candidate_result"))
    baseline = number(execution.get("baseline_result"))
    if candidate is not None and baseline is not None:
        return True

    rule = mapping(execution.get("decision_rule"))
    metric = text(rule.get("metric")).lower()
    if any(token in metric for token in ("baseline", "difference", "delta")):
        return number(metrics.get(text(rule.get("metric")))) is not None

    if domain == "trading" and metric == "expectancy":
        # No-trade/zero-exposure is an exactly defined zero-P&L baseline.  The
        # metric still must have been recomputed/observed; the bool alone is not enough.
        return number(metrics.get("expectancy")) is not None
    if "majority_baseline_accuracy" in metrics and number(metrics.get("accuracy")) is not None:
        return number(metrics.get("majority_baseline_accuracy")) is not None
    return False


def _execution_for(executions: Mapping[str, Any], hypothesis_id: str) -> Mapping[str, Any]:
    return mapping(executions.get(hypothesis_id) or executions.get(f"T-{hypothesis_id}"))


def _downgrade(decision: Dict[str, Any], status: str, reason: str, code: str) -> Dict[str, Any]:
    out = dict(decision or {})
    out["status"] = status
    old = text(out.get("reason"))
    out["reason"] = (old + " " + reason).strip()
    codes = list(out.get("integrity_codes") or [])
    if code not in codes:
        codes.append(code)
    out["integrity_codes"] = codes
    return out


def enforce_validation_packet_integrity(
    packet: Mapping[str, Any],
    *,
    execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Apply monotonic epistemic downgrades to one AI-2 packet."""
    data = dict(packet or {})
    executions = dict(mapping(execution_packets))
    domain = text(data.get("domain")).lower()
    result_rows = []
    decisions_by_hypothesis: Dict[str, Dict[str, Any]] = {}
    counters = {
        "invalidated_evaluations": 0,
        "self_reported_passes_downgraded": 0,
        "baseline_attestations_downgraded": 0,
        "holdout_integrity_downgrades": 0,
        "oos_evidence_downgrades": 0,
    }

    for raw in data.get("results") or []:
        row = dict(raw or {})
        hid = text(row.get("hypothesis_id"))
        execution = _execution_for(executions, hid)
        decision = dict(mapping(row.get("decision")))
        status = text(decision.get("status"), HypothesisStatus.INCONCLUSIVE.value)
        metrics = mapping(row.get("metrics"))
        bias = mapping(row.get("bias_audit"))
        holdout = mapping(row.get("untouched_test_integrity"))

        # A contaminated experiment does not establish H=true or H=false.  It
        # invalidates the performance inference, so FAIL/PASS both collapse to
        # INCONCLUSIVE rather than falsely declaring the hypothesis disproved.
        if bias.get("fatal"):
            decision = _downgrade(
                decision,
                HypothesisStatus.INCONCLUSIVE.value,
                "Evaluation is invalidated by confirmed fatal leakage/bias; this run cannot establish either truth or falsity of the hypothesis.",
                "INVALID_EVALUATION_FATAL_LEAKAGE",
            )
            counters["invalidated_evaluations"] += 1
            status = decision["status"]

        # Re-audit the holdout with the strict guard when a holdout is present.
        if execution.get("untouched_test") is not None:
            strict_holdout = audit_holdout(execution)
            row["untouched_test_integrity"] = strict_holdout
            holdout = strict_holdout
            if strict_holdout.get("evaluation_valid_for_final_claim") is False:
                decision = _downgrade(
                    decision,
                    HypothesisStatus.INCONCLUSIVE.value,
                    "The final holdout is not auditable as a one-time pre-sealed untouched evaluation; its result cannot decide this hypothesis.",
                    "INVALID_OR_UNPROVEN_FINAL_HOLDOUT",
                )
                counters["holdout_integrity_downgrades"] += 1
                status = decision["status"]

        if status == HypothesisStatus.PASS.value:
            # Aggregate metrics can be typed into a packet.  Unless they were
            # independently verified, a PASS based only on those numbers is at
            # most conditional. Raw observations are recomputed by the base
            # director and therefore carry a stronger (still source-dependent)
            # receipt.
            metrics_only = bool(execution.get("metrics")) and not _raw_observations_present(execution)
            independently_verified = bool(execution.get("metrics_verified"))
            if metrics_only and not independently_verified:
                decision = _downgrade(
                    decision,
                    HypothesisStatus.CONDITIONAL_PASS.value,
                    "PASS depends on caller-supplied aggregate metrics that were not independently recomputed/verified.",
                    "SELF_REPORTED_METRICS",
                )
                counters["self_reported_passes_downgraded"] += 1
                status = decision["status"]

        if status == HypothesisStatus.PASS.value and execution.get("baseline_beaten") is True:
            if not _baseline_quantitatively_evidenced(execution, metrics, domain):
                decision = _downgrade(
                    decision,
                    HypothesisStatus.CONDITIONAL_PASS.value,
                    "A boolean 'baseline_beaten' attestation is not quantitative baseline evidence; supply/recompute the baseline result.",
                    "BASELINE_ATTESTATION_ONLY",
                )
                counters["baseline_attestations_downgraded"] += 1
                status = decision["status"]

        if status == HypothesisStatus.PASS.value and domain in {"trading", "prediction"}:
            valid_holdout = bool(holdout.get("evaluation_valid_for_final_claim"))
            other_oos = bool(
                execution.get("out_of_sample_observed")
                or execution.get("external_replication_observed")
                or execution.get("walk_forward_observed")
            )
            if not valid_holdout and not other_oos:
                decision = _downgrade(
                    decision,
                    HypothesisStatus.CONDITIONAL_PASS.value,
                    "Predictive/trading promotion lacks auditable out-of-sample, walk-forward, or external replication evidence.",
                    "OUT_OF_SAMPLE_EVIDENCE_MISSING",
                )
                counters["oos_evidence_downgrades"] += 1

        row["decision"] = decision
        row["epistemic_evidence_origin"] = (
            "RECOMPUTED_FROM_SUPPLIED_RAW_OBSERVATIONS"
            if _raw_observations_present(execution)
            else ("CALLER_SUPPLIED_AGGREGATE_METRICS" if execution.get("metrics") else "NO_OBSERVED_EXECUTION_DATA")
        )
        row["independent_data_provenance_verified"] = bool(execution.get("data_provenance_verified"))
        result_rows.append(row)
        decisions_by_hypothesis[hid] = decision

    hypotheses = []
    for raw in data.get("hypotheses") or []:
        h = dict(raw or {})
        hid = text(h.get("hypothesis_id") or h.get("id"))
        decision = decisions_by_hypothesis.get(hid)
        if decision:
            h["status"] = decision.get("status", HypothesisStatus.INCONCLUSIVE.value)
            h["status_reason"] = decision.get("reason", "")
        hypotheses.append(h)

    data["results"] = result_rows
    data["hypotheses"] = hypotheses
    integrity = {
        "ran": True,
        "monotonic_downgrade_only": True,
        "contaminated_evaluation_can_disprove_hypothesis": False,
        "self_reported_metrics_can_unconditionally_pass": False,
        "bare_baseline_attestation_is_proof": False,
        "predictive_pass_requires_oos_evidence": True,
        **counters,
    }
    data["validation_integrity"] = integrity

    # Confidence here is plan-completeness confidence, never P(theory true).
    # An integrity downgrade should not leave the packet looking maximally
    # complete.  This is deliberately monotonic and bounded.
    current_conf = number(data.get("confidence"))
    if current_conf is not None and any(counters.values()):
        penalty = min(30.0, 5.0 * sum(counters.values()))
        data["confidence"] = max(0, round(current_conf - penalty))
        blockers = list(data.get("higher_score_blockers") or [])
        blocker = "One or more observed-result claims were downgraded by the strict validation-integrity gate."
        if blocker not in blockers:
            blockers.append(blocker)
        data["higher_score_blockers"] = blockers
    return data


class IntegratedQuantitativeValidationDirector(_BaseDirector):
    """Production AI-2 facade; base functionality plus strict integrity gate."""

    def analyze(
        self,
        question: str,
        proposal: Optional[Mapping[str, Any]] = None,
        execution_packets: Optional[Mapping[str, Mapping[str, Any]]] = None,
        agent_outputs: Optional[Mapping[str, Any]] = None,
        phase: str = "first",
    ) -> Dict[str, Any]:
        packet = super().analyze(question, proposal, execution_packets, agent_outputs, phase)
        return enforce_validation_packet_integrity(packet, execution_packets=execution_packets)


QuantitativeValidationDirector = IntegratedQuantitativeValidationDirector


__all__ = [
    "IntegratedQuantitativeValidationDirector",
    "QuantitativeValidationDirector",
    "enforce_validation_packet_integrity",
]
