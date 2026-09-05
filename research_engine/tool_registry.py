"""Server-owned typed tools. Retrieved text cannot grant execution permissions."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import platform
import time
from types import MappingProxyType

from .code_sandbox import NumericCodeSandbox
from utils.research_runtime import checkpoint, digest, check_cancelled


@dataclass(frozen=True)
class ToolSpec:
    name: str
    effect: str
    roles: frozenset
    required: frozenset


SPECS = MappingProxyType({
    "numeric": ToolSpec("numeric", "bounded_calculation", frozenset({"validation", "implementation", "supervisor"}), frozenset({"code", "inputs"})),
    "json_artifact": ToolSpec("json_artifact", "return_artifact", frozenset({"implementation", "supervisor"}), frozenset({"data"})),
})


def execute_tool(name, arguments, *, role, allowed_effects, call_id):
    spec = SPECS.get(name)
    if spec is None or role not in spec.roles or spec.effect not in frozenset(allowed_effects):
        raise PermissionError("tool/effect is outside this worker's server-owned permissions")
    if not isinstance(arguments, dict) or set(arguments) != spec.required:
        raise ValueError("tool arguments do not match schema")
    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 80:
        raise ValueError("stable tool call id required")
    if len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode()) > 64000:
        raise ValueError("tool input too large")
    if name == "numeric" and (not isinstance(arguments["code"], str) or not isinstance(arguments["inputs"], dict)):
        raise ValueError("numeric expects code:string and inputs:object")

    def run():
        check_cancelled()
        begin = time.time()
        record = {"tool": name, "effect": spec.effect, "started_at": begin,
            "input_sha256": digest(arguments), "python_version": platform.python_version(),
            "physical_experiment": False, "filesystem_access": False, "network_access": False,
            "seed": "NOT_APPLICABLE: deterministic tools", "state": "RUNNING"}
        try:
            if name == "numeric":
                result = asdict(NumericCodeSandbox().run(arguments["code"], arguments["inputs"]))
            else:
                result = arguments["data"]
            content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
            record.update(state="EXECUTED", exit_status=0, stdout=result.get("stdout", "") if isinstance(result, dict) else "",
                stderr="", result=result, artifact={"filename": "result.json", "media_type": "application/json",
                    "content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()},
                adequacy="NOT_ASSESSED: successful execution does not establish model adequacy")
        except Exception as exc:
            record.update(state="FAILED", exit_status=1, stdout="", stderr=type(exc).__name__,
                          result=None, artifact=None, adequacy="NOT_ASSESSED")
        record["finished_at"] = time.time()
        return record
    return checkpoint("tool_" + call_id, [name, arguments, role, sorted(allowed_effects)], run)
