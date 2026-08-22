"""Final user-facing presentation quality guard.

The research engine can be technically complex internally, but the final answer
must remain human-first.  This module implements a deterministic last gate that
runs *after* synthesis and before the answer is returned.  It does not invent
research facts: repairs are limited to moving technical junk, simplifying a few
formal-Hindi phrases, and reusing already-produced report text when the opening
answer is too thin.

The audit mirrors the user's A-L presentation checklist.  It is stored for
internal/API diagnostics; it is not dumped into the main answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import EvidencePack

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SOURCE_LINK_RE = re.compile(
    r"\[(S\d+)\]\(https?://[^)\s]+\)",
    re.IGNORECASE,
)
_RAW_LINE_RE = re.compile(
    r"(?:^\s*\[(?:PASS|FAIL)\]\s*|ResourceExhausted|protobuf|google\.rpc|"
    r"grpc\.|Traceback \(most recent call last\)|quota_id|Evidence Pack|"
    r"Connector Status|Retrieval metadata|Gemini pass|internal numeric consistency)",
    re.IGNORECASE,
)
_FORMAL_REPLACEMENTS = (
    ("उपलब्ध साक्ष्यों के आधार पर", "jo evidence mila hai uske basis par"),
    ("उपलब्ध साक्ष्य", "available evidence"),
    ("परिकल्पना", "hypothesis"),
    ("निष्कर्ष", "Final conclusion"),
    ("साक्ष्य", "evidence"),
    ("प्रमाण उपलब्ध है", "evidence milta hai"),
    ("संदेश प्रेषित करें", "message bhejo"),
)
_HYPOTHESIS_REQUIRED = (
    "simple words mein",
    "support karne wali research",
    "against evidence",
    "problem / risk",
    "assumption",
    "test kaise karenge",
    "agar ye sahi hua",
    "agar ye galat hua",
    "current status",
)


@dataclass
class PresentationAudit:
    checks: Dict[str, Optional[bool]] = field(default_factory=dict)
    repairs: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(value is not False for value in self.checks.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": dict(self.checks),
            "repairs": list(self.repairs),
            "failed": list(self.failed),
        }


def _section_spans(text: str) -> List[Tuple[str, int, int]]:
    matches = list(_HEADING_RE.finditer(text or ""))
    spans: List[Tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans.append((match.group(1).strip(), match.start(), end))
    return spans


def _body(text: str, title: str) -> str:
    wanted = title.strip().lower()
    for found, start, end in _section_spans(text):
        if found.strip().lower() == wanted:
            block = text[start:end]
            return block.split("\n", 1)[1].strip() if "\n" in block else ""
    return ""


def _positions(text: str) -> Dict[str, int]:
    return {title: start for title, start, _ in _section_spans(text)}


def _simplify_formal_hindi(text: str) -> Tuple[str, int]:
    out = text
    changed = 0
    for old, new in _FORMAL_REPLACEMENTS:
        if old in out:
            count = out.count(old)
            out = out.replace(old, new)
            changed += count
    return out, changed


def _clean_main_technical_junk(text: str) -> Tuple[str, List[str]]:
    """Move raw diagnostic lines/URLs out of the main explanation, never lose them."""
    marker = text.find("## Sources")
    if marker < 0:
        marker = text.find("## Research quality / technical audit")
    if marker < 0:
        marker = len(text)
    main, tail = text[:marker], text[marker:]
    kept: List[str] = []
    moved: List[str] = []
    for line in main.splitlines():
        stripped = line.strip()
        if stripped and _RAW_LINE_RE.search(stripped):
            moved.append(stripped)
            continue
        # CitationEngine deliberately renders source IDs as clickable Markdown
        # links. They are citations, not raw diagnostic URLs: keep the sentence
        # in the human answer and collapse the target back to the stable [S#]
        # form. The full URL remains available in the Sources section.
        line = _SOURCE_LINK_RE.sub(r"[\1]", line)
        # Detailed URLs belong in Sources. Keep the sentence, remove just the URL.
        if "http://" in line or "https://" in line:
            cleaned = _URL_RE.sub("", line).rstrip()
            if cleaned.strip():
                kept.append(cleaned)
            moved.append(stripped)
            continue
        kept.append(line)
    return "\n".join(kept).rstrip() + ("\n\n" if tail else "") + tail.lstrip(), moved


def _ensure_unknown_section(text: str, pack: EvidencePack) -> Tuple[str, bool]:
    if _body(text, "Kya abhi unknown hai?"):
        return text, False
    insert_at = text.find("## Final conclusion")
    if insert_at < 0:
        return text, False
    unknown: List[str] = []
    if not pack.reasoning_complete:
        unknown.append("AI reasoning ke sab planned passes poore nahi hue, isliye kuch analysis abhi unknown hai.")
    if pack.sources and pack.full_text_read_count < len(pack.sources):
        unknown.append(
            f"{len(pack.sources) - pack.full_text_read_count} source full-text level tak nahi padhe gaye; "
            "unke method/context ka kuch hissa abhi unknown hai."
        )
    if not unknown:
        unknown.append(
            "Available evidence ke bahar kaunse important missing factors bache hain, "
            "is run ne unhe reliably identify nahi kiya; isliye unhe unknown maana gaya hai."
        )
    block = "## Kya abhi unknown hai?\n\n" + "\n\n".join(unknown) + "\n\n"
    return text[:insert_at] + block + text[insert_at:], True


def _strengthen_seedha_from_existing_sections(text: str) -> Tuple[str, bool]:
    """If Seedha jawab is too thin, reuse existing human sections; invent nothing."""
    seedha = _body(text, "Seedha jawab")
    if len(re.sub(r"\s+", " ", seedha)) >= 240:
        return text, False
    spans = _section_spans(text)
    seed_span = next((row for row in spans if row[0].lower() == "seedha jawab"), None)
    if not seed_span:
        return text, False

    pieces: List[str] = [seedha] if seedha else []
    for title in (
        "Research se kya pata chala?",
        "Ye kyun hota hai?",
        "Evidence kya kehta hai?",
        "Iske against kya mila?",
        "Humari Hypotheses",
        "Kya abhi unknown hai?",
        "Final conclusion",
    ):
        body = re.sub(r"\s+", " ", _body(text, title)).strip()
        if not body:
            continue
        # Reuse, do not generate: one compact excerpt per already-written section.
        pieces.append(body[:320] + ("…" if len(body) > 320 else ""))
        if sum(len(part) for part in pieces) >= 900:
            break
    if not pieces:
        return text, False
    replacement = "\n\n".join(pieces)
    title, start, end = seed_span
    old_block = text[start:end]
    new_block = "## Seedha jawab\n\n" + replacement + "\n\n"
    return text[:start] + new_block + text[end:], True


def _append_moved_to_audit(text: str, moved: List[str]) -> str:
    if not moved:
        return text
    audit = text.find("## Research quality / technical audit")
    if audit < 0:
        return text + "\n\n## Research quality / technical audit\n\n"
    block = (
        "\n\n### Technical details jo main answer se neeche move kiye gaye\n"
        + "\n".join(f"- `{line[:280]}`" for line in moved[:10])
    )
    return text.rstrip() + block


class PresentationGuard:
    """Apply safe repairs, then evaluate the A-L user-experience checklist."""

    def enforce(
        self,
        report: str,
        *,
        pack: EvidencePack,
        hypotheses: Optional[List[Dict]] = None,
        status: Optional[Dict] = None,
    ) -> Tuple[str, PresentationAudit]:
        text = report or ""
        audit = PresentationAudit()

        text, formal_changes = _simplify_formal_hindi(text)
        if formal_changes:
            audit.repairs.append(f"{formal_changes} overly-formal Hindi phrase(s) simplified")

        text, moved = _clean_main_technical_junk(text)
        if moved:
            text = _append_moved_to_audit(text, moved)
            audit.repairs.append(f"{len(moved)} technical/raw line(s) moved out of main answer")

        text, added_unknown = _ensure_unknown_section(text, pack)
        if added_unknown:
            audit.repairs.append("missing unknown/limitations section added from existing run state")

        text, strengthened = _strengthen_seedha_from_existing_sections(text)
        if strengthened:
            audit.repairs.append("thin Seedha jawab strengthened only with already-produced report text")

        main_end = text.find("## Sources")
        if main_end < 0:
            main_end = text.find("## Research quality / technical audit")
        if main_end < 0:
            main_end = len(text)
        main = text[:main_end]
        seedha = _body(text, "Seedha jawab")
        positions = _positions(text)
        lower = text.lower()
        main_lower = main.lower()
        hyp_text = _body(text, "Humari Hypotheses").lower()
        has_hypotheses = bool(hypotheses)
        incomplete = (not pack.reasoning_complete) or str((status or {}).get("status") or "").upper() in {
            "RESEARCH INCOMPLETE", "INCOMPLETE", "PARTIAL"
        }

        checks: Dict[str, Optional[bool]] = {
            "A_main_conclusion_understandable": len(re.sub(r"\s+", " ", seedha)) >= 120,
            "B_natural_hinglish": not any(old in main for old, _ in _FORMAL_REPLACEMENTS),
            "C_common_english_words_kept": any(word in main_lower for word in ("research", "evidence", "source", "hypothesis", "result")),
            "D_no_overly_formal_hindi": not any(old in main for old, _ in _FORMAL_REPLACEMENTS),
            "E_hypotheses_explained": (not has_hypotheses) or all(token in hyp_text for token in _HYPOTHESIS_REQUIRED),
            "F_support_and_opposition_explained": (
                ("evidence kya kehta hai" in lower and "iske against kya mila" in lower)
            ),
            "G_fact_inference_hypothesis_distinct": all(token in lower for token in ("fact", "inference", "hypothesis")),
            "H_no_raw_logs_in_main": not bool(_RAW_LINE_RE.search(main)),
            "I_sources_and_audit_last": (
                "Sources" in positions and "Research quality / technical audit" in positions
                and positions["Sources"] < positions["Research quality / technical audit"]
                and all(positions["Sources"] > pos for name, pos in positions.items()
                        if name not in {"Sources", "Research quality / technical audit"})
            ),
            "J_incomplete_run_not_called_verified": (
                (not incomplete)
                or any(token in lower for token in ("research run poora nahi", "run complete nahi", "preliminary", "fully verified final conclusion nahi"))
            ),
            "K_limitations_simple": "kya abhi unknown hai" in lower,
            "L_first_section_gives_useful_picture": len(re.sub(r"\s+", " ", seedha)) >= 240,
        }
        audit.checks = checks
        audit.failed = [name for name, value in checks.items() if value is False]
        return text.strip(), audit
