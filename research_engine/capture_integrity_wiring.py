"""Production wiring for OCR/translation capture integrity (#105/#106).

This layer preserves the existing Passage API while allowing transformed text to
carry structured extraction integrity all the way through ContentFetcher and
claim verification.  A-E remain separate evidence checks; this gate is an
additional prerequisite for *accepted strong support* and never upgrades truth.
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
                span["capture_integrity"] = passage_integrity_gate(integrity)
        return spans

    def verify_claim_with_integrity(line, pack=None, claim_id="", critical=None,
                                    section=""):
        cc = original_verify_claim(line, pack, claim_id=claim_id,
                                   critical=critical, section=section)
        if not cc.source_checks:
            return cc

        accepted = []
        blocked_reasons = []
        for path in cc.source_checks:
            span = dict(path.get("canonical_span") or {})
            integrity = dict(span.get("extraction_integrity") or {})
            gate = passage_integrity_gate(integrity)
            path["capture_integrity"] = gate
            if bool(path.get("passes_ae")) and gate.get("blocks_strong_claim"):
                path["passes_ae"] = False
                blocked_reasons.append(
                    f"{path.get('source_id')}: {gate.get('reason') or 'capture review required'}"
                )
            if bool(path.get("passes_ae")):
                accepted.append(path)

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
            cc.verdict = claim_mod.GENUINE_SUPPORT
            return cc

        # A-E may have passed on transformed text, but transformed capture itself
        # did not pass.  Keep it visible as source-reported/cited, never verified.
        if blocked_reasons:
            cc.supporting_source_id = ""
            if cc.status("C") == claim_mod.PASS:
                cc.verdict = claim_mod.SOURCE_REPORTED
            else:
                cc.verdict = claim_mod.CITED_ONLY
            cc.reason = (
                "capture/transformation integrity strong-claim gate blocked: "
                + "; ".join(blocked_reasons[:3])
            )
        return cc

    fetch_mod.ContentFetcher.best_excerpts = best_excerpts_with_integrity
    fetch_mod.ContentFetcher.enrich = enrich_with_integrity
    claim_mod.evidence_spans = evidence_spans_with_integrity
    claim_mod.verify_claim = verify_claim_with_integrity
