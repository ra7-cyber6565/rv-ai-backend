"""Non-overlapping production extensions for the Advanced Discovery Engine.

The base :mod:`advanced_discovery` module is intentionally preserved. This
facade adds separately-auditable capabilities without duplicating or weakening
its strong discovery logic. Package initialization installs this subclass at
the module boundary before the orchestrator imports ``ScientificDiscoveryEngine``.

Current extensions:
- #40 Triple Independent Implementation;
- #103 Autonomous Literature Debate.

Substantive logic stays in separate production modules. An extension failure is
fail-closed and must never destroy or silently promote the base discovery report.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from .advanced_discovery import ScientificDiscoveryEngine as _BaseScientificDiscoveryEngine
from .literature_debate import AutonomousLiteratureDebate
from .triple_implementation import TripleIndependentImplementation
from .triple_task_adapter import derive_triple_tasks, run_adapted_triple


class IntegratedScientificDiscoveryEngine(_BaseScientificDiscoveryEngine):
    """Base discovery engine plus fail-closed independent capability records."""

    integration_schema_version = "1.2"

    def __init__(
        self,
        planner: Any,
        *args,
        triple_engine=None,
        literature_debate=None,
        **kwargs,
    ):
        super().__init__(planner, *args, **kwargs)
        # Reuse the existing safe numeric executor; do not create a second Python
        # computation engine that can silently diverge from production behavior.
        self.triple_implementation = triple_engine or TripleIndependentImplementation(
            self.executor
        )
        self.literature_debate = literature_debate or AutonomousLiteratureDebate()

    def analyze(
        self,
        *,
        question: str,
        plan: Mapping[str, Any],
        pack: Any,
        hypotheses: Sequence[Mapping[str, Any]],
        contradictions: Sequence[Mapping[str, Any]],
        verification: Mapping[str, Any],
        remembered_hypotheses: Sequence[Mapping[str, Any]] = (),
    ) -> Dict[str, Any]:
        report = super().analyze(
            question=question,
            plan=plan,
            pack=pack,
            hypotheses=hypotheses,
            contradictions=contradictions,
            verification=verification,
            remembered_hypotheses=remembered_hypotheses,
        )
        try:
            policy = getattr(self.triple_implementation, "policy", None)
            max_tasks = int(getattr(policy, "max_tasks", 12) or 12)
            adaptation = derive_triple_tasks(verification, max_tasks=max_tasks)
            # Important: run the adapted task list rather than calling
            # run_from_verification() directly.  The adapter is what turns the
            # verification engine's trusted normalized arithmetic checks into
            # #40 tasks and, critically, verifies that three implementations do
            # not merely agree with each other but also agree with the claim's
            # expected RHS value.
            triple = run_adapted_triple(self.triple_implementation, adaptation)
        except Exception:
            # Auxiliary capability failure never corrupts the already-built base
            # discovery report and is never misrepresented as a pass.
            triple = {
                "schema_version": "1.0",
                "capability_id": 40,
                "capability": "Triple Independent Implementation",
                "status": "ASSESSMENT_ERROR",
                "all_requested_tasks_agree": False,
                "all_expected_values_match": False,
                "results": [],
                "task_adapter": {
                    "status": "ASSESSMENT_ERROR",
                    "derived": False,
                    "source": "unknown",
                },
                "maturity_proof": {
                    "production_module": True,
                    "fail_closed_contract": True,
                    "real_r_runtime_observed_this_run": False,
                    "hardware_validation": False,
                    "live_independent_validation": False,
                    "max_or_verified_real_world_claim": False,
                },
                "note": "#40 assessment fail-closed raha; base discovery result ko promote nahi kiya gaya.",
            }
        try:
            debate = self.literature_debate.reconstruct(
                question,
                pack,
                contradictions=contradictions,
            )
        except Exception:
            debate = {
                "schema_version": "1.0",
                "capability_id": 103,
                "capability": "Autonomous Literature Debate",
                "status": "ASSESSMENT_ERROR",
                "role_slots": {
                    "researcher_a_reasoning": [],
                    "researcher_b_critique": [],
                    "researcher_c_replication_failure": [],
                },
                "debate_map": {"nodes": [], "edges": []},
                "maturity_proof": {
                    "production_module": True,
                    "fail_closed_contract": True,
                    "systematic_review_completeness_proven": False,
                    "live_independent_validation_proven": False,
                    "max_or_verified_real_world_claim": False,
                },
                "note": "#103 reconstruction fail-closed raha; koi debate role invent nahi kiya gaya.",
            }
        report["triple_independent_implementation"] = triple
        report["autonomous_literature_debate"] = debate
        report["extension_integration"] = {
            "schema_version": self.integration_schema_version,
            "capabilities": [40, 103],
            "base_discovery_preserved": True,
            "triple_task_adapter_wired": True,
            "expected_value_gate_wired": True,
        }
        return report


__all__ = ["IntegratedScientificDiscoveryEngine"]
