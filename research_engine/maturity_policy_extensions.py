"""Compile explicit maturity proof-route extensions without minting evidence.

The base proof policy intentionally stays human-reviewable.  This module lets the
repository add the large set of still-missing acceptance *routes* in a compact,
bounded manifest while preserving the exact same ``ProofRule`` semantics used by
the trusted auditor.

Security / honesty invariants:
- An extension can only fill a currently-unmapped (capability, proof-kind) route;
  it cannot override or broaden an existing base rule.
- CODE/TEST paths remain explicit per capability group.  No wildcard paths.
- External proof routes list explicit capability IDs.  No future capability
  inherits a route automatically.
- Every generated external subject and reference prefix is capability-specific.
- This compiler creates policy rules only.  It never creates ProofLedger events,
  never raises a maturity score, and never turns CI into EXECUTION/LIVE/HARDWARE.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .capability_registry import CAPABILITY_BY_ID, ProofKind


_EXTENSION_SCHEMA_VERSION = 1
_DEFAULT_EXTENSION_PATH = "config/maturity_proof_route_extensions.json"
_MAX_EXTENSION_BYTES = 512 * 1024
_MAX_BINDING_GROUPS = 200
_MAX_EXTERNAL_GROUPS = 32
_MAX_CAPABILITIES_PER_GROUP = 142
_REGULAR_GIT_MODES = {"100644", "100755"}
_EXTERNAL_PROOFS = {
    ProofKind.EXECUTION,
    ProofKind.INDEPENDENT,
    ProofKind.PERSISTENCE,
    ProofKind.RUNTIME,
    ProofKind.LIVE,
    ProofKind.HARDWARE,
    ProofKind.SAFETY,
    ProofKind.REPRODUCIBILITY,
}


def _safe_repo_path(value: object, *, field: str) -> str:
    text = str(value or "")
    if not text or len(text) > 1_000 or "\\" in text or "\x00" in text:
        raise ValueError(f"{field} is not a safe repository path")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} is not a safe repository path")
    if path.as_posix() != text:
        raise ValueError(f"{field} must use canonical POSIX spelling")
    return text


def _read_tracked_extension(
    root: Path,
    tracked: Mapping[str, str],
    extension_path: str,
) -> bytes | None:
    canonical = _safe_repo_path(extension_path, field="route extension path")
    mode = tracked.get(canonical)
    if mode is None:
        return None
    if mode not in _REGULAR_GIT_MODES:
        raise ValueError("route extension must be a tracked regular file")
    candidate = root.joinpath(*PurePosixPath(canonical).parts)
    root_resolved = root.resolve(strict=True)
    try:
        info = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("route extension escapes or cannot be resolved") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("route extension must not be a symlink")
    if info.st_size < 1 or info.st_size > _MAX_EXTENSION_BYTES:
        raise ValueError("route extension size is invalid")
    data = candidate.read_bytes()
    if len(data) != info.st_size or len(data) > _MAX_EXTENSION_BYTES:
        raise ValueError("route extension changed during read")
    return data


def _ids(value: Any, *, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value or len(value) > _MAX_CAPABILITIES_PER_GROUP:
        raise ValueError(f"{field} must be a bounded non-empty list")
    result = []
    for item in value:
        if type(item) is not int or item not in CAPABILITY_BY_ID:
            raise ValueError(f"{field} contains an invalid capability id")
        result.append(item)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} contains duplicate capability ids")
    return tuple(result)


def _paths(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise ValueError(f"{field} must be a bounded non-empty list")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} entries must be strings")
        result.append(_safe_repo_path(item, field=field))
    if len(set(result)) != len(result):
        raise ValueError(f"{field} contains duplicate paths")
    return result


def _token(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 120
        or any(not (ch.isalnum() or ch in "_.@/+~-:") for ch in text)
    ):
        raise ValueError(f"{field} is invalid")
    return text


def merge_policy_route_extensions(
    *,
    root: Path,
    tracked: Mapping[str, str],
    base_policy_bytes: bytes,
    extension_path: str = _DEFAULT_EXTENSION_PATH,
) -> bytes:
    """Return canonical base+extension policy JSON bytes.

    If the optional extension file is absent, ``base_policy_bytes`` is returned
    unchanged for backwards compatibility.
    """
    extension_bytes = _read_tracked_extension(root, tracked, extension_path)
    if extension_bytes is None:
        return base_policy_bytes
    try:
        base = json.loads(base_policy_bytes.decode("utf-8"))
        extension = json.loads(extension_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("proof policy route extension is not valid UTF-8 JSON") from exc
    if not isinstance(base, dict) or not isinstance(base.get("rules"), list):
        raise ValueError("base proof policy schema is invalid")
    if not isinstance(extension, dict) or set(extension) != {
        "schema_version", "code_test_bindings", "external_routes"
    }:
        raise ValueError("proof policy route extension schema is invalid")
    if extension.get("schema_version") != _EXTENSION_SCHEMA_VERSION:
        raise ValueError("unsupported proof policy route extension schema_version")

    bindings = extension.get("code_test_bindings")
    external = extension.get("external_routes")
    if (
        not isinstance(bindings, list)
        or len(bindings) > _MAX_BINDING_GROUPS
        or not isinstance(external, list)
        or len(external) > _MAX_EXTERNAL_GROUPS
    ):
        raise ValueError("proof policy route extension groups are invalid")

    base_routes = set()
    for item in base["rules"]:
        if not isinstance(item, dict):
            raise ValueError("base proof policy rule is invalid")
        try:
            key = (int(item["capability_id"]), str(item["proof_kind"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("base proof policy rule is invalid") from exc
        base_routes.add(key)

    generated = []
    generated_routes = set()

    def reserve(capability_id: int, kind: ProofKind) -> None:
        key = (capability_id, kind.value)
        if key in base_routes:
            raise ValueError("route extension attempts to override a base policy route")
        if key in generated_routes:
            raise ValueError("route extension contains a duplicate generated route")
        if kind not in CAPABILITY_BY_ID[capability_id].required_proofs:
            raise ValueError("route extension names a proof not required by capability")
        generated_routes.add(key)

    for index, group in enumerate(bindings):
        if not isinstance(group, dict) or set(group) != {
            "capability_ids", "code_subjects", "test_subjects"
        }:
            raise ValueError(f"code/test binding group {index} schema is invalid")
        capability_ids = _ids(group["capability_ids"], field=f"binding {index} capability_ids")
        code_subjects = _paths(group["code_subjects"], field=f"binding {index} code_subjects")
        test_subjects = _paths(group["test_subjects"], field=f"binding {index} test_subjects")
        for capability_id in capability_ids:
            for kind, subjects in ((ProofKind.CODE, code_subjects), (ProofKind.TEST, test_subjects)):
                reserve(capability_id, kind)
                generated.append({
                    "capability_id": capability_id,
                    "proof_kind": kind.value,
                    "subjects": list(subjects),
                    "verifiers": ["github-actions"],
                    "reference_prefixes": [],
                })

    for index, group in enumerate(external):
        if not isinstance(group, dict) or set(group) != {
            "proof_kind", "capability_ids", "subject_suffix", "verifier", "reference_namespace"
        }:
            raise ValueError(f"external route group {index} schema is invalid")
        try:
            kind = ProofKind(group["proof_kind"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"external route group {index} proof_kind is invalid") from exc
        if kind not in _EXTERNAL_PROOFS:
            raise ValueError("external route group cannot define CODE/TEST/WIRING")
        capability_ids = _ids(group["capability_ids"], field=f"external {index} capability_ids")
        suffix = _token(group["subject_suffix"], field=f"external {index} subject_suffix")
        verifier = _token(group["verifier"], field=f"external {index} verifier")
        namespace = _token(group["reference_namespace"], field=f"external {index} namespace")
        for capability_id in capability_ids:
            reserve(capability_id, kind)
            generated.append({
                "capability_id": capability_id,
                "proof_kind": kind.value,
                "subjects": [f"capability-{capability_id}-{suffix}"],
                "verifiers": [verifier],
                "reference_prefixes": [f"{namespace}:c{capability_id}:"],
            })

    merged = {
        "schema_version": base.get("schema_version"),
        "rules": list(base["rules"]) + generated,
    }
    return json.dumps(
        merged,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
