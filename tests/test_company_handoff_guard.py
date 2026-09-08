import json

from research_engine import research_company as company
from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack, SourceRecord


PLAN_FIELDS = (
    "test_type", "setup", "target_system_sample", "inputs_data_source", "prerequisites",
    "controls", "confounders", "baseline", "primary_outcome", "decision_threshold",
    "falsification", "power_sample_assumptions", "expected_results_by_hypothesis",
    "analysis_method", "uncertainty_method", "stopping_rule", "failure_modes",
    "replication_method", "random_seed_environment",
)


def packet():
    return EvidencePack(sources=[
        SourceRecord(source_id="S1", title="Measured source", snippet="Measured evidence")
    ])


def rich_report():
    hypotheses = []
    for index in range(6):
        plan = {field: (f"{field} explicit measured-plan wording " * 12) for field in PLAN_FIELDS}
        plan["variables"] = [
            {
                "symbol": f"x{j}",
                "definition": "explicit variable definition " * 8,
                "unit": "R" if j else "minutes",
                "role": "independent" if j % 2 == 0 else "dependent",
            }
            for j in range(8)
        ]
        hypotheses.append({
            "hypothesis": f"H{index}: regime-conditioned edge differs from baseline",
            "prediction": "held-out expectancy differs from the simpler baseline after costs",
            "baseline": "simple opening-range baseline",
            "test": "chronological walk-forward backtest with frozen out-of-sample windows",
            "falsification": "reject if held-out friction-net result does not beat baseline",
            "mechanism": "liquidity and volatility state alter execution quality",
            "assumptions": ["timestamps are ordered", "cost model is frozen"],
            "supporting_source_ids": ["S1"],
            "opposing_source_ids": [],
            "applicability_boundaries": "US100/XAUUSD research only; no live-profit claim",
            "test_plan": plan,
        })
    return json.dumps({
        "summary": "Detailed specialist validation draft with bounded, explicit test plans.",
        "claims": [
            {"text": "The supplied source reports measured evidence.", "source_ids": ["S1"], "kind": "SOURCE_REPORTED"}
        ],
        "hypotheses": hypotheses,
        "limitations": ["No live broker execution", "No independent scientific replication"],
        "assumptions": ["Historical data quality must be checked"],
        "contradictions": ["A positive in-sample result may disappear out of sample"],
        "remaining_questions": ["Which untouched period should be frozen before testing?"],
    })


def envelope(answer):
    return {
        "answer": answer,
        "accounting_complete": True,
        "output_truncated": False,
        "accounting": {
            "logical_reasoning_calls": 1,
            "actual_http_attempts": 1,
            "successful_calls": 1,
            "models_tried": ["fixture-model"],
        },
    }


def test_rich_structured_reports_use_bounded_handoff_without_false_10_of_11_gap():
    raw = rich_report()
    result = company.run_company(
        "Build and validate a US100/XAUUSD trading model",
        packet(),
        get_depth_config("COMPANY"),
        worker=lambda payload: envelope(raw),
    )

    handoff = company.chief_handoff(result)

    assert result["completed_workers"] == 4
    assert sorted(result["handoff_compacted_roles"]) == sorted(role for role, _ in company.ROLES[:4])
    assert result["handoff_truncated_roles"] == []
    assert all(level in {"STANDARD", "ULTRA"} for level in result["handoff_compaction_levels"].values())
    assert "STRUCTURED_BOUNDED_VIEW" in handoff
    assert all(role in handoff for role, _ in company.ROLES[:4])

    passes = {
        "planned_passes": ["analysis"],
        "done_passes": ["analysis"],
        "notes": [],
        "api_accounting": {"logical_reasoning_calls": 1, "actual_http_attempts": 1},
    }
    company.attach_company_passes(passes, result)
    assert "specialist_handoff" in passes["planned_passes"]
    assert "specialist_handoff" in passes["done_passes"]
    assert any("bounded structured views" in note for note in passes["notes"])


def test_claim_dominated_oversize_stays_fail_closed():
    claims = [
        {"text": "Measured description " * 110, "source_ids": ["S1"], "kind": "SOURCE_REPORTED"}
        for _ in range(10)
    ]
    raw = json.dumps({
        "summary": "Oversized claim payload",
        "claims": claims,
        "hypotheses": [{
            "hypothesis": "H", "prediction": "P", "baseline": "B",
            "test": "T", "falsification": "F",
        }],
        "limitations": [], "assumptions": [], "contradictions": [], "remaining_questions": [],
    })
    result = company.run_company("Q", packet(), get_depth_config("COMPANY"), worker=lambda payload: envelope(raw))
    company.chief_handoff(result)

    assert sorted(result["handoff_truncated_roles"]) == sorted(role for role, _ in company.ROLES[:4])
    assert all(
        reason == "claim_payload_exceeds_safe_projection"
        for reason in result["handoff_compaction_blocked_reasons"].values()
    )

    passes = {
        "planned_passes": ["analysis"], "done_passes": ["analysis"],
        "notes": [], "api_accounting": {},
    }
    company.attach_company_passes(passes, result)
    assert "specialist_handoff" not in passes["done_passes"]
