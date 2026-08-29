"""Extraction/transformation integrity primitives.

This module deliberately keeps capture quality separate from source quality and
claim entailment.  A high OCR confidence is *not* an accuracy probability and a
translation agreement score is *not* proof that a statement is true.

The output is JSON-friendly so it can travel with a Passage all the way to the
claim gate without importing OCR/translation dependencies.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Dict, Iterable, List, Mapping, Optional, Sequence


OCR_HIGH = 85.0
OCR_REVIEW = 72.0
OCR_LOW_WORD = 60.0


def _finite_float(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _percentile(values: Sequence[float], q: float) -> float:
    """Small deterministic linear percentile; no numpy dependency."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, float(q))) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def assess_ocr_confidences(
    confidences: Iterable[object],
    *,
    total_tokens: int = 0,
    nonempty_tokens: int = 0,
    engine: str = "tesseract",
    language: str = "",
    dpi: int = 0,
) -> Dict:
    """Summarise OCR engine word-confidence values conservatively.

    Tesseract exposes heuristic word confidence in roughly the [0,100] range.
    It is useful for triage, but it is not calibrated as P(text is correct).
    Invalid values and Tesseract's ``-1`` sentinel are excluded.
    """
    clean: List[float] = []
    for raw in confidences:
        value = _finite_float(raw)
        if value is None or value < 0.0:
            continue
        clean.append(max(0.0, min(100.0, value)))

    total = max(0, int(total_tokens or 0))
    nonempty = max(0, int(nonempty_tokens or 0))
    if total and nonempty > total:
        nonempty = total

    if clean:
        mean_conf = sum(clean) / len(clean)
        median_conf = float(median(clean))
        p10 = _percentile(clean, 0.10)
        low_fraction = sum(v < OCR_LOW_WORD for v in clean) / len(clean)
    else:
        mean_conf = median_conf = p10 = 0.0
        low_fraction = 1.0

    token_coverage = (nonempty / total) if total else (1.0 if clean else 0.0)
    # A single optimistic mean can hide badly corrupted tails.  Triage uses a
    # conservative blend and additionally fails closed on sparse/no word data.
    conservative = min(mean_conf, median_conf, p10 + 12.0)
    if not clean or len(clean) < 3:
        label = "unknown"
        review_required = True
        reason = "OCR word-confidence data insufficient"
    elif conservative >= OCR_HIGH and low_fraction <= 0.10 and token_coverage >= 0.70:
        label = "high"
        review_required = False
        reason = "OCR capture quality high enough for automated evidence use"
    elif conservative >= OCR_REVIEW and low_fraction <= 0.30 and token_coverage >= 0.45:
        label = "medium"
        review_required = True
        reason = "OCR capture usable for discovery but critical evidence needs review"
    else:
        label = "low"
        review_required = True
        reason = "OCR capture quality too weak for unattended strong-claim support"

    return {
        "method": "ocr",
        "engine": str(engine or "unknown"),
        "language": str(language or ""),
        "dpi": max(0, int(dpi or 0)),
        "quality_label": label,
        "review_required": bool(review_required),
        "reason": reason,
        "confidence_semantics": (
            "engine word-confidence triage signal; NOT a calibrated probability "
            "that OCR text is correct"
        ),
        "mean_word_confidence": round(mean_conf, 3),
        "median_word_confidence": round(median_conf, 3),
        "p10_word_confidence": round(p10, 3),
        "low_confidence_fraction": round(low_fraction, 4),
        "valid_confidence_words": len(clean),
        "total_tokens": total,
        "nonempty_tokens": nonempty,
        "token_coverage": round(token_coverage, 4),
    }


def native_text_integrity(*, engine: str = "native_text") -> Dict:
    """Capture metadata for text extracted without OCR/translation.

    This does not certify the source as true; it only says no OCR uncertainty
    was introduced by this capture step.
    """
    return {
        "method": "native_text",
        "engine": str(engine or "native_text"),
        "quality_label": "native",
        "review_required": False,
        "reason": "no OCR confidence gate applies to native text extraction",
        "confidence_semantics": "capture-method metadata only; NOT source truth",
    }


def passage_integrity_gate(metadata: Optional[Mapping[str, object]]) -> Dict:
    """Decide whether transformed capture may support an unattended strong claim.

    Unknown metadata is backward compatible: legacy native passages are not
    automatically rejected.  But if a passage explicitly declares OCR or
    translation provenance, missing/weak verification fails closed.
    """
    data = dict(metadata or {})
    method = str(data.get("method") or "").strip().lower()
    if not method:
        return {
            "status": "unknown",
            "blocks_strong_claim": False,
            "reason": "legacy passage has no extraction-integrity metadata",
        }
    if method == "native_text":
        return {"status": "pass", "blocks_strong_claim": False,
                "reason": "native text capture"}
    if method == "ocr":
        if bool(data.get("review_required", True)):
            return {"status": "review_required", "blocks_strong_claim": True,
                    "reason": str(data.get("reason") or "OCR review required")}
        if str(data.get("quality_label") or "").lower() != "high":
            return {"status": "review_required", "blocks_strong_claim": True,
                    "reason": "OCR quality is not high"}
        return {"status": "pass", "blocks_strong_claim": False,
                "reason": "high-quality OCR capture"}
    if method == "translation":
        verdict = str(data.get("verification_verdict") or "").upper()
        if verdict != "AGREEMENT_OK" or bool(data.get("review_required", True)):
            return {"status": "review_required", "blocks_strong_claim": True,
                    "reason": str(data.get("reason") or "translation not independently verified")}
        return {"status": "pass", "blocks_strong_claim": False,
                "reason": "independent translation agreement gate passed"}
    return {"status": "unknown", "blocks_strong_claim": True,
            "reason": f"unrecognised transformation method: {method}"}
