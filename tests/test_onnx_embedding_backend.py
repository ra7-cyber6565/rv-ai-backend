from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_primary_requirements_do_not_pull_sentence_transformers_or_torch():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").casefold()
    assert "sentence-transformers" not in requirements
    assert "torch==" not in requirements


def test_rag_pipeline_uses_chroma_default_embedding_backend():
    source = (ROOT / "rag" / "pipeline.py").read_text(encoding="utf-8")
    assert "DefaultEmbeddingFunction" in source
    assert "from sentence_transformers" not in source
    assert "SentenceTransformer(" not in source


def test_onnx_adapter_preserves_callable_and_legacy_encode_contract():
    from rag import pipeline

    class FakeChromaEmbeddingFunction:
        def __init__(self):
            self.calls = []

        def __call__(self, texts):
            self.calls.append(list(texts))
            return [[float(len(text)), 1.0] for text in texts]

    fake = FakeChromaEmbeddingFunction()
    adapter = pipeline._ChromaEmbeddingAdapter(fake)

    direct = adapter(["a", "abcd"])
    assert direct == [[1.0, 1.0], [4.0, 1.0]]

    legacy = adapter.encode(["xy", "z"]).tolist()
    assert legacy == [[2.0, 1.0], [1.0, 1.0]]
    assert fake.calls == [["a", "abcd"], ["xy", "z"]]


def test_chroma_model_cache_follows_ephemeral_cache_root(monkeypatch, tmp_path):
    from rag import pipeline

    class FakeEmbeddingFunction:
        MODEL_NAME = "all-MiniLM-L6-v2"
        DOWNLOAD_PATH = Path.home() / ".cache" / "chroma" / "old"

    fake = FakeEmbeddingFunction()
    cache_root = tmp_path / "ephemeral-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))

    pipeline._route_chroma_model_cache(fake)

    assert fake.DOWNLOAD_PATH == (
        cache_root / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
    )


def test_chroma_model_cache_keeps_default_when_no_ephemeral_cache_env(monkeypatch):
    from rag import pipeline

    class FakeEmbeddingFunction:
        MODEL_NAME = "all-MiniLM-L6-v2"
        DOWNLOAD_PATH = Path("original-location")

    fake = FakeEmbeddingFunction()
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    pipeline._route_chroma_model_cache(fake)

    assert fake.DOWNLOAD_PATH == Path("original-location")
