from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("research_engine.company_cross_review_wiring")


def test_long_question_is_preserved_or_rejected_explicitly():
    wiring = _module()
    tail = "MANDATORY_FINAL_DELIVERABLE_DO_NOT_DROP"
    question = "Q" * (wiring._REVIEW_QUESTION_LIMIT + 2500) + tail
    try:
        rendered = wiring._review_question(question)
    except ValueError as exc:
        assert "question" in str(exc).lower()
    else:
        assert tail in rendered, "cross-review silently dropped the end of the user's request"


def test_duplicate_reviewer_roles_can_never_complete_handoff(monkeypatch):
    wiring = _module()
    monkeypatch.setattr(wiring, "_ORIGINAL_CHIEF_HANDOFF", lambda company: "BASE")
    report = {
        "summary": "review",
        "claims": [],
        "hypotheses": [],
        "limitations": [],
        "assumptions": [],
        "contradictions": [],
        "remaining_questions": [],
        "contract_issues": [],
        "status": "DRAFT_READY",
        "experiments_performed": False,
        "review_phase": "ROUND_2_CROSS_REVIEW",
        "reviewed_roles": [],
    }
    company = {
        "cross_review_requested": True,
        "requested_cross_reviews": 6,
        "cross_review_status": "REVIEWS_READY",
        "cross_reviews": [
            {"role": "evidence", "status": "DRAFT_READY", "reviewed_roles": [], "report": dict(report)}
            for _ in range(6)
        ],
    }
    wiring.chief_handoff(company)
    assert company["cross_review_handoff_complete"] is False
    assert len(set(company["cross_review_handoff_roles"])) != 6


def test_peer_handoff_keeps_bounded_tool_execution_receipt_without_artifact_content():
    wiring = _module()
    artifact_sha = "a" * 64
    report = {
        "summary": "peer",
        "claims": [],
        "hypotheses": [],
        "limitations": [],
        "assumptions": [],
        "contradictions": [],
        "remaining_questions": [],
        "contract_issues": [],
        "status": "DRAFT_READY",
        "experiments_performed": False,
        "tool_results": [
            {
                "tool": "numeric",
                "effect": "bounded_calculation",
                "state": "EXECUTED",
                "exit_status": 0,
                "input_sha256": "b" * 64,
                "physical_experiment": False,
                "filesystem_access": False,
                "network_access": False,
                "result": {"value": 42},
                "artifact": {
                    "filename": "result.json",
                    "media_type": "application/json",
                    "sha256": artifact_sha,
                    "content": "RAW_ARTIFACT_CONTENT_MUST_NOT_ENTER_PEER_PROMPT",
                },
            }
        ],
    }
    company = {
        "workers": [
            {"role": "evidence", "status": "DRAFT_READY", "report": {"summary": "self"}},
            {"role": "validation", "status": "DRAFT_READY", "report": report},
        ]
    }
    block, reviewed, oversized = wiring._peer_block(company, "evidence")
    assert reviewed == ["validation"]
    assert oversized == []
    assert "EXECUTED" in block
    assert artifact_sha in block
    assert "RAW_ARTIFACT_CONTENT_MUST_NOT_ENTER_PEER_PROMPT" not in block
