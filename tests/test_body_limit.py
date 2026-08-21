"""Offline tests for raw ASGI request-body caps."""
from __future__ import annotations

import asyncio
from pathlib import Path

from utils.body_limit import RequestBodyLimitMiddleware, request_body_limit


ROOT = Path(__file__).resolve().parents[1]


def _scope(path: str, *, content_length: int | None = None) -> dict:
    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }


def _run(middleware, scope, messages):
    sent = []
    queue = list(messages)

    async def receive():
        if queue:
            return queue.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent


def test_route_limits_match_endpoint_intent():
    assert request_body_limit("GET", "/api/v1/chat") is None
    assert request_body_limit("POST", "/health") is None
    assert request_body_limit("POST", "/api/v1/session") == 8 * 1024
    assert request_body_limit("POST", "/api/v1/chat") == 256 * 1024
    assert request_body_limit("POST", "/api/v1/upload-document") == 64 * 1024 * 1024
    assert request_body_limit("POST", "/api/v1/upload-pdf") == 64 * 1024 * 1024
    assert request_body_limit("POST", "/api/v1/upload-audio") == 205 * 1024 * 1024
    assert request_body_limit("POST", "/api/v1/transcribe-audio") == 205 * 1024 * 1024


def test_oversized_declared_body_is_rejected_before_downstream():
    called = {"value": False}

    async def app(scope, receive, send):  # noqa: ARG001
        called["value"] = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestBodyLimitMiddleware(app)
    limit = request_body_limit("POST", "/api/v1/chat")
    sent = _run(
        middleware,
        _scope("/api/v1/chat", content_length=limit + 1),
        [{"type": "http.request", "body": b"", "more_body": False}],
    )
    assert called["value"] is False
    assert sent[0]["status"] == 413
    headers = dict(sent[0]["headers"])
    assert headers[b"cache-control"] == b"no-store"
    assert b"allowed size" in sent[1]["body"]


def test_chunked_body_cannot_bypass_limit_without_content_length():
    async def consuming_app(scope, receive, send):  # noqa: ARG001
        while True:
            message = await receive()
            if message.get("type") != "http.request" or not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestBodyLimitMiddleware(consuming_app)
    first = b"a" * (200 * 1024)
    second = b"b" * (70 * 1024)
    sent = _run(
        middleware,
        _scope("/api/v1/chat"),
        [
            {"type": "http.request", "body": first, "more_body": True},
            {"type": "http.request", "body": second, "more_body": False},
        ],
    )
    assert sent[0]["status"] == 413


def test_under_limit_chunked_body_reaches_downstream():
    seen = {"bytes": 0}

    async def consuming_app(scope, receive, send):  # noqa: ARG001
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                break
            seen["bytes"] += len(message.get("body") or b"")
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestBodyLimitMiddleware(consuming_app)
    sent = _run(
        middleware,
        _scope("/api/v1/chat"),
        [
            {"type": "http.request", "body": b"a" * 1024, "more_body": True},
            {"type": "http.request", "body": b"b" * 1024, "more_body": False},
        ],
    )
    assert seen["bytes"] == 2048
    assert sent[0]["status"] == 204


def test_main_wires_raw_body_limit_before_route_parsing():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from utils.body_limit import RequestBodyLimitMiddleware" in text
    assert "app.add_middleware(RequestBodyLimitMiddleware)" in text
