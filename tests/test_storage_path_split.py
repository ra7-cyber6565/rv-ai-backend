from pathlib import Path

from utils import storage_paths


def _same(path_a: str, path_b: Path) -> bool:
    return Path(path_a).resolve() == path_b.resolve()


def test_legacy_root_keeps_all_storage_unified(tmp_path):
    root = tmp_path / "legacy"
    layout = storage_paths.ensure_layout({"INFINITY_DATA_ROOT": str(root)})

    assert layout["split"] == "false"
    assert _same(layout["durable_root"], root)
    assert _same(layout["ephemeral_root"], root)
    assert _same(layout["research_memory"], root / "research_memory")
    assert _same(layout["models"], root / "models")
    assert _same(layout["temp"], root / "temp")


def test_split_roots_keep_durable_state_off_runtime_cache(tmp_path):
    durable = tmp_path / "durable"
    ephemeral = tmp_path / "ephemeral"
    layout = storage_paths.ensure_layout(
        {
            "INFINITY_DURABLE_ROOT": str(durable),
            "INFINITY_EPHEMERAL_ROOT": str(ephemeral),
        }
    )

    assert layout["split"] == "true"
    for name in storage_paths.DURABLE_SUBDIRS:
        assert _same(layout[name], durable / name)
    for name in storage_paths.EPHEMERAL_SUBDIRS:
        assert _same(layout[name], ephemeral / name)


def test_split_process_env_routes_models_and_temp_to_ephemeral(tmp_path, monkeypatch):
    durable = tmp_path / "durable"
    ephemeral = tmp_path / "ephemeral"

    monkeypatch.delenv("INFINITY_DATA_ROOT", raising=False)
    monkeypatch.delenv("INFINITY_WORK_ROOT", raising=False)
    monkeypatch.setenv("INFINITY_DURABLE_ROOT", str(durable))
    monkeypatch.setenv("INFINITY_EPHEMERAL_ROOT", str(ephemeral))

    status = storage_paths.configure_process_storage()

    assert status["split"] is True
    assert _same(str(status["durable_root"]), durable)
    assert _same(str(status["ephemeral_root"]), ephemeral)
    assert _same(storage_paths.os.environ["RESEARCH_MEMORY_DIR"], durable / "research_memory")
    assert _same(storage_paths.os.environ["CHROMA_DB_DIR"], durable / "vector_db")
    assert _same(storage_paths.os.environ["HF_HOME"], ephemeral / "models" / "huggingface")
    assert _same(storage_paths.os.environ["TMPDIR"], ephemeral / "temp")


def test_public_status_never_exposes_storage_paths():
    raw = {
        "root": "/secret/persistent/path",
        "ephemeral_root": "/secret/runtime/path",
        "explicit": True,
        "split": True,
        "available": True,
        "ephemeral_available": True,
        "disk_total_bytes": 100,
        "disk_free_bytes": 40,
    }
    public = storage_paths.public_storage_status(raw)

    assert public["available"] is True
    assert public["split_storage"] is True
    assert public["ephemeral_available"] is True
    assert public["disk_free_percent"] == 40.0
    rendered = repr(public)
    assert "/secret/persistent/path" not in rendered
    assert "/secret/runtime/path" not in rendered
