"""Manual, stdlib-only provider check; at most one small HTTP attempt.

This is a separate diagnostic, not app/SDK/worker acceptance. It never retries,
follows redirects, switches models/keys, installs packages or launches research.
Public output contains only fixed states, bounded counts and reviewed Git IDs.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_hosted_live_settings import inspect_settings
from utils.release_identity import normalize_git_revision, repository_identity

HOST = "generativelanguage.googleapis.com"
PROMPT = "Reply with the single word OK."
MAX_OUTPUT_TOKENS = 256
MAX_RESPONSE_BYTES = 65536


def inspect_selection(env, identity):
    blockers = list(inspect_settings(env)["blocker_codes"])
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
        "GITHUB_REPOSITORY": "ra7-cyber6565/rv-ai-backend",
        "INFINITY_REPOSITORY_PRIVATE": "false",
        "INFINITY_MODEL_PROBE_REQUESTED": "true",
        "INFINITY_LIVE_COMPANY_REQUESTED": "false",
    }
    if any(env.get(k) != value for k, value in expected.items()):
        blockers.append("manual_public_probe_only_required")
    revision = normalize_git_revision(env.get("INFINITY_REVIEWED_COMMIT"))
    if (not revision or revision != env.get("GITHUB_SHA")
            or revision != identity.get("revision") or identity.get("clean") is not True):
        blockers.append("reviewed_clean_revision_required")
    if not all(re.fullmatch(r"[1-9][0-9]{0,19}", env.get(k, ""))
               for k in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")):
        blockers.append("workflow_run_identity_required")
    if not re.fullmatch(r"[a-z][a-z0-9.-]{0,99}", env.get("GEMINI_MODEL", "")):
        blockers.append("model_identifier_invalid")
    return blockers


def error_kind(status, payload):
    if status in (401, 403):
        return "auth_or_permission_failure"
    if status == 404:
        return "model_or_endpoint_not_found"
    if status == 429:
        # A generic 429 does not prove a daily cap. Only explicit quota IDs
        # distinguish daily from minute limits; mixed/absent IDs stay unknown.
        error = payload.get("error") if isinstance(payload, dict) else None
        details = error.get("details", []) if isinstance(error, dict) else []
        ids = []
        for row in details if isinstance(details, list) else []:
            violations = row.get("violations", []) if isinstance(row, dict) else []
            for item in violations if isinstance(violations, list) else []:
                value = item.get("quotaId") if isinstance(item, dict) else None
                if type(value) is str:
                    ids.append(value.lower())
        daily = any("perday" in value for value in ids)
        minute = any("perminute" in value for value in ids)
        if daily and not minute:
            return "daily_quota"
        if minute and not daily:
            return "rate_limit"
        return "quota_or_rate_limit"
    if 300 <= status < 400:
        return "redirect_not_followed"
    if status == 400:
        return "invalid_request"
    return "server_error" if 500 <= status < 600 else "provider_error"


def run_probe(env, identity, *, execute=False, connection_factory=None):
    report = {
        "schema": 1, "state": "BLOCKED", "scope": "single_small_rest_request",
        "created_at_epoch": int(time.time()),
        "code_revision": normalize_git_revision(identity.get("revision")),
        "generation_attempts": 0, "retry_calls": 0, "fallback_calls": 0,
        "http_status": None, "text_chars": 0, "request_error_kind": "none",
        "prompt_chars": len(PROMPT), "max_output_tokens": MAX_OUTPUT_TOKENS,
        "billing_state_verified": False, "remaining_quota": "UNKNOWN",
        "app_acceptance": "NOT_TESTED", "release_ready": False,
    }
    blockers = inspect_selection(env, identity)
    report["blocker_codes"] = blockers
    if blockers:
        return report
    report["workflow_run_id"] = env["GITHUB_RUN_ID"]
    report["workflow_run_attempt"] = env["GITHUB_RUN_ATTEMPT"]
    report["state"] = "PROBE_READY"
    if not execute:
        return report
    factory = connection_factory or http.client.HTTPSConnection
    connection = None
    try:
        connection = factory(HOST, timeout=30)
        body = json.dumps({
            "contents": [{"parts": [{"text": PROMPT}]}],
            "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
        }).encode("utf-8")
        report["generation_attempts"] = 1
        connection.request("POST", "/v1beta/models/" + env["GEMINI_MODEL"] + ":generateContent",
                           body=body, headers={"Content-Type": "application/json",
                                               "x-goog-api-key": env["GEMINI_API_KEY"]})
        response = connection.getresponse()
        status = response.status
        report["http_status"] = status
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        report["state"] = "MODEL_REQUEST_FAILED"
        if len(raw) > MAX_RESPONSE_BYTES:
            report["request_error_kind"] = "response_size_limit"
            return report
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = None
        if status != 200:
            report["request_error_kind"] = error_kind(status, payload)
            return report
        if not isinstance(payload, dict) or "error" in payload:
            report["request_error_kind"] = "invalid_response"
            return report
        candidates = payload.get("candidates", [])
        for row in candidates if isinstance(candidates, list) else []:
            content = row.get("content") if isinstance(row, dict) else None
            parts = content.get("parts", []) if isinstance(content, dict) else []
            for part in parts if isinstance(parts, list) else []:
                if (isinstance(part, dict) and part.get("thought") is not True
                        and type(part.get("text")) is str):
                    report["text_chars"] += len(part["text"].strip())
        report["state"] = "MODEL_RESPONSE_RECEIVED" if report["text_chars"] else "MODEL_RESPONSE_EMPTY"
        report["request_error_kind"] = "none" if report["text_chars"] else "empty_response"
    except (TimeoutError, OSError, http.client.HTTPException):
        report["state"] = "MODEL_REQUEST_FAILED"
        report["request_error_kind"] = "transport_error"
    except Exception:
        report["state"] = "MODEL_REQUEST_FAILED"
        report["request_error_kind"] = "probe_error"
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    report = run_probe(os.environ, repository_identity(ROOT), execute=args.execute)
    print(json.dumps(report, indent=2))
    if report["state"] == "BLOCKED":
        return 2
    return 0 if report["state"] in {"PROBE_READY", "MODEL_RESPONSE_RECEIVED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
