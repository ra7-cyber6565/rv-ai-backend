"""Offline tests for the one-call safe Gemini request diagnostic."""
from __future__ import annotations

from scripts.diagnose_live_model_request import (
    build_prompt,
    diagnose_request,
    inspect_response,
)


class _Response:
    text = "TOP SECRET RESPONSE CONTENT"


class _FinishReason:
    name = "SAFETY"


class _Candidate:
    finish_reason = _FinishReason()


class _BlockedResponse:
    candidates = [_Candidate()]

    @property
    def text(self):
        raise ValueError("private provider safety body must stay hidden")


def test_diagnostic_prompt_is_bounded_and_preserves_data_boundary():
    prompt = build_prompt(50000)
    assert len(prompt) == 50000
    assert "BEGIN_UNTRUSTED_SOURCES" in prompt
    assert prompt.endswith("END_UNTRUSTED_SOURCES\n")


def test_success_diagnostic_makes_exactly_one_call_and_discards_content():
    seen = {"factory": 0, "generate": 0, "prompt": ""}

    def factory(name):
        seen["factory"] += 1
        assert name == "gemma-test"
        return object()

    def generate(model, prompt):  # noqa: ARG001
        seen["generate"] += 1
        seen["prompt"] = prompt
        return _Response()

    result = diagnose_request(
        "gemma-test",
        prompt_chars=12000,
        model_factory=factory,
        generate_fn=generate,
    )
    assert seen["factory"] == 1
    assert seen["generate"] == 1
    assert len(seen["prompt"]) == 12000
    assert result["generation_calls"] == 1
    assert result["retry_calls"] == 0
    assert result["fallback_calls"] == 0
    assert result["response_received"] is True
    assert result["text_ok"] is True
    assert result["text_chars"] == len(_Response.text)
    assert _Response.text not in repr(result)


def test_request_failure_is_classified_without_raw_provider_body():
    secret = "404 models/gemma-test is not found PRIVATE-PROVIDER-BODY"

    def crash(model, prompt):  # noqa: ARG001
        raise RuntimeError(secret)

    result = diagnose_request(
        "gemma-test",
        model_factory=lambda name: object(),
        generate_fn=crash,
    )
    assert result["response_received"] is False
    assert result["request_error_kind"] == "model_not_found"
    assert result["request_exception_class"] == "RuntimeError"
    assert secret not in repr(result)
    assert result["generation_calls"] == 1
    assert result["retry_calls"] == 0
    assert result["fallback_calls"] == 0


def test_text_accessor_failure_reports_finish_reason_without_raw_body():
    result = inspect_response(_BlockedResponse())
    assert result["response_received"] is True
    assert result["text_ok"] is False
    assert result["text_exception_class"] == "ValueError"
    assert result["finish_reasons"] == ["SAFETY"]
    assert "private provider" not in repr(result)
