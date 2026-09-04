"""Original-text provenance for multilingual AI-1 evidence.

The engine already accepts Unicode text and has script/search bridges. The
missing governance piece was an explicit receipt that says whether the evidence
surface being reasoned over is still the original source text or a claimed
translation/transformation.

This module deliberately detects scripts, not languages. Script detection is a
Unicode property and can be recorded deterministically; calling Bengali script
"Bengali language" or Latin script "English" would be an inference. Likewise a
search/transliteration bridge is never labelled translation.
"""
from __future__ import annotations

from typing import Dict, List, Mapping

from .lang_bridge import dominant_script, script_counts

SCHEMA_VERSION = "multilingual-source-provenance-1.0"


def _translation_integrity(source) -> Dict:
    value = getattr(source, "translation_integrity", None)
    if isinstance(value, Mapping):
        return dict(value)
    verdict = getattr(source, "domain_verdict", None)
    if isinstance(verdict, Mapping):
        value = verdict.get("translation_integrity")
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _source_text(pack, source_id: str, fallback: str) -> str:
    chunks: List[str] = []
    for passage in list(getattr(pack, "passages", []) or []):
        if str(getattr(passage, "source_id", "") or "") != source_id:
            continue
        text = str(getattr(passage, "text", "") or "").strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks) if chunks else str(fallback or "")


def build_original_text_receipt(text: str, translation_integrity: Mapping | None = None) -> Dict:
    body = str(text or "")
    counts = script_counts(body)
    scripts = sorted(counts, key=lambda key: (-counts[key], key))
    translation = dict(translation_integrity or {})
    translation_claimed = bool(translation)
    verdict = str(translation.get("verification_verdict") or "").upper()
    review_required = bool(translation.get("review_required", True)) if translation_claimed else False
    return {
        "schema_version": SCHEMA_VERSION,
        "text_observed": bool(body.strip()),
        "observed_scripts": scripts,
        "script_counts": counts,
        "dominant_script": dominant_script(body) if body.strip() else "unknown",
        "language_inferred": False,
        "original_text_preserved": not translation_claimed,
        "translation_claimed": translation_claimed,
        "translation_verification_verdict": verdict or "NOT APPLICABLE",
        "translation_review_required": review_required,
        "search_or_transliteration_bridge_is_translation": False,
        "truth_boundary": (
            "Unicode script receipt proves only the text/script surface processed; script != language, "
            "multilingual text read != translation, and translation quality != claim truth"
        ),
    }


def annotate_multilingual_provenance(pack) -> Dict:
    report = {
        "sources_annotated": 0,
        "non_latin_or_mixed_sources": 0,
        "translation_claimed_sources": 0,
        "translation_review_required_sources": 0,
        "raw_text_copied_into_report": False,
    }
    for source in list(getattr(pack, "sources", []) or []):
        sid = str(getattr(source, "source_id", "") or "")
        text = _source_text(pack, sid, getattr(source, "snippet", ""))
        if not text.strip():
            continue
        receipt = build_original_text_receipt(text, _translation_integrity(source))
        verdict = getattr(source, "domain_verdict", None)
        verdict = dict(verdict) if isinstance(verdict, dict) else {}
        verdict["multilingual_source_provenance"] = receipt
        source.domain_verdict = verdict
        report["sources_annotated"] += 1
        observed = set(receipt.get("observed_scripts") or [])
        if observed - {"latin", "unknown"} or len(observed - {"unknown"}) > 1:
            report["non_latin_or_mixed_sources"] += 1
        if receipt["translation_claimed"]:
            report["translation_claimed_sources"] += 1
        if receipt["translation_review_required"]:
            report["translation_review_required_sources"] += 1
    report["note"] = (
        f"{report['sources_annotated']} source evidence surfaces par Unicode-script provenance record hua; "
        "language guess nahi ki gayi aur search/transliteration ko translation nahi kaha gaya."
    )
    return report


__all__ = [
    "SCHEMA_VERSION", "annotate_multilingual_provenance", "build_original_text_receipt",
]
