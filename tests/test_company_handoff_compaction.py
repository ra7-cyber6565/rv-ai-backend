import json

from research_engine import research_company as company
from research_engine.depth import get_depth_config
from research_engine.models import EvidencePack, SourceRecord


def _packet():
    return EvidencePack(
        sources=[SourceRecord(source_id="S1", title="Example study", snippet="Measured evidence")]
    )


def _report(claims):
    return json.dumps(
        {
            "summary": "A supported candidate with uncertainty.",
            "claims": claims,
            "hypotheses": [
                {
                    "hypothesis": "H",
                    "prediction": "A exceeds baseline",
                    "baseline": "B",
                    "test": "Compare A and B on a frozen holdout",
                    "falsification": "No improvement",
                }
            ],
            "limitations": ["No external replication"],
            "assumptions": [],
            "contradictions": [],
            "remaining_questions": [],
        }
    )


def _envelope(answer):
    return {
        "answer": answer,
        "accounting_complete": True,
        "output_truncated": False,
        "accounting": {
            "logical_reasoning_calls": 1,
            "actual_http_attempts": 1,
            "successful_calls": 1,
            "models_tried": ["same-model"],
        },
    }


def _analysis_passes():
    return {
        "planned_passes": ["analysis"],
        "done_passes": ["analysis"],
        "notes": [],
        "api_accounting": {},
    }


def test_duplicate_overflow_compacts_without_dropping_unique_reasoning():
    duplicate = {
        "text": "Measured description " * 90,
        "source_ids": ["S1"],
        "kind": "SOURCE_REPORTED",
    }
    answer = _report([duplicate for _ in range(10)])
    result = company.run_company(
        "Q", _packet(), get_depth_config("COMPANY"), worker=lambda payload: _envelope(answer)
    )

    handoff = company.chief_handoff(result)

    assert len(result["handoff_compacted_roles"]) == 4
    assert result["handoff_truncated_roles"] == []
    assert result["handoff_structured_compaction"] is True
    assert all(role in handoff for role, _ in company.ROLES[:4])
    assert all(
        result["handoff_omitted_counts"][role]["claims"] == 9
        for role, _ in company.ROLES[:4]
    )

    passes = _analysis_passes()
    company.attach_company_passes(passes, result)
    assert "specialist_handoff" in passes["done_passes"]


def test_unique_overflow_remains_fail_closed_instead_of_fake_compaction():
    claims = [
        {
            "text": f"Unique claim {index}: " + (chr(65 + index) * 1900),
            "source_ids": ["S1"],
            "kind": "SOURCE_REPORTED",
        }
        for index in range(10)
    ]
    answer = _report(claims)
    result = company.run_company(
        "Q", _packet(), get_depth_config("COMPANY"), worker=lambda payload: _envelope(answer)
    )

    company.chief_handoff(result)

    assert result["handoff_compacted_roles"] == []
    assert len(result["handoff_truncated_roles"]) == 4
    assert result["handoff_structured_compaction"] is False
    assert all(
        result["handoff_omitted_counts"][role]["claims"] == 0
        for role, _ in company.ROLES[:4]
    )

    passes = _analysis_passes()
    company.attach_company_passes(passes, result)
    assert "specialist_handoff" in passes["planned_passes"]
    assert "specialist_handoff" not in passes["done_passes"]
    assert any("Complete specialist handoff was not confirmed" in note for note in passes["notes"])
