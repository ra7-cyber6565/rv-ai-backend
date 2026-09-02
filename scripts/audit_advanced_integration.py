"""Fail-closed static audit for advanced discovery integration wiring.

The normal architecture audit protects the broad API/research/storage/security
pipeline.  This companion gate focuses on the newer advanced-discovery bridge so
an apparently harmless refactor cannot leave #40/#103 implemented in isolated
files but disconnected from the production path.

It performs no network/model/runtime-provider call.  Passing this audit proves
only that required code/safety wiring is present; it is not scientific or live
runtime validation.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Report:
    schema_version: int
    passed: bool
    checks: list[dict]
    failed: list[str]


def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _required(paths: Iterable[str]) -> Check:
    missing = [path for path in paths if not (ROOT / path).is_file()]
    return Check(
        "advanced:required-files",
        not missing,
        "all advanced integration files present" if not missing else "missing: " + ", ".join(missing),
    )


def _contains(name: str, path: str, needles: Sequence[str]) -> Check:
    text = _read(path)
    missing = [needle for needle in needles if needle not in text]
    return Check(
        name,
        bool(text) and not missing,
        "required invariant(s) present" if text and not missing else "missing: " + ", ".join(missing or ["file unreadable"]),
    )


def _package_wiring() -> Check:
    return _contains(
        "advanced:production-package-patch",
        "research_engine/__init__.py",
        (
            "from . import advanced_discovery as _advanced_discovery",
            "from .advanced_discovery_integrated import (",
            "IntegratedScientificDiscoveryEngine as _IntegratedScientificDiscoveryEngine",
            "_advanced_discovery.ScientificDiscoveryEngine = _IntegratedScientificDiscoveryEngine",
        ),
    )


def _extension_wiring() -> Check:
    return _contains(
        "advanced:integrated-engine-extensions",
        "research_engine/advanced_discovery_integrated.py",
        (
            "class IntegratedScientificDiscoveryEngine(_BaseScientificDiscoveryEngine)",
            "derive_triple_tasks(verification",
            "run_adapted_triple(self.triple_implementation, adaptation)",
            "self.literature_debate.reconstruct(",
            'report["triple_independent_implementation"] = triple',
            'report["autonomous_literature_debate"] = debate',
            '"base_discovery_preserved": True',
            '"expected_value_gate_wired": True',
            '"status": "ASSESSMENT_ERROR"',
        ),
    )


def _verification_bridge() -> Check:
    return _contains(
        "advanced:verification-to-triple-bridge",
        "research_engine/verification.py",
        (
            "base_check_rows = [check.to_dict() for check in list(base.checks or [])]",
            'derive_triple_tasks({"checks": base_check_rows})',
            "triple_implementation_tasks: List[Dict]",
            "triple_task_adapter: Dict",
            'data["triple_implementation_tasks"]',
            'data["triple_task_adapter"]',
        ),
    )


def _triple_safety() -> Check:
    return _contains(
        "advanced:triple-computation-safety",
        "research_engine/triple_implementation.py",
        (
            "class FormulaGrammar",
            "max_expression_chars: int = 240",
            "max_ast_nodes: int = 80",
            "max_variables: int = 24",
            "r_timeout_seconds: float = 4.0",
            "[self.executable, \"--vanilla\", \"-e\", script]",
            "shell=False",
            'env["R_DEFAULT_PACKAGES"] = "base"',
            "_R_NUMBER_RE.fullmatch(stdout)",
            '"python_vs_r"',
            '"python_vs_math"',
            '"r_vs_math"',
            '"arbitrary_python": False',
            '"arbitrary_r": False',
            '"max_or_verified_real_world_claim": False',
        ),
    )


def _expected_value_gate() -> Check:
    return _contains(
        "advanced:claimed-value-gate",
        "research_engine/triple_task_adapter.py",
        (
            '"expected_value": claimed',
            "math.isclose(",
            "len(backend_checks) == 3 and all(backend_checks.values())",
            'row["status"] = "CLAIM_MISMATCH"',
            'report["all_expected_values_match"]',
            'report["all_requested_tasks_agree"] = False',
        ),
    )


def _literature_grounding() -> Check:
    return _contains(
        "advanced:literature-debate-grounding",
        "research_engine/literature_debate.py",
        (
            "looks_instruction_like(sentence)",
            "source.independence_key",
            '"reason": "rejected_or_off_domain"',
            '"reason": "duplicate_or_same_independent_origin"',
            'return f"{sid}" + (f" — {title}" if title else ""), "source_fallback"',
            "reliable_current_evidence=not retracted",
            '"systematic_review_completeness_proven": False',
            '"live_independent_validation_proven": False',
            '"max_or_verified_real_world_claim": False',
        ),
    )


def _maturity_honesty() -> Check:
    text = _read("research_engine/capability_maturity.py")
    required = (
        '"current_full_gate_execution_proven": False',
        '"real_r_runtime_execution_proven": False',
        '"live_independent_validation_proven": False',
        '"systematic_review_completeness_proven": False',
        '"claim_ceiling": "IMPLEMENTED_PENDING_EXECUTION_PROOF"',
        '"100/100 or max maturity without executed evidence"',
    )
    missing = [needle for needle in required if needle not in text]
    unsafe = (
        '"current_full_gate_execution_proven": True',
        '"live_independent_validation_proven": True',
        '"systematic_review_completeness_proven": True',
    )
    promoted = [needle for needle in unsafe if needle in text]
    return Check(
        "advanced:maturity-proof-fails-closed",
        bool(text) and not missing and not promoted,
        (
            "repository implementation is not confused with live/scientific proof"
            if text and not missing and not promoted
            else f"missing={missing}; unsafe_promotions={promoted}"
        ),
    )


def run_audit() -> Report:
    required_files = (
        "research_engine/advanced_discovery_integrated.py",
        "research_engine/triple_implementation.py",
        "research_engine/triple_task_adapter.py",
        "research_engine/literature_debate.py",
        "research_engine/capability_maturity.py",
        "research_engine/verification.py",
        "tests/test_advanced_discovery_extensions.py",
        "tests/test_capability_maturity.py",
        "tests/test_literature_debate.py",
        "tests/test_triple_implementation.py",
        "tests/test_triple_task_adapter.py",
        "tests/test_triple_verification_bridge.py",
    )
    checks = [
        _required(required_files),
        _package_wiring(),
        _extension_wiring(),
        _verification_bridge(),
        _triple_safety(),
        _expected_value_gate(),
        _literature_grounding(),
        _maturity_honesty(),
    ]
    failed = [check.name for check in checks if not check.passed]
    return Report(
        schema_version=1,
        passed=not failed,
        checks=[asdict(check) for check in checks],
        failed=failed,
    )


def _write(path: Path, report: Report) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit advanced-discovery production wiring and honesty invariants.")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)
    report = run_audit()
    for row in report.checks:
        print(f"[{'PASS' if row['passed'] else 'FAIL'}] {row['name']}: {row['detail']}")
    if args.json_path:
        _write(Path(args.json_path).expanduser().resolve(), report)
    print("ADVANCED INTEGRATION AUDIT: " + ("PASS" if report.passed else "FAIL"))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
