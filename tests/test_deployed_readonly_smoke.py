"""Deployed zero-model smoke contract tests (all fake transport)."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from scripts.run_deployed_readonly_smoke import (
    DeployedReadonlySmoke,
    HttpResult,
    normalize_base_url,
)


def _response(status: int, payload: dict, headers: dict | None = None) -> HttpResult:
    return HttpResult(
        status=status,
        headers={str(k).casefold(): str(v) for k, v in (headers or {}).items()},
        body=json.dumps(payload).encode("utf-8"),
    )


class FakeDeployment:
    token = "project-token-with-more-than-twenty-four-characters"
    project_id = "p_project_identifier_long_enough"
    revision = "2a21a6fbcb0771be746766dad3c6a511a7c3ec5e"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes) -> HttpResult:
        path = urlsplit(url).path
        self.requests.append((method, path, dict(headers)))
        common = {
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        }
        if method == "GET" and path == "/health":
            return _response(200, {
                "status": "healthy",
                "service": "RV AI Backend",
                "zero_cost_only": True,
                "release_state": "foundation_verification_pending",
                "build_revision": self.revision,
                "storage": {"available": True},
            })
        if method == "GET" and path == "/api":
            return _response(200, {
                "zero_cost_only": True,
                "release_state": "foundation_verification_pending",
                "endpoints": [
                    "POST /api/v1/session",
                    "GET /api/v1/processing-capabilities",
                ],
            })
        if method == "GET" and path == "/api/v1/processing-capabilities":
            return _response(200, {
                "pdf_text": {"available": True},
                "full_text_fetch": {"enabled": True},
            }, common)
        if method == "POST" and path == "/api/v1/session":
            return _response(201, {
                "project_id": self.project_id,
                "project_access_token": self.token,
            }, common)
        if method == "GET" and path == "/api/v1/reading-sessions":
            if headers.get("X-Project-Token") != self.token:
                # Match the production anti-enumeration contract: missing,
                # malformed and wrong capabilities are indistinguishable.
                return _response(404, {"detail": "Project session nahi mila"}, common)
            return _response(200, {"sessions": []}, common)
        if method == "OPTIONS" and path == "/api/v1/session":
            return _response(200, {}, {
                **common,
                "Access-Control-Allow-Origin": headers.get("Origin", ""),
            })
        raise AssertionError(f"unexpected smoke request: {method} {path}")


def test_complete_probe_is_zero_model_and_receipt_has_no_capability():
    fake = FakeDeployment()
    result = DeployedReadonlySmoke(
        "https://research.example",
        expected_origin="https://android-web.example",
        expected_revision=fake.revision,
        transport=fake,
    ).run()

    assert result["complete"] is True
    assert result["zero_model_calls_by_construction"] is True
    assert result["capabilities_or_secrets_recorded"] is False
    assert result["expected_code_revision"] == fake.revision
    assert result["deployed_code_revision"] == fake.revision
    serialized = json.dumps(result)
    assert fake.token not in serialized
    assert fake.project_id not in serialized
    paths = [path for _method, path, _headers in fake.requests]
    assert not any("/chat" in path or "/research" in path or "/upload" in path
                   for path in paths)
    assert all(row["passed"] is True for row in result["checks"])


def test_private_path_or_raw_trace_in_health_turns_gate_red():
    fake = FakeDeployment()
    original = fake.__call__

    def leaking(method: str, url: str, headers: dict, body: bytes) -> HttpResult:
        if urlsplit(url).path == "/health":
            return _response(200, {
                "status": "healthy",
                "zero_cost_only": True,
                "release_state": "foundation_verification_pending",
                "storage_path": "C:\\Users\\intel\\private",
                "error": "Traceback (most recent call last): secret",
            })
        return original(method, url, headers, body)

    result = DeployedReadonlySmoke(
        "https://research.example", transport=leaking,
    ).run()
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["health_public_payload_safe"] is False
    assert result["complete"] is False


def test_wrong_or_missing_deployed_revision_turns_gate_red():
    fake = FakeDeployment()
    fake.revision = "1" * 40
    result = DeployedReadonlySmoke(
        "https://research.example",
        expected_revision="2" * 40,
        transport=fake,
    ).run()
    checks = {row["name"]: row["passed"] for row in result["checks"]}
    assert checks["deployed_revision_matches"] is False
    assert result["complete"] is False


def test_expected_revision_requires_a_full_sha():
    with pytest.raises(ValueError):
        DeployedReadonlySmoke(
            "https://research.example",
            expected_revision="2a21a6f",
            transport=FakeDeployment(),
        )


@pytest.mark.parametrize("value", [
    "", "research.example", "ftp://research.example",
    "https://user:pass@research.example", "https://research.example/api",
    "https://research.example?token=x", "http://research.example",
])
def test_unsafe_base_urls_are_rejected(value: str):
    with pytest.raises(ValueError):
        normalize_base_url(value)


def test_http_is_allowed_only_for_explicit_local_smoke():
    assert normalize_base_url(
        "http://127.0.0.1:8000/", allow_http_local=True,
    ) == "http://127.0.0.1:8000"
    with pytest.raises(ValueError):
        normalize_base_url("http://example.com", allow_http_local=True)
