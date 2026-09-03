"""Bounded structural-causal and counterfactual reasoning for capabilities #11/#12.

The engine deliberately accepts an *explicit* acyclic linear structural causal
model (SCM).  It never converts natural-language correlation into a causal graph.
That boundary matters: a mathematically valid do/counterfactual calculation is
not evidence that the supplied graph is causally correct.

Supported operations:
- structural model validation + deterministic topological evaluation;
- intervention (Pearl-style ``do(X=x)`` severs X's incoming equations);
- unit-level counterfactual abduction -> action -> prediction when a complete
  factual observation is supplied;
- total-effect contrast between two explicit interventions;
- bounded local coefficient sensitivity around an intervention result;
- explicit assumptions/identification warnings and deterministic receipts.

This is not arbitrary nonlinear SCM inference, causal discovery, hidden-
confounder identification, or proof of real-world causation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Dict, Iterable, Mapping, Sequence, Tuple


_MAX_NODES = 64
_MAX_EDGES = 256
_MAX_TARGETS = 64
_MAX_SCENARIOS = 128
_MAX_NAME = 120
_MAX_ABS_VALUE = 1e15


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or abs(result) > _MAX_ABS_VALUE:
        raise ValueError(f"{field} must be finite and bounded")
    return result


def _name(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    result = value.strip()
    if not result or len(result) > _MAX_NAME:
        raise ValueError(f"{field} must be a bounded non-empty name")
    return result


def _canonical_hash(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CausalNode:
    name: str
    parents: Tuple[Tuple[str, float], ...] = ()
    intercept: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CausalNode":
        if not isinstance(value, Mapping):
            raise ValueError("causal node must be a mapping")
        unknown = set(value) - {"name", "parents", "intercept"}
        if unknown:
            raise ValueError("causal node contains unsupported fields")
        name = _name(value.get("name"), "node.name")
        intercept = _finite(value.get("intercept", 0.0), f"{name}.intercept")
        raw_parents = value.get("parents", {})
        if not isinstance(raw_parents, Mapping):
            raise ValueError(f"{name}.parents must be a mapping")
        if len(raw_parents) > _MAX_EDGES:
            raise ValueError("causal node parent budget exceeded")
        parents = []
        for parent, coefficient in raw_parents.items():
            parent_name = _name(parent, f"{name}.parent")
            if parent_name == name:
                raise ValueError("causal node cannot be its own parent")
            parents.append((parent_name, _finite(coefficient, f"{name}.{parent_name}")))
        parents.sort(key=lambda item: item[0])
        return cls(name=name, parents=tuple(parents), intercept=intercept)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "parents": {key: value for key, value in self.parents},
            "intercept": self.intercept,
        }


@dataclass(frozen=True)
class CausalModel:
    nodes: Tuple[CausalNode, ...]
    hidden_confounding_addressed: bool = False
    identification_basis: str = "user_supplied_structural_assumptions"

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CausalModel":
        if not isinstance(value, Mapping):
            raise ValueError("causal model must be a mapping")
        unknown = set(value) - {
            "nodes", "hidden_confounding_addressed", "identification_basis"
        }
        if unknown:
            raise ValueError("causal model contains unsupported fields")
        raw_nodes = value.get("nodes")
        if isinstance(raw_nodes, (str, bytes, bytearray)) or not isinstance(raw_nodes, Sequence):
            raise ValueError("causal model nodes must be a sequence")
        if not raw_nodes or len(raw_nodes) > _MAX_NODES:
            raise ValueError("causal model node count is invalid")
        nodes = tuple(CausalNode.from_mapping(item) for item in raw_nodes)
        names = [item.name for item in nodes]
        if len(set(names)) != len(names):
            raise ValueError("causal model node names must be unique")
        known = set(names)
        edge_count = 0
        for node in nodes:
            for parent, _coefficient in node.parents:
                edge_count += 1
                if parent not in known:
                    raise ValueError(f"unknown parent node: {parent}")
        if edge_count > _MAX_EDGES:
            raise ValueError("causal model edge budget exceeded")
        model = cls(
            nodes=nodes,
            hidden_confounding_addressed=bool(value.get("hidden_confounding_addressed", False)),
            identification_basis=_name(
                value.get("identification_basis", "user_supplied_structural_assumptions"),
                "identification_basis",
            ),
        )
        model.topological_order()  # cycle validation
        return model

    @property
    def model_hash(self) -> str:
        return _canonical_hash(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "nodes": [item.to_dict() for item in self.nodes],
            "hidden_confounding_addressed": self.hidden_confounding_addressed,
            "identification_basis": self.identification_basis,
        }

    def topological_order(self) -> Tuple[str, ...]:
        parents = {node.name: {name for name, _ in node.parents} for node in self.nodes}
        remaining = set(parents)
        order = []
        while remaining:
            ready = sorted(name for name in remaining if not (parents[name] & remaining))
            if not ready:
                raise ValueError("causal model must be acyclic")
            order.extend(ready)
            remaining.difference_update(ready)
        return tuple(order)

    def node_map(self) -> Dict[str, CausalNode]:
        return {item.name: item for item in self.nodes}


@dataclass(frozen=True)
class CausalReceipt:
    operation: str
    model_hash: str
    factual_values: Mapping[str, float]
    intervention: Mapping[str, float]
    predicted_values: Mapping[str, float]
    deltas: Mapping[str, float]
    exogenous_disturbances: Mapping[str, float]
    assumptions: Tuple[str, ...]
    warnings: Tuple[str, ...]
    result_hash: str
    causal_graph_empirically_proven: bool = False
    real_world_effect_proven: bool = False

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "model_hash": self.model_hash,
            "factual_values": dict(self.factual_values),
            "intervention": dict(self.intervention),
            "predicted_values": dict(self.predicted_values),
            "deltas": dict(self.deltas),
            "exogenous_disturbances": dict(self.exogenous_disturbances),
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
            "result_hash": self.result_hash,
            "causal_graph_empirically_proven": self.causal_graph_empirically_proven,
            "real_world_effect_proven": self.real_world_effect_proven,
        }


class CausalCounterfactualEngine:
    def __init__(self, model: CausalModel):
        if not isinstance(model, CausalModel):
            raise ValueError("model must be CausalModel")
        self.model = model
        self._nodes = model.node_map()
        self._order = model.topological_order()

    def _bounded_values(
        self,
        values: Mapping[str, object] | None,
        field: str,
        *,
        allow_partial: bool,
    ) -> Dict[str, float]:
        if values is None:
            return {}
        if not isinstance(values, Mapping):
            raise ValueError(f"{field} must be a mapping")
        if len(values) > _MAX_NODES:
            raise ValueError(f"{field} exceeds node budget")
        output = {}
        for key, raw in values.items():
            name = _name(key, field)
            if name not in self._nodes:
                raise ValueError(f"{field} references unknown node: {name}")
            output[name] = _finite(raw, f"{field}.{name}")
        if not allow_partial and set(output) != set(self._nodes):
            raise ValueError(f"{field} must provide every model node")
        return output

    def evaluate(
        self,
        *,
        exogenous: Mapping[str, object] | None = None,
        intervention: Mapping[str, object] | None = None,
    ) -> Dict[str, float]:
        disturbances = self._bounded_values(exogenous, "exogenous", allow_partial=True)
        do_values = self._bounded_values(intervention, "intervention", allow_partial=True)
        values: Dict[str, float] = {}
        for name in self._order:
            if name in do_values:
                values[name] = do_values[name]
                continue
            node = self._nodes[name]
            value = node.intercept + disturbances.get(name, 0.0)
            for parent, coefficient in node.parents:
                value += coefficient * values[parent]
            values[name] = _finite(value, f"computed.{name}")
        return values

    def abduce(self, factual: Mapping[str, object]) -> Dict[str, float]:
        observed = self._bounded_values(factual, "factual", allow_partial=False)
        disturbances: Dict[str, float] = {}
        for name in self._order:
            node = self._nodes[name]
            expected = node.intercept
            for parent, coefficient in node.parents:
                expected += coefficient * observed[parent]
            disturbances[name] = _finite(
                observed[name] - expected,
                f"abduced.{name}",
            )
        # A hard internal invariant: the abduced unit must reconstruct exactly
        # (within numerical tolerance) before any counterfactual is emitted.
        reconstructed = self.evaluate(exogenous=disturbances)
        for name in self._order:
            tolerance = 1e-9 * max(1.0, abs(observed[name]))
            if abs(reconstructed[name] - observed[name]) > tolerance:
                raise RuntimeError("counterfactual abduction reconstruction failed")
        return disturbances

    def counterfactual(
        self,
        *,
        factual: Mapping[str, object],
        intervention: Mapping[str, object],
        targets: Sequence[str] | None = None,
    ) -> CausalReceipt:
        observed = self._bounded_values(factual, "factual", allow_partial=False)
        do_values = self._bounded_values(intervention, "intervention", allow_partial=True)
        if not do_values:
            raise ValueError("counterfactual intervention must not be empty")
        target_names = self._targets(targets)
        disturbances = self.abduce(observed)
        predicted = self.evaluate(exogenous=disturbances, intervention=do_values)
        selected = {name: predicted[name] for name in target_names}
        deltas = {name: predicted[name] - observed[name] for name in target_names}
        return self._receipt(
            operation="counterfactual_abduction_action_prediction",
            factual=observed,
            intervention=do_values,
            predicted=selected,
            deltas=deltas,
            disturbances=disturbances,
        )

    def interventional_contrast(
        self,
        *,
        intervention_a: Mapping[str, object],
        intervention_b: Mapping[str, object],
        targets: Sequence[str] | None = None,
        exogenous: Mapping[str, object] | None = None,
    ) -> CausalReceipt:
        a = self._bounded_values(intervention_a, "intervention_a", allow_partial=True)
        b = self._bounded_values(intervention_b, "intervention_b", allow_partial=True)
        if not a or not b:
            raise ValueError("both intervention arms must be non-empty")
        target_names = self._targets(targets)
        disturbances = self._bounded_values(exogenous, "exogenous", allow_partial=True)
        values_a = self.evaluate(exogenous=disturbances, intervention=a)
        values_b = self.evaluate(exogenous=disturbances, intervention=b)
        predicted = {name: values_b[name] for name in target_names}
        deltas = {name: values_b[name] - values_a[name] for name in target_names}
        return self._receipt(
            operation="interventional_contrast_b_minus_a",
            factual={name: values_a[name] for name in target_names},
            intervention={f"A:{key}": value for key, value in sorted(a.items())}
            | {f"B:{key}": value for key, value in sorted(b.items())},
            predicted=predicted,
            deltas=deltas,
            disturbances=disturbances,
        )

    def coefficient_sensitivity(
        self,
        *,
        factual: Mapping[str, object],
        intervention: Mapping[str, object],
        target: str,
        relative_perturbation: float = 0.05,
    ) -> Tuple[dict, ...]:
        perturb = _finite(relative_perturbation, "relative_perturbation")
        if not 0.0 < perturb <= 0.5:
            raise ValueError("relative_perturbation must be in (0, 0.5]")
        target_name = _name(target, "target")
        if target_name not in self._nodes:
            raise ValueError("target references unknown node")
        base = self.counterfactual(
            factual=factual,
            intervention=intervention,
            targets=[target_name],
        ).predicted_values[target_name]
        scenarios = []
        for node in self.model.nodes:
            for parent, coefficient in node.parents:
                if len(scenarios) >= _MAX_SCENARIOS:
                    raise ValueError("sensitivity scenario budget exceeded")
                for direction in (-1.0, 1.0):
                    changed_nodes = []
                    for candidate in self.model.nodes:
                        parents = dict(candidate.parents)
                        if candidate.name == node.name:
                            parents[parent] = coefficient * (1.0 + direction * perturb)
                        changed_nodes.append({
                            "name": candidate.name,
                            "parents": parents,
                            "intercept": candidate.intercept,
                        })
                    altered = CausalModel.from_mapping({
                        "nodes": changed_nodes,
                        "hidden_confounding_addressed": self.model.hidden_confounding_addressed,
                        "identification_basis": self.model.identification_basis,
                    })
                    value = CausalCounterfactualEngine(altered).counterfactual(
                        factual=factual,
                        intervention=intervention,
                        targets=[target_name],
                    ).predicted_values[target_name]
                    scenarios.append({
                        "edge": f"{parent}->{node.name}",
                        "coefficient_multiplier": 1.0 + direction * perturb,
                        "target": target_name,
                        "predicted": value,
                        "delta_from_base": value - base,
                        "causal_truth_proven": False,
                    })
        return tuple(scenarios)

    def _targets(self, targets: Sequence[str] | None) -> Tuple[str, ...]:
        if targets is None:
            return self._order
        if isinstance(targets, (str, bytes, bytearray)) or not isinstance(targets, Sequence):
            raise ValueError("targets must be a sequence")
        if not targets or len(targets) > _MAX_TARGETS:
            raise ValueError("targets count is invalid")
        names = tuple(_name(value, "target") for value in targets)
        if len(set(names)) != len(names):
            raise ValueError("targets must be unique")
        unknown = [name for name in names if name not in self._nodes]
        if unknown:
            raise ValueError("targets reference unknown nodes")
        return names

    def _receipt(
        self,
        *,
        operation: str,
        factual: Mapping[str, float],
        intervention: Mapping[str, float],
        predicted: Mapping[str, float],
        deltas: Mapping[str, float],
        disturbances: Mapping[str, float],
    ) -> CausalReceipt:
        assumptions = (
            "supplied structural equations are correct for the intended system",
            "structural coefficients are stable under the stated intervention",
            "counterfactual prediction reuses the same unit-level disturbances",
        )
        warnings = [
            "SCM calculation does not prove the supplied causal graph",
            "model output is not a measured real-world intervention result",
        ]
        if not self.model.hidden_confounding_addressed:
            warnings.append("hidden confounding has not been established as addressed")
        payload = {
            "operation": operation,
            "model_hash": self.model.model_hash,
            "factual_values": dict(sorted(factual.items())),
            "intervention": dict(sorted(intervention.items())),
            "predicted_values": dict(sorted(predicted.items())),
            "deltas": dict(sorted(deltas.items())),
            "exogenous_disturbances": dict(sorted(disturbances.items())),
            "assumptions": list(assumptions),
            "warnings": warnings,
        }
        return CausalReceipt(
            operation=operation,
            model_hash=self.model.model_hash,
            factual_values=dict(sorted(factual.items())),
            intervention=dict(sorted(intervention.items())),
            predicted_values=dict(sorted(predicted.items())),
            deltas=dict(sorted(deltas.items())),
            exogenous_disturbances=dict(sorted(disturbances.items())),
            assumptions=assumptions,
            warnings=tuple(warnings),
            result_hash=_canonical_hash(payload),
        )


def evaluate_causal_contract(contract: Mapping[str, object]) -> dict:
    """Bounded public contract used by production wiring.

    Required shape::
      {"model": {...}, "factual": {...}, "intervention": {...}, "targets": [...]}

    The contract is deliberately explicit.  Missing factual observations block
    unit-level counterfactual generation rather than being guessed from prose.
    """
    if not isinstance(contract, Mapping):
        raise ValueError("causal contract must be a mapping")
    allowed = {"model", "factual", "intervention", "targets"}
    if set(contract) != allowed:
        raise ValueError("causal contract schema is invalid")
    model = CausalModel.from_mapping(contract["model"])
    engine = CausalCounterfactualEngine(model)
    receipt = engine.counterfactual(
        factual=contract["factual"],
        intervention=contract["intervention"],
        targets=contract["targets"],
    )
    result = receipt.to_dict()
    result.update({
        "status": "MODELED_COUNTERFACTUAL",
        "method": "bounded_linear_structural_causal_model",
        "natural_language_causal_discovery_performed": False,
        "hidden_confounding_addressed": model.hidden_confounding_addressed,
        "identification_basis": model.identification_basis,
        "truth_proven": False,
    })
    return result
