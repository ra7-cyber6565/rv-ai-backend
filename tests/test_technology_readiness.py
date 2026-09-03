import pytest

from research_engine.technology_readiness import ReadinessEvidence, assess_technology_readiness


def _e(level, kind, env, eid=None, **kwargs):
    return ReadinessEvidence(
        evidence_id=eid or f"E{level}",
        supports_level=level,
        evidence_kind=kind,
        environment=env,
        provenance_ref=f"receipt://level-{level}",
        **kwargs,
    )


def _software_to_level_9():
    return [
        _e(1, "PRINCIPLE", "ANALYTICAL"),
        _e(2, "CONCEPT", "ANALYTICAL"),
        _e(3, "EXPERIMENT", "LAB", reproducible=True),
        _e(4, "COMPONENT_TEST", "LAB", independent=True, reproducible=True),
        _e(5, "PROTOTYPE_TEST", "RELEVANT", independent=True, reproducible=True),
        _e(6, "PROTOTYPE_TEST", "RELEVANT", integrated_system=True, reproducible=True),
        _e(7, "PROTOTYPE_TEST", "OPERATIONAL", integrated_system=True, independent=True),
        _e(8, "QUALIFICATION", "OPERATIONAL", integrated_system=True, independent=True, reproducible=True),
        _e(9, "PRODUCTION_OBSERVATION", "OPERATIONAL", production_observed=True, independent=True),
    ]


def test_contiguous_software_evidence_can_reach_level_9_without_external_certification_claim():
    report = assess_technology_readiness(
        technology_id="tech-1",
        technology_type="SOFTWARE",
        target_level=9,
        evidence=_software_to_level_9(),
    )
    assert report.achieved_level == 9
    assert report.target_met is True
    assert all(level.passed for level in report.levels)
    assert report.external_certification_claimed is False
    assert report.truth_proven is False


def test_missing_lower_level_prevents_readiness_jump():
    evidence = _software_to_level_9()
    evidence = [row for row in evidence if row.supports_level != 3]
    report = assess_technology_readiness(
        technology_id="tech-2",
        technology_type="SOFTWARE",
        target_level=7,
        evidence=evidence,
    )
    assert report.achieved_level == 2
    assert report.target_met is False
    assert report.levels[2].blockers == ("no_evidence_for_level",)
    assert report.levels[6].passed is False


def test_physical_technology_cannot_use_simulation_to_fake_hardware_readiness():
    evidence = [
        _e(1, "PRINCIPLE", "ANALYTICAL"),
        _e(2, "CONCEPT", "ANALYTICAL"),
        _e(3, "SIMULATION", "LAB", reproducible=True),
        _e(4, "COMPONENT_TEST", "LAB", independent=True, reproducible=True),
    ]
    report = assess_technology_readiness(
        technology_id="physical-1",
        technology_type="PHYSICAL",
        target_level=4,
        evidence=evidence,
    )
    assert report.achieved_level == 3
    assert "real_hardware_observation_missing" in report.levels[3].blockers
    assert report.target_met is False


def test_physical_level_8_requires_safety_review():
    evidence = []
    for row in _software_to_level_9()[:8]:
        kwargs = row.__dict__.copy()
        kwargs["hardware_observed"] = row.supports_level >= 4
        kwargs["safety_reviewed"] = False
        evidence.append(ReadinessEvidence(**kwargs))
    report = assess_technology_readiness(
        technology_id="physical-2",
        technology_type="PHYSICAL",
        target_level=8,
        evidence=evidence,
    )
    assert report.achieved_level == 7
    assert "physical_safety_review_missing" in report.levels[7].blockers


def test_physical_level_9_needs_independent_production_observation():
    evidence = []
    for row in _software_to_level_9():
        kwargs = row.__dict__.copy()
        kwargs["hardware_observed"] = row.supports_level >= 4
        kwargs["safety_reviewed"] = row.supports_level == 8
        if row.supports_level == 9:
            kwargs["independent"] = False
        evidence.append(ReadinessEvidence(**kwargs))
    report = assess_technology_readiness(
        technology_id="physical-3",
        technology_type="PHYSICAL",
        target_level=9,
        evidence=evidence,
    )
    assert report.achieved_level == 8
    assert "independent_production_observation_missing" in report.levels[8].blockers


def test_duplicate_ids_and_invalid_level_fail_closed():
    with pytest.raises(ValueError, match="evidence_id values must be unique"):
        assess_technology_readiness(
            technology_id="t",
            technology_type="SOFTWARE",
            target_level=1,
            evidence=[
                _e(1, "PRINCIPLE", "ANALYTICAL", eid="same"),
                _e(2, "CONCEPT", "ANALYTICAL", eid="same"),
            ],
        )
    with pytest.raises(ValueError, match="supports_level"):
        assess_technology_readiness(
            technology_id="t",
            technology_type="SOFTWARE",
            target_level=1,
            evidence=[_e(10, "PRINCIPLE", "ANALYTICAL")],
        )


def test_report_hash_is_order_independent_for_evidence_set():
    evidence = _software_to_level_9()
    first = assess_technology_readiness(
        technology_id="tech-hash", technology_type="SOFTWARE", target_level=9, evidence=evidence
    )
    second = assess_technology_readiness(
        technology_id="tech-hash", technology_type="SOFTWARE", target_level=9, evidence=list(reversed(evidence))
    )
    assert first.report_sha256 == second.report_sha256
