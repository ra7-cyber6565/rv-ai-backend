"""Honesty tests for advanced capability maturity proof mapping."""
from __future__ import annotations

from research_engine.capability_maturity import (
    all_capability_maturity,
    capability_maturity,
)


def test_40_mapping_names_real_modules_and_tests_without_claiming_execution():
    row = capability_maturity(40)
    assert row["name"] == "Triple Independent Implementation"
    assert row["implementation"]["module"] == "research_engine/triple_implementation.py"
    assert row["implementation"]["production_wiring"] == "research_engine/advanced_discovery_integrated.py"
    assert "tests/test_triple_implementation.py" in row["implementation"]["tests"]
    assert row["implementation"]["fail_closed"] is True
    assert row["proof"]["repository_implementation_present"] is True
    assert row["proof"]["production_wiring_present"] is True
    assert row["proof"]["current_full_gate_execution_proven"] is False
    assert row["proof"]["real_r_runtime_execution_proven"] is False
    assert row["proof"]["live_independent_validation_proven"] is False
    assert row["proof"]["hardware_or_physical_validation_proven"] is False
    assert row["claim_ceiling"] == "IMPLEMENTED_PENDING_EXECUTION_PROOF"


def test_unknown_capability_fails_closed_instead_of_inventing_maturity():
    row = capability_maturity(999999)
    assert row["claim_ceiling"] == "NOT_REGISTERED"
    assert row["proof"] == {}
    assert "verified" in row["cannot_claim"]


def test_registry_returns_copies_not_mutable_global_state():
    first = capability_maturity(40)
    first["proof"]["hardware_or_physical_validation_proven"] = True
    second = capability_maturity(40)
    assert second["proof"]["hardware_or_physical_validation_proven"] is False

    all_rows = all_capability_maturity()
    all_rows[40]["claim_ceiling"] = "MAX"
    assert capability_maturity(40)["claim_ceiling"] == "IMPLEMENTED_PENDING_EXECUTION_PROOF"
