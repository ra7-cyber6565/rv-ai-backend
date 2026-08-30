import hashlib

import pytest

from research_engine.double_blind_evaluation import DoubleBlindStudy


KEY = b"K" * 32


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _study():
    study = DoubleBlindStudy(
        study_id="study-1",
        protocol_hash=_sha("protocol-v1"),
        assignment_key=KEY,
        metric_tolerances={"score": 0.1, "risk": 0.05},
        evaluator_instructions={"task": "score blind artifacts"},
    )
    a = study.register_candidate(
        candidate_id="candidate-a",
        artifact_digest=_sha("artifact-a"),
        builder_theory="theory A",
    )
    b = study.register_candidate(
        candidate_id="candidate-b",
        artifact_digest=_sha("artifact-b"),
        builder_theory="theory B",
    )
    study.register_evaluator(
        evaluator_id="eval-1",
        evaluator_family="family-a",
        evaluator_implementation_hash=_sha("implementation-a"),
    )
    study.register_evaluator(
        evaluator_id="eval-2",
        evaluator_family="family-b",
        evaluator_implementation_hash=_sha("implementation-b"),
    )
    return study, (a, b)


def _complete(study, arms, *, disagreement=False):
    values = {
        "eval-1": [(1.00, 0.20), (2.00, 0.30)],
        "eval-2": [(1.05, 0.22), (2.05, 0.32)],
    }
    if disagreement:
        values["eval-2"][1] = (2.50, 0.70)
    for evaluator, rows in values.items():
        for arm, (score, risk) in zip(arms, rows):
            study.record_result(
                evaluator_id=evaluator,
                arm_id=arm,
                metrics={"score": score, "risk": risk},
            )


def test_evaluator_packets_are_blind_and_deterministic():
    study, _ = _study()
    seal = study.seal()
    packet = study.evaluator_packet("eval-1")
    assert len(seal) == 64
    assert len(packet.arms) == 2
    rendered = repr(packet)
    assert "candidate-a" not in rendered
    assert "candidate-b" not in rendered
    assert "theory A" not in rendered
    assert all(arm.arm_id.startswith("arm_") for arm in packet.arms)
    assert packet == study.evaluator_packet("eval-1")


def test_seal_requires_distinct_evaluator_families_and_implementations():
    study = DoubleBlindStudy(
        study_id="study-2",
        protocol_hash=_sha("p"),
        assignment_key=KEY,
        metric_tolerances={"score": 0.1},
        evaluator_instructions={"task": "blind"},
    )
    for name in ("a", "b"):
        study.register_candidate(
            candidate_id=name,
            artifact_digest=_sha("artifact-" + name),
            builder_theory="theory " + name,
        )
    study.register_evaluator(
        evaluator_id="e1",
        evaluator_family="same-family",
        evaluator_implementation_hash=_sha("impl-1"),
    )
    study.register_evaluator(
        evaluator_id="e2",
        evaluator_family="same-family",
        evaluator_implementation_hash=_sha("impl-2"),
    )
    with pytest.raises(ValueError, match="evaluator_family must be distinct"):
        study.seal()


def test_duplicate_artifact_digest_is_rejected_before_seal():
    study = DoubleBlindStudy(
        study_id="study-3",
        protocol_hash=_sha("p"),
        assignment_key=KEY,
        metric_tolerances={"score": 0.1},
        evaluator_instructions={"task": "blind"},
    )
    digest = _sha("same")
    study.register_candidate(candidate_id="a", artifact_digest=digest, builder_theory="A")
    with pytest.raises(ValueError, match="artifact digests must be distinct"):
        study.register_candidate(candidate_id="b", artifact_digest=digest, builder_theory="B")


def test_result_cells_are_immutable_and_metrics_exact():
    study, arms = _study()
    study.seal()
    study.record_result(
        evaluator_id="eval-1", arm_id=arms[0], metrics={"score": 1.0, "risk": 0.2}
    )
    with pytest.raises(ValueError, match="immutable"):
        study.record_result(
            evaluator_id="eval-1", arm_id=arms[0], metrics={"score": 2.0, "risk": 0.3}
        )
    with pytest.raises(ValueError, match="exactly match"):
        study.record_result(
            evaluator_id="eval-1", arm_id=arms[1], metrics={"score": 2.0}
        )


def test_nonfinite_metrics_fail_closed():
    study, arms = _study()
    study.seal()
    with pytest.raises(ValueError, match="finite"):
        study.record_result(
            evaluator_id="eval-1",
            arm_id=arms[0],
            metrics={"score": float("nan"), "risk": 0.2},
        )


def test_reveal_requires_full_evaluator_arm_matrix():
    study, arms = _study()
    study.seal()
    study.record_result(
        evaluator_id="eval-1", arm_id=arms[0], metrics={"score": 1.0, "risk": 0.2}
    )
    assert study.completion()["complete"] is False
    with pytest.raises(ValueError, match="all blind evaluator-arm results"):
        study.reveal()


def test_agreement_is_computed_pairwise_and_truth_is_never_inferred():
    study, arms = _study()
    study.seal()
    _complete(study, arms)
    report = study.reveal()
    assert report.execution_complete is True
    assert report.blinding_structure_satisfied is True
    assert report.independence_structure_satisfied is True
    assert report.reproducibility_satisfied is True
    assert report.truth_proven is False
    assert report.profitability_proven is False
    assert report.comparisons
    assert len(report.report_hash) == 64


def test_disagreement_fails_reproducibility_without_erasing_execution():
    study, arms = _study()
    study.seal()
    _complete(study, arms, disagreement=True)
    report = study.reveal()
    assert report.execution_complete is True
    assert report.reproducibility_satisfied is False
    assert any(row["passed"] is False for row in report.comparisons)
    assert report.truth_proven is False


def test_builder_view_hides_results_until_reveal():
    study, arms = _study()
    study.seal()
    _complete(study, arms)
    before = study.builder_view()
    assert before["results_visible"] is False
    assert "results" not in before
    study.reveal()
    after = study.builder_view()
    assert after["results_visible"] is True


def test_assignment_key_strength_and_protocol_digest_are_fail_closed():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        DoubleBlindStudy(
            study_id="s",
            protocol_hash=_sha("p"),
            assignment_key=b"short",
            metric_tolerances={"score": 0.1},
            evaluator_instructions={},
        )
    with pytest.raises(ValueError, match="SHA-256"):
        DoubleBlindStudy(
            study_id="s",
            protocol_hash="not-a-digest",
            assignment_key=KEY,
            metric_tolerances={"score": 0.1},
            evaluator_instructions={},
        )
