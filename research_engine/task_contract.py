"""Bounded deterministic task compilation; coverage is assessed separately.

The task contract is a delivery/accounting boundary, not a truth scorer.  It may
only call a user requirement satisfied when an existing measured ledger says so.
In particular, explicit numbered/bullet parts are never completed by keyword
presence in the answer.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

from utils.research_runtime import digest
from .requested import parse_requests, creative_brief


# Parser signal -> measured quality-ledger key.  These are deliberately the
# exact deterministic request signals already produced by requested.py.  Do not
# add loose answer-text keyword matching here: that would turn wording into a
# fake completion proof.
_SEMANTIC_PART_KEYS: Tuple[Tuple[str, str], ...] = (
    ("wants_hypotheses", "hypotheses"),
    ("wants_math_model", "math_model"),
    ("wants_second_order", "second_order"),
    ("wants_red_team", "red_team"),
    ("wants_units", "units"),
    ("wants_comparison", "comparison"),
    ("wants_experiment_design", "experiment_design"),
    ("wants_falsification", "falsification"),
    ("wants_confidence", "confidence"),
    ("wants_readiness", "readiness"),
    ("wants_source_depth", "source_depth"),
)


def compile_contract(question, mode, custom=None):
    requests = parse_requests(question)
    creative = bool(creative_brief(question))
    science = bool(requests.get("wants_hypotheses") or requests.get("wants_experiment_design"))
    coding = bool(re.search(r"\b(code|software|python|javascript|app|build|program)\b", question, re.I))
    numbered = [m.group(1).strip() for m in re.finditer(r"(?m)^\s*(?:\d+[.)]|[-*])\s+(.+)$", question)]
    requirements = [{"id": "objective", "text": question, "kind": "original_request", "mandatory": True}]
    requirements.extend({"id": "part_" + str(i+1), "text": text, "kind": "explicit_part", "mandatory": True}
                        for i, text in enumerate(numbered[:64]))
    for key, wanted in requests.items():
        if key.startswith("wants_") and wanted is True:
            requirements.append({"id": key[6:], "text": key[6:].replace("_", " "),
                                 "kind": "recognized_deliverable", "mandatory": True})
    stages = [{"id": "plan", "depends_on": []},
              {"id": "discover", "depends_on": ["plan"]},
              {"id": "read", "depends_on": ["discover"]},
              {"id": "reason", "depends_on": ["read"]},
              {"id": "validate", "depends_on": ["reason"]},
              {"id": "deliver", "depends_on": ["validate"]}]
    worker_request = re.search(r"\b([1-9][0-9]{0,3})\s+(?:ai|agents?|workers?|specialists?)\b", question, re.I)
    return {"schema_version": 1, "contract_sha256": digest([question, mode, custom]),
            "objective": question, "requirements": requirements, "dependency_graph": stages,
            "parser": "deterministic heuristic; original request retained verbatim",
            "unparsed_numbered_parts": max(0, len(numbered)-64),
            "language": "Hindi/Hinglish" if re.search(r"[ऀ-ॿ]|\b(bhai|banao|karo|bnao|mujhe)\b", question, re.I) else "user request language",
            "task_types": (["creative"] if creative else ["research", "explanation"]) + (["coding"] if coding else []) + (["experiment_design"] if science else []),
            "mode": mode, "custom_budget": custom or {},
            "explicit_min_workers": int(worker_request.group(1)) if worker_request else None,
            "freshness": "CURRENT_REQUIRED" if re.search(r"latest|current|today|abhi|aaj|आज", question, re.I) else "NOT_SPECIFIED",
            "physical_experiment": {"state": "NOT_APPLICABLE" if creative and not science else "NOT_EXECUTED",
                "reason": "creative brief" if creative and not science else "requires actual external execution evidence"},
            "missing_information": [], "success_criteria": "Every explicit deliverable satisfied with appropriate evidence/execution receipts"}


def _ledger_items(result: Dict) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """Return measured ledger rows keyed by id plus their source ledger.

    ``requested_ledger`` is the historical human-facing ledger and many of its
    rows intentionally have no machine key. ``contract_ledger`` is the newer
    measured quality ledger and is authoritative when both expose the same key.
    Reading only the former made every ``part_N`` look unassessed even when the
    corresponding semantic deliverable had actually been measured.
    """
    by_key: Dict[str, Dict] = {}
    sources: Dict[str, str] = {}
    # Legacy keyed rows are a compatibility fallback.  Contract rows are read
    # second and therefore override them for the same key.
    for ledger_name in ("requested_ledger", "contract_ledger"):
        ledger = result.get(ledger_name) or {}
        items = ledger.get("items", []) if isinstance(ledger, dict) else []
        for row in items:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if not key:
                continue
            by_key[key] = row
            sources[key] = ledger_name
    return by_key, sources


def _row_status(row: Dict | None) -> str:
    if not isinstance(row, dict):
        return "NOT_ASSESSED"
    ok = row.get("ok")
    if ok is True:
        return "SATISFIED"
    if ok is False:
        return "MISSING"
    return "NOT_ASSESSED"


def _semantic_keys_for_part(text: str) -> List[str]:
    """Map one explicit part to request-ledger concepts without guessing.

    The part's own text is parsed with the exact same conservative parser used
    to build the quality contract.  A part that cannot be mapped stays
    NOT_ASSESSED; it is never promoted from surface wording alone.
    """
    try:
        parsed = parse_requests(str(text or "")) or {}
    except Exception:
        return []
    keys: List[str] = []
    for signal, ledger_key in _SEMANTIC_PART_KEYS:
        if parsed.get(signal) is True and ledger_key not in keys:
            keys.append(ledger_key)
    return keys


def _combine_statuses(statuses: Iterable[str]) -> str:
    values = list(statuses)
    if not values:
        return "NOT_ASSESSED"
    # One proven miss makes a multi-demand bullet incomplete.  A bullet is only
    # SATISFIED when every semantic demand we identified has a measured pass.
    if "MISSING" in values:
        return "MISSING"
    if all(value == "SATISFIED" for value in values):
        return "SATISFIED"
    return "NOT_ASSESSED"


def assess_contract(contract, result):
    by_key, ledger_sources = _ledger_items(result)
    coverage = []

    for req in contract["requirements"]:
        req_id = str(req.get("id") or "")
        direct = by_key.get(req_id)
        status = _row_status(direct)
        evidence_keys: List[str] = [req_id] if direct is not None else []

        # ``part_1`` / ``part_2`` are positional ids, while the quality ledger
        # is semantic (hypotheses, math_model, falsification, ...).  Bridge them
        # using only the deterministic request parser and the already-measured
        # ledger rows.  No answer-text overlap is accepted as completion proof.
        if req.get("kind") == "explicit_part" and direct is None:
            semantic_keys = _semantic_keys_for_part(str(req.get("text") or ""))
            if semantic_keys:
                evidence_keys = semantic_keys
                status = _combine_statuses(
                    _row_status(by_key.get(key)) for key in semantic_keys
                )

        refs = []
        for key in evidence_keys:
            source = ledger_sources.get(key)
            if source:
                refs.append(f"{source}:{key}")
        coverage.append({
            "requirement_id": req_id,
            "assessment": status,
            "output_reference": ",".join(refs) if refs else None,
            "measured_keys": list(evidence_keys),
        })

    company = (result.get("verification") or {}).get("research_company") or {}
    required = contract["explicit_min_workers"]
    worker_gap = bool(required and company.get("completed_workers", 0) < required)
    explicit_ids = {r["id"] for r in contract["requirements"] if r["kind"] == "explicit_part"}
    unresolved_parts = [r["requirement_id"] for r in coverage
                        if r["requirement_id"] in explicit_ids and r["assessment"] != "SATISFIED"]
    missing = [r["requirement_id"] for r in coverage if r["assessment"] == "MISSING"]
    return {**contract, "coverage": coverage, "worker_requirement_gap": worker_gap,
            "unresolved_explicit_parts": unresolved_parts, "known_missing_deliverables": missing,
            "assessment": "PARTIAL" if worker_gap or unresolved_parts or missing or contract["unparsed_numbered_parts"] else "REQUIRES_COVERAGE_REVIEW",
            "task_completion_is_claim_truth": False,
            "coverage_evidence_policy": "measured ledger evidence only; no answer-text keyword completion"}
