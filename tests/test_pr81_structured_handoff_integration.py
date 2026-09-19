from __future__ import annotations


def test_cross_review_wraps_current_bounded_handoff_without_bypassing_it():
    from research_engine import research_company

    fn = research_company.chief_handoff
    assert getattr(fn, "__company_cross_review_wiring__", False) is True
    base = getattr(fn, "__company_cross_review_original__", None)
    assert callable(base)
    assert getattr(base, "__bounded_structured_handoff_guard__", False) is True

    company = {
        "workers": [
            {
                "role": "evidence",
                "status": "DRAFT_READY",
                "report": {
                    "summary": "bounded report",
                    "claims": [],
                    "hypotheses": [],
                    "contract_issues": [],
                },
            }
        ],
        "cross_review_requested": False,
    }
    prompt = fn(company)
    assert isinstance(prompt, str) and "BEGIN_UNTRUSTED_SPECIALIST_DRAFTS" in prompt
    assert company["handoff_prepared"] is True
    assert company["handoff_policy"] == "LOSSLESS_SHARED_FIELDS_THEN_HARD_FAIL"
    assert company["handoff_truncated_roles"] == []
    assert company["cross_review_handoff_complete"] is True


def test_cross_review_preserves_current_fail_closed_overflow_policy():
    from research_engine import research_company

    fn = research_company.chief_handoff
    oversized_claims = [
        {
            "text": f"Unique claim {index}: " + (chr(65 + index) * 1900),
            "source_ids": ["S1"],
            "kind": "SOURCE_REPORTED",
        }
        for index in range(10)
    ]
    company = {
        "workers": [
            {
                "role": "evidence",
                "status": "DRAFT_READY",
                "report": {
                    "summary": "bounded report",
                    "claims": oversized_claims,
                    "hypotheses": [],
                    "limitations": [],
                    "assumptions": [],
                    "contradictions": [],
                    "remaining_questions": [],
                    "contract_issues": [],
                },
            }
        ],
        "cross_review_requested": False,
    }

    prompt = fn(company)

    assert isinstance(prompt, str)
    assert company["handoff_policy"] == "LOSSLESS_SHARED_FIELDS_THEN_HARD_FAIL"
    assert company["handoff_compacted_roles"] == []
    assert company["handoff_truncated_roles"] == ["evidence"]
    assert company["handoff_compaction_blocked_reasons"]["evidence"] == (
        "claim_payload_exceeds_safe_projection"
    )
    assert company["cross_review_handoff_complete"] is True
