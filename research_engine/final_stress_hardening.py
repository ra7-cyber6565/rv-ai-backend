"""Final stress-test hardening for multi-domain research quality.

This module is deliberately additive and fail-closed.  It does not upgrade
source quality, truth, confidence, or novelty.  It closes three gaps exposed by
the long human-agency stress test:

* source-family classification must depend on the source itself, not merely on
  another active profile in a giant multi-domain question;
* explicit specialist evidence families (official/declassified, historical,
  traditional, scholarly, allegation, measured-frequency, empirical) must be
  machine-auditable and missing required families must block COMPLETE under the
  evidence-first contract;
* an explicitly requested mathematical/optimization/simulation model needs a
  sensitivity/scenario check in addition to the existing formula/input/unit/
  assumptions/result/uncertainty/recalculation gates.

All logic is deterministic and model/network free.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, Mapping, Sequence


_EMPIRICAL_RE = re.compile(
    r"\b(?:randomi[sz]ed|controlled\s+trial|participants?|subjects?|sample\s+(?:of|size)|"
    r"methods?|experiment(?:al)?|measured?|measurement|dataset|observed?|results?|"
    r"regression|statistical(?:ly)?|p\s*[<=>]|confidence\s+interval|effect\s+size|"
    r"longitudinal|cohort|surveyed?|neuroimaging|eeg|fmri|cortisol|assay)\b",
    re.IGNORECASE,
)
_TRADITION_RE = re.compile(
    r"\b(?:hermetic|hermeticism|occult|esoteric|alchemy|alchemical|mystic|mysticism|"
    r"spiritual|metaphysic|ritual|gnostic|theosoph|divine\s+spark|nevill(?:e)?\s+goddard|"
    r"manifestation|freemason|masonic|grimoire)\b",
    re.IGNORECASE,
)
_ALLEGATION_RE = re.compile(
    r"\b(?:conspirac|alleg(?:e|ed|ation)|cover[- ]?up|secret\s+plot|hidden\s+agenda|"
    r"new\s+world\s+order|deep\s+state|claimed?\s+that|accus(?:e|ed|ation))\b",
    re.IGNORECASE,
)
_SENSITIVITY_RE = re.compile(
    r"\b(?:sensitivity\s+analysis|scenario\s+analysis|parameter\s+sweep|"
    r"monte\s+carlo|robustness\s+(?:check|analysis|to)|stress\s+test(?:ing)?|"
    r"vary(?:ing|ied)?\s+(?:the\s+)?(?:parameter|assumption|rate|input)|"
    r"range\s+of\s+assumptions|best[- ]case|worst[- ]case|one[- ]at[- ]a[- ]time|"
    r"what[- ]if\s+analysis)\b",
    re.IGNORECASE,
)
_MATH_MODEL_RE = re.compile(
    r"(?:^[^\n]{0,180}[A-Za-z][^\n]{0,80}[=≈∝][^\n]{0,160}$)|"
    r"\b(?:objective\s+function|decision\s+variable|subject\s+to|constraint|"
    r"minimi[sz]e|maximi[sz]e|simulation|expected\s+value)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _source_text(source: Any) -> str:
    parts = [
        str(getattr(source, "title", "") or ""),
        str(getattr(source, "snippet", "") or ""),
        str(getattr(source, "venue", "") or ""),
        str(getattr(source, "publisher", "") or ""),
    ]
    full = str(getattr(source, "full_text", "") or "")
    if full:
        parts.append(full[:5000])
    return "\n".join(parts)


def _source_type(source: Any) -> str:
    raw = getattr(source, "source_type", "")
    return str(getattr(raw, "value", raw) or "").lower().strip()


def _advanced_source_lane(source: Any, active_profile_keys: Sequence[str]) -> str:
    """Classify by this source's evidence role, not another active question lane.

    The previous implementation made every paper empirical when a giant prompt
    merely contained the mind/cognition profile. That is a question-level
    leakage bug: a historical/Jung review paper is not made empirical by the
    existence of a neuroscience facet elsewhere in the same question.

    Returned lane keys must come from ``specialist_domains.LANES``. In
    particular, allegation material uses the canonical
    ``allegation_or_conspiracy_claim`` key; otherwise a real conspiracy/secret-
    society source could be retrieved yet still appear as a missing required
    lane in the final audit.
    """
    from . import specialist_domains as sd

    if sd._is_official(source):
        return "official_document_record"

    kind = _source_type(source)
    text = _source_text(source)
    keys = set(active_profile_keys or [])

    if kind == "dataset":
        return "empirical_science"
    if kind == "paper":
        if "frequency_claims" in keys and sd._measured_frequency_intent(text):
            return "measured_frequency_evidence"
        if _EMPIRICAL_RE.search(text):
            return "empirical_science"
        return "scholarly_interpretation"
    if kind == "book":
        if keys & {"esotericism_occult_history", "philosophy_metaphysics"} and _TRADITION_RE.search(text):
            return "traditional_belief_text"
        return "primary_historical_text"
    if kind == "document":
        return "primary_historical_text"
    if keys & {"conspiracy_claims", "secret_societies_history"} and _ALLEGATION_RE.search(text):
        return "allegation_or_conspiracy_claim"
    return "secondary_context"


def _unique(values: Sequence[Any]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def _enrich_lane_report(report: Dict[str, Any], specialist: Mapping[str, Any]) -> Dict[str, Any]:
    if not report.get("active"):
        return report
    required = _unique(specialist.get("expected_lanes") or [])
    counts: Dict[str, int] = {}
    for row in report.get("lanes") or []:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("key") or "").strip()
        try:
            count = int(row.get("source_count") or 0)
        except (TypeError, ValueError):
            count = 0
        if key:
            counts[key] = count
    covered = [lane for lane in required if counts.get(lane, 0) > 0]
    missing = [lane for lane in required if counts.get(lane, 0) <= 0]
    report["required_lanes"] = required
    report["covered_required_lanes"] = covered
    report["missing_required_lanes"] = missing
    report["required_lane_coverage_complete"] = not missing
    return report


def _append_unmet(data: Dict[str, Any], *, key: str, what: str, got: str, why: str) -> None:
    ledger = copy.deepcopy(_mapping(data.get("requested_ledger")))
    unmet = list(ledger.get("unmet") or [])
    if any(isinstance(item, Mapping) and str(item.get("key") or "") == key for item in unmet):
        data["requested_ledger"] = ledger
        return
    unmet.append({
        "key": key,
        "what": what,
        "got": got,
        "why": why,
        "ok": False,
        "mandatory": True,
    })
    ledger["unmet"] = unmet
    data["requested_ledger"] = ledger


def _augment_for_final_gate(result: Any, contract: Any = None) -> Any:
    data = _mapping(result)
    if not data:
        return result
    data = copy.deepcopy(data)
    raw_contract = _mapping(contract) or _mapping(data.get("quality_contract"))
    evidence_first = bool(raw_contract.get("evidence_first_required"))

    specialist = _mapping(data.get("specialist_research"))
    if evidence_first and specialist.get("active"):
        missing = _unique(specialist.get("missing_required_lanes") or [])
        if missing:
            _append_unmet(
                data,
                key="specialist_source_family_coverage",
                what="Required specialist evidence/source-family lanes",
                got="missing: " + ", ".join(missing),
                why=(
                    "Question ne specialist evidence families maangi thi, lekin in lanes mein "
                    "koi qualifying source final evidence pack tak nahi pahuncha. Source count "
                    "doosri lane ki kami ko cover nahi karta."
                ),
            )

    if raw_contract.get("math_model_required"):
        answer = str(data.get("answer") or "")
        # Existing gates already reject missing/incomplete calculations. This
        # extra requirement applies only once a model-like answer exists, so a
        # missing model is not double-counted under two different errors.
        if _MATH_MODEL_RE.search(answer) and not _SENSITIVITY_RE.search(answer):
            _append_unmet(
                data,
                key="model_sensitivity_analysis",
                what="Mathematical/optimization model sensitivity or scenario analysis",
                got="nahi mila",
                why=(
                    "Explicit model/simulation maanga gaya tha; ek single assumed parameter set "
                    "ko robust result nahi maana ja sakta. Kam se kam parameter/scenario variation "
                    "aur conclusion par uska effect dikhna chahiye."
                ),
            )
    return data


def install() -> None:
    """Install idempotent wrappers before lazy orchestrator imports."""
    from . import specialist_domains as sd
    from . import final_quality_gate as fq

    if not getattr(sd, "_FINAL_STRESS_HARDENING_INSTALLED", False):
        original_build = sd.build_evidence_lane_report
        sd.source_lane = _advanced_source_lane

        def build_evidence_lane_report(question: str, plan: Dict, pack) -> Dict:
            report = dict(original_build(question, plan, pack) or {})
            specialist = (plan or {}).get("specialist") if isinstance(plan, dict) else None
            if not isinstance(specialist, Mapping):
                specialist = sd.build_specialist_plan(question, question)
            return _enrich_lane_report(report, specialist)

        sd.build_evidence_lane_report = build_evidence_lane_report
        sd._FINAL_STRESS_HARDENING_INSTALLED = True

    if not getattr(fq.FinalQualityGate, "_FINAL_STRESS_HARDENING_INSTALLED", False):
        original_evaluate = fq.FinalQualityGate.evaluate

        def evaluate(self, result: Any, contract=None):
            augmented = _augment_for_final_gate(result, contract)
            return original_evaluate(self, augmented, contract)

        fq.FinalQualityGate.evaluate = evaluate
        fq.FinalQualityGate._FINAL_STRESS_HARDENING_INSTALLED = True


__all__ = [
    "install",
    "_advanced_source_lane",
    "_augment_for_final_gate",
    "_enrich_lane_report",
]
