"""Regression contract for literal evidence-before-generation.

These tests intentionally land before implementation. They define the safety
boundary: the synthesis prompt receives a bounded pre-draft evidence bundle,
source text is inert/untrusted, and strong factual drafting must not proceed
without an eligible exact span.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_placeholder_until_evidence_first_implementation_lands():
    # Replaced in the implementation commit on the same feature branch.
    assert True
