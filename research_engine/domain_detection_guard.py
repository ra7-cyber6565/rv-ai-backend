"""Domain-detection ambiguity guard.

Claude's domain profiles correctly reject off-topic sources once the question is
known to be about superconductivity.  But the raw detector can over-classify a
question from one ambiguous trigger such as ``TC`` or ``critical temperature``.
That is dangerous because a wrong *strict* domain then hard-rejects otherwise
correct sources and routes connectors incorrectly.

This facade keeps the raw detector for normal cases and only demotes a
superconductivity result when exactly one weak/ambiguous trigger caused it and
no superconductivity-specific signal was present. Two weak signals together
still count as meaningful context (for example hydride + critical temperature).

The patch is installed at package import so existing callers of
``research_engine.domain.detect`` and helpers such as ``anchor_terms`` all share
the same guarded decision without duplicating routing logic.
"""
from __future__ import annotations

from typing import List

from . import domain as _domain

_RAW_DETECT = _domain.detect

# Single occurrences of these are not enough to declare the whole question a
# superconductivity question. They occur in unrelated phase transitions,
# materials chemistry and everyday abbreviations too.
_WEAK_SC_TRIGGERS = {
    "tc",
    "critical temperature",
    "hydride",
    "nickelate",
}


def _matched_triggers(question: str, profile) -> List[str]:
    bag = _domain.stems(question or "")
    return [
        trigger
        for trigger in profile.triggers
        if _domain.phrase_hit(trigger, bag)
    ]


def _plan_for_profile(question: str, profile, *, rivals=()):
    bag = _domain.stems(question or "")
    focus = [branch.key for branch in profile.branches if branch.hits(bag)]
    return _domain.DomainPlan(
        question=question,
        profile=profile,
        confidence=profile.trigger_hits(bag),
        rivals=tuple(rivals),
        focus_keys=tuple(focus),
    )


def guarded_detect(question: str):
    """Return raw domain plan except for a proven single-trigger SC ambiguity."""
    plan = _RAW_DETECT(question)
    if plan.key != "superconductivity":
        return plan

    matched = _matched_triggers(question, plan.profile)
    if len(matched) >= 2:
        return plan
    if any(trigger not in _WEAK_SC_TRIGGERS for trigger in matched):
        return plan

    # One weak trigger only: prefer the strongest rival domain if there is one;
    # otherwise stay generic instead of activating a wrong strict hard filter.
    if plan.rivals:
        rival = plan.rivals[0]
        remaining = [plan.profile] + list(plan.rivals[1:])
        return _plan_for_profile(question, rival, rivals=remaining[:3])
    return _domain.DomainPlan(
        question=question,
        profile=_domain.GENERIC,
        confidence=0,
        rivals=(plan.profile,),
        focus_keys=(),
    )


def install() -> None:
    if getattr(_domain, "_ambiguity_guard_installed", False):
        return
    _domain.detect = guarded_detect
    # anchor_terms is cached and calls the module-global ``detect`` name. Clear
    # any entries produced before installation (normally none, but fail-safe).
    try:
        _domain.anchor_terms.cache_clear()
    except Exception:
        pass
    _domain._ambiguity_guard_installed = True


install()
