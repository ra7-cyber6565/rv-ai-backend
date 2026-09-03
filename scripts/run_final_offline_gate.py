"""Final offline proof gate for Infinity Research AI.

This gate answers one narrow question only:

    "Does the current checked-out code pass the strongest proof we can run
     without network access, hosted models, paid services, deployment access,
     or operator-held attestation secrets?"

It deliberately does NOT claim production readiness. A PASS here means the
foundation gate and the independent source-boundary wiring audit passed under a
forced zero-cost/offline environment. Live free-provider availability, deployed
production acceptance, and operator maturity attestation remain separate gates.

No credential values are written to this gate's receipt or child-stage metadata.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE_TIMEOUT_SECONDS = 30 * 60
SCOPE = "offline_code_and_fixture_proof_only"
DOES_NOT_PROVE = [
    "live provider availability",
    "deployed production acceptance",
    "operator maturity attestation",
]

# Explicitly blank known credential-bearing variables. We never copy values into
# the receipt, output structure, command line, or exception strings.
_SECRET_ENV_NAMES = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_1",
    "GEMINI_API_KEY_2",
    "GEMINI_API_KEY_3",
    "GEMINI_API_KEY_4",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "TERABOX_ACCESS_TOKEN",
    "TERABOX_CLIENT_ID",
    "TERABOX_CLIENT_SECRET",
    "TERABOX_PRIVATE_SECRET",
    "INFINITY_ADMIN_TOKEN",
    "INFINITY_OPERATOR_ATTESTATION_KEY",
    "INFINITY_MATURITY_ATTESTATION_KEY",
)


@dataclass(frozen=True)
class StageResult:
    name: str
    command_kind: str
    returncode: int
    duration_seconds: float
    timed_out: bool
    passed: bool


@dataclass(frozen=True)
class FinalOfflineReceipt:
    schema_version: int
    created_at_epoch: int
    scope: str
    offline_zero_cost: bool
    passed: bool
    release_ready: bool
    production_ready: bool
    does_not_prove: list[str]
    foundation_receipt_validated: bool
    failed_stages: list[str]
    stages: list[dict]


def safe_offline_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a fail-closed environment for proof execution.

    The child foundation gate also enforces its own offline environment. Doing it
    again here is intentional defence in depth: even a future child-gate refactor
    cannot silently turn this wrapper into a live/provider test.
    """
    env = dict(os.environ if base is None else base)
    for name in _SECRET_ENV_NAMES:
        env[name] = ""

    env.update({
        "ZERO_COST_ONLY": "true",
        "GEMINI_ZERO_COST_CONFIRMED": "false",
        "GROQ_ZERO_COST_CONFIRMED": "false",
        "OPENROUTER_ZERO_COST_CONFIRMED": "false",
        "OLLAMA_ENABLED": "false",
        "CLOUD_ARCHIVE_PROVIDER": "none",
        "ALLOW_FULLTEXT_FETCH": "false",
        "ALLOW_YT_TRANSCRIPT": "false",
        "ALLOW_NETWORK_RESEARCH": "false",
        "INFINITY_OFFLINE_PROOF": "true",
        # Keep Python output deterministic/easy to inspect in a terminal.
        "PYTHONUNBUFFERED": "1",
    })
    return env


def build_stage_plan(
    python: str,
    *,
    foundation_receipt: Path,
    quick: bool = False,
) -> list[tuple[str, list[str]]]:
    """Return only offline stages. Never add live/deployed/attestation scripts."""
    foundation = [
        python,
        "scripts/run_foundation_gate.py",
        "--receipt",
        str(foundation_receipt),
    ]
    if quick:
        foundation.append("--quick")
    return [
        ("foundation_offline_gate", foundation),
        ("source_boundary_audit", [python, "scripts/audit_source_boundary.py"]),
    ]


