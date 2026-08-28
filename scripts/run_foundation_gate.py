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
- runs the complete ``tests/`` pytest suite (so pytest-only files really execute);
- exercises the real FastAPI session/chat/async-job/result path with no network;
- runs the legacy/core regression;
- directly executes only test files that contain an explicit ``__main__`` harness;
- runs a direct-provider-bypass audit;
- runs a production-wiring/static architecture audit;
- executes Claude's offline 8-domain adversarial reliability benchmark;
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.release_identity import repository_identity


DEFAULT_TIMEOUT_SECONDS = 15 * 60

# These files are the focused integration gates maintained by ChatGPT. The full
# tests/ pytest pass below is the authoritative catch-all for pytest-style tests.
FOCUSED_PYTEST = (
    "tests/test_upload_safety.py",
    "tests/test_body_limit.py",
    "tests/test_work_root.py",
    "tests/test_storage_paths.py",
    "tests/test_storage_quota.py",
    "tests/test_archive_manifest.py",
    "tests/test_archive_manifest_concurrency.py",
    "tests/test_archive_retry.py",
    "tests/test_cloud_storage.py",
    "tests/test_cloud_archive.py",
    "tests/test_archive_runtime.py",
    "tests/test_archive_integration.py",
    "tests/test_archive_routes.py",
    "tests/test_research_job_archive_retention.py",
    "tests/test_process_lock.py",
    "tests/test_google_drive_rclone.py",
    "tests/test_provider_factory.py",
    "tests/test_zero_cost_guard.py",
    "tests/test_reasoning_zero_cost.py",
    "tests/test_reasoning_router.py",
    "tests/test_reasoning_router_integration.py",
    "tests/test_provider_health.py",
    "tests/test_offline_reasoner.py",
    "tests/test_reasoning_status.py",
    "tests/test_gemini_key_status.py",
    "tests/test_quick_chat_resilience.py",
    "tests/test_chat_resilience.py",
    "tests/test_gemini_diag_zero_call.py",
    "tests/test_quota_backup.py",
    "tests/test_provider_bypass_audit.py",
    "tests/test_architecture_audit.py",
    "tests/test_release_state.py",
    "tests/test_repo_hygiene.py",
    "tests/test_admin_guard.py",
    "tests/test_security_config.py",
    "tests/test_request_guard.py",
    "tests/test_api_input_bounds.py",
    "tests/test_job_access.py",
    "tests/test_job_routes_access.py",
    "tests/test_job_result_progress_snapshot.py",
    "tests/test_project_access.py",
    "tests/test_project_route_guards.py",
    "tests/test_project_wiring.py",
    "tests/test_private_response_headers.py",
    "tests/test_cors_private_headers.py",
    "tests/test_web_job_capability.py",
    "tests/test_web_source_link_safety.py",
    "tests/test_source_prompt_guard.py",
    "tests/test_source_output_safety.py",
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
    "tests/test_unverified_semantics.py",
    "tests/test_network_safety.py",
    "tests/test_advanced_discovery.py",
    "tests/test_specialist_research.py",
    "tests/test_research_assurance.py",
    "tests/test_marathon_all_rounds.py",
    "tests/test_exam_intelligence.py",
    "tests/test_resumable_reading.py",
    "tests/test_evidence_mutation_matrix.py",
    "tests/test_lenses.py",
    "tests/test_lens_independent_audit.py",
    "tests/test_deployed_readonly_smoke.py",
    "tests/test_release_identity.py",
    "tests/test_release_bundle.py",
    "tests/test_patents.py",
    "tests/test_live_zero_cost_gate.py",
    "tests/test_windows_launchers.py",
    "tests/test_foundation_gate_runner.py",
    "tests/test_source_integrity.py",
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
    code_revision: str
    repository_clean: bool
    code_identity_verified: bool
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
    # Direct ``python tests/test_*.py`` harnesses put ``tests/`` (not the repo
    # root) first on sys.path. Always make production packages importable while
    # preserving any caller-supplied dependency target directory.
    repo_path = str(REPO_ROOT)
    inherited_paths = [
        item for item in str(env.get("PYTHONPATH", "") or "").split(os.pathsep)
        if item and item != repo_path
    ]
    env["PYTHONPATH"] = os.pathsep.join([repo_path, *inherited_paths])
    env.update(
        {
            "ZERO_COST_ONLY": "true",
            "RATE_LIMIT_ENABLED": "true",
            "GEMINI_API_KEY": "",
            "GEMINI_API_KEY_BACKUP": "",
            "GEMINI_API_KEY_FALLBACK": "",
            "GEMINI_API_KEYS": "",
            "GEMINI_API_KEY_LIST": "",
            "GEMINI_BACKUP_KEYS": "",
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
            "INFINITY_ADMIN_TOKEN": "",
            "INFINITY_OFFLINE_TEST": "true",
        }
    )
    for i in range(2, 10):
        env[f"GEMINI_API_KEY_{i}"] = ""
        env[f"GEMINI_API_KEY{i}"] = ""
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


def _has_main_harness(path: Path) -> bool:
    """True only for tests intended to be meaningful when run as ``python file``."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    return (
        'if __name__ == "__main__"' in text
        or "if __name__ == '__main__'" in text
    )


def _receipt_path(value: str | None, env: dict[str, str]) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    root = Path(env["INFINITY_DATA_ROOT"]).expanduser().resolve()
    return root / "audit" / "foundation_gate_latest.json"


def _write_receipt(
    path: Path,
    stages: list[StageResult],
    *,
    identity: dict[str, object] | None = None,
) -> GateReceipt:
    failed = [stage.name for stage in stages if stage.status != "passed"]
    code = repository_identity(REPO_ROOT) if identity is None else dict(identity)
    identity_verified = bool(
        code.get("available")
        and code.get("revision")
        and code.get("clean") is True
    )
    if not identity_verified:
        failed.append("clean_repository_identity")
    receipt = GateReceipt(
        schema_version=2,
        created_at_epoch=int(time.time()),
        python=sys.version.split()[0],
        repo_root=str(REPO_ROOT),
        code_revision=str(code.get("revision") or ""),
        repository_clean=bool(code.get("clean") is True),
        code_identity_verified=identity_verified,
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

    tests_dir = REPO_ROOT / "tests"
    if tests_dir.is_dir():
        # This is the real catch-all. Running a pytest-only file with `python`
        # merely imports/defines tests and exits 0 without executing assertions.
        plan.append(("all_pytest", [python, "-m", "pytest", "-q", "tests"]))

    api_smoke = REPO_ROOT / "scripts" / "run_offline_api_smoke.py"
    if api_smoke.is_file():
        plan.append((
            "offline_api_smoke",
            [python, api_smoke.relative_to(REPO_ROOT).as_posix()],
        ))

    if (REPO_ROOT / "test_research_engine.py").is_file():
        plan.append(("core_regression", [python, "test_research_engine.py"]))

    # Some legacy project tests use their own main()/exit-code harness instead of
    # pytest collection. Execute only those explicitly designed for script mode.
    if tests_dir.is_dir():
        for path in sorted(tests_dir.glob("test_*.py")):
            if not _has_main_harness(path):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            plan.append((f"script_harness:{rel}", [python, rel]))

    provider_audit = REPO_ROOT / "scripts" / "audit_provider_bypass.py"
    if provider_audit.is_file():
        plan.append((
            "provider_bypass_audit",
            [python, provider_audit.relative_to(REPO_ROOT).as_posix()],
        ))

    architecture = REPO_ROOT / "scripts" / "audit_architecture.py"
    if architecture.is_file():
        plan.append((
            "architecture_audit",
            [python, architecture.relative_to(REPO_ROOT).as_posix()],
        ))

    cross_domain = REPO_ROOT / "tests" / "benchmark_cross_domain.py"
    if cross_domain.is_file():
        plan.append((
            "benchmark_cross_domain",
            [python, cross_domain.relative_to(REPO_ROOT).as_posix()],
        ))

    benchmark = REPO_ROOT / "tests" / "benchmark_superconductivity.py"
    if benchmark.is_file():
        plan.append((
            "benchmark_superconductivity_v2",
            [python, benchmark.relative_to(REPO_ROOT).as_posix()],
        ))
    dark_matter = REPO_ROOT / "tests" / "benchmark_dark_matter_acceptance.py"
    if dark_matter.is_file():
        plan.append((
            "benchmark_dark_matter_acceptance",
            [python, dark_matter.relative_to(REPO_ROOT).as_posix()],
        ))
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
        help="Run compile + focused/full pytest + core regression + provider/architecture audits + both benchmarks only.",
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
                "all_pytest",
                "core_regression",
                "provider_bypass_audit",
                "architecture_audit",
                "benchmark_cross_domain",
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
    print("NOTE: Offline PASS includes full pytest coverage, provider-bypass and")
    print("static architecture wiring checks plus both adversarial benchmarks, but")
    print("it still is not a 100/100 production sign-off; live zero-cost use remains")
    print("a separate required gate.")
    print("=" * 72)
    return 0 if receipt.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
