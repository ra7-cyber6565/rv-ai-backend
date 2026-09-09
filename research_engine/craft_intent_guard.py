"""Guard ambiguous ``script`` requests from entering the creative CRAFT lane.

``craft.detect`` intentionally recognises screenplay/dialogue ``script`` requests,
but the bare word ``script`` is also common in technical requests such as
``Python backtest script`` or ``Pine Script``.  Treating those as dialogue adds a
fake creative deliverable to research coverage and can turn an otherwise
technical Max request PARTIAL for the wrong reason.

This guard is deliberately narrow:
- only an already-detected ``dialogue`` request whose matched form cue is the
  ambiguous bare ``script``/``skrpt`` is reconsidered;
- strong technical/programming context demotes it from CRAFT;
- explicit creative/scriptwriting context always wins, so real dialogue,
  screenplay, scene, character, drama and skit requests keep working.

The guard is deterministic, local, provider-free and does not manufacture a
replacement deliverable.
"""
from __future__ import annotations

import re
from functools import wraps
from typing import Any, Dict

from . import craft as _craft


_TECHNICAL_SCRIPT_RE = re.compile(
    r"(?:"
    r"\bpython\b|\bpine\s*script\b|\bpinescript\b|\bjavascript\b|"
    r"\btypescript\b|\bnode(?:\.js|js)?\b|\bcode\b|\bcoding\b|"
    r"\bback[- ]?test(?:ing)?\b|\bwalk[- ]?forward\b|"
    r"\bevent[- ]?driven\b|\btradingview\b|\bmt\s*5\b|\bmetatrader\b|"
    r"\bhmmlearn\b|\bsimulat(?:e|ed|es|ing|ion|ions)\b|"
    r"\balgorithm(?:ic)?\b|\bfunction\b|\bapi\b|\bnotebook\b|"
    r"\b(?:bash|shell|powershell|sql)\b|\bexecutable\b|"
    r"\b(?:compile|compiler|runtime|library|package)\b"
    r")",
    re.IGNORECASE,
)

_EXPLICIT_CREATIVE_RE = re.compile(
    r"(?:"
    r"\bdialog(?:ue)?\b|\bsamvaad\b|\bsnvaad\b|\bsambad\b|"
    r"\bscreenplay\b|\bscriptwriting\b|\bscript\s*writing\b|"
    r"\bscene\b|\bcharacter(?:s)?\b|\bstory\b|\bfilm\b|\bmovie\b|"
    r"\bdrama\b|\bnatak\b|\bnaatak\b|\bskit\b|\bmonologue\b|"
    r"\bconversation\b|\bbaat(?:cheet|cit)\b"
    r")",
    re.IGNORECASE,
)


def _technical_script_without_creative_context(question: str) -> bool:
    text = str(question or "")
    return bool(_TECHNICAL_SCRIPT_RE.search(text)) and not bool(
        _EXPLICIT_CREATIVE_RE.search(text)
    )


def install() -> None:
    """Install the narrow technical-script boundary once."""
    prior = _craft.detect
    if getattr(prior, "__technical_script_intent_guard__", False):
        return

    @wraps(prior)
    def guarded_detect(question: str) -> Dict[str, Any]:
        result = prior(question)
        if not isinstance(result, dict) or not result.get("is_request"):
            return result

        form = str(result.get("form") or "").strip().lower()
        cue = str(result.get("form_cue") or "").strip().lower()
        if (
            form == "dialogue"
            and cue in {"script", "skrpt"}
            and _technical_script_without_creative_context(question)
        ):
            guarded = dict(result)
            guarded.update(
                {
                    "is_request": False,
                    "form": "",
                    "label": "",
                    "reason": "technical_script_not_creative",
                }
            )
            return guarded
        return result

    guarded_detect.__technical_script_intent_guard__ = True
    _craft.detect = guarded_detect


install()

# ``research_engine.__init__`` imports this deterministic guard on every runtime
# path. Install companion no-network acceptance boundaries here. They only
# normalize/credit behavior already present in the request/runtime and never
# manufacture an unstated threshold, result, or successful model call.
from .trading_hypothesis_structure_guard import install as _install_trading_hypothesis_structure_guard
_install_trading_hypothesis_structure_guard()

from .company_handoff_guard import install as _install_company_handoff_guard
_install_company_handoff_guard()

from .trading_acceptance_guard import install as _install_trading_acceptance_guard
_install_trading_acceptance_guard()

from .trading_threshold_token_guard import install as _install_trading_threshold_token_guard
_install_trading_threshold_token_guard()
