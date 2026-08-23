"""Run the guarded P0-D patcher with one generated-loop normalization."""
from __future__ import annotations

from scripts import apply_p0d_evidence_provenance as base


_original_replace_once = base.replace_once


def _safe_replace_once(text: str, old: str, new: str, label: str) -> str:
    if label == "manifest carries passage capture metadata":
        anchor = "for selected, where, kind, score, provenance, captured_level in "
        tail = "ranked[:max(1, int(max_segments_per_source))]:"
        start = new.find(anchor)
        end = new.find(tail, start + len(anchor)) if start >= 0 else -1
        if start < 0 or end < 0:
            raise RuntimeError("P0-D v2: generated loop anchors not found")
        new = new[: start + len(anchor)] + tail + new[end + len(tail):]
    return _original_replace_once(text, old, new, label)


base.replace_once = _safe_replace_once

if __name__ == "__main__":
    base.main()
