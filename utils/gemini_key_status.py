"""Public-safe Gemini credential setup diagnostics.

This module is deliberately dependency-light and makes **zero** network/model
calls. It inspects only environment variable names/values locally, deduplicates
configured credentials in memory, and returns counts plus supported variable
names. Raw credential values, prefixes, hashes/fingerprints, lengths and other
key-derived identifiers are never returned.

Why separate from ``research_engine.key_pool``: ``utils.reasoning_status`` is
used by public health/diagnostic routes very early in startup. Importing the
research package from there can pull heavy modules and create circular imports.
Keeping the parser here makes the diagnostic safe and cheap while matching the
same supported env contract.
"""
from __future__ import annotations

import os
from typing import Mapping

_PRIMARY = "GEMINI_API_KEY"
_SINGLE_VARS = (
    _PRIMARY,
    "GEMINI_API_KEY_BACKUP",
    "GEMINI_API_KEY_FALLBACK",
)
_LIST_VARS = (
    "GEMINI_API_KEYS",
    "GEMINI_API_KEY_LIST",
    "GEMINI_BACKUP_KEYS",
)
_SPLIT = (",", ";", "\n", "\t", " ")


def _split_list(raw: object) -> list[str]:
    parts = [str(raw or "")]
    for sep in _SPLIT:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(sep))
        parts = next_parts
    return [part.strip() for part in parts if part.strip()]


def _supported_names() -> list[str]:
    names = list(_SINGLE_VARS)
    for i in range(2, 10):
        names.append(f"{_PRIMARY}_{i}")
        names.append(f"{_PRIMARY}{i}")
    names.extend(_LIST_VARS)
    return names


def describe_gemini_keys(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return zero-call setup information without exposing key-derived metadata."""
    source = env if env is not None else os.environ
    entries: list[tuple[str, str]] = []

    for name in _SINGLE_VARS:
        value = str(source.get(name, "") or "").strip()
        if value:
            entries.append((name, value))

    for i in range(2, 10):
        for name in (f"{_PRIMARY}_{i}", f"{_PRIMARY}{i}"):
            value = str(source.get(name, "") or "").strip()
            if value:
                entries.append((name, value))

    for name in _LIST_VARS:
        for value in _split_list(source.get(name, "")):
            entries.append((name, value))

    names_present: list[str] = []
    unique_values: list[str] = []
    for name, value in entries:
        if name not in names_present:
            names_present.append(name)
        if value not in unique_values:
            unique_values.append(value)

    duplicates = len(entries) - len(unique_values)
    unique_count = len(unique_values)
    if not entries:
        note = "Koi supported Gemini credential variable configured nahi hai."
    elif unique_count == 1 and duplicates:
        note = (
            "Multiple supported variables set hain, lekin unique credential sirf 1 hai; "
            "duplicate entries real backup slot nahi banati."
        )
    elif unique_count == 1:
        note = "1 unique Gemini credential configured hai; separate backup slot configured nahi hai."
    else:
        note = f"{unique_count} unique Gemini credential slots configured hain; runtime zarurat par rotate kar sakta hai."

    return {
        "names_present": names_present,
        "configured_entries": len(entries),
        "unique_keys": unique_count,
        "duplicates_dropped": duplicates,
        "backup_slots": max(0, unique_count - 1),
        "supported_variable_names": _supported_names(),
        "note": note,
    }


__all__ = ["describe_gemini_keys"]
