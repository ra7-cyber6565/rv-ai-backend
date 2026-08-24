"""ASGI request-body limits before FastAPI/multipart parsing.

Route-level validators and ``UploadFile.read()`` limits are necessary but they run
*after* Starlette has started parsing the HTTP request. A hostile chunked request
could therefore make the framework buffer/spool far more data than the endpoint
intends to accept. This middleware counts raw ``http.request`` bytes at the ASGI
boundary and fails with 413 before application parsing can consume an oversized
body.

The limits intentionally leave modest multipart overhead above the actual file
caps in ``api.routes``:
- documents/PDF: 60 MiB file -> 64 MiB HTTP body;
- audio/video: 200 MiB file -> 205 MiB HTTP body;
- normal JSON/API POSTs: 256 KiB by default.

No client address, body content, token or exception detail is logged/returned.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable


_MIB = 1024 * 1024
_DEFAULT_API_BYTES = 256 * 1024
_DOC_BODY_BYTES = 64 * _MIB
_AUDIO_BODY_BYTES = 205 * _MIB
_SESSION_BODY_BYTES = 8 * 1024
_EXAM_BODY_BYTES = 4 * _MIB

_ROUTE_LIMITS = {
    "/api/v1/session": _SESSION_BODY_BYTES,
    "/api/v1/upload-document": _DOC_BODY_BYTES,
    "/api/v1/upload-pdf": _DOC_BODY_BYTES,
    "/api/v1/upload-audio": _AUDIO_BODY_BYTES,
    "/api/v1/transcribe-audio": _AUDIO_BODY_BYTES,
    "/api/v1/exam-intelligence/analyze": _EXAM_BODY_BYTES,
}


class RequestBodyTooLarge(Exception):
    pass


def request_body_limit(method: object, path: object) -> int | None:
    """Return raw HTTP-body cap for mutating API requests; ``None`` otherwise."""
    verb = str(method or "").upper()
    route = str(path or "")
    if verb not in {"POST", "PUT", "PATCH"}:
        return None
    if not route.startswith("/api/v1/"):
        return None
    return int(_ROUTE_LIMITS.get(route, _DEFAULT_API_BYTES))


def _content_length(headers) -> int | None:
    for key, value in list(headers or []):
        if bytes(key).lower() != b"content-length":
            continue
        try:
            parsed = int(bytes(value).decode("ascii", errors="strict").strip())
        except (TypeError, ValueError, UnicodeError):
            return None
        return parsed if parsed >= 0 else None
    return None


class RequestBodyLimitMiddleware:
    """Pure ASGI middleware so chunked bodies are bounded before parsing."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    async def _send_413(send: Callable[[dict], Awaitable[None]], limit: int) -> None:
        payload = json.dumps(
            {
                "detail": "Request body allowed size se badi hai.",
                "max_request_bytes": int(limit),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
            ],
        })
        await send({"type": "http.response.body", "body": payload, "more_body": False})

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = request_body_limit(scope.get("method"), scope.get("path"))
        if limit is None:
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope.get("headers"))
        if declared is not None and declared > limit:
            await self._send_413(send, limit)
            return

        consumed = 0
        response_started = False

        async def guarded_receive():
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body") or b"")
                if consumed > limit:
                    raise RequestBodyTooLarge()
            return message

        async def tracked_send(message: dict):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, tracked_send)
        except RequestBodyTooLarge:
            # Request parsing normally happens before a response starts. If an
            # unusual downstream app started streaming a response first, we
            # cannot legally send a second HTTP response; fail closed by ending.
            if not response_started:
                await self._send_413(send, limit)


__all__ = [
    "RequestBodyLimitMiddleware",
    "RequestBodyTooLarge",
    "request_body_limit",
]
