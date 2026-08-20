"""
429 se poora pass mar jaata tha — ab retry + doosra model.

Kyun ye test hai (2026-08-20 ke live MAXIMUM run se): ek hi 429 ne teen pass
(critic, hypothesis, synthesis) ek saath uda diye the, kyunki `generate()` har
exception ko nigal kar "" lauta deta tha. Free tier ka quota PER MODEL hota hai,
isliye ab: thoda ruk kar dobara, phir agla model. Aur jo hua wo audit mein
imaandaari se likha jaata hai.

Koi network, koi API key, koi pytest. Chalao:
    python3 tests/test_gemini_retry.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_reasoning  # noqa: E402
from research_engine.gemini_reasoning import (  # noqa: E402
    GeminiReasoning, QuotaExhausted, _classify,
)

# Test ko sona nahi hai — backoff 0 kar dete hain (asli value production ki hai).
gemini_reasoning._BACKOFF_SECONDS = (0.0, 0.0)


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModel:
    """Ek script ke hisaab se jawab/exception deta hai."""

    def __init__(self, name: str, script):
        self.name = name
        self.script = list(script)
        self.calls = 0

    def generate_content(self, prompt):          # noqa: ARG002
        self.calls += 1
        item = self.script.pop(0) if self.script else "OK late"
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


def _brain(models, budget: int = 2) -> GeminiReasoning:
    """
    `models` = {"model-a": [...script...], "model-b": [...]} — order wahi.

    Asli library ko chhue bina `model()`, `_model_order()` aur `_build()` ko
    fake karte hain. Baaki poora retry logic ASLI chalta hai — wahi test karna hai.
    """
    order = list(models.keys())
    fakes = {name: _FakeModel(name, script) for name, script in models.items()}
    brain = GeminiReasoning(budget=budget, model_name=order[0])
    brain._model = fakes[order[0]]
    brain.model = lambda: brain._model                       # lazy resolve skip
    brain._model_order = lambda: order
    def _build(name):
        brain.model_name = name
        brain._model = fakes[name]
        return fakes[name]
    brain._build = _build
    brain.fakes = fakes                                      # test ke liye
    return brain


def _quota(msg: str = "429 ResourceExhausted: quota exceeded") -> Exception:
    return RuntimeError(msg)


# ── classification ───────────────────────────────────────────────────────────
def test_429_is_transient_and_404_is_model_broken():
    assert _classify(_quota()) == "transient"
    assert _classify(RuntimeError("503 Service Unavailable")) == "transient"
    assert _classify(RuntimeError("404 models/x is not found")) == "model"
    assert _classify(RuntimeError("ValueError: kuch aur")) == "fatal"


# ── retry usi model par ──────────────────────────────────────────────────────
def test_transient_error_is_retried_on_same_model():
    brain = _brain({"model-a": [_quota(), "asli jawab"]})
    text = brain.generate("prompt", "critique")
    assert text == "asli jawab", text
    # LOGICAL budget ek hi khaya (retry budget nahi khaata) — ye zaroori hai,
    # warna ek 429 phir se poora pass kha jaata
    assert brain.calls_used == 1, brain.calls_used
    assert brain.attempts == 2, brain.attempts
    assert brain.remaining == 1
    assert any("koshish ke baad chala" in n for n in brain.notes), brain.notes


def test_retry_gives_up_on_same_model_and_moves_to_next():
    brain = _brain({"model-a": [_quota(), _quota(), _quota()],
                    "model-b": ["doosre model se jawab"]})
    text = brain.generate("prompt", "synthesis")
    assert text == "doosre model se jawab", text
    assert brain.fakes["model-a"].calls == 3, "3 koshish honi chahiye thi"
    assert brain.switched_models == 1
    assert brain.model_name == "model-b"
    assert any("'model-b' par chala" in n for n in brain.notes), brain.notes


def test_model_not_found_does_not_retry_same_model():
    """404 par usi model ko dobara maarna bekaar hai — seedha agla model."""
    brain = _brain({"model-a": [RuntimeError("404 models/model-a is not found")],
                    "model-b": ["theek hai"]})
    assert brain.generate("prompt", "analysis") == "theek hai"
    assert brain.fakes["model-a"].calls == 1, brain.fakes["model-a"].calls


def test_empty_response_counts_as_failure():
    """Khaali jawab ko 'safal' maan lena hi purana chhupa hua bug tha."""
    brain = _brain({"model-a": ["   ", "ab jawab aaya"]})
    assert brain.generate("prompt", "analysis") == "ab jawab aaya"
    assert brain.attempts == 2


def test_everything_fails_returns_empty_but_records_why():
    brain = _brain({"model-a": [_quota(), _quota(), _quota()],
                    "model-b": [_quota(), _quota(), _quota()]})
    assert brain.generate("prompt", "critique") == ""
    assert brain.calls_used == 1
    assert brain.attempts == 6, brain.attempts
    assert brain.errors, "wajah record honi chahiye"
    assert any("429" in e for e in brain.errors)


def test_budget_exhausted_raises_quota_exhausted():
    brain = _brain({"model-a": ["ek", "do"]}, budget=1)
    assert brain.generate("prompt", "analysis") == "ek"
    try:
        brain.generate("prompt", "synthesis")
    except QuotaExhausted as exc:
        assert "budget" in str(exc)
    else:                                        # pragma: no cover
        raise AssertionError("QuotaExhausted aana chahiye tha")


def test_usage_note_tells_the_truth():
    brain = _brain({"model-a": [_quota(), _quota(), _quota()],
                    "model-b": ["jawab"]})
    brain.generate("prompt", "synthesis")
    note = brain.usage_note()
    assert "reasoning pass" in note
    assert "actual API attempts" in note, note
    assert "doosre model par shift" in note, note
    assert "error aaye" in note, note


def _main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:                 # noqa: BLE001
            failed += 1
            print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not failed else f"\n{failed} test fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
