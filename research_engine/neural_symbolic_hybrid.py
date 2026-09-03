"""Neural + symbolic hybrid verification foundation for capability #67.

A neural/model system may propose a structured claim, but it cannot certify its
own logical validity.  This engine binds each proposal to a model identity,
revision and output digest, then independently runs the explicit propositional
contract through the existing symbolic SAT verifier.

No natural-language-to-logic conversion occurs here.  Neural confidence is
preserved as model metadata only and is never interpreted as theorem truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple

from .runtime_capability_wiring import evaluate_formal_logic_contract

_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_PROPOSALS = 1000


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _sha(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return text


def _confidence(value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("model_confidence must be finite and in [0,1]")
    return number


def _canonical_hash(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("hybrid payload must be finite JSON-compatible data") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NeuralProposal:
    proposal_id: str
    model_id: str
    model_revision: str
    model_output_sha256: str
    model_confidence: float
    formal_logic: Mapping[str, Any]
    self_reported_proved: bool = False


@dataclass(frozen=True)
class HybridProposalAudit:
    proposal_id: str
    model_id: str
    model_revision: str
    model_output_sha256: str
    model_confidence: float
    contract_sha256: str
    symbolic_status: str
    symbolic_entailed: bool | None
    symbolic_consistent: bool
    counterexample: Mapping[str, bool]
    hybrid_gate_passed: bool
    self_reported_proved: bool
    model_confidence_is_truth_probability: bool = False
    neural_self_report_can_override_symbolic_gate: bool = False
    natural_language_formalization_performed: bool = False
    truth_proven: bool = False


@dataclass(frozen=True)
class NeuralSymbolicReport:
    audits: Tuple[HybridProposalAudit, ...]
    passed: int
    failed: int
    report_sha256: str
    neural_inference_executed_by_this_function: bool = False
    symbolic_verification_executed: bool = True
    truth_proven: bool = False


def audit_neural_symbolic(proposals: Sequence[NeuralProposal]) -> NeuralSymbolicReport:
    if isinstance(proposals, (str, bytes, bytearray)) or not isinstance(proposals, Sequence):
        raise ValueError("proposals must be a finite sequence")
    if not 1 <= len(proposals) <= _MAX_PROPOSALS:
        raise ValueError(f"proposals must contain 1..{_MAX_PROPOSALS} items")

    normalized = []
    seen = set()
    for proposal in proposals:
        proposal_id = _id(proposal.proposal_id, "proposal_id")
        if proposal_id in seen:
            raise ValueError("proposal_id values must be unique")
        seen.add(proposal_id)
        model_id = _id(proposal.model_id, "model_id")
        model_revision = _id(proposal.model_revision, "model_revision")
        output_sha = _sha(proposal.model_output_sha256, "model_output_sha256")
        confidence = _confidence(proposal.model_confidence)
        if not isinstance(proposal.formal_logic, Mapping):
            raise ValueError("formal_logic must be a mapping")
        contract = dict(proposal.formal_logic)
        contract_hash = _canonical_hash(contract)
        logic = evaluate_formal_logic_contract(contract)
        entailed = logic.get("entailed")
        consistent = bool(logic.get("consistent"))
        gate = entailed is True and consistent and logic.get("status") == "PROVED"
        normalized.append(HybridProposalAudit(
            proposal_id=proposal_id,
            model_id=model_id,
            model_revision=model_revision,
            model_output_sha256=output_sha,
            model_confidence=confidence,
            contract_sha256=contract_hash,
            symbolic_status=str(logic.get("status") or "UNKNOWN"),
            symbolic_entailed=entailed if entailed in (True, False, None) else None,
            symbolic_consistent=consistent,
            counterexample=dict(logic.get("counterexample") or {}),
            hybrid_gate_passed=gate,
            self_reported_proved=bool(proposal.self_reported_proved),
        ))

    audits = tuple(sorted(normalized, key=lambda item: item.proposal_id))
    report_payload = [
        {
            "proposal_id": item.proposal_id,
            "model_id": item.model_id,
            "model_revision": item.model_revision,
            "model_output_sha256": item.model_output_sha256,
            "model_confidence": item.model_confidence,
            "contract_sha256": item.contract_sha256,
            "symbolic_status": item.symbolic_status,
            "symbolic_entailed": item.symbolic_entailed,
            "symbolic_consistent": item.symbolic_consistent,
            "counterexample": item.counterexample,
            "hybrid_gate_passed": item.hybrid_gate_passed,
            "self_reported_proved": item.self_reported_proved,
        }
        for item in audits
    ]
    passed = sum(1 for item in audits if item.hybrid_gate_passed)
    return NeuralSymbolicReport(
        audits=audits,
        passed=passed,
        failed=len(audits) - passed,
        report_sha256=_canonical_hash(report_payload),
        neural_inference_executed_by_this_function=False,
        symbolic_verification_executed=True,
        truth_proven=False,
    )
