"""Offline tests for async research-job capability tokens."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from utils.job_access import JobCapabilitySigner


def test_token_is_stable_across_signer_restart(tmp_path):
    secret = tmp_path / "job-secret.bin"
    job_id = "a" * 32

    signer1 = JobCapabilitySigner(str(secret))
    token1 = signer1.issue(job_id)
    assert token1
    assert signer1.verify(job_id, token1) is True
    assert secret.is_file()
    assert secret.stat().st_size == 32

    signer2 = JobCapabilitySigner(str(secret))
    token2 = signer2.issue(job_id)
    assert token2 == token1
    assert signer2.verify(job_id, token1) is True


def test_wrong_job_or_wrong_token_is_rejected(tmp_path):
    signer = JobCapabilitySigner(str(tmp_path / "secret.bin"))
    one = "1" * 32
    two = "2" * 32
    token = signer.issue(one)

    assert signer.verify(one, token) is True
    assert signer.verify(two, token) is False
    assert signer.verify(one, "wrong-token") is False
    assert signer.verify(one, "") is False
    assert signer.verify("../bad", token) is False


def test_secret_file_does_not_contain_job_id_or_bearer_token(tmp_path):
    path = tmp_path / "secret.bin"
    signer = JobCapabilitySigner(str(path))
    job_id = "job_abcdefghijklmnop"
    token = signer.issue(job_id)

    raw = path.read_bytes()
    assert len(raw) == 32
    assert job_id.encode("utf-8") not in raw
    assert token.encode("utf-8") not in raw


def test_corrupt_secret_fails_closed_instead_of_regenerating(tmp_path):
    path = tmp_path / "secret.bin"
    path.write_bytes(b"broken")
    signer = JobCapabilitySigner(str(path))

    assert signer.verify("a" * 32, "anything") is False
    assert path.read_bytes() == b"broken", "corrupt secret ko silently replace mat karo"
    assert signer.status()["job_capability_tokens_ready"] is False


def test_status_exposes_only_boolean_readiness(tmp_path):
    path = tmp_path / "secret.bin"
    signer = JobCapabilitySigner(str(path))
    status = signer.status()
    assert status == {"job_capability_tokens_ready": True}
    text = repr(status)
    assert str(path) not in text
    assert path.read_bytes() not in text.encode("utf-8")


def test_parallel_signer_instances_publish_one_secret_and_same_token(tmp_path):
    path = str(tmp_path / "secret.bin")
    job_id = "parallel_job_abcdefghijklmnop"

    def issue_once(_index: int) -> str:
        return JobCapabilitySigner(path).issue(job_id)

    with ThreadPoolExecutor(max_workers=12) as pool:
        tokens = list(pool.map(issue_once, range(48)))

    assert len(set(tokens)) == 1
    assert len(Path(path).read_bytes()) == 32
    assert JobCapabilitySigner(path).verify(job_id, tokens[0]) is True
