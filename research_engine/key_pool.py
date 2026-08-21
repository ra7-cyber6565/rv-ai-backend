"""Gemini API-key rotation without exposing credential values.

A reasoning pass should not disappear just because one configured Gemini
credential/project hits a quota/auth wall. This module only maintains an ordered
credential pool and safe labels such as ``free key #2``; it does not make any
network call and it does not decide whether an account is actually free.

Important ₹0 rule: multiple keys/projects are **not** assumed free merely because
they are different. Startup policy in ``utils.zero_cost_guard`` requires the
owner to confirm that every configured Gemini project/key has no paid-spend path
before ZERO_COST_ONLY permits Gemini use. The word ``free`` in labels is therefore
a human-readable project convention, not a billing guarantee.

Supported env names:
    GEMINI_API_KEY
    GEMINI_API_KEY_2 ... GEMINI_API_KEY_9
    GEMINI_API_KEY2 ... GEMINI_API_KEY9
    GEMINI_API_KEY_BACKUP
    GEMINI_API_KEY_FALLBACK
    GEMINI_API_KEYS
    GEMINI_API_KEY_LIST
    GEMINI_BACKUP_KEYS

Security: credential values are returned only by ``active()`` for the SDK. Public
status/notes use labels, variable names and counts only. No fingerprints or
partial hashes are exposed because even non-reversible credential metadata is
unnecessary for normal diagnostics.
"""
from __future__ import annotations

import os
from typing import Dict, List, Mapping, Optional

_PRIMARY = "GEMINI_API_KEY"
_LIST_VARS = ("GEMINI_API_KEYS", "GEMINI_API_KEY_LIST", "GEMINI_BACKUP_KEYS")
_SPLIT = (",", ";", "\n", "\t", " ")


def _split_list(raw: str) -> List[str]:
    parts = [raw]
    for sep in _SPLIT:
        nxt: List[str] = []
        for part in parts:
            nxt.extend(part.split(sep))
        parts = nxt
    return [p.strip() for p in parts if p.strip()]


def _entries(env: Mapping[str, str] | None = None) -> List[tuple[str, str]]:
    """Return configured ``(variable_name, credential_value)`` entries.

    Private helper only: callers that expose status must discard values and use
    :func:`describe` instead.
    """
    src = env if env is not None else os.environ
    out: List[tuple[str, str]] = []

    def take(name: str, raw: object) -> None:
        value = str(raw or "").strip()
        if value:
            out.append((name, value))

    take(_PRIMARY, src.get(_PRIMARY))
    for i in range(2, 10):
        take(f"{_PRIMARY}_{i}", src.get(f"{_PRIMARY}_{i}"))
        take(f"{_PRIMARY}{i}", src.get(f"{_PRIMARY}{i}"))
    take(f"{_PRIMARY}_BACKUP", src.get(f"{_PRIMARY}_BACKUP"))
    take(f"{_PRIMARY}_FALLBACK", src.get(f"{_PRIMARY}_FALLBACK"))
    for name in _LIST_VARS:
        for value in _split_list(str(src.get(name, "") or "")):
            take(name, value)
    return out


def load_keys(env: Optional[Dict[str, str]] = None) -> List[str]:
    """Load unique credentials in deterministic priority order."""
    out: List[str] = []
    for _name, key in _entries(env):
        if key not in out:
            out.append(key)
    return out


def describe(env: Mapping[str, str] | None = None) -> Dict[str, object]:
    """Return zero-call, public-safe setup diagnostics.

    Values are never returned. ``names_present`` helps detect a mistyped env
    variable, while ``duplicates_dropped`` explains the common case where the
    same credential was copied into multiple supported variables and therefore
    does not create a real backup slot.
    """
    entries = _entries(env)
    names_present: List[str] = []
    unique: List[str] = []
    for name, key in entries:
        if name not in names_present:
            names_present.append(name)
        if key not in unique:
            unique.append(key)

    duplicate_count = len(entries) - len(unique)
    if not entries:
        note = "Koi supported Gemini credential variable configured nahi hai."
    elif len(unique) == 1 and duplicate_count:
        note = (
            "Multiple supported variables set hain, lekin unique credential sirf 1 hai; "
            "duplicate entries backup slot nahi banati."
        )
    elif len(unique) == 1:
        note = "1 unique Gemini credential configured hai; separate backup credential configured nahi hai."
    else:
        note = f"{len(unique)} unique Gemini credentials configured hain; runtime zarurat par rotate kar sakta hai."

    return {
        "names_present": names_present,
        "configured_entries": len(entries),
        "unique_keys": len(unique),
        "duplicates_dropped": duplicate_count,
        "backup_slots": max(0, len(unique) - 1),
        "note": note,
    }


class KeyPool:
    """Ordered credential pool + current active index."""

    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self._keys: List[str] = [k for k in (keys if keys is not None else load_keys()) if k]
        self._index = 0
        self.switches = 0
        # Only label + normalized reason; never credential value.
        self.retired: List[Dict[str, str]] = []

    @property
    def count(self) -> int:
        return len(self._keys)

    @property
    def index(self) -> int:
        return self._index

    def has_key(self) -> bool:
        return bool(self._keys)

    def has_backup(self) -> bool:
        return self._index + 1 < len(self._keys)

    def remaining(self) -> int:
        return max(0, len(self._keys) - self._index - 1)

    def label(self, index: Optional[int] = None) -> str:
        i = self._index if index is None else index
        if not self._keys:
            return "koi free key set nahi"
        return f"free key #{i + 1}"

    def previous_label(self) -> str:
        return self.label(max(0, self._index - 1))

    def labels(self) -> List[str]:
        return [self.label(i) for i in range(len(self._keys))]

    def active(self) -> str:
        """Return credential value only for the SDK call path."""
        if not self._keys:
            return ""
        return self._keys[min(self._index, len(self._keys) - 1)]

    def advance(self, reason: str = "") -> bool:
        if not self.has_backup():
            return False
        self.retired.append({"key": self.label(), "reason": reason or "quota"})
        self._index += 1
        self.switches += 1
        return True

    def note(self) -> str:
        """Audit line with labels only, never credential values."""
        if not self._keys:
            return "Koi Gemini credential configured nahi hai."
        bits = [f"{self.count} confirmed credential slot available",
                f"abhi {self.label()} chal rahi hai"]
        if self.switches:
            bits.append(f"{self.switches} baar backup key par shift karna pada")
        for item in self.retired:
            bits.append(f"{item['key']} chhodi gayi ({item['reason']})")
        return ", ".join(bits)
