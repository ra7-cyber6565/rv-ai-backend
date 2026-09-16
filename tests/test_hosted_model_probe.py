"""Exercise real probe transport wiring with an in-memory HTTP connection."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts import run_hosted_model_probe as probe

SHA = "a" * 40
IDENTITY = {"revision": SHA, "clean": True}


def configured():
    return {
        "ZERO_COST_ONLY": "true", "GEMINI_ZERO_COST_CONFIRMED": "true",
        "GEMINI_API_KEY": "PRIVATE_TEST_KEY", "GEMINI_MODEL": "gemini-3.8-flash",
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
        "GITHUB_REPOSITORY": "ra7-cyber6565/rv-ai-backend",
        "INFINITY_REPOSITORY_PRIVATE": "false", "INFINITY_MODEL_PROBE_REQUESTED": "true",
        "INFINITY_LIVE_COMPANY_REQUESTED": "false", "INFINITY_REVIEWED_COMMIT": SHA,
        "GITHUB_SHA": SHA, "GITHUB_RUN_ID": "1234", "GITHUB_RUN_ATTEMPT": "1",
    }


class Wire:
    def __init__(self, status=200, payload=None, failure=None):
        self.status = status
        self.raw = json.dumps(payload if payload is not None else {
            "candidates": [{"content": {"parts": [{"text": "PRIVATE_RESPONSE"}]}}]
        }).encode()
        self.failure = failure
        self.calls = []
        self.opens = []
        self.closed = False

    def connect(self, host, **kwargs):
        self.opens.append((host, kwargs))
        return self

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.failure:
            raise self.failure

    def getresponse(self):
        return self

    def read(self, limit):
        assert limit == 65537
        return self.raw[:limit]

    def close(self):
        self.closed = True


def run(wire, env=None, identity=None, execute=True):
    result = probe.run_probe(env or configured(), identity or IDENTITY,
                             execute=execute, connection_factory=wire.connect)
    public = json.dumps(result)
    assert "PRIVATE" not in public and "gemini-3.8-flash" not in public
    assert result["app_acceptance"] == "NOT_TESTED"
    assert result["release_ready"] is False
    assert result["billing_state_verified"] is False
    assert result["remaining_quota"] == "UNKNOWN"
    return result


def test_exactly_one_bounded_request_returns_only_metadata():
    wire = Wire()
    result = run(wire)
    assert result["state"] == "MODEL_RESPONSE_RECEIVED"
    assert result["generation_attempts"] == 1
    assert result["retry_calls"] == result["fallback_calls"] == 0
    assert wire.opens == [(probe.HOST, {"timeout": 30})]
    assert len(wire.calls) == 1 and wire.closed
    args, kwargs = wire.calls[0]
    assert args == ("POST", "/v1beta/models/gemini-3.8-flash:generateContent")
    assert kwargs["headers"]["x-goog-api-key"] == "PRIVATE_TEST_KEY"
    body = json.loads(kwargs["body"])
    assert body["generationConfig"] == {"maxOutputTokens": 256}
    assert len(body["contents"][0]["parts"][0]["text"]) < 100


@pytest.mark.parametrize("key,value", [
    ("ZERO_COST_ONLY", "false"), ("GEMINI_ZERO_COST_CONFIRMED", "false"),
    ("GEMINI_API_KEY", ""), ("GEMINI_MODEL", "../PRIVATE?key=PRIVATE"),
    ("GEMINI_MODEL", ""), ("GITHUB_EVENT_NAME", "push"),
    ("GITHUB_EVENT_NAME", "pull_request"), ("INFINITY_REPOSITORY_PRIVATE", "true"),
    ("INFINITY_MODEL_PROBE_REQUESTED", "false"), ("INFINITY_LIVE_COMPANY_REQUESTED", "true"),
    ("INFINITY_REVIEWED_COMMIT", "b" * 40), ("GITHUB_SHA", "b" * 40),
    ("GITHUB_RUN_ID", "PRIVATE"), ("GITHUB_RUN_ATTEMPT", "0"),
    ("RUNNER_ENVIRONMENT", "self-hosted"), ("GITHUB_REPOSITORY", "unknown/repo"),
])
def test_unsafe_or_unconfirmed_execution_makes_zero_connections(key, value):
    wire = Wire()
    result = run(wire, dict(configured(), **{key: value}))
    assert result["state"] == "BLOCKED" and result["generation_attempts"] == 0
    assert wire.opens == wire.calls == []


def test_dirty_code_and_default_preflight_make_zero_connections():
    for identity, execute, expected in [
        ({"revision": SHA, "clean": False}, True, "BLOCKED"),
        ({"revision": "b" * 40, "clean": True}, True, "BLOCKED"),
        (IDENTITY, False, "PROBE_READY"),
    ]:
        wire = Wire()
        assert run(wire, identity=identity, execute=execute)["state"] == expected
        assert wire.opens == wire.calls == []


@pytest.mark.parametrize("status,expected", [
    (301, "redirect_not_followed"), (307, "redirect_not_followed"),
    (400, "invalid_request"), (401, "auth_or_permission_failure"),
    (403, "auth_or_permission_failure"), (404, "model_or_endpoint_not_found"),
    (429, "quota_or_rate_limit"), (503, "server_error"),
])
def test_http_failure_never_retries_falls_back_or_follows_redirect(status, expected):
    wire = Wire(status, {"error": {"message": "PRIVATE provider body"}})
    result = run(wire)
    assert result["request_error_kind"] == expected
    assert result["state"] == "MODEL_REQUEST_FAILED"
    assert len(wire.calls) == 1 and wire.closed


@pytest.mark.parametrize("ids,expected", [
    (["GenerateRequestsPerDay"], "daily_quota"),
    (["GenerateRequestsPerMinute"], "rate_limit"),
    (["GenerateRequestsPerDay", "GenerateRequestsPerMinute"], "quota_or_rate_limit"),
    (["PRIVATE"], "quota_or_rate_limit"),
])
def test_only_explicit_quota_ids_distinguish_daily_from_minute(ids, expected):
    wire = Wire(429, {"error": {"details": [{"violations": [{"quotaId": x} for x in ids]}]}})
    assert run(wire)["request_error_kind"] == expected
    assert len(wire.calls) == 1


@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE"), RuntimeError("PRIVATE")])
def test_exception_messages_and_types_never_escape_or_trigger_retry(failure):
    wire = Wire(failure=failure)
    assert run(wire)["state"] == "MODEL_REQUEST_FAILED"
    assert len(wire.calls) == 1 and wire.closed


@pytest.mark.parametrize("payload,state", [
    ({"candidates": []}, "MODEL_RESPONSE_EMPTY"),
    ({"candidates": [{"content": {"parts": [{"thought": True, "text": "PRIVATE"}]}}]},
     "MODEL_RESPONSE_EMPTY"),
    ({"error": "PRIVATE"}, "MODEL_REQUEST_FAILED"),
    (["PRIVATE"], "MODEL_REQUEST_FAILED"),
])
def test_empty_or_invalid_content_is_not_success(payload, state):
    assert run(Wire(payload=payload))["state"] == state


def test_oversized_and_malformed_responses_are_bounded_and_private():
    for raw, expected in [(b"PRIVATE" * 20000, "response_size_limit"),
                          (b"PRIVATE-not-json", "invalid_response")]:
        wire = Wire()
        wire.raw = raw
        assert run(wire)["request_error_kind"] == expected
        assert wire.closed


def test_cli_runs_without_site_packages_and_without_configuration():
    script = Path(probe.__file__)
    result = subprocess.run([sys.executable, "-I", "-S", str(script)],
                            env={}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and not result.stderr
    assert json.loads(result.stdout)["generation_attempts"] == 0


def test_workflow_keeps_probe_manual_separate_and_secrets_at_execution_step():
    root = Path(probe.__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/foundation-tests.yml").read_text())
    jobs = workflow["jobs"]
    job = jobs["model-probe"]
    assert "workflow_dispatch" in job["if"] and "inputs.model_probe_only" in job["if"]
    assert "!(github.event_name == 'workflow_dispatch' && inputs.model_probe_only)" in jobs["offline-regression"]["if"]
    assert "secrets." not in json.dumps({k: v for k, v in job.items() if k != "steps"})
    assert len(job["steps"]) == 2
    assert "secrets." not in json.dumps(job["steps"][0])
    step = job["steps"][1]
    assert step["run"] == "python3 -I -S scripts/run_hosted_model_probe.py --execute"
    assert step["env"]["INFINITY_LIVE_COMPANY_REQUESTED"] == "${{ inputs.live_company }}"
    assert "run_hosted_live_gate" not in json.dumps(job)
