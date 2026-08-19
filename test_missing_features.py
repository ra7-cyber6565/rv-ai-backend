"""
Comprehensive Test Suite for Missing Features
All tests offline — zero Gemini quota needed
"""
import sys
sys.path.insert(0, "/sessions/vigilant-magical-cerf/mnt/infinity-research-ai-main/backend")

from research_engine.paywall_detector import (
    is_likely_paywall, classify_read_level, estimate_content_quality
)
from research_engine.citation_counter import (
    get_quality_boost, classify_citation_level
)
from research_engine.red_team_mode import RedTeamOrchestrator
from research_engine.progress_api import (
    track_job, update_stage, get_progress, complete_job
)


def test_paywall_detector():
    """Test paywall detection logic."""
    print("\\n" + "="*60)
    print("TEST: Paywall Detector")
    print("="*60)

    paywall_html = """<html><body>
    <h1>Subscribe to read</h1>
    <p>This article requires a subscription</p>
    <button>Sign up now</button>
    </body></html>"""

    article_content = """
    Abstract: This study examines bias in AI systems.

    Introduction: Machine learning models are increasingly used in hiring.

    Methods: We analyzed 1000 hiring decisions.

    Results: 23% showed statistical bias against minorities.

    Conclusion: AI bias mitigation is critical.

    References:
    [1] Buolamwini & Gebru, 2018
    """

    # Test 1: Paywall detection
    assert is_likely_paywall(paywall_html) == True, "Should detect paywall"
    assert is_likely_paywall(article_content) == False, "Should detect real content"
    print("✅ Paywall detection works")

    # Test 2: Read level classification
    assert classify_read_level(paywall_html) == "UNAVAILABLE"
    assert classify_read_level(article_content) in ("FULL_TEXT", "ABSTRACT")
    print("✅ Read level classification works")

    # Test 3: Quality scoring
    score_paywall, reason = estimate_content_quality(paywall_html)
    score_article, reason = estimate_content_quality(article_content)
    assert score_paywall < score_article, "Article should score higher than paywall"
    print(f"✅ Quality scoring works (paywall: {score_paywall}, article: {score_article})")


def test_citation_counter():
    """Test citation boost calculations."""
    print("\\n" + "="*60)
    print("TEST: Citation Counter")
    print("="*60)

    # Test quality boost
    assert get_quality_boost(None) == 0.0
    assert get_quality_boost(0) == 0.0
    assert get_quality_boost(10) > get_quality_boost(1)
    assert get_quality_boost(1000) > get_quality_boost(10)
    print("✅ Quality boost calculation works")

    # Test citation levels
    assert classify_citation_level(None) == "UNKNOWN"
    assert classify_citation_level(0) == "UNCITED"
    assert classify_citation_level(10) == "MODERATELY_CITED"
    assert classify_citation_level(500) == "HIGHLY_CITED"
    assert classify_citation_level(10000) == "LANDMARK_PAPER"
    print("✅ Citation level classification works")


def test_red_team_orchestrator():
    """Test red team decision logic."""
    print("\\n" + "="*60)
    print("TEST: Red Team Orchestrator")
    print("="*60)

    orchestrator = RedTeamOrchestrator()

    # QUICK mode: no red team
    assert orchestrator.should_run_red_team("QUICK", 2, 0) == False
    print("✅ QUICK mode skips red team")

    # DEEP mode with contradictory evidence: run red team
    assert orchestrator.should_run_red_team("DEEP", 2, 1, "MIXED") == True
    print("✅ DEEP mode with contradictions runs red team")

    # No calls remaining: skip red team
    assert orchestrator.should_run_red_team("DEEP", 2, 2) == False
    print("✅ Red team skipped when no calls remain")

    # Red team prompt generation
    prompt = orchestrator.red_team_prompt_suffix()
    assert "RED TEAM" in prompt
    assert "weakness" in prompt.lower()
    print("✅ Red team prompt generation works")


def test_progress_api():
    """Test progress tracking API."""
    print("\\n" + "="*60)
    print("TEST: Progress API")
    print("="*60)

    # Start job
    job = track_job("test_job_1", "What is AI?")
    assert job["job_id"] == "test_job_1"
    assert job["current_stage"] == "QUEUED"
    print("✅ Job tracking starts")

    # Update stage
    updated = update_stage("test_job_1", "PLANNING", "Classifying question type")
    assert updated["current_stage"] == "PLANNING"
    assert "PLANNING" in updated["stages_completed"]
    print("✅ Stage update works")

    # Set counts
    update_stage("test_job_1", "DISCOVERY")
    counts = set_counts("test_job_1", web=5, papers=3, books=1, gemini_calls=1)
    assert counts["source_counts"]["web"] == 5
    assert counts["gemini_calls_used"] == 1
    print("✅ Count tracking works")

    # Get progress
    progress = get_progress("test_job_1")
    assert progress["progress_percent"] > 0
    assert progress["question"] == "What is AI?"
    print(f"✅ Progress report works (progress: {progress['progress_percent']}%)")

    # Complete job
    completed = complete_job("test_job_1")
    assert completed["is_complete"] == True
    assert "completed_at" in completed
    print("✅ Job completion works")


def run_all_tests():
    """Run all offline tests."""
    print("\\n" + "🧪 "*30)
    print("OFFLINE TEST SUITE - Zero Gemini Quota")
    print("🧪 "*30)

    try:
        test_paywall_detector()
        test_citation_counter()
        test_red_team_orchestrator()
        test_progress_api()

        print("\\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60)
        print("\\nFeatures verified:")
        print("  ✅ Paywall detection (3 tests)")
        print("  ✅ Citation counting (2 tests)")
        print("  ✅ Red team logic (4 tests)")
        print("  ✅ Progress tracking (5 tests)")
        print("\\nTotal: 14 offline assertions PASSING")
        return True

    except AssertionError as e:
        print(f"\\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
