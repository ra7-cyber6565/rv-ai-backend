"""Bounded interpreter for model-generated numeric experiment snippets.

This module deliberately does *not* call Python ``exec`` or ``eval``.  It
interprets a small Python-like AST with explicit operation, loop, collection,
number and output budgets.  There are no import, attribute, filesystem,
network, subprocess, reflection or dynamic-code primitives.

It is useful for deterministic numeric experiments produced by the research
engine.  It is not advertised as a general Python runtime or an OS/container
security boundary; hostile native binaries still require a separate process /
container isolation layer and an independent safety review.
"""
from __future__ import annotations

import ast
import hashlib
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping


class SandboxViolation(ValueError):
    """The program requested a construct outside the allowed language."""


class SandboxLimitExceeded(RuntimeError):
    """A deterministic resource budget was exceeded."""


@dataclass(frozen=True)
class SandboxPolicy:
    max_source_chars: int = 12_000
    max_ast_nodes: int = 1_500
    max_operations: int = 50_000
    max_loop_iterations: int = 10_000
    max_variables: int = 128
    max_collection_items: int = 4_096
    max_output_chars: int = 16_000
    max_abs_number: float = 1e100
    max_exponent: float = 1_000.0


@dataclass(frozen=True)
class SandboxResult:
    code_sha256: str
    outputs: Mapping[str, Any]
    stdout: str
    operations: int
    deterministic: bool
    network_allowed: bool
    filesystem_allowed: bool
    subprocess_allowed: bool


class _Range:
    __slots__ = ("start", "stop", "step")

    def __init__(self, *args: Any):
        if not 1 <= len(args) <= 3:
            raise SandboxViolation("range expects 1..3 arguments")
        values = [
            int(value)
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and int(value) == value
            else None
            for value in args
        ]
        if any(value is None for value in values):
            raise SandboxViolation("range arguments must be integers")
        if len(values) == 1:
            start, stop, step = 0, values[0], 1
        elif len(values) == 2:
            start, stop, step = values[0], values[1], 1
        else:
            start, stop, step = values
        if step == 0:
            raise SandboxViolation("range step cannot be zero")
        self.start, self.stop, self.step = start, stop, step

    def __iter__(self):
        return iter(range(self.start, self.stop, self.step))

    def __len__(self) -> int:
        return len(range(self.start, self.stop, self.step))


