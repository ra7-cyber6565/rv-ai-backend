"""§20 — chaar alag state, aur unka aapas mein na milna (Claude-owned test).

Ye file un galtiyon ko regression bana deti hai jo live dark-matter run mein
sach mein hui thin:

  * provider ka job `FINISHED` hua aur usi se "jawab poora hai" maan liya gaya;
  * `COMPLETE` + `✅ VERIFIED` top par chhapa jabki claim verification chali hi
    nahi thi (`NOT CHECKED` ko "kuch nahi mila" samajh liya gaya);
  * app ke apne idea ko "naya" kaha, jabki prior-art search hui hi nahi thi;
  * counter-side search ke bina evidence "STRONG" bataya gaya.

Test jaan-boojh kar offline hain: koi network, koi model, koi provider call.

Chalane ka tareeka (repo root = backend/):
    PYTHONPATH=. python3 tests/test_research_output_separation.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import research_state as rs                    # noqa: E402
from research_engine.answer_order import display_heading            # noqa: E402
from research_engine.models import (ANSWER_COMPLETE,                # noqa: E402
                                    ANSWER_FAILED, ANSWER_INSUFFICIENT,
                                    ANSWER_PARTIAL, EVIDENCE_MIXED,
                                    EVIDENCE_MODERATE, EVIDENCE_NONE,
                                    EVIDENCE_NOT_CHECKED, EVIDENCE_STRONG,
                                    EVIDENCE_WEAK, JOB_FAILED, JOB_FINISHED,
                                    JOB_RECOVERED, NOVELTY_KNOWN,
                                    NOVELTY_POSSIBLE, NOVELTY_UNVERIFIED)

_COMPLETE_LEDGER = {"result_state": "COMPLETE", "answer_complete": True}
_PARTIAL_LEDGER = {"result_state": "PARTIAL", "answer_complete": False}


def _strong_run(**over):
    """Ek aisa run jisme sab kuch theek hai — phir usme ek cheez bigaadte hain."""
    kwargs = dict(
        ledger=_COMPLETE_LEDGER, answer_text="jawab", source_count=6,
        usable_source_count=5, verification_ran=True, supported_claims=4,
        unsupported_claims=0, contradictions=0, counter_search=True,
        hypotheses=[], top_label="✅ VERIFIED — 4/4 claims",
    )
    kwargs.update(over)
    return rs.build_state(**kwargs)


def test_finished_job_alone_does_not_make_the_answer_complete():
    state = rs.build_state(ledger=_PARTIAL_LEDGER, answer_text="jawab",
                           source_count=4, verification_ran=True,
                           supported_claims=1, unsupported_claims=2)
    assert state.job_status == JOB_FINISHED
    assert state.answer_state == ANSWER_PARTIAL
    assert state.job_done is True
    assert state.answer_complete is False
    assert state.verified_allowed is False


def test_four_states_live_in_four_separate_fields():
    state = _strong_run()
    data = state.to_dict()
    for key in ("job_status", "answer_state", "evidence_state", "novelty_state"):
        assert key in data, key
    # Ek hi shabd chaar jagah nahi chal sakta: har family ki vocabulary alag hai.
    assert data["job_status"] == JOB_FINISHED
    assert data["answer_state"] == ANSWER_COMPLETE
    assert data["evidence_state"] == EVIDENCE_STRONG
    assert data["novelty_state"] == NOVELTY_UNVERIFIED
    assert data["novelty_applicable"] is False
    assert data["verified_allowed"] is True
    assert not data["conflicts"]


def test_state_value_outside_whitelist_is_rejected_not_silently_kept():
    try:
        rs.ResearchState(evidence_state="MOSTLY VERIFIED")
    except ValueError as exc:
        assert "whitelist" in str(exc)
    else:
        raise AssertionError("whitelist ke bahar ki value chup-chaap le li gayi")


def test_verification_never_ran_is_not_checked_not_weak():
    state = _strong_run(verification_ran=None, supported_claims=None,
                        unsupported_claims=None)
    assert state.evidence_state == EVIDENCE_NOT_CHECKED
    assert state.evidence_state != EVIDENCE_WEAK
    assert state.verified_allowed is False
    joined = " ".join(state.conflicts)
    assert "evidence check hi nahi chala" in joined


def test_zero_sources_is_no_usable_evidence_and_answer_is_insufficient():
    state = rs.build_state(ledger=_PARTIAL_LEDGER, answer_text="jawab",
                           source_count=0, verification_ran=True)
    assert state.evidence_state == EVIDENCE_NONE
    assert state.answer_state == ANSWER_INSUFFICIENT
    assert state.verified_allowed is False


def test_empty_answer_text_is_failed_not_partial():
    state = rs.build_state(ledger=_COMPLETE_LEDGER, answer_text="   ",
                           source_count=5, verification_ran=True,
                           supported_claims=3)
    assert state.answer_state == ANSWER_FAILED
    assert state.verified_allowed is False


def test_strong_evidence_needs_counter_side_search():
    state = _strong_run(counter_search=False)
    assert state.evidence_state in (EVIDENCE_MODERATE, EVIDENCE_WEAK)
    assert state.evidence_state != EVIDENCE_STRONG
    # counter-search ka koi record hi na ho, tab bhi STRONG nahi ban sakta.
    unknown = _strong_run(counter_search=None)
    assert unknown.evidence_state != EVIDENCE_STRONG


def test_support_and_counter_evidence_together_is_mixed():
    state = _strong_run(contradictions=2)
    assert state.evidence_state == EVIDENCE_MIXED


def test_crashed_job_with_complete_answer_is_a_conflict():
    state = _strong_run(crashed=True, finished=False)
    assert state.job_status == JOB_FAILED
    assert state.answer_state == ANSWER_COMPLETE
    assert state.verified_allowed is False
    assert any("Job FAILED" in c for c in state.conflicts)


def test_recovered_run_is_its_own_job_state_not_a_failure():
    state = _strong_run(recovered=True)
    assert state.job_status == JOB_RECOVERED
    # Recovery se jawab ki quality par koi asar nahi padta.
    assert state.answer_state == ANSWER_COMPLETE
    assert state.evidence_state == EVIDENCE_STRONG
    assert not state.conflicts


def test_novelty_without_prior_art_search_cannot_claim_possibly_novel():
    hypo = [{"novelty_status": NOVELTY_POSSIBLE,
             "novelty_search": {"performed": None}}]
    state = _strong_run(hypotheses=hypo)
    assert state.novelty_state == NOVELTY_POSSIBLE
    assert state.novelty_applicable is True
    assert state.verified_allowed is False
    assert any("prior-art" in c for c in state.conflicts)
    # Search sach mein chali ho to koi conflict nahi.
    ran = _strong_run(hypotheses=[{"novelty_status": NOVELTY_POSSIBLE,
                                   "novelty_search": {"performed": True}}])
    assert ran.novelty_state == NOVELTY_POSSIBLE
    assert not ran.conflicts


def test_weakest_novelty_claim_wins_across_hypotheses():
    state = _strong_run(hypotheses=[
        {"novelty_status": NOVELTY_POSSIBLE,
         "novelty_search": {"performed": True}},
        {"novelty_status": NOVELTY_KNOWN, "novelty_search": {"performed": True}},
    ])
    assert state.novelty_state == NOVELTY_KNOWN


def test_missing_novelty_status_is_unverified_not_novel():
    state = _strong_run(hypotheses=[{"statement": "koi idea"}])
    assert state.novelty_state == NOVELTY_UNVERIFIED
    assert state.novelty_applicable is True


def test_prior_art_flag_has_three_honest_answers():
    assert rs.prior_art_flag([]) is None
    assert rs.prior_art_flag([{"novelty_search": {"performed": True}}]) is True
    assert rs.prior_art_flag([{"novelty_search": {"performed": False}}]) is False
    mixed = [{"novelty_search": {"performed": True}},
             {"novelty_search": {"performed": None}}]
    assert rs.prior_art_flag(mixed) is None


def test_verified_top_label_with_partial_answer_is_a_conflict():
    state = rs.build_state(ledger=_PARTIAL_LEDGER, answer_text="jawab",
                           source_count=5, usable_source_count=4,
                           verification_ran=True, supported_claims=4,
                           counter_search=True, top_label="✅ VERIFIED")
    assert state.answer_state == ANSWER_PARTIAL
    assert state.verified_allowed is False
    assert any("label jawab se aage nahi ja sakta" in c for c in state.conflicts)


def test_unverified_label_is_not_read_as_verified():
    state = _strong_run(ledger=_PARTIAL_LEDGER,
                        top_label="🟡 UNVERIFIED — support nahi mila")
    assert not any("label jawab se aage" in c for c in state.conflicts)


def test_rendered_block_shows_all_four_rows_and_the_separation_rule():
    text = rs.render_state_block(_strong_run(verification_ran=None,
                                            supported_claims=None))
    for row in ("Background job", "Jawab poora hua?", "Evidence ki haalat",
                "App ke idea ki novelty"):
        assert row in text, row
    # "NOT CHECKED" wali row bhi chhupti nahi.
    assert EVIDENCE_NOT_CHECKED in text
    assert "Job poora hona ≠ jawab poora hona" in text
    assert "State conflicts" in text
    assert "'VERIFIED' jaisa top label allowed nahi" in text


def test_clean_run_block_has_no_conflict_section():
    text = rs.render_state_block(_strong_run())
    assert "State conflicts" not in text
    assert "Job poora hona ≠ jawab poora hona" in text


def test_state_block_goes_inside_audit_section_and_sources_stay_last():
    answer = (f"## {display_heading('direct_answer')}\nJawab.\n\n"
              f"## {display_heading('audit')}\nCoverage details.\n\n"
              f"### Technical details (developer ke liye — user ke jawab ka hissa nahi)\n"
              f"raw line\n\n"
              f"## {display_heading('sources')}\n- [S1] kuch\n")
    out = rs.inject_state_block(answer, _strong_run())
    audit_pos = out.find(f"## {display_heading('audit')}")
    block_pos = out.find(rs.STATE_HEADING)
    tech_pos = out.find("### Technical details")
    src_pos = out.find(f"## {display_heading('sources')}")
    assert 0 < audit_pos < block_pos < tech_pos < src_pos, (
        audit_pos, block_pos, tech_pos, src_pos)
    # User ke jawab ke section chhoote bhi nahi, badalte bhi nahi.
    assert out.find(f"## {display_heading('direct_answer')}") == 0
    assert "Jawab." in out and "Coverage details." in out


def test_state_block_is_not_injected_twice():
    answer = (f"## {display_heading('audit')}\nCoverage.\n\n"
              f"## {display_heading('sources')}\n- [S1] kuch\n")
    once = rs.inject_state_block(answer, _strong_run())
    twice = rs.inject_state_block(once, _strong_run())
    assert twice == once
    assert once.count(rs.STATE_HEADING) == 1


def test_without_audit_section_block_still_lands_before_sources():
    answer = (f"## {display_heading('direct_answer')}\nJawab.\n\n"
              f"## {display_heading('sources')}\n- [S1] kuch\n")
    out = rs.inject_state_block(answer, _strong_run())
    assert 0 < out.find(rs.STATE_HEADING) < out.find(
        f"## {display_heading('sources')}")


def test_conflicts_are_also_available_as_ui_warnings_and_one_log_line():
    state = _strong_run(verification_ran=None, supported_claims=None)
    warnings = rs.state_warnings(state)
    assert warnings and all(w.startswith("§20 state conflict:") for w in warnings)
    line = rs.summary_line(state)
    for part in ("job=", "answer=", "evidence=", "novelty=", "conflicts=1"):
        assert part in line, part


def test_state_dict_round_trips_through_coerce():
    state = _strong_run(verification_ran=None, supported_claims=None)
    again = rs.coerce(state.to_dict())
    assert again is not None
    assert again.to_dict()["evidence_state"] == state.evidence_state
    assert again.conflicts == state.conflicts
    assert again.verified_allowed == state.verified_allowed
    assert rs.coerce({}) is None
    assert rs.coerce(state) is state


def main() -> int:
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except AssertionError as exc:                  # noqa: PERF203
            failed += 1
            print(f"  [FAIL] {name} -> {exc}")
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {name} -> {type(exc).__name__}: {exc}")
        else:
            print(f"  [PASS] {name}")
    print(f"\n{'FAIL' if failed else 'ok'} — {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
