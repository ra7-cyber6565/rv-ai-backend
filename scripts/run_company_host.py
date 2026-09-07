#!/usr/bin/env python3
"""Prepare/check a local Linux (including WSL) research host; no cloud changes.

Default: preflight only. Preparation, actual isolation tests, live model calls
and localhost serving each require their named operator flag.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.release_identity import repository_identity, normalize_git_revision
from utils.isolated_execution import DockerExecutor
from scripts.run_live_zero_cost_gate import preflight, load_local_env, _validate_runtime_storage

DEPENDENCIES = ("fastapi", "uvicorn", "sympy", "pytest", "dotenv")
SUITES = {"isolated_builds": "test_isolated_build_runtime.py", "protected_improvement": "test_improvement_runtime.py"}
_IMAGE = re.compile(r"sha256:[a-f0-9]{64}")


class HostBlocked(RuntimeError):
    """Static operator-action message, never raw third-party error content."""


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="host-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def setup_env(data_root):
    load_local_env()
    os.environ["INFINITY_DATA_ROOT"] = str(data_root)
    from utils.storage_paths import configure_process_storage
    configure_process_storage()
    path = data_root / "host-runtime.json"
    if path.is_file():
        with path.open("rb") as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            raise ValueError("runtime configuration exceeds size limit")
        config = json.loads(raw)
        if config.get("schema") != 1:
            raise ValueError("unknown runtime configuration schema")
        for key in ("INFINITY_PYTHON_IMAGE", "INFINITY_NODE_IMAGE"):
            image = config.get(key)
            if not isinstance(image, str) or not _IMAGE.fullmatch(image):
                raise ValueError("runtime configuration needs immutable image IDs")
            os.environ.setdefault(key, image)
        os.environ.setdefault("INFINITY_BUILD_EXECUTOR", "docker")


def inspect_host(expected_commit=""):
    identity = repository_identity(ROOT)
    storage = _validate_runtime_storage(os.environ)
    blockers = []
    if platform.system() != "Linux":
        blockers.append("linux_or_wsl_required")
    if sys.version_info < (3, 11):
        blockers.append("python_3_11_or_newer_required")
    if not identity["available"] or not identity["clean"]:
        blockers.append("clean_committed_checkout_required")
    if expected_commit and identity["revision"] != expected_commit:
        blockers.append("reviewed_revision_mismatch")
    if not storage["ready"]:
        blockers.extend(storage["blockers"])
    missing = [name for name in DEPENDENCIES if importlib.util.find_spec(name) is None]
    if missing:
        blockers.append("python_dependencies_missing")
    runtime = {}
    if storage["ready"]:
        executor = DockerExecutor()
        runtime = {language: executor.readiness(language) for language in ("python", "node")}
        blockers.extend(language+":"+result["reason"] for language, result in runtime.items() if not result["ready"])
    live = preflight(os.environ, validate_storage=False)
    return {"code_revision": identity["revision"], "repository_clean": identity["clean"],
        "python": platform.python_version(), "host_platform": platform.system(), "storage": storage,
        "missing_dependencies": missing, "runtimes": runtime, "host_ready": not blockers,
        "host_blockers": blockers, "live_preflight": live, "live_test_performed": False,
        "release_ready": False, "contains_credentials": False}


def quiet_run(command, *, timeout, env=None, cwd=ROOT):
    # Installer/provider subprocess output can contain private paths. Keep only
    # a bounded test-summary tail in memory and never publish raw exceptions.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            raise
        output.seek(0, 2)
        size = output.tell()
        output.seek(max(0, size-16000))
        return code, output.read(16000).decode("utf-8", "replace")


def prepare(data_root):
    """Operator-requested local setup; never sets model eligibility or keys."""
    identity = repository_identity(ROOT)
    if platform.system() != "Linux" or sys.version_info < (3, 11) or not identity["clean"]:
        raise HostBlocked("preparation requires Linux, Python >=3.11 and a clean checkout")
    if not _validate_runtime_storage(os.environ)["ready"]:
        raise HostBlocked("runtime storage not ready")
    os.environ["INFINITY_BUILD_EXECUTOR"] = "docker"
    executor = DockerExecutor()
    try:
        executor._prefix()
    except ValueError as exc:
        raise HostBlocked("local Docker CLI unavailable; enable Docker integration in this Linux/WSL host") from exc
    # Check the actual local daemon before any dependency download.
    with tempfile.TemporaryDirectory(prefix="host-prepare-") as temp:
        executor._config = temp
        info = executor._small(["info", "--format", "{{json .}}"])
        state = json.loads(info.stdout) if info.returncode == 0 else {}
        if state.get("OSType") != "linux" or not state.get("MemoryLimit") or not state.get("PidsLimit"):
            raise HostBlocked("local Docker Linux resource controls unavailable; start Docker and enable this WSL distribution")
        venv = data_root / "host-venv"
        python = venv / "bin" / "python"
        if not python.is_file():
            print("Preparing private Linux Python environment...", flush=True)
            if quiet_run([sys.executable, "-m", "venv", "--copies", str(venv)], timeout=120)[0]:
                raise HostBlocked("Python venv preparation failed; ensure python3-venv is installed")
        # Only the repository's reviewed requirement file; no generated commands.
        stamp = data_root / "host-dependencies.json"
        requirement_hash = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
        previous = json.loads(stamp.read_text()) if stamp.is_file() and stamp.stat().st_size < 4096 else {}
        probe_command = [str(python), "-c", "import fastapi, uvicorn, sympy, pytest, dotenv, platform; print(platform.python_version())"]
        probe_code, probe_tail = quiet_run(probe_command, timeout=60)
        version = probe_tail.strip() if re.fullmatch(r"\d+\.\d+\.\d+", probe_tail.strip()) else "UNKNOWN"
        if probe_code or previous.get("requirements_sha256") != requirement_hash or previous.get("python") != version:
            print("Installing this checkout's Python dependencies in the private environment...", flush=True)
            install_env = {key: os.environ[key] for key in ("PATH", "LANG", "LD_LIBRARY_PATH", "SSL_CERT_FILE") if key in os.environ}
            install_env.update(PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CACHE_DIR=str(data_root / "cache" / "pip"), TMPDIR=str(data_root / "temp"))
            command = [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "pytest"]
            if quiet_run(command, timeout=1800, env=install_env)[0]:
                raise HostBlocked("dependency installation failed; check network and available disk space")
            probe_code, probe_tail = quiet_run(probe_command, timeout=60)
            if probe_code or not re.fullmatch(r"\d+\.\d+\.\d+", probe_tail.strip()):
                raise HostBlocked("installed dependencies did not pass the interpreter import probe")
            write_json(stamp, {"requirements_sha256": requirement_hash, "python": probe_tail.strip()})
        image_config = data_root / "host-runtime.json"
        if image_config.is_file():
            setup_env(data_root)
            if all(executor.readiness(language)["ready"] for language in ("python", "node")):
                return python
        print("Building the reviewed local execution image (no registry push)...", flush=True)
        context = Path(temp) / "context"; context.mkdir()
        (context / "Dockerfile").write_bytes((ROOT / "tests" / "fixtures" / "executor.Dockerfile").read_bytes())
        iid = Path(temp) / "image-id"
        docker_env = {"PATH": os.defpath, "DOCKER_CONFIG": temp}
        command = executor._prefix() + ["build", "--iidfile", str(iid), str(context)]
        if quiet_run(command, timeout=900, env=docker_env)[0]:
            raise HostBlocked("local runtime image build failed; check Docker and registry access")
        image = iid.read_text().strip()
        if not _IMAGE.fullmatch(image):
            raise HostBlocked("image content ID could not be verified")
        config = {"schema": 1, "INFINITY_PYTHON_IMAGE": image, "INFINITY_NODE_IMAGE": image,
                  "prepared_revision": identity["revision"]}
        write_json(image_config, config)
        return python


def run_isolation_suites():
    results = {}
    env = dict(os.environ, INFINITY_REAL_EXECUTOR_TEST="1")
    for label, filename in SUITES.items():
        print("Running actual host check: "+label, flush=True)
        code, tail = quiet_run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", filename, "-v"],
                              timeout=300, env=env)
        count = re.search(r"Ran (\d+) tests?", tail)
        skipped = re.search(r"skipped=(\d+)", tail)
        ran = int(count.group(1)) if count else 0
        skip_count = int(skipped.group(1)) if skipped else 0
        results[label] = {"passed": code == 0 and ran > 0 and skip_count == 0,
                          "tests_run": ran, "skipped": skip_count, "exit_status": code}
    return results


def run_live_modes(data_root, identity):
    results = {}
    for mode in ("COMPANY", "COMPANY_PLUS"):
        current = repository_identity(ROOT)
        if not current["clean"] or current["revision"] != identity:
            raise HostBlocked("checkout changed during validation")
        print("Running confirmed-zero-cost live research: "+mode, flush=True)
        # Fresh path prevents an old passing receipt satisfying a failed run.
        with tempfile.TemporaryDirectory(prefix="live-gate-", dir=data_root / "temp") as temp:
            path = Path(temp) / "receipt.json"
            code, _ = quiet_run([sys.executable, str(ROOT / "scripts" / "run_live_zero_cost_gate.py"),
                "--execute", "--data-root", str(data_root), "--depth-mode", mode, "--receipt", str(path)], timeout=3900)
            record = json.loads(path.read_text()) if path.is_file() and path.stat().st_size < 256000 else {}
            passed = code == 0 and record.get("passed") is True and record.get("code_revision") == identity and record.get("repository_clean") is True and record.get("depth_mode") == mode
            results[mode] = {"passed": passed, "exit_status": code, "receipt": record}
        if not passed:
            break  # Do not burn another company allocation after a failed release run.
    return results


def serve_local(receipt, data_root, port, *, smoke_only=False):
    from scripts.run_deployed_readonly_smoke import DeployedReadonlySmoke
    identity = repository_identity(ROOT)
    if not identity["clean"] or identity["revision"] != receipt["code_revision"]:
        raise HostBlocked("checkout changed before local startup")
    env = dict(os.environ, GIT_COMMIT_SHA=receipt["code_revision"])
    with tempfile.TemporaryFile() as log:
        # Reserve the actual listening socket. An unrelated service already on
        # this port cannot accidentally satisfy this process's health check.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--fd", str(listener.fileno()), "--workers", "1"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                pass_fds=(listener.fileno(),))
        try:
            from urllib.request import urlopen
            deadline = time.monotonic()+45
            base = f"http://127.0.0.1:{port}"
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise ValueError("local server exited before readiness")
                try:
                    with urlopen(base+"/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.5)
            else:
                raise TimeoutError("local server startup timed out")
            probe = DeployedReadonlySmoke(base, expected_revision=receipt["code_revision"])
            result = probe.run()
            receipt["localhost_smoke"] = result
            receipt["deployment"] = "LOCALHOST_SMOKE_PASSED" if result["complete"] else "LOCALHOST_SMOKE_FAILED"
            write_json(data_root / "audit" / "company_host_latest.json", receipt)
            if not result["complete"]:
                raise HostBlocked("local server smoke failed")
            print("Local app ready: "+base, flush=True)
            if not smoke_only:
                print("Keep this window open. Ctrl+C stops this local server.", flush=True)
                server.wait()
        finally:
            if server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL); server.wait(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--execute-host", action="store_true")
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--check-local-api", action="store_true", help="Start, smoke-test and stop a temporary localhost server; zero model calls")
    parser.add_argument("--smoke-only", action="store_true", help="Stop the local server after its actual smoke check")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if (args.serve and not (args.execute_host and args.execute_live)) or (args.smoke_only and not args.serve):
        parser.error("serving requires --execute-host --execute-live; --smoke-only requires --serve")
    if (args.execute_live or args.check_local_api) and not args.execute_host:
        parser.error("live/API execution first requires --execute-host")
    if not 1024 <= args.port <= 65535 or (args.expected_commit and not normalize_git_revision(args.expected_commit)):
        parser.error("invalid port or expected full commit SHA")
    # Preserve absolute-path validation instead of silently converting a relative path.
    data_root = args.data_root.expanduser()
    if not data_root.is_absolute() or data_root.resolve() == ROOT or ROOT in data_root.resolve().parents or data_root.parent == data_root:
        parser.error("data root must be absolute, outside the repository and not a filesystem root")
    try:
        setup_env(data_root)
        if args.prepare:
            if args.expected_commit and repository_identity(ROOT)["revision"] != args.expected_commit:
                raise HostBlocked("reviewed revision mismatch; preparation blocked")
            python = prepare(data_root)
            forwarded = list(sys.argv[1:] if argv is None else argv)
            forwarded.remove("--prepare")
            os.execv(str(python), [str(python), str(Path(__file__).resolve()), *forwarded])
        venv_python = data_root / "host-venv" / "bin" / "python"
        if venv_python.is_file() and Path(sys.prefix).resolve() != (data_root / "host-venv").resolve():
            os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
        receipt = {"schema": 1, "created_at": time.time(), "ci_run_id": os.getenv("GITHUB_RUN_ID", ""),
                   "ci_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""), **inspect_host(args.expected_commit)}
        receipt.update(host_tests="NOT_TESTED", live_tests="NOT_TESTED", deployment="NOT_PERFORMED")
        if args.execute_host and receipt["host_ready"]:
            receipt["host_tests"] = run_isolation_suites()
        host_pass = isinstance(receipt["host_tests"], dict) and all(r["passed"] for r in receipt["host_tests"].values())
        if args.check_local_api and host_pass:
            serve_local(receipt, data_root, args.port, smoke_only=True)
        if args.execute_live and host_pass and receipt["live_preflight"]["ready"]:
            receipt["live_tests"] = run_live_modes(data_root, receipt["code_revision"])
            receipt["live_test_performed"] = True
        live_pass = isinstance(receipt["live_tests"], dict) and set(receipt["live_tests"]) == {"COMPANY", "COMPANY_PLUS"} and all(r["passed"] for r in receipt["live_tests"].values())
        receipt["state"] = "HOST_AND_LIVE_VALIDATED" if host_pass and live_pass else "HOST_VALIDATED_LIVE_NOT_VERIFIED" if host_pass else "PREFLIGHT_READY" if receipt["host_ready"] else "BLOCKED"
        if isinstance(receipt["host_tests"], dict) and not host_pass:
            receipt["state"] = "HOST_TEST_FAILED"
        elif isinstance(receipt["live_tests"], dict) and not live_pass:
            receipt["state"] = "LIVE_TEST_FAILED"
        # Live/host success is only part of release readiness; no independent quality campaign is implied.
        receipt["quality_benchmark"] = "NOT_TESTED"
        write_json(data_root / "audit" / "company_host_latest.json", receipt)
        print(json.dumps(receipt, indent=2, ensure_ascii=False), flush=True)
        if args.serve:
            if not host_pass or not live_pass:
                print("Local serving blocked: this invocation needs passing host and both live gates.")
                return 2
            serve_local(receipt, data_root, args.port, smoke_only=args.smoke_only)
        return 0 if receipt["host_ready"] and (not args.execute_host or host_pass) and (not args.execute_live or live_pass) else 2
    except KeyboardInterrupt:
        print("Local operation stopped.")
        return 130
    except Exception as exc:
        # No raw provider, installer, path or secret content in the console.
        print(json.dumps({"state": "BLOCKED", "failure_class": type(exc).__name__, "reason": str(exc) if isinstance(exc, HostBlocked) else "operation failed safely; inspect prerequisites", "release_ready": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
