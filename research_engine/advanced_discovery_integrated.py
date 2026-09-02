"""Non-overlapping production extensions for the Advanced Discovery Engine.

The base :mod:`advanced_discovery` module is intentionally preserved.  This
facade adds separately-auditable capabilities without duplicating or weakening
its strong discovery logic.  Package initialization installs this subclass at
the module boundary before the orchestrator imports ``ScientificDiscoveryEngine``.

Current extensions:
- #40 Triple Independent Implementation.

Future non-overlapping capabilities (for example #103 literature debate) can be
added here while their substantive logic remains in separate production modules.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from .advanced_discovery import ScientificDiscoveryEngine as _BaseScientificDiscoveryEngine
from .triple_implementation import TripleIndependentImplementation


class IntegratedScientificDiscoveryEngine(_BaseScientificDiscoveryEngine):
    """Base discovery engine plus fail-closed independent capability records."""

    integration_schema_version = "1.0"

    def __init__(self, planner: Any, *args, triple_engine=None, **kwargs):
        super().__init__(planner, *args, **kwargs)
        # Reuse the existing safe numeric executor; do not create a second Python
        # computation engine that can silently diverge from production behavior.
        self.triple_implementation = triple_engine or TripleIndependentImplementation(
            self.executor
        )

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
            triple = self.triple_implementation.run_from_verification(verification)
        except Exception:
            # Auxiliary capability failure never corrupts the already-built base
            # discovery report and is never misrepresented as a pass.
            triple = {
                "schema_version": "1.0",
                "capability_id": 40,
                "capability": "Triple Independent Implementation",
                "status": "ASSESSMENT_ERROR",
                "all_requested_tasks_agree": False,
                "results": [],
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
        report["triple_independent_implementation"] = triple
        report["extension_integration"] = {
            "schema_version": self.integration_schema_version,
            "capabilities": [40],
            "base_discovery_preserved": True,
        }
        return report


__all__ = ["IntegratedScientificDiscoveryEngine"]
