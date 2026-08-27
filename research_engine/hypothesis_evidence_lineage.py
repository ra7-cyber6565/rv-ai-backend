"""Deterministic evidence-lineage gate for app-original hypotheses.

The hypothesis prompt already asks the model to cite evidence and mark unsupported
steps as ``[INFERENCE]``/``[NO-SOURCE]``.  Prompt wording alone is not a gate:
a fluent mechanism can still invent an intermediate biological/physical step and
inherit a respectable confidence band merely because some other part of the
hypothesis cited sources.

This module audits every non-trivial mechanism/reasoning step after parsing:

* a step is evidence-backed only when a same linked/cited source passes the
  existing relevance + available-text support checks for that step;
* an unsupported step is acceptable as *disclosed uncertainty* only when the
  text explicitly says ``[INFERENCE]`` or ``[NO-SOURCE]``;
* a citation that does not support the step is worse than an honest inference;
* undisclosed unsupported steps fail closed and cap confidence at VERY LOW;
* disclosed inference can never keep MODERATE confidence by itself.

The audit is provenance/honesty only.  It never upgrades evidence, novelty,
validation or confidence and performs no model/network call.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence

_INSTALLED = False
_SID_RE = re.compile(r"\[?\b(S\d{1,3})\b[^\]]*\]?", re.IGNORECASE)
_DISCLOSED_INFERENCE_RE = re.compile(r"\[\s*INFERENCE\s*\]", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-]?SOURCE\s*\]", re.IGNORECASE)
_LABEL_RE = re.compile(
    r"\[\s*(?:INFERENCE|NO[\s\-]?SOURCE|EVIDENCE|SOURCE[\s\-]?REPORTED|"
    r"UNVERIFIED|SPECULATION|HYPOTHESIS)\s*\]",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"(?:\r?\n+|(?<=[.!?;])\s+|\s*(?:→|->)\s*)")

STATUS_SUPPORTED = "SUPPORTED_BY_LINKED_SOURCE"
STATUS_INFERENCE = "INFERENCE_DISCLOSED"
STATUS_NO_SOURCE = "NO_SOURCE_DISCLOSED"
STATUS_BAD_CITATION = "CITED_BUT_NOT_SUPPORTED"
STATUS_UNSOURCED = "UNSOURCED_UNLABELLED"
STATUS_VERIFY_UNAVAILABLE = "SUPPORT_VERIFICATION_UNAVAILABLE"


def _unique(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        clean = str(value or "").upper()
        if clean and clean not in out:
            out.append(clean)
    return out


def _steps(text: str) -> List[str]:
    """Return non-trivial prose steps without inventing missing structure."""
    out: List[str] = []
    for raw in _SPLIT_RE.split(str(text or "")):
        step = raw.strip(" -*#\t")
        if len(step) < 18:
            continue
        if step not in out:
            out.append(step[:1200])
    return out


def _claim_text(step: str) -> str:
    text = _LABEL_RE.sub(" ", step)
    text = _SID_RE.sub(" ", text)
    return " ".join(text.split()).strip(" .;:-")


def _supporting_ids(step: str, fallback: Sequence[str], valid: set[str]) -> List[str]:
    explicit = _unique(_SID_RE.findall(step))
    candidates = explicit or _unique(fallback)
    return [sid for sid in candidates if sid in valid]


def _same_source_support(claim: str, source_ids: Sequence[str], pack) -> tuple[List[str], bool]:
    """Use the shipped claim verifier; require B relevance + C support together."""
    if not claim or not source_ids:
        return [], True
    try:
        from .evidence_verification import EvidenceVerifier
        cited = "".join(f"[{sid}]" for sid in source_ids)
        report = EvidenceVerifier().verify(f"[EVIDENCE] {claim} {cited}", pack)
    except Exception:
        return [], False
    if not report.items:
        return [], False
    backed: List[str] = []
    for row in report.items[0].source_checks or []:
        if row.get("relevance") is True and row.get("support") is True:
            sid = str(row.get("source_id") or "").upper()
            if sid and sid not in backed:
                backed.append(sid)
    return backed, True


def audit_hypothesis_lineage(hypothesis, pack) -> Dict:
    """Build a machine-readable evidence map for mechanism + reasoning steps."""
    fields = (("mechanism", getattr(hypothesis, "mechanism", "")),
              ("reasoning", getattr(hypothesis, "reasoning", "")))
    sources = list(getattr(pack, "sources", []) or []) if pack is not None else []
    valid = {str(getattr(s, "source_id", "") or "").upper() for s in sources}
    fallback = _unique(getattr(hypothesis, "facts_used", []) or [])
    rows: List[Dict] = []

    for field, text in fields:
        for step in _steps(text):
            disclosed_inference = bool(_DISCLOSED_INFERENCE_RE.search(step))
            disclosed_no_source = bool(_NO_SOURCE_RE.search(step))
            explicit_ids = _unique(_SID_RE.findall(step))
            candidate_ids = _supporting_ids(step, fallback, valid)
            claim = _claim_text(step)
            backed, verifier_ok = _same_source_support(claim, candidate_ids, pack)

            if backed:
                status = STATUS_SUPPORTED
            elif not verifier_ok and candidate_ids:
                status = STATUS_VERIFY_UNAVAILABLE
            elif disclosed_no_source:
                status = STATUS_NO_SOURCE
            elif disclosed_inference:
                status = STATUS_INFERENCE
            elif explicit_ids:
                status = STATUS_BAD_CITATION
            else:
                status = STATUS_UNSOURCED

            rows.append({
                "field": field,
                "step": claim[:500],
                "status": status,
                "explicit_citations": explicit_ids,
                "candidate_source_ids": candidate_ids,
                "supporting_source_ids": backed,
            })

    counts = {name: 0 for name in (
        STATUS_SUPPORTED, STATUS_INFERENCE, STATUS_NO_SOURCE,
        STATUS_BAD_CITATION, STATUS_UNSOURCED, STATUS_VERIFY_UNAVAILABLE,
    )}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    bad = (counts[STATUS_BAD_CITATION] + counts[STATUS_UNSOURCED]
           + counts[STATUS_VERIFY_UNAVAILABLE])
    disclosed = counts[STATUS_INFERENCE] + counts[STATUS_NO_SOURCE]
    return {
        "schema_version": "1.0",
        "applicable": bool(rows),
        "steps_checked": len(rows),
        "supported_steps": counts[STATUS_SUPPORTED],
        "disclosed_uncertainty_steps": disclosed,
        "undisclosed_or_failed_steps": bad,
        "honesty_complete": bad == 0,
        "evidence_complete": bool(rows) and counts[STATUS_SUPPORTED] == len(rows),
        "counts": counts,
        "steps": rows,
        "note": (
            "Mechanism/reasoning ka har step ya same-source relevance+support se "
            "backed hona chahiye, ya [INFERENCE]/[NO-SOURCE] se uncertainty saaf "
            "batani chahiye. Ye audit hypothesis ko fact/validated nahi banata."
        ),
    }


def _cap_confidence(hypothesis, lineage: Dict) -> None:
    record = getattr(hypothesis, "confidence_record", None)
    if record is None or not lineage.get("applicable"):
        return
    bad = int(lineage.get("undisclosed_or_failed_steps") or 0)
    disclosed = int(lineage.get("disclosed_uncertainty_steps") or 0)
    codes = record.reason_codes
    if bad:
        code = "MECHANISM_LINEAGE_FAILED"
        if code not in codes:
            codes.append(code)
        record.band = "VERY LOW"
        record.why = (record.why.rstrip(" .") + "; mechanism/reasoning me "
                      f"{bad} step cited support ke bina ya unsupported citation "
                      "ke saath mila — confidence VERY LOW par cap hua.")
    elif disclosed and str(record.band).upper() == "MODERATE":
        code = "MECHANISM_INFERENCE_DISCLOSED"
        if code not in codes:
            codes.append(code)
        record.band = "LOW"
        record.why = (record.why.rstrip(" .") + "; unsupported mechanism step "
                      "imaandaari se inference/no-source label hua, isliye MODERATE "
                      "confidence allowed nahi — LOW par cap hua.")


def install() -> None:
    """Install after the existing hypothesis confidence hardening, once."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .hypothesis import Hypothesis, HypothesisEngine

    original_enrich = HypothesisEngine.enrich
    original_honesty = HypothesisEngine.honesty_check
    original_to_dict = Hypothesis.to_dict

    def enriched(self, hypotheses, *args, **kwargs):
        rows = original_enrich(self, hypotheses, *args, **kwargs)
        pack = kwargs.get("pack")
        # positional signature: enrich(hypotheses, question="", pack=None, ...)
        if pack is None and len(args) >= 2:
            pack = args[1]
        for hypothesis in rows:
            lineage = audit_hypothesis_lineage(hypothesis, pack)
            setattr(hypothesis, "mechanism_evidence_lineage", lineage)
            _cap_confidence(hypothesis, lineage)
        return rows

    def honesty(self, hypotheses):
        warnings = list(original_honesty(self, hypotheses))
        for index, hypothesis in enumerate(hypotheses, 1):
            lineage = getattr(hypothesis, "mechanism_evidence_lineage", None) or {}
            bad = int(lineage.get("undisclosed_or_failed_steps") or 0)
            if bad:
                warnings.append(
                    f"Hypothesis {index} ka evidence-lineage fail hua — mechanism/"
                    f"reasoning ke {bad} step same-source support se backed nahi the "
                    "aur [INFERENCE]/[NO-SOURCE] se disclose bhi nahi hue."
                )
        return warnings

    def to_dict(self):
        data = original_to_dict(self)
        lineage = getattr(self, "mechanism_evidence_lineage", None)
        if lineage is not None:
            data["mechanism_evidence_lineage"] = lineage
        return data

    HypothesisEngine.enrich = enriched
    HypothesisEngine.honesty_check = honesty
    Hypothesis.to_dict = to_dict
