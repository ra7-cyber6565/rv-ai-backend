from research_engine.specialist_handoff_guard import (
    is_retryable_specialist_handoff_failure,
    recover_specialist_handoff,
)


def test_explicit_specialist_handoff_failure_retries_once_and_can_recover():
    calls = []
    responses = iter([
        {"status": "specialist_handoff"},
        {"status": "ok", "worker": "AI-3", "payload": "real result"},
    ])

    def invoke():
        calls.append(1)
        return next(responses)

    result = recover_specialist_handoff(invoke)

    assert len(calls) == 2
    assert result.attempts == 2
    assert result.recovered is True
    assert result.payload["payload"] == "real result"


def test_non_handoff_failure_is_not_retried_or_hidden():
    calls = []

    def invoke():
        calls.append(1)
        return {"status": "quality_failed", "reason": "missing evidence"}

    result = recover_specialist_handoff(invoke)

    assert len(calls) == 1
    assert result.recovered is False
    assert result.payload["status"] == "quality_failed"


def test_repeated_handoff_failure_stays_failed_and_partial_eligible():
    calls = []

    def invoke():
        calls.append(1)
        return {"error_code": "specialist_handoff_failed"}

    result = recover_specialist_handoff(invoke)

    assert len(calls) == 2
    assert result.recovered is False
    assert result.retryable_failure is True
    assert result.payload["error_code"] == "specialist_handoff_failed"


def test_transport_exception_is_not_manufactured_into_success():
    def invoke():
        raise RuntimeError("provider unavailable")

    result = recover_specialist_handoff(invoke)

    assert result.recovered is False
    assert result.payload["status"] == "handoff_transport_error"
    assert result.payload["error_type"] == "RuntimeError"


def test_only_explicit_handoff_codes_are_retryable():
    assert is_retryable_specialist_handoff_failure({"status": "handoff_timeout"})
    assert not is_retryable_specialist_handoff_failure({"status": "inconclusive"})
