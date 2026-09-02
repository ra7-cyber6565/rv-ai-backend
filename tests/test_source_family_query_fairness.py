from __future__ import annotations

import research_engine  # noqa: F401 -- production install hooks must run
from research_engine import specialist_domains as sd
from research_engine.planner import ResearchPlanner
from research_engine.source_family_query_fairness import source_family_schedule


BIG_Q = """
Compare human sustained attention, dopamine reward prediction and neuroplasticity;
Carl Jung, shadow work and individuation; metaphysics; Hermeticism and occult
spiritual traditions; CIA declassified Project Stargate and remote-viewing records;
Freemasonry, secret societies and New World Order conspiracy allegations; and
measured 528 Hz frequency claims. Use primary texts, scholarly criticism,
empirical evidence, official documents, counter-evidence and books. Do not treat
a CIA investigation as proof or a traditional teaching as scientific evidence.
"""


def test_production_install_hook_is_active():
    assert getattr(sd, "_SOURCE_FAMILY_QUERY_FAIRNESS_INSTALLED", False) is True


def test_multidomain_schedule_gives_every_required_source_family_a_search_slot():
    schedule = source_family_schedule(BIG_Q, rounds=5, per_round=4)
    assert schedule["active"] is True
    assert schedule["coverage_complete"] is True
    required = set(schedule["required_lanes"])
    assert {
        "empirical_science",
        "scholarly_interpretation",
        "primary_historical_text",
        "traditional_belief_text",
        "official_document_record",
        "allegation_or_conspiracy_claim",
        "measured_frequency_evidence",
    }.issubset(required)
    # At four queries per round the seven current specialist source families
    # must all receive a dedicated opportunity by the end of round two.
    first_two = {
        item["lane"]
        for row in schedule["rounds"][:2]
        for item in row["queries"]
    }
    assert required.issubset(first_two)


def test_round_queries_rotate_instead_of_repeating_first_profiles_forever():
    planner = ResearchPlanner()
    cls = planner.classify(BIG_Q)
    cls["depth"] = {"name": "MARATHON"}
    round1 = planner.search_queries(BIG_Q, cls=cls, round_no=1)
    round2 = planner.search_queries(BIG_Q, cls=cls, round_no=2)
    assert round1
    assert round2
    assert round1 != round2
    joined2 = " ".join(round2).lower()
    assert any(term in joined2 for term in ("declassified", "official", "archive"))
    assert any(term in joined2 for term in ("allegation", "conspiracy", "corroboration"))
    assert any(term in joined2 for term in ("hertz", "frequency", "signal"))


def test_archive_queries_use_archive_profile_not_opening_attention_paragraph():
    queries = sd.official_archive_queries(BIG_Q, "human sustained attention dopamine reward prediction", limit=3)
    assert queries
    joined = " ".join(queries).lower()
    assert any(term in joined for term in ("declassified", "stargate", "remote viewing", "cia"))
    # The giant prompt's opening cognition facet must not become the archive anchor.
    assert "dopamine reward prediction" not in joined


def test_book_queries_cover_multiple_book_requiring_profiles():
    plan = sd.build_specialist_plan(BIG_Q, "human agency consciousness strategy")
    books = " ".join(plan["book_queries"]).lower()
    assert "jung" in books
    assert any(term in books for term in ("hermetic", "occult", "esotericism"))
    assert any(term in books for term in ("freemasonry", "secret societ"))
    schedule = plan["source_family_query_schedule"]
    assert schedule["coverage_complete"] is True


def test_single_profile_preserves_legacy_bounded_behaviour():
    q = "What does cognitive neuroscience say about sustained attention and neuroplasticity?"
    queries = sd.specialist_queries(q, q, round_no=1, limit=4)
    assert 1 <= len(queries) <= 4
    assert any("cognitive" in item.lower() or "attention" in item.lower() for item in queries)
