"""Trusted operator CLI for capability #103 independent validation.

The HMAC key is read only from ``INFINITY_MATURITY_HMAC_KEY_B64``.  This command
is intended for a protected operator/post-merge environment.  Ordinary PR CI
must never receive the signing key and cannot self-assert independent proof.
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

from research_engine.literature_debate_attestor import (
    attest_literature_debate_independent_validation,
)


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
        description=(
            "Validate an independently produced literature-debate validation "
            "receipt and mint only capability #103 independent-validation proof."
        )
    )
    parser.add_argument("--validation-receipt", required=True)
    parser.add_argument(
        "--reference",
        required=True,
        help="Trusted reference beginning with literature-debate: (for example an external validation run ID).",
    )
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--anchor-out", required=True)
    parser.add_argument("--inventory-out", required=True)
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

        result = attest_literature_debate_independent_validation(
            repo_root=REPO_ROOT,
            validation_receipt_path=args.validation_receipt,
            ledger_path=ledger_path,
            integrity_key=key,
            run_reference=args.reference,
            now=time.time(),
            policy_path=args.policy,
            prior_anchor_token=prior_anchor,
            prior_revision=args.prior_revision,
        )
        capability = result.audit.maturity_report.results[102]
        inventory = {
            "schema_version": 1,
            "created_at_epoch": int(time.time()),
            "revision": result.revision,
            "validation_receipt_sha256": result.validation_receipt_sha256,
            "validation_sha256": result.validation_sha256,
            "validator_count": result.validator_count,
            "total_cases": result.total_cases,
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
            "blocking_capability_ids": list(result.audit.maturity_report.blocking_capability_ids),
            "capability_103": {
                "status": capability.status,
                "missing_proofs": [item.value for item in capability.missing_proofs],
            },
            "ledger_head_hash": result.audit.ledger_status.ledger_head_hash,
            "truth_proven": False,
            "consensus_proves_truth": False,
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
        print(
            f"LITERATURE DEBATE ATTESTATION: FAIL ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )
        return 1

    print("LITERATURE DEBATE ATTESTATION: PASS")
    print(f"Revision: {result.revision}")
    print(
        "#103 independent receipt: "
        f"added={result.receipts_added}, reused={result.receipts_reused}, "
        f"validators={result.validator_count}, cases={result.total_cases}"
    )
    print(
        "NOTE: independent implementation validation does not prove a debated "
        "scientific proposition true, and consensus is not proof."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
