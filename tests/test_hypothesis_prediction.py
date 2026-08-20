"""
HypothesisEngine ke prediction parser ka offline test — koi network, koi Gemini.

Kyun ye test hai: 2026-08-19 ko `hypothesis.py` mein `_parse_prediction` DO baar
define mila. Python doosri definition rakhta hai, pehli chup-chaap mar jaati hai.
Doosri wali `(PredictionStructure, text)` ka TUPLE lautati thi, aur `parse()` use
seedha `h.prediction` mein daal deta tha. Uske baad `Hypothesis.to_dict()` mein:

    AttributeError: 'tuple' object has no attribute 'is_complete'

Ye MAXIMUM mode ka asli raasta hai (hypothesis ban kar jawab mein jaati hai),
isliye live crash tha — sirf test ka issue nahi.

Doosra, chhupa hua jhooth: tuple-wali version khaali jagah placeholder se bhar
deti thi ("change expected", "to be determined"). Usse khaali prediction bhi
`is_complete` ban jaati thi, aur report bolti ki structured prediction maujood
hai — jabki thi nahi.

Chalao:  python3 tests/test_hypothesis_prediction.py
Ya:      python3 -m pytest tests/test_hypothesis_prediction.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine.hypothesis import (  # noqa: E402
    STATUS, Hypothesis, HypothesisEngine, PredictionStructure,
)

ENGINE = HypothesisEngine()

# Wahi format jo hum prompt mein Gemini se maangte hain
LABELLED = """## Hypothesis 1
- Statement: Intermittent fasting insulin sensitivity ko weight loss se alag
  badhata hai.
- Reasoning: [S1] trial mein HbA1c gira, [S2] meta-analysis mein insulin.
- Supporting evidence: [S1] [S2]
- Contradicting evidence: [S3] mein weight adjust karne par asar khatam ho gaya.
- Novelty: weight-independent pathway par direct test nahi hua.
- Prediction: Variables: fasting glucose, HOMA-IR index
  Expected outcome: 25% reduction in HOMA-IR after 12 weeks
  Measurement: assessed using HOMA-IR index and fasting plasma glucose
  Falsification: reject if no change in HOMA-IR at weight-matched controls
- How to test: 12-week weight-matched randomized trial, 200 participants,
  HOMA-IR primary endpoint, control group isocaloric non-fasting diet.
- Risks: insulin lene wale patients mein hypoglycaemia ka khatra.
- Confidence: MEDIUM
"""

# Model ne labels nahi likhe — free text
FREE_TEXT = """## Hypothesis 1
- Statement: Fasting se blood glucose girta hai.
- Prediction: fasting glucose levels will show a decrease of 20-30% and the
  effect is measured via continuous glucose monitoring over 8 weeks.
- How to test: 8-week crossover study with continuous glucose monitors on 60
  adults, comparing fasting and non-fasting windows.
- Risks: hypoglycaemia.
- Confidence: LOW
"""

# Bilkul khaali/vague prediction — yahan structure BANNA hi nahi chahiye
VAGUE = """## Hypothesis 1
- Statement: Fasting ka kuch to asar hoga.
- Prediction: something interesting might happen in the body eventually
- How to test: dekhenge
- Confidence: LOW
"""

# Prediction line hi nahi — honesty report mein ye saaf bolna chahiye
NO_PREDICTION = """## Hypothesis 1
- Statement: Fasting se type 2 diabetes reverse ho jaata hai permanently.
- Reasoning: kuch trials mein sugar kam hua.
- Supporting evidence: [S1]
- Confidence: HIGH
"""

# Multi-line reasoning — Gemini se prompt mein "step-by-step chain" maanga hai
MULTILINE_REASONING = """## Hypothesis 1
- Statement: Weight-independent pathway se insulin sensitivity badhti hai.
- Reasoning: Step 1 — [S1] trial mein HbA1c gira.
  Step 2 — [S2] meta-analysis mein insulin sensitivity badhi.
  Step 3 — [S3] mein weight adjust karne ke baad bhi thoda asar bacha.
- Prediction: Variables: HOMA-IR
  Expected outcome: 20% reduction in HOMA-IR
  Measurement: assessed using HOMA-IR index and fasting insulin assay
