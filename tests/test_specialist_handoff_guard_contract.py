from research_engine.specialist_handoff_guard import recover_specialist_handoff


def test_custom_success_predicate_prevents_false_recovery():
    responses = iter([
        {"status": "specialist_handoff_failed"},
        {"status": "ok", "payload": ""},
    ])

    result = recover_specialist_handoff(
        lambda: next(responses),
        success_predicate=lambda value: bool(value.get("payload")),
    )

    assert result.recovered is False
    assert result.payload == {"status": "ok", "payload": ""}
