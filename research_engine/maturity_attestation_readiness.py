"""Read-only 142-capability attestation-route readiness audit.

This module answers a deliberately narrower question than the maturity proof
ledger: *if a required proof were to be produced, is there a concrete tracked
route in this exact repository revision that knows how to accept/attest it?*

It never creates proof receipts, never changes a maturity score, and never calls
an attestor.  In particular, a generic ``trusted-*`` policy route is not treated
as a repo-backed specialized attestor merely because the route name sounds
credible.  Specialized readiness requires an explicit committed registry whose
module/test/optional CLI are tracked regular files and whose verifier/subject
match the committed proof policy exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from utils.release_identity import repository_identity

from .capability_registry import CAPABILITIES, CAPABILITY_BY_ID, ProofKind
from .maturity_auditor import (
    ProofRule,
    RepositoryProofPolicy,
    _hash_tracked_regular,
    _parse_policy,
    _read_policy_bytes,
    _safe_repo_path,
    _tracked_index,
)


_REGISTRY_SCHEMA_VERSION = 1
_DEFAULT_REGISTRY_PATH = "config/maturity_attestor_registry.json"
_MAX_REGISTRY_BYTES = 512 * 1024
_MAX_ATTESTORS = 128
_MAX_ROUTES_PER_ATTESTOR = 256
_REGULAR_GIT_MODES = {"100644", "100755"}
_ATTESTOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")

_TRACKED_CI = "TRACKED_CI"
_SPECIALIZED = "SPECIALIZED_ATTESTOR"
_SPECIALIZED_EXTERNAL = "SPECIALIZED_EXTERNAL_ATTESTOR"
_ROUTE_MISSING = "ROUTE_MISSING"
_GENERIC_EXTERNAL = "GENERIC_EXTERNAL_ROUTE"
_RUNTIME_EXTERNAL = "RUNTIME_EXTERNAL_REQUIRED"
_LIVE_EXTERNAL = "LIVE_EXTERNAL_REQUIRED"
_HARDWARE_EXTERNAL = "HARDWARE_REQUIRED"
_SAFETY_EXTERNAL = "SAFETY_EXTERNAL_REQUIRED"
_ROUTE_NOT_CI_TRACKED = "ROUTE_MAPPED_NOT_CI_TRACKED"


@dataclass(frozen=True)
class AttestorBinding:
    attestor_id: str
    verifier: str
    module: str
    test: str
    cli: str
    external_required: bool
    capability_id: int
    proof_kind: ProofKind
    subject: str


@dataclass(frozen=True)
class RouteReadiness:
    capability_id: int
    capability_name: str
    proof_kind: ProofKind
    verifiers: Tuple[str, ...]
    subjects: Tuple[str, ...]
    status: str
    attestor_id: str
    external_required: bool
    blockers: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "capability_name": self.capability_name,
            "proof_kind": self.proof_kind.value,
            "verifiers": list(self.verifiers),
            "subjects": list(self.subjects),
            "status": self.status,
            "attestor_id": self.attestor_id,
            "external_required": self.external_required,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class CapabilityReadiness:
    capability_id: int
    name: str
    routes: Tuple[RouteReadiness, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "routes": [route.to_dict() for route in self.routes],
        }


@dataclass(frozen=True)
class AttestationReadinessReport:
    revision: str
    total_capabilities: int
    total_required_routes: int
    status_counts: Mapping[str, int]
    capabilities: Tuple[CapabilityReadiness, ...]
    report_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "revision": self.revision,
            "total_capabilities": self.total_capabilities,
            "total_required_routes": self.total_required_routes,
            "status_counts": dict(sorted(self.status_counts.items())),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "report_hash": self.report_hash,
            "note": (
                "Attestation readiness is route/tooling metadata only. It is not "
                "proof evidence, maturity verification, scientific truth, safety, "
                "live operation, hardware validation, or real-world effectiveness."
            ),
        }


@dataclass(frozen=True)
class AttestorRegistry:
    bindings: Tuple[AttestorBinding, ...]
    sha256: str

    @property
    def by_route(self) -> Mapping[Tuple[int, ProofKind], AttestorBinding]:
        return {
            (binding.capability_id, binding.proof_kind): binding
            for binding in self.bindings
        }


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_token(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field} is invalid")
    return text


def _read_tracked_regular(
    root: Path,
    tracked: Mapping[str, str],
    path: str,
    *,
    field: str,
    max_bytes: int,
) -> bytes:
    canonical = _safe_repo_path(path, field=field)
    mode = tracked.get(canonical)
    if mode not in _REGULAR_GIT_MODES:
        raise ValueError(f"{field} must be a tracked regular file")
    candidate = root.joinpath(*PurePosixPath(canonical).parts)
    root_resolved = root.resolve(strict=True)
    try:
        info = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"{field} escapes or cannot be resolved") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{field} must not be a symlink")
    if info.st_size < 1 or info.st_size > max_bytes:
        raise ValueError(f"{field} size is invalid")
    data = candidate.read_bytes()
    if len(data) != info.st_size or len(data) > max_bytes:
        raise ValueError(f"{field} changed during read")
    return data


def _policy_routes(policy: RepositoryProofPolicy) -> Mapping[Tuple[int, ProofKind], ProofRule]:
    routes: Dict[Tuple[int, ProofKind], ProofRule] = {}
    for rule in policy.rules:
        key = (rule.capability_id, rule.proof_kind)
        if key in routes:
            raise ValueError("proof policy contains duplicate capability/proof routes")
        routes[key] = rule
    return routes


def _validate_attestor_path(
    root: Path,
    tracked: Mapping[str, str],
    path: object,
    *,
    field: str,
    prefix: str,
) -> str:
    canonical = _safe_repo_path(path, field=field)
    if not canonical.startswith(prefix) or not canonical.endswith(".py"):
        raise ValueError(f"{field} is outside the allowed repository namespace")
    _hash_tracked_regular(root, tracked, canonical)
    return canonical


def _parse_attestor_registry(
    data: bytes,
    *,
    root: Path,
    tracked: Mapping[str, str],
    policy: RepositoryProofPolicy,
) -> AttestorRegistry:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("attestor registry is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "attestors"}:
        raise ValueError("attestor registry top-level schema is invalid")
    if raw.get("schema_version") != _REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported attestor registry schema_version")
    entries = raw.get("attestors")
    if not isinstance(entries, list) or not entries or len(entries) > _MAX_ATTESTORS:
        raise ValueError("attestor registry entries must be a bounded non-empty list")

    policy_by_route = _policy_routes(policy)
    bindings = []
    attestor_ids = set()
    bound_routes = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"attestor registry entry {index} must be an object")
        keys = set(entry)
        required_keys = {
            "attestor_id", "verifier", "module", "test",
            "external_required", "routes",
        }
        if not required_keys.issubset(keys) or keys - (required_keys | {"cli"}):
            raise ValueError(f"attestor registry entry {index} schema is invalid")

        attestor_id = str(entry.get("attestor_id") or "")
        if not _ATTESTOR_ID_RE.fullmatch(attestor_id) or attestor_id in attestor_ids:
            raise ValueError(f"attestor registry entry {index} attestor_id is invalid or duplicate")
        attestor_ids.add(attestor_id)
        verifier = _safe_token(entry.get("verifier"), field=f"attestor {attestor_id} verifier")
        external_required = entry.get("external_required")
        if type(external_required) is not bool:
            raise ValueError(f"attestor {attestor_id} external_required must be boolean")
        module = _validate_attestor_path(
            root, tracked, entry.get("module"), field=f"attestor {attestor_id} module",
            prefix="research_engine/",
        )
        test = _validate_attestor_path(
            root, tracked, entry.get("test"), field=f"attestor {attestor_id} test",
            prefix="tests/test_",
        )
        cli = ""
        if "cli" in entry:
            cli = _validate_attestor_path(
                root, tracked, entry.get("cli"), field=f"attestor {attestor_id} cli",
                prefix="scripts/",
            )

        routes = entry.get("routes")
        if (
            not isinstance(routes, list)
            or not routes
            or len(routes) > _MAX_ROUTES_PER_ATTESTOR
        ):
            raise ValueError(f"attestor {attestor_id} routes must be bounded and non-empty")
        for route_index, route in enumerate(routes):
            if not isinstance(route, dict) or not set(route).issubset(
                {"capability_id", "proof_kind", "subject"}
            ) or not {"capability_id", "proof_kind"}.issubset(route):
                raise ValueError(f"attestor {attestor_id} route {route_index} schema is invalid")
            capability_id = route.get("capability_id")
            if type(capability_id) is not int or capability_id not in CAPABILITY_BY_ID:
                raise ValueError(f"attestor {attestor_id} route capability_id is invalid")
            try:
                proof_kind = ProofKind(route.get("proof_kind"))
            except ValueError as exc:
                raise ValueError(f"attestor {attestor_id} route proof_kind is invalid") from exc
            if proof_kind in {ProofKind.CODE, ProofKind.TEST}:
                raise ValueError("CODE/TEST belong to tracked CI, not specialized attestor registry")
            if proof_kind not in CAPABILITY_BY_ID[capability_id].required_proofs:
                raise ValueError("attestor registry route names a proof not required by capability")

            key = (capability_id, proof_kind)
            if key in bound_routes:
                raise ValueError("attestor registry contains a duplicate capability/proof binding")
            rule = policy_by_route.get(key)
            if rule is None:
                raise ValueError("attestor registry route is absent from committed proof policy")
            if verifier not in rule.verifiers:
                raise ValueError("attestor verifier is not allowed by committed proof policy")

            subject = ""
            if "subject" in route:
                subject = _safe_token(
                    route.get("subject"),
                    field=f"attestor {attestor_id} route subject",
                )
                if subject not in rule.subjects:
                    raise ValueError("attestor subject is not allowed by committed proof policy")
            elif proof_kind is not ProofKind.WIRING:
                raise ValueError("non-wiring specialized attestor routes require an exact subject")

            bound_routes.add(key)
            bindings.append(AttestorBinding(
                attestor_id=attestor_id,
                verifier=verifier,
                module=module,
                test=test,
                cli=cli,
                external_required=external_required,
                capability_id=capability_id,
                proof_kind=proof_kind,
                subject=subject,
            ))

    bindings.sort(key=lambda item: (
        item.capability_id,
        item.proof_kind.value,
        item.attestor_id,
    ))
    return AttestorRegistry(bindings=tuple(bindings), sha256=_sha(data))


def _generic_status(kind: ProofKind) -> Tuple[str, bool, str]:
    if kind is ProofKind.RUNTIME:
        return (
            _RUNTIME_EXTERNAL,
            True,
            "acceptance route exists but no repo-backed specialized runtime attestor is registered",
        )
    if kind is ProofKind.LIVE:
        return (
            _LIVE_EXTERNAL,
            True,
            "live evidence still requires a real external observation path",
        )
    if kind is ProofKind.HARDWARE:
        return (
            _HARDWARE_EXTERNAL,
            True,
            "hardware evidence still requires a real physical observation path",
        )
    if kind is ProofKind.SAFETY:
        return (
            _SAFETY_EXTERNAL,
            True,
            "safety acceptance route exists but no repo-backed specialized safety attestor is registered",
        )
    return (
        _GENERIC_EXTERNAL,
        True,
        "acceptance route exists but no repo-backed specialized attestor is registered",
    )


def _route_readiness(
    *,
    root: Path,
    tracked: Mapping[str, str],
    policy_by_route: Mapping[Tuple[int, ProofKind], ProofRule],
    registry_by_route: Mapping[Tuple[int, ProofKind], AttestorBinding],
    capability_id: int,
    capability_name: str,
    proof_kind: ProofKind,
) -> RouteReadiness:
    key = (capability_id, proof_kind)
    rule = policy_by_route.get(key)
    if rule is None:
        return RouteReadiness(
            capability_id=capability_id,
            capability_name=capability_name,
            proof_kind=proof_kind,
            verifiers=(),
            subjects=(),
            status=_ROUTE_MISSING,
            attestor_id="",
            external_required=True,
            blockers=("no committed acceptance route exists for this required proof",),
        )

    if proof_kind in {ProofKind.CODE, ProofKind.TEST}:
        ci_ready = "github-actions" in rule.verifiers
        file_error = ""
        for subject in rule.subjects:
            try:
                _hash_tracked_regular(root, tracked, subject)
            except ValueError as exc:
                file_error = str(exc)
                break
        if ci_ready and not file_error:
            return RouteReadiness(
                capability_id=capability_id,
                capability_name=capability_name,
                proof_kind=proof_kind,
                verifiers=rule.verifiers,
                subjects=rule.subjects,
                status=_TRACKED_CI,
                attestor_id="foundation-code-test",
                external_required=False,
                blockers=(),
            )
        blockers = []
        if not ci_ready:
            blockers.append("CODE/TEST route is not bound to github-actions")
        if file_error:
            blockers.append(file_error)
        return RouteReadiness(
            capability_id=capability_id,
            capability_name=capability_name,
            proof_kind=proof_kind,
            verifiers=rule.verifiers,
            subjects=rule.subjects,
            status=_ROUTE_NOT_CI_TRACKED,
            attestor_id="",
            external_required=True,
            blockers=tuple(blockers),
        )

    binding = registry_by_route.get(key)
    if binding is not None:
        status = _SPECIALIZED_EXTERNAL if binding.external_required else _SPECIALIZED
        blocker = (
            "repo-backed attestor exists; real external observation/operator context is still required before evidence can be issued",
        ) if binding.external_required else ()
        return RouteReadiness(
            capability_id=capability_id,
            capability_name=capability_name,
            proof_kind=proof_kind,
            verifiers=rule.verifiers,
            subjects=rule.subjects,
            status=status,
            attestor_id=binding.attestor_id,
            external_required=binding.external_required,
            blockers=blocker,
        )

    status, external, blocker = _generic_status(proof_kind)
    return RouteReadiness(
        capability_id=capability_id,
        capability_name=capability_name,
        proof_kind=proof_kind,
        verifiers=rule.verifiers,
        subjects=rule.subjects,
        status=status,
        attestor_id="",
        external_required=external,
        blockers=(blocker,),
    )


def audit_attestation_readiness(
    repo_root: str | Path,
    *,
    policy_path: str = "config/maturity_proof_policy.json",
    registry_path: str = _DEFAULT_REGISTRY_PATH,
) -> AttestationReadinessReport:
    """Build a deterministic, read-only attestation-route readiness map."""
    root = Path(repo_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    identity = repository_identity(root)
    revision = str(identity.get("revision") or "").strip().lower()
    if not identity.get("available") or not identity.get("clean") or len(revision) != 40:
        raise ValueError("attestation readiness requires a clean Git checkout")

    tracked = _tracked_index(root)
    policy = _parse_policy(_read_policy_bytes(root, tracked, policy_path))
    registry_bytes = _read_tracked_regular(
        root,
        tracked,
        registry_path,
        field="attestor registry",
        max_bytes=_MAX_REGISTRY_BYTES,
    )
    registry = _parse_attestor_registry(
        registry_bytes,
        root=root,
        tracked=tracked,
        policy=policy,
    )
    policy_by_route = _policy_routes(policy)
    registry_by_route = registry.by_route

    capabilities = []
    counts: Dict[str, int] = {}
    total_routes = 0
    for capability in CAPABILITIES:
        routes = []
        for proof_kind in capability.required_proofs:
            total_routes += 1
            route = _route_readiness(
                root=root,
                tracked=tracked,
                policy_by_route=policy_by_route,
                registry_by_route=registry_by_route,
                capability_id=capability.id,
                capability_name=capability.name,
                proof_kind=proof_kind,
            )
            routes.append(route)
            counts[route.status] = counts.get(route.status, 0) + 1
        capabilities.append(CapabilityReadiness(
            capability_id=capability.id,
            name=capability.name,
            routes=tuple(routes),
        ))

    payload = {
        "revision": revision,
        "total_capabilities": len(capabilities),
        "total_required_routes": total_routes,
        "status_counts": dict(sorted(counts.items())),
        "capabilities": [item.to_dict() for item in capabilities],
        "registry_sha256": registry.sha256,
        "policy_sha256": policy.sha256,
    }
    return AttestationReadinessReport(
        revision=revision,
        total_capabilities=len(capabilities),
        total_required_routes=total_routes,
        status_counts=dict(sorted(counts.items())),
        capabilities=tuple(capabilities),
        report_hash=_sha(_canonical(payload)),
    )
