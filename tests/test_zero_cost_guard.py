"""Offline tests for the hard zero-cost runtime guard."""
from utils.zero_cost_guard import (
    enforce_zero_cost_config,
    gemini_credentials_configured,
    inspect_zero_cost_config,
    zero_cost_enabled,
)


def test_zero_cost_mode_defaults_on():
    assert zero_cost_enabled({}) is True


def test_paid_vendor_key_is_blocked_in_zero_cost_mode():
    status = inspect_zero_cost_config({"OPENAI_API_KEY": "secret"})
    assert status.enabled is True
    assert status.ok is False
    assert "OPENAI_API_KEY" in status.blocked_keys


def test_multiple_paid_vendor_keys_are_reported():
    status = inspect_zero_cost_config({
        "OPENAI_API_KEY": "x",
        "ANTHROPIC_API_KEY": "y",
    })
    assert status.blocked_keys == ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def test_guard_raises_when_paid_key_present():
    try:
        enforce_zero_cost_config({"ANTHROPIC_API_KEY": "secret"})
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)


def test_gemini_key_is_blocked_until_owner_confirms_no_paid_billing_path():
    status = inspect_zero_cost_config({"GEMINI_API_KEY": "secret"})
    assert status.enabled is True
    assert status.ok is False
    assert any("GEMINI_ZERO_COST_CONFIRMED" in item for item in status.blocked_keys)


def test_backup_only_gemini_key_cannot_bypass_zero_cost_confirmation():
    env = {"GEMINI_API_KEY_2": "backup-secret"}
    assert gemini_credentials_configured(env) is True
    status = inspect_zero_cost_config(env)
    assert status.ok is False
    assert any("GEMINI_ZERO_COST_CONFIRMED" in item for item in status.blocked_keys)


def test_list_only_gemini_keys_cannot_bypass_zero_cost_confirmation():
    env = {"GEMINI_API_KEYS": "one,two"}
    assert gemini_credentials_configured(env) is True
    status = inspect_zero_cost_config(env)
    assert status.ok is False


def test_all_supported_backup_variable_shapes_are_detected():
    names = [
        "GEMINI_API_KEY_BACKUP",
        "GEMINI_API_KEY_FALLBACK",
        "GEMINI_API_KEY_LIST",
        "GEMINI_BACKUP_KEYS",
        "GEMINI_API_KEY_9",
        "GEMINI_API_KEY9",
    ]
    for name in names:
        assert gemini_credentials_configured({name: "x"}) is True, name


def test_confirmed_zero_cost_gemini_key_is_allowed():
    status = enforce_zero_cost_config({
        "GEMINI_API_KEY": "secret",
        "GEMINI_API_KEY_2": "backup",
        "GEMINI_ZERO_COST_CONFIRMED": "true",
    })
    assert status.ok is True
    assert status.blocked_keys == ()


def test_false_gemini_confirmation_is_not_accepted():
    try:
        enforce_zero_cost_config({
            "GEMINI_API_KEY": "secret",
            "GEMINI_ZERO_COST_CONFIRMED": "false",
        })
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "paid billing/spend path" in str(exc)


def test_explicit_opt_out_allows_paid_key_for_future_manual_use():
    status = enforce_zero_cost_config({
        "ZERO_COST_ONLY": "false",
        "OPENAI_API_KEY": "secret",
        "GEMINI_API_KEY": "secret",
        "GEMINI_API_KEY_2": "backup",
    })
    assert status.enabled is False
    assert status.ok is True
