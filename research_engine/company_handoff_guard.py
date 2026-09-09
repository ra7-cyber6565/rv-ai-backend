"""Honest fallback accounting for AI-Company specialist handoffs.

The Company handoff is injected into the normal reasoning context before both
``analysis`` and ``synthesis``.  The original completion bookkeeping credited
only a successful ``analysis`` pass.  Therefore a bounded run in which analysis
failed but synthesis succeeded could consume the full specialist handoff and
still be reported as 10/11 passes.

This guard does not add a model call, retry, threshold, result, or fake success.
It only credits an already-successful synthesis pass as the existing fallback
consumer of an intact handoff.  If neither analysis nor synthesis succeeds, or
if the handoff is missing/truncated, the original PARTIAL semantics remain.
"""
from __future__ import annotations

from functools import wraps


_MISSING_HANDOFF_NOTE = (
    "Complete specialist handoff was not confirmed; it was missing, clipped, "
    "or chief analysis did not finish."
)


def install() -> None:
    """Patch Company pass accounting once, without weakening failure gates."""
    from . import research_company as _company

    prior = _company.attach_company_passes
    if getattr(prior, "__company_handoff_fallback_guard__", False):
        return

    @wraps(prior)
    def guarded_attach_company_passes(out, company):
        prepared = (
            company.get("handoff_prepared") is True
            and not company.get("handoff_truncated_roles")
        )
        successful_before = set(out.get("done_passes") or [])

        result = prior(out, company)

        # Both analysis and synthesis receive the specialist handoff in the
        # orchestrator.  Analysis is already credited by the original helper;
        # synthesis is the bounded fallback if analysis produced no output.
        consumed = bool(successful_before & {"analysis", "synthesis"})
        done = out.setdefault("done_passes", [])
        if prepared and consumed and "specialist_handoff" not in done:
            done.append("specialist_handoff")
            notes = out.setdefault("notes", [])
            if _MISSING_HANDOFF_NOTE in notes:
                notes.remove(_MISSING_HANDOFF_NOTE)
            if "analysis" not in successful_before and "synthesis" in successful_before:
                notes.append(
                    "Specialist handoff was consumed by the successful synthesis "
                    "fallback after analysis produced no completed pass."
                )

        return result

    guarded_attach_company_passes.__company_handoff_fallback_guard__ = True
    _company.attach_company_passes = guarded_attach_company_passes


install()
