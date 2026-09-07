"""Opt-in company validation on a standard public GitHub-hosted runner.

Default is preflight only. This runner neither deploys nor connects to a laptop.
It accepts fixed reviewed-code receipts, never arbitrary commands or questions.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils.release_identity import repository_identity, normalize_git_revision
from scripts.run_company_host import run_live_modes, write_json
from scripts.run_live_zero_cost_gate import preflight

REPOSITORY = "ra7-cyber6565/rv-ai-backend"
REQUIRED_STAGES = {"compileall", "focused_pytest", "all_pytest", "offline_api_smoke",
                   "provider_bypass_audit", "architecture_audit", "benchmark_cross_domain",
                   "benchmark_superconductivity_v2"}


class HostedGateBlocked(RuntimeError):
    pass


def read_record(path, limit=8_000_000):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise HostedGateBlocked("receipt_size_limit")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise HostedGateBlocked("receipt_schema_invalid")
    return result


def selection(env, identity):
    reasons = []
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
                       "GITHUB_REPOSITORY": REPOSITORY, "INFINITY_REPOSITORY_PRIVATE": "false",
                       "INFINITY_HOSTED_LIVE_REQUESTED": "true"}.items():
        if env.get(key) != value:
            reasons.append("hosted_selection_invalid:"+key)
    revision = normalize_git_revision(env.get("INFINITY_REVIEWED_COMMIT"))
    if not revision or revision != env.get("GITHUB_SHA") or revision != identity.get("revision") or identity.get("clean") is not True:
        reasons.append("reviewed_clean_revision_required")
    if not all(re.fullmatch(r"[1-9][0-9]*", env.get(k, "")) for k in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")):
        reasons.append("workflow_run_identity_required")
    return reasons


def validate_receipts(foundation, host, env):
    revision = env["INFINITY_REVIEWED_COMMIT"].lower()
    for receipt in (foundation, host):
        if receipt.get("code_revision") != revision or receipt.get("repository_clean") is not True:
            raise HostedGateBlocked("prerequisite_revision_mismatch")
        if receipt.get("ci_run_id") != env["GITHUB_RUN_ID"] or receipt.get("ci_run_attempt") != env["GITHUB_RUN_ATTEMPT"]:
            raise HostedGateBlocked("prerequisite_workflow_run_mismatch")
    stages = foundation.get("stages")
    if (foundation.get("passed") is not True or foundation.get("offline_zero_cost") is not True
        or not isinstance(stages, list) or not stages
        or not REQUIRED_STAGES.issubset({row.get("name") for row in stages if isinstance(row, dict)})
        or any(not isinstance(row, dict) or row.get("status") != "passed" or type(row.get("returncode")) is not int or row["returncode"] != 0 for row in stages)):
        raise HostedGateBlocked("foundation_prerequisites_failed")
    suites = host.get("host_tests")
    if not isinstance(suites, dict) or set(suites) != {"isolated_builds", "protected_improvement"}:
        raise HostedGateBlocked("host_suites_missing")
    for label, minimum in (("isolated_builds", 10), ("protected_improvement", 7)):
        row = suites[label]
        if (row.get("passed") is not True or type(row.get("tests_run")) is not int
            or row["tests_run"] < minimum or type(row.get("skipped")) is not int
            or row["skipped"] != 0 or type(row.get("exit_status")) is not int or row["exit_status"] != 0):
            raise HostedGateBlocked("host_suite_failed_or_skipped")
    smoke = host.get("localhost_smoke") or {}
    checks = smoke.get("checks") or []
    if (smoke.get("complete") is not True or smoke.get("expected_code_revision") != revision
        or smoke.get("deployed_code_revision") != revision or len(checks) < 20
        or any(row.get("passed") is not True for row in checks)):
        raise HostedGateBlocked("localhost_prerequisite_failed")
    images = {}
    for language in ("python", "node"):
        row = (host.get("runtimes") or {}).get(language) or {}
        if row.get("ready") is not True or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(row.get("image", ""))):
            raise HostedGateBlocked("immutable_runtime_required")
        images[language] = row["image"]
    return images


def summarize(results):
    # No raw provider/source text or arbitrary receipt fields in public artifacts.
    public = {}
    for mode in ("COMPANY", "COMPANY_PLUS"):
        if mode not in results:
            continue
        row = results[mode]
        receipt = row.get("receipt") or {}
        checks = [{"name": c["name"], "passed": c.get("passed") is True}
                  for c in receipt.get("checks", [])[:128]
                  if isinstance(c, dict) and re.fullmatch(r"[a-z0-9_]{1,100}", str(c.get("name", "")))]
        public[mode] = {"passed": row.get("passed") is True, "checks": checks,
                        "depth_mode": mode}
    return public


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    report = {"schema": 1, "created_at_epoch": int(time.time()), "passed": False,
              "live_test_performed": False, "quality_benchmark": "NOT_TESTED",
              "production_deployed": False, "release_ready": False,
              "contains_credentials_or_source_text": False}
    destination = None
    try:
        identity = repository_identity(ROOT)
        reasons = selection(os.environ, identity)
        if reasons:
            raise HostedGateBlocked(";".join(reasons))
        report.update(code_revision=identity["revision"], ci_run_id=os.environ["GITHUB_RUN_ID"],
                      ci_run_attempt=os.environ["GITHUB_RUN_ATTEMPT"])
        raw_root = Path(os.environ.get("INFINITY_DATA_ROOT", ""))
        runner_temp = Path(os.environ.get("RUNNER_TEMP", ""))
        if (not raw_root.is_absolute() or not runner_temp.is_absolute()
            or raw_root.resolve() == runner_temp.resolve() or runner_temp.resolve() not in raw_root.resolve().parents
            or ROOT == raw_root.resolve() or ROOT in raw_root.resolve().parents):
            raise HostedGateBlocked("dedicated_runner_temporary_storage_required")
        destination = raw_root / "audit" / "hosted_live_gate.json"
        proof_root = Path(os.environ.get("INFINITY_PREREQUISITE_ROOT", ""))
        if not proof_root.is_absolute() or proof_root.resolve() == raw_root.resolve():
            raise HostedGateBlocked("separate_prerequisite_root_required")
        images = validate_receipts(read_record(proof_root / "audit" / "foundation_gate_ci.json"),
                                   read_record(proof_root / "audit" / "company_host_latest.json", 256000), os.environ)
        # No private .env is loaded here. The workflow scopes dedicated credentials
        # to this final step; no credentials are supplied to dependency installation.
        if not os.environ.get("GEMINI_MODEL", "").strip():
            raise HostedGateBlocked("explicit_model_identifier_required")
        os.environ.update(INFINITY_PRESERVE_STORED_DATA="true", INFINITY_BUILD_EXECUTOR="docker",
                          INFINITY_PYTHON_IMAGE=images["python"], INFINITY_NODE_IMAGE=images["node"])
        from utils.storage_paths import configure_process_storage
        configure_process_storage()
        ready = preflight(os.environ, validate_storage=True)
        if not ready["ready"]:
            raise HostedGateBlocked("confirmed_free_model_or_storage_not_ready")
        report["state"] = "PREFLIGHT_READY"
        if args.execute:
            report["live_test_performed"] = True
            results = run_live_modes(raw_root, identity["revision"])
            report["modes"] = summarize(results)
            report["passed"] = set(results) == {"COMPANY", "COMPANY_PLUS"} and all(r.get("passed") is True for r in results.values())
            report["state"] = "LIVE_GATES_PASSED" if report["passed"] else "LIVE_GATES_FAILED"
        write_json(destination, report)
        print(json.dumps(report, indent=2))
        return 0 if not args.execute or report["passed"] else 1
    except Exception as exc:
        report.update(state="BLOCKED", failure_code=str(exc) if isinstance(exc, HostedGateBlocked) else "hosted_operation_failed")
        if destination is not None:
            try:
                write_json(destination, report)
            except Exception:
                pass
        print(json.dumps(report, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
