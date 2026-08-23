"""Integration regressions for reconciling P0-A with latest-main claim audits."""
from __future__ import annotations

from research_engine import claim_verification as CV
from research_engine.models import EvidencePack, Passage, SourceRecord, SourceType


CLAIM = (
    "Lanthanum hydride LaH10 shows a superconducting transition temperature "
    "of 250 K at a pressure of 170 GPa"
)
SUPPORT = (
    "Electrical resistance measurements reproducibly show that lanthanum hydride "
    "LaH10 has a superconducting transition temperature of 250 K at 170 GPa. "
    "Magnetic susceptibility measurements independently track the same transition. "
)


def _pack() -> EvidencePack:
    source = SourceRecord(
        title="Reconciliation fixture",
        url="https://example.org/reconcile",
        snippet="",
        source_type=SourceType.PAPER,
        connector="fixture",
        read_level="full_text",
        full_text_chars=40000,
        peer_reviewed=True,
        quality_score=0.90,
        relevance_score=0.95,
        source_id="S1",
    )
    pack = EvidencePack(sources=[source])
    pack.passages = [Passage(source_id="S1", text=SUPPORT * 3, locator="p.42 ¶3")]
    return pack


def test_same_source_grounding_keeps_latest_access_and_quality_audit_labels():
    pack = _pack()
    line = f"[ESTABLISHED FACT] {CLAIM} [S1]"
    checked = CV.verify_claim(line, pack, claim_id="CL001", critical=True)
    data = checked.to_dict()

    assert checked.passes_ae is True
    assert data["same_source_ae_passed"] is True
    assert data["supporting_source_id"] == "S1"
    assert data["canonical_evidence_span"]["locator"] == "p.42 ¶3"
    assert data["access_depth"]
    assert data["source_quality"]
    assert "peer-reviewed" in data["source_quality"]

    report_row = CV.VerificationReport(claims=[checked]).critical_claim_spans()[0]
    assert report_row["same_source_ae_passed"] is True
    assert report_row["canonical_span"]["locator"] == "p.42 ¶3"
    assert report_row["access_depth"]
    assert report_row["source_quality"]


def test_unlabelled_final_conclusion_second_pass_survives_reconciliation():
    pack = _pack()
    answer = (
        "## Final conclusion\n"
        f"{CLAIM}, reproducibly measured in the cited experiment [S1]\n"
    )
    report = CV.verify_answer(answer, pack)

    assert report.total == 1
    checked = report.claims[0]
    assert checked.critical is True
    assert checked.epistemic_type == "unlabelled"
    assert checked.passes_ae is True
    assert checked.supporting_source_id == "S1"
