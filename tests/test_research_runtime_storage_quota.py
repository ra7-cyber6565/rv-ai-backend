from __future__ import annotations

import os

import pytest


def _limits():
    return {
        "http": 3,
        "input_bytes": 1000,
        "output_tokens": 300,
        "seconds": 3600,
    }


def test_managed_runtime_store_preflights_schema_transactions_and_payload(monkeypatch, tmp_path):
    from utils import research_runtime as runtime

    durable = tmp_path / "durable"
    ephemeral = tmp_path / "ephemeral"
    monkeypatch.setenv("INFINITY_DURABLE_ROOT", str(durable))
    monkeypatch.setenv("INFINITY_EPHEMERAL_ROOT", str(ephemeral))

    calls = []
    monkeypatch.setattr(
        runtime,
        "guard_durable_write",
        lambda path, size: calls.append((os.path.abspath(path), int(size))),
    )

    store = runtime.RuntimeStore()
    store.start("p", "r", "input", "v1", _limits())
    store.claim("p", "r", "stage", runtime.digest({}), "owner", replay_safe=True)
    payload = {"answer": "x" * 200_000}
    store.finish("p", "r", "stage", "owner", payload)

    assert calls
    assert calls[0][1] >= 1024 * 1024  # schema/WAL headroom
    assert any(size >= 256 * 1024 for _path, size in calls)
    assert any(size >= 400_000 for _path, size in calls)  # payload-aware reserve
    assert all(path.startswith(str(durable.resolve())) for path, _size in calls)


def test_storage_quota_error_is_translated_to_runtime_blocked(monkeypatch, tmp_path):
    from utils import research_runtime as runtime
    from utils.storage_quota import StorageQuotaError

    monkeypatch.setenv("INFINITY_DURABLE_ROOT", str(tmp_path / "durable"))
    monkeypatch.setenv("INFINITY_EPHEMERAL_ROOT", str(tmp_path / "ephemeral"))

    def blocked(_path, _size):
        raise StorageQuotaError("full")

    monkeypatch.setattr(runtime, "guard_durable_write", blocked)
    with pytest.raises(runtime.RuntimeBlocked, match="durable research storage capacity reached"):
        runtime.RuntimeStore()


def test_custom_temp_runtime_store_stays_outside_cloud_quota(monkeypatch, tmp_path):
    """The real shared guard must no-op for test/custom DBs outside durable root."""
    from utils import research_runtime as runtime

    durable = tmp_path / "durable"
    durable.mkdir()
    custom = tmp_path / "custom" / "state.sqlite3"
    monkeypatch.setenv("INFINITY_DURABLE_ROOT", str(durable))
    monkeypatch.setenv("INFINITY_EPHEMERAL_ROOT", str(tmp_path / "ephemeral"))

    store = runtime.RuntimeStore(custom)
    store.start("p", "r", "input", "v1", _limits())
    assert store.snapshot("p", "r")["available"] is True
