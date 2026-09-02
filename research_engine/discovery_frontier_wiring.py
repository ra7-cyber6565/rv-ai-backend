"""Production audit wiring for capabilities #62-#65.

Only structured material already present in a ``ResearchResult`` is admitted.
The wrapper never invents a mechanism, unexpected observation, target domain,
or evidence reference from free-form prose.  Output lives under
``coverage.discovery_frontier`` and cannot upgrade result status, evidence,
confidence, truth, or novelty labels.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Mapping, Sequence

from .discovery_frontier import (
    MechanismPattern,
    ResearchSignal,
    TransferTarget,
    build_discovery_frontier,
)


_INSTALLED = False
_SOURCE_RE = re.compile(r"\[\s*(S\d+)\s*\]", re.I)
_MAX_INPUTS = 2_000


def _clean(value: object, limit: int = 8_000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _token(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:24]}"


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _source_refs(value: object) -> tuple[str, ...]:
    refs = []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        refs.extend(_clean(item, 240) for item in value if _clean(item, 240))
    else:
        refs.extend(item.upper() for item in _SOURCE_RE.findall(str(value or "")))
    return tuple(sorted(set(refs)))[:64]


def _domain(result: Mapping[str, Any]) -> str:
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    advanced = coverage.get("advanced_discovery") if isinstance(coverage.get("advanced_discovery"), Mapping) else {}
    validation = advanced.get("domain_validation") if isinstance(advanced.get("domain_validation"), Mapping) else {}
    value = _clean(validation.get("domain") or result.get("domain") or "general", 240).lower()
    return value or "general"


def _gap_signals(result: Mapping[str, Any], domain: str) -> list[ResearchSignal]:
    coverage = result.get("coverage") if isinstance(result.get("coverage"), Mapping) else {}
    advanced = coverage.get("advanced_discovery") if isinstance(coverage.get("advanced_discovery"), Mapping) else {}
    recursive = advanced.get("recursive_research") if isinstance(advanced.get("recursive_research"), Mapping) else {}
    gaps = _sequence(recursive.get("gaps"))
    out = []
    for index, gap in enumerate(gaps[:128], 1):
        statement = _clean(gap, 2_000)
        if len(statement) < 5:
            continue
        out.append(ResearchSignal(
            signal_id=_token("gap", f"{index}:{statement}"),
            kind="gap",
            statement=statement,
            domain=domain,
            provenance_ref="coverage.advanced_discovery.recursive_research.gaps",
            provenance_complete=True,
            unresolved=True,
            relevance=0.85,
            surprise=0.0,
            evidence_strength=0.0,
        ))
    return out


def _contradiction_signals(result: Mapping[str, Any], domain: str) -> list[ResearchSignal]:
    out = []
    for index, item in enumerate(_sequence(result.get("contradictions"))[:256], 1):
        if not isinstance(item, Mapping):
            continue
        if item.get("valid") is False:
            continue
        statement = _clean(
            item.get("normalized_proposition")
            or item.get("summary")
            or item.get("proposition"),
            4_000,
        )
        if len(statement) < 5:
            continue
        refs = _source_refs(item.get("source_ids") or item.get("evidence_span_refs") or ())
        out.append(ResearchSignal(
            signal_id=_token("contradiction", f"{index}:{statement}"),
            kind="contradiction",
            statement=statement,
            domain=domain,
            source_refs=refs,
            provenance_ref=f"contradictions[{index - 1}]",
            provenance_complete=bool(refs),
            unresolved=True,
            relevance=0.9,
            surprise=0.4,
            evidence_strength=0.5 if refs else 0.0,
        ))
    return out


def _explicit_unexpected_signals(result: Mapping[str, Any], domain: str) -> tuple[list[ResearchSignal], int]:
    values = _sequence(result.get("unexpected_observations"))
    out = []
    rejected = 0
    for index, item in enumerate(values[:256], 1):
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        statement = _clean(item.get("statement"), 4_000)
        refs = _source_refs(item.get("source_refs"))
        provenance = _clean(item.get("provenance_ref"), 2_000)
        if len(statement) < 5:
            rejected += 1
            continue
        try:
            out.append(ResearchSignal(
                signal_id=_clean(item.get("signal_id"), 240) or _token("unexpected", f"{index}:{statement}"),
                kind="unexpected_observation",
                statement=statement,
                domain=_clean(item.get("domain"), 240).lower() or domain,
                source_refs=refs,
                provenance_ref=provenance,
                provenance_complete=bool(item.get("provenance_complete") is True and refs and provenance),
                unresolved=bool(item.get("unresolved", True)),
                relevance=float(item.get("relevance", 0.5)),
                surprise=float(item.get("surprise", 0.0)),
                evidence_strength=float(item.get("evidence_strength", 0.0)),
            ).normalized())
        except (TypeError, ValueError):
            rejected += 1
    return out, rejected


def _mechanisms(result: Mapping[str, Any]) -> tuple[list[MechanismPattern], int]:
    out = []
    rejected = 0
    for index, item in enumerate(_sequence(result.get("hypotheses"))[:256], 1):
        if not isinstance(item, Mapping):
            continue
        mechanism = _clean(item.get("mechanism"), 8_000)
        domain = _clean(item.get("mechanism_domain") or item.get("domain"), 240).lower()
        invariants = tuple(_clean(v, 1_000) for v in _sequence(item.get("invariants")) if _clean(v, 1_000))
        assumptions = tuple(_clean(v, 1_000) for v in _sequence(item.get("assumptions")) if _clean(v, 1_000))
        refs = _source_refs(item.get("evidence_refs") or item.get("supporting_evidence") or ())
        # Mechanism/domain/invariants/evidence must be explicit.  Missing fields
        # are not guessed from the hypothesis prose.
        if not mechanism or not domain or not invariants or not refs:
            continue
        try:
            out.append(MechanismPattern(
                mechanism_id=_clean(item.get("id") or item.get("hypothesis_id"), 240) or f"H{index}",
                domain=domain,
                mechanism=mechanism,
                invariants=invariants,
                assumptions=assumptions,
                evidence_refs=refs,
            ).normalized())
        except ValueError:
            rejected += 1
    return out, rejected


def _targets(result: Mapping[str, Any]) -> tuple[list[TransferTarget], int]:
    out = []
    rejected = 0
    for index, item in enumerate(_sequence(result.get("transfer_targets"))[:128], 1):
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        try:
            out.append(TransferTarget(
                target_id=_clean(item.get("target_id"), 240) or f"T{index}",
                domain=_clean(item.get("domain"), 240).lower(),
                context=_clean(item.get("context"), 8_000),
                preserved_invariants=tuple(
                    _clean(v, 1_000) for v in _sequence(item.get("preserved_invariants")) if _clean(v, 1_000)
                ),
                disanalogies=tuple(
                    _clean(v, 1_000) for v in _sequence(item.get("disanalogies")) if _clean(v, 1_000)
                ),
                evidence_refs=_source_refs(item.get("evidence_refs")),
            ).normalized())
        except ValueError:
            rejected += 1
    return out, rejected


def build_discovery_frontier_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    domain = _domain(result)
    signals = _gap_signals(result, domain) + _contradiction_signals(result, domain)
    unexpected, rejected_unexpected = _explicit_unexpected_signals(result, domain)
    signals.extend(unexpected)
    if len(signals) > _MAX_INPUTS:
        raise ValueError("discovery signals exceed runtime budget")
    mechanisms, rejected_mechanisms = _mechanisms(result)
    targets, rejected_targets = _targets(result)

    report = build_discovery_frontier(
        signals=signals,
        mechanisms=mechanisms,
        transfer_targets=targets,
        target_domain=domain,
        max_outputs=12,
    )
    report.update({
        "ran": True,
        "status": "AUDITED" if signals or mechanisms or targets else "NO_STRUCTURED_DISCOVERY_INPUTS",
        "runtime_domain": domain,
        "rejected_unexpected_observations": rejected_unexpected,
        "rejected_mechanisms": rejected_mechanisms,
        "rejected_transfer_targets": rejected_targets,
        "free_form_mechanism_inference_performed": False,
        "free_form_unexpected_observation_inference_performed": False,
        "result_status_upgraded": False,
    })
    return report


def apply_discovery_frontier_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_discovery_frontier_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "questions": [],
            "serendipity": [],
            "cross_domain_transfers": [],
            "creative_candidates": [],
            "candidate_discovery_label": "Candidate discovery — not established fact.",
            "truth_proven": False,
            "global_novelty_proven": False,
            "result_status_upgraded": False,
            "error": type(exc).__name__,
        }
    coverage["discovery_frontier"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_discovery_frontier(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_discovery_frontier_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_discovery_frontier
