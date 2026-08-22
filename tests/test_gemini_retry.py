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

from research_engine import gemini_model, gemini_reasoning  # noqa: E402
from research_engine.gemini_reasoning import (  # noqa: E402
    GeminiReasoning, QuotaExhausted, _classify,
)
from research_engine.model_errors import (  # noqa: E402
    AUTH, DAILY_QUOTA, MODEL_NOT_FOUND, RATE_LIMIT, SERVER, UNKNOWN,
    classify_text,
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
    gemini_model.forget_dead()               # test isolation — 404 memory saaf
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


# Asli live message (2026-08-20) — DIN ka quota, 21 second ka retry_delay
_DAILY_TEXT = (
    "ResourceExhausted: 429 You exceeded your current quota, please check your "
    "plan and billing details. quota_metric: generativelanguage.googleapis.com/"
    "generate_content_free_tier_requests, quota_id: "
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier, "
    "quota_value: 50 retry_delay { seconds: 21 }"
)


def _daily() -> Exception:
    return RuntimeError(_DAILY_TEXT)


# ── classification (§7 — chhe tarah ke error alag-alag) ──────────────────────
def test_error_kinds_are_distinguished():
    """
    Purana code sirf teen label jaanta tha (transient/model/fatal), isliye DIN ka
    quota bhi "random network error" ban jaata tha. Ab har error ka apna matlab.
    """
    assert _classify(_quota()) == RATE_LIMIT
    assert _classify(_daily()) == DAILY_QUOTA
    assert _classify(RuntimeError("503 Service Unavailable")) == SERVER
    assert _classify(RuntimeError("404 models/x is not found")) == MODEL_NOT_FOUND
    assert _classify(RuntimeError("PermissionDenied: 403 permission denied")) == AUTH
    assert _classify(RuntimeError("ValueError: kuch aur")) == UNKNOWN


def test_daily_quota_verdict_says_do_not_retry_same_model():
    v = classify_text(_DAILY_TEXT)
    assert v.kind == DAILY_QUOTA
    assert v.retry_same_model is False, "din ka quota — rukne se kuch nahi badalta"
    assert v.disable_model is True
    assert v.try_other_model is True, "quota PER MODEL hai — agla model try ho"
    assert v.stop_all is False
    assert v.retry_after == 21.0, v.retry_after


def test_per_minute_limit_is_retried_but_daily_is_not():
    minute = classify_text("429 ResourceExhausted: quota_id: "
                           "GenerateRequestsPerMinutePerProjectPerModel-FreeTier")
    assert minute.kind == RATE_LIMIT
    assert minute.retry_same_model is True
    assert classify_text(_DAILY_TEXT).retry_same_model is False


# ── retry usi model par ──────────────────────────────────────────────────────
def test_transient_error_is_retried_on_same_model():
    brain = _brain({"model-a": [_quota(), "asli jawab"]})
    text = brain.generate("prompt", "critique")
    assert text == "asli jawab", text
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
    brain = _brain({"model-a": [RuntimeError("404 models/model-a is not found")],
                    "model-b": ["theek hai"]})
    assert brain.generate("prompt", "analysis") == "theek hai"
    assert brain.fakes["model-a"].calls == 1, brain.fakes["model-a"].calls


def test_empty_response_counts_as_failure():
    brain = _brain({"model-a": ["   ", "ab jawab aaya"]})
    assert brain.generate("prompt", "analysis") == "ab jawab aaya"
    assert brain.attempts == 2


def test_everything_fails_returns_empty_but_records_safe_reason():
    brain = _brain({"model-a": [_quota(), _quota(), _quota()],
                    "model-b": [_quota(), _quota(), _quota()]})
    assert brain.generate("prompt", "critique") == ""
    assert brain.calls_used == 1
    assert brain.attempts == 6, brain.attempts
    assert brain.errors, "wajah record honi chahiye"
    joined = " ".join(brain.errors)
    assert "rate_limit" in joined
    for raw in ("429", "ResourceExhausted", "quota exceeded"):
        assert raw not in joined


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


# ── TEST D (§16): daily quota par bekaar retry nahi ──────────────────────────
def test_daily_quota_is_not_retried_uselessly():
    brain = _brain({"model-a": [_daily(), _daily(), _daily()],
                    "model-b": ["doosre model ne jawab diya"]})
    text = brain.generate("prompt", "synthesis")
    assert text == "doosre model ne jawab diya", text
    assert brain.fakes["model-a"].calls == 1, \
        f"daily quota par sirf 1 attempt honi chahiye, hui {brain.fakes['model-a'].calls}"
    assert brain.attempts == 2, brain.attempts
    assert brain.blocked.get("model-a") == DAILY_QUOTA, brain.blocked
    # The failed attempt remains auditable, but a later model produced the
    # requested output, so the completed logical pass is not a public failure.
    assert brain.failure_kind() == ""
    assert DAILY_QUOTA in brain.api_accounting()["failure_kinds"]


def test_blocked_model_is_skipped_in_later_passes():
    brain = _brain({"model-a": [_daily(), _daily()],
                    "model-b": ["pehla", "doosra"]}, budget=2)
    assert brain.generate("p", "analysis") == "pehla"
    before = brain.fakes["model-a"].calls
    assert brain.generate("p", "synthesis") == "doosra"
    assert brain.fakes["model-a"].calls == before, \
        "band model se dobara poochha gaya — yahi purana waqt ka nuksaan tha"


def test_long_retry_delay_prefers_next_model_over_sleeping():
    gemini_reasoning._MAX_SLEEP_SECONDS = 6.0
    slow = RuntimeError("429 ResourceExhausted: rate limit; retry_delay { seconds: 21 }")
    brain = _brain({"model-a": [slow, "late jawab"], "model-b": ["turant jawab"]})
    assert brain.generate("p", "critique") == "turant jawab"
    assert brain.fakes["model-a"].calls == 1
    assert any("wait" in n for n in brain.notes), brain.notes


# ── TEST E (§16): mara hua model naam pehchano aur chhod do ──────────────────
def test_deprecated_model_is_marked_dead_and_skipped():
    brain = _brain({"model-a": [RuntimeError("404 models/model-a is not found "
                                             "for API version v1beta")],
                    "model-b": ["chal gaya", "phir chala"]}, budget=2)
    assert brain.generate("p", "analysis") == "chal gaya"
    assert gemini_model.is_dead("model-a"), "404 naam process-wide chhodna chahiye"
    assert gemini_model.dead_models().get("model-a") == MODEL_NOT_FOUND
    assert brain.generate("p", "synthesis") == "phir chala"
    assert brain.fakes["model-a"].calls == 1, brain.fakes["model-a"].calls
    gemini_model.forget_dead()


def test_dead_model_never_returned_by_candidates():
    gemini_model.forget_dead()
    gemini_model._cache = None
    gemini_model._seen = ["gemini-2.0-flash", "gemini-2.5-flash"]

    class _FakeGenai:
        @staticmethod
        def list_models():
            raise RuntimeError("offline — list_models nahi chala")

    gemini_model.mark_dead("gemini-2.0-flash")
    order = gemini_model.candidates(_FakeGenai)
    assert "gemini-2.0-flash" not in order, order
    assert order, "kuch naam bachna chahiye"
    gemini_model.forget_dead()
    gemini_model._cache = None
    gemini_model._seen = []


# ── auth failure: aur koshish bekaar hai ─────────────────────────────────────
def test_auth_failure_stops_everything():
    bad_key = RuntimeError("PermissionDenied: 403 API key not valid")
    brain = _brain({"model-a": [bad_key, "kabhi nahi"],
                    "model-b": ["ye bhi nahi chalega"]}, budget=2)
    assert brain.generate("p", "analysis") == ""
    assert brain.fakes["model-a"].calls == 1
    assert brain.fakes["model-b"].calls == 0, "key galat hai — doosra model bhi bekaar"
    assert brain.stopped is True
    attempts = brain.attempts
    assert brain.generate("p", "synthesis") == ""
    assert brain.attempts == attempts, "auth fail ke baad HTTP call nahi honi chahiye"
    assert brain.failure_kind() == AUTH


# ── §9/§25: user/audit dono mein raw provider payload leak nahi ───────────────
def test_failure_reason_and_public_details_are_sanitized():
    brain = _brain({"model-a": [_daily()], "model-b": [_daily()]})
    assert brain.generate("p", "synthesis") == ""
    reason = brain.failure_reason()
    assert reason, "wajah khaali nahi honi chahiye"
    assert "free daily limit" in reason, reason
    for bad in ("ResourceExhausted", "quota_id", "429", "Traceback"):
        assert bad not in reason, f"user-facing line mein raw error nahi: {reason}"
    details = brain.technical_details()
    assert details and any("daily_quota" in d for d in details), details
    joined = " ".join(details)
    for bad in ("ResourceExhausted", "quota_id", "429", "protobuf"):
        assert bad not in joined


def test_api_accounting_is_honest():
    brain = _brain({"model-a": [_quota(), _quota(), _quota()],
                    "model-b": ["jawab"]})
    brain.generate("p", "synthesis")
    acc = brain.api_accounting()
    assert acc["logical_reasoning_calls"] == 1
    assert acc["actual_http_attempts"] == 4, acc
    assert acc["successful_calls"] == 1
    assert acc["failed_http_attempts"] == 3, acc
    assert acc["failed_attempts"] == 3, acc
    assert acc["same_model_retries"] == 2, acc
    assert acc["retries"] == 2, acc
    assert acc["model_switches"] == 1
    assert acc["models_tried"] == ["model-a", "model-b"], acc
    assert RATE_LIMIT in acc["failure_kinds"], acc
    assert acc["failure_summary"], acc
    assert acc["stopped_early"] is False
    assert acc["actual_http_attempts"] == (
        1 + acc["same_model_retries"] + acc["model_switches"]), acc


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
