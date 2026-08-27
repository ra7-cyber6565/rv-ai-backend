"""Deterministic, self-verifying research capsule packaging.

A research result is reproducible only if the inputs, code, environment and
outputs can be tied to exact bytes.  This module packages those artifacts into a
stable ZIP with a canonical manifest and SHA-256 hashes, then independently
verifies every declared member on read.

The capsule intentionally rejects obvious secret-bearing filenames and unsafe
paths.  It is an audit/reproducibility primitive, not a substitute for data
licenses or access controls.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


_ALLOWED_KINDS = {
    "source", "data", "code", "experiment", "graph", "claim", "hypothesis",
    "result", "environment", "report",
}
_SECRET_NAME = re.compile(
    r"(^|[._-])(\.env|api[_-]?key|client[_-]?secret|private[_-]?key|credentials?|token)([._-]|$)",
    re.IGNORECASE,
)
_MANIFEST_NAME = "manifest.json"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_SCHEMA_VERSION = 1


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative_path(value: str) -> str:
    path = str(value or "").replace("\\", "/").strip("/")
    if not path or path.startswith("."):
        raise ValueError("artifact path must be a non-hidden relative path")
    pieces = path.split("/")
    if any(piece in {"", ".", ".."} for piece in pieces):
        raise ValueError("artifact path contains unsafe traversal")
    if any("\x00" in piece for piece in pieces):
        raise ValueError("artifact path contains NUL")
    if path == _MANIFEST_NAME:
        raise ValueError("manifest.json is reserved")
    if _SECRET_NAME.search(path):
        raise ValueError("secret-like artifact filenames are not allowed in research capsules")
    return path


@dataclass(frozen=True)
class CapsuleArtifact:
    kind: str
    path: str
    data: bytes
    media_type: str = "application/octet-stream"
    provenance: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CapsuleBuild:
    capsule_id: str
    capsule_sha256: str
    bytes_data: bytes
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class CapsuleVerification:
    valid: bool
    capsule_id: Optional[str]
    errors: Tuple[str, ...]
    artifact_count: int


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def build_capsule(
    artifacts: Sequence[CapsuleArtifact],
    *,
    environment: Mapping[str, Any],
    metadata: Optional[Mapping[str, Any]] = None,
) -> CapsuleBuild:
    if not artifacts:
        raise ValueError("at least one artifact is required")

    prepared: Dict[str, Tuple[CapsuleArtifact, bytes]] = {}
    manifest_rows = []
    for artifact in artifacts:
        kind = str(artifact.kind).strip().lower()
        if kind not in _ALLOWED_KINDS:
            raise ValueError(f"unsupported artifact kind: {artifact.kind}")
        path = _safe_relative_path(artifact.path)
        if path in prepared:
            raise ValueError(f"duplicate artifact path: {path}")
        if not isinstance(artifact.data, (bytes, bytearray)):
            raise ValueError(f"artifact {path} data must be bytes")
        data = bytes(artifact.data)
        prepared[path] = (artifact, data)
        manifest_rows.append({
            "kind": kind,
            "path": path,
            "sha256": _sha(data),
            "bytes": len(data),
            "media_type": str(artifact.media_type or "application/octet-stream"),
            "provenance": sorted({str(item).strip() for item in artifact.provenance if str(item).strip()}),
        })

    manifest_rows.sort(key=lambda row: row["path"])
    manifest_without_id = {
        "schema_version": _SCHEMA_VERSION,
        "environment": dict(environment),
        "metadata": dict(metadata or {}),
        "artifacts": manifest_rows,
    }
    capsule_id = _sha(_canonical(manifest_without_id))
    manifest = {**manifest_without_id, "capsule_id": capsule_id}
    manifest_bytes = _canonical(manifest)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_zip_info(_MANIFEST_NAME), manifest_bytes)
        for path in sorted(prepared):
            archive.writestr(_zip_info(path), prepared[path][1])
    capsule_bytes = output.getvalue()
    return CapsuleBuild(capsule_id, _sha(capsule_bytes), capsule_bytes, manifest)


def write_capsule(path: str, capsule: CapsuleBuild) -> str:
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".capsule_", suffix=".zip", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(capsule.bytes_data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return target


def verify_capsule_bytes(payload: bytes) -> CapsuleVerification:
    errors = []
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        return CapsuleVerification(False, None, ("capsule payload is empty or invalid",), 0)
    try:
        archive = zipfile.ZipFile(io.BytesIO(bytes(payload)), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        return CapsuleVerification(False, None, (f"invalid zip: {exc}",), 0)

    with archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("archive contains duplicate member names")
        if _MANIFEST_NAME not in names:
            return CapsuleVerification(False, None, tuple(errors + ["manifest.json missing"]), 0)
        unsafe = []
        for name in names:
            if name == _MANIFEST_NAME:
                continue
            try:
                _safe_relative_path(name)
            except ValueError:
                unsafe.append(name)
        if unsafe:
            errors.append(f"unsafe member path(s): {', '.join(sorted(unsafe))}")
        try:
            manifest = json.loads(archive.read(_MANIFEST_NAME).decode("utf-8"))
        except Exception as exc:
            return CapsuleVerification(False, None, tuple(errors + [f"manifest unreadable: {exc}"]), 0)
        if not isinstance(manifest, dict) or manifest.get("schema_version") != _SCHEMA_VERSION:
            errors.append("unsupported or invalid manifest schema")
        rows = manifest.get("artifacts")
        if not isinstance(rows, list):
            return CapsuleVerification(False, manifest.get("capsule_id") if isinstance(manifest, dict) else None, tuple(errors + ["manifest artifacts invalid"]), 0)

        declared = []
        for row in rows:
            if not isinstance(row, dict):
                errors.append("artifact declaration is not an object")
                continue
            path = row.get("path")
            try:
                path = _safe_relative_path(path)
            except ValueError as exc:
                errors.append(f"invalid declared path {path!r}: {exc}")
                continue
            declared.append(path)
            if path not in names:
                errors.append(f"declared artifact missing: {path}")
                continue
            data = archive.read(path)
            if row.get("sha256") != _sha(data):
                errors.append(f"hash mismatch: {path}")
            if row.get("bytes") != len(data):
                errors.append(f"size mismatch: {path}")
        if len(declared) != len(set(declared)):
            errors.append("manifest declares duplicate artifact paths")
        undeclared = sorted(set(names) - {_MANIFEST_NAME} - set(declared))
        if undeclared:
            errors.append(f"undeclared archive member(s): {', '.join(undeclared)}")

        manifest_without_id = dict(manifest)
        claimed_id = manifest_without_id.pop("capsule_id", None)
        expected_id = _sha(_canonical(manifest_without_id))
        if claimed_id != expected_id:
            errors.append("capsule_id does not match canonical manifest")
        return CapsuleVerification(not errors, claimed_id, tuple(errors), len(rows))


def verify_capsule_file(path: str) -> CapsuleVerification:
    with open(path, "rb") as handle:
        return verify_capsule_bytes(handle.read())
