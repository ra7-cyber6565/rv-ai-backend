"""Bounded deterministic task compilation; coverage is assessed separately."""
from __future__ import annotations
import re
from utils.research_runtime import digest
from .requested import parse_requests, creative_brief


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
    worker_request = re.search(r"\b([4-9])\s+(?:ai|agents?|workers?|specialists?)\b", question, re.I)
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


def assess_contract(contract, result):
    ledger = result.get("requested_ledger") or {}
    items = ledger.get("items", []) if isinstance(ledger, dict) else []
    by_key = {r.get("key"): r for r in items if isinstance(r, dict)}
    coverage = []
    for req in contract["requirements"]:
        item = by_key.get(req["id"])
        # No keyword overlap score may invent completion of arbitrary subparts.
        status = "NOT_ASSESSED"
        if item is not None:
            ok = item.get("ok")
            status = "SATISFIED" if ok is True else "MISSING" if ok is False else "NOT_ASSESSED"
        coverage.append({"requirement_id": req["id"], "assessment": status,
                         "output_reference": "requested_ledger" if item is not None else None})
    company = (result.get("verification") or {}).get("research_company") or {}
    required = contract["explicit_min_workers"]
    worker_gap = bool(required and company.get("completed_workers", 0) < required)
    return {**contract, "coverage": coverage, "worker_requirement_gap": worker_gap,
            "assessment": "PARTIAL" if worker_gap or contract["unparsed_numbered_parts"] else "REQUIRES_COVERAGE_REVIEW",
            "task_completion_is_claim_truth": False}
