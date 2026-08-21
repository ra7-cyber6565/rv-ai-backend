"""Claim-level evidence verification A-E for Infinity Research AI.

A valid citation ID is not enough to call a claim verified. This module checks
five separate things without spending any model/API quota:

A. citation integrity — cited IDs exist for the claim;
B. relevance — at least one cited source is relevant to the question;
C. available-text support — the claim is supported by the title/abstract/
   snippet/full-text excerpt the engine actually has in hand;
D. access depth — strong fact language needs full-text-level reading;
E. source quality — at least one supporting source is usable quality and is not
   retracted/withdrawn.

Important limitation: this is a conservative deterministic gate, not a neural
NLI model. Similar wording can establish that a source is plausibly supportive,
but borderline cases stay ``unknown`` instead of being silently promoted to
verified. Numeric and obvious direction/negation mismatches fail explicitly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import ClaimType, EvidencePack, SourceRecord, SourceType, label_to_claim_type
from .semantic import similarity

_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE|SOURCE[\s\-]?REPORTED|"
    r"MIXED\s+EVIDENCE|WEAK\s+EVIDENCE|EVIDENCE|INFERENCE|HYPOTHESIS|"
    r"SPECULATION|UNVERIFIED|UNKNOWN)\s*\]",
    re.IGNORECASE,
)
_BRACKET_RE = re.compile(r"\[([^\[\]]{1,80})\]")
_SID_TOKEN_RE = re.compile(r"\bS\s?(\d{1,3})\b", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-_]?SOURCE\s*\]", re.IGNORECASE)
_STRONG_LABELS = {"ESTABLISHED", "ESTABLISHED FACT", "FACT", "STRONG EVIDENCE"}
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(-?\d+(?:\.\d+)?)\s*(%|percent|percentage|gpa|k|kelvin|°c|c)?",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(no|not|never|without|doesn['’]?t|didn['’]?t|nahi|nahin|mat)\b", re.I)
_UP_RE = re.compile(r"\b(increase[sd]?|increasing|higher|rise[sn]?|rising|grow(?:s|th)?|badh(?:ta|ti|te|na|a)?|zyada)\b", re.I)
_DOWN_RE = re.compile(r"\b(decrease[sd]?|decreasing|lower|reduce[sd]?|reduction|fall(?:s|ing)?|decline[sd]?|kam|ghat(?:ta|ti|te|na|a)?)\b", re.I)


def _ids(text: str) -> List[str]:
    found: List[str] = []
    for bracket in _BRACKET_RE.findall(text or ""):
        for number in _SID_TOKEN_RE.findall(bracket):
            sid = f"S{int(number)}"
            if sid not in found:
                found.append(sid)
    return found


def _clean_claim(line: str) -> str:
    text = _LABEL_RE.sub("", line or "")
    text = _BRACKET_RE.sub("", text)
    text = re.sub(r"^[#\s\-\*\d\.]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _unit(unit: str) -> str:
    low = (unit or "").lower()
    if low in {"%", "percent", "percentage"}:
        return "%"
    if low in {"k", "kelvin"}:
        return "k"
    if low in {"c", "°c"}:
        return "c"
    return low


def _numbers(text: str) -> List[str]:
    out: List[str] = []
    for value, unit in _NUMBER_RE.findall(text or ""):
        try:
            num = float(value)
        except ValueError:
            continue
        normalized = f"{num:g}{_unit(unit)}"
        if normalized not in out:
            out.append(normalized)
    return out


def _numbers_supported(claim: str, source_text: str) -> Optional[bool]:
    claim_nums = _numbers(claim)
    if not claim_nums:
        return None
    source_nums = set(_numbers(source_text))
    # Numeric drift is one of the highest-risk hallucinations. If an answer says
    # 100% while its cited excerpt says 30%, semantic similarity cannot rescue it.
    return all(number in source_nums for number in claim_nums)


def _direction(text: str) -> str:
    up = bool(_UP_RE.search(text or ""))
    down = bool(_DOWN_RE.search(text or ""))
    if up and not down:
        return "up"
    if down and not up:
        return "down"
    return ""


def _obvious_semantic_conflict(claim: str, source_text: str) -> bool:
    claim_direction = _direction(claim)
    source_direction = _direction(source_text)
    if claim_direction and source_direction and claim_direction != source_direction:
        return True
    # Only use negation as a hard conflict when the texts otherwise overlap well;
    # long academic excerpts often contain unrelated negated sentences.
    if bool(_NEGATION_RE.search(claim)) != bool(_NEGATION_RE.search(source_text)):
        if similarity(claim, source_text) >= 0.30:
            return True
    return False


def _source_text(pack: EvidencePack, source: SourceRecord) -> str:
    # Include structured metadata too. This avoids falsely failing a correctly
    # cited publication year merely because the year was stored in metadata and
    # not repeated inside the excerpt.
    pieces = [
        source.title or "",
        source.snippet or "",
        str(source.year or ""),
        source.publisher or "",
        source.venue or "",
        source.locator or "",
        source.read_note or "",
    ]
    for passage in pack.passages:
        if passage.source_id == source.source_id and passage.text:
            pieces.append(passage.text)
    return "\n".join(piece for piece in pieces if piece)


def _quality_state(source: SourceRecord) -> Optional[bool]:
    if source.retracted is True:
        return False
    score = float(source.quality_score or 0.0)
    if score >= 0.45:
        return True
    if score >= 0.30:
        return None
    return False


def _depth_state(label: str, source: SourceRecord) -> Optional[bool]:
    level = source.reading_level()
    strong = label.upper().strip() in _STRONG_LABELS
    if strong:
        # A selected-page large PDF can still support a specific claim if the
        # cited relevant page/excerpt was actually processed. The separate
        # read_note/pages fields disclose that the entire document was not read.
        return level == "full_text"
    if level in {"full_text", "abstract"}:
        return True
    if level == "snippet":
        return None
    return False


def _relevance_state(pack: EvidencePack, source: SourceRecord, source_text: str) -> Optional[bool]:
    if source.source_type == SourceType.DOCUMENT:
        return True
    score = float(source.relevance_score or 0.0)
    if score >= 0.22:
        return True
    if score > 0:
        return None
    if pack.question:
        semantic_q = similarity(pack.question, source_text)
        if semantic_q >= 0.22:
            return True
        if semantic_q >= 0.12:
            return None
    return False


def _support_state(claim: str, source_text: str) -> tuple[Optional[bool], float, Optional[bool]]:
    score = similarity(claim, source_text)
    numeric = _numbers_supported(claim, source_text)
    if numeric is False or _obvious_semantic_conflict(claim, source_text):
        return False, score, numeric
    if score >= 0.24:
        return True, score, numeric
    if score >= 0.12:
        return None, score, numeric
    return False, score, numeric


@dataclass
class ClaimEvidenceResult:
    claim: str
    label: str
    source_ids: List[str] = field(default_factory=list)
    citation: Optional[bool] = None
    relevance: Optional[bool] = None
    support: Optional[bool] = None
    depth: Optional[bool] = None
    quality: Optional[bool] = None
    verdict: str = "unknown"
    source_checks: List[Dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "claim": self.claim,
            "label": self.label,
            "source_ids": self.source_ids,
            "citation": self.citation,
            "relevance": self.relevance,
            "support": self.support,
            "depth": self.depth,
            "quality": self.quality,
            "verdict": self.verdict,
            "source_checks": self.source_checks,
            "note": self.note,
        }


@dataclass
class EvidenceVerificationReport:
    claims_checked: int = 0
    passed_claims: int = 0
    uncertain_claims: int = 0
    failed_claims: int = 0
    gate_passed: bool = False
    checks: Dict[str, Optional[bool]] = field(default_factory=dict)
    items: List[ClaimEvidenceResult] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "claims_checked": self.claims_checked,
            "passed_claims": self.passed_claims,
            "uncertain_claims": self.uncertain_claims,
            "failed_claims": self.failed_claims,
            "gate_passed": self.gate_passed,
            "checks": self.checks,
            "items": [item.to_dict() for item in self.items],
            "note": self.note,
        }


class EvidenceVerifier:
    """Deterministic, zero-cost A-E verification for labelled factual claims."""

    def verify(self, answer: str, pack: EvidencePack) -> EvidenceVerificationReport:
        result = EvidenceVerificationReport()
        valid = set(pack.valid_ids)

        for raw in (answer or "").splitlines():
            labels = _LABEL_RE.findall(raw)
            if not labels:
                continue
            label = re.sub(r"[\s\-]+", " ", labels[0]).strip().upper()
            claim_type = label_to_claim_type(labels[0])
            if claim_type not in {ClaimType.FACT, ClaimType.EVIDENCE}:
                continue
            claim = _clean_claim(raw)
            if len(claim) < 12:
                continue

            cited = _ids(raw)
            valid_ids = [sid for sid in cited if sid in valid]
            citation_ok = (
                bool(valid_ids)
                and len(valid_ids) == len(cited)
                and not _NO_SOURCE_RE.search(raw)
            )
            item = ClaimEvidenceResult(
                claim=claim[:500], label=label, source_ids=cited, citation=citation_ok,
            )

            source_rows: List[Dict] = []
            for sid in valid_ids:
                source = pack.by_id(sid)
                if source is None:
                    continue
                text = _source_text(pack, source)
                relevance = _relevance_state(pack, source, text)
                support, support_score, numeric = _support_state(claim, text)
                depth = _depth_state(label, source)
                quality = _quality_state(source)
                source_rows.append({
                    "source_id": sid,
                    "relevance": relevance,
                    "support": support,
                    "support_score": round(support_score, 4),
                    "numeric_match": numeric,
                    "depth": depth,
                    "read_level": source.reading_level(),
                    "read_note": source.read_note,
                    "quality": quality,
                    "quality_score": round(float(source.quality_score or 0.0), 4),
                    "retracted": source.retracted is True,
                })
            item.source_checks = source_rows

            def any_true(key: str) -> Optional[bool]:
                values = [row.get(key) for row in source_rows]
                if any(value is True for value in values):
                    return True
                if any(value is None for value in values):
                    return None
                return False

            item.relevance = any_true("relevance") if citation_ok else False
            item.support = any_true("support") if citation_ok else False
            item.depth = any_true("depth") if citation_ok else False
            item.quality = any_true("quality") if citation_ok else False

            states = [item.citation, item.relevance, item.support, item.depth, item.quality]
            if all(value is True for value in states):
                item.verdict = "verified_against_available_evidence"
                result.passed_claims += 1
            elif any(value is False for value in states):
                item.verdict = "failed_evidence_gate"
                result.failed_claims += 1
            else:
                item.verdict = "uncertain_needs_deeper_check"
                result.uncertain_claims += 1

            named = (
                ("citation", item.citation),
                ("relevance", item.relevance),
                ("support", item.support),
                ("depth", item.depth),
                ("quality", item.quality),
            )
            failed_names = [name for name, value in named if value is False]
            unknown_names = [name for name, value in named if value is None]
            if failed_names:
                item.note = "Fail: " + ", ".join(failed_names)
            elif unknown_names:
                item.note = "Abhi pakka verify nahi hua: " + ", ".join(unknown_names)
            else:
                item.note = "Citation, relevance, available-text support, depth aur quality sab pass."
            result.items.append(item)

        result.claims_checked = len(result.items)

        def aggregate(attr: str) -> Optional[bool]:
            if not result.items:
                return None
            values = [getattr(item, attr) for item in result.items]
            if any(value is False for value in values):
                return False
            if any(value is None for value in values):
                return None
            return True

        result.checks = {
            "A_citation": aggregate("citation"),
            "B_relevance": aggregate("relevance"),
            "C_support": aggregate("support"),
            "D_depth": aggregate("depth"),
            "E_quality": aggregate("quality"),
        }
        result.gate_passed = bool(result.items) and all(
            value is True for value in result.checks.values()
        )

        if not result.items:
            result.note = (
                "Koi labelled factual/evidence claim nahi mila, isliye claim-level A-E verification apply nahi hui."
            )
        elif result.gate_passed:
            result.note = (
                f"{result.claims_checked}/{result.claims_checked} labelled factual/evidence claims ne A-E gate pass kiya."
            )
        else:
            result.note = (
                f"{result.claims_checked} claims check hui: {result.passed_claims} pass, "
                f"{result.uncertain_claims} uncertain, {result.failed_claims} fail. "
                "Valid citation ko akela verification nahi maana gaya."
            )
        return result
