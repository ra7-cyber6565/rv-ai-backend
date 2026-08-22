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


def _records(line: str, pack: Optional[EvidencePack]) -> List:
    if pack is None:
        return []
    rows = [pack.by_id(sid) for sid in _cited_ids(line)]
    return [row for row in rows if row is not None]


def _has_full_text_cite(line: str, pack: Optional[EvidencePack]) -> bool:
    """Whether a non-patent cited source can enter the strict A-E gate."""
    for record in _records(line, pack):
        try:
            if not getattr(record, "is_patent", False) and record.reading_level() == _FULL:
                return True
        except Exception:  # pragma: no cover - defensive
            continue
    return False


def _ae_verdict(line: str, pack: Optional[EvidencePack]) -> Tuple[Optional[bool], str]:
    """Cumulative same-source A-E result; None means context unavailable."""
    if pack is None:
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
    """Return the strongest label allowed by depth, A-E, and patent rules.

    Patent claims are legal assertions rather than experimental proof. A
    patent-only line therefore stays SOURCE-REPORTED even when its claims or
    description were read. In the production strict path, a non-patent source
    must independently pass the cumulative same-source A-E verification gate.
    """
    ids = _cited_ids(line)
    records = _records(line, pack)

    if not records:
        if _NO_SOURCE_RE.search(line or ""):
            return UNVERIFIED, "is line par koi source nahi hai ([NO-SOURCE])"
        if ids:
            return UNVERIFIED, (
                "cite kiye gaye " + ", ".join(ids) + " evidence pack mein nahi mile"
            )
        return UNVERIFIED, "is line par koi [S#] citation nahi hai"

    levels = {}
    patent_ids: List[str] = []
    for record in records:
        try:
            level = record.reading_level()
        except Exception:  # pragma: no cover
            level = "metadata"
        levels[record.source_id] = level
        if getattr(record, "is_patent", False):
            patent_ids.append(record.source_id)

    # Patent full text can provide prior-art context, never scientific proof.
    full = [sid for sid, level in levels.items()
            if level == _FULL and sid not in patent_ids]
    if not full:
        patent_full = [sid for sid in patent_ids if levels.get(sid) == _FULL]
        if patent_full and len(patent_ids) == len(levels):
            return SOURCE_REPORTED, (
                f"is line ka evidence sirf patent(s) hai ({', '.join(patent_full)}) — "
                "patent ke claims LEGAL dawe hain, experiment ka proof nahi")
        detail = ", ".join(f"{sid}={level}" for sid, level in levels.items())
        if patent_ids:
            detail += f" (patent: {', '.join(patent_ids)} — legal dawa, proof nahi)"
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
        # Compatibility name used by Claude's older tests. It now means a
        # full-text strong label was blocked by the stricter A-E gate; an
        # abstract/snippet depth downgrade is NOT counted here.
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
        ae_attempted = bool(check_entailment and _has_full_text_cite(raw, pack))
        verdict, why = line_verdict(raw, pack, check_entailment=check_entailment)

        # A-E is a separate stage from access-depth gating. Do not report an
        # abstract/snippet downgrade as "A-E checked and failed" when the A-E
        # verifier was never actually reached.
        if ae_attempted:
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
            if report["a_e_failed"]
            else "source access depth strong label ke liye enough nahi thi"
        )
        report["note"] = (
            f"{report['downgraded']}/{report['checked']} strong dave neeche kiye gaye "
            f"(" + ", ".join(bits) + f") — {strict_reason}."
        )
    return "\n".join(out_lines), report


def merge_reports(strict: Optional[Dict], depth: Optional[Dict]) -> Dict:
    """Merge the two sequential label gates without losing A-E accounting.

    ``enforce_strict_labels`` runs first. A line it turns into UNVERIFIED no
    longer contains a strong label when ``downgrade`` runs, so simply returning
    the second report under-counts real work. Claude's cross-domain benchmark
    caught that audit bug. This integration keeps that fix while preserving the
    stricter A-E counters introduced on this branch.

    The merge is deliberately conservative: strict downgrades are added once;
    checked is the maximum (same original answer, sequential passes), details are
    deduplicated, and A-E counters remain those of the depth/A-E pass rather than
    being invented from the older strict entailment proxy.
    """
    strict = dict(strict or {})
    depth = dict(depth or {})
    out: Dict = {
        "checked": int(depth.get("checked") or 0),
        "downgraded": int(depth.get("downgraded") or 0),
        "to_source_reported": int(depth.get("to_source_reported") or 0),
        "to_unverified": int(depth.get("to_unverified") or 0),
        "a_e_checked": int(depth.get("a_e_checked") or 0),
        "a_e_failed": int(depth.get("a_e_failed") or 0),
        "entailment_blocked": int(depth.get("entailment_blocked") or 0),
        "strict_unverified": 0,
        "details": list(depth.get("details") or []),
        "note": str(depth.get("note") or "").strip(),
    }

    strict_checked = int(strict.get("checked") or 0)
    strict_unverified = int(strict.get("to_unverified") or 0)
    out["checked"] = max(out["checked"], strict_checked)
    out["downgraded"] += strict_unverified
    out["to_unverified"] += strict_unverified
    out["strict_unverified"] = strict_unverified

    seen = set(out["details"])
    for line in strict.get("details") or []:
        detail = f"{line} — poora text mila par strict support check fail hua"
        if detail in seen:
            continue
        if len(out["details"]) >= 8:
            break
        out["details"].append(detail)
        seen.add(detail)

    notes: List[str] = []
    for value in (strict.get("note"), depth.get("note")):
        clean = str(value or "").strip()
        if clean and clean not in notes:
            notes.append(clean)
    out["note"] = " ".join(notes)
    return out


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
