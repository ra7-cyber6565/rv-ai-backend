import inspect
from pathlib import Path

import posthog

from rag import pipeline
from utils import chroma_quota


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_pin_posthog_below_breaking_capture_api():
    requirements = {
        line.strip()
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "chromadb==0.5.23" in requirements
    assert "posthog>=2.4.0,<6.0.0" in requirements


def test_installed_posthog_accepts_chroma_0523_three_positional_capture_shape():
    # Chroma 0.5.23 calls posthog.capture(user_id, event_name, properties).
    # PostHog 6+ broke that positional API. Binding the signature is a local,
    # zero-network compatibility check and does not emit any telemetry event.
    inspect.signature(posthog.capture).bind("anonymous-user", "event", {"k": "v"})


def test_chroma_persistent_client_is_created_with_telemetry_disabled(tmp_path, monkeypatch):
    captured = {}
    sentinel = object()

    def fake_persistent_client(*, path, settings):
        captured["path"] = path
        captured["anonymized_telemetry"] = settings.anonymized_telemetry
        return sentinel

    def fake_quota_client(client, path):
        captured["wrapped_client"] = client
        captured["wrapped_path"] = path
        return client

    monkeypatch.setenv("CHROMA_DB_DIR", str(tmp_path / "vector_db"))
    monkeypatch.setattr(pipeline, "_client", None)
    monkeypatch.setattr(pipeline.chromadb, "PersistentClient", fake_persistent_client)
    monkeypatch.setattr(chroma_quota, "QuotaBoundClient", fake_quota_client)

    client = pipeline.get_client()

    assert client is sentinel
    assert captured["anonymized_telemetry"] is False
    assert Path(captured["path"]).resolve() == (tmp_path / "vector_db").resolve()
    assert captured["wrapped_client"] is sentinel
    assert captured["wrapped_path"] == captured["path"]
