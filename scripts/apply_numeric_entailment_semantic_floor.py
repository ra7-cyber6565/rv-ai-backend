"""Guarded one-shot patch for numeric entailment semantic floor.

This script edits only research_engine/claim_verification.py and refuses to run
if the expected post-a96cf block is not present exactly once.  It does not lower
any configured threshold.  The +0.20 all-number bonus remains in evidence-span
ranking; check C itself must still have nonnumeric semantic overlap.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "research_engine" / "claim_verification.py"

EXPECTED = {
    "_ENTAIL_SIM": "0.30",
    "_ENTAIL_SIM_WITH_NUM": "0.12",
    "_MIN_TEXT_CHARS": "120",
    "_MIN_RELEVANCE": "0.25",
    "_MIN_QUALITY": "0.35",
    "_LOW_QUALITY": "0.20",
}

OLD = '''    wanted = _numbers(body)\n    score = _similarity(body, span_text)\n    low = span_text.lower()\n    hits = [n for n in wanted if n in low]\n    matched_all = bool(wanted) and len(hits) == len(wanted)\n    effective = score + (0.20 if matched_all else 0.0)\n    # Relaxed numeric threshold sirf tab, jab claim ke SAARE numbers isi span mein\n    # exact mile hon. Pehle yahan `if wanted` tha: claim mein number hone se hi\n    # bar 0.30 se 0.12 gir jaata tha, chahe ek bhi number span mein na mile —\n    # yaani "same-ish numbers, bilkul alag matlab" wala text bhi genuine support\n    # ban jaata tha. Numbers adhoore mile to poora text-match hi maangte hain.\n    threshold = _ENTAIL_SIM_WITH_NUM if matched_all else _ENTAIL_SIM\n    sid = str(span.get("source_id") or "?")\n    locator = str(span.get("locator") or "").strip()\n    note = (f"{len(hits)}/{len(wanted)} number exact span mein mile, text-match {score:.2f}"\n            if wanted else f"text-match {score:.2f}")\n    where = f" ({locator})" if locator else ""\n    if effective >= threshold:\n        c.status = PASS\n        c.detail = f"{sid} ke exact evidence span{where} se support mila — {note}"\n    else:\n        c.status = FAIL\n        c.detail = f"{sid} ke exact evidence span{where} mein support nahi dikha — {note}"\n'''

NEW = '''    wanted = _numbers(body)\n    score = _similarity(body, span_text)\n    low = span_text.lower()\n    hits = [n for n in wanted if n in low]\n    matched_all = bool(wanted) and len(hits) == len(wanted)\n\n    # Exact numbers are useful corroboration, but numbers themselves must never\n    # manufacture semantic support.  The +0.20 all-number bonus remains in\n    # `evidence_spans()` for deterministic span ranking only.  For the C verdict,\n    # strip numeric tokens and require real subject/meaning overlap as well.\n    nonnumeric_body = _NUM_RE.sub(" ", body)\n    nonnumeric_span = _NUM_RE.sub(" ", span_text)\n    nonnumeric_score = _similarity(nonnumeric_body, nonnumeric_span)\n    threshold = _ENTAIL_SIM_WITH_NUM if matched_all else _ENTAIL_SIM\n    decision_score = nonnumeric_score if matched_all else score\n\n    sid = str(span.get("source_id") or "?")\n    locator = str(span.get("locator") or "").strip()\n    if wanted:\n        note = (f"{len(hits)}/{len(wanted)} number exact span mein mile, "\n                f"text-match {score:.2f}, nonnumeric-match {nonnumeric_score:.2f}")\n    else:\n        note = f"text-match {score:.2f}"\n    where = f" ({locator})" if locator else ""\n    if decision_score >= threshold:\n        c.status = PASS\n        c.detail = f"{sid} ke exact evidence span{where} se support mila — {note}"\n    else:\n        c.status = FAIL\n        c.detail = f"{sid} ke exact evidence span{where} mein support nahi dikha — {note}"\n'''


def thresholds(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in EXPECTED:
        match = re.search(rf"^{re.escape(name)}\s*=\s*([0-9.]+)", text, re.MULTILINE)
        out[name] = match.group(1) if match else ""
    return out


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    before = thresholds(text)
    if before != EXPECTED:
        raise SystemExit(f"STOP: threshold constants changed unexpectedly: {before}")
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"STOP: expected check_c_span block count=1, got {count}")
    patched = text.replace(OLD, NEW, 1)
    after = thresholds(patched)
    if after != EXPECTED:
        raise SystemExit(f"STOP: patch changed thresholds: {after}")
    ranking_marker = "entailment_score = float(score) + (0.20 if matched_all else 0.0)"
    if ranking_marker not in patched:
        raise SystemExit("STOP: numeric ranking bonus unexpectedly missing")
    TARGET.write_text(patched, encoding="utf-8")
    print("Numeric entailment semantic-floor patch applied safely.")
    print("Thresholds unchanged:", after)
    print("All-number +0.20 bonus preserved for span ranking only: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
