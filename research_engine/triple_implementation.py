"""#40 Triple Independent Implementation.

For important deterministic numeric checks, run the same allow-listed formula
through three computationally independent paths:

1. the existing Python numeric sandbox supplied by the caller;
2. a real Rscript process executing only engine-generated R code; and
3. an independent Decimal-based mathematical evaluator.

Agreement is a *computational consistency* check, not evidence that a scientific
claim, hardware design, treatment, or real-world prediction is true.  The module
fails closed: missing R, malformed tasks, backend errors, non-finite values, or
any pairwise mismatch prevent promotion to ``TRIPLE_AGREEMENT``.

No arbitrary Python/R code is accepted.  User-controlled input is limited to a
small expression grammar and bounded numeric variables.  R code is rendered from
validated AST nodes and invoked with ``shell=False``.
"""
from __future__ import annotations

import ast
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable, Dict, Mapping, Optional, Sequence


_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,39}\Z")
_TASK_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_R_NUMBER_RE = re.compile(
    r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z"
)
_ALLOWED_FUNCTIONS = {"abs", "min", "max", "round", "sqrt"}
_ALLOWED_BINARY = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


@dataclass(frozen=True)
class TripleImplementationPolicy:
    max_tasks: int = 12
    max_expression_chars: int = 240
    max_ast_nodes: int = 80
    max_variables: int = 24
    max_abs_input: float = 1e12
    max_abs_result: float = 1e18
    max_power: int = 12
    r_timeout_seconds: float = 4.0
    default_abs_tolerance: float = 1e-9
    default_rel_tolerance: float = 1e-9


@dataclass(frozen=True)
class FormulaTask:
    task_id: str
    expression: str
    variables: Dict[str, float]
    abs_tolerance: float
    rel_tolerance: float


class FormulaValidationError(ValueError):
    pass


def _safe_error(value: object, allowed: set[str]) -> str:
    text = str(value or "")
    return text if text in allowed else "backend_error"


def _float_literal(value: float) -> str:
    if not math.isfinite(value):
        raise FormulaValidationError("non_finite_variable")
    return format(float(value), ".17g")


