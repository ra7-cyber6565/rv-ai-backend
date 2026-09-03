from research_engine.ai1_research_director import (
    FULL_TEXT_REQUIRED,
    MISSING_SOURCE,
    NOT_VERIFIED,
    PACKET_SECTION_NAMES,
    attach_ai1_research_packet,
    build_ai1_research_packet,
)


def _result():
    return {
        "status": "COMPLETE",
        "question_types": ["scientific"],
        "relevant_fields": ["Physics", "Statistics"],
        "sources": [
            {
                "source_id": "S1",
                "title": "Primary experiment",
                "source_type": "paper",
                "authors": ["A. Researcher"],
                "quality_score": 0.91,
                "relevance_score": 0.93,
                "peer_reviewed": True,
                "is_primary": True,
                "read_level": "full_text",
                "full_text_chars": 8000,
                "methodology": "controlled_experiment",
            },
            {
                "source_id": "S2",
                "title": "Abstract-only follow-up",
                "source_type": "paper",
                "authors": ["B. Scientist"],
                "quality_score": 0.75,
                "relevance_score": 0.82,
                "peer_reviewed": True,
                "read_level": "abstract",
                "full_text_chars": 0,
            },
        ],
        "uncited_sources": [],
        "citations": [{"source_id": "S1", "title": "Primary experiment"}],
        "verification": {
            "claim_checks": {
                "claims": [
                    {
                        "claim_id": "CL001",
                        "text": "Measured outcome increased because mechanism M changed.",
                        "source_ids": ["S1"],
                        "best_source": "S1",
                        "epistemic_type": "evidence",
                        "result": "SUPPORTED",
                        "source_quality": "primary peer-reviewed",
                        "checks": [
                            {"check": key, "status": "pass"}
                            for key in "ABCDE"
                        ],
                        "source_checks": [{"source_id": "S1", "passes_ae": True}],
                        "canonical_span": {
                            "source_id": "S1",
                            "text": "Measured outcome increased ...",
                        },
                    },
                    {
                        "claim_id": "CL002",
                        "text": "A new mechanism may explain the residual effect.",
                        "source_ids": [],
                        "epistemic_type": "hypothesis",
                        "result": "UNABLE TO VERIFY",
                    },
                ]
            }
        },
        "contradictions": [
            {
                "source_a": "S1",
                "source_b": "S2",
                "status": "possible_conflict",
                "reason": "different measured direction",
            }
        ],
        "coverage": {
            "evidence_axes": {
                "summary": {
                    "mandatory_missing": 1,
                    "missing_labels": ["replication"],
                }
            }
        },
        "quality_context": {"counter_search_performed": True},
        "quality_contract": {"requires_evidence": True},
        "contract_ledger": {"unmet": []},
        "source_integrity": {"high_risk": False},
        "hypotheses": [{"id": "H1", "hypothesis": "testable hypothesis"}],
        "experiment_intelligence": {"status": "PARTIAL"},
        "specialist_research": {"active": False},
        "rejects": {},
    }


def test_exact_15_section_contract_and_order():
    packet = build_ai1_research_packet("Explain the measured effect", _result())
    assert list(packet["sections"]) == list(PACKET_SECTION_NAMES)
    assert len(packet["sections"]) == 15
    assert packet["validation"]["valid"] is True
    assert packet["is_final_user_answer"] is False


def test_c_d_e_claims_cannot_be_promoted_to_fact():
    packet = build_ai1_research_packet("Explain the measured effect", _result())
    matrix = packet["sections"]["6. Claim-Evidence Matrix"]
    by_id = {row["claim_id"]: row for row in matrix}
    assert by_id["CL001"]["confidence_grade"] == "A"
    assert by_id["CL001"]["fact_promotion_allowed"] is True
    assert by_id["CL002"]["confidence_grade"] == "D"
    assert by_id["CL002"]["fact_promotion_allowed"] is False
    assert packet["validation"]["c_d_e_promotion_violations"] == []


def test_shallow_source_is_explicit_full_text_gap():
    packet = build_ai1_research_packet("Explain the measured effect", _result())
    missing = packet["sections"]["11. Missing Evidence"]
    codes = {item["code"] for item in missing}
    assert FULL_TEXT_REQUIRED in codes
    strongest = packet["sections"]["5. Strongest Sources"]
    s2 = next(item for item in strongest if item["source_id"] == "S2")
    assert s2["full_text_status"] == "ABSTRACT ONLY"
    assert FULL_TEXT_REQUIRED in s2["limitations"]


def test_missing_sources_fail_closed_instead_of_fabricating():
    result = _result()
    result["sources"] = []
    result["citations"] = []
    result["uncited_sources"] = []
    packet = build_ai1_research_packet("Unknown question", result)
    missing = packet["sections"]["11. Missing Evidence"]
    assert any(item["code"] == MISSING_SOURCE for item in missing)
    assert packet["sections"]["5. Strongest Sources"] == []
    assert packet["sections"]["14. Confidence in Research Packet /100"]["score"] <= 25


def test_cross_agent_routing_and_second_pass_are_measured():
    packet = build_ai1_research_packet("Explain the measured effect", _result())
    alerts = packet["sections"]["12. Cross-Agent Alerts"]
    agents = {item["agent"] for item in alerts}
    assert {"AI-2", "AI-3", "AI-4"}.issubset(agents)

    tasks = packet["sections"]["13. Highest-Value Second-Pass Research Tasks"]
    assert tasks
    scores = [item["priority_score"] for item in tasks]
    assert scores == sorted(scores, reverse=True)
    for item in tasks:
        assert item["priority_score"] == (
            item["importance"] * item["expected_information_gain"]
        )
        assert item["priority_formula"] == "Importance × Expected Information Gain"


def test_packet_confidence_is_not_truth_or_success_probability():
    packet = build_ai1_research_packet("Explain the measured effect", _result())
    conf = packet["sections"]["14. Confidence in Research Packet /100"]
    assert 0 <= conf["score"] <= 100
    assert conf["not_a_truth_probability"] is True
    assert conf["not_a_success_or_profitability_probability"] is True


def test_trading_research_targets_are_not_assumed_true():
    result = _result()
    result["question_types"] = ["financial"]
    result["relevant_fields"] = ["Finance", "Market microstructure"]
    packet = build_ai1_research_packet(
        "US100 XAUUSD 1m scalping model using ICT and order flow", result
    )
    experts = packet["sections"]["4. Relevant Experts / Thinkers / Schools"]
    schools = experts["schools_or_research_traditions_to_test"]
    names = {item["name"] for item in schools}
    assert "ICT primary teaching material" in names
    assert "market microstructure" in names
    assert all(item["status"] == "research target, not assumed correct" for item in schools)


def test_attach_is_backward_compatible_and_additive():
    result = _result()
    original_keys = set(result)
    returned = attach_ai1_research_packet("Explain the measured effect", result)
    assert returned is result
    assert original_keys.issubset(result)
    assert "ai1_research_packet" in result
    assert result["ai1_research_packet"]["validation"]["valid"] is True


def test_no_structured_claim_checks_are_not_called_verified():
    result = _result()
    result["verification"] = {}
    packet = build_ai1_research_packet("Explain the measured effect", result)
    matrix = packet["sections"]["6. Claim-Evidence Matrix"]
    assert matrix[0]["claim"] == NOT_VERIFIED
    assert matrix[0]["confidence_grade"] == "E"
    assert matrix[0]["fact_promotion_allowed"] is False
    assert packet["sections"]["14. Confidence in Research Packet /100"]["score"] <= 55
