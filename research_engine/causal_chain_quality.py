"""Fail-closed quality gate for explicitly requested causal / second-order chains.

The synthesis prompt asks the model to label each causal arrow, but prompt text is
not enforcement.  A long answer could mention the requested chain once and still
leave individual links unsupported or epistemically ambiguous.  This module adds
a deterministic post-answer audit for questions that explicitly contain an arrow
chain (for example ``biology -> environment -> culture``).

For every requested edge the final answer must:

* represent the same ordered pair of nodes;
* state an epistemic status (ESTABLISHED/EVIDENCE/SOURCE-REPORTED/INFERENCE/
  SPECULATION/UNKNOWN/UNVERIFIED, or an equivalent evidence-supported phrase);
* include a source citation when the edge is presented as ESTABLISHED, EVIDENCE
  or SOURCE-REPORTED.

INFERENCE/SPECULATION/UNKNOWN are valid outcomes: the gate checks honesty and
requested delivery, not whether every causal link is already scientifically
settled.  It never upgrades evidence or confidence and performs no model/network
call.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Sequence, Tuple

_INSTALLED = False
_ARROW_RE = re.compile(r"\s*(?:→|->|⇒|⟶)\s*")
_CIT_RE = re.compile(r"\[S\d{1,3}(?:[^\]]{0,40})?\]", re.IGNORECASE)
_CUE_RE = re.compile(
    r"\b(?:causal(?:\s+model|\s+chain)?|second[- ]order|cause[- ]effect|"
    r"which\s+links?|har\s+arrow|each\s+arrow|chain)\b",
    re.IGNORECASE,
)
_STATUS_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("ESTABLISHED", re.compile(r"(?:\[\s*ESTABLISHED\s*\]|\bestablished\b|\bstrong empirical\b)", re.I)),
    ("EVIDENCE", re.compile(r"(?:\[\s*EVIDENCE\s*\]|\bevidence[- ]supported\b|\bsupported by evidence\b)", re.I)),
    ("SOURCE-REPORTED", re.compile(r"(?:\[\s*SOURCE[- ]REPORTED\s*\]|\bsource[- ]reported\b)", re.I)),
    ("INFERENCE", re.compile(r"(?:\[\s*INFERENCE\s*\]|\binference\b|\binferred\b)", re.I)),
    ("SPECULATION", re.compile(r"(?:\[\s*SPECULATION\s*\]|\bspeculative\b|\bspeculation\b)", re.I)),
    ("UNKNOWN", re.compile(r"(?:\[\s*UNKNOWN\s*\]|\bunknown\b|\buncertain\b|\binsufficient evidence\b)", re.I)),
    ("UNVERIFIED", re.compile(r"(?:\[\s*UNVERIFIED\s*\]|\bunverified\b)", re.I)),
)
_CITATION_REQUIRED = {"ESTABLISHED", "EVIDENCE", "SOURCE-REPORTED"}
_MARKER = "CAUSAL CHAIN GAP"


def _dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _clean_node(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[*_`#>]+", " ", text)
    text = re.sub(r"^[\s\-•\d.)]+", "", text)
    text = re.sub(r"[\s:;,.!?]+$", "", text)
    text = " ".join(text.split()).strip()
    return text[:100]


def _node_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", text)
    return " ".join(text.split())


def extract_requested_chain(question: str) -> List[str]:
    """Return the longest explicit ordered arrow chain in the question."""
    candidates: List[List[str]] = []
    raw_question = str(question or "")
    for raw_line in raw_question.splitlines():
        if len(_ARROW_RE.findall(raw_line)) < 2:
            continue
        parts = [_clean_node(part) for part in _ARROW_RE.split(raw_line)]
        parts = [part for part in parts if 1 < len(_node_key(part)) <= 100]
        if 3 <= len(parts) <= 24:
            candidates.append(parts)
    if not candidates:
        return []
    candidates.sort(key=lambda row: (len(row), sum(len(x) for x in row)), reverse=True)
    return candidates[0]


def requires_causal_chain_audit(question: str) -> bool:
    chain = extract_requested_chain(question)
    if len(chain) < 3:
        return False
    # Four or more explicit nodes are unambiguously a chain request.  Three-node
    # arrows require a causal/chain cue to avoid policing incidental notation.
    return len(chain) >= 4 or bool(_CUE_RE.search(str(question or "")))


def _status(text: str) -> str:
    for label, pattern in _STATUS_PATTERNS:
        if pattern.search(text or ""):
            return label
    return ""


def _edge_window(answer: str, left: str, right: str) -> str:
    """Find a bounded answer window containing the ordered edge."""
    body = str(answer or "")
    folded = unicodedata.normalize("NFKC", body).casefold()
    lkey, rkey = _node_key(left), _node_key(right)
    if not lkey or not rkey:
        return ""

    # Prefer a single line: tables and bullet lists normally encode one edge per
    # row, which prevents a status from a neighbouring edge leaking in.
    for line in body.splitlines():
        line_key = _node_key(line)
        li, ri = line_key.find(lkey), line_key.find(rkey)
        if li >= 0 and ri > li:
            return line[:1200]

    # Fallback for wrapped prose.  Bound the span so labels/citations from a far
    # away paragraph cannot satisfy this edge.
    start = 0
    while True:
        li = folded.find(lkey, start)
        if li < 0:
            return ""
        ri = folded.find(rkey, li + len(lkey))
        if ri >= 0 and ri - li <= 500:
            return body[max(0, li - 120): min(len(body), ri + len(rkey) + 320)]
        start = li + len(lkey)


def audit_causal_chain(question: str, answer: str) -> Dict:
    nodes = extract_requested_chain(question)
    required = requires_causal_chain_audit(question)
    if not required:
        return {
            "required": False,
            "complete": True,
            "nodes": nodes,
            "edges_total": max(0, len(nodes) - 1),
            "edges_complete": max(0, len(nodes) - 1),
            "edges": [],
            "missing_edges": [],
            "note": "no explicit causal/second-order chain contract detected",
        }

    rows: List[Dict] = []
    missing: List[str] = []
    for left, right in zip(nodes, nodes[1:]):
        window = _edge_window(answer, left, right)
        represented = bool(window)
        label = _status(window) if represented else ""
        citation_present = bool(_CIT_RE.search(window)) if represented else False
        citation_required = label in _CITATION_REQUIRED
        complete = represented and bool(label) and (not citation_required or citation_present)
        reasons: List[str] = []
        if not represented:
            reasons.append("edge_not_represented")
        elif not label:
            reasons.append("epistemic_status_missing")
        elif citation_required and not citation_present:
            reasons.append("evidence_label_without_source_citation")
        edge_name = f"{left} → {right}"
        if not complete:
            missing.append(edge_name)
        rows.append({
            "from": left,
            "to": right,
            "edge": edge_name,
            "represented": represented,
            "epistemic_status": label or None,
            "citation_required": citation_required,
            "citation_present": citation_present,
            "complete": complete,
            "reasons": reasons,
        })

    return {
        "required": True,
        "complete": not missing,
        "nodes": nodes,
        "edges_total": len(rows),
        "edges_complete": sum(1 for row in rows if row["complete"]),
        "edges": rows,
        "missing_edges": missing,
        "note": (
            "requested causal chain delivery audit: every arrow needs an explicit "
            "epistemic status; ESTABLISHED/EVIDENCE/SOURCE-REPORTED arrows also "
            "need a citation. This is not itself truth verification."
        ),
    }


def apply_causal_chain_gate(result: Dict) -> Dict:
    """Attach audit and monotonically downgrade a false COMPLETE result."""
    data = dict(result or {})
    question = str(data.get("question") or "")
    answer = str(data.get("answer") or "")
    audit = audit_causal_chain(question, answer)
    coverage = dict(data.get("coverage") or {})
    coverage["causal_chain"] = audit
    data["coverage"] = coverage
    if not audit.get("required") or audit.get("complete") is True:
        return data

    current = str(data.get("status") or "COMPLETE")
    if current == "COMPLETE":
        data["status"] = "PARTIAL"
    missing = list(audit.get("missing_edges") or [])
    sections = _dedupe(list(data.get("missing_sections") or []) + [
        "Causal / second-order chain: " + ", ".join(missing[:4])
    ])
    data["missing_sections"] = sections
    reason = (
        f"Requested causal/second-order chain ke {audit.get('edges_complete', 0)}/"
        f"{audit.get('edges_total', 0)} arrows epistemic-status contract pass karte hain."
    )
    old_reason = str(data.get("status_reason") or "").strip()
    if not old_reason:
        data["status_reason"] = reason
    elif reason not in old_reason:
        data["status_reason"] = old_reason + " | " + reason
    warning = (
        f"{_MARKER}: requested causal chain ke {len(missing)} arrow incomplete hain; "
        "har link ko evidence/inference/speculation/unknown status ke saath dikhana zaroori hai."
    )
    warnings = _dedupe(list(data.get("warnings") or []) + [warning])
    data["warnings"] = warnings
    return data


def install() -> None:
    """Install after the existing stress/semantic quality layers, exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import final_quality_gate as final_mod
    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_causal_chain(result: Dict) -> Dict:
        return apply_causal_chain_gate(original_enforce(result))

    result_mod.enforce = enforce_with_causal_chain

    original_requirements = final_mod.FinalQualityGate._check_requirements

    def causal_requirements(state, data, answer, ledger, spec) -> None:
        original_requirements(state, data, answer, ledger, spec)
        if not bool(getattr(spec, "evidence_first_required", False)):
            return
        audit = audit_causal_chain(str(data.get("question") or ""), answer)
        if not audit.get("required"):
            return
        passed = audit.get("complete") is True
        state.check("causal_chain_per_edge_epistemic_status", passed)
        if passed:
            return
        state.issue(
            "REQUESTED_DELIVERABLE_MISSING",
            "requirement_coverage",
            "critical",
            "Requested causal/second-order chain is missing one or more labelled links.",
            deduction=final_mod.CATEGORY_WEIGHTS["requirement_coverage"],
            hard_cap=40 if str(data.get("status") or "").upper() == "COMPLETE" else 60,
            details={"causal_chain": audit},
        )

    final_mod.FinalQualityGate._check_requirements = staticmethod(causal_requirements)
