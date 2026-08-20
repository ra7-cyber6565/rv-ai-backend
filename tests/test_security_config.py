"""Offline tests for browser CORS safety config."""
from __future__ import annotations

import pytest

from utils.security_config import allowed_cors_origins


def test_cors_defaults_to_same_origin_only():
    assert allowed_cors_origins({}) == []


def test_explicit_origins_are_parsed_and_deduped():
    env = {
        "CORS_ALLOWED_ORIGINS": "https://example.com, https://app.example.com/, https://example.com"
    }
    assert allowed_cors_origins(env) == [
        "https://example.com",
        "https://app.example.com",
    ]


def test_wildcard_is_rejected():
    with pytest.raises(RuntimeError):
        allowed_cors_origins({"CORS_ALLOWED_ORIGINS": "*"})


def test_invalid_origin_is_rejected():
    with pytest.raises(RuntimeError):
        allowed_cors_origins({"CORS_ALLOWED_ORIGINS": "example.com"})
