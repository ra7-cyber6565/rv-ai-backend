"""Guarded one-shot patcher for P0-B exact-locator binding.

Run only on chatgpt-p0b-hardening-20260824, then remove this script before the
final commit. It refuses to patch if upstream anchors moved.
"""
from __future__ import annotations

from pathlib import Path

PATH = Path("research_engine/evidence_drafting.py")
text = PATH.read_text(encoding="utf-8")

helper_anchor = '''def _normalise_text(value: object) -> str:\n    text = unicodedata.normalize("NFKC", str(value or ""))\n    return " ".join(text.split()).strip()\n\n\n'''
helper_replacement = '''def _normalise_text(value: object) -> str:\n    text = unicodedata.normalize("NFKC", str(value or ""))\n    return " ".join(text.split()).strip()\n\n\n_GENERIC_LOCATOR_MARKERS = (\n    "exact page/section unavailable", "exact page ka pata nahi",\n    "locator unavailable", "locator unknown", "unknown locator",\n)\n\n\ndef _locator_key(value: object) -> str:\n    """Stable locator identity; whitespace-only formatting cannot spoof a mismatch."""\n    return "".join(_normalise_text(value).lower().split())\n\n\ndef _exact_locator_available(value: object) -> bool:\n    """Strong preselection needs a concrete page/section/paragraph locator."""\n    locator = _normalise_text(value).lower()\n    if not locator:\n        return False\n    return not any(marker in locator for marker in _GENERIC_LOCATOR_MARKERS)\n\n\n'''
if text.count(helper_anchor) != 1:
    raise SystemExit("STOP: _normalise_text anchor moved; no patch applied")
text = text.replace(helper_anchor, helper_replacement, 1)

sig_anchor = '''def _eligibility(\n    source: SourceRecord,\n    passage: str,\n    *,\n    span_kind: str = "passage",\n    passage_provenance: str = "",\n    read_level_at_capture: str = "",\n) -> Tuple[bool, List[str], Dict[str, str]]:\n'''
sig_replacement = '''def _eligibility(\n    source: SourceRecord,\n    passage: str,\n    *,\n    span_kind: str = "passage",\n    locator: str = "",\n    passage_provenance: str = "",\n    read_level_at_capture: str = "",\n) -> Tuple[bool, List[str], Dict[str, str]]:\n'''
if text.count(sig_anchor) != 1:
    raise SystemExit("STOP: _eligibility signature moved; no patch applied")
text = text.replace(sig_anchor, sig_replacement, 1)

reason_anchor = '''    if span_kind == "snippet":\n        reasons.append("snippet_not_strong_evidence_span")\n\n    captured = (read_level_at_capture or "").strip().lower()\n'''
reason_replacement = '''    if span_kind == "snippet":\n        reasons.append("snippet_not_strong_evidence_span")\n\n    # Exact-locator binding is part of the evidence-before-generation contract.\n    # A repeated sentence on another page/section must not be able to satisfy a\n    # preselection audit merely because source ID + text happen to match.\n    if span_kind == "passage" and not _exact_locator_available(locator):\n        reasons.append("exact_locator_missing")\n\n    captured = (read_level_at_capture or "").strip().lower()\n'''
if text.count(reason_anchor) != 1:
    raise SystemExit("STOP: eligibility reason anchor moved; no patch applied")
text = text.replace(reason_anchor, reason_replacement, 1)

call_anchor = '''        eligible, reasons, checks = _eligibility(\n            source, passage, span_kind=kind, passage_provenance=provenance,\n            read_level_at_capture=captured_level)\n'''
call_replacement = '''        eligible, reasons, checks = _eligibility(\n            source, passage, span_kind=kind, locator=locator,\n            passage_provenance=provenance,\n            read_level_at_capture=captured_level)\n'''
if text.count(call_anchor) != 1:
    raise SystemExit("STOP: _eligibility call anchor moved; no patch applied")
text = text.replace(call_anchor, call_replacement, 1)

match_anchor = '''        norm_claim = _normalise_text(passage)\n        matched: Optional[EvidenceDraftSpan] = None\n        if source_id and norm_claim:\n            for segment in spans:\n                if segment.source_id != source_id or not segment.strong_claim_eligible:\n                    continue\n                if norm_claim in _normalise_text(segment.passage):\n                    matched = segment\n                    break\n'''
match_replacement = '''        norm_claim = _normalise_text(passage)\n        matched: Optional[EvidenceDraftSpan] = None\n        claim_locator_key = _locator_key(locator)\n        if source_id and norm_claim and _exact_locator_available(locator):\n            for segment in spans:\n                if segment.source_id != source_id or not segment.strong_claim_eligible:\n                    continue\n                if not _exact_locator_available(segment.locator):\n                    continue\n                if _locator_key(segment.locator) != claim_locator_key:\n                    continue\n                if norm_claim in _normalise_text(segment.passage):\n                    matched = segment\n                    break\n'''
if text.count(match_anchor) != 1:
    raise SystemExit("STOP: preselection match anchor moved; no patch applied")
text = text.replace(match_anchor, match_replacement, 1)

PATH.write_text(text, encoding="utf-8", newline="\n")
print("P0-B exact locator binding applied safely.")
print("Strong eligibility now requires a concrete locator.")
print("Post-draft audit now requires same source + exact locator + span text.")
