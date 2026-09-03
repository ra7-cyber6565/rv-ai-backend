from dataclasses import replace

import pytest

from research_engine.tool_broker import (
    CapabilityCatalog,
    PermissionAuthority,
    PermissionDenied,
    ToolBoundaryError,
    ToolBroker,
    ToolDescriptor,
)


SECRET = b"0123456789abcdef0123456789abcdef"


def _catalog():
    catalog = CapabilityCatalog()
    catalog.register(
        ToolDescriptor(
            name="paper.fetch",
            capabilities=("literature.read", "http.fetch"),
            required_permissions=("read:papers",),
            risk="external",
            allowed_hosts=("example.com",),
            url_argument="url",
            max_input_bytes=1024,
            max_output_bytes=2048,
        )
    )
    return catalog


def _grant(authority, *, expires_at=200.0, max_calls=2, permissions=("read:papers",), tool="paper.fetch"):
    return authority.issue(
        principal="research-agent",
        tool=tool,
        permissions=permissions,
        expires_at=expires_at,
        max_calls=max_calls,
        grant_id="grant-1",
    )


def test_capability_discovery_requires_all_requested_capabilities():
    catalog = _catalog()
    assert [item.name for item in catalog.discover("literature.read")] == ["paper.fetch"]
    assert [item.name for item in catalog.discover(("literature.read", "http.fetch"))] == ["paper.fetch"]
    assert catalog.discover(("literature.read", "write.files")) == ()
    assert set(catalog.capabilities) == {"http.fetch", "literature.read"}


def test_descriptor_rejects_dangerous_and_unsafe_network_surfaces():
    with pytest.raises(ValueError, match="dangerous|unsupported"):
        ToolDescriptor(
            name="shell.run",
            capabilities=("shell",),
            required_permissions=("shell:run",),
            risk="dangerous",
        ).validate()

    with pytest.raises(ValueError, match="unsafe host"):
        ToolDescriptor(
            name="private.fetch",
            capabilities=("http.fetch",),
            required_permissions=("read:http",),
            risk="external",
            allowed_hosts=("127.0.0.1",),
            url_argument="url",
        ).validate()

    with pytest.raises(ValueError, match="allowed_hosts"):
        ToolDescriptor(
            name="open.fetch",
            capabilities=("http.fetch",),
            required_permissions=("read:http",),
            risk="external",
            url_argument="url",
        ).validate()


def test_valid_scoped_grant_allows_exact_tool_and_hash_audits_without_raw_payload():
    catalog = _catalog()
    authority = PermissionAuthority(SECRET)
    broker = ToolBroker(catalog, authority)
    seen = []
    broker.bind("paper.fetch", lambda args: seen.append(dict(args)) or {"ok": True, "count": 3})
    token = _grant(authority)

    result = broker.call(
        "paper.fetch",
        {"url": "https://example.com/paper", "query": "room temp"},
        token=token,
        now=100.0,
    )

    assert result == {"ok": True, "count": 3}
    assert seen == [{"url": "https://example.com/paper", "query": "room temp"}]
    assert broker.verify_audit_chain() is True
    event = broker.audit_events[-1]
    assert event.status == "ALLOWED"
    assert event.principal == "research-agent"
    assert len(event.request_sha256) == 64
    assert len(event.response_sha256) == 64
    assert "room temp" not in repr(event)


def test_tampered_wrong_tool_wrong_scope_and_expired_grants_are_denied():
    authority = PermissionAuthority(SECRET)
    catalog = _catalog()
    broker = ToolBroker(catalog, authority)
    broker.bind("paper.fetch", lambda args: {"ok": True})

    token = _grant(authority)
    left, right = token.split(".", 1)
    tampered = ("A" if left[0] != "A" else "B") + left[1:] + "." + right
    with pytest.raises(PermissionDenied):
        broker.call("paper.fetch", {"url": "https://example.com/x"}, token=tampered, now=100.0)

    wrong_tool = authority.issue(
        principal="research-agent",
        tool="other.tool",
        permissions=("read:papers",),
        expires_at=200.0,
        max_calls=1,
    )
    with pytest.raises(PermissionDenied, match="another tool"):
        broker.call("paper.fetch", {"url": "https://example.com/x"}, token=wrong_tool, now=100.0)

    wrong_scope = _grant(authority, permissions=("read:metadata",))
    with pytest.raises(PermissionDenied, match="required permission"):
        broker.call("paper.fetch", {"url": "https://example.com/x"}, token=wrong_scope, now=100.0)

    expired = _grant(authority, expires_at=100.0)
    with pytest.raises(PermissionDenied, match="expired"):
        broker.call("paper.fetch", {"url": "https://example.com/x"}, token=expired, now=100.0)

    assert all(event.status == "DENIED" for event in broker.audit_events)
    assert broker.verify_audit_chain() is True


