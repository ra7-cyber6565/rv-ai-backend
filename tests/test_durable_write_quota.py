from __future__ import annotations

from pathlib import Path


def test_durable_guard_enforces_only_inside_explicit_root(monkeypatch, tmp_path):
    from utils import durable_write_guard as guard

    durable = tmp_path / "durable"
    durable.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    calls = []

    monkeypatch.setenv("INFINITY_DURABLE_ROOT", str(durable))
    monkeypatch.delenv("INFINITY_DATA_ROOT", raising=False)
    monkeypatch.delenv("INFINITY_WORK_ROOT", raising=False)
    monkeypatch.setattr(guard, "assert_capacity", lambda size: calls.append(size) or {"blocked": False})

    assert guard.guard_durable_write(str(durable / "vector_db"), 1234) == {"blocked": False}
    assert calls == [1234]

    assert guard.guard_durable_write(str(outside / "state.db"), 9999) is None
    assert calls == [1234]


def test_chroma_wrapper_guards_add_and_upsert_but_not_reads(monkeypatch, tmp_path):
    from utils import chroma_quota

    guarded = []
    monkeypatch.setattr(
        chroma_quota,
        "guard_durable_write",
        lambda path, size: guarded.append((path, size)),
    )

    class FakeCollection:
        def __init__(self):
            self.calls = []

        def add(self, **kwargs):
            self.calls.append(("add", kwargs))
            return "added"

        def upsert(self, **kwargs):
            self.calls.append(("upsert", kwargs))
            return "upserted"

        def query(self, **kwargs):
            self.calls.append(("query", kwargs))
            return {"ids": [["x"]]}

    inner = FakeCollection()
    wrapped = chroma_quota.QuotaBoundCollection(inner, str(tmp_path / "vector_db"))

    assert wrapped.add(ids=["1"], embeddings=[[1.0, 2.0]], metadatas=[{"a": 1}], documents=["hello"]) == "added"
    assert wrapped.upsert(ids=["1"], embeddings=[[3.0, 4.0]], metadatas=[{"a": 2}], documents=["world"]) == "upserted"
    assert wrapped.query(query_embeddings=[[1.0, 2.0]], n_results=1) == {"ids": [["x"]]}

    assert len(guarded) == 2
    assert all(size >= 4 * 1024 * 1024 for _path, size in guarded)
    assert [name for name, _payload in inner.calls] == ["add", "upsert", "query"]


def test_quota_bound_client_wraps_every_collection_factory(tmp_path):
    from utils.chroma_quota import QuotaBoundClient, QuotaBoundCollection

    class FakeCollection:
        pass

    class FakeClient:
        def get_or_create_collection(self, *args, **kwargs):
            return FakeCollection()

        def get_collection(self, *args, **kwargs):
            return FakeCollection()

        def create_collection(self, *args, **kwargs):
            return FakeCollection()

        def heartbeat(self):
            return 7

    client = QuotaBoundClient(FakeClient(), str(tmp_path / "vector_db"))
    assert isinstance(client.get_or_create_collection("a"), QuotaBoundCollection)
    assert isinstance(client.get_collection("a"), QuotaBoundCollection)
    assert isinstance(client.create_collection("a"), QuotaBoundCollection)
    assert client.heartbeat() == 7


def test_vector_estimate_grows_with_payload():
    from utils.chroma_quota import estimate_vector_write_bytes

    small = estimate_vector_write_bytes(ids=["1"], embeddings=[[0.1] * 4], documents=["x"])
    large = estimate_vector_write_bytes(ids=[str(i) for i in range(100)], embeddings=[[0.1] * 384 for _ in range(100)], documents=["x" * 1000] * 100)
    assert small >= 4 * 1024 * 1024
    assert large > small