class FormulaGrammar:
    """Shared allow-list parser only; execution remains backend-independent."""

    def __init__(self, policy: Optional[TripleImplementationPolicy] = None):
        self.policy = policy or TripleImplementationPolicy()

    def parse_task(self, raw: Mapping[str, Any], index: int = 0) -> tuple[FormulaTask, ast.Expression]:
        if not isinstance(raw, Mapping):
            raise FormulaValidationError("task_not_mapping")
        task_id = str(raw.get("task_id") or f"T{index + 1}").strip()
        if not _TASK_ID_RE.fullmatch(task_id):
            raise FormulaValidationError("invalid_task_id")
        expression = str(raw.get("expression") or "").strip()
        if not expression:
            raise FormulaValidationError("empty_expression")
        if len(expression) > self.policy.max_expression_chars:
            raise FormulaValidationError("expression_too_long")
        variables_raw = raw.get("variables") or {}
        if not isinstance(variables_raw, Mapping):
            raise FormulaValidationError("variables_not_mapping")
        if len(variables_raw) > self.policy.max_variables:
            raise FormulaValidationError("too_many_variables")
        variables: Dict[str, float] = {}
        for name, value in variables_raw.items():
            key = str(name)
            if not _NAME_RE.fullmatch(key):
                raise FormulaValidationError("invalid_variable_name")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FormulaValidationError("non_numeric_variable")
            number = float(value)
            if not math.isfinite(number) or abs(number) > self.policy.max_abs_input:
                raise FormulaValidationError("variable_out_of_bounds")
            variables[key] = number
        abs_tol = self._tolerance(raw.get("abs_tolerance"), self.policy.default_abs_tolerance)
        rel_tol = self._tolerance(raw.get("rel_tolerance"), self.policy.default_rel_tolerance)
        if rel_tol > 1.0:
            raise FormulaValidationError("relative_tolerance_out_of_bounds")
        try:
            tree = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError) as exc:
            raise FormulaValidationError("invalid_expression") from exc
        if sum(1 for _ in ast.walk(tree)) > self.policy.max_ast_nodes:
            raise FormulaValidationError("expression_too_complex")
        self._validate_node(tree.body, variables)
        return FormulaTask(task_id, expression, variables, abs_tol, rel_tol), tree

    @staticmethod
    def _tolerance(value: Any, default: float) -> float:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FormulaValidationError("invalid_tolerance")
        number = float(value)
        if not math.isfinite(number) or number < 0 or number > 1e6:
            raise FormulaValidationError("invalid_tolerance")
        return number

    def _validate_node(self, node: ast.AST, variables: Mapping[str, float]) -> None:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise FormulaValidationError("unsupported_syntax")
            number = float(node.value)
            if not math.isfinite(number) or abs(number) > self.policy.max_abs_input:
                raise FormulaValidationError("constant_out_of_bounds")
            return
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise FormulaValidationError("unknown_name")
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
            self._validate_node(node.operand, variables)
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINARY):
            self._validate_node(node.left, variables)
            self._validate_node(node.right, variables)
            if isinstance(node.op, ast.Pow):
                if not isinstance(node.right, ast.Constant):
                    raise FormulaValidationError("power_must_be_constant_integer")
                exponent = node.right.value
                if isinstance(exponent, bool) or not isinstance(exponent, int):
                    raise FormulaValidationError("power_must_be_constant_integer")
                if abs(exponent) > self.policy.max_power:
                    raise FormulaValidationError("power_out_of_bounds")
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in _ALLOWED_FUNCTIONS or node.keywords:
                raise FormulaValidationError("unsupported_syntax")
            if not node.args or len(node.args) > 8:
                raise FormulaValidationError("invalid_function_arguments")
            if name == "round" and len(node.args) not in {1, 2}:
                raise FormulaValidationError("invalid_function_arguments")
            if name == "round" and len(node.args) == 2:
                digits = node.args[1]
                if not isinstance(digits, ast.Constant) or isinstance(digits.value, bool) or not isinstance(digits.value, int):
                    raise FormulaValidationError("round_digits_must_be_integer")
                if abs(digits.value) > 12:
                    raise FormulaValidationError("round_digits_out_of_bounds")
            for arg in node.args:
                self._validate_node(arg, variables)
            return
        raise FormulaValidationError("unsupported_syntax")

    def render_r(self, node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return _float_literal(float(node.value))
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.UnaryOp):
            op = "+" if isinstance(node.op, ast.UAdd) else "-"
            return f"({op}{self.render_r(node.operand)})"
        if isinstance(node, ast.BinOp):
            op = {
                ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
                ast.Mod: "%%", ast.Pow: "^",
            }[type(node.op)]
            return f"({self.render_r(node.left)} {op} {self.render_r(node.right)})"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            rendered = [self.render_r(arg) for arg in node.args]
            if name == "round":
                return f"round({', '.join(rendered)})"
            return f"{name}({', '.join(rendered)})"
        raise FormulaValidationError("unsupported_syntax")


