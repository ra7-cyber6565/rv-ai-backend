"""Quota admission wrapper for Chroma durable vector writes.

Chroma owns its physical files and index layout, so exact post-write growth is
not knowable before mutation. We therefore use a deliberately conservative
estimate and the shared durable-root guard. Reads stay untouched.
"""
from __future__ import annotations

import json
from typing import Any

from utils.durable_write_guard import guard_durable_write


_FLOOR_RESERVE = 4 * 1024 * 1024
_OVERHEAD_MULTIPLIER = 4


def _utf8_bytes(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    except Exception:
        return len(str(value).encode("utf-8"))


def _embedding_bytes(embeddings: Any) -> int:
    if embeddings is None:
        return 0
    nbytes = getattr(embeddings, "nbytes", None)
    if isinstance(nbytes, int) and nbytes >= 0:
        return nbytes
    total = 0
    if isinstance(embeddings, (list, tuple)):
        for row in embeddings:
            if isinstance(row, (list, tuple)):
                total += max(1, len(row)) * 8
            else:
                total += 8
    return total


def estimate_vector_write_bytes(*, ids=None, embeddings=None, metadatas=None, documents=None) -> int:
    """Return a conservative pre-write reserve for Chroma data + index overhead."""
    logical = (
        _utf8_bytes(ids)
        + _utf8_bytes(metadatas)
        + _utf8_bytes(documents)
        + _embedding_bytes(embeddings)
    )
    return max(_FLOOR_RESERVE, logical * _OVERHEAD_MULTIPLIER + _FLOOR_RESERVE)


class QuotaBoundCollection:
    def __init__(self, collection, db_path: str):
        self._collection = collection
        self._db_path = db_path

    def __getattr__(self, name):
        return getattr(self._collection, name)

    def _guard(self, *, ids=None, embeddings=None, metadatas=None, documents=None) -> None:
        guard_durable_write(
            self._db_path,
            estimate_vector_write_bytes(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            ),
        )

    def add(self, ids, embeddings=None, metadatas=None, documents=None, images=None, uris=None):
        self._guard(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
        return self._collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
            images=images,
            uris=uris,
        )

    def upsert(self, ids, embeddings=None, metadatas=None, documents=None, images=None, uris=None):
        self._guard(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
        return self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
            images=images,
            uris=uris,
        )


class QuotaBoundClient:
    """Delegate Chroma client behavior while wrapping every collection writer."""

    def __init__(self, client, db_path: str):
        self._client = client
        self._db_path = db_path

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _wrap(self, collection):
        if isinstance(collection, QuotaBoundCollection):
            return collection
        return QuotaBoundCollection(collection, self._db_path)

    def get_or_create_collection(self, *args, **kwargs):
        return self._wrap(self._client.get_or_create_collection(*args, **kwargs))

    def get_collection(self, *args, **kwargs):
        return self._wrap(self._client.get_collection(*args, **kwargs))

    def create_collection(self, *args, **kwargs):
        return self._wrap(self._client.create_collection(*args, **kwargs))


__all__ = [
    "QuotaBoundClient",
    "QuotaBoundCollection",
    "estimate_vector_write_bytes",
]
