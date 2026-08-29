"""Production audit wiring for #103 Autonomous Literature Debate.

Only explicit structured contradictions are converted into opposing literature
positions.  The wrapper never infers opposition from prose, never upgrades the
answer/status/evidence level, and never labels consensus as truth.  It is an
audit packet under ``coverage.literature_debate``.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Mapping, Sequence
from urllib.parse import urlparse

from .literature_debate import LiteraturePosition, debate_literature, report_to_dict


_INSTALLED = False
_MAX_CONTRADICTIONS = 5_000


def _clean(value: object, limit: int = 20_000) -> str:
    return str(value or "").strip()[:limit]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_token(value: str, prefix: str) -> str:
    digest = _hash_text(value)
    return f"{prefix}:{digest[:24]}"


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().strip()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _independence_key(source: Mapping[str, Any]) -> str:
    patent = _clean(source.get("patent_family_key"), 240)
    if patent:
        return _safe_token(patent.lower(), "patent")
    doi = _clean(source.get("doi"), 240).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    if doi:
        return _safe_token(doi, "doi")
    domain = _clean(source.get("domain"), 240).lower() or _domain(_clean(source.get("url"), 2_000))
    if domain:
        return _safe_token(domain, "domain")
    title = " ".join(_clean(source.get("title"), 1_000).lower().split())
    if title:
        return _safe_token(title, "title")
    return _safe_token(_clean(source.get("source_id"), 240), "source")


def _content_hash(source: Mapping[str, Any], claim: str) -> str:
    # Exact/syndicated snippets should collapse.  Claim text is included only
    # when source text is unavailable so two opaque source IDs are not assumed
    # to have identical content.
    title = " ".join(_clean(source.get("title"), 2_000).lower().split())
    snippet = " ".join(_clean(source.get("snippet"), 8_000).lower().split())
    doi = _clean(source.get("doi"), 240).lower()
    basis = f"{doi}\n{title}\n{snippet}".strip()
    if not basis:
        basis = f"{_clean(source.get('source_id'), 240)}\n{claim}"
    return _hash_text(basis)


def _provenance_complete(source: Mapping[str, Any]) -> bool:
    source_id = _clean(source.get("source_id"), 240)
    title = _clean(source.get("title"), 2_000)
    stable_ref = _clean(source.get("doi"), 240) or _clean(source.get("url"), 2_000)
    return bool(source_id and title and stable_ref)


def _quality(source: Mapping[str, Any]) -> str:
    if source.get("retracted") is True:
        return "WEAK"
    try:
        relevance = float(source.get("relevance_score") or 0.0)
    except (TypeError, ValueError):
        relevance = 0.0
    level = _clean(source.get("reading_level") or source.get("read_level"), 80).lower()
    if relevance >= 0.25 and level in {"abstract", "full_text"}:
        return "USABLE"
    if relevance > 0 and level in {"snippet", "metadata"}:
        return "UNKNOWN"
    return "WEAK" if relevance < 0.25 else "UNKNOWN"


def _position(
    source: Mapping[str, Any],
    *,
    proposition_id: str,
    claim: str,
    position_id: str,
    evidence_ref: str,
) -> LiteraturePosition:
    parents_raw = source.get("parent_source_ids") or ()
    parents = tuple(
        _clean(item, 240)
        for item in parents_raw
        if _clean(item, 240)
    ) if isinstance(parents_raw, Sequence) and not isinstance(parents_raw, (str, bytes, bytearray)) else ()
    return LiteraturePosition(
        source_id=_clean(source.get("source_id"), 240),
        proposition_id=proposition_id,
        position_id=position_id,
        position_text=claim,
        independence_key=_independence_key(source),
        content_hash=_content_hash(source, claim),
        evidence_ref=evidence_ref,
        quality=_quality(source),
        retracted=bool(source.get("retracted") is True),
        provenance_complete=_provenance_complete(source),
        parent_source_ids=parents,
    )


def build_literature_debate_packet(result: Mapping[str, Any]) -> Dict[str, Any]:
    sources_raw = result.get("sources") or []
    contradictions = result.get("contradictions") or []
    if not isinstance(sources_raw, Sequence) or isinstance(sources_raw, (str, bytes, bytearray)):
        raise ValueError("sources must be a sequence")
    if not isinstance(contradictions, Sequence) or isinstance(contradictions, (str, bytes, bytearray)):
        raise ValueError("contradictions must be a sequence")
    if len(contradictions) > _MAX_CONTRADICTIONS:
        raise ValueError("contradictions exceed literature debate budget")

    sources = {
        _clean(item.get("source_id"), 240): item
        for item in sources_raw
        if isinstance(item, Mapping) and _clean(item.get("source_id"), 240)
    }
    positions = []
    accepted = 0
    skipped = 0
    seen_source_prop = set()

    for index, contradiction in enumerate(contradictions, 1):
        if not isinstance(contradiction, Mapping):
            skipped += 1
            continue
        if contradiction.get("valid") is not True:
            skipped += 1
            continue
        if contradiction.get("schema_complete") is not True:
            skipped += 1
            continue
        if contradiction.get("opposing_direction") is not True:
            skipped += 1
            continue
        source_ids = contradiction.get("source_ids") or []
        if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes, bytearray)) or len(source_ids) != 2:
            skipped += 1
            continue
        left_id, right_id = (_clean(source_ids[0], 240), _clean(source_ids[1], 240))
        left_source, right_source = sources.get(left_id), sources.get(right_id)
        left_claim = _clean(contradiction.get("source_a_claim"), 20_000)
        right_claim = _clean(contradiction.get("source_b_claim"), 20_000)
        proposition = _clean(contradiction.get("normalized_proposition"), 10_000)
        if not left_source or not right_source or not left_claim or not right_claim or not proposition:
            skipped += 1
            continue

        proposition_id = _safe_token(proposition.lower(), "prop")
        left_key = (left_id, proposition_id)
        right_key = (right_id, proposition_id)
        # Ambiguous duplicate rows for a source/proposition are not allowed to
        # inflate debate size.  The first complete structured record wins only
        # for counting; all raw contradictions remain elsewhere in the result.
        if left_key in seen_source_prop or right_key in seen_source_prop:
            skipped += 1
            continue
        seen_source_prop.update((left_key, right_key))
        left_position_id = _safe_token(left_claim.lower(), "position")
        right_position_id = _safe_token(right_claim.lower(), "position")
        if left_position_id == right_position_id:
            skipped += 1
            continue
        refs = contradiction.get("evidence_span_refs") or []
        left_ref = _clean(refs[0], 2_000) if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes, bytearray)) and len(refs) > 0 else f"{left_id}:structured-contradiction"
        right_ref = _clean(refs[1], 2_000) if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes, bytearray)) and len(refs) > 1 else f"{right_id}:structured-contradiction"
        positions.extend([
            _position(left_source, proposition_id=proposition_id, claim=left_claim, position_id=left_position_id, evidence_ref=left_ref),
            _position(right_source, proposition_id=proposition_id, claim=right_claim, position_id=right_position_id, evidence_ref=right_ref),
        ])
        accepted += 1

    if not positions:
        return {
            "ran": True,
            "status": "NO_EXPLICIT_OPPOSING_LITERATURE",
            "input_contradictions": len(contradictions),
            "accepted_contradictions": 0,
            "skipped_contradictions": skipped,
            "proposition_count": 0,
            "source_count": 0,
            "debates": [],
            "consensus_proves_truth": False,
            "truth_proven": False,
            "independent_validation_proven": False,
        }

    report = report_to_dict(debate_literature(positions))
    report.update({
        "ran": True,
        "status": "AUDITED",
        "input_contradictions": len(contradictions),
        "accepted_contradictions": accepted,
        "skipped_contradictions": skipped,
    })
    return report


def apply_literature_debate_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        packet = build_literature_debate_packet(data)
    except Exception as exc:
        packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "debates": [],
            "consensus_proves_truth": False,
            "truth_proven": False,
            "independent_validation_proven": False,
            "error": type(exc).__name__,
        }
    coverage["literature_debate"] = packet
    data["coverage"] = coverage
    return data


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_literature_debate(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_literature_debate_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_literature_debate
