"""Final one-way truth guards for the AI-2 line-by-line runtime audit.

This module exists to make downgrade decisions monotonic across composition:
a later AI-2 hardening stage may never accidentally restore a decisive verdict
that an earlier verified bias/leakage guard invalidated.  It is additive,
deterministic and fail-closed; it never creates observations or upgrades status.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, MutableMapping

from .validation_contracts import CONDITIONAL_PASS, FAIL, INCONCLUSIVE, PASS

_DECISIVE = {PASS, CONDITIONAL_PASS, FAIL}


def _verified_bias_findings(packet: Mapping[str, Any]) -> list:
    guards = packet.get("decision_guards")
    if not isinstance(guards, Mapping):
        return []
    bias = guards.get("bias_leakage_guard")
    if not isinstance(bias, Mapping):
        return []
    findings = bias.get("verified_findings")
    return list(findings) if isinstance(findings, list) else []


def enforce_ai2_final_truth_guards(research_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copied result with monotonic fail-closed AI-2 truth guards applied."""
    enriched = dict(research_result or {})
    raw_packet = enriched.get("ai2_validation")
    if not isinstance(raw_packet, Mapping):
        return enriched
    packet: Dict[str, Any] = deepcopy(dict(raw_packet))
    findings = _verified_bias_findings(packet)
    if not findings:
        enriched["ai2_validation"] = packet
        return enriched

    sections = packet.get("sections")
    if not isinstance(sections, MutableMapping):
        enriched["ai2_validation"] = packet
        return enriched
    experiment_section = sections.get("6. Exact Experiments / Backtests / Simulations Required")
    rows = experiment_section.get("domain_hypothesis_experiments") if isinstance(experiment_section, Mapping) else None
    downgraded = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, MutableMapping):
                continue
            status = row.get("hypothesis_status")
            if status not in _DECISIVE:
                continue
            row.setdefault("pre_final_bias_guard_status", status)
            row["hypothesis_status"] = INCONCLUSIVE
            row["status_reason"] = (
                "INCONCLUSIVE — a provenance/evidence-bearing bias or leakage finding is present; "
                "the decisive verdict cannot be restored by later scoring or multi-metric composition "
                "until the affected design/data path is cleanly re-tested."
            )
            row["final_truth_guard"] = "BIAS_OR_LEAKAGE_DOWNGRADE_IS_MONOTONIC"
            downgraded.append(str(row.get("hypothesis_id") or "UNKNOWN"))

    guards = packet.setdefault("decision_guards", {})
    if isinstance(guards, MutableMapping):
        final_guard = guards.setdefault("final_monotonic_truth_guard", {})
        if isinstance(final_guard, MutableMapping):
            final_guard.update({
                "active": True,
                "verified_bias_finding_count": len(findings),
                "downgraded_hypothesis_ids": downgraded,
                "rule": (
                    "Verified bias/leakage downgrade is monotonic: later AI-2 layers may not restore "
                    "PASS, CONDITIONAL PASS, or FAIL until clean re-test evidence replaces the affected path."
                ),
            })

    audit = packet.get("line_by_line_spec_audit")
    if isinstance(audit, MutableMapping):
        audit["monotonic_bias_guard_enforced"] = True
        audit["truth_guard_rule"] = (
            "Later composition can only preserve/downgrade a verified-bias verdict, never re-upgrade it."
        )

    enriched["ai2_validation"] = packet
    return enriched
