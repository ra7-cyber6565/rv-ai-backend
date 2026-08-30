"""Bridge capability #41 Reality Oracle to ``ScientificMemory`` prediction state.

The bridge reuses the existing immutable prediction registry rather than
creating a second prediction store. It only converts an unresolved, previously
registered threshold prediction into a strict Reality Oracle contract and can
optionally record the observed value back into ScientificMemory after a
non-inconclusive evaluation.

Recording an outcome is not a LIVE proof. The Reality Oracle evaluation still
carries ``live_observation_proven=False`` until a separate trusted live attestor
validates the measurement source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from .reality_oracle import (
    ObservationReceipt,
    OracleEvaluation,
    PredictionContract,
    evaluate_reality,
    freeze_prediction_contract,
)


@dataclass(frozen=True)
class MemoryOracleResult:
    evaluation: OracleEvaluation
    memory_outcome: Optional[Dict[str, Any]]
    committed_to_memory: bool
    live_proof_minted: bool = False
    truth_proven: bool = False


def contract_from_scientific_memory(
    memory: Any,
    prediction_id: str,
    *,
    unit: str,
) -> PredictionContract:
    """Load one unresolved threshold prediction and freeze an oracle contract."""
    data = memory.load()
    predictions = data.get("predictions")
    if not isinstance(predictions, dict):
        raise ValueError("scientific memory predictions store is invalid")
    record = predictions.get(str(prediction_id))
    if not isinstance(record, dict):
        raise KeyError(prediction_id)
    if record.get("resolved") is True:
        raise ValueError("prediction is already resolved")

    return freeze_prediction_contract(
        prediction_id=str(record.get("prediction_id") or ""),
        hypothesis_id=str(record.get("hypothesis_id") or ""),
        metric=str(record.get("metric") or ""),
        unit=unit,
        rule="directional",
        target=record.get("threshold"),
        direction=str(record.get("direction") or ""),
        tolerance=0.0,
        preregistered_at=str(record.get("registered_at") or ""),
        evaluation_after=str(record.get("evaluation_after") or ""),
        protocol_hash=str(record.get("protocol_hash") or ""),
    )


def evaluate_memory_prediction(
    memory: Any,
    prediction_id: str,
    observation: ObservationReceipt,
    *,
    unit: str,
    commit: bool = False,
    evidence_ids: Sequence[str] = (),
) -> MemoryOracleResult:
    """Evaluate a registered prediction and optionally record its observed value.

    ``commit=True`` is intentionally explicit. An inconclusive result can never
    resolve the persistent prediction. A successful memory write remains an
    outcome record only; it is not converted to trusted runtime/live evidence.
    """
    contract = contract_from_scientific_memory(memory, prediction_id, unit=unit)
    evaluation = evaluate_reality(contract, observation)
    if not commit:
        return MemoryOracleResult(evaluation, None, False)
    if evaluation.status == "INCONCLUSIVE":
        raise ValueError("inconclusive oracle evaluation cannot resolve prediction memory")

    outcome = memory.resolve_prediction(
        prediction_id,
        observed_value=observation.observed_value,
        evaluated_at=observation.observed_at,
        evidence_ids=evidence_ids,
    )
    expected_pass = evaluation.status == "MATCH"
    if bool(outcome.get("passed")) != expected_pass:
        raise RuntimeError("scientific memory outcome disagrees with oracle evaluation")
    return MemoryOracleResult(evaluation, dict(outcome), True)
