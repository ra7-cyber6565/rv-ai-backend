#!/usr/bin/env python3
"""Verify that release receipts prove one exact, recent, clean Git revision.

This verifier performs no network/model call. It reads three bounded non-secret
receipts, validates each gate contract, checks pass state, freshness and exact
revision binding, then writes a compact manifest containing only hashes,
booleans and the Git SHA.

A hand-written JSON object with a few convenient ``passed=true`` fields must not
be accepted as a real Foundation/live/deployed receipt. Likewise an old live or
deployed receipt must not be replayed indefinitely after provider/deployment
conditions may have changed. This is still not cryptographic signing; it is a
fail-closed structural, freshness and exact-revision verifier for
operator-controlled local receipt files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.release_identity import normalize_git_revision, repository_identity


MAX_RECEIPT_BYTES = 2_000_000
# Exact code does not change between receipts, but live quota/provider and
# deployment state can. Keep code proof reusable for a few days while requiring
# operational proof to be recent.
MAX_FOUNDATION_AGE_SECONDS = 7 * 24 * 60 * 60
MAX_LIVE_AGE_SECONDS = 24 * 60 * 60
MAX_DEPLOYED_AGE_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
_DEPLOYED_GATE = "DEPLOYED_READONLY_ZERO_MODEL_SMOKE"
_REQUIRED_DEPLOYED_CALLS = {
    "GET /health",
    "GET /api",
    "GET /api/v1/processing-capabilities",
    "POST /api/v1/session",
}
_ALLOWED_DEPLOYED_CALL_PREFIXES = (
    "GET /health",
    "GET /api",
    "GET /api/v1/processing-capabilities",
    "POST /api/v1/session",
    "GET /api/v1/reading-sessions?",
    "OPTIONS /api/v1/session",
)


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


def _int_at_least(value: object, minimum: int) -> bool:
    """Parse hostile receipt scalar fail-closed instead of raising."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False
    return parsed >= int(minimum)


def _epoch(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not (number > 0):
        return None
    return number


def _iso_epoch(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or len(text) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return None


def _fresh(timestamp: float | None, *, now: float, max_age: int) -> bool:
    if timestamp is None:
        return False
    age = float(now) - float(timestamp)
    return -MAX_FUTURE_SKEW_SECONDS <= age <= int(max_age)


def _live_contract_ok(live: Mapping[str, object]) -> bool:
    preflight = live.get("zero_cost_preflight")
    if not isinstance(preflight, Mapping):
        return False
    blockers = preflight.get("blockers")
    if not isinstance(blockers, list):
        return False
    return bool(
        _schema_at_least(live, 2)
        and preflight.get("ready") is True
        and preflight.get("zero_cost_only") is True
        and _int_at_least(preflight.get("model_layers_usable_now"), 1)
        and preflight.get("storage_validated") is True
        and preflight.get("storage_ready") is True
        and not blockers
    )


def _deployed_contract_ok(deployed: Mapping[str, object]) -> bool:
    calls = deployed.get("calls")
    if not isinstance(calls, list) or not calls:
        return False
    if not all(isinstance(item, str) and 1 <= len(item) <= 300 for item in calls):
        return False
    rows = set(calls)
    required_present = _REQUIRED_DEPLOYED_CALLS.issubset(rows)
    allowed_only = all(
        any(item.startswith(prefix) for prefix in _ALLOWED_DEPLOYED_CALL_PREFIXES)
        for item in calls
    )
    return bool(
        deployed.get("gate") == _DEPLOYED_GATE
        and required_present
        and allowed_only
    )


def verify_release_bundle(
    foundation: Mapping[str, object],
    live: Mapping[str, object],
    deployed: Mapping[str, object],
    *,
    current_identity: Mapping[str, object],
    now_epoch: float | None = None,
) -> dict:
    checks: list[dict[str, object]] = []

    def check(name: str, passed: object, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    now = float(time.time() if now_epoch is None else now_epoch)
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
    foundation_fresh = _fresh(
        _epoch(foundation.get("created_at_epoch")),
        now=now,
        max_age=MAX_FOUNDATION_AGE_SECONDS,
    )
    live_fresh = _fresh(
        _epoch(live.get("created_at_epoch")),
        now=now,
        max_age=MAX_LIVE_AGE_SECONDS,
    )
    deployed_fresh = _fresh(
        _iso_epoch(deployed.get("checked_at_utc")),
        now=now,
        max_age=MAX_DEPLOYED_AGE_SECONDS,
    )

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
        "exact zero-model deployed gate with required safe call ledger",
    )
    check(
        "foundation_receipt_fresh",
        foundation_fresh,
        "foundation proof is not older than 7 days and is not future-dated",
    )
    check(
        "live_receipt_fresh",
        live_fresh,
        "live provider proof is not older than 24 hours and is not future-dated",
    )
    check(
        "deployed_receipt_fresh",
        deployed_fresh,
        "deployed smoke is not older than 24 hours and is not future-dated",
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
        "schema_version": 3,
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
        description="Verify recent Foundation/live/deployed receipts against one Git SHA.",
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
