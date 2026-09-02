"""Measured MARATHON research-process assurance.

This module deliberately does *not* estimate whether an answer or hypothesis is
90--95% true/profitable/successful.  It measures only whether the configured
research process actually ran: search rounds, mandatory evidence-axis search,
independent sources, legally accessible full text, opposition search, reasoning
passes, claim checks and hypothesis testability.

The score is an audit/checklist coverage number.  Missing/unknown work loses
credit; a large source count cannot hide a mandatory search or verification gap.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


SCHEMA_VERSION = "1.0"
NOT_A_PROBABILITY = (
    "Ye research-process coverage hai; answer ki truth probability, trading "
    "profitability ya real-world hypothesis success probability nahi."
)


def _integer(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _ratio(achieved: int, target: int) -> float:
    if target <= 0:
        return 1.0
    return round(max(0.0, min(1.0, achieved / target)), 4)


def _component(key: str, label: str, weight: int, achieved: int, target: int,
               *, mandatory: bool = False, detail: str = "") -> Dict[str, Any]:
    ratio = _ratio(achieved, target)
    return {
        "key": key,
        "label": label,
        "weight": int(weight),
        "mandatory": bool(mandatory),
        "achieved": int(achieved),
        "target": int(target),
        "ratio": ratio,
        "passed": ratio >= 1.0,
        "detail": str(detail or "")[:240],
    }


def _hypothesis_component(discovery: Mapping[str, Any]) -> tuple[int, int]:
    entries = [row for row in (discovery.get("hypotheses") or [])
               if isinstance(row, Mapping)]
    if not entries:
        return 0, 0
    ready = 0
    for row in entries:
        falsification = row.get("falsification") or {}
        confidence = row.get("confidence") or {}
        experiment = row.get("experiment") or {}
        if (falsification.get("falsifiable") is True
                and confidence.get("real_world_success_probability") is None
                and experiment.get("auto_execution_allowed") is False):
            ready += 1
    return ready, len(entries)


def _saturation(round_metrics: Sequence[Mapping[str, Any]], rounds_run: int,
                rounds_target: int) -> Dict[str, Any]:
    if rounds_run < rounds_target:
        return {
            "status": "ROUNDS_INCOMPLETE",
            "reason": f"{rounds_run}/{rounds_target} configured rounds chale",
            "globally_exhaustive": False,
        }
    tail = list(round_metrics or [])[-2:]
    new_urls = sum(_integer(row.get("new_unique_urls")) for row in tail)
    if len(tail) >= 2 and new_urls == 0:
        status = "BOUNDED_SATURATION_SIGNAL"
        reason = "aakhri do rounds mein naya unique URL nahi mila"
    else:
        status = "BOUNDED_STOP_WITH_OPEN_LEADS"
        reason = (
            "configured rounds poore hue; aakhri rounds mein naye leads mile, "
            "isliye global literature exhaustion claim nahi kiya gaya"
        )
    return {"status": status, "reason": reason, "globally_exhaustive": False}


def build_research_assurance(*, config: object, pack: object,
                             discovered: Mapping[str, Any],
                             reading: Mapping[str, Any],
                             passes: Mapping[str, Any],
                             verification: Mapping[str, Any],
                             discovery_analysis: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a non-secret, deterministic MARATHON process audit."""
    mode = str(getattr(config, "name", "") or "").upper()
    target_percent = _integer(
        getattr(config, "research_process_target_percent", 0))
    if mode != "MARATHON" or target_percent <= 0:
        return {
            "active": False,
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "not_a_probability": NOT_A_PROBABILITY,
        }

    rounds_target = max(1, _integer(getattr(config, "max_rounds", 1)))
    rounds_run = _integer(discovered.get("rounds_run"))
    sources = list(getattr(pack, "sources", []) or [])
    independent = _integer(getattr(pack, "independent_source_count", 0))
    independent_target = min(8, max(3, _integer(
        getattr(config, "max_sources", 1)) // 5))
    full_text_target = min(8, max(3, _integer(
        getattr(config, "max_fulltext", 0)) // 2))
    full_text_read = _integer(reading.get("succeeded"))

    axis_rows = [row for row in (discovered.get("axis_coverage") or [])
                 if isinstance(row, Mapping) and row.get("mandatory") is not False]
    searched_axes = sum(str(row.get("status") or "") != "NOT SEARCHED"
                        for row in axis_rows)
    axes_target = len(axis_rows)
    counter_done = discovered.get("counter_search_performed") is True

    planned = [str(x) for x in (passes.get("planned_passes") or []) if str(x)]
    done = {str(x) for x in (passes.get("done_passes") or []) if str(x)}
    reasoning_done = sum(name in done for name in planned)

    claim_checks = verification.get("claim_checks") or {}
    critical_total = _integer(claim_checks.get("critical_claims"))
    critical_passed = _integer(
        claim_checks.get("critical_claims_same_source_ae_passed"))
    unsupported = sum(_integer(claim_checks.get(key)) for key in (
        "unsupported_critical_claims", "unverifiable_critical_claims",
        "critical_contradicted_claims",
    ))
    if unsupported:
        critical_passed = min(critical_passed,
                              max(0, critical_total - unsupported))

    hyp_ready, hyp_total = _hypothesis_component(discovery_analysis)
    components = [
        _component("all_search_rounds", "saare configured search rounds", 15,
                   rounds_run, rounds_target, mandatory=True),
        _component("mandatory_axes_searched", "mandatory evidence axes search", 20,
                   searched_axes, axes_target or 1, mandatory=True,
                   detail=("axis plan available" if axes_target
                           else "axis coverage record missing")),
        _component("independent_sources", "independent source diversity", 15,
                   independent, independent_target, mandatory=True),
        _component("legal_full_text", "legally accessible full-text reading", 15,
                   full_text_read, full_text_target, mandatory=True),
        _component("counter_search", "opposition/counter-evidence search", 10,
                   int(counter_done), 1, mandatory=True),
        _component("reasoning_passes", "planned reasoning/red-team passes", 10,
                   reasoning_done, len(planned) or 1, mandatory=True),
    ]
    if critical_total:
        components.append(_component(
            "critical_claim_verification", "critical claims same-source A-E", 10,
            critical_passed, critical_total, mandatory=True,
        ))
    if hyp_total:
        components.append(_component(
            "hypothesis_testability", "falsifiable, non-probability hypotheses", 5,
            hyp_ready, hyp_total, mandatory=True,
        ))

    weight = sum(row["weight"] for row in components)
    weighted = sum(row["weight"] * row["ratio"] for row in components)
    percent = round((100.0 * weighted / weight) if weight else 0.0, 1)
    mandatory_gaps = [row["key"] for row in components
                      if row["mandatory"] and not row["passed"]]
    target_met = percent >= target_percent and not mandatory_gaps
    gaps = [row["key"] for row in components if not row["passed"]]

    return {
        "active": True,
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "research_process_coverage_percent": percent,
        "target_percent": target_percent,
        "target_met": target_met,
        "status": ("PROCESS_TARGET_MET" if target_met else "PROCESS_GAPS_REMAIN"),
        "components": components,
        "gaps": gaps,
        "mandatory_gaps": mandatory_gaps,
        "saturation": _saturation(
            discovered.get("round_metrics") or [], rounds_run, rounds_target),
        "source_count": len(sources),
        "not_a_probability": NOT_A_PROBABILITY,
        "global_exhaustiveness_claimed": False,
        "hypothesis_success_probability_claimed": False,
    }
