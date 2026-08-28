"""Trusted operator CLI for conservative Foundation maturity attestation.

The HMAC key must be supplied through ``INFINITY_MATURITY_HMAC_KEY_B64`` and is
never printed or persisted. This command intentionally belongs in a protected
post-merge/operator context, not in an ordinary pull-request job that executes
mutable PR code with secrets.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_engine.maturity_attestor import attest_foundation_code_test_proofs


_KEY_ENV = "INFINITY_MATURITY_HMAC_KEY_B64"
_MAX_ANCHOR_BYTES = 16_384


def _decode_key() -> bytes:
    text = str(os.environ.get(_KEY_ENV, "") or "").strip()
    if not text:
        raise ValueError(f"{_KEY_ENV} is required")
    try:
        padding = "=" * ((4 - len(text) % 4) % 4)
        key = base64.b64decode(
            (text + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except Exception as exc:
        raise ValueError(f"{_KEY_ENV} must be valid base64/base64url") from exc
    if len(key) < 32:
        raise ValueError(f"{_KEY_ENV} must decode to at least 32 bytes")
    return key


def _outside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError("attestation output paths must live outside the repository")


def _read_anchor(path: str | None) -> str:
    if not path:
        return ""
    candidate = Path(path).expanduser().resolve()
    try:
        info = candidate.stat()
    except OSError as exc:
        raise ValueError("prior anchor file cannot be read") from exc
    if not candidate.is_file() or info.st_size < 1 or info.st_size > _MAX_ANCHOR_BYTES:
        raise ValueError("prior anchor file size is invalid")
    text = candidate.read_text(encoding="utf-8").strip()
    if not text or len(text.encode("utf-8")) > _MAX_ANCHOR_BYTES:
        raise ValueError("prior anchor file is invalid")
    return text


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Attest only CODE/TEST maturity proofs from a green Foundation receipt."
    )
    parser.add_argument("--foundation-receipt", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--anchor-out", required=True)
    parser.add_argument("--inventory-out", required=True)
    parser.add_argument("--run-reference", required=True)
    parser.add_argument("--prior-anchor")
    parser.add_argument("--prior-revision", default="")
    parser.add_argument(
        "--policy",
        default="config/maturity_proof_policy.json",
        help="Committed repository proof policy path.",
    )
    args = parser.parse_args(argv)

    try:
        key = _decode_key()
        ledger_path = _outside_repo(Path(args.ledger))
        anchor_out = _outside_repo(Path(args.anchor_out))
        inventory_out = _outside_repo(Path(args.inventory_out))
        if len({ledger_path, anchor_out, inventory_out}) != 3:
            raise ValueError("ledger, anchor and inventory paths must be distinct")
        prior_anchor = _read_anchor(args.prior_anchor)

        result = attest_foundation_code_test_proofs(
            repo_root=REPO_ROOT,
            foundation_receipt_path=args.foundation_receipt,
            ledger_path=ledger_path,
            integrity_key=key,
            run_reference=args.run_reference,
            now=time.time(),
            policy_path=args.policy,
            prior_anchor_token=prior_anchor,
            prior_revision=args.prior_revision,
        )
        inventory = {
            "schema_version": 1,
            "created_at_epoch": int(time.time()),
            "revision": result.revision,
            "foundation_receipt_sha256": result.foundation_receipt_sha256,
            "receipts_added": result.receipts_added,
            "receipts_reused": result.receipts_reused,
            "audit_valid": result.audit.audit_valid,
            "max_level_eligible": result.audit.max_level_eligible,
            "cryptographic_integrity": result.audit.cryptographic_integrity,
            "policy_sha256": result.audit.policy_sha256,
            "audit_sha256": result.audit.audit_sha256,
            "verified_capabilities": result.audit.maturity_report.verified,
            "total_capabilities": result.audit.maturity_report.total,
            "proof_completion_score": result.audit.maturity_report.proof_completion_score,
            "blocking_capability_ids": list(
                result.audit.maturity_report.blocking_capability_ids
            ),
            "blockers": [
                {
                    "capability_id": item.capability_id,
                    "name": item.name,
                    "missing_proofs": list(item.missing_proofs),
                }
                for item in result.audit.blockers
            ],
            "ledger_head_hash": result.audit.ledger_status.ledger_head_hash,
        }
        _atomic_text(anchor_out, result.anchor_token + "\n")
        _atomic_text(
            inventory_out,
            json.dumps(
                inventory,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            ) + "\n",
        )
    except Exception as exc:
        print(f"MATURITY ATTESTATION: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1

    print("MATURITY ATTESTATION: PASS")
    print(f"Revision: {result.revision}")
    print(
        "CODE/TEST receipts: "
        f"added={result.receipts_added}, reused={result.receipts_reused}"
    )
    print(
        "Verified capabilities: "
        f"{result.audit.maturity_report.verified}/{result.audit.maturity_report.total}"
    )
    print(
        "Proof-completion score: "
        f"{result.audit.maturity_report.proof_completion_score:.2f}%"
    )
    print("NOTE: this command does not mint execution/repro/safety/live/hardware proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
