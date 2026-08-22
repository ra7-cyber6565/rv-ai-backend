"""Fail the release gate if production code bypasses the resilient AI router.

Why this matters: a perfect fallback/zero-cost router is useless if one legacy
endpoint calls a provider SDK directly. QUICK chat and the old RAG helper once
did exactly that.

Only these adapter modules may execute provider surfaces directly:
- research_engine/gemini_reasoning.py
- research_engine/gemini_model.py
- research_engine/reasoning_router.py

Everything else must use the resilient facade/manager. The scan is AST-based so
comments/docstrings that merely discuss old provider code do not create false
positives. No network/API key is used.
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


ROOT = Path(__file__).resolve().parents[1]

ALLOWLIST = {
    "research_engine/gemini_reasoning.py",
    "research_engine/gemini_model.py",
    "research_engine/reasoning_router.py",
}

PRODUCTION_ROOTS = (
    "api", "agents", "rag", "research_engine", "utils", "storage", "knowledge",
)

_ENDPOINT_MARKERS = {
    "groq_endpoint": "api.groq.com/openai/",
    "openrouter_endpoint": "openrouter.ai/api/",
    "ollama_chat_endpoint": "/api/chat",
}


@dataclass(frozen=True)
class BypassHit:
    path: str
    marker: str
    line: int


@dataclass(frozen=True)
class BypassReport:
    schema_version: int
    passed: bool
    scanned_files: int
    parse_failures: list[str]
    allowlist: list[str]
    hits: list[dict]


def _production_files(root: Path = ROOT) -> Iterable[Path]:
    seen = set()
    for folder in PRODUCTION_ROOTS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path
    main = root / "main.py"
    if main.is_file() and main not in seen:
        yield main


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Return ids of literal nodes used only as module/class/function docstrings."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            ids.add(id(first.value))
    return ids


def _hits_for_tree(rel: str, tree: ast.AST) -> List[BypassHit]:
    hits: List[BypassHit] = []
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        line = int(getattr(node, "lineno", 0) or 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "google.generativeai" or alias.name.startswith("google.generativeai."):
                    hits.append(BypassHit(rel, "google_sdk_import", line))
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if module == "google.generativeai" or module.startswith("google.generativeai."):
                hits.append(BypassHit(rel, "google_sdk_import", line))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "generate_content":
                hits.append(BypassHit(rel, "gemini_generate", line))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            value = node.value
            for marker_name, marker in _ENDPOINT_MARKERS.items():
                if marker in value:
                    hits.append(BypassHit(rel, marker_name, line))
    # De-duplicate multiple AST views of the same surface.
    unique = {(h.path, h.marker, h.line): h for h in hits}
    return list(unique.values())


def scan(root: Path = ROOT) -> BypassReport:
    hits: List[BypassHit] = []
    parse_failures: List[str] = []
    count = 0
    for path in sorted(_production_files(root), key=lambda p: p.as_posix()):
        count += 1
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=rel)
        except Exception as exc:
            parse_failures.append(f"{rel}: {type(exc).__name__}")
            continue
        hits.extend(_hits_for_tree(rel, tree))

    hits.sort(key=lambda h: (h.path, h.line, h.marker))
    # A production file that cannot be parsed is fail-closed here too. Compileall
    # will provide the detailed syntax error in the preceding release-gate stage.
    passed = not hits and not parse_failures
    return BypassReport(
        schema_version=2,
        passed=passed,
        scanned_files=count,
        parse_failures=parse_failures,
        allowlist=sorted(ALLOWLIST),
        hits=[asdict(hit) for hit in hits],
    )


def write_report(path: Path, report: BypassReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect production code bypassing the resilient AI router.")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)

    report = scan(ROOT)
    if report.passed:
        print(f"PROVIDER BYPASS AUDIT: PASS ({report.scanned_files} production Python files scanned)")
    else:
        print("PROVIDER BYPASS AUDIT: FAIL")
        for failure in report.parse_failures:
            print(f"- parse failure: {failure}")
        for hit in report.hits:
            print(f"- {hit['path']}:{hit['line']} -> {hit['marker']}")
    if args.json_path:
        target = Path(args.json_path).expanduser().resolve()
        write_report(target, report)
        print(f"Report: {target}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
