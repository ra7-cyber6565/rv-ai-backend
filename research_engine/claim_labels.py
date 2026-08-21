"""Claim-label honesty gate.

Compatibility + production rule:
- default helper behaviour remains depth/citation-only for old tests/callers;
- the production orchestrator passes ``check_entailment=True``;
- in that strict path, full-text access alone is NOT enough: the same cited
  source must pass citation + relevance + support + depth + quality (A-E).

No label is ever upgraded here.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .models import EvidencePack

ESTABLISHED = "ESTABLISHED"
SOURCE_REPORTED = "SOURCE-REPORTED"
UNVERIFIED = "UNVERIFIED"

_STRONG_LABEL_RE = re.compile(
    r"\[\s*(ESTABLISHED(?:\s+FACT)?|FACT|STRONG\s+EVIDENCE)\s*\]",
    re.IGNORECASE,
)
_SID_RE = re.compile(r"\[\s*S\s*(\d{1,3})[^\]]*\]", re.IGNORECASE)
_NO_SOURCE_RE = re.compile(r"\[\s*NO[\s\-]?SOURCE\s*\]", re.IGNORECASE)
_FULL = "full_text"


def _cited_ids(line: str) -> List[str]:
    out: List[str] = []
    for num in _SID_RE.findall(line or ""):
        sid = f"S{int(num)}"
        if sid not in out:
            out.append(sid)
    return out


def _ae_verdict(line: str, pack: Optional[EvidencePack]) -> Tuple[Optional[bool], str]:
    """Cumulative same-source A-E result; None means context unavailable."""
    if pack is None or not str(getattr(pack, "question", "") or "").strip():
        return None, "claim-level A-E context available nahi tha"
    try:
        from .evidence_verification import EvidenceVerifier
        report = EvidenceVerifier().verify(line, pack)
    except Exception as exc:  # strong labels fail closed
        return False, f"claim-level A-E verification run nahi ho saki ({type(exc).__name__})"
    if not report.items:
        return False, "labelled factual claim A-E verifier ne parse nahi ki"
    item = report.items[0]
    if item.verdict == "verified_against_available_evidence":
        return True, (
            "same cited source ne citation+relevance+support+depth+quality A-E gate pass kiya"
        )
    return False, item.note or "claim-level A-E gate pass nahi hua"


def line_verdict(
    line: str,
    pack: Optional[EvidencePack],
    check_entailment: bool = False,
) -> Tuple[str, str]:
    """Return strongest label allowed by the requested checking depth."""
    ids = _cited_ids(line)
    records = []
    if pack is not None:
        records = [pack.by_id(sid) for sid in ids]
        records = [record for record in records if record is not None]

    if not records:
        if _NO_SOURCE_RE.search(line or ""):
            return UNVERIFIED, "is line par koi source nahi hai ([NO-SOURCE])"
        if ids:
            return UNVERIFIED, (
                "cite kiye gaye " + ", ".join(ids) + " evidence pack mein nahi mile"
            )
        return UNVERIFIED, "is line par koi [S#] citation nahi hai"

    levels = {}
    for record in records:
        try:
            level = record.reading_level()
        except Exception:  # pragma: no cover
            level = "metadata"
        levels[record.source_id] = level

    full = [sid for sid, level in levels.items() if level == _FULL]
    if not full:
        detail = ", ".join(f"{sid}={level}" for sid, level in levels.items())
        return SOURCE_REPORTED, f"full text nahi padha gaya ({detail})"

    if not check_entailment:
        return ESTABLISHED, f"full text padha gaya: {', '.join(full)}"

    verified, why = _ae_verdict(line, pack)
    if verified is True:
        return ESTABLISHED, why
    if verified is None:
        # Strict check requested but context missing: strong label ko pass mat
        # karo. Unknown verification is not PASS.
        return UNVERIFIED, why
    return UNVERIFIED, f"full text access tha, lekin {why}"


def downgrade(
    text: str,
    pack: Optional[EvidencePack] = None,
    check_entailment: bool = False,
) -> Tuple[str, Dict]:
    """Strong user-facing labels ko deterministic evidence state se match karao."""
    body = text or ""
    report: Dict = {
        "checked": 0,
        "downgraded": 0,
        "to_source_reported": 0,
        "to_unverified": 0,
        "a_e_checked": 0,
        "a_e_failed": 0,
        # Claude compatibility name; in production this means the stricter A-E
        # gate blocked a strong label, not merely a lexical entailment proxy.
        "entailment_blocked": 0,
        "details": [],
        "note": "",
    }
    if not body.strip():
        return body, report

    out_lines: List[str] = []
    for raw in body.splitlines():
        if not _STRONG_LABEL_RE.search(raw):
            out_lines.append(raw)
            continue

        report["checked"] += 1
        verdict, why = line_verdict(raw, pack, check_entailment=check_entailment)
        if check_entailment:
            report["a_e_checked"] += 1
            if verdict != ESTABLISHED:
                report["a_e_failed"] += 1
                report["entailment_blocked"] += 1

        if verdict == ESTABLISHED:
            out_lines.append(raw)
            continue

        new_line = _STRONG_LABEL_RE.sub(f"[{verdict}]", raw)
        out_lines.append(new_line)
        report["downgraded"] += 1
        if verdict == SOURCE_REPORTED:
            report["to_source_reported"] += 1
        else:
            report["to_unverified"] += 1
        if len(report["details"]) < 8:
            snippet = re.sub(r"^[#\s\-\*\d\.]+", "", new_line).strip()
            report["details"].append(f"{snippet[:150]} — {why}")

    if report["downgraded"]:
        bits = []
        if report["to_source_reported"]:
            bits.append(f"{report['to_source_reported']} claim SOURCE-REPORTED")
        if report["to_unverified"]:
            bits.append(f"{report['to_unverified']} claim UNVERIFIED")
        strict_reason = (
            "full text hone ke baad bhi same cited source par claim-level A-E support "
            "nahi mila"
            if check_entailment and report["a_e_failed"]
            else "source access depth strong label ke liye enough nahi thi"
        )
        report["note"] = (
            f"{report['downgraded']}/{report['checked']} strong dave neeche kiye gaye "
            f"(" + ", ".join(bits) + f") — {strict_reason}."
        )
    return "\n".join(out_lines), report


def human_note(report: Optional[Dict]) -> str:
    """Audit section ke liye normal bhasha, raw PASS/FAIL log nahi."""
    r = report or {}
    checked = int(r.get("checked") or 0)
    if not checked:
        return (
            "Answer mein 'established fact' type ka koi strong dava nahi tha, "
            "isliye yahan kuch downgrade karne ki zaroorat nahi padi."
        )
    down = int(r.get("downgraded") or 0)
    if not down:
        if int(r.get("a_e_checked") or 0):
            return (
                f"{checked} strong dave check kiye gaye; required full-text access ke "
                "saath claim-level citation, relevance, support, depth aur source-quality "
                "gate bhi pass hua, isliye ESTABLISHED label reh saka."
            )
        return (
            f"{checked} strong dave depth-level check mein theek the. Claim-level A-E "
            "strict mode is helper call mein apply nahi hua tha."
        )
    return (
        f"{down} jagah ESTABLISHED strong label neeche karna pada. Jahan sirf "
        "abstract/snippet support hai wahan SOURCE-REPORTED hota hai; aur jahan "
        "strong claim ko same cited source par A-E support prove nahi hua wahan "
        "UNVERIFIED rakha jaata hai. Sirf full text khulna enough nahi hai."
    )


LABEL_RULE_PROMPT = """# LABEL RULE (strict evidence honesty)
- `[ESTABLISHED]` / `[FACT]` / `[STRONG EVIDENCE]` sirf tab likho jab source
  block mein required `full_text` access ho AUR claim usi cited evidence se
  citation + relevance + support + depth + quality checks pass kar sake.
- Full text khul jaana apne aap claim ko verify nahi karta.
- Agar sirf abstract/snippet/metadata mila hai, `[SOURCE-REPORTED]` likho —
  matlab source ye report karta hai, confirmed fact nahi.
- Kisi source se support na ho to `[NO-SOURCE]` + `[INFERENCE]`, `[HYPOTHESIS]`
  ya `[UNVERIFIED]` use karo.
- Labels kabhi confidence decoration nahi hain; evidence state ka sach hain.
"""
