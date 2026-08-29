"""Fail-closed production wiring for formal logic and capability discovery.

This module closes two *wiring* gaps without pretending they are stronger proof:

* #14 Formal Logic runs only on an explicit structured propositional contract.
  Natural-language prose is never silently converted into premises/conclusions.
* #112 Capability Discovery exposes a bounded snapshot of registered components
  that are actually present in the result path.  Discovery is not invocation,
  authorization, execution, safety proof or live proof.

The installer wraps ``result_coverage_gate.enforce`` so every normal
``ResearchResult.to_dict()`` path receives the two audit packets after all older
coverage gates have run.  It never upgrades answer status, evidence, confidence
or truth labels.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from .formal_logic import FormalLogicEngine
from .tool_broker import CapabilityCatalog, ToolDescriptor


_INSTALLED = False
_MAX_HYPOTHESES = 100
_MAX_ATOMS = 48
_MAX_PREMISES = 64
_MAX_FORMULA_DEPTH = 16
_MAX_BOOLEAN_OPERANDS = 64


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _sequence(value: Any, field: str, *, maximum: int) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a bounded sequence")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds bounded size")
    return value


def _formula(engine: FormalLogicEngine, node: Any, *, depth: int = 0):
    if depth > _MAX_FORMULA_DEPTH:
        raise ValueError("formal logic expression exceeds depth budget")
    item = _mapping(node, "formula")
    if len(item) != 1:
        raise ValueError("formula must contain exactly one operator")
    operator, payload = next(iter(item.items()))
    op = str(operator or "").strip().lower()

    if op == "atom":
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("atom must be a non-empty string")
        return engine.atom(payload.strip())
    if op == "not":
        return engine.NOT(_formula(engine, payload, depth=depth + 1))
    if op in {"and", "or"}:
        values = _sequence(payload, op, maximum=_MAX_BOOLEAN_OPERANDS)
        if not values:
            raise ValueError(f"{op} requires at least one operand")
        formulas = [_formula(engine, value, depth=depth + 1) for value in values]
        return engine.AND(*formulas) if op == "and" else engine.OR(*formulas)
    if op in {"implies", "iff"}:
        values = _sequence(payload, op, maximum=2)
        if len(values) != 2:
            raise ValueError(f"{op} requires exactly two operands")
        left = _formula(engine, values[0], depth=depth + 1)
        right = _formula(engine, values[1], depth=depth + 1)
        return engine.IMPLIES(left, right) if op == "implies" else engine.IFF(left, right)
    raise ValueError("unsupported formal logic operator")


def evaluate_formal_logic_contract(contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate one explicit bounded propositional contract.

    Contract schema::

        {
          "atoms": ["A", "B"],
          "premises": [{"implies": [{"atom": "A"}, {"atom": "B"}]}],
          "conclusion": {"atom": "B"}
        }

    No natural-language parsing occurs here.
    """
    data = _mapping(contract, "formal_logic")
    allowed = {"atoms", "premises", "conclusion"}
    if set(data) != allowed:
        raise ValueError("formal_logic contract schema is invalid")

    atoms_raw = _sequence(data.get("atoms"), "atoms", maximum=_MAX_ATOMS)
    atoms = tuple(str(item or "").strip() for item in atoms_raw)
    if not atoms or any(not item for item in atoms) or len(set(atoms)) != len(atoms):
        raise ValueError("atoms must be unique non-empty names")
    engine = FormalLogicEngine(atoms)

    premise_nodes = _sequence(data.get("premises"), "premises", maximum=_MAX_PREMISES)
    premises = tuple(_formula(engine, node) for node in premise_nodes)
    conclusion = _formula(engine, data.get("conclusion"))
    result = engine.prove(premises, conclusion)
    return {
        "status": result.status,
        "entailed": result.entailed,
        "consistent": result.consistent,
        "counterexample": dict(result.counterexample or {}),
        "premises_count": result.premises_count,
        "method": result.method,
        "bounded_propositional_only": True,
        "natural_language_formalization_performed": False,
        "truth_proven": False,
    }


def build_runtime_formal_logic_packet(hypotheses: Sequence[Any]) -> Dict[str, Any]:
    if isinstance(hypotheses, (str, bytes, bytearray)) or not isinstance(hypotheses, Sequence):
        raise ValueError("hypotheses must be a bounded sequence")
    if len(hypotheses) > _MAX_HYPOTHESES:
        raise ValueError("hypotheses exceed formal logic audit budget")

    rows = []
    explicit = 0
    invalid = 0
    for index, hypothesis in enumerate(hypotheses, 1):
        if not isinstance(hypothesis, Mapping):
            continue
        contract = hypothesis.get("formal_logic")
        if contract is None:
            continue
        explicit += 1
        hypothesis_id = str(
            hypothesis.get("id") or hypothesis.get("hypothesis_id") or f"H{index}"
        )[:240]
        try:
            audit = evaluate_formal_logic_contract(_mapping(contract, "formal_logic"))
        except Exception as exc:
            invalid += 1
            audit = {
                "status": "INVALID_CONTRACT",
                "entailed": None,
                "consistent": False,
                "counterexample": {},
                "premises_count": None,
                "method": "symbolic-sat",
                "bounded_propositional_only": True,
                "natural_language_formalization_performed": False,
                "truth_proven": False,
                "error": type(exc).__name__,
            }
        rows.append({"hypothesis_id": hypothesis_id, **audit})

    if explicit == 0:
        status = "NO_EXPLICIT_CONTRACTS"
    elif invalid:
        status = "PARTIAL_INVALID_CONTRACTS"
    else:
        status = "AUDITED"
    return {
        "ran": True,
        "status": status,
        "hypotheses_seen": len(hypotheses),
        "explicit_contracts": explicit,
        "invalid_contracts": invalid,
        "results": rows,
        "bounded_propositional_only": True,
        "natural_language_formalization_performed": False,
        "truth_proven": False,
    }


