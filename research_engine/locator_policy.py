"""Shared fail-closed policy for claim-level evidence locators."""
from __future__ import annotations

import unicodedata


GENERIC_LOCATOR_MARKERS = (
    "exact page/section unavailable",
    "exact page ka pata nahi",
    "locator unavailable",
    "locator unknown",
    "unknown locator",
    "selected source passage",
    "source snippet",
    "full text ka padha gaya hissa",
    "abstract/snippet",
)


def normalize_locator(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split()).strip()


def locator_key(value: object) -> str:
    """Formatting-only whitespace/case changes keep the same identity."""
    return "".join(normalize_locator(value).casefold().split())


def exact_locator_available(value: object) -> bool:
    """True only for an attributable, non-placeholder locator."""
    locator = normalize_locator(value).casefold()
    if not locator:
        return False
    return not any(marker in locator for marker in GENERIC_LOCATOR_MARKERS)


__all__ = ["exact_locator_available", "locator_key", "normalize_locator"]
