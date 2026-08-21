"""Truthful presentation facade for the human-first research report.

The large formatting implementation remains in ``synthesizer_legacy.py``. This
facade tightens source-access wording so a downloaded large PDF with only
selected relevant pages processed is never presented as "poora document padha".
It also separates *source access depth* from *claim verification*: full-text
access alone never proves that a claim is supported.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .models import EvidencePack
from .synthesizer_legacy import *  # noqa: F401,F403 - compatibility exports
from .synthesizer_legacy import FinalSynthesizer as _LegacyFinalSynthesizer


class FinalSynthesizer(_LegacyFinalSynthesizer):
    """Legacy human-first formatter with stricter access-depth honesty."""

    @staticmethod
    def _is_partial_large_source(source) -> bool:
        total = int(getattr(source, "pages_total", 0) or 0)
        read = int(getattr(source, "pages_read", 0) or 0)
        return total > 0 and read > 0 and read < total

    @staticmethod
    def _access_block(coverage: Dict, pack: EvidencePack) -> str:
        levels = (coverage or {}).get("read_levels") or {}
        full = int(levels.get("full_text", 0) or 0)
        abstract = int(levels.get("abstract", 0) or 0)
        snippet = int(levels.get("snippet", 0) or 0)
        meta = int(levels.get("metadata", 0) or 0)
        partial = [s for s in pack.sources if FinalSynthesizer._is_partial_large_source(s)]
        full_whole = max(0, full - len(partial))

        if not (full or abstract or snippet or meta):
            return (
                "**Kitna gehra padha gaya:** iska data available nahi hai, isliye "
                "source-access depth ko verify nahi kiya ja saka."
            )

        lines = [
            "**Kitna gehra padha gaya (access depth confidence ko affect karti hai, "
            "lekin claim verification alag A-E check se hoti hai):**"
        ]
        if full_whole:
            lines.append(
                f"- {full_whole} source ka legally available full text process hua. "
                "Isse strong checking possible hoti hai, lekin sirf full text milne "
                "se koi claim automatically verified nahi maana jaata."
            )
        if partial:
            lines.append(
                f"- {len(partial)} badi PDF/document mein poora document ek saath nahi "
                "padha gaya; sawal se relevant pages page-by-page select karke process hue."
            )
            for source in partial[:4]:
                lines.append(
                    f"  - [{source.source_id}] {int(source.pages_read)}/{int(source.pages_total)} "
                    f"pages process hue. {str(getattr(source, 'read_note', '') or '').strip()}"
                )
        if abstract:
            lines.append(
                f"- {abstract} source ka sirf abstract mila — paper ka summary, poora "
                "method/result context nahi. Isse strong fact automatically nahi banta."
            )
        if snippet:
            lines.append(
                f"- {snippet} source se sirf search snippet mila. Ye weak/supporting "
                "signal ho sakta hai, verification nahi."
            )
        if meta:
            lines.append(
                f"- {meta} source ka sirf title/metadata mila — content-level claim "
                "verify nahi ki ja sakti."
            )
        if not full:
            lines.append(
                "- Kisi source ka full-text-level access nahi mila, isliye strong claims "
                "ko full-text verified kehna allowed nahi hai."
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
            title = (s.title or s.url or "naam nahi mila").strip()
            head = f"**[{s.source_id}] {title}**"
            if s.url:
                head += f"  \n{s.url}"
            about: List[str] = [self._KIND_WORDS.get(
                getattr(s.source_type, "value", str(s.source_type)),
                getattr(s.source_type, "value", "source"),
            )]
            if s.year:
                about.append(f"saal {s.year}")
            if s.publisher or s.venue:
                about.append(str(s.publisher or s.venue))
            if s.peer_reviewed is True:
                about.append("peer-reviewed")
            lines = [head, f"- Ye kya hai: {', '.join(about)}."]

            took = re.sub(r"\s+", " ", (s.snippet or "")).strip()
            if took:
                lines.append(
                    "- Isse kya liya gaya: " + took[:220] + ("…" if len(took) > 220 else "")
                )
            else:
                lines.append("- Isse kya liya gaya: kuch nahi — content mila hi nahi.")

            level = s.reading_level()
            if level == "full_text" and self._is_partial_large_source(s):
                access = (
                    f"PARTIAL FULL-TEXT REVIEW — large document ke {int(s.pages_read)}/"
                    f"{int(s.pages_total)} relevant pages process hue; poora document "
                    "padha gaya aisa claim nahi hai"
                )
            elif level == "full_text":
                access = (
                    "FULL-TEXT VERIFIED ACCESS — legally available full text process hua; "
                    "claim ka support/entailment alag evidence-verification gate check karta hai"
                )
            else:
                access = self._ACCESS_WORDS.get(level, level)
            lines.append(f"- Kitna padha gaya: {access}.")
            if getattr(s, "read_note", ""):
                lines.append(f"- Reading scope: {s.read_note}")

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


# Preserve the public section-order constant for existing imports/tests.
SECTION_TITLES = SECTION_TITLES  # type: ignore[name-defined]  # noqa: F821
