"""Deterministic coverage plan for very long, explicitly structured questions.

The research engine already keeps answers human-first and simple, but a second
problem appears with prompts that contain many numbered domains/chapters: an LLM
can understand the prompt and still accidentally skip one item.  This module
extracts only the user's own high-level Markdown outline and turns it into a
small synthesis checklist.  It does not invent topics, evidence, claims or
citations.

Important boundary: the outline is a *delivery contract*, not evidence.  Missing
research for an item must be reported as unknown/insufficient rather than filled
with model knowledge or speculation.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Dict, List, Mapping, Sequence

_MAX_ITEMS = 24
_MAX_TITLE_CHARS = 120

# High-level numbered headings such as ``### 1. Consciousness...``.  A user may
# choose ##, ### or ####; deeper bullet lists are intentionally not promoted to
# top-level deliverables because doing so can create hundreds of fake sections.
_NUMBERED_HEADING_RE = re.compile(
    r"^[ \t]{0,3}#{2,4}[ \t]+(\d{1,2})[.)][ \t]+(.+?)[ \t]*$",
    re.MULTILINE,
)
_ANY_HEADING_RE = re.compile(
    r"^[ \t]{0,3}#{2,4}[ \t]+(.+?)[ \t]*$",
    re.MULTILINE,
)

# These are structural deliverables rather than ordinary prose headings.  They
# are matched semantically/conservatively so the exact question can use case or
# punctuation variations without a static topic list.
_SPECIAL_HEADING_KEYS = (
    "final challenge",
    "mandatory evidence standard",
    "ultimate question",
)

_MARKDOWN_RE = re.compile(r"[*_`~]+")
_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9\u0900-\u097f]+", re.UNICODE)
_STOP = {
    "the", "and", "or", "of", "a", "an", "to", "in", "for", "with", "on",
    "ka", "ki", "ke", "aur", "ya", "me", "mein", "par", "ko", "se",
    "problem", "question", "section", "part",
}


def _clean_title(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _MARKDOWN_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip(" #\t.-:;|")
    if len(text) > _MAX_TITLE_CHARS:
        text = text[:_MAX_TITLE_CHARS].rsplit(" ", 1)[0].strip()
    return text


def _key(value: object) -> str:
    return _clean_title(value).casefold()


def extract_outline(question: str, limit: int = _MAX_ITEMS) -> List[Dict]:
    """Return the user's explicit high-level answer outline, in source order.

    Numbered headings are primary.  Special unnumbered deliverables (Final
    Challenge / Mandatory Evidence Standard / Ultimate Question) are included
    when present.  Ordinary prose, bullets and model-inferred topics are not.
    """
    text = str(question or "")
    found: List[tuple[int, Dict]] = []
    seen = set()

    for match in _NUMBERED_HEADING_RE.finditer(text):
        number = int(match.group(1))
        title = _clean_title(match.group(2))
        if not title:
            continue
        ident = f"number:{number}:{title.casefold()}"
        if ident in seen:
            continue
        seen.add(ident)
        found.append((match.start(), {
            "id": f"section_{number}",
            "number": number,
            "title": title,
            "label": f"{number}. {title}",
            "source": "numbered_markdown_heading",
        }))

    numbered_spans = {
        _key(match.group(2)) for match in _NUMBERED_HEADING_RE.finditer(text)
    }
    for match in _ANY_HEADING_RE.finditer(text):
        raw = _clean_title(match.group(1))
        low = raw.casefold()
        # A numbered heading is already represented above.
        if re.match(r"^\d{1,2}[.)]\s+", raw) or low in numbered_spans:
            continue
        canonical = next((name for name in _SPECIAL_HEADING_KEYS if name in low), "")
        if not canonical:
            continue
        ident = f"special:{canonical}"
        if ident in seen:
            continue
        seen.add(ident)
        found.append((match.start(), {
            "id": canonical.replace(" ", "_"),
            "number": None,
            "title": raw,
            "label": raw,
            "source": "explicit_special_heading",
        }))

    found.sort(key=lambda row: row[0])
    return [item for _, item in found[: max(1, min(int(limit or 0), _MAX_ITEMS))]]


def requires_structured_coverage(question: str) -> bool:
    """Only activate for genuinely multi-part prompts, not normal questions."""
    outline = extract_outline(question)
    numbered = [item for item in outline if item.get("number") is not None]
    return len(numbered) >= 4


def prompt_rule(question: str) -> str:
    """Synthesis rule that makes a long user outline hard to silently skip."""
    if not requires_structured_coverage(question):
        return ""
    outline = extract_outline(question)
    lines = [
        "# LONG STRUCTURED QUESTION — FULL COVERAGE CONTRACT",
        "- User ne ek bada multi-part sawaal diya hai. Neeche USER KE KHUD KE high-level parts hain; inme se koi part chup-chaap skip mat karo.",
        "- Har item ko answer mein kam se kam ek baar EXACT bold label se mark karo, jaise `**1. Consciousness, Self and Inner Reality**`. `##`/`###` mat lagao, kyunki top-level report headings system control karta hai.",
        "- Har item ke neeche simple bhasha mein: (a) main answer, (b) kyun/mechanism, (c) strongest evidence, (d) strongest competing explanation ya limitation, aur (e) iska practical/overall matlab batao — jitna us item par relevant ho.",
        "- Evidence kam ho to item ko hatao MAT. Seedha likho `is part par evidence insufficient/unknown hai` aur batao kya missing hai.",
        "- Do related items ko jod sakte ho, lekin dono bold labels aur dono ke distinct asks clearly cover hone chahiye. Ek item ka answer doosre ka substitute nahi hai.",
        "- Pehle overall seedha map do, phir domain-by-domain samjhao, aur final conclusion mein sabko ek causal model mein jodo. Repetition kam rakho, coverage nahi.",
        "- Ye checklist evidence nahi hai; factual claim ko normal citation/evidence rules hi pass karne hain.",
        "",
        "USER OUTLINE (mandatory coverage):",
    ]
    for item in outline:
        lines.append(f"- **{item['label']}**")
    return "\n".join(lines)


def _content_words(value: str) -> List[str]:
    words = [w.casefold() for w in _WORD_RE.findall(_clean_title(value))]
    return [w for w in words if len(w) >= 3 and w not in _STOP]


def coverage(question: str, answer: str) -> Dict:
    """Conservative, zero-model audit of whether outline labels were surfaced.

    Exact labels are preferred.  A fallback content-word match is allowed so
    punctuation/number formatting cannot create a false miss.  This audit does
    *not* judge whether the scientific explanation is correct; claim-level
    evidence gates do that separately.
    """
    outline = extract_outline(question)
    body = unicodedata.normalize("NFKC", str(answer or "")).casefold()
    covered: List[str] = []
    missing: List[str] = []
    for item in outline:
        label = _clean_title(item.get("label")).casefold()
        title = _clean_title(item.get("title")).casefold()
        exact = bool(label and label in body) or bool(title and title in body)
        words = _content_words(str(item.get("title") or ""))
        fallback = len(words) >= 2 and all(
            re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", body)
            for word in words[:6]
        )
        target = str(item.get("label") or item.get("title") or "")
        (covered if (exact or fallback) else missing).append(target)
    required = requires_structured_coverage(question)
    return {
        "required": required,
        "items_total": len(outline),
        "items_covered": len(covered),
        "complete": (not required) or not missing,
        "covered": covered,
        "missing": missing,
        "note": "outline delivery audit only; not evidence/truth verification",
    }


def _as_mapping(value: Any) -> Dict:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _append_unique(values: Any, extra: Sequence[str]) -> List[str]:
    out: List[str] = []
    for item in list(values or []) + list(extra or []):
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _partial_reason(audit: Mapping[str, Any]) -> str:
    total = int(audit.get("items_total") or 0)
    covered = int(audit.get("items_covered") or 0)
    missing = [str(x) for x in (audit.get("missing") or []) if str(x).strip()]
    reason = (
        f"Long structured question ke {covered}/{total} required high-level parts "
        "cover hue"
    )
    if missing:
        reason += "; missing: " + ", ".join(missing[:6])
        if len(missing) > 6:
            reason += f" (+{len(missing) - 6} aur)"
    return reason + "."


def _merge_requested_ledger(response: Dict, audit: Mapping[str, Any], reason: str) -> None:
    ledger = _as_mapping(response.get("requested_ledger"))
    if not ledger:
        ledger = {"any_requested": True, "items": [], "unmet": [], "lines": [], "banner": ""}
    item = {
        "what": "Long structured question outline coverage",
        "got": f"{int(audit.get('items_covered') or 0)}/{int(audit.get('items_total') or 0)}",
        "ok": False,
        "why": reason,
    }
    items = [dict(x) for x in (ledger.get("items") or []) if isinstance(x, Mapping)]
    items = [x for x in items if x.get("what") != item["what"]]
    items.append(item)
    unmet = [dict(x) for x in (ledger.get("unmet") or []) if isinstance(x, Mapping)]
    unmet = [x for x in unmet if x.get("what") != item["what"]]
    unmet.append(item)
    ledger["any_requested"] = True
    ledger["items"] = items
    ledger["unmet"] = unmet
    response["requested_ledger"] = ledger


def _merge_contract_ledger(response: Dict, audit: Mapping[str, Any], reason: str) -> None:
    ledger = _as_mapping(response.get("contract_ledger"))
    if not ledger:
        return
    item = {
        "key": "structured_outline",
        "what": "User ke high-level structured answer parts",
        "got": f"{int(audit.get('items_covered') or 0)}/{int(audit.get('items_total') or 0)}",
        "ok": False,
        "unknown": False,
        "mandatory": True,
        "why": reason,
    }
    items = [dict(x) for x in (ledger.get("items") or []) if isinstance(x, Mapping)]
    items = [x for x in items if x.get("key") != "structured_outline"]
    items.append(item)
    failed = [dict(x) for x in (ledger.get("failed") or []) if isinstance(x, Mapping)]
    failed = [x for x in failed if x.get("key") != "structured_outline"]
    failed.append(item)
    mandatory = [dict(x) for x in (ledger.get("mandatory_missing") or [])
                 if isinstance(x, Mapping)]
    mandatory = [x for x in mandatory if x.get("key") != "structured_outline"]
    mandatory.append(item)
    ledger["items"] = items
    ledger["failed"] = failed
    ledger["mandatory_missing"] = mandatory
    ledger["answer_complete"] = False
    ledger["verified_allowed"] = False
    if str(ledger.get("result_state") or "").upper() != "INSUFFICIENT_EVIDENCE":
        ledger["result_state"] = "PARTIAL"
    response["contract_ledger"] = ledger


def _merge_research_state(response: Dict, reason: str) -> None:
    state = _as_mapping(response.get("research_state"))
    if not state:
        return
    if str(state.get("answer_state") or "").upper() == "COMPLETE":
        state["answer_state"] = "PARTIAL"
    reasons = _as_mapping(state.get("reasons"))
    reasons["answer_state"] = reason
    state["reasons"] = reasons
    explain = _as_mapping(state.get("explain"))
    if explain:
        explain["answer_state"] = "kuch zaroori hissa nahi ban paaya"
        state["explain"] = explain
    state["verified_allowed"] = False
    response["research_state"] = state


def enforce_result(result: Any) -> Dict:
    """Fail closed at the result boundary when a long answer skips user parts.

    This changes *answer completeness only*.  It never upgrades/downgrades the
    scientific evidence state, never invents missing content and never turns the
    outline audit into claim verification.  Repeated calls are idempotent.
    """
    response = copy.deepcopy(_as_mapping(result))
    if not response:
        return response
    question = str(response.get("question") or "")
    answer = str(response.get("answer") or "")
    try:
        audit = coverage(question, answer)
    except Exception:
        # The detector is pure/deterministic.  If it ever fails after a prompt
        # clearly activated structured mode, silence would be fail-open.  Keep
        # the error private and conservatively mark delivery as incomplete.
        if not requires_structured_coverage(question):
            return response
        audit = {
            "required": True,
            "items_total": len(extract_outline(question)),
            "items_covered": 0,
            "complete": False,
            "covered": [],
            "missing": [],
            "audit_error": True,
            "note": "outline delivery audit failed closed; not evidence/truth verification",
        }

    if not audit.get("required"):
        return response

    coverage_map = _as_mapping(response.get("coverage"))
    coverage_map["structured_answer"] = dict(audit)
    response["coverage"] = coverage_map
    if audit.get("complete") is True:
        return response

    reason = _partial_reason(audit)
    if audit.get("audit_error"):
        reason = "Long structured answer ka mandatory coverage audit complete nahi ho saka; result ko complete nahi maana gaya."

    missing = [str(x) for x in (audit.get("missing") or []) if str(x).strip()]
    if audit.get("audit_error") and not missing:
        missing = ["Structured answer coverage audit"]
    response["missing_sections"] = _append_unique(response.get("missing_sections"), missing)

    warning = "Structured answer incomplete: " + reason
    response["warnings"] = _append_unique(response.get("warnings"), [warning])

    original_status = str(response.get("status") or "").strip().upper()
    if original_status == "COMPLETE":
        response["status"] = "PARTIAL"
        response["status_reason"] = reason
        marker = "**PARTIAL — STRUCTURED COVERAGE**"
        if marker not in answer:
            total = int(audit.get("items_total") or 0)
            covered_count = int(audit.get("items_covered") or 0)
            banner = (
                f"> ⚠️ {marker}\n"
                f"> Long structured question ke {covered_count}/{total} required "
                "high-level parts cover hue. Kuch requested parts missing hain; "
                "`missing_sections`/coverage audit dekhein. Is result ko full answer "
                "na maanein.\n\n"
            )
            response["answer"] = banner + answer
    elif original_status == "PARTIAL" and not str(response.get("status_reason") or "").strip():
        response["status_reason"] = reason
    # RESEARCH INCOMPLETE / FAILED ko kabhi less-severe PARTIAL mein upgrade mat karo.

    _merge_requested_ledger(response, audit, reason)
    _merge_contract_ledger(response, audit, reason)
    _merge_research_state(response, reason)
    response["structured_answer_enforced"] = True
    return response


__all__ = [
    "coverage",
    "enforce_result",
    "extract_outline",
    "prompt_rule",
    "requires_structured_coverage",
]
