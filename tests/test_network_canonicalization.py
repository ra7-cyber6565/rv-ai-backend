"""Regression for URL spellings that can bypass downstream host policy.

These tests are offline and make no network call. The problem is not only SSRF:
source/legal policy compares canonical publisher hostnames. A redundant port or
trailing DNS dot must not turn `nature.com` into a different string that slips
past a blocked-host comparison.
"""
from __future__ import annotations

import pytest

from research_engine.content_fetcher import ContentFetcher
from research_engine.models import SourceRecord
from research_engine.network_safety import UnsafeURL, validate_public_http_url


@pytest.mark.parametrize("url", [
    "https://example.org:443/paper.pdf",
    "http://example.org:80/paper.pdf",
    "https://example.org./paper.pdf",
    "https://exa%6dple.org/paper.pdf",
    "https://example.org\\@attacker.invalid/paper.pdf",
])
def test_noncanonical_authorities_fail_closed_before_dns_or_http(url):
    with pytest.raises(UnsafeURL):
        validate_public_http_url(url, resolve_dns=False)


def test_normal_default_port_url_stays_allowed():
    assert validate_public_http_url(
        "https://example.org/paper.pdf", resolve_dns=False
    ) == "https://example.org/paper.pdf"


@pytest.mark.parametrize("url", [
    "https://nature.com:443/article.pdf",
    "https://nature.com./article.pdf",
    "https://www.nature.com:443/article.pdf",
])
def test_blocked_publisher_cannot_use_authority_spelling_to_reach_direct_pdf_route(url):
    plan = ContentFetcher(allow_network=True).resolve(SourceRecord(
        title="publisher-policy regression",
        url=url,
    ))
    assert plan["ok"] is False
    # It may be rejected by network canonicalization before the publisher rule;
    # either is correct because no request is allowed to leave the process.
    assert "unsafe" in plan["reason"].lower() or "paywall" in plan["reason"].lower()