def _register(
    catalog: CapabilityCatalog,
    *,
    name: str,
    capabilities: Sequence[str],
    permissions: Sequence[str],
    risk: str = "read",
) -> None:
    catalog.register(ToolDescriptor(
        name=name,
        capabilities=tuple(capabilities),
        required_permissions=tuple(permissions),
        risk=risk,
    ))


def build_runtime_capability_snapshot(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Discover only components evidenced by this structured result path."""
    data = _mapping(result, "result")
    coverage = data.get("coverage") if isinstance(data.get("coverage"), Mapping) else {}
    catalog = CapabilityCatalog()

    # The result itself proves that the research pipeline and result gate exist.
    _register(
        catalog,
        name="research_pipeline",
        capabilities=("research_orchestration", "structured_result"),
        permissions=("research.read",),
    )
    _register(
        catalog,
        name="formal_logic",
        capabilities=("formal_logic", "symbolic_verification"),
        permissions=("compute.local",),
    )

    if isinstance(data.get("verification"), Mapping):
        _register(
            catalog,
            name="claim_verification",
            capabilities=("claim_verification", "citation_verification"),
            permissions=("research.read",),
        )
    if isinstance(data.get("lab"), Mapping) and data.get("lab"):
        _register(
            catalog,
            name="bounded_lab",
            capabilities=("bounded_experiment", "numeric_execution"),
            permissions=("compute.local",),
        )
    if isinstance(coverage.get("experiment_intelligence"), Mapping):
        _register(
            catalog,
            name="experiment_intelligence",
            capabilities=("experiment_planning", "discriminating_experiment"),
            permissions=("compute.local",),
        )
    if isinstance(coverage.get("knowledge_watch"), Mapping):
        _register(
            catalog,
            name="knowledge_watch",
            capabilities=("knowledge_revalidation", "persistent_research_memory"),
            permissions=("research.write",),
            risk="write",
        )
    if isinstance(coverage.get("source_integrity"), Mapping):
        _register(
            catalog,
            name="source_integrity",
            capabilities=("source_integrity", "source_trust_audit"),
            permissions=("research.read",),
        )

    descriptors = catalog.discover(catalog.capabilities)
    # ``discover(all capabilities)`` normally has no single descriptor covering
    # everything, so expose registered descriptors by asking each capability and
    # de-duplicating names.  This still uses the real catalog API rather than an
    # invented output list.
    by_name = {}
    for capability in catalog.capabilities:
        for descriptor in catalog.discover(capability):
            by_name[descriptor.name] = descriptor
    rows = [
        {
            "name": descriptor.name,
            "capabilities": list(descriptor.capabilities),
            "required_permissions": list(descriptor.required_permissions),
            "risk": descriptor.risk,
        }
        for descriptor in sorted(by_name.values(), key=lambda item: item.name)
    ]
    return {
        "ran": True,
        "registered_components": rows,
        "capabilities": list(catalog.capabilities),
        "component_count": len(rows),
        "discovery_only": True,
        "execution_authority_granted": False,
        "permission_enforcement_proven_by_snapshot": False,
        "execution_proven_by_snapshot": False,
        "truth_proven": False,
    }


def apply_runtime_capability_wiring(result: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(result or {})
    coverage = dict(data.get("coverage") or {})
    try:
        logic_packet = build_runtime_formal_logic_packet(data.get("hypotheses") or [])
    except Exception as exc:
        logic_packet = {
            "ran": False,
            "status": "ASSESSMENT_ERROR",
            "results": [],
            "bounded_propositional_only": True,
            "natural_language_formalization_performed": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage["formal_logic"] = logic_packet
    data["coverage"] = coverage

    try:
        capability_packet = build_runtime_capability_snapshot(data)
    except Exception as exc:
        capability_packet = {
            "ran": False,
            "registered_components": [],
            "capabilities": [],
            "component_count": 0,
            "discovery_only": True,
            "execution_authority_granted": False,
            "permission_enforcement_proven_by_snapshot": False,
            "execution_proven_by_snapshot": False,
            "truth_proven": False,
            "error": type(exc).__name__,
        }
    coverage = dict(data.get("coverage") or {})
    coverage["capability_discovery"] = capability_packet
    data["coverage"] = coverage
    return data


def install() -> None:
    """Install after older result gates, exactly once."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from . import result_coverage_gate as result_mod

    original_enforce = result_mod.enforce

    def enforce_with_runtime_capabilities(result: Dict[str, Any]) -> Dict[str, Any]:
        return apply_runtime_capability_wiring(original_enforce(result))

    result_mod.enforce = enforce_with_runtime_capabilities
