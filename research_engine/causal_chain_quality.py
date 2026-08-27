"""Fail-closed quality gate for explicitly requested causal / second-order chains.

The synthesis prompt asks the model to label each causal arrow, but prompt text is
not enforcement. A long answer could mention the requested chain once and still
leave individual links unsupported or epistemically ambiguous. This module adds
a deterministic post-answer audit for questions that explicitly request a causal
or second-order arrow chain (for example ``biology -> environment -> culture``).

For every requested edge the final answer must:

* represent the same ordered pair of nodes;
* state an epistemic status (ESTABLISHED/EVIDENCE/SOURCE-REPORTED/INFERENCE/
  SPECULATION/UNKNOWN/UNVERIFIED, or an equivalent evidence-supported phrase);
* include a source citation when the edge is presented as ESTABLISHED, EVIDENCE
  or SOURCE-REPORTED.

INFERENCE/SPECULATION/UNKNOWN are valid outcomes: the gate checks honesty and
requested delivery, not whether every causal link is already scientifically
settled. It never upgrades evidence or confidence and performs no model/network
call.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Tuple

_INSTALLED = False
_ARROW_RE = re.compile(r"\s*(?:→|->|⇒|⟶)\s*")
_ARROW_TOKEN_RE = re.compile(r"(?:→|->|⇒|⟶)")
_CIT_RE = re.compile(r"\[S\d{1,3}(?:[^\]]{0,40})?\]", re.IGNORECASE)
_CUE_RE = re.compile(
    r"\b(?:causal(?:\s+model|\s+chain)?|second[- ]order|cause[- ]effect|"
    r"which\s+links?|har\s+arrow|each\s+arrow|causal\s+links?|causal\s+arrows?|"
    r"chain\s+of\s+causation)\b",
    re.IGNORECASE,
)
# Bracket labels are authoritative within an edge window.  Check them before
# prose so a line like ``[SPECULATION] ... not established`` cannot be promoted
# to ESTABLISHED merely because it contains the word "established".
_EXPLICIT_STATUS_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("ESTABLISHED", re.compile(r"\[\s*ESTABLISHED\s*\]", re.I)),
    ("EVIDENCE", re.compile(r"\[\s*EVIDENCE\s*\]", re.I)),
    ("SOURCE-REPORTED", re.compile(r"\[\s*SOURCE[- ]REPORTED\s*\]", re.I)),
    ("INFERENCE", re.compile(r"\[\s*INFERENCE\s*\]", re.I)),
    ("SPECULATION", re.compile(r"\[\s*SPECULATION\s*\]", re.I)),
    ("UNKNOWN", re.compile(r"\[\s*UNKNOWN\s*\]", re.I)),
    ("UNVERIFIED", re.compile(r"\[\s*UNVERIFIED\s*\]", re.I)),
)
_PROSE_STATUS_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("EVIDENCE", re.compile(r"\bevidence[- ]supported\b|\bsupported by evidence\b", re.I)),
    ("SOURCE-REPORTED", re.compile(r"\bsource[- ]reported\b", re.I)),
    ("INFERENCE", re.compile(r"\binference\b|\binferred\b", re.I)),
    ("SPECULATION", re.compile(r"\bspeculative\b|\bspeculation\b", re.I)),
    ("UNKNOWN", re.compile(r"\bunknown\b|\buncertain\b|\binsufficient evidence\b", re.I)),
    ("UNVERIFIED", re.compile(r"\bunverified\b", re.I)),
    # ESTABLISHED is deliberately last: negative phrases such as "not
    # established" are handled below and cannot silently upgrade an edge.
    ("ESTABLISHED", re.compile(r"\bestablished\b|\bstrong empirical\b", re.I)),
)
_NEGATED_ESTABLISHED_RE = re.compile(
    r"\b(?:not|isn['’]?t|wasn['’]?t|never|no)\s+(?:yet\s+)?established\b|"
    r"\bestablished\s+(?:evidence\s+)?(?:is\s+)?(?:absent|lacking|insufficient)\b",
    re.I,
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


def _clean_chain_parts(raw_line: str) -> List[str]:
    """Strip prose prefixes/suffixes without changing the ordered node names."""
    raw_parts = list(_ARROW_RE.split(raw_line))
    if not raw_parts:
        return []
    cleaned: List[str] = []
    for index, raw in enumerate(raw_parts):
        value = raw
        # Common natural-language form: "Causal chain: exposure → habit → outcome".
        # The cue before ':' describes the contract, not the first node.
        if index == 0 and ":" in value:
            prefix, suffix = value.rsplit(":", 1)
            if suffix.strip() and _CUE_RE.search(prefix):
                value = suffix
        # Common trailing form: "... → outcome: explain uncertainty". Text after
        # the colon belongs to the instruction, not the last node.
        if index == len(raw_parts) - 1 and ":" in value:
            node, suffix = value.split(":", 1)
            if node.strip() and len(_node_key(node)) >= 2 and len(suffix.split()) >= 2:
                value = node
        node = _clean_node(value)
        if 1 < len(_node_key(node)) <= 100:
            cleaned.append(node)
    return cleaned


def extract_requested_chain(question: str) -> List[str]:
    """Return the longest explicit ordered arrow chain in the question."""
    candidates: List[List[str]] = []
    raw_question = str(question or "")
    for raw_line in raw_question.splitlines():
        if len(_ARROW_RE.findall(raw_line)) < 2:
            continue
        parts = _clean_chain_parts(raw_line)
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
    # Arrow notation is also used for software/data pipelines and workflows.
    # Require an explicit causal/second-order/link-evidence cue instead of
    # policing every multi-node arrow diagram as a scientific causal claim.
    return bool(_CUE_RE.search(str(question or "")))


def _status(text: str) -> str:
    body = str(text or "")
    for label, pattern in _EXPLICIT_STATUS_PATTERNS:
        if pattern.search(body):
            return label
    for label, pattern in _PROSE_STATUS_PATTERNS:
        if not pattern.search(body):
            continue
        if label == "ESTABLISHED" and _NEGATED_ESTABLISHED_RE.search(body):
            continue
        return label
    return ""


def _edge_window(answer: str, left: str, right: str) -> str:
    """Find a bounded answer window containing the explicit ordered edge."""
    body = str(answer or "")
    lkey, rkey = _node_key(left), _node_key(right)
    if not lkey or not rkey:
        return ""

    # Prefer a single line: tables and bullet lists normally encode one edge per
    # row, which prevents a status from a neighbouring edge leaking in. Requiring
    # an arrow token between the nodes also avoids matching two names that merely
    # occur in the same sentence for another reason.
    for line in body.splitlines():
        line_key = _node_key(line)
        li, ri = line_key.find(lkey), line_key.find(rkey)
        if li < 0 or ri <= li:
            continue
        # Work on the raw line because normalization removes the arrow symbol.
        left_raw = re.search(re.escape(str(left)), line, re.I)
        if left_raw is None:
            # Case/Unicode normalization can defeat literal matching; the ordered
            # key test above is still useful, but require at least one arrow on
            # the line to preserve the explicit-edge contract.
            if _ARROW_TOKEN_RE.search(line):
                return line[:1200]
            continue
        right_raw = re.search(re.escape(str(right)), line[left_raw.end():], re.I)
        if right_raw is None:
            continue
        between = line[left_raw.end(): left_raw.end() + right_raw.start()]
        if _ARROW_TOKEN_RE.search(between):
            return line[:1200]

    # Wrapped Markdown may split one edge across physical lines. Permit that
    # only inside the same paragraph and only when an arrow token is actually
    # between the two nodes. Never bridge into a neighbouring bullet/heading;
    # that was the bug that made a missing environment→culture edge look present.
    for paragraph in re.split(r"\n\s*\n", body):
        if not paragraph.strip() or re.search(r"\n\s*(?:[-*+]\s+|#{1,6}\s+)", paragraph):
            continue
        pkey = _node_key(paragraph)
        li, ri = pkey.find(lkey), pkey.find(rkey)
        if li < 0 or ri <= li:
            continue
        left_raw = re.search(re.escape(str(left)), paragraph, re.I)
        if left_raw is None:
            continue
        right_raw = re.search(re.escape(str(right)), paragraph[left_raw.end():], re.I)
        if right_raw is None:
            continue
        between = paragraph[left_raw.end(): left_raw.end() + right_raw.start()]
        if _ARROW_TOKEN_RE.search(between):
            return paragraph[:1600]
    return ""


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
            "need a citation. Existing claim-verification remains authoritative "
            "for whether that citation actually supports the claim."
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
