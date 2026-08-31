#!/usr/bin/env python3
"""Verify one externally signed generic maturity-proof receipt.

Required secrets are supplied only through environment variables:
- RV_AI_PROOF_LEDGER_KEY_HEX: HMAC key for the local proof ledger/anchor.
- RV_AI_EXTERNAL_VERIFIER_KEY_HEX: independent HMAC key used by the external
  evidence issuer/verifier.

This CLI does not create or sign external evidence. It only verifies an already
signed receipt against the exact clean Git revision and committed proof policy.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from research_engine.external_proof_attestor import attest_external_proof


def _secret_from_env(name: str) -> bytes:
    raw = str(os.environ.get(name) or "").strip()
    if len(raw) < 64 or len(raw) % 2:
        raise SystemExit(f"{name} must contain at least 32 bytes as hex")
    try:
        value = bytes.fromhex(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} is not valid hex") from exc
    if len(value) < 32:
        raise SystemExit(f"{name} must contain at least 32 bytes")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--prior-anchor", default="")
    parser.add_argument("--prior-revision", default="")
    parser.add_argument("--anchor-output", default="")
    args = parser.parse_args()

    ledger_key = _secret_from_env("RV_AI_PROOF_LEDGER_KEY_HEX")
    verifier_key = _secret_from_env("RV_AI_EXTERNAL_VERIFIER_KEY_HEX")
    result = attest_external_proof(
        repo_root=args.repo_root,
        evidence_receipt_path=args.receipt,
        ledger_path=args.ledger,
        ledger_integrity_key=ledger_key,
        verifier_key=verifier_key,
        now=time.time(),
        prior_anchor_token=args.prior_anchor,
        prior_revision=args.prior_revision,
    )

    if args.anchor_output:
        target = Path(args.anchor_output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(result.anchor_token + "\n", encoding="utf-8")
        os.replace(temporary, target)

    print(json.dumps({
        "revision": result.revision,
        "capability_id": result.capability_id,
        "proof_kind": result.proof_kind.value,
        "receipt_sha256": result.receipt_sha256,
        "receipts_added": result.receipts_added,
        "receipts_reused": result.receipts_reused,
        "audit_valid": result.audit.audit_valid,
        "maturity_score": result.audit.maturity_report.score,
        "anchor_token": result.anchor_token,
        "note": (
            "Attestation records a signed external observation only. It is not "
            "scientific truth, profitability, safety beyond the scoped safety "
            "gate, or evidence for any other capability/proof route."
        ),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
