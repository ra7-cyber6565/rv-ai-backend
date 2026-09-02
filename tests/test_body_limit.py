"""Offline tests for raw ASGI request-body caps.

`from __future__ import annotations` yahan JAAN-BOOJH KAR nahi hai (2026-08-23):
    Us import se saare annotation string ban jaate hain. Neeche
    `test_fastapi_integration_rejects_before_json_handler` ke andar `Request`
    function-local import hai, isliye FastAPI/pydantic string "Request" ko
    module ke globals me dhoondhta hai - wahan wo nahi milta aur test
    `PydanticUndefinedAnnotation: name 'Request' is not defined` de kar girta
    hai (product code bilkul theek hota hai). Bina future-import annotation
    def-time par asli class ban jaata hai. `int | None` Python 3.10+ par
    native chalta hai aur repo 3.11/3.12 use karta hai, isliye kuch khota nahi.
"""

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


def test_fastapi_integration_rejects_before_json_handler():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    called = {"value": False}
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.post("/api/v1/chat")
    async def endpoint(request: Request):
        called["value"] = True
        await request.body()
        return {"ok": True}

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat",
        content=b"x" * (256 * 1024 + 1),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert called["value"] is False
    assert response.headers["cache-control"] == "no-store"


def test_local_class_annotations_stay_eager_for_fastapi_resolution():
    """Guard: file ke top par future-import wapas aaya to ye test red hoga.

    FastAPI function-local `Request` annotation ko sirf tab resolve kar paata
    hai jab annotation def-time par asli object bane. Lazy (string) annotation
    ke saath wahi `PydanticUndefinedAnnotation` wapas aa jaayega.
    """
    class _LocalMarker:
        pass

    def probe(value: _LocalMarker) -> None:  # noqa: ARG001
        return None

    annotation = probe.__annotations__["value"]
    assert annotation is _LocalMarker, (
        "annotation lazy string ban gaya (%r) - tests/test_body_limit.py se "
        "`from __future__ import annotations` hataya hi rehna chahiye" % (annotation,)
    )


def test_main_wires_raw_body_limit_outermost_before_route_parsing():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from utils.body_limit import RequestBodyLimitMiddleware" in text
    body_guard = text.index("app.add_middleware(RequestBodyLimitMiddleware)")
    quota_middleware = text.index('@app.middleware("http")')
    first_router = text.index("app.include_router(")
    # Starlette inserts newly-added user middleware at the outside of the stack.
    # Body limit must therefore be added after the decorator middleware but
    # before routers/runtime starts serving requests.
    assert quota_middleware < body_guard < first_router