class DecimalMathBackend:
    """Independent mathematical implementation using Decimal arithmetic."""

    name = "independent_decimal_math"

    def __init__(self, policy: Optional[TripleImplementationPolicy] = None):
        self.policy = policy or TripleImplementationPolicy()

    def evaluate(self, tree: ast.Expression, variables: Mapping[str, float]) -> Dict[str, Any]:
        try:
            with localcontext() as ctx:
                ctx.prec = 50
                values = {key: Decimal(str(value)) for key, value in variables.items()}
                result = self._eval(tree.body, values)
            number = float(result)
            if not math.isfinite(number) or abs(number) > self.policy.max_abs_result:
                return {"backend": self.name, "ok": False, "error": "result_out_of_bounds"}
            return {"backend": self.name, "ok": True, "value": number, "precision_digits": 50}
        except ZeroDivisionError:
            return {"backend": self.name, "ok": False, "error": "division_by_zero"}
        except (InvalidOperation, ArithmeticError, ValueError):
            return {"backend": self.name, "ok": False, "error": "math_backend_error"}

    def _eval(self, node: ast.AST, values: Mapping[str, Decimal]) -> Decimal:
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.UnaryOp):
            value = self._eval(node.operand, values)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left, values), self._eval(node.right, values)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left ** int(node.right.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            args = [self._eval(arg, values) for arg in node.args]
            if name == "abs":
                return abs(args[0])
            if name == "min":
                return min(args)
            if name == "max":
                return max(args)
            if name == "sqrt":
                return args[0].sqrt()
            if name == "round":
                if len(args) == 1:
                    return args[0].quantize(Decimal("1"))
                digits = int(node.args[1].value)
                quantum = Decimal("1").scaleb(-digits)
                return args[0].quantize(quantum)
        raise ValueError("unsupported")


class RScriptFormulaBackend:
    """Real R backend; generated code only, no user-provided R source."""

    name = "rscript"

    def __init__(
        self,
        policy: Optional[TripleImplementationPolicy] = None,
        *,
        executable: Optional[str] = None,
        runner: Optional[Callable[..., Any]] = None,
    ):
        self.policy = policy or TripleImplementationPolicy()
        self.executable = executable if executable is not None else shutil.which("Rscript")
        self.runner = runner or subprocess.run

    def evaluate(self, task: FormulaTask, tree: ast.Expression, grammar: FormulaGrammar) -> Dict[str, Any]:
        if not self.executable:
            return {"backend": self.name, "ok": False, "available": False, "error": "rscript_not_found"}
        assignments = "; ".join(
            f"{key} <- {_float_literal(value)}" for key, value in sorted(task.variables.items())
        )
        expression = grammar.render_r(tree.body)
        script = (
            f"{assignments}; result <- {expression}; "
            "if (length(result) != 1 || !is.numeric(result) || !is.finite(result)) quit(status=23); "
            "cat(sprintf('%.17g', as.numeric(result)))"
        )
        env = self._minimal_env()
        try:
            completed = self.runner(
                [self.executable, "--vanilla", "-e", script],
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.policy.r_timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"backend": self.name, "ok": False, "available": True, "error": "rscript_timeout"}
        except (OSError, ValueError):
            return {"backend": self.name, "ok": False, "available": False, "error": "rscript_launch_failed"}
        if int(getattr(completed, "returncode", 1)) != 0:
            return {"backend": self.name, "ok": False, "available": True, "error": "rscript_nonzero_exit"}
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        if not _R_NUMBER_RE.fullmatch(stdout):
            return {"backend": self.name, "ok": False, "available": True, "error": "rscript_protocol_error"}
        try:
            value = float(stdout)
        except ValueError:
            return {"backend": self.name, "ok": False, "available": True, "error": "rscript_protocol_error"}
        if not math.isfinite(value) or abs(value) > self.policy.max_abs_result:
            return {"backend": self.name, "ok": False, "available": True, "error": "result_out_of_bounds"}
        return {
            "backend": self.name,
            "ok": True,
            "available": True,
            "value": value,
            "runtime_observed": True,
            "executable": os.path.basename(str(self.executable)),
        }

    @staticmethod
    def _minimal_env() -> Dict[str, str]:
        keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "LANG", "LC_ALL")
        env = {key: os.environ[key] for key in keep if os.environ.get(key)}
        env["R_DEFAULT_PACKAGES"] = "base"
        return env


