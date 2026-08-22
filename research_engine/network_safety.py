"""Fail-closed network guards for research discovery and full-text fetching.

The research engine talks to two kinds of URLs:

* discovery API endpoints selected by our own connector code; and
* full-text links learned from external search results.

The second category is untrusted.  A URL ending in ``.pdf`` is not proof that it
is safe to request: it can still point at localhost, a cloud metadata service,
or a private address after a redirect.  This module keeps the policy in one
small, deterministic place so connector/fetch code does not grow slightly
different SSRF checks.

No exception returned by these helpers contains a response body, secret URL
credentials, or a raw SDK/requests error string.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Iterable, Optional, Tuple
from urllib.parse import urljoin, urlsplit


MAX_URL_CHARS = 2048
MAX_REDIRECTS = 4
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SAFE_PORTS = {None, 80, 443}
_LOCAL_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
)


class NetworkSafetyError(RuntimeError):
    """A request was blocked before untrusted network data could be consumed."""


class UnsafeURL(NetworkSafetyError):
    """The URL can reach a local/private/non-HTTP target."""


class UnsafeRedirect(NetworkSafetyError):
    """A redirect was missing, excessive, or pointed at an unsafe target."""


class ResponseTooLarge(NetworkSafetyError):
    """The decompressed response exceeded its configured byte budget."""


class UnexpectedContentType(NetworkSafetyError):
    """The response type did not match the requested research artifact."""


def _host_is_public_literal(host: str) -> Optional[bool]:
    """Return literal-IP safety, or None when *host* is a DNS name."""
    candidate = (host or "").strip().strip("[]")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return bool(address.is_global)


def _resolved_addresses(host: str) -> list[str]:
    """Resolve all addresses; kept separate so offline tests can patch it."""
    rows = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    found: list[str] = []
    for row in rows:
        sockaddr = row[4]
        if not sockaddr:
            continue
        address = str(sockaddr[0]).split("%", 1)[0]
        if address not in found:
            found.append(address)
    return found


def validate_public_http_url(
    url: str,
    *,
    resolve_dns: bool = True,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> str:
    """Validate and return a public HTTP(S) URL, otherwise raise ``UnsafeURL``.

    ``allowed_hosts`` is used for connector endpoints chosen by source code.
    Exact-host matching prevents a future connector from turning ``http_get``
    into a generic URL fetcher.  Those trusted constants do not need a DNS
    lookup to establish SSRF safety; untrusted full-text hosts always do.
    """
    clean = str(url or "").strip()
    if not clean or len(clean) > MAX_URL_CHARS:
        raise UnsafeURL("unsafe URL blocked")
    try:
        parsed = urlsplit(clean)
        port = parsed.port
    except (TypeError, ValueError):
        raise UnsafeURL("unsafe URL blocked") from None

    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeURL("non-HTTP URL blocked")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURL("URL credentials blocked")
    if port not in _SAFE_PORTS:
        raise UnsafeURL("non-standard network port blocked")

    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("URL hostname missing")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        raise UnsafeURL("local network target blocked")

    literal_state = _host_is_public_literal(host)
    if literal_state is False:
        raise UnsafeURL("private or reserved network target blocked")

    allowed = {str(item or "").rstrip(".").lower() for item in (allowed_hosts or ())}
    if allowed and host not in allowed:
        raise UnsafeURL("connector host is not allowlisted")

    # Connector endpoints are hard-coded and exact-host allowlisted.  Untrusted
    # full-text hostnames must resolve now, and every answer must be globally
    # routable.  One private answer is enough to fail closed.
    if resolve_dns and literal_state is None and not allowed:
        try:
            addresses = _resolved_addresses(host)
        except (OSError, socket.gaierror):
            raise UnsafeURL("URL hostname could not be safely resolved") from None
        if not addresses:
            raise UnsafeURL("URL hostname could not be safely resolved")
        for address in addresses:
            try:
                if not ipaddress.ip_address(address).is_global:
                    raise UnsafeURL("private or reserved network target blocked")
            except ValueError:
                raise UnsafeURL("URL hostname resolved unsafely") from None
    return clean


def _close(response) -> None:
    try:
        response.close()
    except Exception:
        pass


def safe_get_with_redirects(
    requests_module,
    url: str,
    *,
    params=None,
    headers=None,
    timeout=None,
    stream: bool = True,
    allowed_hosts: Optional[Iterable[str]] = None,
    resolve_dns: bool = True,
    max_redirects: int = MAX_REDIRECTS,
) -> Tuple[object, str]:
    """GET with manual redirect validation.

    ``requests`` normally follows redirects before callers can inspect the next
    host.  Manual following guarantees that every hop passes the same public-IP
    and allowlist policy as the original URL.
    """
    current = str(url or "")
    first_params = params
    for hop in range(max(0, int(max_redirects)) + 1):
        current = validate_public_http_url(
            current,
            resolve_dns=resolve_dns,
            allowed_hosts=allowed_hosts,
        )
        response = requests_module.get(
            current,
            params=first_params,
            headers=headers,
            timeout=timeout,
            stream=stream,
            allow_redirects=False,
        )
        first_params = None
        status = int(getattr(response, "status_code", 200) or 200)
        if status not in _REDIRECT_STATUSES:
            return response, current

        location = str((getattr(response, "headers", None) or {}).get("Location") or "")
        request_url = str(getattr(response, "url", current) or current)
        _close(response)
        if not location:
            raise UnsafeRedirect("redirect without a safe destination blocked")
        if hop >= max_redirects:
            raise UnsafeRedirect("too many redirects blocked")
        current = urljoin(request_url, location)
    raise UnsafeRedirect("too many redirects blocked")  # pragma: no cover


def declared_length(response) -> Optional[int]:
    """Return a valid Content-Length, ignoring missing/malformed values."""
    try:
        raw = (getattr(response, "headers", None) or {}).get("Content-Length")
        value = int(str(raw).strip())
        return value if value >= 0 else None
    except (TypeError, ValueError):
        return None


def read_bounded_response(response, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` decompressed bytes and cache them on response."""
    limit = max(1, int(max_bytes))
    stated = declared_length(response)
    if stated is not None and stated > limit:
        _close(response)
        raise ResponseTooLarge("network response exceeded the byte limit")

    iterator = getattr(response, "iter_content", None)
    if not callable(iterator):
        raw = getattr(response, "content", b"") or b""
        data = raw if isinstance(raw, bytes) else bytes(raw)
        if len(data) > limit:
            _close(response)
            raise ResponseTooLarge("network response exceeded the byte limit")
        return data

    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            piece = chunk if isinstance(chunk, bytes) else bytes(chunk)
            total += len(piece)
            if total > limit:
                raise ResponseTooLarge("network response exceeded the byte limit")
            chunks.append(piece)
    except Exception:
        _close(response)
        raise
    data = b"".join(chunks)
    # requests.Response.json()/content continue to work after bounded streaming.
    try:
        response._content = data
        response._content_consumed = True
    except Exception:
        pass
    return data


