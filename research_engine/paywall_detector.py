"""
paywall_detector.py — Spec Section 3/4 (Honest Full-Text Access)

Content fetcher full-text laata hai, par ye module verify karta hai ki:
- Content actually article/paper hai (paywall HTML nahi)
- Read level kya hai (full-text, abstract, snippet)
- Source legitimacy

Zero Gemini quota — sirf pattern matching + heuristics.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Paywall indicator patterns
_PAYWALL_PATTERNS = [
    r"subscribe",
    r"sign\s*up",
    r"login\s*required",
    r"purchase",
    r"unlock full access",
    r"limited preview",
    r"this content is restricted",
    r"requires subscription",
]

# Legal free source domains (never paywalled)
_ALWAYS_FREE = {
    "arxiv.org", "biorxiv.org", "medrxiv.org",  # Preprints
    "plos.org", "plosone.org",  # Open access journals
    "doaj.org",  # Directory of Open Access Journals
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",  # PubMed
    "archive.org", "archive.is",  # Internet Archive
    "google.com",  # Google Scholar
    "wikipedia.org", "en.wikipedia.org",  # Wikipedia
    "github.com",  # GitHub (code + docs)
}

# Typical article structure patterns (real content vs paywall)
_ARTICLE_MARKERS = [
    (r"(?:abstract|abstract[:\s]*)", 1.0),  # Abstract section
    (r"(?:introduction|introduction[:\s]*)", 1.0),
    (r"(?:methodology|methods|approach)", 1.0),
    (r"(?:results|findings)", 1.0),
    (r"(?:discussion|conclusion)", 1.0),
    (r"(?:references|bibliography)", 1.0),
    (r"doi\s*[:\-]?\s*10\.", 1.0),  # DOI presence
]


def is_likely_paywall(content: str, url: str = "") -> bool:
    """
    Check karein ki content paywall page lagta hai ya nahi.
    """
    if not content:
        return True

    # Check URL domain
    for domain in _ALWAYS_FREE:
        if domain in url.lower():
            return False  # Always free domain

    # Check for paywall patterns
    content_lower = content.lower()
    paywall_count = 0
    for pattern in _PAYWALL_PATTERNS:
        if re.search(pattern, content_lower, re.IGNORECASE):
            paywall_count += 1

    if paywall_count >= 2:
        return True  # Likely paywall

    # Check for article structure
    article_markers_found = 0
    for marker, weight in _ARTICLE_MARKERS:
        if re.search(marker, content_lower, re.IGNORECASE):
            article_markers_found += weight

    # If multiple article markers found, probably real content
    if article_markers_found >= 3.0:
        return False

    # Default: if very short or mostly HTML, likely paywall
    if len(content) < 500:
        return True

    return False


def classify_read_level(content: str, url: str = "",
                        source_type: str = "") -> str:
    """
    Content ko read level classify karo:
    - FULL_TEXT: Poora paper/article
    - ABSTRACT: Sirf abstract + metadata
    - SNIPPET: Search result snippet
    - METADATA: Sirf title + author
    - UNAVAILABLE: Paywall/404
    """
    if not content:
        return "UNAVAILABLE"

    # Paywall check
    if is_likely_paywall(content, url):
        return "UNAVAILABLE"

    # Length-based heuristics
    content_len = len(content)

    if content_len >= 5000:
        return "FULL_TEXT"  # Typical paper: 5k+ chars
    elif content_len >= 1500:
        return "ABSTRACT"  # Abstract + intro: 1.5k-5k
    elif content_len >= 300:
        return "SNIPPET"  # Search result: 300-1.5k
    else:
        return "METADATA"  # Just title/author


def estimate_content_quality(content: str, url: str = "",
                            source_type: str = "web") -> Tuple[float, str]:
    """
    Content quality score (0.0 - 1.0) + reason.
    """
    if not content:
        return 0.0, "No content"

    read_level = classify_read_level(content, url, source_type)

    if read_level == "FULL_TEXT":
        return 0.9, f"Full text ({len(content)} chars)"
    elif read_level == "ABSTRACT":
        return 0.7, f"Abstract ({len(content)} chars)"
    elif read_level == "SNIPPET":
        return 0.4, f"Snippet ({len(content)} chars)"
    elif read_level == "METADATA":
        return 0.1, f"Metadata only ({len(content)} chars)"
    else:  # UNAVAILABLE
        return 0.0, "Paywall or inaccessible"


# Test
if __name__ == "__main__":
    test_paywall = """
    <html>
    <body>
    <h1>Subscribe to read</h1>
    <p>This content requires a subscription. <a href="/subscribe">Sign up now</a></p>
    </body>
    </html>
    """

    test_article = """
    Abstract: This study examines the impact of AI bias on hiring decisions.

    Introduction: Machine learning models are increasingly used in recruitment.

    Methodology: We analyzed 1000 hiring decisions across 50 companies.

    Results: 23% of decisions showed statistical bias against protected groups.

    Discussion: These findings suggest the need for bias audits.

    References:
    [1] Buolamwini & Gebru, "Gender Shades", 2018
    [2] ProPublica, "Machine Bias", 2016
    """

    print(f"Paywall test: {is_likely_paywall(test_paywall)}")
    print(f"Article test: {is_likely_paywall(test_article)}")
    print(f"Read level (paywall): {classify_read_level(test_paywall)}")
    print(f"Read level (article): {classify_read_level(test_article)}")
    print(f"Quality (article): {estimate_content_quality(test_article)}")
