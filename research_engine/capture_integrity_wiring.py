"""Production wiring for OCR/translation capture integrity (#105/#106).

Capture integrity is deliberately NOT folded into the A-E evidence vocabulary.
A-E answers citation/relevance/entailment/read-depth/source-quality questions.
OCR/translation integrity answers a different question: whether the exact text
capture/transformation is trustworthy enough to be used unattended.

Therefore ``passes_ae`` is never rewritten by this layer.  Instead each source
path receives ``capture_integrity_passed`` and ``passes_verified_support``.
Accepted strong support requires both same-source A-E and capture integrity.
This avoids a mixed semantic score while still failing closed on weak or lost
OCR/translation provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

from .extraction_integrity import passage_integrity_gate
from .models import Passage


_INSTALLED = False


@dataclass
class IntegrityPassage(Passage):
    """Backward-compatible Passage with serialized capture-integrity metadata."""
    extraction_integrity: Dict = field(default_factory=dict)


def _same_passage(passage: Passage, source_id: str, locator: str, text: str) -> bool:
    if passage.source_id != source_id:
        return False
    if locator and (passage.locator or "") != locator:
        return False
    left = (passage.text or "").strip()
    right = (text or "").strip()
    return bool(left and right and (left == right or left.startswith(right) or right.startswith(left)))


def _integrity_for_span(pack, span: Mapping[str, object]) -> Dict:
    if pack is None:
        return {}
    source_id = str(span.get("source_id") or "")
    locator = str(span.get("locator") or "")
    text = str(span.get("passage") or "")
    for passage in getattr(pack, "passages", []) or []:
        if _same_passage(passage, source_id, locator, text):
            return dict(getattr(passage, "extraction_integrity", {}) or {})
    return {}


def _transformation_hint(span: Mapping[str, object]) -> str:
    locator = str(span.get("locator") or "").casefold()
    provenance = str(span.get("passage_provenance") or "").casefold()
    if "ocr" in locator or "ocr" in provenance:
        return "ocr"
    if "translat" in locator or "translat" in provenance:
        return "translation"
    return ""


def _capture_gate(span: Mapping[str, object]) -> Dict:
    integrity = dict(span.get("extraction_integrity") or {})
    if integrity:
        return passage_integrity_gate(integrity)

    # Losing metadata must not turn explicitly transformed evidence into a
    # legacy-native passage.  Locator/provenance are conservative hints only:
    # they can block, never upgrade.
    hinted = _transformation_hint(span)
    if hinted:
        return {
            "status": "missing_integrity_metadata",
            "blocks_strong_claim": True,
            "reason": f"{hinted} passage declared by provenance/locator but integrity ledger is missing",
        }
    return passage_integrity_gate({})


def _check_objects_from_path(claim_mod, path: Mapping[str, object]):
    out = []
    for raw in path.get("checks", []) or []:
        if not isinstance(raw, Mapping):
            continue
        out.append(claim_mod.Check(
            key=str(raw.get("check") or ""),
            label=str(raw.get("label") or ""),
            status=str(raw.get("status") or claim_mod.UNKNOWN),
            detail=str(raw.get("detail") or ""),
        ))
    return out


def _path_verified(path: Mapping[str, object]) -> bool:
    return bool(path.get("passes_ae")) and bool(path.get("capture_integrity_passed"))


def install() -> None:
    """Install content-fetch + claim-gate integrity wiring exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import content_fetcher as fetch_mod
    from . import claim_verification as claim_mod

    original_best_excerpts = fetch_mod.ContentFetcher.best_excerpts
    original_enrich = fetch_mod.ContentFetcher.enrich
    original_evidence_spans = claim_mod.evidence_spans
    original_verify_claim = claim_mod.verify_claim
    original_claim_to_dict = claim_mod.ClaimCheck.to_dict

    def best_excerpts_with_integrity(self, chunks, question, budget_chars):
        picked = original_best_excerpts(self, chunks, question, budget_chars)
        for item in picked:
            locator = str(item.get("locator") or "")
            text = str(item.get("text") or "").rstrip(" …")
            candidates = [chunk for chunk in chunks
                          if str(chunk.get("locator") or "") == locator]
            if not candidates:
                candidates = list(chunks)
            chosen: Optional[Mapping] = None
            for chunk in candidates:
                body = str(chunk.get("text") or "")
                if text and (body.startswith(text) or text.startswith(body)):
                    chosen = chunk
                    break
            if chosen is None and len(candidates) == 1:
                chosen = candidates[0]
            if chosen is not None and chosen.get("extraction_integrity"):
                item["extraction_integrity"] = dict(
                    chosen.get("extraction_integrity") or {}
                )
        return picked

    def enrich_with_integrity(self, pack, max_sources=3, budget_chars=2400):
        report = original_enrich(self, pack, max_sources=max_sources,
                                 budget_chars=budget_chars)
        metadata = {}
        for entry in report.get("entries", []) or []:
            source_id = str(entry.get("source_id") or "")
            for excerpt in entry.get("excerpts", []) or []:
                integrity = dict(excerpt.get("extraction_integrity") or {})
                if not integrity:
                    continue
                metadata[(source_id, str(excerpt.get("locator") or ""),
                          str(excerpt.get("text") or "").strip())] = integrity

        replaced = []
        for passage in getattr(pack, "passages", []) or []:
            integrity = dict(getattr(passage, "extraction_integrity", {}) or {})
            if not integrity:
                for (source_id, locator, text), value in metadata.items():
                    if _same_passage(passage, source_id, locator, text):
                        integrity = dict(value)
                        break
            if integrity and not isinstance(passage, IntegrityPassage):
                passage = IntegrityPassage(
                    source_id=passage.source_id,
                    text=passage.text,
                    locator=passage.locator,
                    provenance=passage.provenance,
                    read_level_at_capture=passage.read_level_at_capture,
                    extraction_integrity=integrity,
                )
            elif integrity:
                passage.extraction_integrity = integrity
            replaced.append(passage)
        pack.passages[:] = replaced
        return report

    def evidence_spans_with_integrity(line, records, pack=None, max_spans=3):
        spans = original_evidence_spans(line, records, pack, max_spans=max_spans)
        for span in spans:
            integrity = _integrity_for_span(pack, span)
            if integrity:
                span["extraction_integrity"] = integrity
            span["capture_integrity"] = _capture_gate(span)
        return spans

    def verify_claim_with_integrity(line, pack=None, claim_id="", critical=None,
                                    section=""):
        cc = original_verify_claim(line, pack, claim_id=claim_id,
                                   critical=critical, section=section)
        if not cc.source_checks:
            cc.capture_integrity_passed = False
            cc.passes_verified_support = False
            return cc

        accepted = []
        blocked_reasons = []
        for path in cc.source_checks:
            span = dict(path.get("canonical_span") or {})
            gate = _capture_gate(span)
            capture_passed = not bool(gate.get("blocks_strong_claim"))
            path["capture_integrity"] = gate
            path["capture_integrity_passed"] = capture_passed
            path["passes_verified_support"] = bool(path.get("passes_ae")) and capture_passed
            if bool(path.get("passes_ae")) and not capture_passed:
                blocked_reasons.append(
                    f"{path.get('source_id')}: {gate.get('reason') or 'capture review required'}"
                )
            if _path_verified(path):
                accepted.append(path)

        cc.capture_integrity_passed = False
        cc.passes_verified_support = False

        # Contradiction always wins.  Keep capture audit fields, but never revive
        # a contradicted path merely because its OCR/translation capture is good.
        if cc.contradicted:
            return cc

        if accepted:
            current = next(
                (path for path in accepted
                 if str(path.get("source_id") or "") == cc.supporting_source_id),
                None,
            )
            chosen = current or max(
                accepted,
                key=lambda path: float(
                    (path.get("canonical_span") or {}).get("entailment_score", 0.0) or 0.0
                ),
            )
            cc.supporting_source_id = str(chosen.get("source_id") or "")
            cc.best_source = cc.supporting_source_id
            cc.canonical_span = dict(chosen.get("canonical_span") or {})
            rebuilt = _check_objects_from_path(claim_mod, chosen)
            if rebuilt:
                cc.checks = rebuilt
            cc.capture_integrity_passed = True
            cc.passes_verified_support = True
            cc.verdict = claim_mod.GENUINE_SUPPORT
            return cc

        # A-E may have passed on transformed text, while capture integrity did
        # not. Preserve the true A-E result for audit and block only the final
        # accepted-support gate.
        if blocked_reasons:
            cc.supporting_source_id = ""
            cc.capture_integrity_passed = False
            cc.passes_verified_support = False
            if cc.status("C") == claim_mod.PASS:
                cc.verdict = claim_mod.SOURCE_REPORTED
            else:
                cc.verdict = claim_mod.CITED_ONLY
            cc.reason = (
                "capture/transformation integrity strong-claim gate blocked: "
                + "; ".join(blocked_reasons[:3])
            )
        return cc

    def claim_to_dict_with_capture(self):
        payload = original_claim_to_dict(self)
        path_rows = [dict(row) for row in getattr(self, "source_checks", []) or []]
        verified = bool(getattr(self, "passes_verified_support", False))
        capture_passed = bool(getattr(self, "capture_integrity_passed", False))
        payload["source_checks"] = path_rows
        payload["same_source_ae_passed"] = bool(self.passes_ae and not self.contradicted)
        payload["capture_integrity_passed"] = capture_passed
        payload["passes_verified_support"] = verified
        payload["verified_support"] = verified
        return payload

    fetch_mod.ContentFetcher.best_excerpts = best_excerpts_with_integrity
    fetch_mod.ContentFetcher.enrich = enrich_with_integrity
    claim_mod.evidence_spans = evidence_spans_with_integrity
    claim_mod.verify_claim = verify_claim_with_integrity
    claim_mod.ClaimCheck.to_dict = claim_to_dict_with_capture