def _run_stage(
    name: str,
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> StageResult:
    started = time.monotonic()
    print("\n" + "-" * 72)
    print(f"FINAL OFFLINE STAGE: {name}")
    print("-" * 72)
    timed_out = False
    returncode = 1
    try:
        completed = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            env=dict(env),
            timeout=max(30, int(timeout_seconds)),
            check=False,
        )
        returncode = int(completed.returncode)
    except subprocess.TimeoutExpired:
        timed_out = True
        returncode = 124
        print(f"[FAIL] {name}: timeout after {timeout_seconds}s")
    except Exception as exc:  # never expose potentially sensitive child details
        returncode = 125
        print(f"[FAIL] {name}: runner error ({type(exc).__name__})")

    duration = round(time.monotonic() - started, 3)
    passed = returncode == 0 and not timed_out
    print(f"[{'PASS' if passed else 'FAIL'}] {name} ({duration:.3f}s)")
    return StageResult(
        name=name,
        command_kind="offline_subprocess",
        returncode=returncode,
        duration_seconds=duration,
        timed_out=timed_out,
        passed=passed,
    )


def validate_foundation_receipt(path: Path) -> bool:
    """Require the child gate's own fail-closed receipt, not only exit code."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(
        isinstance(data, dict)
        and data.get("passed") is True
        and data.get("offline_zero_cost") is True
        and data.get("code_identity_verified") is True
        and data.get("repository_clean") is True
        and str(data.get("code_revision") or "").strip()
    )


def make_receipt(
    stages: Sequence[StageResult],
    *,
    foundation_receipt_validated: bool,
) -> FinalOfflineReceipt:
    failed = [stage.name for stage in stages if not stage.passed]
    if not foundation_receipt_validated:
        failed.append("foundation_receipt_validation")
    passed = not failed
    return FinalOfflineReceipt(
        schema_version=1,
        created_at_epoch=int(time.time()),
        scope=SCOPE,
        offline_zero_cost=True,
        passed=passed,
        # These remain false by design even when every offline stage passes.
        release_ready=False,
        production_ready=False,
        does_not_prove=list(DOES_NOT_PROVE),
        foundation_receipt_validated=foundation_receipt_validated,
        failed_stages=failed,
        stages=[asdict(stage) for stage in stages],
    )


def _default_audit_root(env: Mapping[str, str]) -> Path:
    configured = str(env.get("INFINITY_DATA_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve() / "audit"
    # Do not create proof artifacts inside the git checkout: that could dirty the
    # repository and invalidate the foundation identity gate mid-run.
    return Path(tempfile.gettempdir()).resolve() / "InfinityResearchAI" / "audit"


def _atomic_json(path: Path, receipt: FinalOfflineReceipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(asdict(receipt), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the strongest offline/zero-cost proof without claiming production readiness."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_STAGE_TIMEOUT_SECONDS,
        help=f"Per-stage timeout (default: {DEFAULT_STAGE_TIMEOUT_SECONDS}).",
    )
    parser.add_argument("--receipt", help="Optional final JSON receipt path.")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Ask the nested foundation gate for its quick offline plan.",
    )
    args = parser.parse_args(argv)

    env = safe_offline_env()
    audit_root = _default_audit_root(env)
    final_receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt
        else audit_root / "final_offline_gate.json"
    )
    foundation_receipt = audit_root / "foundation_for_final_offline_gate.json"

    stages: list[StageResult] = []
    for name, command in build_stage_plan(
        sys.executable,
        foundation_receipt=foundation_receipt,
        quick=bool(args.quick),
    ):
        stages.append(
            _run_stage(
                name,
                command,
                env=env,
                timeout_seconds=max(30, int(args.timeout_seconds)),
            )
        )

    foundation_ok = validate_foundation_receipt(foundation_receipt)
    receipt = make_receipt(stages, foundation_receipt_validated=foundation_ok)
    _atomic_json(final_receipt_path, receipt)

    print("\n" + "=" * 72)
    print("FINAL OFFLINE GATE: " + ("PASS" if receipt.passed else "FAIL"))
    if receipt.failed_stages:
        print("Failed requirements:")
        for item in receipt.failed_stages:
            print(f"  - {item}")
    print(f"Receipt: {final_receipt_path}")
    print("Scope: offline code + deterministic fixture proof only.")
    print("Release ready: NO (live acceptance is a separate gate).")
    print("Production ready: NO (deployed acceptance is a separate gate).")
    print("This gate does NOT prove:")
    for item in DOES_NOT_PROVE:
        print(f"  - {item}")
    print("=" * 72)
    return 0 if receipt.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
