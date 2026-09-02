"""Trusted execution benchmark for reproducibility/capsule/crypto primitives.

Specializes software EXECUTION + REPRODUCIBILITY routes for:
- #24 Experiment Reproducibility Package
- #79 Cryptographic Evidence Integrity
- #80 Reproducible Research Capsule

The benchmark proves deterministic tracked software behaviour only.  It does
NOT mint #79 PERSISTENCE/SAFETY or #80 PERSISTENCE.  Protected key custody,
external latest-anchor storage, durable archive retention and operational
security remain separate evidence requirements.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from utils.release_identity import repository_identity

from . import maturity_proof as proof_mod
from . import research_capsule as capsule_mod
from .capability_registry import ProofKind
from .maturity_attestor import _existing_adds, _outside_repo, _safe_reference
from .maturity_auditor import (
    TrustedMaturityAudit,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _tracked_index,
    audit_repository_maturity,
)
from .maturity_proof import ProofLedger
from .research_capsule import CapsuleArtifact


_CAPABILITY_IDS = (24, 79, 80)
_REQUIRED = (ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY)
_SUBJECT = "reproducibility-integrity-benchmark"
_VERIFIER = "trusted-operator"
_CAPSULE_ENGINE = "research_engine/research_capsule.py"
_PROOF_ENGINE = "research_engine/maturity_proof.py"
_BENCHMARK_VERSION = "reproducibility-integrity-benchmark-v1"
_FIXTURE_KEY = b"R" * 32


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _artifacts():
    return (
        CapsuleArtifact(
            "source",
            "sources/paper.txt",
            b"source text fixture\n",
            "text/plain",
            ("SRC-FIXTURE",),
        ),
        CapsuleArtifact(
            "code",
            "code/model.py",
            b"RESULT = 42\n",
            "text/x-python",
            ("REV-FIXTURE",),
        ),
        CapsuleArtifact(
            "result",
            "results/metrics.json",
            b'{"score":0.75}',
            "application/json",
            ("RUN-FIXTURE",),
        ),
    )


def _tampered_capsule(payload: bytes, *, path: str, replacement: bytes) -> bytes:
    original = zipfile.ZipFile(io.BytesIO(payload), "r")
    try:
        entries = {name: original.read(name) for name in original.namelist()}
    finally:
        original.close()
    entries[path] = replacement
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in sorted(entries):
            archive.writestr(name, entries[name])
    return output.getvalue()


def _crypto_fixture() -> Mapping[str, Any]:
    with tempfile.TemporaryDirectory(prefix="integrity_fixture_") as directory:
        path = Path(directory) / "proofs.jsonl"
        ledger = ProofLedger(str(path), integrity_key=_FIXTURE_KEY)
        ledger.add(
            receipt_id="fixture-code",
            capability_id=1,
            proof_kind=ProofKind.CODE,
            subject="fixture/code.py",
            subject_sha256=hashlib.sha256(b"code").hexdigest(),
            verifier="fixture-ci",
            observed_at=100.0,
            implementation_revision="fixture-rev",
        )
        ledger.add(
            receipt_id="fixture-test",
            capability_id=1,
            proof_kind=ProofKind.TEST,
            subject="fixture/test_code.py",
            subject_sha256=hashlib.sha256(b"test").hexdigest(),
            verifier="fixture-ci",
            observed_at=101.0,
            implementation_revision="fixture-rev",
        )
        anchor = ledger.create_anchor(
            current_revision="fixture-rev",
            issued_at=102.0,
        )
        intact_chain = ledger.verify_chain(
            anchor_token=anchor,
            current_revision="fixture-rev",
        )
        wrong_revision = ledger.verify_chain(
            anchor_token=anchor,
            current_revision="other-rev",
        )
        wrong_key = ProofLedger(
            str(path), integrity_key=b"W" * 32
        ).verify_chain(
            anchor_token=anchor,
            current_revision="fixture-rev",
        )

        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[0] + "\n", encoding="utf-8")
        raw_prefix_chain = ledger.verify_chain()
        retained_anchor_detects_truncation = not ledger.verify_chain(
            anchor_token=anchor,
            current_revision="fixture-rev",
        )
        return {
            "intact_chain_verified": intact_chain,
            "wrong_revision_rejected": wrong_revision is False,
            "wrong_key_rejected": wrong_key is False,
            "valid_prefix_still_internally_consistent": raw_prefix_chain,
            "retained_anchor_detects_truncation": retained_anchor_detects_truncation,
            "fixture_event_count_before_truncation": len(lines),
        }


def run_reproducibility_integrity_benchmark() -> Mapping[str, Any]:
    artifacts = _artifacts()
    one = capsule_mod.build_capsule(
        artifacts,
        environment={"python": "3.11", "lock_sha256": "f" * 64},
        metadata={"question_id": "Q-FIXTURE"},
    )
    two = capsule_mod.build_capsule(
        tuple(reversed(artifacts)),
        environment={"python": "3.11", "lock_sha256": "f" * 64},
        metadata={"question_id": "Q-FIXTURE"},
    )
    verified = capsule_mod.verify_capsule_bytes(one.bytes_data)

    tampered = _tampered_capsule(
        one.bytes_data,
        path="results/metrics.json",
        replacement=b'{"score":999}',
    )
    tamper_verification = capsule_mod.verify_capsule_bytes(tampered)

    with tempfile.TemporaryDirectory(prefix="capsule_roundtrip_") as directory:
        target = Path(directory) / "research.zip"
        written = capsule_mod.write_capsule(str(target), one)
        reopened = capsule_mod.verify_capsule_file(written)
        disk_bytes_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()

    secret_path_rejected = False
    traversal_rejected = False
    try:
        capsule_mod.build_capsule(
            [CapsuleArtifact("data", "keys/api_key.txt", b"secret")],
            environment={},
        )
    except ValueError:
        secret_path_rejected = True
    try:
        capsule_mod.build_capsule(
            [CapsuleArtifact("data", "../escape.txt", b"x")],
            environment={},
        )
    except ValueError:
        traversal_rejected = True

    crypto = _crypto_fixture()
    checks = {
        "capsule_is_byte_deterministic_under_input_reordering": (
            one.capsule_id == two.capsule_id
            and one.capsule_sha256 == two.capsule_sha256
            and one.bytes_data == two.bytes_data
        ),
        "capsule_self_verification_succeeds": (
            verified.valid is True
            and verified.capsule_id == one.capsule_id
            and verified.artifact_count == len(artifacts)
        ),
        "artifact_tampering_is_detected": (
            tamper_verification.valid is False
            and any("hash mismatch" in error for error in tamper_verification.errors)
        ),
        "file_roundtrip_preserves_exact_capsule": (
            reopened.valid is True
            and reopened.capsule_id == one.capsule_id
            and disk_bytes_sha256 == one.capsule_sha256
        ),
        "unsafe_secret_and_traversal_paths_are_rejected": (
            secret_path_rejected and traversal_rejected
        ),
        "hmac_chain_and_external_anchor_verify": (
            crypto["intact_chain_verified"] is True
            and crypto["wrong_revision_rejected"] is True
            and crypto["wrong_key_rejected"] is True
        ),
        "retained_anchor_detects_valid_prefix_rollback": (
            crypto["valid_prefix_still_internally_consistent"] is True
            and crypto["retained_anchor_detects_truncation"] is True
        ),
    }
    payload = {
        "benchmark_version": _BENCHMARK_VERSION,
        "checks": checks,
        "capsule": {
            "capsule_id": one.capsule_id,
            "capsule_sha256": one.capsule_sha256,
            "artifact_count": verified.artifact_count,
            "tamper_errors": tuple(tamper_verification.errors),
            "disk_roundtrip_sha256": disk_bytes_sha256,
        },
        "cryptographic_integrity": dict(crypto),
        "persistent_archive_retention_observed": False,
        "protected_key_custody_observed": False,
        "external_anchor_retention_service_observed": False,
        "safety_certified": False,
        "truth_proven": False,
    }
    return {
        **payload,
        "benchmark_passed": all(checks.values()),
        "benchmark_sha256": _sha(payload),
    }


@dataclass(frozen=True)
class ReproducibilityIntegrityAttestation:
    revision: str
    capsule_engine_sha256: str
    proof_engine_sha256: str
    benchmark_sha256: str
    receipts_added: int
    receipts_reused: int
    anchor_token: str
    audit: TrustedMaturityAudit
    persistent_archive_retention_observed: bool = False
    protected_key_custody_observed: bool = False
    external_anchor_retention_service_observed: bool = False
    safety_certified: bool = False
    truth_proven: bool = False


def _same_receipt(
    row: Mapping[str, Any],
    *,
    capability_id: int,
    kind: ProofKind,
    digest: str,
    reference: str,
    revision: str,
) -> bool:
    expected = {
        "capability_id": capability_id,
        "proof_kind": kind.value,
        "subject": _SUBJECT,
        "subject_sha256": digest,
        "verifier": _VERIFIER,
        "reference": reference,
        "implementation_revision": revision,
    }
    return all(row.get(key) == value for key, value in expected.items())


def attest_reproducibility_integrity(
    *,
    repo_root: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str],
    integrity_key: bytes,
    run_reference: str,
    now: float,
    policy_path: str = "config/maturity_proof_policy.json",
    prior_anchor_token: str = "",
    prior_revision: str = "",
) -> ReproducibilityIntegrityAttestation:
    current_time = float(now)
    if not math.isfinite(current_time):
        raise ValueError("now must be finite")
    reference = _safe_reference(run_reference)
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    ledger_target = Path(ledger_path).expanduser().resolve()
    if not _outside_repo(root, ledger_target):
        raise ValueError("maturity ledger must live outside the audited repository")

    identity_before = repository_identity(root)
    revision = str(identity_before.get("revision") or "")
    if not identity_before.get("available") or not identity_before.get("clean") or not revision:
        raise ValueError("integrity attestation requires a clean Git checkout")

    tracked = _tracked_index(root)
    capsule_digest = _hash_tracked_regular(root, tracked, _CAPSULE_ENGINE)
    proof_digest = _hash_tracked_regular(root, tracked, _PROOF_ENGINE)
    if Path(str(capsule_mod.__file__)).resolve(strict=True) != (root / _CAPSULE_ENGINE).resolve(strict=True):
        raise ValueError("research capsule runtime is not loaded from the audited repository")
    if Path(str(proof_mod.__file__)).resolve(strict=True) != (root / _PROOF_ENGINE).resolve(strict=True):
        raise ValueError("maturity proof runtime is not loaded from the audited repository")

    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            matching = tuple(
                rule for rule in policy.rules
                if rule.capability_id == capability_id
                and rule.proof_kind is kind
                and _SUBJECT in rule.subjects
                and _VERIFIER in rule.verifiers
            )
            if not matching:
                raise ValueError(
                    f"committed proof policy has no trusted c{capability_id} {kind.value} integrity rule"
                )
            if not any(
                not rule.reference_prefixes
                or any(reference.startswith(prefix) for prefix in rule.reference_prefixes)
                for rule in matching
            ):
                raise ValueError("run_reference is not allowed by integrity proof policy")

    ledger_exists = ledger_target.exists() and ledger_target.stat().st_size > 0
    if ledger_exists:
        prior = str(prior_revision or "").strip().lower()
        if not prior_anchor_token or not prior:
            raise ValueError("existing maturity ledger requires prior trusted anchor and revision")
        continuity = ProofLedger(str(ledger_target), integrity_key=integrity_key)
        if not continuity.verify_chain(
            anchor_token=prior_anchor_token,
            current_revision=prior,
        ):
            raise ValueError("existing maturity ledger failed prior anchor continuity check")
    elif prior_anchor_token or prior_revision:
        raise ValueError("prior anchor/revision supplied for an empty maturity ledger")

    first = run_reproducibility_integrity_benchmark()
    second = run_reproducibility_integrity_benchmark()
    if first.get("benchmark_passed") is not True or second.get("benchmark_passed") is not True:
        raise ValueError("reproducibility/integrity benchmark failed")
    if _canonical(first) != _canonical(second):
        raise ValueError("reproducibility/integrity benchmark is not deterministic")
    benchmark_digest = str(first.get("benchmark_sha256") or "")
    payload_for_digest = {
        key: value for key, value in first.items()
        if key not in {"benchmark_passed", "benchmark_sha256"}
    }
    if len(benchmark_digest) != 64 or benchmark_digest != _sha(payload_for_digest):
        raise ValueError("reproducibility/integrity benchmark digest verification failed")

    receipt_digest = _sha({
        "revision": revision,
        "capsule_engine_sha256": capsule_digest,
        "proof_engine_sha256": proof_digest,
        "benchmark_sha256": benchmark_digest,
        "subject": _SUBJECT,
        "capabilities": _CAPABILITY_IDS,
    })
    ledger = ProofLedger(str(ledger_target), integrity_key=integrity_key)
    existing = _existing_adds(ledger)
    added = reused = 0
    for capability_id in _CAPABILITY_IDS:
        for kind in _REQUIRED:
            receipt_id = (
                f"repro-integrity:{revision[:12]}:c{capability_id}:{kind.value}"
            )
            previous = existing.get(receipt_id)
            if previous is not None:
                if not _same_receipt(
                    previous,
                    capability_id=capability_id,
                    kind=kind,
                    digest=receipt_digest,
                    reference=reference,
                    revision=revision,
                ):
                    raise ValueError("deterministic integrity receipt_id collision")
                reused += 1
                continue
            ledger.add(
                receipt_id=receipt_id,
                capability_id=capability_id,
                proof_kind=kind,
                subject=_SUBJECT,
                subject_sha256=receipt_digest,
                verifier=_VERIFIER,
                observed_at=current_time,
                reference=reference,
                implementation_revision=revision,
            )
            added += 1

    anchor = ledger.create_anchor(current_revision=revision, issued_at=current_time)
    audit = audit_repository_maturity(
        repo_root=root,
        ledger_path=ledger_target,
        integrity_key=integrity_key,
        anchor_token=anchor,
        now=current_time,
        policy_path=policy_path,
    )
    if not audit.audit_valid:
        raise ValueError("trusted maturity audit rejected integrity attestation")

    identity_after = repository_identity(root)
    if (
        not identity_after.get("available")
        or not identity_after.get("clean")
        or str(identity_after.get("revision") or "") != revision
    ):
        raise ValueError("repository changed during integrity attestation")

    return ReproducibilityIntegrityAttestation(
        revision=revision,
        capsule_engine_sha256=capsule_digest,
        proof_engine_sha256=proof_digest,
        benchmark_sha256=benchmark_digest,
        receipts_added=added,
        receipts_reused=reused,
        anchor_token=anchor,
        audit=audit,
    )
