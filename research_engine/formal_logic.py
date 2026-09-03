"""Formal propositional-logic verification for research claims.

LLMs may propose premises and conclusions, but this module performs the
consistency/entailment check with SymPy's symbolic SAT machinery. A claim is
reported as proved only when the negated implication is unsatisfiable.

This is intentionally a bounded formal layer: it is a real propositional theorem
checker, not a claim to solve arbitrary first-order mathematics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

from sympy import Symbol
from sympy.logic.boolalg import And, Boolean, Equivalent, Implies, Not, Or
from sympy.logic.inference import satisfiable


_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


@dataclass(frozen=True)
class LogicResult:
    status: str
    entailed: Optional[bool]
    consistent: bool
    counterexample: Optional[Mapping[str, bool]]
    premises_count: int
    method: str = "symbolic-sat"


@dataclass(frozen=True)
class UnsatCore:
    inconsistent: bool
    premise_indices: Tuple[int, ...]
    minimal: bool


class FormalLogicEngine:
    """Small explicit-symbol formal logic environment."""

    def __init__(self, atom_names: Sequence[str]):
        names = tuple(dict.fromkeys(str(name).strip() for name in atom_names))
        if not names:
            raise ValueError("at least one atom is required")
        bad = [name for name in names if not _NAME_RE.fullmatch(name)]
        if bad:
            raise ValueError(f"invalid atom name(s): {', '.join(bad)}")
        self.symbols: Dict[str, Symbol] = {name: Symbol(name, boolean=True) for name in names}

    def atom(self, name: str) -> Symbol:
        try:
            return self.symbols[str(name)]
        except KeyError as exc:
            raise KeyError(f"unknown atom: {name}") from exc

    @staticmethod
    def NOT(value: Boolean) -> Boolean:
        return Not(value)

    @staticmethod
    def AND(*values: Boolean) -> Boolean:
        if not values:
            raise ValueError("AND requires at least one operand")
        return And(*values)

    @staticmethod
    def OR(*values: Boolean) -> Boolean:
        if not values:
            raise ValueError("OR requires at least one operand")
        return Or(*values)

    @staticmethod
    def IMPLIES(left: Boolean, right: Boolean) -> Boolean:
        return Implies(left, right)

    @staticmethod
    def IFF(left: Boolean, right: Boolean) -> Boolean:
        return Equivalent(left, right)

    @staticmethod
    def _model_to_plain(model) -> Optional[Dict[str, bool]]:
        if model is False:
            return None
        if model is True:
            return {}
        out: Dict[str, bool] = {}
        for key, value in dict(model).items():
            if isinstance(key, Symbol):
                out[str(key)] = bool(value)
        return dict(sorted(out.items()))

    def check_consistency(self, premises: Sequence[Boolean]) -> LogicResult:
        conjunction = And(*premises) if premises else True
        model = satisfiable(conjunction, all_models=False)
        consistent = model is not False
        return LogicResult(
            status="CONSISTENT" if consistent else "INCONSISTENT",
            entailed=None,
            consistent=consistent,
            counterexample=self._model_to_plain(model) if consistent else None,
            premises_count=len(premises),
        )

    def prove(self, premises: Sequence[Boolean], conclusion: Boolean) -> LogicResult:
        """Return entailed=True iff premises logically entail conclusion.

        Inconsistent premises are never allowed to produce a vacuous proof:
        they return status INCONSISTENT_PREMISES and entailed=None.
        """
        consistency = self.check_consistency(premises)
        if not consistency.consistent:
            return LogicResult(
                status="INCONSISTENT_PREMISES",
                entailed=None,
                consistent=False,
                counterexample=None,
                premises_count=len(premises),
            )

        conjunction = And(*premises) if premises else True
        witness = satisfiable(And(conjunction, Not(conclusion)), all_models=False)
        entailed = witness is False
        return LogicResult(
            status="PROVED" if entailed else "NOT_PROVED",
            entailed=entailed,
            consistent=True,
            counterexample=None if entailed else self._model_to_plain(witness),
            premises_count=len(premises),
        )

    def equivalent(self, left: Boolean, right: Boolean) -> LogicResult:
        witness = satisfiable(Not(Equivalent(left, right)), all_models=False)
        is_equivalent = witness is False
        return LogicResult(
            status="EQUIVALENT" if is_equivalent else "NOT_EQUIVALENT",
            entailed=is_equivalent,
            consistent=True,
            counterexample=None if is_equivalent else self._model_to_plain(witness),
            premises_count=0,
        )

    def minimal_unsat_core(self, premises: Sequence[Boolean], *, max_premises: int = 16) -> UnsatCore:
        """Find a subset-minimal inconsistent premise set by deletion."""
        if len(premises) > max_premises:
            raise ValueError(f"minimal unsat core is limited to {max_premises} premises")
        if self.check_consistency(premises).consistent:
            return UnsatCore(False, (), True)

        core = list(range(len(premises)))
        changed = True
        while changed:
            changed = False
            for index in tuple(core):
                candidate = [i for i in core if i != index]
                formulas = [premises[i] for i in candidate]
                if not self.check_consistency(formulas).consistent:
                    core = candidate
                    changed = True
                    break
        return UnsatCore(True, tuple(core), True)

    def truth_table_counterexamples(
        self,
        premises: Sequence[Boolean],
        conclusion: Boolean,
        *,
        limit: int = 20,
    ) -> Tuple[Mapping[str, bool], ...]:
        """Enumerate bounded countermodels from the symbolic SAT generator."""
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        conjunction = And(*premises) if premises else True
        models = satisfiable(And(conjunction, Not(conclusion)), all_models=True)
        if models is False:
            return ()
        out = []
        for model in models:
            if model is False:
                break
            plain = self._model_to_plain(model)
            if plain is not None:
                out.append(plain)
            if len(out) >= limit:
                break
        return tuple(out)
