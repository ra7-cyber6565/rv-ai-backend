"""Guarded one-shot P0-D patcher. Refuses drift and writes only after all guards pass."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def load(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> None:
    targets = {
        "research_engine/models.py": load("research_engine/models.py"),
        "research_engine/evidence.py": load("research_engine/evidence.py"),
        "research_engine/content_fetcher.py": load("research_engine/content_fetcher.py"),
        "research_engine/evidence_drafting.py": load("research_engine/evidence_drafting.py"),
    }
    originals = dict(targets)

    # 1) Freeze provenance/depth on each Passage at capture time. Defaults keep
    # older serialized/manual callers readable; production writers set both.
    targets["research_engine/models.py"] = replace_once(
        targets["research_engine/models.py"],
        '''@dataclass\nclass Passage:\n    """Kisi source ka wo hissa jo actually reasoning model ko bheja gaya."""\n    source_id: str\n    text: str\n    locator: str = ""\n\n    def to_dict(self) -> Dict:\n        return asdict(self)\n''',
        '''@dataclass\nclass Passage:\n    """Kisi source ka exact hissa + capture-time provenance/depth.\n\n    SourceRecord mutable hai: full-text reading ke baad uska read_level upgrade\n    ho sakta hai. Isliye passage ko capture ke waqt ka level alag freeze karna\n    zaroori hai; warna purana search snippet baad mein full-text evidence ban\n    sakta hai. Khaali fields legacy/manual callers ke liye backward-compatible\n    hain; production writers inhe explicitly set karte hain.\n    """\n    source_id: str\n    text: str\n    locator: str = ""\n    provenance: str = ""\n    read_level_at_capture: str = ""\n\n    def to_dict(self) -> Dict:\n        return asdict(self)\n''',
        "models.Passage provenance fields",
    )

    # 2) Initial retrieval passages remember their ORIGINAL depth. If the same
    # SourceRecord is later upgraded, this frozen value does not change.
    targets["research_engine/evidence.py"] = replace_once(
        targets["research_engine/evidence.py"],
        '''                passages.append(Passage(\n                    source_id=s.source_id,\n                    text=text[:chars_per_source],\n                    locator=s.locator,\n                ))\n''',
        '''                passages.append(Passage(\n                    source_id=s.source_id,\n                    text=text[:chars_per_source],\n                    locator=s.locator,\n                    provenance="retrieval_excerpt",\n                    read_level_at_capture=s.reading_level(),\n                ))\n''',
        "evidence.build_pack capture metadata",
    )

    # 3) A successful external full-text read supersedes the earlier snippet
    # passages for that source. Failed reads leave the original pack untouched.
    targets["research_engine/content_fetcher.py"] = replace_once(
        targets["research_engine/content_fetcher.py"],
        '''            combined = []\n            for excerpt in entry["excerpts"]:\n                locator = excerpt.get("locator") or ""\n                prefix = f"[{locator}] " if locator else ""\n                combined.append(prefix + excerpt["text"])\n                pack.passages.append(Passage(\n                    source_id=source.source_id,\n                    text=excerpt["text"],\n                    locator=locator,\n                ))\n''',
        '''            # The source object has just been upgraded to full_text. Any\n            # passage captured before this successful read still represents the\n            # old snippet/abstract depth, so it must not survive as if it were a\n            # full-text passage. Keep other sources untouched.\n            pack.passages[:] = [\n                passage for passage in pack.passages\n                if passage.source_id != source.source_id\n            ]\n\n            combined = []\n            for excerpt in entry["excerpts"]:\n                locator = excerpt.get("locator") or ""\n                prefix = f"[{locator}] " if locator else ""\n                combined.append(prefix + excerpt["text"])\n                pack.passages.append(Passage(\n                    source_id=source.source_id,\n                    text=excerpt["text"],\n                    locator=locator,\n                    provenance="full_text_excerpt",\n                    read_level_at_capture=source.reading_level(),\n                ))\n''',
        "content_fetcher replace stale passages",
    )

    drafting = targets["research_engine/evidence_drafting.py"]

    drafting = replace_once(
        drafting,
        '''def _eligibility(source: SourceRecord, passage: str) -> Tuple[bool, List[str], Dict[str, str]]:\n    """Pre-claim B/D/E eligibility.  C is intentionally impossible pre-draft."""\n    b = CV.check_b([source])\n    d = CV.check_d([source])\n    e = CV.check_e([source])\n    checks = {"B": b.status, "D": d.status, "E": e.status}\n    reasons: List[str] = []\n    if len((passage or "").strip()) < CV._MIN_TEXT_CHARS:\n        reasons.append("segment_too_short")\n    if b.status != CV.PASS:\n        reasons.append("source_relevance_not_pass")\n    if d.status != CV.PASS:\n        reasons.append("reading_depth_not_pass")\n    if e.status != CV.PASS:\n        reasons.append("source_quality_not_pass")\n    return not reasons, reasons, checks\n''',
        '''def _eligibility(\n    source: SourceRecord,\n    passage: str,\n    *,\n    span_kind: str = "passage",\n    passage_provenance: str = "",\n    read_level_at_capture: str = "",\n) -> Tuple[bool, List[str], Dict[str, str]]:\n    """Pre-claim B/D/E + capture-provenance eligibility.\n\n    C is intentionally impossible pre-draft. Crucially, D on the mutable\n    SourceRecord cannot promote material that was captured earlier at a shallower\n    depth. Explicit capture depth therefore adds a second fail-closed depth lock.\n    Legacy/manual Passage objects with no capture metadata retain old behavior;\n    all current production writers stamp the metadata.\n    """\n    b = CV.check_b([source])\n    d = CV.check_d([source])\n    e = CV.check_e([source])\n    checks = {"B": b.status, "D": d.status, "E": e.status}\n    reasons: List[str] = []\n    if len((passage or "").strip()) < CV._MIN_TEXT_CHARS:\n        reasons.append("segment_too_short")\n\n    # `source.snippet` is a display/context aggregate and may combine several\n    # locators. It remains useful context, but strong claims must bind to an\n    # exact Passage record instead.\n    if span_kind == "snippet":\n        reasons.append("snippet_not_strong_evidence_span")\n\n    captured = (read_level_at_capture or "").strip().lower()\n    if span_kind == "passage" and captured and captured != "full_text":\n        reasons.append("passage_capture_depth_not_strong")\n\n    if b.status != CV.PASS:\n        reasons.append("source_relevance_not_pass")\n    if d.status != CV.PASS:\n        reasons.append("reading_depth_not_pass")\n    if e.status != CV.PASS:\n        reasons.append("source_quality_not_pass")\n    return not reasons, reasons, checks\n''',
        "evidence_drafting provenance eligibility",
    )

    drafting = replace_once(
        drafting,
        '''    eligibility_reasons: List[str] = field(default_factory=list)\n    eligibility_checks: Dict[str, str] = field(default_factory=dict)\n''',
        '''    eligibility_reasons: List[str] = field(default_factory=list)\n    eligibility_checks: Dict[str, str] = field(default_factory=dict)\n    passage_provenance: str = ""\n    read_level_at_capture: str = ""\n''',
        "EvidenceDraftSpan provenance fields",
    )

    drafting = replace_once(
        drafting,
        '''            "span_kind": self.span_kind,\n            "question_match": round(float(self.question_match), 4),\n''',
        '''            "span_kind": self.span_kind,\n            "passage_provenance": self.passage_provenance,\n            "read_level_at_capture": self.read_level_at_capture,\n            "question_match": round(float(self.question_match), 4),\n''',
        "EvidenceDraftSpan compact provenance",
    )

    drafting = replace_once(
        drafting,
        '''            (s.span_id, s.source_id, s.locator, s.passage_sha256,\n             bool(s.strong_claim_eligible))\n''',
        '''            (s.span_id, s.source_id, s.locator, s.passage_sha256,\n             s.passage_provenance, s.read_level_at_capture,\n             bool(s.strong_claim_eligible))\n''',
        "manifest hash binds provenance",
    )

    drafting = replace_once(
        drafting,
        '''                f"[{span.span_id}] source={span.source_id} strong_claim_eligible={eligible} "\n                f"kind={span.span_kind} access={span.access_depth} "\n''',
        '''                f"[{span.span_id}] source={span.source_id} strong_claim_eligible={eligible} "\n                f"kind={span.span_kind} provenance={span.passage_provenance or 'legacy'} "\n                f"captured_read={span.read_level_at_capture or 'unknown'} access={span.access_depth} "\n''',
        "prompt provenance metadata",
    )

    drafting = replace_once(
        drafting,
        '''    candidates: List[Tuple[SourceRecord, str, str, str, float]] = []\n    passages = list(getattr(pack, "passages", None) or [])\n    for source in list(pack.sources):\n        chunks: List[Tuple[str, str, str]] = []\n        for passage in passages:\n            if getattr(passage, "source_id", "") != source.source_id:\n                continue\n            text = (getattr(passage, "text", "") or "").strip()\n            if text:\n                chunks.append((text, getattr(passage, "locator", "") or "", "passage"))\n        snippet = (getattr(source, "snippet", "") or "").strip()\n        if snippet:\n            chunks.append((snippet, getattr(source, "locator", "") or "", "snippet"))\n\n        ranked: List[Tuple[str, str, str, float]] = []\n        seen_hashes: set = set()\n        for text, locator, kind in chunks:\n            selected, score = _bounded_question_segment(question, text, segment_chars)\n            if not selected:\n                continue\n            digest = passage_sha256(selected)\n            if digest in seen_hashes:\n                continue\n            seen_hashes.add(digest)\n            where = (locator or getattr(source, "locator", "") or "").strip()\n            if not where:\n                where = ("selected source passage (exact page/section unavailable)"\n                         if kind == "passage" else\n                         "source snippet (exact page/section unavailable)")\n            ranked.append((selected, where, kind, score))\n        ranked.sort(key=lambda row: (row[3], len(row[0])), reverse=True)\n        for selected, where, kind, score in ranked[:max(1, int(max_segments_per_source))]:\n            candidates.append((source, selected, where, kind, score))\n''',
        '''    candidates: List[Tuple[SourceRecord, str, str, str, float, str, str]] = []\n    passages = list(getattr(pack, "passages", None) or [])\n    for source in list(pack.sources):\n        chunks: List[Tuple[str, str, str, str, str]] = []\n        for passage in passages:\n            if getattr(passage, "source_id", "") != source.source_id:\n                continue\n            text = (getattr(passage, "text", "") or "").strip()\n            if text:\n                chunks.append((\n                    text,\n                    getattr(passage, "locator", "") or "",\n                    "passage",\n                    str(getattr(passage, "provenance", "") or ""),\n                    str(getattr(passage, "read_level_at_capture", "") or ""),\n                ))\n        snippet = (getattr(source, "snippet", "") or "").strip()\n        if snippet:\n            chunks.append((\n                snippet, getattr(source, "locator", "") or "", "snippet",\n                "source_snippet", str(source.reading_level() or ""),\n            ))\n\n        ranked: List[Tuple[str, str, str, float, str, str]] = []\n        seen_hashes: set = set()\n        for text, locator, kind, provenance, captured_level in chunks:\n            selected, score = _bounded_question_segment(question, text, segment_chars)\n            if not selected:\n                continue\n            digest = passage_sha256(selected)\n            if digest in seen_hashes:\n                continue\n            seen_hashes.add(digest)\n            where = (locator or getattr(source, "locator", "") or "").strip()\n            if not where:\n                where = ("selected source passage (exact page/section unavailable)"\n                         if kind == "passage" else\n                         "source snippet (exact page/section unavailable)")\n            ranked.append((selected, where, kind, score, provenance, captured_level))\n        ranked.sort(key=lambda row: (row[3], len(row[0])), reverse=True)\n        for selected, where, kind, score, provenance, captured_level in \\n                ranked[:max(1, int(max_segments_per_source))]:\n            candidates.append((source, selected, where, kind, score,\n                               provenance, captured_level))\n''',
        "manifest carries passage capture metadata",
    )

    drafting = replace_once(
        drafting,
        '''    prepared: List[Tuple[Tuple[int, float, float, float], EvidenceDraftSpan]] = []\n    for source, passage, locator, kind, score in candidates:\n        eligible, reasons, checks = _eligibility(source, passage)\n        span = EvidenceDraftSpan(\n''',
        '''    prepared: List[Tuple[Tuple[int, float, float, float], EvidenceDraftSpan]] = []\n    for source, passage, locator, kind, score, provenance, captured_level in candidates:\n        eligible, reasons, checks = _eligibility(\n            source, passage, span_kind=kind, passage_provenance=provenance,\n            read_level_at_capture=captured_level)\n        span = EvidenceDraftSpan(\n''',
        "manifest eligibility receives provenance",
    )

    drafting = replace_once(
        drafting,
        '''            eligibility_reasons=reasons,\n            eligibility_checks=checks,\n        )\n''',
        '''            eligibility_reasons=reasons,\n            eligibility_checks=checks,\n            passage_provenance=provenance,\n            read_level_at_capture=captured_level,\n        )\n''',
        "EvidenceDraftSpan stores provenance",
    )

    targets["research_engine/evidence_drafting.py"] = drafting

    # No write happens until every replacement above succeeded and every result
    # parses. This protects concurrent/drifted branches from partial corruption.
    for rel, text in targets.items():
        ast.parse(text, filename=rel)
        if text == originals[rel]:
            raise RuntimeError(f"{rel}: patch unexpectedly made no change")

    # Contract thresholds live in claim_verification.py; this patch must never
    # touch that file at all.
    if "research_engine/claim_verification.py" in targets:
        raise RuntimeError("P0-D must not patch claim_verification thresholds")

    for rel, text in targets.items():
        (ROOT / rel).write_text(text, encoding="utf-8", newline="\n")

    print("P0-D evidence provenance patch applied to 4 files.")
    print("Capture-time depth frozen; stale passages replaced after successful full-text read.")
    print("Generic source snippets remain context-only for strong-claim eligibility.")


if __name__ == "__main__":
    main()