- How to test: weight-matched randomized trial, 12 weeks, 200 log.
- Risks: insulin par chal rahe patients mein hypoglycaemia.
- Confidence: MEDIUM
"""


def test_parse_does_not_crash_and_returns_structure_or_none():
    """Asli bug: `h.prediction` mein tuple aa jaata tha."""
    for text in (LABELLED, FREE_TEXT, VAGUE, NO_PREDICTION):
        for h in ENGINE.parse(text):
            assert not isinstance(h.prediction, tuple), \
                f"prediction tuple aa gaya (purana bug wapas): {h.prediction!r}"
            assert h.prediction is None or isinstance(h.prediction, PredictionStructure), \
                type(h.prediction)


def test_to_dict_never_raises():
    """Ye wahi line thi jo crash karti thi: `self.prediction.is_complete`."""
    for text in (LABELLED, FREE_TEXT, VAGUE, NO_PREDICTION):
        for h in ENGINE.parse(text):
            d = h.to_dict()                      # crash nahi hona chahiye
            assert d["status"] == STATUS, d["status"]
            assert isinstance(d["prediction"], dict), d["prediction"]


def test_multiline_field_values_are_not_thrown_away():
    """
    Gemini "Prediction:" ke neeche labelled lines likhta hai. Purana parser
    sirf pehli line uthata tha, baaki gum. Isse structured prediction kabhi
    complete nahi banti thi aur reasoning chain kat jaati thi.
    """
    h = ENGINE.parse(LABELLED)[0]
    assert "Expected outcome" in h.prediction_text, h.prediction_text
    assert "Falsification" in h.prediction_text, h.prediction_text
    # multi-line reasoning bhi poori aaye
    h2 = ENGINE.parse(MULTILINE_REASONING)[0]
    assert "step 2" in h2.reasoning.lower(), h2.reasoning
    assert "step 3" in h2.reasoning.lower(), h2.reasoning
    # aur field boundary respect ho — reasoning mein risks ghus na jaaye
    assert "hypoglycaemia" not in h2.reasoning.lower(), h2.reasoning
    assert "hypoglycaemia" in h2.risks.lower(), h2.risks


def test_labelled_prediction_becomes_structured():
    hyps = ENGINE.parse(LABELLED)
    assert hyps, "hypothesis parse hi nahi hui"
    h = hyps[0]
    assert h.statement, h
    assert isinstance(h.prediction, PredictionStructure), h.prediction
    assert h.prediction.variables, h.prediction.to_dict()
    assert h.prediction.expected_outcome, h.prediction.to_dict()
    assert h.has_prediction is True


def test_free_text_prediction_still_extracts_something():
    """Labels na ho to bhi keyword+regex heuristic kaam kare — capability gum na ho."""
    h = ENGINE.parse(FREE_TEXT)[0]
    assert isinstance(h.prediction, PredictionStructure), h.prediction
    assert "glucose" in h.prediction.variables, h.prediction.variables
    assert h.prediction.expected_outcome, h.prediction.to_dict()
    # text fallback bhi hamesha bacha rehna chahiye
    assert h.prediction_text.strip(), h.prediction_text


def test_vague_prediction_is_not_dressed_up_as_structured():
    """
    Placeholder bharna mana hai. Khaali prediction ko structured batana =
    honesty report ka jhooth.
    """
    h = ENGINE.parse(VAGUE)[0]
    if h.prediction is not None:
        assert h.prediction.is_complete is False, h.prediction.to_dict()
        for fake in ("change expected", "to be determined",
                     "no observable change"):
            assert fake not in str(h.prediction.to_dict()).lower(), fake
    d = h.to_dict()
    assert d["prediction"].get("structured") is False or not d["has_prediction"], d


def test_short_prediction_returns_none_not_empty_structure():
    assert HypothesisEngine._parse_prediction("") is None
    assert HypothesisEngine._parse_prediction("maybe") is None


def test_incomplete_structure_is_not_marked_complete():
    p = PredictionStructure(variables=["glucose"])
    assert p.is_complete is False
    p2 = PredictionStructure(variables=["glucose"],
                             expected_outcome="25% reduction in HOMA-IR",
                             measurement_method="HOMA-IR index, fasting glucose")
    assert p2.is_complete is True


def test_honesty_check_flags_missing_prediction():
    warnings = ENGINE.honesty_check(ENGINE.parse(NO_PREDICTION))
    joined = " ".join(warnings).lower()
    assert "prediction" in joined, warnings
    # test design bhi nahi hai — wo bhi bolna chahiye
    assert "speculation" in joined, warnings


def test_vague_hypothesis_is_flagged_as_speculation():
    """
    Test design chhota (20 char se kam) — flag hona chahiye.

    Note: `is_testable` sirf LAMBAI dekhta hai. Yaani lamba-lekin-bekaar test
    design ("hum ek study karke dekhenge ki kya hota hai") bach jaayega. Ye gate
    kamzor hai, par ise semantic banane ka faisla alag kaam hai — yahan wahi
    test kar rahe hain jo rule asal mein hai.
    """
    warnings = ENGINE.honesty_check(ENGINE.parse(VAGUE))
    assert any("speculation" in w.lower() for w in warnings), warnings


def test_status_is_never_a_fact():
    h = ENGINE.parse(LABELLED)[0]
    assert h.status == STATUS == "UNTESTED HYPOTHESIS"
    d = h.to_dict()
    assert d["status"] == "UNTESTED HYPOTHESIS"
    assert "UNTESTED HYPOTHESIS" in d["disclaimer"]
    # confidence ko evidence-proof kehna mana hai
    assert "confidence_reasoning_based" in d


def test_hypothesis_dataclass_defaults_are_safe():
    h = Hypothesis()
    assert h.prediction is None
    assert h.to_dict()["prediction"] == {"text": "", "structured": False}


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not fails else f"\n{fails} test fail")
    sys.exit(1 if fails else 0)
