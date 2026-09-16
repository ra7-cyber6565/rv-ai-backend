import copy
import json
from pathlib import Path

import pytest

from research_engine.capability_registry import ProofKind
from research_engine.debate_independence_attestor import (
    DebateJudgeSpec,
    _guarded_judge,
    attest_debate_independence,
    build_debate_independence_execution_receipt,
    validate_debate_independence_receipt,
)
from research_engine.maturity_proof import ProofLedger
from research_engine.scientist_society import TournamentCandidate


ROOT = Path(__file__).resolve().parents[1]
KEY = b"D" * 32
NOW = 2_000_000_000


def _candidates():
    return (
        TournamentCandidate("H1", "candidate one", ("E1", "E2"), "author-a"),
        TournamentCandidate("H2", "candidate two", ("E2", "E3"), "author-b"),
        TournamentCandidate("H3", "candidate three", ("E3", "E4"), "author-c"),
    )


def _judge(winner="A", confidence=0.75):
    def run(packet):
        assert "author_agent_id" not in json.dumps(packet)
        assert set(packet["candidate_A"]) == {"hypothesis_id", "statement", "evidence_ids"}
        assert set(packet["candidate_B"]) == {"hypothesis_id", "statement", "evidence_ids"}
        evidence = sorted(
            set(packet["candidate_A"]["evidence_ids"])
            | set(packet["candidate_B"]["evidence_ids"])
        )
        return {
            "winner": winner,
            "confidence": confidence,
            "reasons": ["external blinded assessment"],
            "evidence_ids": evidence,
        }
    return run


def _judges(*, third_winner="A"):
    return (
        DebateJudgeSpec("judge-a", "runner-a", "family-a", "domain-a", _judge("A")),
        DebateJudgeSpec("judge-b", "runner-b", "family-b", "domain-b", _judge("B")),
        DebateJudgeSpec("judge-c", "runner-c", "family-c", "domain-c", _judge(third_winner)),
    )


def _write(tmp_path, value, name="debate.json"):
    path = tmp_path / name
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def test_external_judges_are_blinded_and_disagreement_does_not_fake_truth(tmp_path):
    receipt = build_debate_independence_execution_receipt(
        repo_root=ROOT,
        candidates=_candidates(),
        judges=_judges(third_winner="A"),
        created_at_epoch=NOW,
        repetitions=2,
    )
    assert receipt["candidate_authorship_blinded"] is True
    assert receipt["external_independence_structure_satisfied"] is True
    assert receipt["observer_asserted_independence_domains"] is True
    assert receipt["hidden_provider_dependencies_ruled_out"] is False
    assert receipt["judge_agreement_required"] is False
    assert receipt["agreement_proves_truth"] is False
    assert receipt["truth_proven"] is False
    assert len(receipt["judge_manifest"]) == 3
    assert len({row["independence_domain"] for row in receipt["judge_manifest"]}) == 3
    assert all("author_agent_id" not in json.dumps(row) for row in receipt["runs"])

    winners = {
        run["winner_id"]
        for judge in receipt["runs"]
        for run in judge["runs"]
        if run["winner_id"] is not None
    }
    assert len(winners) >= 2  # Independent judges may genuinely disagree.

    validated = validate_debate_independence_receipt(
        _write(tmp_path, receipt), repo_root=ROOT, now=NOW + 1
    )
    assert validated.run_count == 6
    assert len(validated.candidate_commitment) == 64
    assert len(validated.judge_manifest_hash) == 64


def test_guard_rejects_any_future_author_metadata_leak():
    spec = _judges()[0]
    guarded = _guarded_judge(spec, [])
    with pytest.raises(ValueError, match="leaked candidate author identity"):
        guarded({
            "round": 1,
            "candidate_A": {
                "hypothesis_id": "H1",
                "statement": "x",
                "evidence_ids": ["E1"],
                "author_agent_id": "secret",
            },
            "candidate_B": {
                "hypothesis_id": "H2",
                "statement": "y",
                "evidence_ids": ["E2"],
            },
        })


