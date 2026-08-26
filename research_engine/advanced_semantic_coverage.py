"""Compatibility-safe semantic coverage enforcement for deep multi-facet answers.

PR #51 intentionally made long-answer coverage stricter, but it replaced the
older ``structured_answer.coverage`` contract.  That contract is deliberately a
surface/delivery audit: callers use ``items_covered`` to count user labels, not
to grade the scientific substance.  Replacing it caused fully surfaced answers
to report 0/N covered and downgraded bare ``ResearchResult`` fixtures.

This module keeps the two questions separate:

* surface coverage: did the answer expose every requested high-level item?
* semantic coverage: did each exposed item contain substantive explanation plus
  an evidence/uncertainty signal?

The public legacy surface audit is restored unchanged.  The stricter semantic
audit is preserved as a second machine-readable field and is enforced by the
production final-quality gate only when the production evidence-first contract
is active.  Nothing here can upgrade evidence, confidence or release status.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Dict, List, Mapping, Optional

_INSTALLED = False
_SEMANTIC_COVERAGE: Optional[Callable[[str, str], Dict]] = None


def _surface_coverage(structured_mod, question: str, answer: str) -> Dict:
    """Reproduce the stable outline-delivery API without semantic grading."""
    outline = structured_mod.extract_outline(question)
    body = unicodedata.normalize("NFKC", str(answer or "")).casefold()
    covered: List[str] = []
    missing: List[str] = []
    for item in outline:
        label = structured_mod._clean_title(item.get("label")).casefold()
        title = structured_mod._clean_title(item.get("title")).casefold()
        exact = bool(label and label in body) or bool(title and title in body)
        words = structured_mod._content_words(str(item.get("title") or ""))
        fallback = len(words) >= 2 and all(
            re.search(
                r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])",
                body,
            )
            for word in words[:6]
        )
        target = str(item.get("label") or item.get("title") or "")
        (covered if (exact or fallback) else missing).append(target)
    required = structured_mod.requires_structured_coverage(question)
    return {
        "required": required,
        "items_total": len(outline),
        "items_covered": len(covered),
        "complete": (not required) or not missing,
        "covered": covered,
        "missing": missing,
        "note": "outline delivery audit only; not evidence/truth verification",
    }


def substantive_coverage(question: str, answer: str) -> Dict:
    """Return the stricter semantic audit retained from advanced hardening."""
    if _SEMANTIC_COVERAGE is None:
        # Importing the package normally installs this module after
        # advanced_research_quality.  Fail closed if somebody calls the helper
        # in an unusual partial-import environment.
        return {
            "required": False,
            "items_total": 0,
            "items_covered": 0,
            "complete": False,
            "covered": [],
            "missing": ["semantic structured coverage audit unavailable"],
            "substantive_missing": ["semantic structured coverage audit unavailable"],
            "section_checks": [],
            "note": "semantic delivery audit unavailable",
        }
    audit = dict(_SEMANTIC_COVERAGE(question, answer))
    total = audit.get("items_total")
    covered = audit.get("items_covered")
    if isinstance(total, int) and total > 0 and isinstance(covered, int):
        audit["semantic_coverage_percent"] = round(100.0 * covered / total, 1)
    elif not audit.get("required"):
        audit["semantic_coverage_percent"] = 100.0
    else:
        audit["semantic_coverage_percent"] = None
    audit["coverage_kind"] = "substantive_semantic_delivery"
    return audit


def _semantic_issue_details(audit: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "coverage_kind": "substantive_semantic_delivery",
        "items_total": audit.get("items_total"),
        "items_covered": audit.get("items_covered"),
        "semantic_coverage_percent": audit.get("semantic_coverage_percent"),
        "missing": list(audit.get("substantive_missing") or audit.get("missing") or []),
        "section_checks": list(audit.get("section_checks") or []),
    }


def install() -> None:
    """Install after ``advanced_research_quality`` exactly once."""
    global _INSTALLED, _SEMANTIC_COVERAGE
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import advanced_research_quality as advanced
    from . import final_quality_gate as final_mod
    from . import result_coverage_gate as result_mod
    from . import structured_answer as structured_mod

    # advanced_research_quality has already installed a semantic wrapper over
    # the old surface coverage. Preserve that wrapper before restoring the
    # stable public surface API.
    _SEMANTIC_COVERAGE = structured_mod.coverage

    def surface_coverage(question: str, answer: str) -> Dict:
        return _surface_coverage(structured_mod, question, answer)

    structured_mod.coverage = surface_coverage
    result_mod.structured_coverage = surface_coverage
    # Explicit discoverable hook for diagnostics/tests/UI without changing the
    # stable ``coverage`` contract.
    structured_mod.substantive_coverage = substantive_coverage

    # Enrich every serialized result with BOTH dimensions.  The original
    # result_coverage_gate still owns surface-status downgrades; this wrapper
    # only adds diagnostic semantic metadata.
    original_enforce = result_mod.enforce

    def enriched_enforce(result: Dict) -> Dict:
        data = original_enforce(result)
        question = str(data.get("question") or "")
        answer = str(data.get("answer") or "")
        try:
            semantic = substantive_coverage(question, answer)
        except Exception as exc:
            semantic = {
                "required": bool(structured_mod.requires_structured_coverage(question)),
                "items_total": None,
                "items_covered": None,
                "complete": False,
                "covered": [],
                "missing": ["semantic structured coverage audit unavailable"],
                "substantive_missing": ["semantic structured coverage audit unavailable"],
                "section_checks": [],
                "semantic_coverage_percent": None,
                "coverage_kind": "substantive_semantic_delivery",
                "note": "semantic audit failed closed: " + type(exc).__name__,
            }
        coverage = dict(data.get("coverage") or {})
        coverage["structured_answer_semantic"] = semantic
        data["coverage"] = coverage
        return data

    result_mod.enforce = enriched_enforce

    # Bare/legacy ResearchResult serialization remains a surface-delivery gate.
    # Real production research opts into evidence_first_required; there the
    # final quality gate additionally requires substantive structured delivery.
    original_check = final_mod.FinalQualityGate._check_requirements

    def semantic_requirements(state, data, answer, ledger, spec) -> None:
        original_check(state, data, answer, ledger, spec)
        question = str(data.get("question") or "")
        if not bool(getattr(spec, "evidence_first_required", False)):
            return
        if not advanced._multi_facet(question):
            return

        audit = substantive_coverage(question, answer)
        required = bool(audit.get("required"))
        passed = (not required) or audit.get("complete") is True
        state.check("structured_sections_substantive", passed)
        if passed:
            return

        details = _semantic_issue_details(audit)
        # Reuse the established missing-deliverable blocker so answer_complete
        # and public PARTIAL semantics remain monotonic without weakening the
        # existing final-quality evaluator.
        state.issue(
            "REQUESTED_DELIVERABLE_MISSING",
            "requirement_coverage",
            "critical",
            "Requested structured sections were surfaced but one or more are not substantively delivered.",
            deduction=final_mod.CATEGORY_WEIGHTS["requirement_coverage"],
            hard_cap=40 if str(data.get("status") or "").upper() == "COMPLETE" else 60,
            details={"semantic_structured_coverage": details},
        )

    final_mod.FinalQualityGate._check_requirements = staticmethod(semantic_requirements)