def test_call_budget_is_exhausted_fail_closed():
    authority = PermissionAuthority(SECRET)
    catalog = _catalog()
    broker = ToolBroker(catalog, authority)
    calls = []
    broker.bind("paper.fetch", lambda args: calls.append(args["url"]) or {"ok": True})
    token = _grant(authority, max_calls=1)

    broker.call("paper.fetch", {"url": "https://example.com/one"}, token=token, now=100.0)
    with pytest.raises(PermissionDenied, match="budget exhausted"):
        broker.call("paper.fetch", {"url": "https://example.com/two"}, token=token, now=101.0)

    assert calls == ["https://example.com/one"]
    assert [event.status for event in broker.audit_events] == ["ALLOWED", "DENIED"]


def test_url_allowlist_and_private_targets_fail_before_callback():
    authority = PermissionAuthority(SECRET)
    catalog = _catalog()
    broker = ToolBroker(catalog, authority)
    called = []
    broker.bind("paper.fetch", lambda args: called.append(True) or {"ok": True})
    token = _grant(authority)

    with pytest.raises(ToolBoundaryError, match="unsafe tool URL"):
        broker.call("paper.fetch", {"url": "https://evil.example/x"}, token=token, now=100.0)
    with pytest.raises(ToolBoundaryError, match="unsafe tool URL"):
        broker.call("paper.fetch", {"url": "http://127.0.0.1/x"}, token=token, now=100.0)

    assert called == []
    assert all(event.status == "DENIED" for event in broker.audit_events)


def test_callback_failure_consumes_budget_and_is_audited_as_error():
    authority = PermissionAuthority(SECRET)
    catalog = _catalog()
    broker = ToolBroker(catalog, authority)
    broker.bind("paper.fetch", lambda args: (_ for _ in ()).throw(RuntimeError("boom secret")))
    token = _grant(authority, max_calls=1)

    with pytest.raises(ToolBoundaryError, match="invocation failed") as caught:
        broker.call("paper.fetch", {"url": "https://example.com/x"}, token=token, now=100.0)
    assert "boom secret" not in str(caught.value)

    with pytest.raises(PermissionDenied, match="budget exhausted"):
        broker.call("paper.fetch", {"url": "https://example.com/x"}, token=token, now=101.0)

    assert [event.status for event in broker.audit_events] == ["ERROR", "DENIED"]


def test_nonfinite_and_oversize_json_boundaries_fail_closed():
    authority = PermissionAuthority(SECRET)
    catalog = _catalog()
    broker = ToolBroker(catalog, authority)
    broker.bind("paper.fetch", lambda args: {"ok": True})
    token = _grant(authority)

    with pytest.raises(ToolBoundaryError, match="finite JSON"):
        broker.call(
            "paper.fetch",
            {"url": "https://example.com/x", "value": float("nan")},
            token=token,
            now=100.0,
        )

    with pytest.raises(ToolBoundaryError, match="input exceeds"):
        broker.call(
            "paper.fetch",
            {"url": "https://example.com/x", "payload": "x" * 5000},
            token=token,
            now=100.0,
        )


def test_audit_chain_detects_tampering():
    authority = PermissionAuthority(SECRET)
    catalog = _catalog()
    broker = ToolBroker(catalog, authority)
    broker.bind("paper.fetch", lambda args: {"ok": True})
    token = _grant(authority)
    broker.call("paper.fetch", {"url": "https://example.com/x"}, token=token, now=100.0)
    assert broker.verify_audit_chain() is True

    broker._audit[0] = replace(broker._audit[0], status="DENIED")
    assert broker.verify_audit_chain() is False
