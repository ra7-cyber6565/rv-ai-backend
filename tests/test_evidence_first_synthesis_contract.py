"""Evidence-first synthesis boundary regressions.

The orchestrator passes an already-built pre-draft evidence block into the
integrated FinalSynthesizer. The facade must accept and append it after the
legacy Claude prompt so broad source/context text cannot become the last word on
critical-claim grounding.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.models import EvidencePack
from research_engine.synthesizer import FinalSynthesizer


def _call_prompt(*, evidence_first_block=None):
    synth = FinalSynthesizer()
    kwargs = {}
    if evidence_first_block is not None:
        kwargs["evidence_first_block"] = evidence_first_block
    return synth.prompt(
        "What does the evidence show?",
        "analysis notes",
        "",
        "",
        EvidencePack(),
        {},
        "",
        **kwargs,
    )


def test_integrated_synthesizer_accepts_orchestrator_evidence_first_keyword():
    marker = "EVIDENCE-FIRST-TEST-MANIFEST\nBEGIN_PRESELECTED_EVIDENCE\nEND_PRESELECTED_EVIDENCE"
    prompt = _call_prompt(evidence_first_block=marker)
    assert marker in prompt


def test_evidence_first_contract_is_last_prompt_boundary():
    marker = "EVIDENCE-FIRST-TEST-MANIFEST"
    prompt = _call_prompt(evidence_first_block=marker)
    assert prompt.rstrip().endswith(marker)
    assert prompt.count(marker) == 1


def test_legacy_prompt_call_without_manifest_remains_compatible():
    prompt = _call_prompt()
    assert "SAWAL: What does the evidence show?" in prompt
    assert "EVIDENCE-FIRST-TEST-MANIFEST" not in prompt


def test_blank_manifest_does_not_add_fake_boundary():
    with_blank = _call_prompt(evidence_first_block="   ")
    legacy = _call_prompt()
    assert with_blank == legacy
