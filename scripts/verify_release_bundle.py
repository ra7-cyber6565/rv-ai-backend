#!/usr/bin/env python3
"""Verify that all release receipts prove the same exact clean Git revision.

This verifier performs no network/model call. It reads the three bounded,
non-secret receipts, validates that each receipt has the expected gate contract,
checks its pass state and revision binding, then writes a compact manifest
containing only hashes, booleans and the Git SHA.

The contract checks matter: a hand-written JSON object with a few convenient
``passed=true`` fields must not be accepted as a real Foundation/live/deployed
receipt. This is still not cryptographic signing; it is a fail-closed structural
and exact-revision verifier for operator-controlled local receipt files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.release_identity import normalize_git_revision, repository_identity


MAX_RECEIPT_BYTES = 2_000_000
_DEPLOYED_GATE = "DEPLOYED_READONLY_ZERO_MODEL_SMOKE"


def _load_receipt(path: Path) -> tuple[dict, str]:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_RECEIPT_BYTES:
            raise ValueError("receipt size safety bound failed")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("receipt could not be read as bounded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("receipt JSON object hona chahiye")
    return value, hashlib.sha256(raw).hexdigest()


def _schema_at_least(receipt: Mapping[str, object], minimum: int) -> bool:
    try:
        value = int(receipt.get("schema_version") or 0)
    except (TypeError, ValueError):
        return False
    return value >= int(minimum)


def _live_contract_ok(live: Mapping[str, object]) -> bool:
    preflight = live.get("zero_cost_preflight")
    if not isinstance(preflight, Mapping):
        return False
    return bool(
        _schema_at_least(live, 2)
        and preflight.get("ready") is True
        and preflight.get("zero_cost_only") is True
        and int(preflight.get("model_layers_usable_now") or 0) >= 1
        and preflight.get("storage_validated") is True
        and preflight.get("storage_ready") is True
        and not (preflight.get("blockers") or [])
    )


def _deployed_contract_ok(deployed: Mapping[str, object]) -> bool:
    calls = deployed.get("calls")
    if not isinstance(calls, list):
        return False
    # The deployed gate is intentionally read-only/zero-model. The receipt must
    # identify that exact gate and contain only the bounded call ledger emitted by
    # the probe, not a generic handcrafted success object.
    return bool(
        deployed.get("gate") == _DEPLOYED_GATE
        and all(isinstance(item, str) and len(item) <= 300 for item in calls)
    )


def verify_release_bundle(
    foundation: Mapping[str, object],
    live: Mapping[str, object],
    deployed: Mapping[str, object],
    *,
    current_identity: Mapping[str, object],
) -> dict:
    checks: list[dict[str, object]] = []

    def check(name: str, passed: object, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    foundation_revision = normalize_git_revision(foundation.get("code_revision"))
    live_revision = normalize_git_revision(live.get("code_revision"))
    deployed_expected = normalize_git_revision(deployed.get("expected_code_revision"))
    deployed_revision = normalize_git_revision(deployed.get("deployed_code_revision"))
    current_revision = normalize_git_revision(current_identity.get("revision"))

    foundation_contract = bool(
        _schema_at_least(foundation, 2)
        and foundation.get("offline_zero_cost") is True
    )
    live_contract = _live_contract_ok(live)
    deployed_contract = _deployed_contract_ok(deployed)

    check(
        "foundation_receipt_contract",
        foundation_contract,
        "schema>=2 and offline_zero_cost=true",
    )
    check(
        "live_receipt_contract",
        live_contract,
        "schema>=2 plus ready confirmed-free model/storage preflight",
    )
    check(
        "deployed_receipt_contract",
        deployed_contract,
        "exact zero-model deployed gate and bounded call ledger",
    )
    check(
        "foundation_gate_passed",
        foundation_contract
        and foundation.get("passed") is True
        and foundation.get("code_identity_verified") is True
        and foundation.get("repository_clean") is True,
        "offline stages plus clean code identity",
    )
    check(
        "live_zero_cost_gate_passed",
        live_contract
        and live.get("passed") is True
        and live.get("repository_clean") is True
        and live.get("contains_answer_or_source_text") is False
        and live.get("contains_credentials") is False,
        "live gate, confirmed-free preflight and receipt privacy contract",
    )
    check(
        "deployed_zero_model_gate_passed",
        deployed_contract
        and deployed.get("complete") is True
        and deployed.get("zero_model_calls_by_construction") is True
        and deployed.get("capabilities_or_secrets_recorded") is False,
        "deployed smoke and capability privacy contract",
    )
    check(
        "deployed_revision_matches_expected",
        bool(deployed_expected) and deployed_revision == deployed_expected,
        "deployment reported the expected full Git SHA",
    )
    revisions = {
        foundation_revision, live_revision, deployed_expected,
        deployed_revision, current_revision,
    }
    check(
        "all_receipts_same_revision",
        "" not in revisions and len(revisions) == 1,
        "foundation/live/deployed/current revisions are identical",
    )
    check(
        "current_checkout_clean",
        current_identity.get("available") is True
        and current_identity.get("clean") is True
        and bool(current_revision),
        "current release-verifier checkout is committed and clean",
    )
    passed = all(bool(row["passed"]) for row in checks)
    common_revision = foundation_revision if passed else ""
    return {
        "schema_version": 2,
        "gate": "EXACT_REVISION_RELEASE_BUNDLE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "code_revision": common_revision,
        "checks": checks,
        "contains_credentials_or_capabilities": False,
    }


def _write_manifest(path: Path, payload: Mapping[str, object]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Foundation/live/deployed receipts against one Git SHA.",
    )
    parser.add_argument("--foundation", required=True)
    parser.add_argument("--live", required=True)
    parser.add_argument("--deployed", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        foundation, foundation_hash = _load_receipt(Path(args.foundation))
        live, live_hash = _load_receipt(Path(args.live))
        deployed, deployed_hash = _load_receipt(Path(args.deployed))
        result = verify_release_bundle(
            foundation,
            live,
            deployed,
            current_identity=repository_identity(ROOT),
        )
        result["receipt_sha256"] = {
            "foundation": foundation_hash,
            "live": live_hash,
            "deployed": deployed_hash,
        }
        _write_manifest(Path(args.output), result)
    except ValueError as exc:
        print(f"RELEASE BUNDLE: FAIL — {exc}")
        return 1
    except OSError:
        print("RELEASE BUNDLE: FAIL — manifest write failed safely")
        return 1

    for row in result["checks"]:
        print(f"[{'PASS' if row['passed'] else 'FAIL'}] {row['name']}: {row['detail']}")
    print("EXACT-REVISION RELEASE BUNDLE: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
