"""Offline tests for public-safe Gemini backup-key setup diagnostics.

The endpoint must explain why a configured backup is not a real backup without
making provider calls or leaking any credential-derived identifier.
"""
from __future__ import annotations

from utils.gemini_key_status import describe_gemini_keys
from utils.reasoning_status import reasoning_status


_K1 = "DUMMY_GEMINI_SECRET_ONE_123456789"
_K2 = "DUMMY_GEMINI_SECRET_TWO_987654321"
_K3 = "DUMMY_GEMINI_SECRET_THREE_555555"


def _assert_no_secret_metadata(payload) -> None:
    text = repr(payload)
    for secret in (_K1, _K2, _K3):
        assert secret not in text
    keys = {str(key).lower() for key in payload}
    forbidden = {"fingerprint", "fingerprints", "hash", "hashes", "key_length", "prefix", "suffix"}
    assert not (keys & forbidden)


def test_empty_setup_is_honest_and_safe():
    status = describe_gemini_keys({})
    assert status["configured_entries"] == 0
    assert status["unique_keys"] == 0
    assert status["duplicates_dropped"] == 0
    assert status["backup_slots"] == 0
    assert status["names_present"] == []
    _assert_no_secret_metadata(status)


def test_duplicate_primary_and_backup_are_not_counted_as_two_slots():
    status = describe_gemini_keys({
        "GEMINI_API_KEY": _K1,
        "GEMINI_API_KEY_2": _K1,
    })
    assert status["configured_entries"] == 2
    assert status["unique_keys"] == 1
    assert status["duplicates_dropped"] == 1
    assert status["backup_slots"] == 0
    assert status["names_present"] == ["GEMINI_API_KEY", "GEMINI_API_KEY_2"]
    assert "duplicate" in str(status["note"]).lower()
    _assert_no_secret_metadata(status)


def test_two_distinct_credentials_create_one_real_backup_slot():
    status = describe_gemini_keys({
        "GEMINI_API_KEY": _K1,
        "GEMINI_API_KEY_2": _K2,
    })
    assert status["unique_keys"] == 2
    assert status["duplicates_dropped"] == 0
    assert status["backup_slots"] == 1
    _assert_no_secret_metadata(status)


def test_wrong_variable_names_are_ignored():
    status = describe_gemini_keys({
        "Gemini API Key 2": _K1,
        "gemini_api_key": _K2,
        "GEMINI-API-KEY": _K3,
    })
    assert status["unique_keys"] == 0
    assert status["names_present"] == []
    _assert_no_secret_metadata(status)


def test_list_variables_split_and_deduplicate():
    status = describe_gemini_keys({
        "GEMINI_API_KEYS": f"{_K1}, {_K2};{_K1}\n{_K3}",
    })
    assert status["configured_entries"] == 4
    assert status["unique_keys"] == 3
    assert status["duplicates_dropped"] == 1
    assert status["backup_slots"] == 2
    assert status["names_present"] == ["GEMINI_API_KEYS"]
    _assert_no_secret_metadata(status)


def test_supported_variable_names_include_all_runtime_aliases():
    status = describe_gemini_keys({})
    supported = set(status["supported_variable_names"])
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_2",
        "GEMINI_API_KEY2",
        "GEMINI_API_KEY_9",
        "GEMINI_API_KEY9",
        "GEMINI_API_KEY_BACKUP",
        "GEMINI_API_KEY_FALLBACK",
        "GEMINI_API_KEYS",
        "GEMINI_API_KEY_LIST",
        "GEMINI_BACKUP_KEYS",
    ):
        assert name in supported


def test_reasoning_status_exposes_same_safe_setup_without_key_values(monkeypatch):
    # Freeze process-local provider health so this test cannot depend on an earlier
    # test's cooldown state. No provider/network method is called here.
    monkeypatch.setattr("utils.reasoning_status.provider_health.snapshot", lambda: {})
    env = {
        "ZERO_COST_ONLY": "true",
        "GEMINI_API_KEY": _K1,
        "GEMINI_API_KEY_2": _K1,
        "GEMINI_ZERO_COST_CONFIRMED": "true",
        "GROQ_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "OLLAMA_ENABLED": "false",
    }
    report = reasoning_status(env)
    setup = report["gemini_key_setup"]
    assert setup["unique_keys"] == 1
    assert setup["duplicates_dropped"] == 1
    assert setup["backup_slots"] == 0
    assert report["layers"]["gemini_primary"]["configured"] is True
    _assert_no_secret_metadata(setup)
    assert _K1 not in repr(report)


def test_public_parser_matches_runtime_key_pool_counts():
    # The public status parser is intentionally lightweight, while the runtime
    # pool owns the SDK credential values. Lock their supported-env semantics
    # together so a future alias change cannot make diagnostics lie.
    from research_engine.key_pool import describe as runtime_describe

    env = {
        "GEMINI_API_KEY": _K1,
        "GEMINI_API_KEY2": _K2,
        "GEMINI_API_KEY_BACKUP": _K1,
        "GEMINI_API_KEYS": f"{_K3},{_K2}",
    }
    public = describe_gemini_keys(env)
    runtime = runtime_describe(env)
    for key in (
        "names_present", "configured_entries", "unique_keys",
        "duplicates_dropped", "backup_slots",
    ):
        assert public[key] == runtime[key]
    _assert_no_secret_metadata(public)
    _assert_no_secret_metadata(runtime)


def test_diagnostic_module_contains_no_network_dependency_contract():
    # Structural guard: this utility should remain stdlib/local-env only.
    import inspect
    import utils.gemini_key_status as module

    source = inspect.getsource(module)
    for forbidden in (
        "requests.", "httpx.", "urllib.request", "google.generativeai",
        "generate_content", "list_models", "socket.",
    ):
        assert forbidden not in source
