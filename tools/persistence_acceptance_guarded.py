#!/usr/bin/env python3
"""Fail-closed Railway persistence acceptance entrypoint.

This is a thin safety wrapper around ``tools.persistence_acceptance``.  The
underlying two-phase client owns the public API requests, private capability
state, and stable-result hashing.  This wrapper adds the production preconditions
that the historical harness lacked:

* the deployed build must equal one explicitly reviewed full Git SHA;
* public storage health must attest a Railway runtime;
* both Railway Volume markers must be present;
* the runtime mount must match the configured durable root; and
* ``persistent_volume_ready`` must be true before *every* phase health read.

The wrapper never restarts or deploys Railway.  A controlled restart remains an
operator action between phases.  It never uploads or prints the private job
capability.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from tools import persistence_acceptance as core

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_VOLUME_FIELDS = (
    "railway_runtime",
    "railway_volume_attached",
    "railway_volume_mount_matches_durable_root",
    "persistent_volume_ready",
)


class GuardedAcceptanceError(RuntimeError):
    """Public-safe fixed-code failure from persistence preflight."""


def _reviewed_sha(value: object) -> str:
    text = str(value or "").strip().lower()
    if not _SHA40.fullmatch(text):
        raise GuardedAcceptanceError("invalid_reviewed_revision")
    return text


def storage_receipt(health: dict[str, Any]) -> dict[str, Any]:
    """Extend the historical sanitized receipt with path-free Volume booleans."""
    receipt = dict(core._storage_receipt(health))
    storage = health.get("storage")
    if not isinstance(storage, dict):
        return receipt
    for key in _VOLUME_FIELDS:
        if key in storage:
            receipt[key] = storage.get(key) is True
    return receipt


def validate_persistent_health(
    health: Any,
    *,
    expected_build_revision: str,
) -> dict[str, Any]:
    """Fail closed unless this exact reviewed Railway build has a real /data Volume."""
    expected = _reviewed_sha(expected_build_revision)
    if not isinstance(health, dict):
        raise GuardedAcceptanceError("health_not_object")
    build = str(health.get("build_revision") or "").strip().lower()
    if build != expected:
        raise GuardedAcceptanceError("deployed_revision_mismatch")
    storage = health.get("storage")
    if not isinstance(storage, dict):
        raise GuardedAcceptanceError("storage_status_missing")
    if storage.get("available") is not True or storage.get("split_storage") is not True:
        raise GuardedAcceptanceError("split_storage_not_ready")
    if storage.get("railway_runtime") is not True:
        raise GuardedAcceptanceError("railway_runtime_not_attested")
    if storage.get("railway_volume_attached") is not True:
        raise GuardedAcceptanceError("railway_volume_not_attached")
    if storage.get("railway_volume_mount_matches_durable_root") is not True:
        raise GuardedAcceptanceError("railway_volume_mount_mismatch")
    if storage.get("persistent_volume_ready") is not True:
        raise GuardedAcceptanceError("persistent_volume_not_ready")
    return {
        "build_revision": build,
        "service_health": str(health.get("status") or ""),
        "storage": storage_receipt(health),
        "persistent_volume_ready": True,
    }


def _state_revision(path: str) -> str:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardedAcceptanceError("private_state_invalid") from exc
    if not isinstance(value, dict):
        raise GuardedAcceptanceError("private_state_invalid")
    return _reviewed_sha(value.get("build_revision_before"))


def _run_with_guard(args: argparse.Namespace, expected_revision: str) -> dict[str, Any]:
    """Inject the same exact-build/Volume validation into every core health read."""
    original_health = core._health
    original_receipt = core._storage_receipt

    def guarded_health(base_url: str) -> dict[str, Any]:
        health = original_health(base_url)
        validate_persistent_health(
            health,
            expected_build_revision=expected_revision,
        )
        return health

    core._health = guarded_health
    core._storage_receipt = storage_receipt
    try:
        if args.phase == "before-restart":
            return core._phase1(args)
        return core._phase2(args)
    finally:
        core._health = original_health
        core._storage_receipt = original_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)

    before = sub.add_parser("before-restart")
    before.add_argument("--base-url", required=True)
    before.add_argument("--expected-build-revision", required=True)
    before.add_argument("--state-file", required=True)
    before.add_argument("--receipt-file", required=True)
    before.add_argument(
        "--question",
        default=(
            "Persistence acceptance test: give one concise source-backed fact about "
            "Python's standard library. Keep the answer short."
        ),
    )
    before.add_argument("--depth-mode", default="QUICK", choices=["QUICK"])
    before.add_argument("--timeout-seconds", type=float, default=600.0)
    before.add_argument("--poll-seconds", type=float, default=2.0)

    after = sub.add_parser("after-restart")
    after.add_argument("--base-url", default="")
    after.add_argument("--state-file", required=True)
    after.add_argument("--receipt-file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.phase == "before-restart":
            expected = _reviewed_sha(args.expected_build_revision)
        else:
            expected = _state_revision(args.state_file)
        receipt = _run_with_guard(args, expected)
    except GuardedAcceptanceError as exc:
        print(f"PERSISTENCE_GUARD_FAIL:{exc}", file=sys.stderr)
        return 3
    except core.AcceptanceError:
        # Core errors can contain server detail strings. Keep the public failure
        # surface fixed; sanitized receipts remain the only shareable artifacts.
        print("PERSISTENCE_ACCEPTANCE_FAIL:core_acceptance_failed", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
