"""Capability-discovered external-tool broker with deny-by-default grants.

The broker separates four concerns that must not be blurred together:

* discovery: which registered tool can perform a capability;
* permission: a signed, scoped, expiring and call-bounded capability grant;
* execution boundary: JSON/size/URL-host constraints before host callbacks run;
* audit: request/response hashes in an append-only in-memory hash chain.

The broker never stores the authority secret in a token, never puts raw tool
arguments/results into audit events, and never autonomously registers a
``dangerous`` tool. Network URL validation reuses ``network_safety`` so SSRF
policy stays centralized.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .network_safety import NetworkSafetyError, validate_public_http_url


_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,99}$")
_MAX_TOKEN_CHARS = 16_384


class PermissionDenied(PermissionError):
    """A tool request lacked a valid capability grant."""


class ToolBoundaryError(RuntimeError):
    """A request/result crossed a declared execution boundary."""


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    capabilities: Tuple[str, ...]
    required_permissions: Tuple[str, ...]
    risk: str = "read"  # read | write | external; dangerous is manual-only
    allowed_hosts: Tuple[str, ...] = ()
    url_argument: str = ""
    max_input_bytes: int = 65_536
    max_output_bytes: int = 262_144

    def validate(self) -> None:
        if not _NAME_RE.fullmatch(str(self.name or "")):
            raise ValueError("unsafe tool name")
        if not self.capabilities:
            raise ValueError("capabilities required")
        for capability in self.capabilities:
            if not _NAME_RE.fullmatch(str(capability or "")):
                raise ValueError("invalid capability name")
        if not self.required_permissions:
            raise ValueError("permissions required")
        for permission in self.required_permissions:
            if not _NAME_RE.fullmatch(str(permission or "")):
                raise ValueError("invalid permission name")
        if self.risk not in {"read", "write", "external"}:
            raise ValueError("dangerous/unsupported tools cannot enter autonomous broker")
        if self.url_argument and not self.allowed_hosts:
            raise ValueError("URL tools require allowed_hosts")
        if self.url_argument and not _NAME_RE.fullmatch(self.url_argument):
            raise ValueError("invalid URL argument name")
        if not 1 <= int(self.max_input_bytes) <= 10_000_000:
            raise ValueError("invalid input byte budget")
        if not 1 <= int(self.max_output_bytes) <= 10_000_000:
            raise ValueError("invalid output byte budget")

        # Fail at registration time if the allowlist itself contains a local,
        # private, credentialed or malformed destination.
        normalized = []
        for host in self.allowed_hosts:
            clean = str(host or "").strip().rstrip(".").lower()
            if not clean or "/" in clean or "://" in clean:
                raise ValueError("allowed_hosts must contain hostnames only")
            try:
                validate_public_http_url(
                    f"https://{clean}",
                    resolve_dns=False,
                    allowed_hosts=(clean,),
                )
            except NetworkSafetyError as exc:
                raise ValueError("unsafe host in tool allowlist") from exc
            normalized.append(clean)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate allowed_hosts")


@dataclass(frozen=True)
class PermissionGrant:
    grant_id: str
    principal: str
    tool: str
    permissions: Tuple[str, ...]
    expires_at: float
    max_calls: int


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    tool: str
    principal: str
    status: str
    request_sha256: str
    response_sha256: str
    previous_hash: str
    event_hash: str


class CapabilityCatalog:
    """Explicit registry; discovery never invents tools that are not registered."""

    def __init__(self) -> None:
        self._descriptors: Dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        descriptor.validate()
        if descriptor.name in self._descriptors:
            raise ValueError("tool already registered")
        self._descriptors[descriptor.name] = descriptor

    def get(self, name: str) -> ToolDescriptor:
        try:
            return self._descriptors[str(name)]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def discover(
        self,
        required_capabilities: str | Sequence[str],
    ) -> Tuple[ToolDescriptor, ...]:
        if isinstance(required_capabilities, str):
            required = {required_capabilities.casefold()}
        else:
            required = {
                str(item).strip().casefold()
                for item in required_capabilities
                if str(item).strip()
            }
        if not required:
            return ()
        matches = []
        for descriptor in self._descriptors.values():
            offered = {item.casefold() for item in descriptor.capabilities}
            if required.issubset(offered):
                matches.append(descriptor)
        return tuple(sorted(matches, key=lambda item: item.name))

    @property
    def capabilities(self) -> Tuple[str, ...]:
        found = {
            capability
            for descriptor in self._descriptors.values()
            for capability in descriptor.capabilities
        }
        return tuple(sorted(found))


class PermissionAuthority:
    """HMAC capability-token issuer/verifier; caller owns secret lifecycle."""

    def __init__(self, secret: bytes):
        if not isinstance(secret, (bytes, bytearray)) or len(secret) < 32:
            raise ValueError("permission secret must be at least 32 bytes")
        self._secret = bytes(secret)

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _unb64(text: str) -> bytes:
        padding = "=" * ((4 - len(text) % 4) % 4)
        return base64.urlsafe_b64decode((text + padding).encode("ascii"))

    def issue(
        self,
        *,
        principal: str,
        tool: str,
        permissions: Sequence[str],
        expires_at: float,
        max_calls: int,
        grant_id: Optional[str] = None,
    ) -> str:
        principal = str(principal or "").strip()
        tool = str(tool or "").strip()
        if not _NAME_RE.fullmatch(principal) or not _NAME_RE.fullmatch(tool):
            raise ValueError("principal/tool invalid")
        permission_set = tuple(sorted({
            str(permission).strip()
            for permission in permissions
            if str(permission).strip()
        }))
        if not permission_set or any(
            not _NAME_RE.fullmatch(permission) for permission in permission_set
        ):
            raise ValueError("permissions invalid")
        expiry = float(expires_at)
        if not math.isfinite(expiry):
            raise ValueError("expires_at must be finite")
        if not isinstance(max_calls, int) or not 1 <= max_calls <= 1_000_000:
            raise ValueError("max_calls invalid")
        identifier = str(grant_id or secrets.token_urlsafe(16))
        if not identifier or len(identifier) > 200:
            raise ValueError("grant_id invalid")

        payload = {
            "v": 1,
            "grant_id": identifier,
            "principal": principal,
            "tool": tool,
            "permissions": permission_set,
            "expires_at": expiry,
            "max_calls": max_calls,
        }
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._secret, body, hashlib.sha256).digest()
        return f"{self._b64(body)}.{self._b64(signature)}"

    def verify(self, token: str) -> PermissionGrant:
        token = str(token or "")
        if not token or len(token) > _MAX_TOKEN_CHARS:
            raise PermissionDenied("invalid capability token")
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            supplied_signature = self._unb64(signature_text)
        except Exception as exc:
            raise PermissionDenied("invalid capability token") from exc
        expected_signature = hmac.new(
            self._secret,
            body,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise PermissionDenied("invalid capability token")
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise PermissionDenied("invalid capability token") from exc
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise PermissionDenied("unsupported capability token")
        try:
            grant = PermissionGrant(
                grant_id=str(payload["grant_id"]),
                principal=str(payload["principal"]),
                tool=str(payload["tool"]),
                permissions=tuple(str(item) for item in payload["permissions"]),
                expires_at=float(payload["expires_at"]),
                max_calls=int(payload["max_calls"]),
            )
        except Exception as exc:
            raise PermissionDenied("invalid capability token") from exc
        if (
            not grant.grant_id
            or not _NAME_RE.fullmatch(grant.principal)
            or not _NAME_RE.fullmatch(grant.tool)
            or not grant.permissions
            or any(not _NAME_RE.fullmatch(item) for item in grant.permissions)
            or not math.isfinite(grant.expires_at)
            or not 1 <= grant.max_calls <= 1_000_000
        ):
            raise PermissionDenied("invalid capability token")
        return grant


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ToolBoundaryError("tool payload must be finite JSON data") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ToolBroker:
    """Permission-check, invoke a host callback, and hash-audit the call."""

    def __init__(
        self,
        catalog: CapabilityCatalog,
        authority: PermissionAuthority,
    ) -> None:
        self.catalog = catalog
        self.authority = authority
        self._invokers: Dict[str, Callable[[Mapping[str, Any]], Any]] = {}
        self._calls: Dict[str, int] = {}
        self._audit: list[AuditEvent] = []

    def bind(
        self,
        tool: str,
        invoker: Callable[[Mapping[str, Any]], Any],
    ) -> None:
        self.catalog.get(tool)
        if not callable(invoker):
            raise ValueError("invoker must be callable")
        if tool in self._invokers:
            raise ValueError("tool already bound")
        self._invokers[tool] = invoker

    def call(
        self,
        tool: str,
        args: Mapping[str, Any],
        *,
        token: str,
        now: Optional[float] = None,
    ) -> Any:
        principal = ""
        status = "DENIED"
        request_hash = _sha(b"INVALID_REQUEST")
        response_hash = ""
        authorized = False
        try:
            descriptor = self.catalog.get(tool)
            if not isinstance(args, Mapping):
                raise ToolBoundaryError("tool arguments must be a mapping")
            payload = dict(args)
            request = _canonical_bytes(payload)
            request_hash = _sha(request)
            if len(request) > descriptor.max_input_bytes:
                raise ToolBoundaryError("tool input exceeds byte budget")

            grant = self.authority.verify(token)
            principal = grant.principal
            current_time = time.time() if now is None else float(now)
            if not math.isfinite(current_time):
                raise PermissionDenied("invalid authorization time")
            if grant.tool != descriptor.name:
                raise PermissionDenied("grant is for another tool")
            if current_time >= grant.expires_at:
                raise PermissionDenied("grant expired")
            if not set(descriptor.required_permissions).issubset(grant.permissions):
                raise PermissionDenied("grant lacks required permission")

            used = self._calls.get(grant.grant_id, 0)
            if used >= grant.max_calls:
                raise PermissionDenied("grant call budget exhausted")

            if descriptor.url_argument:
                if descriptor.url_argument not in payload:
                    raise ToolBoundaryError("required URL argument missing")
                try:
                    payload[descriptor.url_argument] = validate_public_http_url(
                        str(payload[descriptor.url_argument]),
                        resolve_dns=False,
                        allowed_hosts=descriptor.allowed_hosts,
                    )
                except NetworkSafetyError as exc:
                    raise ToolBoundaryError("unsafe tool URL") from exc

            invoker = self._invokers.get(descriptor.name)
            if invoker is None:
                raise ToolBoundaryError("tool is not bound")

            # Reserve the call before invoking.  A callback error must still
            # consume a capability budget because it may already have produced
            # an external side effect that cannot be rolled back here.
            self._calls[grant.grant_id] = used + 1
            authorized = True
            try:
                result = invoker(payload)
            except Exception as exc:
                status = "ERROR"
                raise ToolBoundaryError("tool invocation failed") from exc

            response = _canonical_bytes(result)
            if len(response) > descriptor.max_output_bytes:
                status = "ERROR"
                raise ToolBoundaryError("tool output exceeds byte budget")
            response_hash = _sha(response)
            status = "ALLOWED"
            return result
        except (PermissionDenied, ToolBoundaryError):
            if authorized and status != "ERROR":
                status = "ERROR"
            raise
        finally:
            self._record(
                tool=str(tool),
                principal=principal,
                status=status,
                request_hash=request_hash,
                response_hash=response_hash,
            )

    def _record(
        self,
        *,
        tool: str,
        principal: str,
        status: str,
        request_hash: str,
        response_hash: str,
    ) -> None:
        previous_hash = self._audit[-1].event_hash if self._audit else "GENESIS"
        sequence = len(self._audit) + 1
        payload = {
            "sequence": sequence,
            "tool": tool,
            "principal": principal,
            "status": status,
            "request_sha256": request_hash,
            "response_sha256": response_hash,
            "previous_hash": previous_hash,
        }
        event_hash = _sha(_canonical_bytes(payload))
        self._audit.append(AuditEvent(
            sequence=sequence,
            tool=tool,
            principal=principal,
            status=status,
            request_sha256=request_hash,
            response_sha256=response_hash,
            previous_hash=previous_hash,
            event_hash=event_hash,
        ))

    @property
    def audit_events(self) -> Tuple[AuditEvent, ...]:
        return tuple(self._audit)

    def verify_audit_chain(self) -> bool:
        previous_hash = "GENESIS"
        for sequence, event in enumerate(self._audit, start=1):
            payload = {
                "sequence": sequence,
                "tool": event.tool,
                "principal": event.principal,
                "status": event.status,
                "request_sha256": event.request_sha256,
                "response_sha256": event.response_sha256,
                "previous_hash": previous_hash,
            }
            expected_hash = _sha(_canonical_bytes(payload))
            if (
                event.sequence != sequence
                or event.previous_hash != previous_hash
                or not hmac.compare_digest(event.event_hash, expected_hash)
            ):
                return False
            previous_hash = event.event_hash
        return True
