"""Final fail-closed coverage gate for long structured user questions.

`structured_answer.py` gives the synthesis model an explicit outline contract,
but prompt instructions alone are not enforcement.  This module installs a
small wrapper around ``ResearchResult.to_dict`` so the *final assembled answer*
is audited immediately before it leaves the engine.

Boundary: this gate checks delivery/coverage only.  It never upgrades evidence,
truth, confidence, citations or hypothesis quality.  A missing requested section
can only make the answer status worse (COMPLETE -> PARTIAL), never better.

The installed ``to_dict`` boundary also appends the deterministic AI-2
validation packet after all registered result enforcers have run.  That packet is
plan/audit data only: without execution observations it remains TEST PROPOSED /
INCONCLUSIVE and cannot upgrade the research result.
"""
from __future__ import annotations

from typing import Dict, List

from .structured_answer import coverage as structured_coverage
from .structured_answer import requires_structured_coverage

_COMPLETE = "COMPLETE"
_PARTIAL = "PARTIAL"
_INCOMPLETE = "RESEARCH INCOMPLETE"
_MARKER = "STRUCTURED COVERAGE GAP"


def _dedupe(values) -> List[str]:
    out: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _coverage_failure(question: str, reason: str) -> Dict:
    return {
        "required": True,
        "items_total": None,
        "items_covered": None,
        "complete": False,
        "covered": [],
        "missing": ["structured coverage audit unavailable"],
        "note": (
            "outline delivery audit failed closed; not evidence/truth verification; "
            + str(reason or "unknown audit error")[:160]
        ),
    }


def enforce(result: Dict) -> Dict:
    """Downgrade false COMPLETE status when explicit outline items are missing."""
    data = dict(result or {})
    question = str(data.get("question") or "")
    answer = str(data.get("answer") or "")

    # Normal/short questions pay no semantic price.  We still expose an audit
    # object when parsing succeeds so UI/debug tools can see that the gate was
    # considered but not required.
    try:
        audit = structured_coverage(question, answer)
    except Exception as exc:  # fail closed only when this question needs the gate
        if not requires_structured_coverage(question):
            return data
        audit = _coverage_failure(question, type(exc).__name__)

    coverage = dict(data.get("coverage") or {})
    coverage["structured_answer"] = audit
    data["coverage"] = coverage

    if not audit.get("required") or audit.get("complete") is True:
        return data

    missing = _dedupe(audit.get("missing") or [])
    if not missing:
        missing = ["structured coverage audit incomplete"]

    # Monotonic safety rule: this gate can only downgrade COMPLETE.  A run that
    # is already RESEARCH INCOMPLETE remains so; PARTIAL remains PARTIAL.
    current = str(data.get("status") or _COMPLETE)
    if current == _COMPLETE:
        data["status"] = _PARTIAL

    existing_missing = _dedupe(data.get("missing_sections") or [])
    data["missing_sections"] = _dedupe(existing_missing + missing)

    count_total = audit.get("items_total")
    count_covered = audit.get("items_covered")
    if count_total is not None and count_covered is not None:
        reason = (
            f"Long structured question ke {count_covered}/{count_total} high-level "
            f"parts answer mein mile; {len(missing)} part missing hai."
        )
    else:
        reason = "Long structured question ka mandatory coverage audit poora nahi hua."

    old_reason = str(data.get("status_reason") or "").strip()
    if current == _COMPLETE or not old_reason:
        data["status_reason"] = reason
    elif reason not in old_reason:
        data["status_reason"] = old_reason + " | " + reason

    warning = (
        f"{_MARKER}: answer ke mandatory high-level parts missing hain: "
        + ", ".join(missing[:6])
        + (" ..." if len(missing) > 6 else "")
        + ". Isliye ise COMPLETE nahi maana gaya."
    )
    warnings = _dedupe(data.get("warnings") or [])
    if warning not in warnings:
        warnings.append(warning)
    data["warnings"] = warnings

    # §20 has an independent answer-state.  Do not leave it saying COMPLETE
    # while the public result status is PARTIAL.  Evidence/novelty/job states are
    # deliberately untouched.
    state = dict(data.get("research_state") or {})
    if str(state.get("answer_state") or "") == _COMPLETE:
        state["answer_state"] = _PARTIAL
    if state:
        notes = _dedupe(state.get("conflicts") or [])
        state_note = (
            "Structured delivery contract incomplete: "
            + ", ".join(missing[:6])
            + (" ..." if len(missing) > 6 else "")
        )
        if state_note not in notes:
            notes.append(state_note)
        state["conflicts"] = notes
        data["research_state"] = state

    # Machine status is primary, but the human answer must not visually look
    # complete when the machine says PARTIAL.  Add one bounded banner only.
    if _MARKER not in answer:
        banner = (
            "> ⚠️ **PARTIAL — STRUCTURED COVERAGE GAP:** "
            f"{len(missing)} requested high-level part(s) answer mein missing hain. "
            "Neeche ka research useful ho sakta hai, par isse poora answer mat maano."
        )
        data["answer"] = banner + "\n\n" + answer

    return data


def install() -> None:
    """Install exactly once; no network/model calls and no import-time audit."""
    from . import models

    cls = models.ResearchResult
    if getattr(cls, "_structured_coverage_gate_installed", False):
        return

    original = cls.to_dict

    def guarded_to_dict(self):
        # ``enforce`` is intentionally looked up dynamically: later wiring
        # modules wrap result_coverage_gate.enforce and remain in the chain.
        data = enforce(original(self))
        try:
            from .validation_director_wiring import apply_runtime_ai2_validation
            data = apply_runtime_ai2_validation(data)
        except Exception as exc:
            # The validation audit must fail closed but must not destroy an
            # otherwise useful research result.
            coverage = dict(data.get("coverage") or {})
            coverage["ai2_validation"] = {
                "agent_id": "AI-2 / VALIDATION-DIRECTOR",
                "status": "ASSESSMENT_ERROR",
                "results": [],
                "confidence": 0,
                "runtime_wiring": {
                    "ran": False,
                    "real_world_experiment_executed": False,
                    "truth_proven": False,
                    "result_status_upgraded": False,
                    "error": type(exc).__name__,
                },
            }
            data["coverage"] = coverage
        return data

    cls.to_dict = guarded_to_dict
    cls._structured_coverage_gate_installed = True
