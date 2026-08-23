"""Guarded one-shot patch for the integrated evidence-first synthesis boundary.

This script exists only to make a small, reviewable edit without replacing the
large synthesizer facade through a remote contents API. It refuses to patch if
the expected current-main anchor moved, is idempotent, and never touches
thresholds or Claude-owned formatter code.
"""
from __future__ import annotations

from pathlib import Path


PATH = Path("research_engine/synthesizer.py")
ANCHOR = '''    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.presentation_guard = PresentationGuard()
        self.offline_reasoner = OfflineEvidenceReasoner()
        self.last_presentation_check: Dict = {}

'''
METHOD = '''    def prompt(self, question: str, analysis: str, critique: str,
               hypothesis_text: str, pack: EvidencePack, plan: Dict,
               memory_note: str = "", evidence_first_block: str = "") -> str:
        """Build the legacy human-first prompt, then seal the pre-draft contract.

        P0-B builds the evidence manifest before model prose exists. The
        orchestrator passes that exact block here during synthesis. Appending it
        *after* the broad legacy source/context prompt keeps the preselection
        contract as the final instruction boundary and avoids modifying the
        Claude-owned formatter itself.
        """
        prompt = super().prompt(
            question, analysis, critique, hypothesis_text, pack, plan, memory_note
        )
        block = str(evidence_first_block or "").strip()
        if not block:
            return prompt
        return f"{prompt.rstrip()}\\n\\n{block}"

'''
MARKER = "evidence_first_block: str = \"\""


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print("P0-E synthesis contract already present; no change needed.")
        return
    count = text.count(ANCHOR)
    if count != 1:
        raise SystemExit(
            f"STOP: expected synthesizer facade anchor exactly once, found {count}; "
            "refusing unsafe patch."
        )
    updated = text.replace(ANCHOR, ANCHOR + METHOD, 1)
    if updated.count(MARKER) != 1:
        raise SystemExit("STOP: patch postcondition failed; file not written.")
    PATH.write_text(updated, encoding="utf-8", newline="\n")
    print("P0-E synthesis evidence-first contract applied safely to synthesizer facade.")
    print("Claude formatter file untouched: yes")
    print("Quality/claim thresholds touched: no")


if __name__ == "__main__":
    main()