def normalized_content_type(response) -> str:
    raw = str((getattr(response, "headers", None) or {}).get("Content-Type") or "")
    return raw.split(";", 1)[0].strip().lower()


def require_content_type(response, expected: str) -> None:
    """Reject a declared type that is incompatible with the expected artifact."""
    actual = normalized_content_type(response)
    if not actual:  # Some public archives omit it; magic/content checks still run.
        return
    groups = {
        "discovery": (
            "application/json", "application/ld+json", "application/xml",
            "application/atom+xml", "text/xml", "text/plain",
        ),
        "json": ("application/json", "application/ld+json", "text/json"),
        "pdf": (
            "application/pdf", "application/x-pdf", "application/octet-stream",
            "binary/octet-stream",
        ),
        "txt": ("text/plain", "application/octet-stream", "binary/octet-stream"),
        "html": (
            "text/html", "application/xhtml+xml", "application/xml", "text/xml",
        ),
        "wikipedia": ("application/json", "application/ld+json", "text/json"),
    }
    allowed = groups.get(expected, ())
    if actual.endswith("+json") and expected in {"discovery", "json", "wikipedia"}:
        return
    if actual not in allowed:
        raise UnexpectedContentType("unexpected network content type blocked")


def public_error(exc: BaseException) -> str:
    """Map internal/network failures to a short user-safe explanation."""
    if isinstance(exc, ResponseTooLarge):
        return "network response byte limit se badi thi"
    if isinstance(exc, UnexpectedContentType):
        return "response ka content type expected document se match nahi karta"
    if isinstance(exc, (UnsafeURL, UnsafeRedirect)):
        return str(exc)
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "network timeout"
    if any(word in name for word in ("ssl", "tls", "certificate")):
        return "TLS/certificate verification fail hui"
    if any(word in name for word in ("connection", "proxy", "dns", "gaierror")):
        return "network connection fail hui"
    return "network request fail hui"
