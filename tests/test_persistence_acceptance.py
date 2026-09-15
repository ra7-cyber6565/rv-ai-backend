from __future__ import annotations

import json
from pathlib import Path

from tools.persistence_acceptance import (
    _storage_receipt,
    _write_private_json,
    _write_receipt,
    result_digest,
    stable_result,
)


def test_stable_result_ignores_runtime_progress_only():
    before = {
        "status": "COMPLETE",
        "answer": "same",
        "sources": [{"title": "A", "url": "https://example.test/a"}],
        "research_progress": {"stages_done": 4, "log": [{"stage": "READING"}]},
    }
    after = {
        "status": "COMPLETE",
        "answer": "same",
        "sources": [{"title": "A", "url": "https://example.test/a"}],
        "research_progress": {"available": False},
    }

    assert stable_result(before) == stable_result(after)
    assert result_digest(before) == result_digest(after)


def test_stable_digest_detects_semantic_result_change():
    original = {"status": "COMPLETE", "answer": "alpha", "research_progress": {"available": True}}
    changed = {"status": "COMPLETE", "answer": "beta", "research_progress": {"available": False}}

    assert result_digest(original) != result_digest(changed)


def test_storage_receipt_is_strict_allowlist_and_hides_paths():
    health = {
        "storage": {
            "available": True,
            "configured": True,
            "split_storage": True,
            "durable_available": True,
            "ephemeral_available": True,
            "durable_root": "/data/private",
            "ephemeral_root": "/tmp/private",
            "raw_error": "secret path /home/user",
        }
    }

    receipt = _storage_receipt(health)
    text = json.dumps(receipt)
    assert receipt["split_storage"] is True
    assert "/data" not in text
    assert "/tmp" not in text
    assert "raw_error" not in receipt


def test_private_state_keeps_token_out_of_sanitized_receipt(tmp_path: Path):
    state_path = tmp_path / "private.json"
    receipt_path = tmp_path / "receipt.json"
    token = "super-secret-job-capability"

    _write_private_json(
        state_path,
        {
            "job_id": "job_1234567890123456",
            "job_access_token": token,
            "digest_before": "a" * 64,
        },
    )
    _write_receipt(
        receipt_path,
        {
            "job_id": "job_1234567890123456",
            "stable_result_sha256": "a" * 64,
            "private_capability_in_receipt": False,
        },
    )

    assert token in state_path.read_text(encoding="utf-8")
    assert token not in receipt_path.read_text(encoding="utf-8")
