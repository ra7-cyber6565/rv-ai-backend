"""Offline regression tests for discovery/full-text network boundaries."""
from __future__ import annotations

import sys
import types

import pytest

from research_engine.connectors import base as connector_base
from research_engine.content_fetcher import ContentFetcher
from research_engine.models import SourceRecord
from research_engine.network_safety import (
    ResponseTooLarge,
    UnexpectedContentType,
    UnsafeRedirect,
    UnsafeURL,
    read_bounded_response,
    require_content_type,
    safe_get_with_redirects,
    validate_public_http_url,
)


class _Response:
    def __init__(self, *, status=200, headers=None, chunks=(), content=b""):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.content = content
        self.closed = False

    def iter_content(self, chunk_size=64 * 1024):
        del chunk_size
        yield from self._chunks

    def close(self):
        self.closed = True


def test_private_local_credential_and_nonstandard_targets_are_blocked():
    blocked = (
        "http://localhost/report.pdf",
        "http://127.0.0.1/report.pdf",
        "http://10.2.3.4/report.pdf",
        "http://169.254.169.254/latest/meta-data/report.pdf",
        "http://[::1]/report.pdf",
        "https://service.internal/report.pdf",
        "https://user:secret@example.org/report.pdf",
        "https://example.org:22/report.pdf",
        "file:///etc/passwd",
    )
    for url in blocked:
        with pytest.raises(UnsafeURL):
            validate_public_http_url(url, resolve_dns=False)


def test_public_literal_and_normal_https_host_are_allowed_without_dns():
    assert validate_public_http_url("https://8.8.8.8/report.pdf", resolve_dns=False)
    assert validate_public_http_url("https://example.org/report.pdf", resolve_dns=False)


def test_untrusted_dns_name_fails_if_any_resolved_address_is_private(monkeypatch):
    monkeypatch.setattr(
        "research_engine.network_safety._resolved_addresses",
        lambda _host: ["93.184.216.34", "127.0.0.1"],
    )
    with pytest.raises(UnsafeURL):
        validate_public_http_url("https://example.org/report.pdf", resolve_dns=True)


def test_redirect_to_cloud_metadata_is_blocked_before_second_request():
    response = _Response(
        status=302,
        headers={"Location": "http://169.254.169.254/latest/meta-data/report.pdf"},
    )
    calls = []
    fake_requests = types.SimpleNamespace(
        get=lambda url, **kwargs: calls.append((url, kwargs)) or response
    )

    with pytest.raises(UnsafeURL):
        safe_get_with_redirects(
            fake_requests,
            "https://example.org/report.pdf",
            resolve_dns=False,
        )

    assert len(calls) == 1
    assert response.closed is True
    assert calls[0][1]["allow_redirects"] is False


def test_missing_or_excessive_redirects_fail_closed():
    missing = _Response(status=302, headers={})
    fake_missing = types.SimpleNamespace(get=lambda *_args, **_kwargs: missing)
    with pytest.raises(UnsafeRedirect):
        safe_get_with_redirects(fake_missing, "https://example.org/x", resolve_dns=False)

    loop = _Response(status=302, headers={"Location": "/again"})
    fake_loop = types.SimpleNamespace(get=lambda *_args, **_kwargs: loop)
    with pytest.raises(UnsafeRedirect):
        safe_get_with_redirects(
            fake_loop,
            "https://example.org/x",
            resolve_dns=False,
            max_redirects=1,
        )


def test_decompressed_stream_limit_closes_response():
    response = _Response(chunks=[b"a" * 6, b"b" * 6])
    with pytest.raises(ResponseTooLarge):
        read_bounded_response(response, max_bytes=10)
    assert response.closed is True


def test_content_length_limit_fails_before_streaming():
    response = _Response(headers={"Content-Length": "1000"}, chunks=[b"small"])
    with pytest.raises(ResponseTooLarge):
        read_bounded_response(response, max_bytes=100)
    assert response.closed is True


def test_content_type_sanity_rejects_binary_discovery_and_html_pdf():
    with pytest.raises(UnexpectedContentType):
        require_content_type(
            _Response(headers={"Content-Type": "application/zip"}),
            "discovery",
        )
    with pytest.raises(UnexpectedContentType):
        require_content_type(
            _Response(headers={"Content-Type": "text/html; charset=utf-8"}),
            "pdf",
        )


def test_content_fetcher_rejects_private_direct_pdf_before_network():
    fetcher = ContentFetcher(allow_network=True)
    plan = fetcher.resolve(SourceRecord(url="http://127.0.0.1/private.pdf"))
    assert plan["ok"] is False
    assert "unsafe" in plan["reason"]


def test_discovery_http_helper_rejects_non_allowlisted_host():
    fake_requests = types.SimpleNamespace(
        get=lambda *_args, **_kwargs: pytest.fail("network call must not happen")
    )
    original = sys.modules.get("requests")
    sys.modules["requests"] = fake_requests
    try:
        with pytest.raises(UnsafeURL):
            connector_base.http_get("https://attacker.example/api", retries=0)
    finally:
        if original is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = original


def test_connector_safe_search_redacts_raw_exception_details():
    class _Boom(connector_base.BaseConnector):
        name = "boom"

        def search(self, query, max_results=3):
            del query, max_results
            raise RuntimeError("SECRET-TOKEN traceback /private/path")

    result = _Boom().safe_search("x", 1)
    assert result["reason"] == "error"
    assert "SECRET-TOKEN" not in result["error"]
    assert "traceback" not in result["error"].lower()
    assert "/private/path" not in result["error"]


def test_discovery_response_is_bounded_before_json_parser(monkeypatch):
    response = _Response(
        headers={"Content-Type": "application/json"},
        chunks=[b"x" * 700_000, b"y" * 700_000],
    )
    fake_requests = types.SimpleNamespace(get=lambda *_args, **_kwargs: response)
    original = sys.modules.get("requests")
    sys.modules["requests"] = fake_requests
    monkeypatch.setattr(connector_base, "_max_response_bytes", lambda: 1024 * 1024)
    try:
        with pytest.raises(connector_base.ConnectorHTTPError):
            connector_base.http_get("https://api.openalex.org/works", retries=0)
    finally:
        if original is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = original
    assert response.closed is True
