#!/usr/bin/env python3
"""Evaluate a frozen held-out campaign without printing raw answers or gold data."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.heldout_release_gate import HeldoutGateError, assess_release
from utils.research_runtime import digest


def _read(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HeldoutGateError(f"{label} JSON is unavailable or invalid") from exc


def _file_sha256(path: str) -> str:
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError as exc:
        raise HeldoutGateError("input artifact became unavailable before receipt binding") from exc
    return hasher.hexdigest()


def _write(path: str, receipt: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Blind untouched-holdout manifest JSON")
    parser.add_argument("--baseline", required=True, help="Independently graded baseline receipt rows")
    parser.add_argument("--candidate", required=True, help="Independently graded candidate receipt rows")
    parser.add_argument("--policy", required=True, help="Predeclared frozen release policy JSON")
    parser.add_argument("--campaign", required=True, help="Revision/freeze provenance receipt JSON")
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("--receipt-file", required=True, help="Sanitized output receipt; no answer/gold rows")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--draws", type=int, default=2000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = assess_release(
            _read(args.manifest, "manifest"),
            _read(args.baseline, "baseline"),
            _read(args.candidate, "candidate"),
            _read(args.policy, "policy"),
            _read(args.campaign, "campaign"),
            expected_manifest_hash=args.expected_manifest_sha256,
            expected_policy_hash=args.expected_policy_sha256,
            seed=args.seed,
            draws=args.draws,
        )
        receipt.pop("receipt_sha256", None)
        receipt["input_artifacts_sha256"] = {
            "manifest": _file_sha256(args.manifest),
            "baseline": _file_sha256(args.baseline),
            "candidate": _file_sha256(args.candidate),
            "policy": _file_sha256(args.policy),
            "campaign": _file_sha256(args.campaign),
        }
        receipt["receipt_sha256"] = digest(receipt)
        _write(args.receipt_file, receipt)
    except (HeldoutGateError, ValueError) as exc:
        # The paired evaluator uses fixed ValueError messages for malformed
        # pairing/provenance. Never print JSON rows, answers or provider bodies.
        print(f"HELDOUT_RELEASE_INVALID: {exc}", file=sys.stderr)
        return 4
    decision = receipt["decision"]
    print(f"HELDOUT_RELEASE_{decision}: receipt={args.receipt_file}")
    if decision == "PASS":
        return 0
    if decision == "FAIL":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
