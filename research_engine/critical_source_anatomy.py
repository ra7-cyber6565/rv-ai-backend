"""Deterministic anatomy extraction for critical full-text sources.

A document being downloaded is not proof that AI-1 inspected the parts needed to
judge it. This module records whether the processed text actually exposes:
methods, sample/data, assumptions, findings, limitations and
replication/falsification/robustness material.

No model is called and nothing is inferred from silence. A missing heading/cue is
reported as UNKNOWN/MISSING, never as a negative result (for example, absence of
a "Limitations" heading does not prove the study has no limitations).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

SCHEMA_VERSION = "critical-source-anatomy-1.0"
UNKNOWN = "UNKNOWN"
MISSING = "MISSING"
PRESENT = "PRESENT"

FIELDS: Tuple[str, ...] = (
    "methods",
    "sample_or_data",
    "assumptions",
    "findings",
    "limitations",
    "replication_or_falsification",
)

_HEADING_PATTERNS: Mapping[str, Tuple[str, ...]] = {
    "methods": (
        r"methods?", r"methodology", r"materials?\s+and\s+methods?",
        r"experimental\s+(?:setup|design|procedure)", r"procedure", r"study\s+design",
    ),
    "sample_or_data": (
        r"participants?", r"sample", r"subjects?", r"population",
        r"data(?:set)?", r"data\s+collection", r"materials?",
    ),
    "assumptions": (
        r"assumptions?", r"model\s+assumptions?", r"identification\s+assumptions?",
    ),
    "findings": (
        r"results?", r"findings?", r"observations?", r"main\s+results?",
        r"conclusions?",
    ),
    "limitations": (
        r"limitations?", r"study\s+limitations?", r"threats?\s+to\s+validity",
        r"limitations?\s+and\s+future\s+work",
    ),
    "replication_or_falsification": (
        r"replication", r"reproducibility", r"robustness", r"validation",
        r"external\s+validation", r"sensitivity\s+analysis", r"falsification",
        r"ablation",
    ),
}

_CUE_PATTERNS: Mapping[str, Tuple[re.Pattern, ...]] = {
    "methods": tuple(re.compile(p, re.I) for p in (
        r"\bwe (?:measured|estimated|tested|randomized|randomised|collected|used)\b",
        r"\bthe (?:experiment|study|analysis) (?:used|included|measured|tested)\b",
    )),
    "sample_or_data": tuple(re.compile(p, re.I) for p in (
        r"\b(?:n\s*=\s*\d+|\d+\s+(?:participants|subjects|patients|samples|observations))\b",
        r"\bdata (?:were|was) (?:collected|obtained|drawn|downloaded)\b",
    )),
    "assumptions": tuple(re.compile(p, re.I) for p in (
        r"\bwe assume\b", r"\bassum(?:e|ed|ing|ption)s?\b",
    )),
    "findings": tuple(re.compile(p, re.I) for p in (
        r"\bwe (?:found|observed|show|showed|report)\b", r"\bresults? (?:show|showed|indicate|suggest)\b",
    )),
    "limitations": tuple(re.compile(p, re.I) for p in (
        r"\blimitations?\b", r"\bshould be interpreted with caution\b",
        r"\bcannot rule out\b", r"\bmay not generalize\b",
    )),
    "replication_or_falsification": tuple(re.compile(p, re.I) for p in (
        r"\breplicat(?:e|ed|ion|ability)\b", r"\breproducib(?:le|ility)\b",
        r"\brobust(?:ness)?\b", r"\bsensitivity analysis\b", r"\bexternal validation\b",
        r"\bfalsif(?:y|ied|ication)\b", r"\bablation\b",
    )),
}

_HEADING_LINE = re.compile(r"(?m)^[ \t]{0,3}(?:#{1,6}[ \t]*)?([^\n]{2,100})[ \t]*$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def _norm_heading(value: str) -> str:
    clean = re.sub(r"^[\dIVXivx.()\-\s]+", "", str(value or "")).strip()
    clean = re.sub(r"[:.\s]+$", "", clean).strip()
    return clean.casefold()


def _heading_field(value: str) -> str:
    heading = _norm_heading(value)
    if not heading or len(heading.split()) > 10:
        return ""
    for field, patterns in _HEADING_PATTERNS.items():
        if any(re.fullmatch(pattern, heading, re.I) for pattern in patterns):
            return field
    return ""


def _heading_blocks(text: str) -> List[Dict]:
    matches = []
    for match in _HEADING_LINE.finditer(text):
        field = _heading_field(match.group(1))
        if field:
            matches.append((match, field))
    out: List[Dict] = []
    for index, (match, field) in enumerate(matches):
        start = match.end()
        end = matches[index + 1][0].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) < 40:
            continue
        excerpt = " ".join(body.split())[:1400]
        out.append({
            "field": field,
            "status": PRESENT,
            "extraction_method": "explicit_heading_block",
            "heading": " ".join(match.group(1).split())[:100],
            "span_start": start,
            "span_end": min(end, start + max(1, len(body))),
            "excerpt": excerpt,
        })
    return out


def _sentences_with_spans(text: str) -> List[Tuple[int, int, str]]:
    rows: List[Tuple[int, int, str]] = []
    start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        end = match.start()
        chunk = text[start:end].strip()
        if chunk:
            left = text.find(chunk, start, max(start + 1, end + 1))
            left = start if left < 0 else left
            rows.append((left, left + len(chunk), chunk))
        start = match.end()
    tail = text[start:].strip()
    if tail:
        left = text.find(tail, start)
        left = start if left < 0 else left
        rows.append((left, left + len(tail), tail))
    return rows


def _cue_record(field: str, text: str) -> Dict:
    for start, end, sentence in _sentences_with_spans(text):
        compact = " ".join(sentence.split())
        if len(compact) < 30 or len(compact) > 1800:
            continue
        for pattern in _CUE_PATTERNS[field]:
            if pattern.search(compact):
                return {
                    "field": field,
                    "status": PRESENT,
                    "extraction_method": "explicit_text_cue",
                    "heading": "",
                    "span_start": start,
                    "span_end": end,
                    "excerpt": compact[:1400],
                }
    return {}


def extract_critical_source_anatomy(text: str) -> Dict:
    """Extract source anatomy from the processed full text, without guessing."""
    body = str(text or "")
    base = {
        "schema_version": SCHEMA_VERSION,
        "ran": bool(body.strip()),
        "processed_text_chars": len(body),
        "fields": {},
        "present_count": 0,
        "missing_count": len(FIELDS),
        "complete": False,
        "truth_boundary": (
            "section/cue detection records what text exposed; it does not prove the "
            "study is valid, replicated, unbiased, causal or true"
        ),
    }
    if not body.strip():
        base["fields"] = {
            field: {"field": field, "status": UNKNOWN, "reason": "full text unavailable"}
            for field in FIELDS
        }
        return base

    by_field: Dict[str, Dict] = {}
    for record in _heading_blocks(body):
        by_field.setdefault(record["field"], record)
    for field in FIELDS:
        if field not in by_field:
            cue = _cue_record(field, body)
            if cue:
                by_field[field] = cue
        if field not in by_field:
            by_field[field] = {
                "field": field,
                "status": UNKNOWN,
                "extraction_method": "none",
                "heading": "",
                "span_start": None,
                "span_end": None,
                "excerpt": "",
                "reason": (
                    "processed text did not expose a sufficiently explicit heading/cue; "
                    "absence is not evidence that this concept is absent from the study"
                ),
            }

    present = sum(1 for field in FIELDS if by_field[field]["status"] == PRESENT)
    base["fields"] = by_field
    base["present_count"] = present
    base["missing_count"] = len(FIELDS) - present
    base["complete"] = present == len(FIELDS)
    base["missing_fields"] = [field for field in FIELDS if by_field[field]["status"] != PRESENT]
    return base


def missing_anatomy_items(anatomy: Mapping) -> List[Dict]:
    if not isinstance(anatomy, Mapping) or not anatomy.get("ran"):
        return [{"code": "FULL TEXT REQUIRED", "detail": "critical-source anatomy did not run on full text"}]
    return [
        {
            "code": "MISSING DATA",
            "detail": f"critical source did not expose an explicit {field.replace('_', ' ')} section/cue",
            "anatomy_field": field,
        }
        for field in anatomy.get("missing_fields") or []
    ]


__all__ = [
    "FIELDS", "MISSING", "PRESENT", "SCHEMA_VERSION", "UNKNOWN",
    "extract_critical_source_anatomy", "missing_anatomy_items",
]
