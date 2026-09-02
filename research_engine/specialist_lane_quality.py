"""Qualification gate for specialist evidence lanes.

Why this exists
---------------
Source-family fairness guarantees that a requested lane gets a search chance,
and final-stress hardening classifies each retrieved source by its own content.
But the lane report historically counted *any* source assigned to a lane as
coverage. That leaves a semantic loophole: a low-relevance, metadata-only,
retracted, or proposition-mismatched record can make a required lane look
"covered" even though it is not usable evidence.

This layer is deliberately additive and fail-closed:

* candidate sources remain visible for audit/backward compatibility;
* only qualified sources satisfy a mandatory specialist lane;
* weak candidates are reported with machine-readable reasons instead of being
  silently treated as missing or as evidence;
* empirical/measured lanes require proposition-level support in addition to
  relevance because their role is to test a claim, not merely mention a topic;
* historical/traditional/official/allegation lanes are judged according to
  their source role, so a primary belief/claim source can document that a claim
  existed without being promoted to scientific truth;
* no source, claim, confidence, novelty, or access depth is ever upgraded.

Zero model calls, zero network calls, zero paid services.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Mapping

MIN_RELEVANCE = 0.25
MIN_SCHOLARLY_QUALITY = 0.30

_EMPIRICAL_LANES = {"empirical_science", "measured_frequency_evidence"}
_SCHOLARLY_LANES = {"scholarly_interpretation"}
_PRIMARY_TEXT_LANES = {"primary_historical_text", "traditional_belief_text"}
_CONTEXT_LANES = {"official_document_record", "allegation_or_conspiracy_claim"}


def _reading_level(source: Any) -> str:
    fn = getattr(source, "reading_level", None)
    if callable(fn):
        try:
            return str(fn() or "").strip().lower()
        except Exception:
            pass
    return str(getattr(source, "read_level", "") or "").strip().lower()


def _float_attr(source: Any, name: str) -> float | None:
    if not hasattr(source, name):
        return None
    try:
        return float(getattr(source, name))
    except (TypeError, ValueError):
        return None


def _proposition_state(source: Any) -> bool | None:
    parts = getattr(source, "relevance_parts", None)
    if not isinstance(parts, Mapping):
        return None
    value = parts.get("tests_proposition")
    return value if value in (True, False) else None


def _source_id(source: Any) -> str:
    return str(getattr(source, "source_id", "") or "").strip()


def _qualify(source: Any, lane: str) -> Dict[str, Any]:
    """Return a fail-closed qualification receipt for one lane candidate."""
    reasons: list[str] = []
    sid = _source_id(source)
    relevance = _float_attr(source, "relevance_score")
    quality = _float_attr(source, "quality_score")
    read_level = _reading_level(source)
    proposition = _proposition_state(source)

    rejected_reason = str(getattr(source, "rejected_reason", "") or "").strip()
    if rejected_reason:
        reasons.append("RELEVANCE_GATE_REJECTED")
    if getattr(source, "retracted", None) is True:
        reasons.append("RETRACTED_SOURCE")

    if relevance is None:
        reasons.append("RELEVANCE_NOT_MEASURED")
    elif relevance < MIN_RELEVANCE:
        reasons.append("RELEVANCE_BELOW_LANE_FLOOR")

    if lane in _PRIMARY_TEXT_LANES:
        if read_level not in {"claims", "full_text"}:
            reasons.append("PRIMARY_TEXT_NOT_ACCESSED")
    elif lane in _EMPIRICAL_LANES | _SCHOLARLY_LANES:
        if read_level not in {"abstract", "claims", "full_text"}:
            reasons.append("INSUFFICIENT_READING_DEPTH")
    elif lane in _CONTEXT_LANES:
        if read_level not in {"snippet", "abstract", "claims", "full_text"}:
            reasons.append("CONTENT_NOT_ACCESSED")

    if lane in _EMPIRICAL_LANES and proposition is not True:
        reasons.append(
            "PROPOSITION_NOT_CONFIRMED" if proposition is None
            else "PROPOSITION_MISMATCH"
        )

    if lane in _EMPIRICAL_LANES | _SCHOLARLY_LANES:
        if quality is None:
            reasons.append("SOURCE_QUALITY_NOT_MEASURED")
        elif quality < MIN_SCHOLARLY_QUALITY:
            reasons.append("SOURCE_QUALITY_BELOW_FLOOR")

    unique_reasons = list(dict.fromkeys(reasons))[:8]
    return {
        "source_id": sid,
        "lane": lane,
        "qualified": not unique_reasons,
        "reasons": unique_reasons,
        "relevance_score": relevance,
        "quality_score": quality,
        "reading_level": read_level or "not_recorded",
        "tests_proposition": proposition,
    }


def _required_lanes(plan: Mapping[str, Any] | None, report: Mapping[str, Any]) -> list[str]:
    specialist = (plan or {}).get("specialist") if isinstance(plan, Mapping) else None
    if isinstance(specialist, Mapping):
        values = specialist.get("expected_lanes") or []
    else:
        values = report.get("required_lanes") or []
    out: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def qualify_lane_report(report: Dict[str, Any], plan: Mapping[str, Any] | None, pack: Any) -> Dict[str, Any]:
    """Add qualified/weak accounting and recompute mandatory lane coverage."""
    if not isinstance(report, dict) or not report.get("active"):
        return report

    out = copy.deepcopy(report)
    by_id = {
        _source_id(source): source
        for source in list(getattr(pack, "sources", None) or [])
        if _source_id(source)
    }
    qualified_by_lane: Dict[str, list[str]] = {}
    weak_by_lane: Dict[str, list[str]] = {}

    for row in out.get("lanes") or []:
        if not isinstance(row, dict):
            continue
        lane = str(row.get("key") or "").strip()
        candidate_ids = [str(x) for x in (row.get("source_ids") or []) if str(x).strip()]
        receipts: list[Dict[str, Any]] = []
        qualified: list[str] = []
        weak: list[str] = []
        for sid in candidate_ids:
            source = by_id.get(sid)
            if source is None:
                receipt = {
                    "source_id": sid,
                    "lane": lane,
                    "qualified": False,
                    "reasons": ["SOURCE_RECORD_UNAVAILABLE"],
                    "relevance_score": None,
                    "quality_score": None,
                    "reading_level": "not_recorded",
                    "tests_proposition": None,
                }
            else:
                receipt = _qualify(source, lane)
            receipts.append(receipt)
            (qualified if receipt["qualified"] else weak).append(sid)

        row["candidate_source_ids"] = candidate_ids
        row["candidate_source_count"] = len(candidate_ids)
        row["qualified_source_ids"] = qualified
        row["qualified_source_count"] = len(qualified)
        row["weak_source_ids"] = weak
        row["weak_source_count"] = len(weak)
        row["qualification_status"] = (
            "QUALIFIED" if qualified else ("WEAK" if candidate_ids else "MISSING")
        )
        row["qualification_receipts"] = receipts[:100]
        qualified_by_lane[lane] = qualified
        weak_by_lane[lane] = weak

    required = _required_lanes(plan, out)
    covered = [lane for lane in required if qualified_by_lane.get(lane)]
    weak_required = [
        lane for lane in required
        if not qualified_by_lane.get(lane) and weak_by_lane.get(lane)
    ]
    missing = [lane for lane in required if not qualified_by_lane.get(lane)]

    out["required_lanes"] = required
    out["covered_required_lanes"] = covered
    out["weak_required_lanes"] = weak_required
    out["missing_required_lanes"] = missing
    out["required_lane_coverage_complete"] = bool(required) and not missing
    out["lane_qualification"] = {
        "version": 1,
        "minimum_relevance": MIN_RELEVANCE,
        "minimum_scholarly_quality": MIN_SCHOLARLY_QUALITY,
        "candidate_sources_are_not_automatically_evidence": True,
        "metadata_only_counts_as_content_coverage": False,
        "empirical_requires_proposition_support": True,
        "qualified_required_lanes": len(covered),
        "weak_required_lanes": len(weak_required),
        "missing_required_lanes": len(missing),
    }
    return out


def _render_qualified_report(report: Dict[str, Any]) -> str:
    from . import specialist_domains as sd

    original = getattr(sd, "_SPECIALIST_LANE_QUALITY_ORIGINAL_RENDER", None)
    if not callable(original):
        return ""
    text = original(report)
    if not isinstance(report, Mapping) or not report.get("active"):
        return text
    notes: list[str] = []
    for row in report.get("lanes") or []:
        if not isinstance(row, Mapping):
            continue
        candidates = int(row.get("candidate_source_count") or 0)
        qualified = int(row.get("qualified_source_count") or 0)
        weak = int(row.get("weak_source_count") or 0)
        if candidates and (weak or qualified != candidates):
            notes.append(
                f"- **{row.get('label', 'Evidence lane')} qualification:** "
                f"{qualified}/{candidates} candidate source strict lane-quality gate pass; "
                f"{weak} weak/unqualified. Weak candidate required lane ko COMPLETE nahi karta."
            )
    if notes:
        return text + "\n\n### Specialist lane quality gate\n" + "\n".join(notes)
    return text


def install() -> None:
    """Install after final-stress/source-family hardening; idempotent."""
    from . import specialist_domains as sd

    if getattr(sd, "_SPECIALIST_LANE_QUALITY_INSTALLED", False):
        return

    original_build = sd.build_evidence_lane_report
    original_render = sd.render_evidence_lane_report
    sd._SPECIALIST_LANE_QUALITY_ORIGINAL_RENDER = original_render

    def build_evidence_lane_report(question: str, plan: Dict, pack) -> Dict:
        report = dict(original_build(question, plan, pack) or {})
        return qualify_lane_report(report, plan, pack)

    sd.build_evidence_lane_report = build_evidence_lane_report
    sd.render_evidence_lane_report = _render_qualified_report
    sd._SPECIALIST_LANE_QUALITY_INSTALLED = True


__all__ = [
    "MIN_RELEVANCE",
    "MIN_SCHOLARLY_QUALITY",
    "install",
    "qualify_lane_report",
    "_qualify",
]
