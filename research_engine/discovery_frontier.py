"""Bounded candidate-discovery engine for capabilities #62-#65.

This module does not create facts.  It converts explicit unresolved research
signals and mechanism records into auditable *research candidates*:

* #62 Autonomous Question Generator -- questions only from supplied gaps,
  contradictions, null results, boundary failures, or explicit unexpected
  observations.
* #63 Serendipity Engine -- ranks provenance-backed unexpected observations;
  coincidence, surprise, or novelty alone never becomes a discovery claim.
* #64 Cross-Domain Transfer -- tests whether a supplied mechanism is even a
  defensible analogy in a distinct target domain, with preserved invariants,
  disanalogies and a falsifier made explicit.
* #65 Scientific Creativity -- recombines supplied evidence-backed mechanisms
  into bounded experiment candidates, never established claims.

Evolutionary population search remains delegated to ``hypothesis_evolution``
(#66) rather than duplicated here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple


_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_SIGNAL_KINDS = {
    "gap",
    "contradiction",
    "unexpected_observation",
    "null_result",
    "boundary_failure",
}
_MAX_SIGNALS = 2_000
_MAX_MECHANISMS = 512
_MAX_OUTPUTS = 64


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("discovery payload must be finite JSON-compatible data") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _text(value: object, field: str, *, minimum: int = 3, maximum: int = 8_000) -> str:
    text = " ".join(str(value or "").split())
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} length is invalid")
    return text


def _unit(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be finite and in [0,1]")
    return number


def _bounded_count(value: int, field: str, *, low: int = 1, high: int = _MAX_OUTPUTS) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field} must be an integer in [{low},{high}]")
    return value


def _items(values: Sequence[object], field: str, *, maximum: int = 256) -> Tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ValueError(f"{field} must be a sequence")
    if len(values) > maximum:
        raise ValueError(f"{field} exceeds bounded size")
    out = tuple(sorted({_text(item, field, minimum=1, maximum=1_000) for item in values}))
    return out


@dataclass(frozen=True)
class ResearchSignal:
    signal_id: str
    kind: str
    statement: str
    domain: str
    source_refs: Tuple[str, ...] = ()
    provenance_ref: str = ""
    provenance_complete: bool = False
    unresolved: bool = True
    relevance: float = 0.5
    surprise: float = 0.0
    evidence_strength: float = 0.0

    def normalized(self) -> "ResearchSignal":
        kind = str(self.kind or "").strip().lower()
        if kind not in _ALLOWED_SIGNAL_KINDS:
            raise ValueError("unsupported signal kind")
        refs = _items(self.source_refs, "source_ref", maximum=64)
        provenance = str(self.provenance_ref or "").strip()
        if provenance and len(provenance) > 2_000:
            raise ValueError("provenance_ref is too long")
        return ResearchSignal(
            signal_id=_id(self.signal_id, "signal_id"),
            kind=kind,
            statement=_text(self.statement, "signal.statement", minimum=5),
            domain=_text(self.domain, "signal.domain", minimum=2, maximum=240).lower(),
            source_refs=refs,
            provenance_ref=provenance,
            provenance_complete=bool(self.provenance_complete),
            unresolved=bool(self.unresolved),
            relevance=_unit(self.relevance, "signal.relevance"),
            surprise=_unit(self.surprise, "signal.surprise"),
            evidence_strength=_unit(self.evidence_strength, "signal.evidence_strength"),
        )


@dataclass(frozen=True)
class MechanismPattern:
    mechanism_id: str
    domain: str
    mechanism: str
    invariants: Tuple[str, ...]
    assumptions: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]

    def normalized(self) -> "MechanismPattern":
        invariants = _items(self.invariants, "mechanism.invariant", maximum=64)
        assumptions = _items(self.assumptions, "mechanism.assumption", maximum=64)
        refs = _items(self.evidence_refs, "mechanism.evidence_ref", maximum=64)
        if not invariants:
            raise ValueError("mechanism requires at least one invariant")
        if not refs:
            raise ValueError("mechanism requires evidence_refs")
        return MechanismPattern(
            mechanism_id=_id(self.mechanism_id, "mechanism_id"),
            domain=_text(self.domain, "mechanism.domain", minimum=2, maximum=240).lower(),
            mechanism=_text(self.mechanism, "mechanism", minimum=8),
            invariants=invariants,
            assumptions=assumptions,
            evidence_refs=refs,
        )


@dataclass(frozen=True)
class TransferTarget:
    target_id: str
    domain: str
    context: str
    preserved_invariants: Tuple[str, ...]
    disanalogies: Tuple[str, ...]
    evidence_refs: Tuple[str, ...] = ()

    def normalized(self) -> "TransferTarget":
        preserved = _items(self.preserved_invariants, "target.preserved_invariant", maximum=64)
        disanalogies = _items(self.disanalogies, "target.disanalogy", maximum=64)
        refs = _items(self.evidence_refs, "target.evidence_ref", maximum=64)
        if not disanalogies:
            raise ValueError("cross-domain target requires explicit disanalogies")
        return TransferTarget(
            target_id=_id(self.target_id, "target_id"),
            domain=_text(self.domain, "target.domain", minimum=2, maximum=240).lower(),
            context=_text(self.context, "target.context", minimum=5),
            preserved_invariants=preserved,
            disanalogies=disanalogies,
            evidence_refs=refs,
        )


def _question_for(signal: ResearchSignal) -> Dict[str, Any]:
    templates = {
        "gap": "What observation or experiment would close this evidence gap: {s}?",
        "contradiction": "What discriminating observation would resolve this contradiction: {s}?",
        "unexpected_observation": "What mechanism could explain this unexpected observation without contradicting established constraints: {s}?",
        "null_result": "Which assumption, boundary condition, or power limitation best explains this null result: {s}?",
        "boundary_failure": "Which boundary condition failed, and what test would distinguish the competing explanations: {s}?",
    }
    statement = signal.statement
    priority = (
        0.45 * signal.relevance
        + 0.30 * (1.0 - signal.evidence_strength)
        + 0.25 * (signal.surprise if signal.kind == "unexpected_observation" else 0.5)
    )
    payload = {
        "trigger_id": signal.signal_id,
        "trigger_kind": signal.kind,
        "question": templates[signal.kind].format(s=statement),
        "domain": signal.domain,
        "source_refs": list(signal.source_refs),
        "provenance_ref": signal.provenance_ref,
        "priority_score": round(priority, 6),
        "priority_is_truth_probability": False,
        "must_answer_with_new_evidence": True,
        "candidate_only": True,
    }
    return {**payload, "candidate_hash": _hash(payload)}


def generate_autonomous_questions(
    signals: Sequence[ResearchSignal], *, max_questions: int = 12
) -> Tuple[Dict[str, Any], ...]:
    limit = _bounded_count(max_questions, "max_questions")
    if isinstance(signals, (str, bytes, bytearray)) or not isinstance(signals, Sequence):
        raise ValueError("signals must be a sequence")
    if len(signals) > _MAX_SIGNALS:
        raise ValueError("signals exceed bounded size")
    normalized = [item.normalized() for item in signals]
    if len({item.signal_id for item in normalized}) != len(normalized):
        raise ValueError("signal_id values must be unique")
    candidates = [_question_for(item) for item in normalized if item.unresolved]
    candidates.sort(key=lambda row: (-float(row["priority_score"]), row["trigger_id"]))
    return tuple(candidates[:limit])


def rank_serendipity(
    signals: Sequence[ResearchSignal], *, max_candidates: int = 12
) -> Tuple[Dict[str, Any], ...]:
    limit = _bounded_count(max_candidates, "max_candidates")
    if len(signals) > _MAX_SIGNALS:
        raise ValueError("signals exceed bounded size")
    out = []
    for raw in signals:
        item = raw.normalized()
        if item.kind != "unexpected_observation" or not item.unresolved:
            continue
        provenance_ok = bool(item.provenance_complete and item.provenance_ref and item.source_refs)
        score = 0.45 * item.surprise + 0.35 * item.relevance + 0.20 * item.evidence_strength
        state = (
            "CANDIDATE_SERENDIPITY"
            if provenance_ok and item.surprise >= 0.5 and item.relevance >= 0.5
            else "REVIEW_REQUIRED"
        )
        payload = {
            "signal_id": item.signal_id,
            "state": state,
            "score": round(score, 6),
            "provenance_complete": provenance_ok,
            "source_refs": list(item.source_refs),
            "provenance_ref": item.provenance_ref,
            "candidate_discovery_not_established_fact": True,
            "global_novelty_proven": False,
            "truth_proven": False,
        }
        out.append({**payload, "candidate_hash": _hash(payload)})
    out.sort(key=lambda row: (-float(row["score"]), row["signal_id"]))
    return tuple(out[:limit])


def evaluate_cross_domain_transfer(
    mechanism: MechanismPattern, target: TransferTarget
) -> Dict[str, Any]:
    source = mechanism.normalized()
    destination = target.normalized()
    if source.domain == destination.domain:
        raise ValueError("cross-domain transfer requires distinct source and target domains")
    source_invariants = {item.casefold(): item for item in source.invariants}
    preserved_keys = {item.casefold() for item in destination.preserved_invariants}
    matched = tuple(sorted(source_invariants[key] for key in source_invariants if key in preserved_keys))
    coverage = len(matched) / len(source.invariants)
    target_evidence_present = bool(destination.evidence_refs)
    conceptual_gate = bool(matched and destination.disanalogies and target_evidence_present)
    score = max(0.0, min(1.0, 0.70 * coverage + 0.30 * (1.0 if target_evidence_present else 0.0)))
    payload = {
        "mechanism_id": source.mechanism_id,
        "target_id": destination.target_id,
        "source_domain": source.domain,
        "target_domain": destination.domain,
        "mechanism": source.mechanism,
        "matched_invariants": list(matched),
        "unmatched_invariants": sorted(
            item for item in source.invariants if item.casefold() not in preserved_keys
        ),
        "disanalogies": list(destination.disanalogies),
        "source_evidence_refs": list(source.evidence_refs),
        "target_evidence_refs": list(destination.evidence_refs),
        "transfer_score": round(score, 6),
        "conceptual_gate_passed": conceptual_gate,
        "falsifier": (
            "Reject the transfer if a required invariant fails in the target, "
            "or preregistered target measurements contradict the transferred mechanism."
        ),
        "candidate_discovery_not_established_fact": True,
        "truth_proven": False,
        "global_novelty_proven": False,
    }
    return {**payload, "candidate_hash": _hash(payload)}


def generate_creative_candidates(
    mechanisms: Sequence[MechanismPattern], *, target_domain: str, max_candidates: int = 12
) -> Tuple[Dict[str, Any], ...]:
    limit = _bounded_count(max_candidates, "max_candidates")
    if isinstance(mechanisms, (str, bytes, bytearray)) or not isinstance(mechanisms, Sequence):
        raise ValueError("mechanisms must be a sequence")
    if len(mechanisms) > _MAX_MECHANISMS:
        raise ValueError("mechanisms exceed bounded size")
    target = _text(target_domain, "target_domain", minimum=2, maximum=240).lower()
    normalized = tuple(item.normalized() for item in mechanisms)
    if len({item.mechanism_id for item in normalized}) != len(normalized):
        raise ValueError("mechanism_id values must be unique")

    out = []
    for left, right in combinations(normalized, 2):
        if left.mechanism_id == right.mechanism_id:
            continue
        evidence = tuple(sorted(set(left.evidence_refs) | set(right.evidence_refs)))
        shared_invariants = tuple(sorted(
            set(item.casefold() for item in left.invariants)
            & set(item.casefold() for item in right.invariants)
        ))
        payload = {
            "mechanism_ids": [left.mechanism_id, right.mechanism_id],
            "source_domains": sorted({left.domain, right.domain}),
            "target_domain": target,
            "research_candidate": (
                f"Test whether the interaction of [{left.mechanism}] and "
                f"[{right.mechanism}] produces a discriminating effect in {target}."
            ),
            "shared_invariants": list(shared_invariants),
            "evidence_refs": list(evidence),
            "falsifier": (
                "Reject the combined candidate if preregistered measurements show "
                "no discriminating effect beyond either mechanism alone."
            ),
            "requires_ablation": True,
            "requires_independent_validation": True,
            "candidate_discovery_not_established_fact": True,
            "truth_proven": False,
            "global_novelty_proven": False,
        }
        out.append({**payload, "candidate_hash": _hash(payload)})
    out.sort(key=lambda row: (row["mechanism_ids"], row["candidate_hash"]))
    return tuple(out[:limit])


def build_discovery_frontier(
    *,
    signals: Sequence[ResearchSignal],
    mechanisms: Sequence[MechanismPattern] = (),
    transfer_targets: Sequence[TransferTarget] = (),
    target_domain: str = "general",
    max_outputs: int = 12,
) -> Dict[str, Any]:
    limit = _bounded_count(max_outputs, "max_outputs")
    normalized_signals = tuple(item.normalized() for item in signals)
    normalized_mechanisms = tuple(item.normalized() for item in mechanisms)
    normalized_targets = tuple(item.normalized() for item in transfer_targets)
    if len(normalized_signals) > _MAX_SIGNALS:
        raise ValueError("signals exceed bounded size")
    if len(normalized_mechanisms) > _MAX_MECHANISMS:
        raise ValueError("mechanisms exceed bounded size")

    questions = generate_autonomous_questions(normalized_signals, max_questions=limit)
    serendipity = rank_serendipity(normalized_signals, max_candidates=limit)
    transfers = []
    for mechanism in normalized_mechanisms:
        for target in normalized_targets:
            if mechanism.domain == target.domain:
                continue
            transfers.append(evaluate_cross_domain_transfer(mechanism, target))
    transfers.sort(key=lambda row: (-float(row["transfer_score"]), row["mechanism_id"], row["target_id"]))
    transfers = transfers[:limit]
    creative = generate_creative_candidates(
        normalized_mechanisms, target_domain=target_domain, max_candidates=limit
    ) if len(normalized_mechanisms) >= 2 else ()

    body = {
        "questions": list(questions),
        "serendipity": list(serendipity),
        "cross_domain_transfers": list(transfers),
        "creative_candidates": list(creative),
        "input_signal_count": len(normalized_signals),
        "input_mechanism_count": len(normalized_mechanisms),
        "input_transfer_target_count": len(normalized_targets),
        "evolutionary_search_delegate": "research_engine.hypothesis_evolution",
        "evolutionary_search_executed_here": False,
        "candidate_discovery_label": "Candidate discovery — not established fact.",
        "truth_proven": False,
        "global_novelty_proven": False,
        "real_world_success_probability_claimed": False,
    }
    return {**body, "report_hash": _hash(body)}
