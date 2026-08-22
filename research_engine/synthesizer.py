"""Integrated human-first synthesizer facade.

``synthesizer_claude.py`` is the exact latest Claude formatter from main,
including claim-check, physics-sanity and hypothesis-quality presentation. This
facade keeps those features and adds ChatGPT's stricter user-facing safeguards:

1. selected-page large-PDF reading is never described as the whole document;
2. full-text ACCESS is never confused with claim verification;
3. the deterministic A-L presentation guard runs before the report is returned;
4. incomplete runs get an explicit opening warning if the model omitted it;
5. if every reasoning provider is unavailable, retrieved evidence is still
   turned into a conservative cited answer by the local deterministic reasoner;
6. source-controlled title/snippet/URL metadata cannot inject report headings,
   bidi controls or non-http clickable schemes into the human-facing report.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .answer_order import section_start
from .models import EvidencePack
from .offline_reasoner import OfflineEvidenceReasoner
from .presentation_guard import PresentationGuard
from .specialist_domains import render_evidence_lane_report
from .synthesizer_claude import *  # noqa: F401,F403 - compatibility exports
from .synthesizer_claude import FinalSynthesizer as _ClaudeFinalSynthesizer


_BIDI = {
    "\u061c", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d",
    "\u202e", "\u2066", "\u2067", "\u2068", "\u2069",
}
_MARKDOWN_INERT = str.maketrans({
    "*": "∗", "_": "＿", "[": "［", "]": "］", "<": "‹", ">": "›", "`": "ˋ",
})


def _safe_source_display(value: object, limit: int = 500) -> str:
    """Flatten hostile source metadata into inert, bounded display text."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    chars: List[str] = []
    for ch in text:
        if ch in _BIDI or ch == "\x00":
            continue
        if unicodedata.category(ch) == "Cc" and ch not in {"\n", "\r", "\t"}:
            continue
        chars.append(ch)
    text = re.sub(r"\s+", " ", "".join(chars)).strip().translate(_MARKDOWN_INERT)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _safe_source_url(value: object) -> str:
    """Only render external source URLs as URLs when scheme is http(s)."""
    raw = re.sub(r"[\x00-\x20]+", "", str(value or "").strip())
    if not raw or len(raw) > 2048:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


