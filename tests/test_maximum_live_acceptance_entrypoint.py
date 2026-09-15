from __future__ import annotations

import subprocess
import sys

from tools import run_maximum_live_acceptance as pinned


def test_pinned_entrypoint_rejects_non_full_revision(capsys):
    code = pinned.main([
        "--base-url", "https://example.invalid",
        "--receipt-file", "unused.json",
        "--expected-build-revision", "abc123",
    ])
    assert code == 2
    assert "40-hex Git SHA" in capsys.readouterr().err


def test_pinned_entrypoint_forwards_exact_revision_without_network(monkeypatch):
    seen = {}

    def fake_main(argv):
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(pinned.core, "main", fake_main)
    sha = "A" * 40
    code = pinned.main([
        "--base-url", "https://example.invalid",
        "--receipt-file", "receipt.json",
        "--expected-build-revision", sha,
        "--timeout-seconds", "12",
        "--poll-seconds", "1",
    ])
    assert code == 0
    args = seen["argv"]
    index = args.index("--expected-build-revision")
    assert args[index + 1] == sha.lower()


def test_pinned_entrypoint_is_directly_executable_from_repo_root():
    result = subprocess.run(
        [sys.executable, "tools/run_maximum_live_acceptance.py", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "--expected-build-revision" in result.stdout
