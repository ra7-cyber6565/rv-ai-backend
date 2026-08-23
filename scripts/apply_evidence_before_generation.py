"""One-shot guarded patcher for the evidence-before-generation facade wiring.

Run only on branch chatgpt-evidence-before-generation-20260823.  It refuses to
edit if the expected latest-main anchors are missing or duplicated.
"""
from __future__ import annotations

from pathlib import Path
import subprocess


BRANCH = "chatgpt-evidence-before-generation-20260823"
TARGET = Path("research_engine/synthesizer.py")


def _branch() -> str:
    return subprocess.check_output(
        ["git", "branch", "--show-current"], text=True
    ).strip()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"STOP: {label} anchor count={count}, expected 1")
    return text.replace(old, new, 1)


def main() -> None:
    if _branch() != BRANCH:
        raise SystemExit(f"STOP: expected branch {BRANCH!r}")
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise SystemExit("STOP: worktree is not clean before guarded patch")

    text = TARGET.read_text(encoding="utf-8")
    if "def prompt(self, question: str, analysis: str" in text:
        raise SystemExit("STOP: evidence-before-generation prompt override already present")

    import_anchor = (
        "from .answer_order import section_start\n"
        "from .models import EvidencePack\n"
    )
    import_replacement = (
        "from .answer_order import section_start\n"
        "from .evidence_before_generation import prepare_evidence_first_prompt\n"
        "from .models import EvidencePack\n"
    )
    text = _replace_once(text, import_anchor, import_replacement, "import")

    init_anchor = (
        "        self.offline_reasoner = OfflineEvidenceReasoner()\n"
        "        self.last_presentation_check: Dict = {}\n\n"
        "    def extractive_summary(self, question: str, pack: EvidencePack) -> str:\n"
    )
    prompt_method = '''        self.offline_reasoner = OfflineEvidenceReasoner()\n        self.last_presentation_check: Dict = {}\n        self.last_evidence_preselection: Dict = {}\n\n    def prompt(self, question: str, analysis: str, critique: str,\n               hypothesis_text: str, pack: EvidencePack, plan: Dict,\n               memory_note: str = "") -> str:\n        """Build the model prompt from preselected exact evidence spans first.\n\n        The original EvidencePack is never mutated.  The parent formatter sees a\n        reduced copy containing only one selected exact span per source, while\n        the system-owned contract explicitly forbids post-hoc citation borrowing.\n        Final same-source A-E verification still runs after drafting.\n        """\n        prompt_pack, evidence_block, audit = prepare_evidence_first_prompt(\n            question, pack\n        )\n        self.last_evidence_preselection = dict(audit)\n        base = super().prompt(\n            question, analysis, critique, hypothesis_text,\n            prompt_pack, plan, memory_note\n        )\n        marker = "\\nSOURCES (sirf inhi IDs se cite karo):\\n"\n        if marker in base:\n            return base.replace(\n                marker, f"\\n{evidence_block}\\n\\nSOURCES (sirf inhi IDs se cite karo):\\n", 1\n            )\n        # Defensive fallback if the inherited prompt wording changes: the\n        # evidence-first contract still precedes the model-visible prompt.\n        return f"{evidence_block}\\n\\n{base}"\n\n    def extractive_summary(self, question: str, pack: EvidencePack) -> str:\n'''
    text = _replace_once(text, init_anchor, prompt_method, "prompt-method")

    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print("Evidence-before-generation facade wiring applied safely.")
    print("Original EvidencePack mutation: prohibited by design.")
    print("Post-draft same-source A-E verification: still required.")


if __name__ == "__main__":
    main()
