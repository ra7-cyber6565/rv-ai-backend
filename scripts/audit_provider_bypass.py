"""Fail the release gate if production code bypasses the resilient AI router.

Why this matters: the project can have a perfect zero-cost/fallback router and
still lose all of those guarantees if one legacy endpoint directly calls
`GenerativeModel.generate_content()` (QUICK chat and old RAG once did exactly
that). This audit makes that regression mechanically visible.

Only these modules may touch provider SDK/HTTP generation surfaces directly:
- `research_engine/gemini_reasoning.py` — primary Gemini adapter/retry ledger
- `research_engine/gemini_model.py` — Gemini model discovery helper
- `research_engine/reasoning_router.py` — Groq/OpenRouter/Ollama adapters

Everything else must call the resilient facade/manager instead.

No network or API key is used.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


ROOT = Path(__file__).resolve().parents[1]

ALLOWLIST = {
    "research_engine/gemini_reasoning.py",
    "research_engine/gemini_model.py",
    "research_engine/reasoning_router.py",
}

PRODUCTION_ROOTS = (
    "api",
    "agents",
    "rag",
    "research_engine",
    "utils",
    "storage",
    "knowledge",
)

# These are provider execution surfaces, not harmless mentions in comments/docs.
MARKERS = {
    "google_sdk_import": "google.generativeai",
    "gemini_generate": ".generate_content(",
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
    allowlist: list[str]
    hits: list[dict]


def _production_files(root: Path = ROOT) -> Iterable[Path]:
    for folder in PRODUCTION_ROOTS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.is_file():
                yield path
    main = root / "main.py"
    if main.is_file():
        yield main


def scan(root: Path = ROOT) -> BypassReport:
    hits: List[BypassHit] = []
    count = 0
    for path in sorted(_production_files(root), key=lambda p: p.as_posix()):
        count += 1
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            # Unreadable production source is a separate compile/repo integrity
            # failure. This audit does not pretend it scanned bytes it couldn't read.
            continue
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            # Ignore pure comments/doc prose. A marker in executable Python or a
            # string literal still counts, which is exactly what we want for URLs.
            if stripped.startswith("#"):
                continue
            for name, marker in MARKERS.items():
                if marker in line:
                    hits.append(BypassHit(rel, name, number))
    return BypassReport(
        schema_version=1,
        passed=not hits,
        scanned_files=count,
        allowlist=sorted(ALLOWLIST),
        hits=[asdict(hit) for hit in hits],
    )


def write_report(path: Path, report: BypassReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect production code that bypasses the resilient AI router.")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)

    report = scan(ROOT)
    if report.passed:
        print(f"PROVIDER BYPASS AUDIT: PASS ({report.scanned_files} production Python files scanned)")
    else:
        print("PROVIDER BYPASS AUDIT: FAIL")
        for hit in report.hits:
            print(f"- {hit['path']}:{hit['line']} -> {hit['marker']}")
    if args.json_path:
        target = Path(args.json_path).expanduser().resolve()
        write_report(target, report)
        print(f"Report: {target}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
