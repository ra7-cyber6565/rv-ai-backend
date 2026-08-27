import pytest

from research_engine.formal_logic import FormalLogicEngine


def test_modus_ponens_is_symbolically_proved():
    engine = FormalLogicEngine(["A", "B"])
    A, B = engine.atom("A"), engine.atom("B")
    result = engine.prove([engine.IMPLIES(A, B), A], B)
    assert result.status == "PROVED"
    assert result.entailed is True
    assert result.counterexample is None


def test_non_entailment_returns_concrete_counterexample():
    engine = FormalLogicEngine(["A", "B"])
    A, B = engine.atom("A"), engine.atom("B")
    result = engine.prove([A], B)
    assert result.status == "NOT_PROVED"
    assert result.entailed is False
    assert result.counterexample["A"] is True
    assert result.counterexample["B"] is False


def test_inconsistent_premises_never_get_vacuous_proof_label():
    engine = FormalLogicEngine(["A", "B"])
    A, B = engine.atom("A"), engine.atom("B")
    result = engine.prove([A, engine.NOT(A)], B)
    assert result.status == "INCONSISTENT_PREMISES"
    assert result.entailed is None
    assert result.consistent is False


def test_minimal_unsat_core_excludes_irrelevant_premises():
    engine = FormalLogicEngine(["A", "B", "C"])
    A, B, C = engine.atom("A"), engine.atom("B"), engine.atom("C")
    core = engine.minimal_unsat_core([A, engine.NOT(A), B, engine.OR(B, C)])
    assert core.inconsistent is True
    assert core.premise_indices == (0, 1)
    assert core.minimal is True


def test_equivalence_and_countermodels_are_executable_not_language_guessing():
    engine = FormalLogicEngine(["A", "B"])
    A, B = engine.atom("A"), engine.atom("B")
    equivalent = engine.equivalent(engine.IMPLIES(A, B), engine.OR(engine.NOT(A), B))
    assert equivalent.status == "EQUIVALENT"
    assert equivalent.entailed is True

    counterexamples = engine.truth_table_counterexamples([A], B, limit=10)
    assert counterexamples
    assert any(model.get("A") is True and model.get("B") is False for model in counterexamples)


def test_unknown_or_malicious_atom_names_fail_closed():
    engine = FormalLogicEngine(["SafeAtom"])
    with pytest.raises(KeyError):
        engine.atom("Missing")
    with pytest.raises(ValueError):
        FormalLogicEngine(["A; import os"])
    with pytest.raises(ValueError):
        FormalLogicEngine([])


def test_unsat_core_has_explicit_compute_bound():
    engine = FormalLogicEngine([f"A{i}" for i in range(20)])
    premises = [engine.atom(f"A{i}") for i in range(17)]
    with pytest.raises(ValueError, match="limited"):
        engine.minimal_unsat_core(premises, max_premises=16)
