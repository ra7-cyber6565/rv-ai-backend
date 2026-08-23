"""Guarded one-shot P0-C fix for 'inconsistent with' stance collision.

This script edits only the exact expected branch text. It refuses to run if the
source has drifted, and it does not change any claim-verification thresholds.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRA = ROOT / "research_engine" / "contradiction.py"
TEST = ROOT / "tests" / "test_p0c_claim_level_contradiction.py"
CLAIM = ROOT / "research_engine" / "claim_verification.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"STOP: expected exactly one {label} sentinel, found {count}")
    return text.replace(old, new, 1)


contra = CONTRA.read_text(encoding="utf-8")
old_opp = '''    "failed to", "does not", "did not", "no association", "no benefit", "contradicts",\n'''
new_opp = '''    "failed to", "does not", "did not", "no association", "no benefit", "contradicts",\n    # Do not let the SUPPORT cue "consistent with" fire inside the opposite\n    # phrase "inconsistent with".  Treat the whole phrase as explicit opposition.\n    "inconsistent with",\n'''
contra = replace_once(contra, old_opp, new_opp, "opposition cue")

old_strong = '''    "failed to", "does not", "did not", "no association", "no benefit",\n    "no difference", "refuted", "disproved", "not reproduced",\n'''
new_strong = '''    "failed to", "does not", "did not", "no association", "no benefit",\n    "inconsistent with",\n    "no difference", "refuted", "disproved", "not reproduced",\n'''
contra = replace_once(contra, old_strong, new_strong, "strong opposition cue")

# Direct mutation-proof regression for the substring collision that caused the
# higher-level exact-span tests to fail.
test = TEST.read_text(encoding="utf-8")
old_import = '''from research_engine import final_quality_gate as FQ\nfrom research_engine.models import EvidencePack, Passage, SourceRecord, SourceType\n'''
new_import = '''from research_engine import final_quality_gate as FQ\nfrom research_engine.contradiction import ContradictionEngine\nfrom research_engine.models import EvidencePack, Passage, SourceRecord, SourceType\n'''
test = replace_once(test, old_import, new_import, "ContradictionEngine import")

anchor = '''def test_distant_opposing_paragraph_cannot_bleed_into_selected_claim_span():\n'''
regression = '''def test_inconsistent_with_is_opposition_not_false_consistent_support():\n    engine = ContradictionEngine()\n    stance, cues = engine.stance(EXACT_OPPOSE)\n\n    assert stance == "OPPOSE"\n    assert "inconsistent with" in cues\n    assert "consistent with" not in cues\n\n\n'''
if regression not in test:
    test = replace_once(test, anchor, regression + anchor, "P0-C stance regression anchor")

# Explicitly assert the P0-A/P0-C evidence thresholds were not changed by this
# focused contradiction-stemming fix.
claim = CLAIM.read_text(encoding="utf-8")
required = {
    '_ENTAIL_SIM = 0.30',
    '_ENTAIL_SIM_WITH_NUM = 0.12',
    '_MIN_TEXT_CHARS = 120',
    '_MIN_RELEVANCE = 0.25',
    '_MIN_QUALITY = 0.35',
    '_LOW_QUALITY = 0.20',
}
missing = sorted(item for item in required if item not in claim)
if missing:
    raise SystemExit("STOP: verification thresholds drifted: " + ", ".join(missing))

CONTRA.write_text(contra, encoding="utf-8", newline="\n")
TEST.write_text(test, encoding="utf-8", newline="\n")

print("P0-C stance collision fix applied safely.")
print('[OK] "inconsistent with" is explicit strong opposition')
print('[OK] direct substring-collision regression added')
print('[OK] claim-verification thresholds unchanged')