class FinalSynthesizer(_ClaudeFinalSynthesizer):
    """Claude latest formatter + final truth/presentation guardrails."""

    # §9 — access depth ka vocabulary ab sirf `models.ACCESS_DEPTH_LABELS` mein
    # rehta hai (paanch allowed label). Pehle yahan apni alag wording thi
    # ("FULL-TEXT VERIFIED ACCESS", "PATENT CLAIMS REVIEWED") — do jagah do
    # bhasha se report aur claim-check ek doosre se ulta bolne lagte the, aur
    # "VERIFIED" shabd access ke saath lagna hi §8 ka rule todta hai. Iska
    # matlab yahan koi feature nahi gaya: patent ke claims ab
    # `RELEVANT SECTIONS REVIEWED` bante hain (models.py mein tay), aur patent
    # ke "legal dawa, proof nahi" wali baat neeche `_KIND_WORDS` + patent gates
    # se aati hai.
    _KIND_WORDS = {
        **_ClaudeFinalSynthesizer._KIND_WORDS,
        "patent": "patent document (legal filing; scientific proof nahi)",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.presentation_guard = PresentationGuard()
        self.offline_reasoner = OfflineEvidenceReasoner()
        self.last_presentation_check: Dict = {}

    def extractive_summary(self, question: str, pack: EvidencePack) -> str:
        """No-model fallback used by the orchestrator when every AI pass is empty.

        The old fallback was a thin extract. This replacement remains fully
        deterministic/₹0 but ranks actual retrieved evidence, keeps [S#]
        provenance, avoids invented causal/hypothesis claims and produces useful
        human-readable sections so quota exhaustion does not turn into a blank
        answer or server error.
        """
        summary = self.offline_reasoner.synthesize(question, pack)
        honesty = (
            "Reasoning model is run mein nahi chala; ye deterministic, "
            "retrieved-evidence-only fallback hai."
        )
        if summary.startswith("## Seedha jawab\n"):
            return summary.replace("## Seedha jawab\n", f"## Seedha jawab\n{honesty}\n\n", 1)
        return f"## Seedha jawab\n{honesty}\n\n{summary}"

    @staticmethod
    def _is_partial_large_source(source) -> bool:
        total = int(getattr(source, "pages_total", 0) or 0)
        read = int(getattr(source, "pages_read", 0) or 0)
        return total > 0 and read > 0 and read < total

    @staticmethod
    def _access_block(coverage: Dict, pack: Optional[EvidencePack]) -> str:
        levels = (coverage or {}).get("read_levels") or {}
        full = int(levels.get("full_text", 0) or 0)
        abstract = int(levels.get("abstract", 0) or 0)
        snippet = int(levels.get("snippet", 0) or 0)
        meta = int(levels.get("metadata", 0) or 0)
        claims = int(levels.get("claims", 0) or 0)
        partial = [
            s for s in (getattr(pack, "sources", None) or [])
            if FinalSynthesizer._is_partial_large_source(s)
        ]
        full_whole = max(0, full - len(partial))

        if not (full or abstract or snippet or meta or claims):
            return (
                "**Kitna gehra padha gaya:** iska data available nahi hai, isliye "
                "source-access depth ko verify nahi kiya ja saka."
            )

        total = full + abstract + snippet + meta + claims
        lines = [
            "**Kitna gehra padha gaya (access depth confidence ko affect karti hai, "
            "lekin claim verification alag A-E check se hoti hai) — "
            f"kul {total} sources par:**"
        ]
        if full_whole:
            lines.append(
                f"- {full_whole}/{total} source ka POORA text mila aur process hua. "
                "Isse strong checking possible hoti hai, lekin sirf full text milne "
                "se koi claim automatically verified nahi maana jaata."
            )
        if partial:
            lines.append(
                f"- {len(partial)}/{total} badi PDF/document mein poora document ek saath nahi "
                "padha gaya; sawal se relevant pages page-by-page select karke process hue."
            )
            for source in partial[:4]:
                scope = _safe_source_display(getattr(source, "read_note", ""), 500)
                lines.append(
                    f"  - [{source.source_id}] {int(source.pages_read)}/{int(source.pages_total)} "
                    f"pages process hue. {scope}"
                )
        if abstract:
            lines.append(
                f"- {abstract}/{total} source ka sirf abstract mila — paper ka summary, poora "
                "method/result context nahi. Isse strong fact automatically nahi banta."
            )
        if claims:
            lines.append(
                f"- {claims}/{total} patent ke claims process hue. Ye invention par "
                "LEGAL dawe hain; experimental result ya scientific verification nahi."
            )
        if snippet:
            lines.append(
                f"- {snippet}/{total} source se sirf ek chhota snippet mila. Ye weak/supporting "
                "signal ho sakta hai, verification nahi."
            )
        if meta:
            lines.append(
                f"- {meta}/{total} source ka sirf title/metadata mila — content-level claim "
                "verify nahi ki ja sakti."
            )
        if not full:
            # §9 — is line mein jaan-boojh kar "full-text verified" shabd nahi
            # likha jaata, chahe wo negation mein ho. Access-depth detector
            # (bilkul theek) us phrase ko dhoondta hai, aur apni hi imaandaar
            # line se audit mein "1 overclaim" ki jhoothi ginti ban rahi thi.
            lines.append(
                "- Kisi source ka full-text-level access nahi mila, isliye strong "
                "claims ke liye 'poora text padh kar check kiya' wala dava bhi "
                "allowed nahi hai."
            )
        return "\n".join(lines)

    def _sources_section(self, pack: EvidencePack, honesty: Optional[Dict] = None) -> str:
        if not pack.sources:
            return (
                "Is run mein ek bhi source retrieve nahi hua. Isliye upar likhi koi bhi "
                "baat kisi source se verify nahi hui hai."
            )

        cited_raw = (honesty or {}).get("cited") or []
        cited_ids = {
            c.get("source_id") if isinstance(c, dict) else str(c)
            for c in cited_raw
        }
        blocks: List[str] = []

        for s in pack.sources:
            safe_url = _safe_source_url(s.url)
            title = _safe_source_display(s.title or safe_url or "naam nahi mila", 500)
            safe_id = re.sub(r"[^A-Za-z0-9._-]", "", str(s.source_id or ""))[:40] or "?"
            head = f"**[{safe_id}] {title}**"
            if safe_url:
                head += f"  \n{safe_url}"
            about: List[str] = [_safe_source_display(self._KIND_WORDS.get(
                getattr(s.source_type, "value", str(s.source_type)),
                getattr(s.source_type, "value", "source"),
            ), 120)]
            if s.year:
                about.append(f"saal {s.year}")
            if s.publisher or s.venue:
                about.append(_safe_source_display(s.publisher or s.venue, 300))
            if s.peer_reviewed is True:
                about.append("peer-reviewed")
            lines = [head, f"- Ye kya hai: {', '.join(x for x in about if x)}."]
            if getattr(s, "is_patent", False):
                lines.append(
                    "- Evidence rule: patent ke claims legal dawe hain; inhe paper, "
                    "experiment ya independently verified scientific result nahi maana gaya."
                )

            took = _safe_source_display(s.snippet, 220)
            if took:
                lines.append("- Isse kya liya gaya: " + took)
            else:
                lines.append("- Isse kya liya gaya: kuch nahi — content mila hi nahi.")

            # §9 — ek hi jagah se label: partial-page reading `RELEVANT SECTIONS
            # REVIEWED` banti hai (poora document padha gaya aisa dava nahi),
            # patent ke claims bhi wahi, aur "FULL TEXT ACCESSED" sirf access
            # kehta hai — verification ka dava kabhi nahi.
            access = s.access_depth_note()
            lines.append(f"- Kitna padha gaya: {access}.")
            if getattr(s, "read_note", ""):
                lines.append(f"- Reading scope: {_safe_source_display(s.read_note, 500)}")

            rel = float(getattr(s, "relevance_score", 0.0) or 0.0)
            rel_word = (
                "sawal se seedha juda hua" if rel >= 0.6 else
                "thoda sa juda hua" if rel >= 0.3 else
                "kam juda hua — ise halke se lein"
            )
            lines.append(f"- Sawal se kitna juda hai: {rel_word} (score {rel:.2f}).")
            if s.retracted is True:
                lines.append(
                    "- ⚠️ Is kaam par retraction/withdrawal ka signal hai — ise normal "
                    "evidence ki tarah nahi lena chahiye."
                )
            lines.append(
                "- Jawab mein use hua: "
                + ("haan, cite kiya gaya hai." if s.source_id in cited_ids
                   else "nahi, sirf background mein raha.")
            )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    @staticmethod
    def _repair_incomplete_honesty(report: str) -> str:
        """Add a truthful opening warning only when A-L check J says it is missing."""
        marker = "## Seedha jawab"
        pos = (report or "").find(marker)
        if pos < 0:
            return report
        insert = pos + len(marker)
        warning = (
            "\n\n**Important:** Ye research run complete nahi hua. Neeche diya gaya result "
            "preliminary hai, fully verified final conclusion nahi. Jo passes/sources "
            "complete nahi hue unka reason technical audit mein neeche diya gaya hai."
        )
        return report[:insert] + warning + report[insert:]

    def assemble(self, *args, **kwargs) -> str:
        """Assemble with Claude features, then enforce the user's A-L presentation gate."""
        specialist_report = kwargs.pop("specialist_report", None)
        report = super().assemble(*args, **kwargs)
        specialist_block = render_evidence_lane_report(specialist_report or {})
        if specialist_block:
            # System-owned deterministic boundary.  It sits immediately before
            # app-generated hypotheses, so official/traditional/allegation lanes
            # cannot visually merge into the hypothesis section.  Sources and
            # the technical audit remain the final two sections.
            # §12 (2026-08-22) — anchor ab canonical key se milta hai. Pehle
            # yahan literal `"## Humari Hypotheses"` dhoonda jaata tha; heading
            # `APP ORIGINAL RESEARCH LAB` ho jaane ke baad wo find() hamesha -1
            # deta aur specialist block chup-chaap Sources se pehle (ya report ke
            # aakhir mein) chala jaata tha. Purana naam fallback mein rakha hai,
            # taaki legacy synthesizer se bani report par bhi kaam kare.
            anchor = section_start(report, "original_lab")
            if anchor < 0:
                anchor = report.find("## Humari Hypotheses")
            if anchor < 0:
                anchor = section_start(report, "audit")
            if anchor < 0:
                anchor = section_start(report, "sources")
            if anchor < 0:
                report = f"{report.rstrip()}\n\n{specialist_block}".strip()
            else:
                report = (
                    report[:anchor].rstrip()
                    + "\n\n"
                    + specialist_block
                    + "\n\n"
                    + report[anchor:].lstrip()
                )
        pack = kwargs.get("pack")
        if pack is None and len(args) > 1:
            pack = args[1]
        if pack is None:
            self.last_presentation_check = {
                "passed": False,
                "failed": ["presentation_guard_missing_evidence_pack"],
                "checks": {},
                "repairs": [],
            }
            return report

        hypotheses = kwargs.get("hypotheses")
        if hypotheses is None and len(args) > 5:
            hypotheses = args[5]
        status = kwargs.get("status")
        if status is None and len(args) > 19:
            status = args[19]

        guarded, audit = self.presentation_guard.enforce(
            report,
            pack=pack,
            hypotheses=hypotheses or [],
            status=status or {},
        )
        first_repairs = list(audit.repairs)

        if audit.checks.get("J_incomplete_run_not_called_verified") is False:
            guarded = self._repair_incomplete_honesty(guarded)
            guarded, audit = self.presentation_guard.enforce(
                guarded,
                pack=pack,
                hypotheses=hypotheses or [],
                status=status or {},
            )
            audit.repairs = first_repairs + [
                "incomplete-run warning inserted into Seedha jawab"
            ] + [r for r in audit.repairs if r not in first_repairs]
            audit.failed = [name for name, value in audit.checks.items() if value is False]

        self.last_presentation_check = audit.to_dict()
        return guarded