class NumericCodeSandbox:
    """Execute the constrained numeric language without Python exec/eval."""

    _RESERVED_NAMES = {
        "eval", "exec", "open", "compile", "globals", "locals", "vars",
        "__import__", "getattr", "setattr", "delattr", "input", "help",
        "breakpoint",
    }

    def __init__(self, policy: SandboxPolicy | None = None):
        self.policy = policy or SandboxPolicy()
        self._ops = 0
        self._loop_iterations = 0
        self._env: Dict[str, Any] = {}
        self._stdout: list[str] = []

    def run(
        self,
        source: str,
        inputs: Mapping[str, Any] | None = None,
    ) -> SandboxResult:
        text = str(source or "")
        if not text.strip():
            raise SandboxViolation("source is empty")
        if len(text) > self.policy.max_source_chars:
            raise SandboxLimitExceeded("source too large")
        try:
            tree = ast.parse(text, mode="exec")
        except SyntaxError as exc:
            raise SandboxViolation(f"syntax error: {exc.msg}") from exc
        if len(list(ast.walk(tree))) > self.policy.max_ast_nodes:
            raise SandboxLimitExceeded("AST too large")

        self._ops = 0
        self._loop_iterations = 0
        self._stdout = []
        self._env = {}
        for key, value in dict(inputs or {}).items():
            self._validate_name(key)
            self._env[key] = self._clean_value(value)
        for statement in tree.body:
            self._statement(statement)

        outputs = {
            key: self._copy_value(value)
            for key, value in self._env.items()
            if not key.startswith("_")
        }
        return SandboxResult(
            code_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            outputs=outputs,
            stdout="\n".join(self._stdout),
            operations=self._ops,
            deterministic=True,
            network_allowed=False,
            filesystem_allowed=False,
            subprocess_allowed=False,
        )

    def _tick(self, count: int = 1) -> None:
        self._ops += count
        if self._ops > self.policy.max_operations:
            raise SandboxLimitExceeded("operation budget exceeded")

    def _validate_name(self, name: str) -> None:
        if (
            not isinstance(name, str)
            or not name.isidentifier()
            or name.startswith("_")
        ):
            raise SandboxViolation("unsafe variable name")
        if name in self._RESERVED_NAMES:
            raise SandboxViolation("reserved variable name")

    def _clean_number(self, value: Any) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SandboxViolation("numeric value required")
        if isinstance(value, float) and not math.isfinite(value):
            raise SandboxViolation("non-finite numbers are forbidden")
        if abs(value) > self.policy.max_abs_number:
            raise SandboxLimitExceeded("numeric magnitude exceeded")
        return value

    def _clean_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return self._clean_number(value)
            if isinstance(value, str) and len(value) > self.policy.max_output_chars:
                raise SandboxLimitExceeded("string too large")
            return value
        if isinstance(value, (list, tuple)):
            if len(value) > self.policy.max_collection_items:
                raise SandboxLimitExceeded("collection too large")
            cleaned = [self._clean_value(item) for item in value]
            return cleaned if isinstance(value, list) else tuple(cleaned)
        if isinstance(value, dict):
            if len(value) > self.policy.max_collection_items:
                raise SandboxLimitExceeded("collection too large")
            cleaned: Dict[Any, Any] = {}
            for key, item in value.items():
                if not isinstance(key, (str, int, float, bool)):
                    raise SandboxViolation("unsafe mapping key")
                cleaned[self._clean_value(key)] = self._clean_value(item)
            return cleaned
        raise SandboxViolation(f"unsupported value type: {type(value).__name__}")

    def _copy_value(self, value: Any) -> Any:
        return self._clean_value(value)

    def _statement(self, node: ast.stmt) -> None:
        self._tick()
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise SandboxViolation("only simple assignments are allowed")
            name = node.targets[0].id
            self._validate_name(name)
            self._env[name] = self._clean_value(self._expression(node.value))
            if len(self._env) > self.policy.max_variables:
                raise SandboxLimitExceeded("too many variables")
            return

        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise SandboxViolation("only simple augmented assignment allowed")
            name = node.target.id
            self._validate_name(name)
            if name not in self._env:
                raise SandboxViolation(f"unknown variable: {name}")
            self._env[name] = self._clean_value(
                self._binary(node.op, self._env[name], self._expression(node.value))
            )
            return

        if isinstance(node, ast.Expr):
            self._expression(node.value)
            return

        if isinstance(node, ast.If):
            branch = node.body if self._truth(self._expression(node.test)) else node.orelse
            for child in branch:
                self._statement(child)
            return

        if isinstance(node, ast.For):
            if not isinstance(node.target, ast.Name):
                raise SandboxViolation("for target must be a name")
            self._validate_name(node.target.id)
            iterable = self._expression(node.iter)
            if not isinstance(iterable, (_Range, list, tuple)):
                raise SandboxViolation("for loop iterable must be range/list/tuple")
            length = len(iterable)
            self._loop_iterations += length
            if self._loop_iterations > self.policy.max_loop_iterations:
                raise SandboxLimitExceeded("loop budget exceeded")
            for item in iterable:
                self._env[node.target.id] = self._clean_value(item)
                for child in node.body:
                    self._statement(child)
            for child in node.orelse:
                self._statement(child)
            return

        if isinstance(node, ast.Pass):
            return
        raise SandboxViolation(f"statement not allowed: {type(node).__name__}")

    def _expression(self, node: ast.expr) -> Any:
        self._tick()
        if isinstance(node, ast.Constant):
            return self._clean_value(node.value)
        if isinstance(node, ast.Name):
            if node.id in self._env:
                return self._env[node.id]
            raise SandboxViolation(f"unknown name: {node.id}")
        if isinstance(node, ast.BinOp):
            return self._clean_value(
                self._binary(
                    node.op,
                    self._expression(node.left),
                    self._expression(node.right),
                )
            )
        if isinstance(node, ast.UnaryOp):
            value = self._expression(node.operand)
            if isinstance(node.op, ast.UAdd):
                return self._clean_number(+self._number(value))
            if isinstance(node.op, ast.USub):
                return self._clean_number(-self._number(value))
            if isinstance(node.op, ast.Not):
                return not self._truth(value)
            raise SandboxViolation("unary operator not allowed")
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result: Any = True
                for item in node.values:
                    result = self._expression(item)
                    if not self._truth(result):
                        return result
                return result
            if isinstance(node.op, ast.Or):
                result = False
                for item in node.values:
                    result = self._expression(item)
                    if self._truth(result):
                        return result
                return result
            raise SandboxViolation("boolean operator not allowed")
        if isinstance(node, ast.Compare):
            left = self._expression(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._expression(comparator)
                if not self._compare(operator, left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self._expression(
                node.body if self._truth(self._expression(node.test)) else node.orelse
            )
        if isinstance(node, ast.List):
            return self._clean_value([self._expression(item) for item in node.elts])
        if isinstance(node, ast.Tuple):
            return self._clean_value(tuple(self._expression(item) for item in node.elts))
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise SandboxViolation("dictionary unpacking is not allowed")
            return self._clean_value({
                self._expression(key): self._expression(value)
                for key, value in zip(node.keys, node.values)
            })
        if isinstance(node, ast.Subscript):
            target = self._expression(node.value)
            if not isinstance(target, (list, tuple, dict, str)):
                raise SandboxViolation("subscript target not allowed")
            index = self._expression(node.slice)
            try:
                return self._clean_value(target[index])
            except (KeyError, IndexError, TypeError) as exc:
                raise SandboxViolation("invalid subscript") from exc
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise SandboxViolation("only direct calls to safe functions allowed")
            if node.keywords:
                raise SandboxViolation("keyword arguments are not allowed")
            return self._call(
                node.func.id,
                [self._expression(argument) for argument in node.args],
            )
        raise SandboxViolation(f"expression not allowed: {type(node).__name__}")

    def _number(self, value: Any) -> int | float:
        return self._clean_number(value)

    def _binary(self, operator: ast.operator, left: Any, right: Any) -> Any:
        if isinstance(operator, ast.Add):
            if (
                isinstance(left, (int, float)) and not isinstance(left, bool)
                and isinstance(right, (int, float)) and not isinstance(right, bool)
            ):
                return self._clean_number(left + right)
            if isinstance(left, str) and isinstance(right, str):
                result = left + right
                if len(result) > self.policy.max_output_chars:
                    raise SandboxLimitExceeded("string too large")
                return result
            if isinstance(left, list) and isinstance(right, list):
                if len(left) + len(right) > self.policy.max_collection_items:
                    raise SandboxLimitExceeded("collection too large")
                return left + right
            raise SandboxViolation("unsupported + operands")

        x, y = self._number(left), self._number(right)
        if isinstance(operator, ast.Sub):
            return self._clean_number(x - y)
        if isinstance(operator, ast.Mult):
            return self._clean_number(x * y)
        if isinstance(operator, ast.Div):
            if y == 0:
                raise SandboxViolation("division by zero")
            return self._clean_number(x / y)
        if isinstance(operator, ast.FloorDiv):
            if y == 0:
                raise SandboxViolation("division by zero")
            return self._clean_number(x // y)
        if isinstance(operator, ast.Mod):
            if y == 0:
                raise SandboxViolation("modulo by zero")
            return self._clean_number(x % y)
        if isinstance(operator, ast.Pow):
            if abs(y) > self.policy.max_exponent:
                raise SandboxLimitExceeded("exponent too large")
            try:
                result = x ** y
            except (OverflowError, ValueError) as exc:
                raise SandboxViolation("invalid power") from exc
            if isinstance(result, complex):
                raise SandboxViolation("complex numbers forbidden")
            return self._clean_number(result)
        raise SandboxViolation("binary operator not allowed")

    def _compare(self, operator: ast.cmpop, left: Any, right: Any) -> bool:
        try:
            if isinstance(operator, ast.Eq):
                return left == right
            if isinstance(operator, ast.NotEq):
                return left != right
            if isinstance(operator, ast.Lt):
                return left < right
            if isinstance(operator, ast.LtE):
                return left <= right
            if isinstance(operator, ast.Gt):
                return left > right
            if isinstance(operator, ast.GtE):
                return left >= right
        except TypeError as exc:
            raise SandboxViolation("incompatible comparison") from exc
        raise SandboxViolation("comparison operator not allowed")

    @staticmethod
    def _truth(value: Any) -> bool:
        if isinstance(value, (bool, int, float, str, list, tuple, dict)) or value is None:
            return bool(value)
        raise SandboxViolation("value cannot be used as condition")

    def _call(self, name: str, arguments: list[Any]) -> Any:
        self._tick()
        if name == "range":
            result = _Range(*arguments)
            if len(result) > self.policy.max_loop_iterations:
                raise SandboxLimitExceeded("range too large")
            return result
        if name == "print":
            text = " ".join(str(self._clean_value(value)) for value in arguments)
            current_size = sum(len(line) + 1 for line in self._stdout) + len(text)
            if current_size > self.policy.max_output_chars:
                raise SandboxLimitExceeded("output budget exceeded")
            self._stdout.append(text)
            return None
        if name == "abs":
            if len(arguments) != 1:
                raise SandboxViolation("abs expects one argument")
            return self._clean_number(abs(self._number(arguments[0])))
        if name in {"min", "max"}:
            if not arguments:
                raise SandboxViolation(f"{name} expects arguments")
            values = (
                arguments[0]
                if len(arguments) == 1 and isinstance(arguments[0], (list, tuple))
                else arguments
            )
            if not values:
                raise SandboxViolation(f"{name} empty sequence")
            numbers = [self._number(value) for value in values]
            return self._clean_number(min(numbers) if name == "min" else max(numbers))
        if name == "sum":
            if len(arguments) != 1 or not isinstance(arguments[0], (list, tuple)):
                raise SandboxViolation("sum expects one list/tuple")
            return self._clean_number(sum(self._number(value) for value in arguments[0]))
        if name == "len":
            if len(arguments) != 1 or not isinstance(arguments[0], (list, tuple, dict, str)):
                raise SandboxViolation("len expects a collection")
            return len(arguments[0])
        if name == "round":
            if not 1 <= len(arguments) <= 2:
                raise SandboxViolation("round expects 1..2 arguments")
            value = self._number(arguments[0])
            digits = int(self._number(arguments[1])) if len(arguments) == 2 else 0
            if abs(digits) > 20:
                raise SandboxLimitExceeded("round precision too large")
            return self._clean_number(round(value, digits))

        math_functions = {
            "sqrt": math.sqrt,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "floor": math.floor,
            "ceil": math.ceil,
        }
        if name in math_functions:
            if len(arguments) != 1:
                raise SandboxViolation(f"{name} expects one argument")
            try:
                result = math_functions[name](self._number(arguments[0]))
            except (ValueError, OverflowError) as exc:
                raise SandboxViolation(f"invalid {name} domain") from exc
            return self._clean_number(result)
        if name == "isfinite":
            if len(arguments) != 1:
                raise SandboxViolation("isfinite expects one argument")
            return (
                isinstance(arguments[0], (int, float))
                and not isinstance(arguments[0], bool)
                and math.isfinite(arguments[0])
            )
        raise SandboxViolation(f"function not allowed: {name}")
