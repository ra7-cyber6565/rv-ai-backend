"""Evidence-first wiring ka pin + do purane khule taale (Claude-owned).

Kyun ye file bani (2026-08-23, ChatGPT ke P0-A/B/C/D review ke baad):

  1. WIRING FAIL-OPEN. `final_quality_gate.py` ka P0-B check
     `quality_context["evidence_first_required"] is True` par gate hai, aur
     `quality_producers.quality_context()` audit na mile to us key ko `None`
     rakhta hai. Yaani orchestrator ki teen wiring line (manifest banana, audit
     chalana, `quality_context(evidence_first_audit=...)` bhejna) hatt jaayein to
     release-time check CHUP-CHAAP gayab ho jaata hai — aur saare 32 P0 test
     phir bhi green rehte hain, kyunki wo sab audit function ko SEEDHA bulate
     hain, pipeline se nahi. Isliye yahan asli pipeline chalti hai.

  2. "SAME NUMBERS, ALAG MATLAB". `check_c_span` mein threshold pehle
     `_ENTAIL_SIM_WITH_NUM if wanted else _ENTAIL_SIM` tha — claim mein number
     HONE se hi bar 0.30 se 0.12 gir jaata tha, chahe ek bhi number span mein na
     mile. Naapa hua nateeja: 250/170 wala bilkul unrelated moss-survey text
     text-match 0.126 par bhi `genuine_support` + `passes_ae True` le jaata tha.
     Fix (claim_verification.py): relaxed bar sirf `matched_all` par. Ye test us
     fix ka taala hai, dono taraf se (spoof fail + asli support pass).

  3. FLOORS UNPINNED. `_MIN_RELEVANCE 0.25` aur `_MIN_QUALITY 0.35` ko koi test
     nahi pakadta tha, to inhe chupke se giraya ja sakta tha aur kuch red nahi
     hota. Yahan dono ke aas-paas ka behaviour pin hai.

Sab kuch offline aur ₹0 hai: sirf network/Google boundary stub hoti hai.

Chalao:  python3 tests/test_evidence_first_wiring_and_floors.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _path in (_ROOT, _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from research_engine import claim_verification as CV  # noqa: E402
from research_engine import gemini_reasoning  # noqa: E402
from research_engine.models import (EvidencePack, Passage, SourceRecord,  # noqa: E402
                                    SourceType)
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402

# Poore pipeline ka harness pehle se maujood hai (question + fixtures + fake
# Gemini). Usi ko dobara use karte hain — naya fake likhna do sach paida karta.
import test_pipeline_offline as PO  # noqa: E402


# ── production-shaped reader stub ────────────────────────────────────────────
# `test_pipeline_offline.py` ka reader stub sirf `read_level` palat deta hai.
# Asli `content_fetcher.enrich` isse zyada karta hai (P0-D): source ke PURANE
# passages hata kar `provenance="full_text_excerpt"` wale naye passages likhta
# hai. Evidence-first manifest ki strong-eligibility usi capture-depth par tiki
# hai, isliye yahan stub production ka shape copy karta hai — warna test un
# raaston ko chhoo hi nahi paata jinhe hum pin karna chahte hain.
FULL_TEXT = (
    "Randomized controlled trial of intermittent fasting in adults with type 2 "
    "diabetes. Over 12 months, intermittent fasting reduced HbA1c in adults with "
    "type 2 diabetes, and fasting glucose fell in the intervention arm as well. "
    "Sample size was 209 adults. Insulin sensitivity improved in the fasting arm "
    "relative to the control arm, and the authors report that weight loss "
    "explains part of the effect. Hypoglycaemia events were monitored throughout "
    "the intervention period and reported for patients on insulin."
)


def _full_text_reader(pack, max_sources: int = 3, budget_chars: int = 2400):
    entries = []
    for source in pack.sources[:max_sources]:
        source.full_text_chars = len(FULL_TEXT) * 8
        source.read_level = "full_text"
        # P0-D: upgrade se pehle ke passages usi source ke liye purge hote hain.
        pack.passages[:] = [p for p in pack.passages
                            if p.source_id != source.source_id]
        pack.passages.append(Passage(
            source_id=source.source_id, text=FULL_TEXT, locator="p.3",
            provenance="full_text_excerpt",
            read_level_at_capture=source.reading_level()))
        source.snippet = FULL_TEXT[:budget_chars]
        entries.append({"source_id": source.source_id, "ok": True,
                        "chars": len(FULL_TEXT), "reason": "",
                        "title": source.title})
    return {"attempted": len(entries), "succeeded": len(entries), "failed": 0,
            "skipped": 0, "chars_read": sum(e["chars"] for e in entries),
            "note": "full text pada", "entries": entries}


def _run_full_text_pipeline():
    """Asli DeepResearchEngine — sirf network/Google seemaayein stub."""
    fake = PO._FakeGemini()
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="offline-test", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = PO._FakeVectors()
        engine.discovery.discover = PO._fake_discover(PO._records(PO.ON_TOPIC))
        engine.reader.enrich = _full_text_reader
        return engine.research(PO.QUESTION, depth_mode="MAXIMUM"), fake
    finally:
        gemini_reasoning.GeminiReasoning.generate = original


# Ek hi run se saare wiring assert nikal lete hain (pipeline mehnga hai).
_RUN_CACHE = {}


def _cached_run():
    if "res" not in _RUN_CACHE:
        res, fake = _run_full_text_pipeline()
        _RUN_CACHE["res"], _RUN_CACHE["fake"] = res, fake
    return _RUN_CACHE["res"], _RUN_CACHE["fake"]


# ── GUARD 1: evidence-first wiring pipeline mein zinda hai ───────────────────
def test_quality_context_carries_evidence_first_required():
    """`final_quality_gate` ka P0-B check ISI key par gate hai.

    Ye `None` hua (yaani orchestrator ne audit bheja hi nahi) to gate ka
    `critical_claims_preselected_before_generation` check chup-chaap fail-open ho
    jaata hai. Isliye pipeline ke asli output par assert hai, audit function ko
    seedha bula kar nahi.
    """
    res, _fake = _cached_run()
    ctx = res.get("quality_context") or {}
    assert ctx, "quality_context hi result mein nahi hai"
    assert ctx.get("evidence_first_required") is True, (
        "quality_context['evidence_first_required'] True nahi hai "
        f"({ctx.get('evidence_first_required')!r}) — final gate ka P0-B check "
        "fail-open ho jaayega")
    # Counters bhi None nahi hone chahiye, warna audit "check hua hi nahi" ginta.
    for key in ("critical_claims_same_source_ae_passed",
                "critical_claims_preselected_span_matched",
                "critical_claims_preselected_span_unmatched",
                "preselected_evidence_spans_count",
                "preselected_strong_eligible_spans"):
        assert isinstance(ctx.get(key), int), f"{key} int nahi hai: {ctx.get(key)!r}"


def test_verification_carries_audit_and_manifest():
    res, _fake = _cached_run()
    ver = res.get("verification") or {}
    audit = ver.get("evidence_first_audit") or {}
    manifest = ver.get("evidence_first_manifest") or {}
    assert audit.get("schema_version") == "p0b-1", (
        f"audit schema galat/gayab: {audit.get('schema_version')!r}")
    assert audit.get("evidence_first_required") is True
    assert len(str(audit.get("manifest_sha256") or "")) == 64, (
        "audit mein manifest_sha256 nahi hai — manifest audit tak pahuncha hi nahi")
    assert manifest.get("schema_version") == "p0b-1"
    assert manifest.get("manifest_sha256") == audit.get("manifest_sha256"), (
        "manifest aur audit do alag manifest ki baat kar rahe hain")
    assert int(manifest.get("preselected_evidence_spans_count") or 0) >= 1


def test_manifest_block_reaches_analysis_and_synthesis_prompts():
    """Evidence-first ka matlab hai ki manifest DRAFT se pehle prompt mein tha.

    Sirf audit dict hona kaafi nahi — agar block prompt tak nahi pahuncha to
    "evidence pehle chuni gayi thi" ek kaagzi dava hai.
    """
    res, fake = _cached_run()
    manifest = (res.get("verification") or {}).get("evidence_first_manifest") or {}
    stamp = "manifest_sha256=" + str(manifest.get("manifest_sha256") or "x")
    seen = {}
    for label, prompt in fake.prompts:
        seen[label] = ("BEGIN_PRESELECTED_EVIDENCE" in prompt
                       and "END_PRESELECTED_EVIDENCE" in prompt
                       and stamp in prompt)
    for label in ("analysis", "synthesis"):
        assert seen.get(label) is True, (
            f"'{label}' prompt mein preselected-evidence block + wahi "
            f"manifest hash nahi mila (mila: {seen})")


def test_live_manifest_object_does_not_leak_into_result():
    """`_evidence_first_manifest` ek live Python object hai — JSON mein nahi jaana."""
    res, _fake = _cached_run()
    assert "_evidence_first_manifest" not in res
    ver = res.get("verification") or {}
    assert "_evidence_first_manifest" not in ver
    manifest = ver.get("evidence_first_manifest") or {}
    for span in manifest.get("spans") or []:
        assert "passage" not in span, (
            "manifest ke span mein poora source passage aa gaya — compact_dict "
            "sirf sha256 + char count deta hai")
        assert len(str(span.get("passage_sha256") or "")) == 64


def test_full_text_run_reaches_non_vacuous_evidence_first_achievement():
    """Positive control: achievement flag SACH mein kabhi True hota hai.

    Iske bina baaki guards ek aise pipeline par bhi pass ho jaate jahan har
    claim reject ho raha ho. Yahan poora full-text run hai, isliye kam se kam ek
    critical claim ko preselected strong-eligible span se match karna chahiye.
    """
    res, _fake = _cached_run()
    ctx = res.get("quality_context") or {}
    assert int(ctx.get("preselected_strong_eligible_spans") or 0) >= 1, (
        "full-text run mein bhi ek bhi strong-eligible span nahi bana")
    assert int(ctx.get("critical_claims_same_source_ae_passed") or 0) >= 1, (
        "koi bhi critical claim same-source A-E pass nahi kar paaya")
    assert int(ctx.get("critical_claims_preselected_span_unmatched") or 0) == 0, (
        f"supported claim ka span preselected evidence mein nahi mila: "
        f"{ctx.get('evidence_first_failures')}")
    assert ctx.get("critical_claim_preselection_complete") is True
    assert ctx.get("evidence_first_achievement") is True


def test_pipeline_repairs_model_critical_claim_that_failed_predraft_boundary():
    """Prompt ko ignore karne wala model final critical surface control nahi karta."""
    class _UnsafeCriticalFake(PO._FakeGemini):
        def __call__(self, brain, prompt, label=""):
            text = super().__call__(brain, prompt, label)
            if label != "synthesis":
                return text
            next_section = text.find("\n## Research se kya pata chala?")
            assert next_section > 0, "synthesis fixture ka direct section nahi mila"
            return (
                "## Seedha jawab\n"
                "- [SOURCE-REPORTED] Lunar basalt contains olivine crystals and "
                "records ancient volcanic eruptions on the Moon [S1].\n\n"
                + text[next_section + 1:]
            )

    fake = _UnsafeCriticalFake()
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="offline-test", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = PO._FakeVectors()
        engine.discovery.discover = PO._fake_discover(PO._records(PO.ON_TOPIC))
        engine.reader.enrich = _full_text_reader
        result = engine.research(PO.QUESTION, depth_mode="MAXIMUM")
    finally:
        gemini_reasoning.GeminiReasoning.generate = original

    verification = result.get("verification") or {}
    claim_checks = verification.get("claim_checks") or {}
    audit = verification.get("evidence_first_audit") or {}
    enforcement = audit.get("critical_draft_enforcement") or {}
    assert enforcement.get("applied") is True, enforcement
    assert int(enforcement.get("pre_enforcement_critical_claims") or 0) > int(
        enforcement.get("pre_enforcement_same_source_ae_passed") or 0)
    assert "Lunar basalt contains olivine" not in result.get("answer", "")
    assert int(claim_checks.get("unsupported_critical_claims") or 0) == 0
    assert int(audit.get("critical_claims_preselected_span_unmatched") or 0) == 0
    assert audit.get("evidence_first_achievement") is True


def test_pipeline_second_stage_removes_residual_critical_claims_fail_closed():
    """A lying/ineffective first binder cannot leave a partial 3/6 surface."""
    class _UnsafeCriticalFake(PO._FakeGemini):
        def __call__(self, brain, prompt, label=""):
            text = super().__call__(brain, prompt, label)
            if label != "synthesis":
                return text
            next_section = text.find("\n## Research se kya pata chala?")
            assert next_section > 0
            return (
                "## Seedha jawab\n"
                "- [SOURCE-REPORTED] Lunar basalt contains olivine crystals and "
                "records ancient volcanic eruptions on the Moon [S1].\n\n"
                + text[next_section + 1:]
            )

    fake = _UnsafeCriticalFake()
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="offline-test", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = PO._FakeVectors()
        engine.discovery.discover = PO._fake_discover(PO._records(PO.ON_TOPIC))
        engine.reader.enrich = _full_text_reader
        real_binder = engine.synthesizer.bind_evidence_first_critical_sections
        binder_calls = {"count": 0}

        def ineffective_once(text, *, direct_answer, conclusion):
            binder_calls["count"] += 1
            if binder_calls["count"] == 1:
                return text, {
                    "applied": True,
                    "reason": "simulated_ineffective_targeted_rebind",
                    "replaced_sections": ["direct_answer", "conclusion"],
                    "strong_labels_lowered": 0,
                }
            return real_binder(
                text, direct_answer=direct_answer, conclusion=conclusion)

        engine.synthesizer.bind_evidence_first_critical_sections = ineffective_once
        result = engine.research(PO.QUESTION, depth_mode="MAXIMUM")
    finally:
        gemini_reasoning.GeminiReasoning.generate = original

    verification = result.get("verification") or {}
    checks = verification.get("claim_checks") or {}
    enforcement = (
        (verification.get("evidence_first_audit") or {})
        .get("critical_draft_enforcement") or {}
    )
    assert binder_calls["count"] == 2, binder_calls
    assert enforcement.get("second_stage_applied") is True, enforcement
    assert enforcement.get("recovery_mode") == \
        "deterministic_preselected_evidence_surface"
    assert checks.get("critical_claim_coverage_complete") is True, checks
    assert int(checks.get("critical_claims") or 0) > 0
    assert int(checks.get("critical_claims_same_source_ae_passed") or 0) == int(
        checks.get("critical_claims") or 0)
    assert int(checks.get("unsupported_critical_claims") or 0) == 0
    assert int(checks.get("unverifiable_critical_claims") or 0) == 0
    assert "Lunar basalt contains olivine" not in result.get("answer", "")


# ── GUARD 2: "same numbers, alag matlab" support nahi hai ────────────────────
NUM_CLAIM = ("[ESTABLISHED FACT] LaH10 250 K par 170 GPa pressure mein "
             "superconductivity dikhata hai [S1].")

# Wahi do number (250, 170) — par matlab ka koi lena-dena nahi.
SPOOF_SPAN = (
    "The bryophyte survey of the reserve recorded 250 transects during the "
    "monsoon season, and the tallest canopy in the valley measured 170 metres "
    "above the river bed. Sampling followed standard herbarium protocol and "
    "voucher specimens were deposited in the state museum. No physical or "
    "chemical measurements were attempted in this work."
)

REAL_SPAN = (
    "Lanthanum superhydride LaH10 shows superconductivity with a transition "
    "temperature of 250 K at a pressure of 170 GPa, confirmed by resistance and "
    "magnetic susceptibility measurements on multiple samples in a diamond anvil "
    "cell. The isotope effect was also measured for the same sample series."
)


def _strong_pack(text: str, *, relevance: float = 0.90,
                 quality: float = 0.90) -> EvidencePack:
    """Ek aisa pack jahan A/B/D/E jaan-boojh kar poore hain — sirf C ka imtihaan."""
    source = SourceRecord(
        title="Superhydride study", url="https://example.org/lah10",
        snippet=text[:200], connector="pubmed", source_type=SourceType.PAPER,
        peer_reviewed=True, doi="10.1/lah10", year=2024,
        full_text_available=True)
    source.source_id = "S1"
    source.relevance_score = relevance
    source.quality_score = quality
    source.full_text_chars = 6000
    source.read_level = "full_text"
    pack = EvidencePack(question="LaH10 superconductivity 250 K 170 GPa",
                        sources=[source])
    pack.passages = [Passage(source_id="S1", text=text, locator="p.4",
                             provenance="full_text_excerpt",
                             read_level_at_capture="full_text")]
    return pack


def test_same_numbers_wrong_meaning_is_not_genuine_support():
    check = CV.verify_claim(NUM_CLAIM, _strong_pack(SPOOF_SPAN), claim_id="C1",
                            critical=True, section="direct_answer")
    assert check.status("C") == CV.FAIL, (
        "sirf number match hone se C pass ho gaya — "
        f"{check.check('C').detail}")
    assert check.passes_ae is False, "spoof span par same-source A-E pass ho gaya"
    assert check.verdict != "genuine_support", (
        f"unrelated text ko '{check.verdict}' mila")


def test_real_support_with_numbers_still_passes():
    """Ulta taala: fix ne asli numeric support ko nahi maara."""
    check = CV.verify_claim(NUM_CLAIM, _strong_pack(REAL_SPAN), claim_id="C1",
                            critical=True, section="direct_answer")
    assert check.status("C") == CV.PASS, check.check("C").detail
    assert check.passes_ae is True
    assert check.verdict == "genuine_support", check.verdict


def test_relaxed_numeric_threshold_needs_all_numbers_matched():
    """Threshold ka niyam seedha pin: relaxed bar sirf `matched_all` par.

    Pehle `threshold = _ENTAIL_SIM_WITH_NUM if wanted else _ENTAIL_SIM` tha,
    yaani claim mein number hona hi 0.30 ko 0.12 kar deta tha.
    """
    assert CV._ENTAIL_SIM == 0.30, CV._ENTAIL_SIM
    assert CV._ENTAIL_SIM_WITH_NUM == 0.12, CV._ENTAIL_SIM_WITH_NUM
    body = CV.claim_body(NUM_CLAIM)
    wanted = CV._numbers(body)
    assert wanted, "claim mein number hi nahi mile — fixture galat hai"

    spoof_hits = [n for n in wanted if n in SPOOF_SPAN.lower()]
    assert spoof_hits, "spoof span mein ek bhi claim number nahi hai — trap kamzor hai"
    assert len(spoof_hits) < len(wanted), (
        "spoof span saare number match kar raha hai; ye is trap ka case nahi")
    spoof_score = CV._similarity(body, SPOOF_SPAN)
    assert spoof_score < CV._ENTAIL_SIM, (
        f"spoof ka text-match {spoof_score:.4f} strict bar se upar hai — "
        "fixture ab is hole ko naap nahi raha")
    assert spoof_score >= CV._ENTAIL_SIM_WITH_NUM, (
        f"spoof ka text-match {spoof_score:.4f} relaxed bar se bhi neeche hai, "
        "isliye ye test purane bug ko pakad nahi paata")

    span = {"source_id": "S1", "locator": "p.4", "passage": SPOOF_SPAN}
    assert CV.check_c_span(NUM_CLAIM, span).status == CV.FAIL
    ok_span = {"source_id": "S1", "locator": "p.4", "passage": REAL_SPAN}
    assert CV.check_c_span(NUM_CLAIM, ok_span).status == CV.PASS


# ── GUARD 3: B/E ke floors pinned hain ───────────────────────────────────────
def test_floor_constants_are_pinned():
    """Ye do number chupke se giraye ja sakte the aur kuch red nahi hota tha.

    Inhe badalna galat nahi hai — par jaan-boojh kar hona chahiye, isliye taala.
    """
    assert CV._MIN_RELEVANCE == 0.25, CV._MIN_RELEVANCE
    assert CV._MIN_QUALITY == 0.35, CV._MIN_QUALITY
    assert CV._LOW_QUALITY == 0.20, CV._LOW_QUALITY
    assert CV._MIN_TEXT_CHARS == 120, CV._MIN_TEXT_CHARS
    assert CV._LOW_QUALITY < CV._MIN_QUALITY, "quality band ulta ho gaya"


def _one(relevance: float, quality: float) -> SourceRecord:
    source = SourceRecord(
        title="Superhydride study", url="https://example.org/lah10",
        snippet=REAL_SPAN[:200], connector="pubmed",
        source_type=SourceType.PAPER, peer_reviewed=True, doi="10.1/lah10",
        year=2024, full_text_available=True)
    source.source_id = "S1"
    source.relevance_score = relevance
    source.quality_score = quality
    return source


def test_relevance_floor_boundary_behaviour():
    assert CV.check_b([_one(0.25, 0.90)]).status == CV.PASS, "0.25 par B pass hona chahiye"
    assert CV.check_b([_one(0.26, 0.90)]).status == CV.PASS
    below = CV.check_b([_one(0.24, 0.90)])
    assert below.status == CV.FAIL, (
        f"relevance 0.24 (floor 0.25 se neeche) par B ne {below.status} diya")


def test_quality_floor_boundary_behaviour():
    assert CV.check_e([_one(0.90, 0.35)]).status == CV.PASS, "0.35 par E pass hona chahiye"
    assert CV.check_e([_one(0.90, 0.36)]).status == CV.PASS
    # 0.20 < score < 0.35 = "pata nahi", jaan-boojh kar PASS bhi nahi FAIL bhi
    # nahi — isliye yahan sirf "PASS nahi" pin karte hain.
    middle = CV.check_e([_one(0.90, 0.34)])
    assert middle.status != CV.PASS, "quality 0.34 par E pass ho gaya"
    assert CV.check_e([_one(0.90, 0.19)]).status == CV.FAIL


def test_claim_just_below_floors_cannot_pass_same_source_ae():
    """End-to-end: floor ke neeche wala source strong claim ko support nahi karta."""
    good = CV.verify_claim(NUM_CLAIM, _strong_pack(REAL_SPAN, relevance=0.26,
                                                  quality=0.36),
                           claim_id="C1", critical=True, section="direct_answer")
    assert good.passes_ae is True, (
        "floor ke thoda upar wala source bhi block ho gaya — floor galat jagah hai")
    weak = CV.verify_claim(NUM_CLAIM, _strong_pack(REAL_SPAN, relevance=0.24,
                                                  quality=0.34),
                           claim_id="C1", critical=True, section="direct_answer")
    assert weak.passes_ae is False, (
        "relevance 0.24 + quality 0.34 par bhi same-source A-E pass ho gaya")
    assert weak.verdict != "genuine_support", weak.verdict


def _main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print("\nsab pass" if not failed else f"\n{failed} test fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
