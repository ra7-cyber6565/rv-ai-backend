"""Release-gate regressions for the advanced-discovery production bridge.

These tests are deliberately static/offline.  They complement behavioural tests
by catching wiring removal, unsafe R execution changes, or maturity overclaims.
"""
from __future__ import annotations

from pathlib import Path

from scripts import audit_advanced_integration as audit


def test_real_advanced_integration_audit_passes():
    report = audit.run_audit()
    assert report.passed is True, report.failed
    names = {row["name"] for row in report.checks}
    assert {
        "advanced:required-files",
        "advanced:production-package-patch",
        "advanced:integrated-engine-extensions",
        "advanced:verification-to-triple-bridge",
        "advanced:triple-computation-safety",
        "advanced:claimed-value-gate",
        "advanced:literature-debate-grounding",
        "advanced:maturity-proof-fails-closed",
    } <= names


def test_package_wiring_gate_fails_if_integrated_engine_is_not_installed(monkeypatch, tmp_path):
    target = tmp_path / "research_engine"
    target.mkdir()
    (target / "__init__.py").write_text(
        "from .advanced_discovery_integrated import IntegratedScientificDiscoveryEngine\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._package_wiring()
    assert result.passed is False
    assert "_advanced_discovery.ScientificDiscoveryEngine" in result.detail


def test_triple_safety_gate_fails_if_shell_false_is_removed(monkeypatch, tmp_path):
    target = tmp_path / "research_engine"
    target.mkdir()
    source = (
        Path(__file__).resolve().parents[1]
        / "research_engine"
        / "triple_implementation.py"
    ).read_text(encoding="utf-8")
    source = source.replace("shell=False", "shell=True")
    (target / "triple_implementation.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._triple_safety()
    assert result.passed is False
    assert "shell=False" in result.detail


def test_maturity_gate_rejects_static_live_proof_promotion(monkeypatch, tmp_path):
    target = tmp_path / "research_engine"
    target.mkdir()
    source = (
        Path(__file__).resolve().parents[1]
        / "research_engine"
        / "capability_maturity.py"
    ).read_text(encoding="utf-8")
    source = source.replace(
        '"live_independent_validation_proven": False',
        '"live_independent_validation_proven": True',
        1,
    )
    (target / "capability_maturity.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._maturity_honesty()
    assert result.passed is False
    assert "unsafe_promotions" in result.detail


def test_expected_value_gate_must_fail_three_way_agreement_on_wrong_claim(monkeypatch, tmp_path):
    target = tmp_path / "research_engine"
    target.mkdir()
    source = (
        Path(__file__).resolve().parents[1]
        / "research_engine"
        / "triple_task_adapter.py"
    ).read_text(encoding="utf-8")
    source = source.replace(
        "len(backend_checks) == 3 and all(backend_checks.values())",
        "bool(backend_checks)",
    )
    (target / "triple_task_adapter.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._expected_value_gate()
    assert result.passed is False


def test_literature_gate_requires_prompt_injection_boundary(monkeypatch, tmp_path):
    target = tmp_path / "research_engine"
    target.mkdir()
    source = (
        Path(__file__).resolve().parents[1]
        / "research_engine"
        / "literature_debate.py"
    ).read_text(encoding="utf-8")
    source = source.replace("looks_instruction_like(sentence)", "False")
    (target / "literature_debate.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    result = audit._literature_grounding()
    assert result.passed is False
