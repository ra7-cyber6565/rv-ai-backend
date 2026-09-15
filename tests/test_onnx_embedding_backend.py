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
