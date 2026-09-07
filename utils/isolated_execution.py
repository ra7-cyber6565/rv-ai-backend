"""Operator-enabled local Docker execution; never falls back to host execution.

Only immutable, already-local images are accepted. All container controls,
paths and commands are assembled here, outside model-generated instructions.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile

from .research_runtime import RuntimeStore, check_cancelled, digest

MAX_FILES = 64
MAX_INPUT = 512_000
MAX_OUTPUT = 2_000_000
MAX_LOG = 64_000
WALL_SECONDS = 30
MEMORY_BYTES = 268_435_456
PIDS = 32
_RUNTIMES = {"python": ("INFINITY_PYTHON_IMAGE", "python3"), "node": ("INFINITY_NODE_IMAGE", "node")}
# Explicit profile; no reliance on an operator's potentially unconfined default.
_SECCOMP = {"defaultAction": "SCMP_ACT_ALLOW", "syscalls": [{"action": "SCMP_ACT_ERRNO",
    "errnoRet": 1, "names": ["mount", "umount2", "pivot_root", "setns", "unshare", "ptrace",
    "process_vm_readv", "process_vm_writev", "bpf", "perf_event_open", "keyctl", "add_key",
    "request_key", "init_module", "finit_module", "delete_module", "kexec_load", "reboot",
    "swapon", "swapoff", "open_by_handle_at", "io_uring_setup"]}]}


def safe_path(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 180 or "\\" in name or "\x00" in name:
        raise ValueError("invalid artifact path")
    parts = name.split("/")
    if name.startswith("/") or any(p in {"", ".", ".."} for p in parts) or ":" in name:
        raise ValueError("artifact path must stay inside its workspace")
    return str(PurePosixPath(name))


def validate_request(runtime, files, entrypoint):
    if runtime not in _RUNTIMES or not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("unsupported runtime or file count")
    normalized = {}
    for name, content in files.items():
        name = safe_path(name)
        if name == ".infinity-runner.py":
            raise ValueError("reserved executor filename")
        if not isinstance(content, str):
            raise ValueError("source files must be UTF-8 text")
        normalized[name] = content
    if sum(len(v.encode()) for v in normalized.values()) > MAX_INPUT:
        raise ValueError("source payload exceeds limit")
    entrypoint = safe_path(entrypoint)
    if entrypoint not in normalized or not entrypoint.endswith(".py" if runtime == "python" else ".js"):
        raise ValueError("entrypoint must be a supplied source file")
    # A file cannot also be an ancestor directory of another input.
    if any(str(parent) in normalized for name in normalized for parent in PurePosixPath(name).parents if str(parent) != "."):
        raise ValueError("conflicting source paths")
    return normalized, entrypoint


def package_files(files, filename="build-artifacts.zip"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(safe_path(name), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode() if isinstance(content, str) else content)
    data = stream.getvalue()
    return {"filename": filename, "media_type": "application/zip", "encoding": "base64",
            "content": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "files": [{"path": n, "sha256": hashlib.sha256(v.encode() if isinstance(v, str) else v).hexdigest()}
                                         for n, v in sorted(files.items())]}


class DockerExecutor:
    def __init__(self, store=None):
        self.store = store or RuntimeStore()
        with self.store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS execution_leases (name TEXT PRIMARY KEY, expires REAL)")

    def _prefix(self):
        binary = shutil.which("docker")
        endpoint = os.environ.get("INFINITY_DOCKER_SOCKET", "unix:///var/run/docker.sock")
        if not binary or os.environ.get("INFINITY_BUILD_EXECUTOR") != "docker":
            raise ValueError("local Docker executor is not enabled")
        if not endpoint.startswith("unix:///") or any(c in endpoint for c in ("\n", "\r", "\x00")):
            raise ValueError("only an explicitly local Docker socket is allowed")
        return [binary, "--host", endpoint]

    def _small(self, args, *, timeout=10):
        # Commands here have bounded daemon metadata output, never program logs.
        return subprocess.run(self._prefix() + args, capture_output=True, timeout=timeout,
                              env={"PATH": os.defpath, "DOCKER_CONFIG": self._config}, check=False)

    def _stream(self, args, *, timeout, cap, cancel=True):
        process = subprocess.Popen(self._prefix() + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={"PATH": os.defpath, "DOCKER_CONFIG": self._config}, start_new_session=True)
        output, reason = bytearray(), None
        poller = selectors.DefaultSelector()
        poller.register(process.stdout, selectors.EVENT_READ)
        end = time.monotonic() + timeout
        try:
            while poller.get_map():
                if cancel:
                    check_cancelled()
                if time.monotonic() >= end:
                    reason = "wall_time_limit"
                    break
                for key, _ in poller.select(.1):
                    block = os.read(key.fileobj.fileno(), min(65536, cap + 1 - len(output)))
                    if not block:
                        poller.unregister(key.fileobj)
                    else:
                        output.extend(block)
                        if len(output) > cap:
                            reason = "output_limit"
                            break
                if reason:
                    break
            if reason:
                process.kill()
            returncode = process.wait(timeout=3)
            return returncode, bytes(output[:cap]), reason
        finally:
            poller.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            process.stdout.close()

    def readiness(self, runtime):
        if not hasattr(self, "_config"):
            with tempfile.TemporaryDirectory(prefix="executor-probe-") as config:
                self._config = config
                try:
                    return self.readiness(runtime)
                finally:
                    del self._config
        if runtime not in _RUNTIMES:
            return {"ready": False, "reason": "unsupported_runtime"}
        try:
            self._prefix()
            image = os.environ.get(_RUNTIMES[runtime][0], "")
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                return {"ready": False, "reason": "immutable_local_image_required"}
            info = self._small(["info", "--format", "{{json .}}"])
            state = json.loads(info.stdout) if info.returncode == 0 else {}
            if state.get("OSType") != "linux" or not state.get("MemoryLimit") or not state.get("PidsLimit"):
                return {"ready": False, "reason": "required_linux_resource_controls_unavailable"}
            found = self._small(["image", "inspect", image, "--format", "{{.Id}}"])
            if found.returncode or found.stdout.decode().strip() != image:
                return {"ready": False, "reason": "approved_image_not_local"}
            return {"ready": True, "image": image, "engine_version": state.get("ServerVersion", "UNKNOWN")}
        except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return {"ready": False, "reason": "local_executor_unavailable"}

    def _remove(self, name):
        """Confirm deletion or absence; ambiguous daemon errors keep the lease."""
        try:
            if self._small(["rm", "-f", name]).returncode == 0:
                return True
            listing = self._small(["ps", "-a", "--filter", "name=^/"+name+"$", "--format", "{{.Names}}"])
            return listing.returncode == 0 and not listing.stdout.strip()
        except (ValueError, OSError, subprocess.SubprocessError):
            return False

    def run(self, runtime, files, entrypoint):
        files, entrypoint = validate_request(runtime, files, entrypoint)
        record = {"state": "BLOCKED", "runtime": runtime, "input_sha256": digest([runtime, files, entrypoint]),
                  "started_at": time.time(), "physical_experiment": False, "artifact": None,
                  "automatic_deploy_allowed": False, "model_adequacy": "NOT_ASSESSED"}
        from .storage_paths import ensure_layout
        with tempfile.TemporaryDirectory(prefix="build-", dir=ensure_layout()["temp"]) as root:
            self._config = str(Path(root) / "docker-config")
            Path(self._config).mkdir()
            readiness = self.readiness(runtime)
            record["executor"] = readiness
            if not readiness["ready"]:
                return dict(record, reason=readiness["reason"], finished_at=time.time())
            name = "infinity-exec-" + uuid.uuid4().hex
            # Reconcile expired leases before freeing their resource slots.
            with self.store.db() as db:
                expired = db.execute("SELECT name FROM execution_leases WHERE expires<?", (time.time(),)).fetchall()
            for old in expired:
                if self._remove(old[0]):
                    with self.store.transaction() as db:
                        db.execute("DELETE FROM execution_leases WHERE name=?", (old[0],))
            with self.store.transaction() as db:
                if db.execute("SELECT count(*) FROM execution_leases").fetchone()[0] >= 2:
                    return dict(record, reason="shared_executor_slots_exhausted", finished_at=time.time())
                db.execute("INSERT INTO execution_leases VALUES(?,?)", (name, time.time()+120))
            creation_attempted = False
            try:
                inputs = Path(root) / "inputs"
                inputs.mkdir(mode=0o755)
                for path, content in files.items():
                    target = inputs / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
                    target.chmod(0o644)
                runner = inputs / ".infinity-runner.py"
                runner.write_bytes(Path(__file__).with_name("isolated_runner.py").read_bytes())
                runner.chmod(0o644)
                profile = Path(root) / "seccomp.json"
                profile.write_text(json.dumps(_SECCOMP))
                if "," in str(inputs):
                    raise ValueError("unsupported workspace path")
                command = ["python3", "-I", "-B", "/inputs/.infinity-runner.py", runtime, entrypoint]
                args = ["create", "--name", name, "--pull", "never", "--network", "none", "--read-only",
                    "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--security-opt", "seccomp="+str(profile), "--memory", str(MEMORY_BYTES),
                    "--memory-swap", str(MEMORY_BYTES), "--cpus", "1", "--pids-limit", str(PIDS),
                    "--ulimit", "nofile=64:64", "--ulimit", "core=0:0", "--log-driver", "none",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
                    "--tmpfs", "/work:rw,nosuid,nodev,size=16m,mode=1777",
                    "--mount", f"type=bind,src={inputs},dst=/inputs,readonly", "--workdir", "/work",
                    "--label", "infinity.executor=bounded-build", "--entrypoint", command[0],
                    readiness["image"], *command[1:]]
                creation_attempted = True
                started = self._small(args)
                if started.returncode:
                    raise ValueError("container_creation_failed")
                record.update(state="RUNNING", isolation="LOCAL_DOCKER", network_access=False,
                    host_filesystem_access=False, limits={"wall_seconds": WALL_SECONDS,
                    "memory_bytes": MEMORY_BYTES, "pids": PIDS, "cpus": 1, "artifact_bytes": MAX_OUTPUT})
                code, logs, limit = self._stream(["start", "--attach", name], timeout=WALL_SECONDS, cap=3_000_000)
                if limit:
                    self._small(["kill", name])
                inspected = self._small(["inspect", name, "--format", "{{json .State}}"])
                state = json.loads(inspected.stdout) if inspected.returncode == 0 else {}
                record.update(exit_status=state.get("ExitCode", code), stdout="",
                              state="FAILED", failure=limit or "execution_failed")
                if not limit and state.get("Running") is False and state.get("ExitCode") == 0:
                    payload = json.loads(logs)
                    if payload.get("protocol") != 1 or type(payload.get("exit_status")) is not int or not isinstance(payload.get("files"), dict):
                        raise ValueError("invalid executor receipt")
                    generated = {safe_path(k): base64.b64decode(v, validate=True) for k, v in payload["files"].items()}
                    if len(generated) > MAX_FILES or sum(map(len, generated.values())) > MAX_OUTPUT:
                        raise ValueError("artifact limit")
                    record.update(exit_status=payload["exit_status"], stdout=str(payload.get("stdout", ""))[:MAX_LOG],
                                  failure=payload.get("failure") or "execution_failed")
                    if payload["exit_status"] == 0 and payload.get("failure") is None:
                        record.update(state="EXECUTED", failure=None, result={"output_files": len(generated)},
                            artifact=package_files({**{"source/"+p: v for p, v in files.items()},
                                                    **{"output/"+p: v for p, v in generated.items()}}))
                record["oom_killed"] = state.get("OOMKilled") is True
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                record.update(state="FAILED", failure=type(exc).__name__, artifact=None)
            finally:
                removed = self._remove(name) if creation_attempted else True
                if removed:
                    with self.store.transaction() as db:
                        db.execute("DELETE FROM execution_leases WHERE name=?", (name,))
                else:
                    record.update(state="FAILED", failure="container_cleanup_unconfirmed", artifact=None)
                record["cleanup_confirmed"] = removed
                record["finished_at"] = time.time()
            return record