class TripleIndependentImplementation:
    """Fail-closed coordinator for Python + R + independent math agreement."""

    schema_version = "1.0"

    def __init__(
        self,
        python_executor: Any,
        *,
        policy: Optional[TripleImplementationPolicy] = None,
        r_backend: Optional[RScriptFormulaBackend] = None,
        math_backend: Optional[DecimalMathBackend] = None,
    ):
        self.policy = policy or TripleImplementationPolicy()
        self.python_executor = python_executor
        self.grammar = FormulaGrammar(self.policy)
        self.r_backend = r_backend or RScriptFormulaBackend(self.policy)
        self.math_backend = math_backend or DecimalMathBackend(self.policy)

    def run(self, tasks: Sequence[Mapping[str, Any]] | None) -> Dict[str, Any]:
        raw_tasks = list(tasks or [])
        if not raw_tasks:
            return self._report("NO_TASKS", [], 0)
        if len(raw_tasks) > self.policy.max_tasks:
            return self._report(
                "INVALID_TASK_SET",
                [{"task_id": "*", "status": "INVALID_TASK", "verified": False,
                  "error": "too_many_tasks"}],
                len(raw_tasks),
            )
        results = [self._run_one(raw, index) for index, raw in enumerate(raw_tasks)]
        if any(row["status"] == "DISAGREEMENT" for row in results):
            status = "DISAGREEMENT"
        elif any(row["status"] in {"INCOMPLETE", "INVALID_TASK"} for row in results):
            status = "INCOMPLETE"
        elif results and all(row["status"] == "TRIPLE_AGREEMENT" for row in results):
            status = "TRIPLE_AGREEMENT"
        else:
            status = "INCOMPLETE"
        return self._report(status, results, len(raw_tasks))

    def run_from_verification(self, verification: Mapping[str, Any]) -> Dict[str, Any]:
        tasks = verification.get("triple_implementation_tasks") if isinstance(verification, Mapping) else None
        if tasks is None and isinstance(verification, Mapping):
            nested = verification.get("data_for_verification")
            if isinstance(nested, Mapping):
                tasks = nested.get("triple_implementation_tasks")
        if tasks is not None and not isinstance(tasks, Sequence):
            return self._report(
                "INVALID_TASK_SET",
                [{"task_id": "*", "status": "INVALID_TASK", "verified": False,
                  "error": "tasks_not_sequence"}],
                0,
            )
        return self.run(tasks or [])

    def _run_one(self, raw: Mapping[str, Any], index: int) -> Dict[str, Any]:
        try:
            task, tree = self.grammar.parse_task(raw, index)
        except FormulaValidationError as exc:
            return {
                "task_id": str(raw.get("task_id") if isinstance(raw, Mapping) else f"T{index + 1}"),
                "status": "INVALID_TASK",
                "verified": False,
                "error": _safe_error(str(exc), {
                    "task_not_mapping", "invalid_task_id", "empty_expression",
                    "expression_too_long", "variables_not_mapping", "too_many_variables",
                    "invalid_variable_name", "non_numeric_variable", "variable_out_of_bounds",
                    "invalid_tolerance", "relative_tolerance_out_of_bounds", "invalid_expression",
                    "expression_too_complex", "unsupported_syntax", "constant_out_of_bounds",
                    "unknown_name", "power_must_be_constant_integer", "power_out_of_bounds",
                    "invalid_function_arguments", "round_digits_must_be_integer",
                    "round_digits_out_of_bounds",
                }),
            }

        py = self._python(task)
        math_result = self.math_backend.evaluate(tree, task.variables)
        r = self.r_backend.evaluate(task, tree, self.grammar)
        implementations = [py, r, math_result]
        failed = [row for row in implementations if not row.get("ok")]
        if failed:
            return {
                "task_id": task.task_id,
                "status": "INCOMPLETE",
                "verified": False,
                "expression": task.expression,
                "implementations": implementations,
                "missing_or_failed_backends": [row.get("backend", "unknown") for row in failed],
                "pairwise_agreement": {},
                "note": "Teenon implementation successful bina computational agreement verify nahi hota.",
            }

        values = {str(row["backend"]): float(row["value"]) for row in implementations}
        pairs = {
            "python_vs_r": self._close(values["python_sandbox"], values["rscript"], task),
            "python_vs_math": self._close(values["python_sandbox"], values["independent_decimal_math"], task),
            "r_vs_math": self._close(values["rscript"], values["independent_decimal_math"], task),
        }
        agree = all(pairs.values())
        return {
            "task_id": task.task_id,
            "status": "TRIPLE_AGREEMENT" if agree else "DISAGREEMENT",
            "verified": agree,
            "expression": task.expression,
            "implementations": implementations,
            "pairwise_agreement": pairs,
            "abs_tolerance": task.abs_tolerance,
            "rel_tolerance": task.rel_tolerance,
            "note": (
                "Teen independent computation paths tolerance ke andar agree karte hain."
                if agree else
                "Kam se kam ek implementation pair disagree karta hai; majority vote se result promote nahi kiya gaya."
            ),
        }

    def _python(self, task: FormulaTask) -> Dict[str, Any]:
        try:
            raw = self.python_executor.evaluate(task.expression, task.variables)
        except Exception:
            return {"backend": "python_sandbox", "ok": False, "error": "python_backend_error"}
        if not isinstance(raw, Mapping) or not raw.get("ok"):
            return {
                "backend": "python_sandbox",
                "ok": False,
                "error": _safe_error(
                    raw.get("error") if isinstance(raw, Mapping) else "backend_error",
                    {"empty_expression", "expression_too_long", "too_many_variables",
                     "invalid_variable_name", "non_numeric_variable", "variable_out_of_bounds",
                     "invalid_expression", "expression_too_complex", "division_by_zero",
                     "unknown_name", "unsupported_syntax", "result_out_of_bounds",
                     "power_out_of_bounds", "invalid_function_arguments", "numeric_error"},
                ),
            }
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            return {"backend": "python_sandbox", "ok": False, "error": "python_protocol_error"}
        if not math.isfinite(value) or abs(value) > self.policy.max_abs_result:
            return {"backend": "python_sandbox", "ok": False, "error": "result_out_of_bounds"}
        return {"backend": "python_sandbox", "ok": True, "value": value}

    @staticmethod
    def _close(left: float, right: float, task: FormulaTask) -> bool:
        return math.isclose(left, right, rel_tol=task.rel_tolerance, abs_tol=task.abs_tolerance)

    def _report(self, status: str, results: Sequence[Mapping[str, Any]], requested: int) -> Dict[str, Any]:
        agreed = sum(1 for row in results if row.get("status") == "TRIPLE_AGREEMENT")
        executed_r = any(
            any(impl.get("backend") == "rscript" and impl.get("runtime_observed")
                for impl in row.get("implementations", []))
            for row in results
        )
        return {
            "schema_version": self.schema_version,
            "capability_id": 40,
            "capability": "Triple Independent Implementation",
            "status": status,
            "tasks_requested": requested,
            "tasks_triple_agreed": agreed,
            "all_requested_tasks_agree": bool(results) and agreed == len(results) and status == "TRIPLE_AGREEMENT",
            "results": list(results),
            "independence": {
                "python": "existing bounded Python numeric sandbox",
                "r": "real Rscript process with engine-generated allow-listed code",
                "mathematical": "Decimal evaluator with separate arithmetic implementation",
                "shared_component": "task grammar/allow-list validation is shared; computational engines are separate",
            },
            "safety": {
                "arbitrary_python": False,
                "arbitrary_r": False,
                "shell": False,
                "network_required": False,
                "r_runtime_required_for_full_triple_check": True,
            },
            "maturity_proof": {
                "production_module": True,
                "fail_closed_contract": True,
                "real_r_runtime_observed_this_run": executed_r,
                "hardware_validation": False,
                "live_independent_validation": False,
                "max_or_verified_real_world_claim": False,
            },
            "note": (
                "TRIPLE_AGREEMENT sirf numeric implementation-consistency hai; scientific truth, hardware validation, ya real-world success ka proof nahi."
            ),
        }


__all__ = [
    "DecimalMathBackend",
    "FormulaGrammar",
    "FormulaTask",
    "FormulaValidationError",
    "RScriptFormulaBackend",
    "TripleImplementationPolicy",
    "TripleIndependentImplementation",
]
