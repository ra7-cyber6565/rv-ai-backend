"""Static audit for untrusted research-source boundaries.

Unit tests prove individual helpers. This audit proves the helpers are still
wired into the *production path*: retrieved/uploaded content must be rendered as
untrusted evidence before any reasoning model sees it, and source-controlled
metadata must not become an unsafe browser link/report structure.

Pure Python, offline, ₹0. Exit 1 on any missing invariant.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _require(path: str, *needles: str) -> Check:
    text = _read(path)
    missing = [needle for needle in needles if needle not in text]
    return Check(
        name=path,
        passed=bool(text) and not missing,
        detail="ok" if text and not missing else "missing: " + ", ".join(missing or ["file"]),
    )


def run() -> List[Check]:
    files = (
        "research_engine/source_prompt_guard.py",
        "research_engine/synthesizer.py",
        "utils/body_limit.py",
        "tests/test_source_prompt_guard.py",
        "tests/test_source_output_safety.py",
        "tests/test_web_source_link_safety.py",
        "tests/test_body_limit.py",
        "tests/benchmark_cross_domain.py",
    )
    missing_files = [path for path in files if not (ROOT / path).is_file()]
    checks: List[Check] = [Check(
        "required-source-boundary-files",
        not missing_files,
        "all present" if not missing_files else "missing: " + ", ".join(missing_files),
    )]

    checks.extend([
        _require(
            "research_engine/__init__.py",
            "source_prompt_guard",
            "_install_source_prompt_guard()",
        ),
        _require(
            "research_engine/source_prompt_guard.py",
            "BEGIN_UNTRUSTED_SOURCES",
            "END_UNTRUSTED_SOURCES",
            "POTENTIAL-INJECTION-DATA>",
            "_safe_source_id",
            "EvidencePack.to_prompt_block = guarded_prompt_block",
        ),
        _require(
            "research_engine/synthesizer.py",
            "_safe_source_display",
            "_safe_source_url",
            "parsed.scheme.lower() not in {\"http\", \"https\"}",
        ),
        _require(
            "web/index.html",
            "function safeHttpUrl",
            'u.protocol===\"http:\"||u.protocol===\"https:\"',
            "href=safeHttpUrl(s.url)",
            "function htmlText(s){return esc(s)",
        ),
        _require(
            "main.py",
            "RequestBodyLimitMiddleware",
            "app.add_middleware(RequestBodyLimitMiddleware)",
            "Content-Security-Policy",
            "Permissions-Policy",
            "Cross-Origin-Opener-Policy",
        ),
        _require(
            "scripts/run_foundation_gate.py",
            "test_source_prompt_guard.py",
            "test_source_output_safety.py",
            "test_web_source_link_safety.py",
            "test_body_limit.py",
            "benchmark_cross_domain",
        ),
    ])
    return checks


def main() -> int:
    checks = run()
    failed = [row.name for row in checks if not row.passed]
    for row in checks:
        print(f"[{'PASS' if row.passed else 'FAIL'}] {row.name}: {row.detail}")
    print("SOURCE BOUNDARY AUDIT: " + ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
