"""Fail-closed maturity registry for the 142-engine Infinity Research AI blueprint.

A feature name, module, screenshot, or passing happy-path test is not proof that
a capability is max-level. A capability becomes ``VERIFIED`` only when every
proof class required by its semantics is present. The aggregate percentage is a
*proof-completion score*, never a truth, safety, profitability, or real-world
success probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Mapping, Sequence, Tuple


class ProofKind(str, Enum):
    CODE = "code"
    TEST = "test"
    WIRING = "production_wiring"
    EXECUTION = "execution"
    INDEPENDENT = "independent_validation"
    PERSISTENCE = "persistence"
    RUNTIME = "runtime_observation"
    LIVE = "live_observation"
    HARDWARE = "hardware_observation"
    SAFETY = "safety_gate"
    REPRODUCIBILITY = "reproducibility"


@dataclass(frozen=True)
class CapabilitySpec:
    id: int
    name: str
    required_proofs: Tuple[ProofKind, ...]
    note: str = ""


@dataclass(frozen=True)
class CapabilityEvidence:
    capability_id: int
    proofs: Mapping[ProofKind, Tuple[str, ...]] = field(default_factory=dict)

    def has(self, kind: ProofKind) -> bool:
        values = self.proofs.get(kind, ())
        return any(str(item).strip() for item in values)


@dataclass(frozen=True)
class CapabilityResult:
    capability_id: int
    name: str
    status: str
    required_proofs: Tuple[ProofKind, ...]
    missing_proofs: Tuple[ProofKind, ...]


@dataclass(frozen=True)
class MaturityReport:
    verified: int
    total: int
    proof_completion_score: float
    all_verified: bool
    results: Tuple[CapabilityResult, ...]

    @property
    def blocking_capability_ids(self) -> Tuple[int, ...]:
        return tuple(
            result.capability_id for result in self.results
            if result.status != "VERIFIED"
        )


def _proofs_for(capability_id: int) -> Tuple[ProofKind, ...]:
    """Evidence classes required before a capability can be called max-level."""
    required = {ProofKind.CODE, ProofKind.TEST}

    # Standalone libraries are not enough for these capabilities. They must
    # prove an actual production result/claim path invokes the implementation.
    production_wiring = {
        11, 12, 14, 62, 63, 64, 65, 67, 68, 70, 85, 95, 100, 101, 102, 103,
        104, 105, 106, 110, 112, 119, 120,
    }

    execution = {
        18, 19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
        36, 37, 38, 39, 40, 41, 66, 67, 68, 69, 71, 72, 73, 74, 79, 80, 86,
        88, 89, 97, 98, 99, 100, 102, 107, 108, 109, 122, 123, 124, 125, 126,
        127,
    }
    independent = {16, 17, 18, 19, 36, 37, 39, 40, 98, 103, 140}
    persistent = {
        42, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 76, 77, 78,
        79, 80, 87, 88, 89, 90, 96, 134, 135, 136, 137,
    }
    runtime = {41, 42, 49, 75, 76, 87, 88, 89, 91, 92, 135, 136, 137}
    live = {41, 42, 87, 88, 89, 135, 136, 137}
    physical = {25, 26, 71, 72, 73, 74, 125, 126, 127}
    safety_boundary = {23, 79, 111, 113, 114}

    if capability_id in execution:
        required.update({ProofKind.EXECUTION, ProofKind.REPRODUCIBILITY})
    if capability_id in independent:
        required.add(ProofKind.INDEPENDENT)
    if capability_id in persistent:
        required.add(ProofKind.PERSISTENCE)
    if capability_id in runtime:
        required.add(ProofKind.RUNTIME)
    if capability_id in live:
        required.add(ProofKind.LIVE)
    if capability_id in physical:
        required.update({ProofKind.HARDWARE, ProofKind.SAFETY})
    if capability_id in safety_boundary:
        required.add(ProofKind.SAFETY)
    if capability_id in production_wiring:
        required.add(ProofKind.WIRING)

    return tuple(sorted(required, key=lambda item: item.value))


_NAMES: Tuple[str, ...] = (
    "Question Understanding Engine",
    "Requirement Compiler",
    "Dynamic Problem Decomposition",
    "Universal Knowledge Acquisition System",
    "Research Dark-Matter Detector",
    "Source Genealogy Engine",
    "Primary-Source Hunter",
    "Claim Atomicization Engine",
    "Epistemic Type System",
    "Contradiction Graph",
    "Causal Reasoning Engine",
    "Counterfactual Engine",
    "Mathematical Reality Engine",
    "Formal Logic Engine",
    "Multi-Model Brain",
    "Agent Society",
    "Intellectual Diversity System",
    "Blind Analysis",
    "Debate Tournament",
    "Hypothesis Evolution Engine",
    "Novelty Engine",
    "Experiment Compiler",
    "Code Sandbox",
    "Experiment Reproducibility Package",
    "Digital Twin Engine",
    "Multi-Physics Simulation",
    "Synthetic Environment",
    "Agent-Based Simulation",
    "Monte Carlo Universe",
    "Sensitivity Analysis",
    "Ablation Testing",
    "Placebo Tests",
    "Leakage Detector",
    "Overfitting Detector",
    "Out-of-Distribution Testing",
    "Red-Team AI",
    "Devil's Advocate Swarm",
    "Falsification Budget",
    "Replication Engine",
    "Triple Implementation Testing",
    "Reality Oracle Layer",
    "Calibration Memory",
    "Domain-Specific Confidence",
    "Confidence Is Not Truth",
    "Bayesian Belief Updating",
    "Evidence Ledger",
    "Evidence Dependency Graph",
    "Truth Debt",
    "Knowledge Decay",
    "Temporal Knowledge Graph",
    "Versioned Beliefs",
    "Long-Term Scientific Memory",
    "Memory Consolidation",
    "Procedural Memory",
    "Failure Memory",
    "Mistake Taxonomy",
    "Meta-Reasoning Agent",
    "Strategy Selector",
    "Compute Economy",
    "Adaptive Research Depth",
    "Research Saturation Detector",
    "Autonomous Question Generator",
    "Serendipity Engine",
    "Cross-Domain Transfer Engine",
    "Scientific Creativity Engine",
    "Evolutionary Idea Search",
    "Neural + Symbolic Hybrid",
    "World Model",
    "Physical Reality Constraints",
    "Technology Readiness Engine",
    "Manufacturing Reality",
    "Human Factors Simulation",
    "Failure Mode and Effects Analysis",
    "Fault Injection",
    "Graceful Degradation",
    "Self-Healing Research Runs",
    "Provenance Everywhere",
    "Immutable Audit Log",
    "Cryptographic Evidence Integrity",
    "Reproducible Research Capsule",
    "Anti-Hallucination Architecture",
    "Negative Evidence Reporting",
    "Null Result Preservation",
    "Uncertainty Decomposition",
    "Unknown-Unknown Hunter",
    "Black Swan Testing",
    "Distribution Shift Monitor",
    "Continuous Post-Deployment Validation",
    "Champion-Challenger Architecture",
    "Model Graveyard",
    "Automated Benchmark Lab",
    "Self-Improvement - Controlled",
    "Research Quality Score",
    "Hard Claim Gate",
    "Claim Insurance",
    "Prediction Registry",
    "Holdout Vault",
    "Double-Blind Strategy Evaluation",
    "Multiple Hypothesis Correction",
    "Economic Reality Test",
    "Causal Mechanism Requirement",
    "Mechanistic Simulation",
    "Autonomous Literature Debate",
    "Historical Context Engine",
    "Translation Verification",
    "OCR Confidence Ledger",
    "Visual Reasoning",
    "Chart Fraud / Misleading Visualization Detector",
    "Data Forensics",
    "Synthetic Data Boundary",
    "External Tool Brain",
    "Capability Discovery",
    "Permission System",
    "Sandboxed Reality",
    "Data Poisoning Defense",
    "Source Trust Is Dynamic",
    "Fraud / Manipulation Detector",
    "Consensus Is Not Proof",
    "Belief Sandbox",
    "Conspiracy Hypothesis Discipline",
    "Prediction Before Explanation",
    "Discriminating Experiment Generator",
    "Minimum-Cost Experiment Planner",
    "Active Learning",
    "Autonomous Lab Interface",
    "Real-World Sensor Loop",
    "Simulation-to-Reality Gap",
    "Autonomous Debugging Scientist",
    "Hierarchical Truth",
    "Best-Alternative Explanation",
    "What-Would-Change-My-Mind Field",
    "Evidence Frontier",
    "Research Coverage Map",
    "Open Questions Queue",
    "Continuous Knowledge Watch",
    "Retraction Detector",
    "Dependency Shock Propagation",
    "Personalized Research Standard",
    "Answer Generator Last",
    "Anti-Confirmation Architecture",
    "Stop Saying 'I Think'",
    "Final Evidence Packet",
)


CAPABILITIES: Tuple[CapabilitySpec, ...] = tuple(
    CapabilitySpec(id=index, name=name, required_proofs=_proofs_for(index))
    for index, name in enumerate(_NAMES, start=1)
)
CAPABILITY_BY_ID: Dict[int, CapabilitySpec] = {
    item.id: item for item in CAPABILITIES
}


def assess_capabilities(
    evidence: Mapping[int, CapabilityEvidence] | None = None,
) -> MaturityReport:
    evidence = evidence or {}
    results = []
    verified = 0
    for spec in CAPABILITIES:
        item = evidence.get(spec.id)
        missing = tuple(
            proof for proof in spec.required_proofs
            if item is None or not item.has(proof)
        )
        status = "VERIFIED" if not missing else "INCOMPLETE"
        if status == "VERIFIED":
            verified += 1
        results.append(CapabilityResult(
            capability_id=spec.id,
            name=spec.name,
            status=status,
            required_proofs=spec.required_proofs,
            missing_proofs=missing,
        ))
    total = len(CAPABILITIES)
    score = round((verified / total) * 100.0, 2) if total else 0.0
    return MaturityReport(
        verified=verified,
        total=total,
        proof_completion_score=score,
        all_verified=(verified == total),
        results=tuple(results),
    )


def evidence_item(
    capability_id: int,
    **proofs: Sequence[str],
) -> CapabilityEvidence:
    """Convenience constructor with strict proof-name validation."""
    if capability_id not in CAPABILITY_BY_ID:
        raise ValueError(f"Unknown capability id: {capability_id}")
    normalized: Dict[ProofKind, Tuple[str, ...]] = {}
    for key, values in proofs.items():
        try:
            kind = ProofKind(key)
        except ValueError as exc:
            raise ValueError(f"Unknown proof kind: {key}") from exc
        normalized[kind] = tuple(
            str(value).strip() for value in values if str(value).strip()
        )
    return CapabilityEvidence(capability_id=capability_id, proofs=normalized)


def validate_registry() -> None:
    ids = [item.id for item in CAPABILITIES]
    names = [item.name for item in CAPABILITIES]
    if ids != list(range(1, 143)):
        raise RuntimeError("Capability registry must contain contiguous IDs 1..142")
    if len(set(names)) != 142:
        raise RuntimeError("Capability names must be unique")
    for item in CAPABILITIES:
        if not item.required_proofs:
            raise RuntimeError(f"Capability {item.id} has no proof requirements")
        if (
            ProofKind.CODE not in item.required_proofs
            or ProofKind.TEST not in item.required_proofs
        ):
            raise RuntimeError(
                f"Capability {item.id} must require code and tests"
            )


validate_registry()
