#!/usr/bin/env python3
"""Zero-model deployed API smoke gate.

This probe never calls chat, research, upload, reasoning or provider endpoints.
It checks only public runtime metadata, local processing capability reporting,
anonymous capability issuance and access isolation around an empty project.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.release_identity import normalize_git_revision, repository_identity


PRIVATE_VALUE_RE = re.compile(
    r"(?:[A-Za-z]:\\(?:Users|ProgramData|Windows|InfinityResearchAI)\\|"
    r"/(?:home|root|workspace|tmp)/)", re.IGNORECASE,
)
RAW_ERROR_RE = re.compile(
    r"(?:Traceback \(most recent call last\)|File \"[^\"]+\", line \d+|"
    r"ResourceExhausted|grpc_status|protobuf|sk-[A-Za-z0-9_-]{12,})",
    re.IGNORECASE,
)
FORBIDDEN_MODEL_ROUTE_RE = re.compile(
    r"/(?:chat|research|agent|jobs?)(?:/|$)", re.IGNORECASE,
)


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Dict[str, str]
    body: bytes


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    passed: bool
    detail: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def normalize_base_url(value: str, *, allow_http_local: bool = False) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Base URL absolute http(s) origin hona chahiye")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Base URL mein credentials, query ya fragment allowed nahi")
    if parsed.path not in {"", "/"}:
        raise ValueError("Base URL sirf deployment origin ho; extra path mat dein")
    local = parsed.hostname.casefold() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (allow_http_local and local):
        raise ValueError("Remote deployment smoke ke liye HTTPS required hai")
    port = f":{parsed.port}" if parsed.port else ""
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return urlunsplit((parsed.scheme, f"{host}{port}", "", "", ""))


def _stdlib_transport(timeout: float) -> Callable[..., HttpResult]:
    opener = build_opener(_NoRedirect())

    def send(method: str, url: str, headers: Mapping[str, str], body: bytes) -> HttpResult:
        request = Request(url, data=body or None, headers=dict(headers), method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                return HttpResult(
                    status=int(response.status),
                    headers={str(k).casefold(): str(v) for k, v in response.headers.items()},
                    body=response.read(1_000_001),
                )
        except HTTPError as exc:
            return HttpResult(
                status=int(exc.code),
                headers={str(k).casefold(): str(v) for k, v in exc.headers.items()},
                body=exc.read(1_000_001),
            )
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("Deployment endpoint tak safe HTTP request nahi pahunchi") from exc

    return send


def _json(response: HttpResult) -> Dict:
    if len(response.body) > 1_000_000:
        raise ValueError("Response 1 MB safety bound se badi hai")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Expected bounded UTF-8 JSON response nahi mila") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object nahi mila")
    return value


def _public_payload_safe(value: object) -> bool:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return not PRIVATE_VALUE_RE.search(text) and not RAW_ERROR_RE.search(text)


class DeployedReadonlySmoke:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        expected_origin: str = "",
        expected_revision: str = "",
        transport: Optional[Callable[..., HttpResult]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        raw_origin = str(expected_origin or "").strip()
        self.expected_origin = (
            normalize_base_url(raw_origin, allow_http_local=True)
            if raw_origin else ""
        )
        raw_revision = str(expected_revision or "").strip()
        self.expected_revision = normalize_git_revision(raw_revision)
        if raw_revision and not self.expected_revision:
            raise ValueError("Expected commit poora 40-character Git SHA hona chahiye")
        self.transport = transport or _stdlib_transport(timeout)
        self.checks: list[SmokeCheck] = []
        self.calls: list[str] = []

    def _check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(SmokeCheck(name, bool(passed), str(detail)))

    def _call(
        self, method: str, path: str, *, headers: Optional[Mapping[str, str]] = None,
    ) -> HttpResult:
        if FORBIDDEN_MODEL_ROUTE_RE.search(path):
            raise RuntimeError(f"Zero-model smoke ne forbidden route rok di: {path}")
        self.calls.append(f"{method} {path.split('?', 1)[0]}")
        return self.transport(method, f"{self.base_url}{path}", headers or {}, b"")

    def run(self) -> Dict:
        health_response = self._call("GET", "/health")
        self._check("health_http", health_response.status == 200,
                    f"HTTP {health_response.status}")
        health = _json(health_response) if health_response.status == 200 else {}
        self._check("health_state", health.get("status") == "healthy",
                    str(health.get("status") or "missing"))
        self._check("zero_cost_only", health.get("zero_cost_only") is True,
                    str(health.get("zero_cost_only")))
        self._check(
            "release_state_honest",
            health.get("release_state") == "foundation_verification_pending",
            str(health.get("release_state") or "missing"),
        )
        deployed_revision = normalize_git_revision(health.get("build_revision"))
        if self.expected_revision:
            self._check(
                "deployed_revision_matches",
                deployed_revision == self.expected_revision,
                (
                    "exact expected Git revision"
                    if deployed_revision else "missing/invalid build revision"
                ),
            )
        self._check("health_public_payload_safe", _public_payload_safe(health),
                    "private path/raw provider trace absent")

        api_response = self._call("GET", "/api")
        self._check("api_http", api_response.status == 200,
                    f"HTTP {api_response.status}")
        api = _json(api_response) if api_response.status == 200 else {}
        endpoints = list(api.get("endpoints") or [])
        self._check("session_route_advertised",
                    any("POST /api/v1/session" == row for row in endpoints),
                    f"{len(endpoints)} endpoint(s) advertised")
        self._check("processing_route_advertised",
                    any("GET /api/v1/processing-capabilities" == row for row in endpoints),
                    "processing capability route")
        self._check("api_public_payload_safe", _public_payload_safe(api),
                    "private path/raw provider trace absent")

        processing_response = self._call("GET", "/api/v1/processing-capabilities")
        self._check("processing_http", processing_response.status == 200,
                    f"HTTP {processing_response.status}")
        processing = _json(processing_response) if processing_response.status == 200 else {}
        self._check("processing_contract",
                    isinstance(processing.get("pdf_text"), dict)
                    and isinstance(processing.get("full_text_fetch"), dict),
                    "PDF and legal full-text capability states present")
        self._check("processing_public_payload_safe", _public_payload_safe(processing),
                    "private path/raw provider trace absent")

        session_response = self._call("POST", "/api/v1/session")
        self._check("session_http", session_response.status == 201,
                    f"HTTP {session_response.status}")
        session = _json(session_response) if session_response.status == 201 else {}
        project_id = str(session.get("project_id") or "")
        token = str(session.get("project_access_token") or "")
        self._check("session_capability_shape",
                    len(project_id) >= 16 and len(token) >= 24,
                    "opaque project id/token issued" if project_id and token else "missing")
        cache = session_response.headers.get("cache-control", "").casefold()
        pragma = session_response.headers.get("pragma", "").casefold()
        robots = session_response.headers.get("x-robots-tag", "").casefold()
        self._check("private_no_store_headers",
                    "no-store" in cache and "no-cache" in pragma and "noindex" in robots,
                    "Cache-Control/Pragma/X-Robots-Tag")

        if project_id and token:
            query = urlencode({"project_id": project_id})
            unauth = self._call("GET", f"/api/v1/reading-sessions?{query}")
            # Production deliberately returns the same 404 for a missing,
            # malformed or wrong capability so callers cannot use this route
            # as a project-namespace enumeration oracle. 401/403 remain valid
            # for compatible deployments, but 404 is the hardened contract.
            self._check("missing_capability_rejected", unauth.status in {401, 403, 404},
                        f"HTTP {unauth.status}")
            authorised = self._call(
                "GET", f"/api/v1/reading-sessions?{query}",
                headers={"X-Project-Token": token},
            )
            authorised_json = _json(authorised) if authorised.status == 200 else {}
            self._check("empty_project_capability_accepted",
                        authorised.status == 200
                        and isinstance(authorised_json.get("sessions"), list),
                        f"HTTP {authorised.status}")
            self._check("private_list_no_store",
                        "no-store" in authorised.headers.get("cache-control", "").casefold(),
                        "authorised private response")

        if self.expected_origin:
            cors = self._call(
                "OPTIONS", "/api/v1/session",
                headers={
                    "Origin": self.expected_origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            allow = cors.headers.get("access-control-allow-origin", "")
            self._check("cors_exact_origin",
                        cors.status in {200, 204}
                        and allow == self.expected_origin and allow != "*",
                        f"HTTP {cors.status}; allow-origin={allow or 'missing'}")

        forbidden = [call for call in self.calls
                     if FORBIDDEN_MODEL_ROUTE_RE.search(call.split(" ", 1)[1])]
        self._check("no_model_or_research_route_called", not forbidden,
                    f"{len(self.calls)} bounded non-model request(s)")
        passed = all(check.passed for check in self.checks)
        return {
            "gate": "DEPLOYED_READONLY_ZERO_MODEL_SMOKE",
            "complete": passed,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "target_origin": self.base_url,
            "expected_code_revision": self.expected_revision,
            "deployed_code_revision": deployed_revision,
            "zero_model_calls_by_construction": True,
            "checks": [asdict(check) for check in self.checks],
            "calls": list(self.calls),
            "capabilities_or_secrets_recorded": False,
        }


def _write_receipt(path: str, result: Dict) -> None:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a zero-model deployed API smoke gate.")
    parser.add_argument("--base-url", required=True, help="Deployment origin, e.g. https://app.example")
    parser.add_argument("--execute", action="store_true",
                        help="Actually make the bounded HTTP requests. Without this, no call is made.")
    parser.add_argument("--expected-origin", default="",
                        help="Optional frontend origin whose exact CORS grant must pass.")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--receipt", default="",
                        help="Optional non-secret JSON receipt path.")
    parser.add_argument(
        "--expected-commit", default="",
        help="Expected full Git SHA; defaults to the current clean checkout.",
    )
    parser.add_argument("--allow-http-local", action="store_true",
                        help="Allow http://localhost only; remote targets still require HTTPS.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        base = normalize_base_url(args.base_url, allow_http_local=args.allow_http_local)
        raw_expected = str(args.expected_commit or "").strip()
        expected_revision = normalize_git_revision(raw_expected)
        if raw_expected and not expected_revision:
            raise ValueError("Expected commit poora 40-character Git SHA hona chahiye")
        if not expected_revision:
            identity = repository_identity(ROOT)
            if not identity["available"]:
                raise ValueError(
                    "Current Git revision safely resolve nahi hui; --expected-commit dein"
                )
            if not identity["clean"]:
                raise ValueError(
                    "Current Git checkout clean nahi hai; pehle changes commit karein"
                )
            expected_revision = str(identity["revision"])
    except ValueError as exc:
        print(f"DEPLOYED SMOKE: BLOCKED — {exc}")
        return 2
    if not args.execute:
        print("DEPLOYED SMOKE PREFLIGHT: READY")
        print("No HTTP call made. Add --execute when the deployed read-only smoke is intended.")
        return 0
    try:
        result = DeployedReadonlySmoke(
            base,
            timeout=max(1.0, min(float(args.timeout_seconds), 60.0)),
            expected_origin=args.expected_origin,
            expected_revision=expected_revision,
        ).run()
    except (RuntimeError, ValueError) as exc:
        print(f"DEPLOYED SMOKE: FAIL — {exc}")
        return 1
    for check in result["checks"]:
        tag = "PASS" if check["passed"] else "FAIL"
        print(f"[{tag}] {check['name']}: {check['detail']}")
    if args.receipt:
        _write_receipt(args.receipt, result)
        print(f"Receipt: {Path(args.receipt).expanduser().resolve()}")
    print("DEPLOYED READONLY SMOKE: " + ("PASS" if result["complete"] else "FAIL"))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