def test_three_distinct_external_boundaries_are_mandatory():
    base = list(_judges())
    with pytest.raises(ValueError, match="3..12 external judges"):
        build_debate_independence_execution_receipt(
            repo_root=ROOT,
            candidates=_candidates(),
            judges=base[:2],
            created_at_epoch=NOW,
        )

    duplicate_domain = [base[0], base[1], DebateJudgeSpec(
        "judge-c", "runner-c", "family-c", "domain-a", _judge("A")
    )]
    with pytest.raises(ValueError, match="distinct independence_domain"):
        build_debate_independence_execution_receipt(
            repo_root=ROOT,
            candidates=_candidates(),
            judges=duplicate_domain,
            created_at_epoch=NOW,
        )

    duplicate_family = [base[0], base[1], DebateJudgeSpec(
        "judge-c", "runner-c", "family-a", "domain-c", _judge("A")
    )]
    with pytest.raises(ValueError, match="distinct model_family"):
        build_debate_independence_execution_receipt(
            repo_root=ROOT,
            candidates=_candidates(),
            judges=duplicate_family,
            created_at_epoch=NOW,
        )


def test_receipt_tampering_staleness_and_truth_overclaim_fail_closed(tmp_path):
    original = build_debate_independence_execution_receipt(
        repo_root=ROOT,
        candidates=_candidates(),
        judges=_judges(),
        created_at_epoch=NOW,
    )

    stale = _write(tmp_path, original, "stale.json")
    with pytest.raises(ValueError, match="stale"):
        validate_debate_independence_receipt(
            stale, repo_root=ROOT, now=NOW + 2 * 60 * 60 + 1
        )

    tampered = copy.deepcopy(original)
    tampered["judge_manifest"][0]["independence_domain"] = "forged-domain"
    with pytest.raises(ValueError, match="judge manifest hash"):
        validate_debate_independence_receipt(
            _write(tmp_path, tampered, "tampered.json"), repo_root=ROOT, now=NOW + 1
        )

    overclaim = copy.deepcopy(original)
    overclaim["truth_proven"] = True
    overclaim_payload = {key: value for key, value in overclaim.items() if key != "report_hash"}
    import hashlib
    overclaim["report_hash"] = hashlib.sha256(
        json.dumps(
            overclaim_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="must not claim truth"):
        validate_debate_independence_receipt(
            _write(tmp_path, overclaim, "overclaim.json"), repo_root=ROOT, now=NOW + 1
        )


def test_trusted_attestor_mints_only_capability_19_independent_proof(tmp_path):
    receipt = build_debate_independence_execution_receipt(
        repo_root=ROOT,
        candidates=_candidates(),
        judges=_judges(),
        created_at_epoch=NOW,
    )
    receipt_path = _write(tmp_path, receipt)
    ledger_path = tmp_path / "proofs.jsonl"

    result = attest_debate_independence(
        repo_root=ROOT,
        execution_receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-1",
        now=NOW + 1,
    )
    assert result.receipts_added == 1
    assert result.receipts_reused == 0
    assert result.hidden_provider_dependencies_ruled_out is False
    assert result.truth_proven is False
    assert result.audit.audit_valid is True

    ledger = ProofLedger(str(ledger_path), integrity_key=KEY)
    rows = [row for row in ledger._events() if row.get("event_type") == "ADD"]  # noqa: SLF001
    assert len(rows) == 1
    assert rows[0]["capability_id"] == 19
    assert rows[0]["proof_kind"] == ProofKind.INDEPENDENT.value
    assert rows[0]["subject"] == "capability-19-independent-validation"
    assert rows[0]["verifier"] == "trusted-independent-validator"
    assert rows[0]["reference"].startswith("independent:c19:")


def test_existing_ledger_requires_anchor_continuity_and_same_receipt_is_idempotent(tmp_path):
    receipt = build_debate_independence_execution_receipt(
        repo_root=ROOT,
        candidates=_candidates(),
        judges=_judges(),
        created_at_epoch=NOW,
    )
    receipt_path = _write(tmp_path, receipt)
    ledger_path = tmp_path / "proofs.jsonl"
    first = attest_debate_independence(
        repo_root=ROOT,
        execution_receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-2",
        now=NOW + 1,
    )

    with pytest.raises(ValueError, match="prior trusted anchor"):
        attest_debate_independence(
            repo_root=ROOT,
            execution_receipt_path=receipt_path,
            ledger_path=ledger_path,
            integrity_key=KEY,
            observation_id="campaign-2",
            now=NOW + 2,
        )

    second = attest_debate_independence(
        repo_root=ROOT,
        execution_receipt_path=receipt_path,
        ledger_path=ledger_path,
        integrity_key=KEY,
        observation_id="campaign-2",
        now=NOW + 2,
        prior_anchor_token=first.anchor_token,
        prior_revision=first.revision,
    )
    assert second.receipts_added == 0
    assert second.receipts_reused == 1
