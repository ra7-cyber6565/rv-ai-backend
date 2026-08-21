"""Run the Infinity Research AI foundation release gate locally/offline.

Why this exists
---------------
GitHub Actions is currently not exposing a run/status for the integration PR.
That must never become an excuse to call the foundation "green" without an
actual execution. This script gives Windows/Linux/macOS the same deterministic,
zero-cost gate from one command and writes a machine-readable receipt outside
Git by default.

The default mode is deliberately strict:
- forces every cloud reasoning provider and cloud archive off for the offline gate;
- runs compile checks;
- runs targeted infrastructure/integration pytest gates;
- runs the legacy/core regression;
- executes every standalone ``tests/test_*.py`` file;
- runs a production-wiring/static architecture audit;
- executes the offline superconductivity Benchmark V2;
- continues after failures so the final receipt shows *all* broken stages;
- exits non-zero if any stage failed/timed out/could not start.

No paid API/service is used by this runner, and configured user API keys are
explicitly blanked so a developer machine cannot accidentally spend quota while
testing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT_SECONDS = 15 * 60

# These files are the focused integration gates maintained by ChatGPT. Claude's
# own standalone tests are still executed later through the all-test-files pass.
FOCUSED_PYTEST = (
    "tests/test_upload_safety.py",
    "tests/test_work_root.py",
    "tests/test_storage_paths.py",
    "tests/test_storage_quota.py",
    "tests/test_archive_manifest.py",
    "tests/test_archive_manifest_concurrency.py",
    "tests/test_archive_retry.py",
    "tests/test_cloud_storage.py",
    "tests/test_cloud_archive.py",
    "tests/test_process_lock.py",
    "tests/test_google_drive_rclone.py",
    "tests/test_provider_factory.py",
    "tests/test_zero_cost_guard.py",
    "tests/test_reasoning_zero_cost.py",
    "tests/test_reasoning_router.py",
    "tests/test_reasoning_router_integration.py",
    "tests/test_offline_reasoner.py",
    "tests/test_reasoning_status.py",
    "tests/test_architecture_audit.py",
    "tests/test_release_state.py",
    "tests/test_security_config.py",
    "tests/test_request_guard.py",
    "tests/test_research_jobs.py",
    "tests/test_domain_guardrails.py",
    "tests/test_domain_ambiguity.py",
    "tests/test_pdf_sparse_sampling.py",
    "tests/test_evidence_verification.py",
    "tests/test_claim_label_ae_gate.py",
    "tests/test_verification_fail_closed.py",
    "tests/test_user_presentation_contract.py",
    "tests/test_presentation_guard.py",
    "tests/test_integrated_facades.py",
    "tests/test_claim_label_accounting.py",
)


@dataclass
class StageResult:
    name: str
    command: list[str]
    returncode: int | None
    duration_seconds: float
    status: str
    output_tail: list[str]


@dataclass
class GateReceipt:
    schema_version: int
    created_at_epoch: int
    python: str
    repo_root: str
    offline_zero_cost: bool
    passed: bool
    failed_stages: list[str]
    stages: list[dict]


def _tail(text: str, lines: int = 80) -> list[str]:
    rows = [row.rstrip() for row in (text or "").splitlines()]
    return rows[-max(1, int(lines)) :]


def _safe_env() -> dict[str, str]:
    """Return an explicitly offline/₹0 environment for the release gate."""
    env = dict(os.environ)
    env.update(
        {
            "ZERO_COST_ONLY": "true",
            "RATE_LIMIT_ENABLED": "true",
            # Every cloud reasoning key is blanked even if the developer has a
            # real key in their shell. Tests inject fakes explicitly when they
            # need to exercise fallback behaviour.
            "GEMINI_API_KEY": "",
            "GEMINI_ZERO_COST_CONFIRMED": "false",
            "GROQ_API_KEY": "",
            "GROQ_ZERO_COST_CONFIRMED": "false",
            "OPENROUTER_API_KEY": "",
            "OPENROUTER_MODEL": "openrouter/free",
            "OLLAMA_ENABLED": "false",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "REASONING_FALLBACK_CHAIN": "groq,openrouter,ollama",
            "CLOUD_ARCHIVE_PROVIDER": "none",
            "GOOGLE_DRIVE_RCLONE_REMOTE": "",
            "TERABOX_CLIENT_ID": "",
            "TERABOX_CLIENT_SECRET": "",
            "TERABOX_PRIVATE_SECRET": "",
            # Common project convention. Production code does not rely on this
            # alone; tests may use it as an additional no-network hint.
            "INFINITY_OFFLINE_TEST": "true",
        }
    )
    if not env.get("INFINITY_DATA_ROOT"):
        env["INFINITY_DATA_ROOT"] = str(REPO_ROOT / "runtime_data" / "gate")
    return env


def _run_stage(
    name: str,
    command: Sequence[str],
    *,
    env: dict[str, str],
    timeout_seconds: int,
) -> StageResult:
    print(f"\n=== {name} ===", flush=True)
    print("$ " + " ".join(command), flush=True)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        output = proc.stdout or ""
        if output:
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
        status = "passed" if proc.returncode == 0 else "failed"
        return StageResult(
            name=name,
            command=list(command),
            returncode=proc.returncode,
            duration_seconds=round(time.monotonic() - started, 3),
            status=status,
            output_tail=_tail(output),
        )
    except subprocess.TimeoutExpired as exc:
        output = ""
        if exc.stdout:
            output += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace")
        if exc.stderr:
            output += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", "replace")
        if output:
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
        print(f"[TIMEOUT] {name} exceeded {timeout_seconds}s", flush=True)
        return StageResult(
            name=name,
            command=list(command),
            returncode=None,
            duration_seconds=round(time.monotonic() - started, 3),
            status="timeout",
            output_tail=_tail(output),
        )
    except OSError as exc:
        print(f"[START ERROR] {type(exc).__name__}: {exc}", flush=True)
        return StageResult(
            name=name,
            command=list(command),
            returncode=None,
            duration_seconds=round(time.monotonic() - started, 3),
            status="start_error",
            output_tail=[f"{type(exc).__name__}: {exc}"],
        )


def _existing(paths: Iterable[str]) -> list[str]:
    return [path for path in paths if (REPO_ROOT / path).is_file()]


def _receipt_path(value: str | None, env: dict[str, str]) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    root = Path(env["INFINITY_DATA_ROOT"]).expanduser().resolve()
    return root / "audit" / "foundation_gate_latest.json"


def _write_receipt(path: Path, stages: list[StageResult]) -> GateReceipt:
    failed = [stage.name for stage in stages if stage.status != "passed"]
    receipt = GateReceipt(
        schema_version=1,
        created_at_epoch=int(time.time()),
        python=sys.version.split()[0],
        repo_root=str(REPO_ROOT),
        offline_zero_cost=True,
        passed=not failed,
        failed_stages=failed,
        stages=[asdict(stage) for stage in stages],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(receipt), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return receipt


def build_stage_plan(python: str) -> list[tuple[str, list[str]]]:
    """Pure helper kept testable: return the deterministic default gate plan."""
    plan: list[tuple[str, list[str]]] = [
        ("compileall", [python, "-m", "compileall", "-q", "."]),
    ]

    focused = _existing(FOCUSED_PYTEST)
    if focused:
        plan.append(("focused_pytest", [python, "-m", "pytest", "-q", *focused]))

    if (REPO_ROOT / "test_research_engine.py").is_file():
        plan.append(("core_regression", [python, "test_research_engine.py"]))

    # Run each standalone test directly because several project tests use their
    # own main()/exit-code harness rather than pytest collection semantics.
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        plan.append((f"standalone:{rel}", [python, rel]))

    architecture = REPO_ROOT / "scripts" / "audit_architecture.py"
    if architecture.is_file():
        plan.append((
            "architecture_audit",
            [python, architecture.relative_to(REPO_ROOT).as_posix()],
        ))

    benchmark = REPO_ROOT / "tests" / "benchmark_superconductivity.py"
    if benchmark.is_file():
        plan.append(("benchmark_superconductivity_v2", [python, benchmark.relative_to(REPO_ROOT).as_posix()]))
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the strict offline foundation release gate.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-stage timeout (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--receipt",
        help="Optional JSON receipt path. Default is under INFINITY_DATA_ROOT/audit.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run compile + focused pytest + core regression + architecture audit + benchmark only.",
    )
    args = parser.parse_args(argv)

    env = _safe_env()
    timeout = max(30, int(args.timeout_seconds))
    plan = build_stage_plan(sys.executable)
    if args.quick:
        plan = [
            item for item in plan
            if item[0] in {
                "compileall",
                "focused_pytest",
                "core_regression",
                "architecture_audit",
                "benchmark_superconductivity_v2",
            }
        ]

    stages: list[StageResult] = []
    for name, command in plan:
        stages.append(_run_stage(name, command, env=env, timeout_seconds=timeout))

    receipt_path = _receipt_path(args.receipt, env)
    receipt = _write_receipt(receipt_path, stages)

    print("\n" + "=" * 72)
    if receipt.passed:
        print("FOUNDATION OFFLINE GATE: PASS")
    else:
        print("FOUNDATION OFFLINE GATE: FAIL")
        print("Failed stages:")
        for name in receipt.failed_stages:
            print(f"  - {name}")
    print(f"Receipt: {receipt_path}")
    print("NOTE: Offline PASS includes static architecture wiring, but it still is")
    print("not a 100/100 production sign-off; live zero-cost benchmark/use remains a")
    print("separate required gate.")
    print("=" * 72)
    return 0 if receipt.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
