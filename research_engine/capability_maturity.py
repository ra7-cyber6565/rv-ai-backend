"""Honest maturity-proof registry for advanced Infinity Research AI capabilities.

This registry records what the repository can prove from code/tests versus what
still requires an external runtime, live validation, hardware, wet-lab work, or
independent human replication.  It is intentionally conservative: implementation
and tests never imply scientific truth or production/max maturity by themselves.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


_CAPABILITIES: Dict[int, Dict[str, Any]] = {
    40: {
        "id": 40,
        "name": "Triple Independent Implementation",
        "implementation": {
            "module": "research_engine/triple_implementation.py",
            "production_wiring": "research_engine/advanced_discovery_integrated.py",
            "tests": [
                "tests/test_triple_implementation.py",
                "tests/test_advanced_discovery_extensions.py",
            ],
            "fail_closed": True,
            "adversarial_tests_defined": True,
        },
        "proof": {
            "repository_implementation_present": True,
            "production_wiring_present": True,
            "test_definitions_present": True,
            # These fields must be promoted only from real execution receipts,
            # never because source code merely contains a test.
            "current_full_gate_execution_proven": False,
            "real_r_runtime_execution_proven": False,
            "live_independent_validation_proven": False,
            "hardware_or_physical_validation_proven": False,
        },
        "claim_ceiling": "IMPLEMENTED_PENDING_EXECUTION_PROOF",
        "cannot_claim": [
            "scientific truth from triple numeric agreement",
            "hardware validation",
            "live independent replication",
            "100/100 or max maturity without executed evidence",
        ],
    },
    103: {
        "id": 103,
        "name": "Autonomous Literature Debate",
        "implementation": {
            "module": "research_engine/literature_debate.py",
            "readiness_guard": "research_engine/literature_debate_guard.py",
            "production_wiring": "research_engine/advanced_discovery_integrated.py",
            "tests": [
                "tests/test_literature_debate.py",
                "tests/test_literature_debate_guard.py",
                "tests/test_advanced_discovery_extensions.py",
            ],
            "fail_closed": True,
            "adversarial_tests_defined": True,
            "grounded_presence_separate_from_readiness": True,
        },
        "proof": {
            "repository_implementation_present": True,
            "production_wiring_present": True,
            "test_definitions_present": True,
            "current_full_gate_execution_proven": False,
            "grounded_available_text_reconstruction_proven_by_execution": False,
            "depth_relevance_quality_readiness_gate_proven_by_execution": False,
            "systematic_review_completeness_proven": False,
            "live_independent_validation_proven": False,
            "hardware_or_physical_validation_proven": False,
        },
        "claim_ceiling": "IMPLEMENTED_PENDING_EXECUTION_PROOF",
        "cannot_claim": [
            "global literature completeness",
            "missing critique means no critique exists",
            "missing replication failure means replication succeeded",
            "snippet or low-quality argument means reliable debate readiness",
            "invented researcher identities",
            "100/100 or max maturity without executed evidence",
        ],
    },
}


def capability_maturity(capability_id: int) -> Dict[str, Any]:
    """Return a copy so callers cannot mutate the global proof registry."""
    row = _CAPABILITIES.get(int(capability_id))
    if row is None:
        return {
            "id": int(capability_id),
            "name": "unknown",
            "claim_ceiling": "NOT_REGISTERED",
            "proof": {},
            "cannot_claim": ["implemented", "verified", "max maturity"],
        }
    return deepcopy(row)


def all_capability_maturity() -> Dict[int, Dict[str, Any]]:
    return {key: deepcopy(value) for key, value in sorted(_CAPABILITIES.items())}


__all__ = ["all_capability_maturity", "capability_maturity"]
