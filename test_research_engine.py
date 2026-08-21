"""
test_research_engine.py — OFFLINE test suite (0 Gemini calls, 0 network needed)

Kaise chalayein (Windows PowerShell):
    cd C:\\Users\\intel\\Music\\infinity-research-ai-main\\infinity-research-ai-main\\backend
    venv\\Scripts\\activate
    python test_research_engine.py

Ye suite sirf pure logic test karti hai, isliye API quota bilkul kharch nahi
hoti. Ye GUARANTEE code se enforce hui hai, mere bharose par nahi:

  * Test 10 mein `GeminiReasoning.generate` ko monkeypatch karke block kiya
    jaata hai. Yani .env mein API key hone par bhi ek bhi call nahi jaayegi.
  * Test 10 mein discovery aur vector search bhi stub hain — koi network
    request nahi jaati, isliye result kabhi rate limit se flaky nahi hota.

Isse suite har machine par same result deti hai aur seconds mein khatam hoti hai.
Live API / live Gemini check ke liye alag script hai: `test_connectors.py`
(connector field mapping, 0 Gemini calls) aur Swagger par `/deep-research`
(asli end-to-end, jo quota use karta hai — wahi asli integration test hai).
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import pathlib
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import types
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from research_engine.citation import CitationEngine
from research_engine.consensus_gate import CONSENSUS_UNAVAILABLE
from research_engine.contradiction import ContradictionEngine
from research_engine.critic import Critic
from research_engine.dedup import DeduplicationEngine
from research_engine.depth import get_depth_config
from research_engine.evidence import EvidenceEngine
from research_engine.hypothesis import HypothesisEngine
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.planner import ResearchPlanner
from research_engine.processing import DocumentProcessor, TranscriptProcessor
from research_engine.relevance import RelevanceEngine
from research_engine.research_memory import ResearchMemory
from research_engine.synthesizer import FinalSynthesizer
from research_engine.verification import VerificationEngine

PASSED: list = []
FAILED: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append((name, detail))
        print(f"  [FAIL] {name} — {detail}")


def section(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


# ── fixtures ─────────────────────────────────────────────────────────────────
def sample_sources() -> list:
    return [
        SourceRecord(
            title="Gender Shades: Intersectional Accuracy Disparities in Commercial "
                  "Gender Classification",
            url="https://proceedings.mlr.press/v81/buolamwini18a.html",
            snippet="Commercial gender classification systems show significantly higher "
                    "error rates for darker-skinned women, up to 34.7% error, which "
                    "confirms systematic bias in training data.",
            connector="openalex", source_type=SourceType.PAPER,
            authors=["Buolamwini", "Gebru"], year=2018, doi="10.5555/gs2018",
            peer_reviewed=True, citation_count=4200,
        ),
        SourceRecord(
            title="Dissecting racial bias in an algorithm used to manage the health "
                  "of populations",
            url="https://www.science.org/doi/10.1126/science.aax2342",
            snippet="The algorithm reduced the number of Black patients identified for "
                    "extra care by more than half; bias increased because cost was used "
                    "as a proxy for illness.",
            connector="crossref", source_type=SourceType.PAPER,
            authors=["Obermeyer"], year=2019, doi="10.1126/science.aax2342",
            peer_reviewed=True, citation_count=3100,
        ),
        # Same paper, different aggregator → dedup ka kaam
        SourceRecord(
            title="Dissecting racial bias in an algorithm used to manage the health of "
                  "populations.",
            url="https://pubmed.ncbi.nlm.nih.gov/31649194/",
            snippet="Duplicate record of the same study from a different database.",
            connector="pubmed", source_type=SourceType.PAPER,
            year=2019, doi="10.1126/science.aax2342", peer_reviewed=True,
        ),
        SourceRecord(
            title="Study finds no significant association between training data "
                  "composition and downstream discrimination",
            url="https://example-journal.org/no-effect-study",
            snippet="Across 12 deployments the authors report no significant effect and "
                    "no association between dataset composition and measured "
                    "discrimination; only 12% of cases showed disparity.",
            connector="doaj", source_type=SourceType.PAPER,
            year=2023, peer_reviewed=True,
        ),
        SourceRecord(
            title="Algorithmic bias — Wikipedia",
            url="https://en.wikipedia.org/wiki/Algorithmic_bias",
            snippet="Algorithmic bias describes systematic and repeatable errors that "
                    "create unfair outcomes.",
            connector="wikipedia", source_type=SourceType.ENCYCLOPEDIA,
            is_primary=False,
        ),
        SourceRecord(
            title="my thoughts on ai bias lol",
            url="https://www.reddit.com/r/ai/comments/xyz/",
            snippet="honestly i think the models are just fine, people overreact",
            connector="duckduckgo", source_type=SourceType.WEB,
        ),
    ]


QUESTION = "kya AI training data ka bias real-world discrimination badha sakta hai?"


# ── 1. planner ───────────────────────────────────────────────────────────────
def test_planner():
    section("1. ResearchPlanner (Spec 1)")
    planner = ResearchPlanner()
    cls = planner.classify(QUESTION)
    check("multi-type detection", len(cls["all_detected_types"]) >= 2,
          str(cls["all_detected_types"]))
    check("fields nikle", len(cls["relevant_fields"]) >= 2, str(cls["relevant_fields"]))

    cleaned = planner.clean_query(QUESTION)
    check("filler hata", "kya" not in cleaned.split() and len(cleaned) > 10, cleaned)
    check("khaali query nahi", bool(planner.clean_query("kya hai")), "empty")

    round2 = planner.search_queries(QUESTION, cls, round_no=2)
    round3 = planner.search_queries(QUESTION, cls, round_no=3)
    check("round 2 expand hui", len(round2) >= 2, str(round2))
    check("round 3 contradiction angle", any("contradict" in q or "criticism" in q
                                             for q in round3), str(round3))

    plan = planner.plan(QUESTION, get_depth_config("DEEP"))
    check("connector plan bana", plan["connectors"]["web"] is True
          and len(plan["connectors"]["papers"]) >= 2, str(plan["connectors"]))
    check("sub-questions bane", len(plan["sub_questions"]) >= 3,
          str(len(plan["sub_questions"])))
    check("counter-evidence sub-question hai",
          any("KHILAF" in s for s in plan["sub_questions"]), str(plan["sub_questions"]))

    # Orchestrator round 2/3 mein poora `plan` dict paas karta hai (cls ka
    # superset). Ye kaam karna chahiye, aur adhoore dict par bhi girna nahi
    # chahiye — warna ek missing key poora research round kha jaata hai.
    from_plan = planner.search_queries(QUESTION, plan, round_no=2)
    check("plan dict ko cls ki jagah dene par bhi round 2 banti hai",
          from_plan == round2, f"{from_plan} != {round2}")
    check("adhoore cls dict par round 2/3 crash nahi karti",
          planner.search_queries(QUESTION, {}, round_no=2)
          and planner.search_queries(QUESTION, {"relevant_fields": []}, round_no=3),
          "KeyError")
    check("adhoore cls dict par sub-questions aur connector plan bhi chalte hain",
          len(planner.sub_questions(QUESTION, {})) >= 3
          and planner.connector_plan({}, get_depth_config("DEEP"))["web"] is True,
          "KeyError")


# ── 2. dedup + relevance ─────────────────────────────────────────────────────
def test_dedup_and_relevance():
    section("2. Dedup + Relevance (Spec 6, 7)")
    dedup = DeduplicationEngine()
    unique = dedup.deduplicate(sample_sources())
    check("DOI duplicate hata", len(unique) == 5, f"{len(unique)} bache")

    report = dedup.independence_report(unique)
    check("independence count sahi",
          0 < report["independent_voices"] <= report["total_sources"] == len(unique),
          str({k: v for k, v in report.items() if k != "note"}))

    engine = RelevanceEngine(dedup=dedup)
    ranked = engine.rank(sample_sources(), QUESTION, max_sources=4)
    check("ranking ne top 4 chune", len(ranked) == 4, str(len(ranked)))
    check("peer-reviewed paper top par", ranked[0].peer_reviewed is True,
          f"{ranked[0].connector}: {ranked[0].title[:40]}")
    check("reddit low-trust filter hua",
          not any("reddit.com" in (s.url or "") for s in ranked),
          str([s.domain for s in ranked]))

    sufficiency = engine.is_evidence_sufficient(ranked, require_scholarly=True)
    check("sufficiency report bana", "sufficient" in sufficiency, str(sufficiency))


# ── 3. evidence pack + citations ─────────────────────────────────────────────
def test_evidence_and_citations():
    section("3. EvidencePack + CitationEngine (Spec 7, 14)")
    evidence = EvidenceEngine()
    pack = evidence.build_pack(
        question=QUESTION, doc_records=[], external_records=sample_sources(),
        max_sources=5, connectors_searched=["openalex", "crossref", "doaj"],
        rounds_run=2)
    check("pack bana", len(pack.sources) >= 4, str(len(pack.sources)))
    check("IDs assign hui", all(s.source_id.startswith("S") for s in pack.sources),
          str([s.source_id for s in pack.sources]))
    check("prompt block mein IDs hain", "[S1]" in pack.to_prompt_block(),
          pack.to_prompt_block()[:80])

    citations = CitationEngine()
    fake_answer = (
        "## Factual Findings\n"
        "- [ESTABLISHED] Commercial gender classification me error rate darker-skinned "
        "women ke liye zyada tha [S1].\n"
        "- [STRONG EVIDENCE] Health algorithm ne Black patients ko kam identify kiya "
        "[S2].\n"
        "- [ESTABLISHED] AI bias se poori duniya me 80% hiring decisions galat hoti "
        "hain.\n"
        "- [EVIDENCE] Ek aur study ne yahi baat kahi [S99].\n"
        "- [INFERENCE] Isse lagta hai ki data composition matter karta hai "
        "[NO-SOURCE].\n"
    )
    report = citations.verify(fake_answer, pack)
    check("valid citations mili", len(report.cited) >= 2, str(report.cited))
    check("hallucinated [S99] pakda", "S99" in report.invalid_ids,
          str(report.invalid_ids))
    check("bina source wala ESTABLISHED claim pakda",
          any("80%" in c for c in report.ungrounded_claims),
          str(report.ungrounded_claims))
    check("[NO-SOURCE] marker gina", report.no_source_markers >= 1,
          str(report.no_source_markers))

    annotated = citations.annotate(fake_answer, pack)
    check("invalid citation answer me mark hui", "S99" in annotated
          and "INVALID" in annotated.upper(),
          annotated[annotated.find("S99") - 40:annotated.find("S99") + 40])

    biblio = citations.render_bibliography(pack, cited_ids=["S1"])
    check("bibliography bani (pack se)", "S1" in biblio and "http" in biblio,
          biblio[:100])
    check("cited source par tick laga", "✓cited" in biblio, biblio[:120])
    check("bibliography dict-list se bhi bani",
          "S1" in citations.render_bibliography(report.cited), "dict input toota")

    # ── honesty_report (Spec 2 + 7) — ye line kabhi over/under-claim na kare ──
    honesty = citations.honesty_report(report, pack)
    check("honesty report bana", "Sources retrieved" in honesty, honesty[:80])
    check("hallucinated ID honesty report mein bhi dikhi",
          "S99" in honesty, honesty)
    check("bina source wale claim ki ginti report mein hai",
          "no source attached" in honesty, honesty)
    # Pehle yahan ek FIXED line thi ("poora full text nahi padha") jo ContentFetcher
    # aane ke baad jhooth ban sakti thi. Ab reading depth asli counts se aati hai.
    check("reading depth asli ginti se aata hai (fixed line nahi)",
          "Reading depth (asli ginti):" in honesty
          and pack.reading_note()[:40] in honesty, honesty)
    # grounded ratio ka denominator hallucinated IDs ko bhi ginta hai, warna
    # 2 valid + 1 fake = "100%" jaisa jhooth chhap jaata.
    check("citation percentage ka denominator invalid IDs ko ginta hai",
          f"({len(report.cited)} valid / {len(report.cited) + 1} total)" in honesty
          and "100%" not in honesty, honesty)

    # Jab sach mein sab full text padha ho, tab "poora text NAHI padha" na likhe
    full_pack = evidence.build_pack(
        question=QUESTION, doc_records=evidence.records_from_retrieval({
            "context": "[Source: mera_paper.pdf, Page 1]\nAI bias par poora "
                       "chapter, jo upload ke waqt process hua tha.",
            "sources": [{"file": "mera_paper.pdf", "page": "1"}]}),
        external_records=[], max_sources=3)
    full_note = full_pack.reading_note()
    check("sab full_text hone par 'poora text NAHI padha' nahi likhta",
          "NAHI padha" not in full_note and "full text" in full_note, full_note)

    level = evidence.grade_evidence(pack, evidence.extract_claims(fake_answer, pack))
    check("evidence level asli signals se bana", isinstance(level, str) and level,
          level)
    print(f"     → evidence_level: {level}")
    return pack, fake_answer


# ── 4. contradictions ────────────────────────────────────────────────────────
def test_contradictions(pack):
    section("4. ContradictionEngine (Spec 8)")
    engine = ContradictionEngine()
    found = engine.detect(pack)
    kinds = {c.kind for c in found}
    check("contradiction detect hui", len(found) >= 1,
          str([c.summary for c in found]))
    check("stance conflict pakda", "STANCE" in kinds or "NUMERIC" in kinds, str(kinds))

    consensus = engine.consensus_report(pack, found)
    # EXPECTATION JAAN-BOOJH KAR BADLI GAYI (§11, 2026-08-20): pehle yahan sirf
    # chaar level (APPARENT CONSENSUS / DISPUTED / LEANING / NO CLEAR STANCE)
    # allowed the, yaani consensus HAMESHA ban jaata tha. Naya niyam: chhe
    # shartein poori na hon to level banta hi nahi — "Consensus evaluate nahi
    # kiya ja saka." Is fake pack mein reasoning passes hi nahi chale, isliye
    # blocked hona hi SAHI jawab hai.
    check("consensus report bana", consensus["level"] in
          ("APPARENT CONSENSUS", "DISPUTED", "LEANING", "NO CLEAR STANCE",
           CONSENSUS_UNAVAILABLE),
          str(consensus["level"]))
    if consensus["level"] == CONSENSUS_UNAVAILABLE:
        check("gate ne wajah likhi (§11)", bool(consensus["unmet_conditions"]),
              str(consensus["gate"]["unmet"]))
        check("chhe shartein check hui", len(consensus["gate"]["checks"]) == 6,
              str(len(consensus["gate"]["checks"])))
        check("raw level developer ke liye bacha hua hai",
              bool(consensus.get("level_if_gate_passed")))
    else:
        check("gate pass hone par hi level bana", consensus["gate_passed"] is True)
    print(f"     → consensus: {consensus['level']}, conflicts: {len(found)}")
    return [c.to_dict() for c in found], consensus


# ── 5. verification ──────────────────────────────────────────────────────────
def test_verification(pack):
    section("5. VerificationEngine (Spec 11)")
    verifier = VerificationEngine()

    checks = verifier.check_math("Total 45 x 3 = 135 aur 20% of 200 = 50 hota hai.")
    passed = [c for c in checks if c.passed]
    failed = [c for c in checks if c.passed is False]
    check("sahi math pass hui", any("135" in c.name for c in passed), str(checks))
    check("galat math pakdi", any("50" in c.name for c in failed), str(failed))

    warnings = verifier.check_overclaims(
        "Ye clinically proven hai aur 100% effective cure hai.", has_hypothesis=True)
    check("overclaim language pakdi", len(warnings) >= 1, str(warnings))

    report = verifier.verify(
        "Result: 10 + 5 = 15. Ye hypothesis hai.", pack,
        citation_ok=True, ungrounded_count=0,
        hypotheses=[{"statement": "Naya compound synthesis se cell line par asar hoga",
                     "how_to_test": "in vitro assay with control group"}])
    check("physical test requirement pakdi",
          report.status == "REQUIRES PHYSICAL TEST", report.status)
    check("experiment design mila", len(report.required_tests) >= 1,
          str(report.required_tests)[:120])
    print(f"     → verification status: {report.status}")
    return report.to_dict()


# ── 6. critic + hypothesis parsing ───────────────────────────────────────────
def test_critic_and_hypothesis():
    section("6. Critic + HypothesisEngine (Spec 9, 10)")
    critic_output = """## Weaknesses
- Sample size chhota tha, sirf 12 deployments.
- Correlation ko causation maana gaya hai.

## Missing Evidence
- Longitudinal data 5 saal ka nahi hai.

## Alternative Explanations
- Deployment context ka farq bhi wahi result de sakta hai.

## Hypothesis 1
- Statement: Dataset ke label noise se downstream disparity badhti hai
- Reasoning: [S1] me error rate subgroup wise badla, isliye label quality suspect hai
- Supporting evidence: [S1], [S2]
- Contradicting evidence: [S4] no effect batata hai
- Novelty: label noise angle ko in studies me alag se test nahi kiya gaya
- Prediction: clean-label training par subgroup error gap 30% se zyada girega
- How to test: same model ko clean-label aur noisy-label dataset par train karke
  subgroup error gap measure karo, control group ke saath
- Risks: galat conclusion se deployment rok dena
- Confidence: MEDIUM
"""
    critique = Critic().parse(critic_output)
    check("weaknesses parse hui", len(critique.weaknesses) >= 2,
          str(critique.weaknesses))
    check("missing evidence parse hui", len(critique.missing_evidence) >= 1,
          str(critique.missing_evidence))
    check("alternative explanation parse hui",
          len(critique.alternative_explanations) >= 1,
          str(critique.alternative_explanations))

    engine = HypothesisEngine()
    hypotheses = engine.parse(critic_output)
    check("hypothesis parse hui", len(hypotheses) == 1, str(len(hypotheses)))
    if hypotheses:
        h = hypotheses[0]
        check("status forced UNTESTED", h.to_dict()["status"] == "UNTESTED HYPOTHESIS",
              h.status)
        check("test design mila", h.is_testable, h.how_to_test[:60])
        check("disclaimer laga", "untested" in h.to_dict()["disclaimer"].lower(),
              h.to_dict()["disclaimer"][:60])
        # Spec §10 ka 8th field — prediction (isi se hypothesis falsifiable banti hai)
        # Note: prediction ab structured ho sakta hai (dict) ya text (backward compat)
        pred_text = h.prediction_text if hasattr(h, 'prediction_text') else ""
        check("prediction field parse hui (Spec §10)",
              "subgroup error gap" in pred_text, pred_text[:60] if pred_text else "N/A")
        check("prediction to_dict mein bhi jaati hai",
              h.to_dict().get("prediction") is not None
              and h.to_dict().get("has_prediction") is True, str(h.to_dict().get("prediction"))[:60])
        check("prompt Gemini se prediction maangta hai",
              "Prediction:" in engine.prompt("q", "analysis", EvidencePack(), {})
              and "Prediction:" in engine.prompt_appendix(), "prompt mein prediction nahi")

    untestable = engine.parse("## Hypothesis 1\n- Statement: kuch to hoga\n")
    check("untestable hypothesis flag hui",
          len(engine.honesty_check(untestable)) >= 1, str(engine.honesty_check(untestable)))
    no_pred = engine.parse(
        "## Hypothesis 1\n- Statement: label noise se disparity badhti hai\n"
        "- How to test: clean vs noisy label training with control group and "
        "subgroup measurement\n")
    check("prediction na ho to honesty_check bolti hai",
          any("prediction" in w for w in engine.honesty_check(no_pred)),
          str(engine.honesty_check(no_pred)))
    return [h.to_dict() for h in hypotheses], critique.to_dict()


# ── 7. processing ────────────────────────────────────────────────────────────
def test_processing():
    section("7. Processing pipeline (Spec 4, 5)")
    temp_dir = tempfile.mkdtemp(prefix="ire_test_")
    try:
        vtt_path = os.path.join(temp_dir, "lecture.vtt")
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write("""WEBVTT

00:00:01.000 --> 00:00:04.000
Aaj hum training data bias ke baare mein baat karenge.

00:02:30.000 --> 00:02:36.000
Gender Shades study ne error rate ka farq dikhaya tha.

00:05:10.000 --> 00:05:15.000
Iska matlab dataset composition important hai.
""")
        result = TranscriptProcessor().process_file(vtt_path, chunk_seconds=120)
        check("vtt parse hui", result["ok"], result.get("error", ""))
        check("timestamped chunks bane", len(result["chunks"]) >= 2,
              str([c["locator"] for c in result["chunks"]]))
        check("citation header timestamp ke saath",
              "2:30" in result["text"] or "2:30" in str(result["chunks"]),
              str(result["chunks"][1]["header"]) if len(result["chunks"]) > 1 else "")

        txt_path = os.path.join(temp_dir, "notes.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("Pehla paragraph.\n\n" + ("Doosra paragraph. " * 120))
        doc = DocumentProcessor().process(txt_path)
        check("txt process hui", doc["ok"] and len(doc["chunks"]) >= 2,
              f"{doc.get('error')} chunks={len(doc['chunks'])}")

        missing = DocumentProcessor().process(os.path.join(temp_dir, "nahi.pdf"))
        check("missing file par crash nahi", missing["ok"] is False
              and "nahi mili" in missing["error"], str(missing["error"]))

        weird = os.path.join(temp_dir, "file.xyz")
        open(weird, "w").close()
        unsupported = DocumentProcessor().process(weird)
        check("unsupported format honestly bataya",
              unsupported["ok"] is False and "supported" in unsupported["error"],
              unsupported["error"][:60])

        # .srt bhi chalni chahiye — /upload-document isi raste se jaata hai
        srt_path = os.path.join(temp_dir, "talk.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:02,000 --> 00:00:06,000\n"
                    "Training data ka composition matter karta hai.\n\n"
                    "2\n00:03:40,000 --> 00:03:47,000\n"
                    "Audit ke baad error rate gap kam hua.\n")
        srt = DocumentProcessor().process(srt_path)
        check("srt transcript process hui",
              srt["ok"] and srt["kind"] == "transcript" and srt["chunks"],
              f"{srt.get('error')} kind={srt.get('kind')}")
        check("srt citation timestamp ke saath aati hai",
              any(":" in (c.get("locator") or "") for c in srt["chunks"]),
              str([c.get("locator") for c in srt["chunks"]]))

        html_path = os.path.join(temp_dir, "page.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<html><head><style>p{color:red}</style>"
                    "<script>var x=1;</script></head><body><h1>Bias audit</h1>"
                    "<p>Error rate 34.7% tha darker skinned women ke liye.</p>"
                    "</body></html>")
        html = DocumentProcessor().process(html_path)
        check("html se saaf text nikla (script/style hate)",
              html["ok"] and "34.7%" in html["text"]
              and "var x" not in html["text"] and "color:red" not in html["text"],
              html["text"][:80])

        # OCR: available ho ya na ho, jawab imaandaar hona chahiye
        from research_engine.processing import OCRProcessor
        ocr = OCRProcessor().available()
        check("OCR apni availability ke baare mein saaf batata hai",
              isinstance(ocr.get("ok"), bool) and bool(ocr.get("reason")), str(ocr))

        # YouTube captions default OFF — flag ke bina chup-chaap chalna nahi chahiye
        old_flag = os.environ.pop("ALLOW_YT_TRANSCRIPT", None)
        try:
            yt = TranscriptProcessor().youtube_captions("dQw4w9WgXcQ")
            check("YouTube captions flag ke bina band rehte hain",
                  yt.get("ok") is False and bool(yt.get("error")), str(yt)[:90])
        finally:
            if old_flag is not None:
                os.environ["ALLOW_YT_TRANSCRIPT"] = old_flag
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── 8. research memory ───────────────────────────────────────────────────────
def test_memory():
    section("8. ResearchMemory (Spec 16)")
    temp_dir = tempfile.mkdtemp(prefix="ire_mem_")
    try:
        memory = ResearchMemory("test_project", directory=temp_dir)
        memory.remember_run(QUESTION, "STRONG", 5, "DEEP", ["openalex"], "summary text")
        memory.remember_hypotheses(QUESTION, [{
            "statement": "label noise se disparity badhti hai",
            "how_to_test": "clean vs noisy label training",
            "status": "UNTESTED HYPOTHESIS"}])
        memory.remember_urls(["https://example.org/a", "https://example.org/a/"])
        # Spec 16 — dead ends: kya kaam nahi aaya, taaki agli baar na dohraaye
        memory.remember_dead_end("connector fail: pubmed",
                                 "training data bias query par timeout hua")
        memory.remember_dead_end("connector fail: pubmed", "duplicate — save nahi hona chahiye")
        memory.remember_dead_end("full text nahi mila: nature.com",
                                 "paywalled/ToS-restricted publisher")
        check("dead end duplicate nahi bana", len(memory.dead_ends()) == 2,
              str(memory.dead_ends()))
        check("save hui", memory.save(), memory.path)

        fresh = ResearchMemory("test_project", directory=temp_dir)
        check("reload hui", len(fresh.load()["runs"]) == 1, str(fresh.load()["runs"]))
        check("URL dedup hua", len(fresh.seen_urls()) == 1, str(fresh.seen_urls()))
        related = fresh.recall_related("AI training data bias discrimination")
        check("related run recall hua", len(related) == 1, str(related))
        note = fresh.context_note("AI training data bias discrimination")
        check("context note bana", "PICHHLI RESEARCH" in note, note[:60])
        check("dead end disk se wapas aaya",
              len(fresh.dead_ends()) == 2, str(fresh.dead_ends()))
        matched = fresh.related_dead_ends("AI training data bias discrimination")
        check("sawal se related dead end mila",
              any("pubmed" in d.get("what", "") for d in matched), str(matched))
        check("dead end prompt note mein bhi gaya",
              "pehle kaam nahi aaya" in note and "pubmed" in note, note)
        check("bilkul unrelated sawal par dead end nahi thopa",
              fresh.related_dead_ends("quantum tunnelling semiconductor") == [],
              str(fresh.related_dead_ends("quantum tunnelling semiconductor")))

        # legacy/haath se edit ki hui memory file par context_note crash na ho
        legacy_dir = tempfile.mkdtemp(prefix="ire_legacy_")
        try:
            legacy = ResearchMemory("legacy", directory=legacy_dir)
            legacy._data = {"project_id": "legacy",
                            "runs": [{"question": "AI training data bias kya karta hai"}],
                            "hypotheses": [{"question": "AI training data bias",
                                            "statement": "purani hypothesis"}],
                            "dead_ends": [{}], "seen_urls": []}
            legacy_note = legacy.context_note("AI training data bias discrimination")
            check("purane format ki memory par KeyError nahi",
                  "PICHHLI RESEARCH" in legacy_note, legacy_note[:80])
        finally:
            shutil.rmtree(legacy_dir, ignore_errors=True)

        broken_dir = tempfile.mkdtemp(prefix="ire_bad_")
        broken = ResearchMemory("bad", directory=broken_dir)
        with open(broken.path, "w", encoding="utf-8") as f:
            f.write("{ not json at all")
        check("corrupt file par crash nahi", broken.load()["runs"] == [], "recovered")
        shutil.rmtree(broken_dir, ignore_errors=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── 9. synthesizer (Gemini ke bina) ──────────────────────────────────────────
def test_synthesizer(pack, contradictions, consensus, verification, hypotheses,
                     critique):
    section("9. FinalSynthesizer — Gemini fail hone par bhi (Spec 12, 13)")
    synthesizer = FinalSynthesizer()
    coverage = pack.coverage_report()
    coverage["by_source_type"] = {"paper": 4, "web": 1}
    answer = synthesizer.assemble(
        gemini_answer="",                     # Gemini fail hua
        pack=pack, evidence_level="⚠️ MIXED — sources aapas me disagree karte hain",
        confidence_note="Test note.",
        contradictions=contradictions, hypotheses=hypotheses,
        verification=verification, coverage=coverage,
        honesty={"citations_verified": 2, "summary": "- test summary"},
        consensus=consensus, discovery_note="mile: openalex(3)",
        quota_note="0/2 calls used", critique=critique,
        warnings=["test warning"])

    # NOTE (2026-08-20): neeche ka poora block pehle purane numbered headings
    # ("1. Seedha Jawab", "4. Conflicting Evidence", "9. Verification",
    # "12. Sources", "14. Coverage") par tika tha. §16 ke naye structure mein
    # wahi cheezein naye naamon se aati hain — na koi section gaya, na koi
    # feature. SIRF is test ki expectation naye headings par le aayi gayi hai.
    # Section-level detail coverage tests/test_answer_structure.py mein hai.
    #
    # EXPECTATION JAAN-BOOJH KAR BADLI GAYI (§10, 2026-08-20): pehle yahan
    # `for title in SECTION_TITLES` chal kar HAR heading maangi jaati thi — is
    # run mein `gemini_answer=""` hai, isliye 3 section (Research se kya pata
    # chala? / Ye kyun hota hai? / Kya abhi unknown hai?) mein andar kuch bhi
    # nahi hota tha, sirf khaali heading + "_(Reasoning model ne ye section
    # nahi diya.)_" chhapta tha. User ka §10 saaf kehta hai: khaali template
    # section nahi chahiye. Ab aisa section CHHAPTA HI NAHI aur uska naam ek
    # jagah (top banner + audit) list ho jaata hai. Isliye test do hisson mein:
    #   * jin section mein system ka apna content hai -> zaroor maujood ho
    #   * jin mein kuch nahi tha -> heading NA ho, par naam list mein ho
    from research_engine.synthesizer import SECTION_TITLES
    # index 1 = "Research se kya pata chala?", 2 = "Ye kyun hota hai?",
    # 7 = "Kya abhi unknown hai?" — inme system ka apna computed content nahi
    # hota, isliye model ke bina ye khaali hi rehte the.
    empty_when_no_model = {SECTION_TITLES[1], SECTION_TITLES[2], SECTION_TITLES[7]}
    for index, title in enumerate(SECTION_TITLES):
        present = f"\n## {title}\n" in "\n" + answer
        if title in empty_when_no_model and not present:
            check(f"khaali section chhapa NAHI (§10): {title}", True)
        else:
            check(f"section maujood: {title}", present, "missing")
    for title in sorted(empty_when_no_model):
        check(f"chhoda hua section naam se list hua: {title}",
              title in answer, "naam kahin nahi likha")
    check("hypothesis par UNTESTED label", "UNTESTED" in answer, "missing")
    check("limits section imaandaar", "bypass nahi kiya gaya" in answer, "missing")
    check("independent human experts ka disclaimer", "independent " in answer
          and "human experts" in answer, "missing")

    extractive = synthesizer.extractive_summary(QUESTION, pack)
    check("zero-gemini extract bana", "S1" in extractive, extractive[:80])

    # ── §16 ka section ORDER ──────────────────────────────────────────────────
    gemini_body = (
        "Yahan model ne heading se pehle kuch likh diya.\n\n"
        "## Seedha jawab\nHaan, bias real discrimination badha "
        "sakta hai [S1].\n\n"
        "## Research se kya pata chala?\n"
        "### Fact\n- [ESTABLISHED] error rate zyada tha [S1]\n"
        "### Inference\n- [INFERENCE] deployment scale badhne se asar badhega [S1]\n\n"
        "## Ye kyun hota hai?\nCS + public health dono taraf se yahi baat aati hai.\n\n"
        "## Evidence kya kehta hai?\nMethodology theek thi.\n\n"
        "## Sources\n- model ki apni banayi hui list (system isse "
        "replace karega)\n\n"
        "## Kya abhi unknown hai?\nLong-term effect pata nahi.\n\n"
        "## Final conclusion\nAudit karo.\n\n"
        "## Random Extra Heading\nye canonical list mein nahi hai.")
    ordered = synthesizer.assemble(
        gemini_answer=gemini_body, pack=pack, evidence_level="🟡 MIXED",
        confidence_note="Test note.", contradictions=contradictions,
        hypotheses=hypotheses, verification=verification, coverage=coverage,
        honesty={"citations_verified": 2, "summary": "- test summary"},
        consensus=consensus, discovery_note="mile: openalex(3)",
        quota_note="2/2 calls used", critique=critique, warnings=[])

    padded = "\n" + ordered
    positions = [(title, padded.find(f"\n## {title}\n")) for title in SECTION_TITLES]
    missing = [title for title, pos in positions if pos < 0]
    check("saare canonical sections final answer mein hain", not missing, str(missing))
    found = [pos for _, pos in positions if pos >= 0]
    check("sections §16 ke order mein hain", found == sorted(found),
          str([(t, p) for t, p in positions]))
    inference_zone = ordered[padded.find("\n## Research se kya pata chala?\n"):
                             padded.find("\n## Ye kyun hota hai?\n")]
    check("Inferences ka apna sub-heading hai aur model ka inference wahin gaya",
          "### Inference" in inference_zone
          and "deployment scale badhne se asar badhega" in inference_zone,
          "inferences section galat jagah hai")
    check("model ka jawab pehle section mein hi hai",
          0 <= ordered.find("Haan, bias real discrimination")
          < padded.find("\n## Research se kya pata chala?\n"),
          "pehla section apni jagah nahi hai")
    check("heading se pehle likha text bhi bacha",
          "heading se pehle kuch likh diya" in ordered, "text kho gaya")
    check("model ki banayi Sources list system ki verified list ko replace nahi karti",
          "**[S1]" in ordered and "Isse kya liya gaya" in ordered,
          "system bibliography hat gayi")
    against_zone = ordered[padded.find("\n## Iske against kya mila?\n"):
                           padded.find("\n## Humari Hypotheses\n")]
    check("hypothesis ke khilaf evidence 'Iske against kya mila?' mein hai",
          "Hypotheses ke khilaf" in against_zone or "khilaf" in against_zone,
          "against evidence galat section mein hai")
    check("anjaan heading delete nahi hui, extra notes mein gayi",
          "Extra notes" in ordered and "ye canonical list mein nahi hai" in ordered,
          "content kho gaya")

    # model kuch sections chhod de to jhoothi bharai nahi, saaf likha jaaye
    partial = synthesizer.assemble(
        gemini_answer="## Seedha jawab\nSirf ek section diya.",
        pack=pack, evidence_level="🟡 MIXED", confidence_note="n",
        contradictions=[], hypotheses=[], verification=verification,
        coverage=coverage, honesty={}, consensus=consensus, discovery_note="",
        quota_note="1/2", critique={}, warnings=[])
    # EXPECTATION JAAN-BOOJH KAR BADLI GAYI (§10, 2026-08-20): pehle yahan
    # `"Reasoning model ne ye section nahi diya" in partial` aur
    # `"## Ye kyun hota hai?" in partial` maanga jaata tha — yaani khaali
    # heading + placeholder line. User ka §10 kehta hai ki 11 khaali heading
    # padhne se kuch nahi milta. Naya vaada: aisi heading chhapti hi nahi, par
    # us section ka NAAM ek jagah saaf likha jaata hai (top banner + audit ka
    # "Kaunse hisse nahi ban paaye" block). Imaandaari kam nahi hui, ek jagah
    # aa gayi.
    check("model ka chhoda hua section khaali heading ban kar nahi chhapta",
          "## Ye kyun hota hai?" not in partial, partial[:200])
    check("chhoda hua section naam se ek jagah imaandaari se likha hai",
          "Ye kyun hota hai?" in partial
          and "nahi ban paaye" in partial, partial[:400])
    check("purana placeholder text ab report mein nahi hai",
          "Reasoning model ne ye section nahi diya" not in partial,
          "placeholder wapas aa gaya")


# ── 10. end-to-end (poori tarah hermetic — na network, na Gemini) ────────────
def test_end_to_end():
    section("10. DeepResearchEngine end-to-end (hermetic degradation test)")
    temp_dir = tempfile.mkdtemp(prefix="ire_e2e_")
    os.environ["RESEARCH_MEMORY_DIR"] = temp_dir

    from research_engine import gemini_reasoning as gemini_module
    from research_engine.orchestrator import DeepResearchEngine

    # Gemini ko sach mein BLOCK karo.
    #
    # Kyun zaroori hai: is suite ka waada hai "0 Gemini calls". Agar hum sirf
    # module missing hone par bharosa karein, to jis machine par API key .env
    # mein hai wahan ye test chupke se asli quota kharch kar dega. Isliye
    # generate() ko yahan replace kar rahe hain — koi network call ho hi nahi
    # sakti, aur agar kabhi koi naya code path Gemini call karega to counter
    # usse pakad lega.
    real_generate = gemini_module.GeminiReasoning.generate
    attempts: List[str] = []

    def blocked_generate(self, prompt: str, label: str = "") -> str:
        attempts.append(label or "unlabelled")
        self.calls_used += 1
        self.errors.append(f"{label or 'gemini'} blocked by offline test")
        return ""

    gemini_module.GeminiReasoning.generate = blocked_generate
    try:
        engine = DeepResearchEngine(project_id="offline_test", enable_kg=False)

        # Network ko bhi block karo, warna ye test asli APIs hit karega:
        # slow, rate-limit-prone, aur "offline suite" ka matlab khatam.
        engine.discovery.discover = lambda **kwargs: {
            "records": [], "log": [{"connector": "offline_test", "count": 0,
                                    "error": "network test mein band hai"}],
            "connectors_searched": [], "seen_urls": set()}
        engine.vectors.retrieve = lambda *args, **kwargs: {
            "context": "", "sources": [], "chunks": []}

        # Full-text reader ko bhi band karo. Is test mein discovery khaali hai
        # isliye waise bhi kuch download nahi hota — par ye line guarantee ko
        # code se pakka karti hai: kal koi naya source path aaya to bhi ye test
        # internet par nahi jaayega.
        engine.reader.allow_network = False

        result = engine.research("kya AI bias real-world discrimination badhata hai?",
                                 depth_mode="QUICK")

        legacy_keys = ("question", "answer", "sources", "safety_flags",
                       "evidence_level", "mode", "question_types", "relevant_fields")
        missing = [k for k in legacy_keys if k not in result]
        check("purane API keys bache", not missing, f"missing: {missing}")
        check("naye keys aaye", all(k in result for k in
                                    ("citations", "contradictions", "hypotheses",
                                     "verification", "coverage", "warnings",
                                     "gemini_calls_used")), str(list(result)))
        check("answer khaali nahi", len(result["answer"]) > 300,
              str(len(result["answer"])))
        # NOTE (2026-08-20): pehle "14. Coverage" / "12. Sources" dhoondte the.
        # §16 ke baad wahi hissa "## Sources" aur "## Research quality /
        # technical audit" ke naam se aata hai — content wahi hai.
        check("audit (coverage) section aaya",
              "## Research quality / technical audit" in result["answer"],
              "missing")
        check("Sources section aaya", "## Sources" in result["answer"], "missing")
        check("crash nahi hua", result["mode"] == "QUICK", result["mode"])
        # NOTE (2026-08-21, §8): pehle yahan sirf "Gemini" shabd dhoondha jaata
        # tha. Ab jab reasoning model nahi chalta to warning RV ki apni bhasha
        # mein aati hai ("AI reasoning model is baar nahi chala ...") — kyunki
        # user ko model/company ka naam dena persona ke against hai. Warning ka
        # KAAM wahi hai: saaf batana ki reasoning nahi hui aur jawab engine ke
        # apne offline reasoning se bana hai. Isliye check dono roop maanta hai.
        check("Gemini fail hone par bhi honest warning aayi",
              any(("Gemini" in w) or ("AI reasoning model" in w)
                  for w in result["warnings"]),
              str(result["warnings"]))
        check("koi asli Gemini network call nahi hui",
              gemini_module.GeminiReasoning.generate is blocked_generate,
              "stub hat gaya")
        check("coverage mein reading ka honest hisaab aata hai",
              isinstance(result["coverage"].get("reading"), dict)
              and "attempted" in result["coverage"]["reading"],
              str(result["coverage"].get("reading")))
        check("coverage mein read_levels + honesty_note aate hain",
              "read_levels" in result["coverage"]
              and bool(result["coverage"].get("honesty_note")),
              str(list(result["coverage"])))
        print(f"     → evidence_level: {result['evidence_level']}")
        print(f"     → sources: {len(result['sources'])}, "
              f"gemini attempts (sab blocked): {attempts}")
    finally:
        gemini_module.GeminiReasoning.generate = real_generate
        os.environ.pop("RESEARCH_MEMORY_DIR", None)
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── 11. content fetcher (paywall rule + read levels) ─────────────────────────
def test_content_fetcher():
    """
    ContentFetcher ka sabse zaroori kaam SIRF text laana nahi hai — ye decide
    karna hai ki KAUNSA link kholna legal hai. Wo faisla `resolve()` mein hota
    hai aur usme network ki zaroorat nahi, isliye poora rule set yahan offline
    test ho jaata hai. Ek bhi request nahi jaati: hum `_download` /
    `read_source` ko stub karte hain.
    """
    section("11. ContentFetcher (paywall rule, whitelist, read levels — 0 network)")
    from research_engine.content_fetcher import ContentFetcher, _is_blocked

    fetcher = ContentFetcher(allow_network=False)

    # ── A. resolve() ka routing — kaunsa source kahan se legally milega ──
    def resolve(url: str, source_type: SourceType = SourceType.WEB) -> dict:
        return fetcher.resolve(SourceRecord(title="t", url=url,
                                            source_type=source_type))

    arxiv = resolve("https://arxiv.org/abs/2103.00020v3")
    check("arXiv abs → open-access PDF",
          arxiv["ok"] and arxiv["url"] == "https://arxiv.org/pdf/2103.00020"
          and arxiv["kind"] == "pdf", str(arxiv))

    wiki = resolve("https://en.wikipedia.org/wiki/Algorithmic_bias")
    check("Wikipedia → official API extract",
          wiki["ok"] and wiki["kind"] == "wikipedia" and "api.php" in wiki["url"]
          and "Algorithmic_bias" in wiki["url"], str(wiki))

    archive = resolve("https://archive.org/details/discriminationbook/page/12")
    check("Internet Archive → public djvu.txt",
          archive["ok"] and archive["url"].endswith(
              "/discriminationbook/discriminationbook_djvu.txt")
          and archive["kind"] == "txt", str(archive))

    pmc = resolve("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7654321/")
    check("PMC → Europe PMC OA full text",
          pmc["ok"] and "PMC7654321/fullTextXML" in pmc["url"], str(pmc))

    pubmed = resolve("https://pubmed.ncbi.nlm.nih.gov/32409431/")
    check("PubMed → pehle OA status check (needs_lookup)",
          pubmed.get("needs_lookup") == "32409431" and not pubmed.get("url"),
          str(pubmed))

    open_pdf = resolve("https://ojs.university.edu/papers/bias-study.pdf")
    check("koi bhi khula .pdf link allowed",
          open_pdf["ok"] and open_pdf["kind"] == "pdf", str(open_pdf))

    # ── B. paywall / ToS rule — ye test spec ka sabse sakht rule hai ──
    blocked_urls = [
        "https://www.sciencedirect.com/science/article/pii/S000",
        "https://onlinelibrary.wiley.com/doi/10.1002/abc",
        "https://link.springer.com/article/10.1007/xyz",
        "https://www.nature.com/articles/s41586-021-1",
        "https://ieeexplore.ieee.org/document/8765432",
        "https://www.jstor.org/stable/2657316",
        "https://www.researchgate.net/publication/123_full",
        "https://www.scribd.com/document/999/book",
        "https://books.google.com/books?id=abc",
    ]
    leaked = [u for u in blocked_urls if resolve(u)["ok"]]
    check("paywalled/ToS-restricted hosts kabhi fetch nahi hote",
          not leaked, f"leak: {leaked}")
    check("block hone par honest reason milta hai",
          "bypass nahi kiya" in resolve(blocked_urls[0])["reason"],
          resolve(blocked_urls[0])["reason"])

    check("blocked host ka subdomain bhi blocked",
          _is_blocked("https://cdn.assets.sciencedirect.com/x.pdf"), "leak")
    check("milta-julta naam blocked NAHI hota (nature.com vs mynature.com)",
          not _is_blocked("https://mynature.com/open.pdf"), "over-block")
    check("blocked host par .pdf bhi allowed nahi",
          not resolve("https://www.nature.com/articles/s1.pdf")["ok"],
          "pdf ne blocklist bypass kar li")

    doi = resolve("https://doi.org/10.1145/3287560.3287596")
    check("DOI link jaan-boojh kar nahi khola jaata",
          not doi["ok"] and "DOI" in doi["reason"], str(doi))

    no_url = resolve("")
    check("URL hi nahi hai → metadata level par imaandaar rukna",
          not no_url["ok"] and "URL nahi hai" in no_url["reason"], str(no_url))

    unknown = resolve("https://some-random-blog.example/post/1")
    check("anjaan host ke liye koi jhootha route nahi banta",
          not unknown["ok"] and "snippet level" in unknown["reason"], str(unknown))

    # ── C. best_excerpts — poora document nahi, kaam ka hissa ──
    chunks = [
        {"locator": "p.1", "text": "Title page aur acknowledgements. " * 5},
        {"locator": "p.4", "text": "short"},                       # 80 char se kam
        {"locator": "p.7", "text": "Facial recognition error rates were higher "
                                   "for darker skinned women in commercial "
                                   "gender classification systems. " * 3},
        {"locator": "p.9", "text": "Appendix tables about unrelated funding "
                                   "disclosures and printing history. " * 3},
    ]
    excerpts = fetcher.best_excerpts(
        chunks, "kya facial recognition error rates darker skinned women ke liye "
                "zyada hain?", budget_chars=400)
    check("sabse relevant hissa pehle aata hai",
          excerpts and excerpts[0]["locator"] == "p.7",
          str([e["locator"] for e in excerpts]))
    check("chhote/bekaar chunk chhod diye jaate hain",
          all(e["locator"] != "p.4" for e in excerpts),
          str([e["locator"] for e in excerpts]))
    check("budget sach mein enforce hota hai",
          sum(len(e["text"]) for e in excerpts) <= 400 + 4,
          str(sum(len(e["text"]) for e in excerpts)))
    check("koi relevant chunk hi na ho to khaali list",
          fetcher.best_excerpts([{"locator": "x", "text": "tiny"}], "q", 400) == [],
          "kuch aa gaya")

    # ── D. network band hone par imaandaari (chup-chaap fail nahi) ──
    offline = fetcher.read_source(
        SourceRecord(title="t", url="https://arxiv.org/abs/2103.00020"), "q")
    check("ALLOW_FULLTEXT_FETCH=false par saaf reason milta hai",
          not offline["ok"] and "band hai" in offline["reason"], str(offline))

    # ── E. enrich() — read_level upgrade, passages, aur imaandaar counts ──
    from research_engine.models import EvidencePack

    pack = EvidencePack(question="kya AI bias real-world discrimination badhata hai?")
    paper = SourceRecord(source_id="S1", title="Gender Shades",
                         url="https://arxiv.org/abs/1801.00001",
                         snippet="Abstract: error rates differ. " * 12,
                         source_type=SourceType.PAPER, connector="openalex",
                         combined_score=0.9)
    paywalled = SourceRecord(source_id="S2", title="Paywalled study",
                             url="https://www.sciencedirect.com/science/article/pii/S1",
                             snippet="Abstract only.", source_type=SourceType.PAPER,
                             connector="crossref", combined_score=0.8)
    mine = SourceRecord(source_id="S3", title="mera_notes.pdf",
                        snippet="Meri file ka text.", source_type=SourceType.DOCUMENT,
                        connector="user_upload", combined_score=0.7)
    extra = SourceRecord(source_id="S4", title="Blog post",
                         url="https://blog.example/ai-bias",
                         snippet="Blog snippet.", connector="tavily",
                         combined_score=0.4)
    pack.sources = [paper, paywalled, mine, extra]

    # read_source ko stub karte hain: asli network ki zaroorat nahi, par enrich
    # ka poora accounting (upgrade + passages + counts) test ho jaata hai.
    def fake_read(source, question, budget_chars=2400):
        if "arxiv.org" in source.url:
            return {"source_id": source.source_id, "title": source.title,
                    "url": source.url, "ok": True, "chars": 41000,
                    "reason": "arXiv open-access PDF",
                    "excerpts": [{"locator": "p.7", "text": "Darker skinned women "
                                                            "ke liye error rate "
                                                            "34.7% tak tha.",
                                  "score": 5}]}
        return {"source_id": source.source_id, "title": source.title,
                "url": source.url, "ok": False, "chars": 0, "excerpts": [],
                "reason": "paywalled/ToS-restricted publisher — bypass nahi kiya"}

    reader = ContentFetcher(allow_network=True)
    reader.read_source = fake_read
    report = reader.enrich(pack, max_sources=2, budget_chars=600)

    check("user ka apna document dobara nahi padha jaata",
          all(e["source_id"] != "S3" for e in report["entries"]),
          str([e["source_id"] for e in report["entries"]]))
    check("enrich ne budget ke andar hi kaam kiya",
          report["attempted"] == 2 and report["succeeded"] == 1
          and report["failed"] == 1, str(report))
    check("budget se bahar wale sources honestly gine gaye",
          report["skipped"] == 1, str(report["skipped"]))
    check("padha gaya source full_text par upgrade hua",
          paper.reading_level() == "full_text" and paper.full_text_chars == 41000,
          f"{paper.reading_level()} / {paper.full_text_chars}")
    check("na padha gaya source jhoothi upgrade nahi paata",
          paywalled.reading_level() != "full_text", paywalled.reading_level())
    check("full text excerpt snippet mein aa gaya (Gemini ko asli content mile)",
          "34.7%" in paper.snippet, paper.snippet[:60])
    check("locator citation ke liye set hua", paper.locator == "p.7", paper.locator)
    check("passage evidence pack mein juda",
          any(p.source_id == "S1" and p.locator == "p.7" for p in pack.passages),
          str([(p.source_id, p.locator) for p in pack.passages]))
    check("reading note mein asli ginti hai",
          "1/2" in report["note"] and "41,000" in report["note"], report["note"])
    check("jo fail hua uski wajah note mein likhi hai",
          "bypass nahi kiya" in report["note"], report["note"])

    # ── F. read-level accounting poore pack par ──
    #
    # Yahan sirf 1 source "full_text" par hai: S1, jise ContentFetcher ne asli
    # mein download + process kiya. S3 (mera document) is fixture mein haath se
    # banaya gaya hai aur uska read_level set nahi hai — isliye wo imaandaari se
    # "snippet" dikhta hai. Ye jaan-boojh kar hai: models.py kabhi "full_text"
    # ka ANDAZA nahi lagata. Asli pipeline mein wo label EvidenceEngine lagata
    # hai (neeche uska alag test hai), kyunki wahi code jaanta hai ki file
    # ingest ke waqt poori padhi gayi thi.
    counts = pack.read_level_counts()
    check("read levels sach dikhate hain (sirf 1 asli full_text)",
          counts.get("full_text") == 1 and counts.get("snippet") == 3
          and sum(counts.values()) == 4, str(counts))
    check("bina label wale document ko full_text ka andaza nahi milta",
          mine.reading_level() == "snippet", mine.reading_level())
    coverage = pack.coverage_report()
    check("coverage report mein read_levels aur chars aate hain",
          coverage["read_levels"] == counts
          and coverage["full_text_chars_read"] == 41000, str(coverage))
    check("honesty_note hardcoded nahi — counts se banta hai",
          "4 sources mein se" in coverage["honesty_note"]
          and "41,000" in coverage["honesty_note"], coverage["honesty_note"])
    check("honesty_note saaf kehta hai baaki ka poora text nahi padha",
          "NAHI padha gaya" in coverage["honesty_note"],
          coverage["honesty_note"][-80:])

    # ── G. budget 0 / khaali pack ──
    zero = ContentFetcher(allow_network=True).enrich(pack, max_sources=0)
    check("max_fulltext=0 par reading skip, par batati hai",
          zero["attempted"] == 0 and "budget 0" in zero["note"], str(zero))
    empty = ContentFetcher(allow_network=True).enrich(
        EvidencePack(question="q"), max_sources=3)
    check("source hi na ho to bhi crash nahi",
          empty["attempted"] == 0 and "koi source nahi" in empty["note"], str(empty))

    # ── H. asli pipeline document ko full_text label deta hai ──
    # Ye wo jagah hai jahan label lagna CHAHIYE: yahan code jaanta hai ki file
    # upload ke waqt DocumentProcessor se poori padhi gayi thi.
    doc_records = EvidenceEngine().records_from_retrieval({
        "context": "[Source: mera_paper.pdf, Page 3]\nPage 3 ka asli text yahan hai.\n\n"
                   "[Source: mera_paper.pdf, Page 8]\nPage 8 ka asli text yahan hai.",
        "sources": [{"file": "mera_paper.pdf", "page": 3},
                    {"file": "mera_paper.pdf", "page": 8}],
    })
    check("retrieval se bane document records par explicit full_text label",
          len(doc_records) == 2
          and all(r.read_level == "full_text" for r in doc_records),
          str([(r.locator, r.read_level) for r in doc_records]))
    doc_pack = EvidencePack(question="q", sources=doc_records)
    check("document ka reading note 'download' ka jhootha dava nahi karta",
          "download" not in doc_pack.reading_note()
          and "aapke apne uploaded document" in doc_pack.reading_note(),
          doc_pack.reading_note())


# ── 12. progress tracker ─────────────────────────────────────────────────────
def test_progress_tracker():
    section("12. Progress tracker (asli counts, banaya hua percentage NAHI)")
    from utils import progress_tracker as pt

    job = "offline_progress_test"
    pt.clear_tracking(job)

    missing = pt.get_progress("unknown_job_id")
    check("anjaan job par honest error + hint",
          missing.get("error") == "Job not found" and "hint" in missing, str(missing))

    # register hone se PEHLE update — pehle yahi bug tha (progress hamesha
    # "Job not found" deta tha), isliye crash-free behaviour pin kar rahe hain
    pt.update_stage(job, "DISCOVERING", "register hone se pehle")
    check("un-registered job par update chup-chaap ignore hota hai",
          pt.get_progress(job).get("error") == "Job not found", "register ho gaya")

    pt.start_tracking(job, "test question")
    pt.update_stage(job, "PLANNING", "plan bana")
    pt.update_stage(job, "DISCOVERING", "connectors chal rahe hain")
    pt.update_stage(job, "READING", "full text padha ja raha hai")
    pt.update_stage(job, "READING", "dobara wahi stage")
    pt.update_stage(job, "GALAT_STAGE", "ye list mein nahi hai")
    pt.set_counts(job, sources=12, documents=1, conflicts=2,
                  full_text_read=3, gemini_calls=2)

    state = pt.get_progress(job)
    check("READING stage track hoti hai (Spec 3/4/5 ka naya step)",
          "READING" in pt.STAGES and state["current_stage"] == "READING",
          state["current_stage"])
    check("duplicate stage do baar nahi ginta",
          state["stages_completed"].count("READING") == 1,
          str(state["stages_completed"]))
    check("galat stage naam accept nahi hota",
          "GALAT_STAGE" not in state["stages_completed"],
          str(state["stages_completed"]))
    check("full_text_read count save hua (pehle ye kwarg hi nahi tha)",
          state["full_text_sources_read"] == 3, str(state))
    check("gemini calls track hote hain",
          state["gemini_calls_used"] == 2, str(state["gemini_calls_used"]))
    check("counts sach mein store hue",
          (state["sources_discovered"], state["documents_processed"],
           state["evidence_conflicts_found"]) == (12, 1, 2), str(state))
    check("percentage nahi, sirf stage ki ginti",
          "percent" not in str(state).lower()
          and state["stages_done"] + state["stages_remaining"] == len(pt.STAGES),
          str(state.get("stages_done")))
    check("log mein har stage ka note + timestamp",
          all("timestamp" in e and "stage" in e for e in state["log"])
          and len(state["log"]) >= 4, str(len(state["log"])))

    pt.update_stage(job, "COMPLETE", "ho gaya")
    check("COMPLETE par finished_at bharta hai",
          bool(pt.get_progress(job)["finished_at"]), "khaali")
    check("active_jobs job dikhata hai", job in pt.active_jobs(), str(pt.active_jobs()))
    pt.clear_tracking(job)
    check("clear_tracking sach mein hataata hai",
          pt.get_progress(job).get("error") == "Job not found", "bacha reh gaya")


# ── 13. source discovery — web tier ek CHAIN hai, parallel nahi ──────────────
def test_discovery_chain():
    section("13. SourceDiscovery web chain (Spec 2, 18 — free quota bachao)")
    from research_engine.source_discovery import SourceDiscovery

    calls: list = []

    def stub(name: str, count: int):
        """Nakli connector.search — kya-kya call hua aur kitna maanga, record karta hai."""
        def search(query, max_results=5):
            calls.append((name, max_results))
            return [SourceRecord(
                title=f"{name} result {i}", url=f"https://{name}.test/{i}",
                snippet="ye ek test snippet hai jisme thoda text hai " * 2,
                connector=name, source_type=SourceType.WEB) for i in range(count)]
        return search

    plan_web = {"web": True, "papers": [], "books": []}

    # ── A. Tavily se target pura → Wikipedia/DuckDuckGo ko chhuo bhi na ──
    # Pehle teeno parallel submit hote the: har round mein Tavily ka free quota
    # (~1000/month) jal jaata tha aur DDG "last resort" ke bajaye hamesha chalta tha.
    d = SourceDiscovery(max_workers=4)
    d.web.tavily.search = stub("tavily", 5)
    d.web.wikipedia.search = stub("wikipedia", 3)
    d.web.duckduckgo.search = stub("duckduckgo", 3)
    result = d.discover(["kya AI bias real hai"], plan_web, max_web=5)
    check("Tavily ne target pura kiya to DuckDuckGo chala hi nahi",
          [c[0] for c in calls] == ["tavily"], str(calls))
    check("web se poore records mile", len(result["records"]) == 5,
          str(len(result["records"])))
    check("connectors_searched sirf jo chala wahi batata hai",
          result["connectors_searched"] == ["tavily"],
          str(result["connectors_searched"]))

    # ── B. Tavily khaali → Wikipedia → tab DuckDuckGo, aur 'need' ghatta jaaye ──
    calls.clear()
    d2 = SourceDiscovery(max_workers=4)
    d2.web.tavily.search = stub("tavily", 0)
    d2.web.wikipedia.search = stub("wikipedia", 2)
    d2.web.duckduckgo.search = stub("duckduckgo", 3)
    d2.discover(["kya AI bias real hai"], plan_web, max_web=5)
    check("Tavily khaali to Wikipedia, uske baad hi last-resort DuckDuckGo",
          [c[0] for c in calls] == ["tavily", "wikipedia", "duckduckgo"], str(calls))
    check("agla tier sirf bachi hui ginti maangta hai (need ghata: 5→5→3)",
          [c[1] for c in calls] == [5, 5, 3], str(calls))

    # ── C. pehle dekhe hue URL dobara na aayein (Spec 2 + 16) ──
    calls.clear()
    d3 = SourceDiscovery()
    d3.web.tavily.search = stub("tavily", 3)
    result3 = d3.discover(["kya AI bias real hai"], plan_web, max_web=3, round_no=2,
                          exclude_urls={"https://tavily.test/0"})
    urls = [r.url for r in result3["records"]]
    check("pichhle round ka URL dobara nahi aata",
          "https://tavily.test/0" not in urls and len(urls) == 2, str(urls))
    check("round number har record par lag gaya",
          all(r.round_found == 2 for r in result3["records"]), str(urls))
    check("seen_urls wapas milta hai (agle round ke liye)",
          "https://tavily.test/1" in result3["seen_urls"], str(result3["seen_urls"]))

    # ── D. ek tier crash ho jaaye to chain rukni nahi chahiye ──
    calls.clear()
    d4 = SourceDiscovery()

    def boom(query, max_results=5):
        raise RuntimeError("network down")

    d4.web.tavily.search = boom
    d4.web.wikipedia.search = stub("wikipedia", 1)
    d4.web.duckduckgo.search = stub("duckduckgo", 1)
    result4 = d4.discover(["kya AI bias real hai"], plan_web, max_web=2)
    check("ek tier crash hone par baaki chain chalti rehti hai",
          len(result4["records"]) == 2, str(result4["log"]))
    note = SourceDiscovery.discovery_note(result4["log"])
    check("discovery note failure chhupata nahi",
          "fail" in note and "tavily" in note, note)

    # ── E. papers per-query, books sirf primary query par ──
    calls.clear()
    d5 = SourceDiscovery()
    for name in ("openalex", "crossref"):
        connector = d5.papers.by_name(name)
        connector.search = stub(name, 1)
    d5.books.by_name("open_library").search = stub("open_library", 1)
    d5.discover(["query ek", "query do"],
                {"web": False, "papers": ["openalex", "crossref"],
                 "books": ["open_library"]}, max_per_connector=3)
    names = sorted(c[0] for c in calls)
    check("har paper connector har query par chala (2 queries x 2 = 4)",
          names.count("openalex") == 2 and names.count("crossref") == 2, str(calls))
    check("book connector sirf primary query par chala (1 baar)",
          names.count("open_library") == 1, str(calls))
    check("web off hone par ek bhi web tier nahi chala",
          not any(c[0] in ("tavily", "wikipedia", "duckduckgo") for c in calls),
          str(calls))

    # ── F. koi task hi na bane to bhi shape poori ho (KeyError na aaye) ──
    empty = SourceDiscovery().discover([], {"web": True, "papers": [], "books": []})
    check("koi task na ho to bhi 'seen_urls' key maujood",
          empty["records"] == [] and empty["connectors_searched"] == []
          and isinstance(empty["seen_urls"], set), str(empty))


# ── 14. package surface — `from research_engine import *` toot na jaaye ──────
def test_package_surface():
    section("14. research_engine package surface (lazy import contract)")
    import ast
    from importlib import util as import_util

    import research_engine as pkg

    lazy = pkg._LAZY
    eager = set(vars(pkg))
    # Ye wahi bug hai jo mila tha: "agent_manager" __all__ mein tha par _LAZY
    # mein nahi, isliye `from research_engine import *` AttributeError deta tha.
    unresolvable = [n for n in pkg.__all__ if n not in eager and n not in lazy]
    check("__all__ ka har naam resolve hota hai (import * safe hai)",
          not unresolvable, str(unresolvable))
    hidden = [n for n in lazy if n not in pkg.__all__]
    check("_LAZY ka har naam __all__ mein bhi hai", not hidden, str(hidden))

    # Har lazy target module disk par maujood ho aur us naam ko define kare —
    # ye check karne ke liye module CHALANA nahi padta (ast se padh rahe hain),
    # isliye chromadb/gemini install na ho tab bhi ye test chalta hai.
    missing_modules, missing_names = [], []
    for name, module_path in lazy.items():
        try:
            spec = import_util.find_spec(module_path, "research_engine")
        except Exception as exc:
            spec = None
            module_path = f"{module_path} ({type(exc).__name__})"
        if not spec or not spec.origin:
            missing_modules.append(f"{name} → {module_path}")
            continue
        with open(spec.origin, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        defined = set()
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                defined.update(a.asname or a.name.split(".")[0] for a in node.names)
        if name not in defined:
            missing_names.append(f"{name} not in {spec.origin.split('research_engine')[-1]}")
    check("har lazy module asli file par point karta hai", not missing_modules,
          str(missing_modules))
    check("har lazy naam apne module mein sach mein define hai", not missing_names,
          str(missing_names))
    check("galat naam par saaf AttributeError",
          _raises_attribute_error(pkg, "KoiAisaNaamNahiHai"), "AttributeError nahi aaya")

    # main.py ki endpoint list hardcoded nahi honi chahiye (purani ho jaati hai)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"),
              "r", encoding="utf-8") as f:
        main_src = f.read()
    check("root endpoint list app.routes se banti hai, hardcoded nahi",
          "app.routes" in main_src and "/api/v1/deep-research\"" not in main_src,
          "hardcoded list wapas aa gayi")

    # requirements.txt jhooth na bole: jo likha hai wo sach mein use hota ho
    # (free-tier laptop par bina wajah ka install time + disk kharch hota hai)
    backend = os.path.dirname(os.path.abspath(__file__))
    source_text = []
    for folder in ("api", "rag", "agents", "utils", "safety", "knowledge",
                   "research_engine"):
        for root, _dirs, files in os.walk(os.path.join(backend, folder)):
            if "__pycache__" in root:
                continue
            for filename in files:
                if filename.endswith(".py"):
                    with open(os.path.join(root, filename), "r", encoding="utf-8") as f:
                        source_text.append(f.read())
    source_text.append(main_src)
    all_source = "\n".join(source_text)

    # package naam != import naam, isliye mapping. Jo runtime-only hain (server
    # chalane ya form-upload parse karne ke liye) unhe "" se whitelist kiya hai.
    import_names = {
        "fastapi": "fastapi", "uvicorn": "", "python-multipart": "",
        "python-dotenv": "dotenv", "pydantic": "pydantic",
        "pymupdf": "fitz", "chromadb": "chromadb",
        "sentence-transformers": "sentence_transformers",
        "google-generativeai": "generativeai", "requests": "requests",
        "tavily-python": "tavily", "ddgs": "ddgs",
        # ye pehle map hi nahi the, isliye test "anjaan package" bol kar fail
        # ho raha tha — package galat nahi the, test ki list purani thi.
        "pillow": "PIL", "scipy": "scipy", "sympy": "sympy", "numpy": "numpy",
        "httpx": "httpx", "beautifulsoup4": "bs4", "lxml": "lxml",
        "tiktoken": "tiktoken",
    }
    # Jaan-boojh kar rakhe gaye, par abhi kisi .py file mein import nahi hote.
    # Inhe HATAYA NAHI gaya — feature plan ka hissa hain (HTML parsing aur token
    # counting), aur dependency chupchaap nikaalna mana hai. Test inhe naam se
    # janta hai, taaki "unused" check baaki packages par sakht bana rahe.
    declared_but_unused = {"httpx", "beautifulsoup4", "lxml", "tiktoken"}
    unused, unmapped, stale_exception = [], [], []
    with open(os.path.join(backend, "requirements.txt"), "r",
              encoding="utf-8-sig") as f:   # utf-8-sig = BOM ho to bhi chale
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            package = re.split(r"[<>=!\[]", line)[0].strip().lower()
            if package not in import_names:
                unmapped.append(package)
                continue
            import_name = import_names[package]
            if import_name and import_name not in all_source:
                if package not in declared_but_unused:
                    unused.append(package)
            elif package in declared_but_unused:
                # ab use hone lag gaya — exception list se hata do
                stale_exception.append(package)
    check("requirements.txt ka har package sach mein code mein use hota hai",
          not unused, str(unused))
    check("requirements.txt mein koi anjaan package nahi (test se chhupa hua)",
          not unmapped, str(unmapped))
    check("'declared_but_unused' list purani nahi hui",
          not stale_exception, str(stale_exception))


def _raises_attribute_error(module, name: str) -> bool:
    try:
        getattr(module, name)
    except AttributeError:
        return True
    except Exception:
        return False
    return False


# ── 15. knowledge graph — hint layer, evidence layer NAHI ────────────────────
def test_knowledge_graph():
    section("15. Knowledge graph (Spec 16 — hint hai, evidence nahi)")
    from knowledge import graph as kg
    from research_engine.knowledge_graph import KnowledgeGraphAdapter

    temp_dir = tempfile.mkdtemp(prefix="ire_kg_")
    old_file = kg.GRAPH_FILE
    kg.GRAPH_FILE = os.path.join(temp_dir, "sub", "knowledge_graph.json")
    try:
        check("graph file CWD par depend nahi karta (absolute path)",
              os.path.isabs(old_file) and old_file.endswith("knowledge_graph.json"),
              old_file)

        answer = ("Buolamwini aur Gebru ne Gender Shades study ki. "
                  "Obermeyer ne health algorithm ka bias dikhaya.")
        stored = kg.extract_and_store("AI bias kya hai", answer, "proj_a")
        check("entities nikle aur file ban gayi",
              stored["entities_found"] >= 2 and stored["saved"] is True
              and os.path.exists(kg.GRAPH_FILE), str(stored))
        rels = kg.get_entity_graph("proj_a")["relationships"]
        check("relationship 'proven rishta' ka dava nahi karta",
              all(r["relation"] == "co_occurs_with" and r["verified"] is False
                  for r in rels), str(rels[:1]))
        check("graph report par honesty note hai",
              "citation ki tarah use nahi" in kg.get_entity_graph("proj_a")["honesty_note"],
              "note missing")

        kg.extract_and_store("AI bias kya hai", answer, "proj_a")
        stats = kg.get_entity_stats("proj_a")
        check("dobara mention par count badhta hai (duplicate entity nahi)",
              stats["top_entities"][0]["mention_count"] == 2
              and stats["total_entities"] == len(kg.get_entity_graph("proj_a")["entities"]),
              str(stats["top_entities"][:1]))
        check("dusre project ka data leak nahi hota",
              kg.get_entity_stats("proj_b")["total_entities"] == 0,
              str(kg.get_entity_stats("proj_b")))
        check("related knowledge hint milta hai",
              "Pehle poocha gaya" in kg.get_related_knowledge("AI bias", "proj_a"),
              kg.get_related_knowledge("AI bias", "proj_a")[:60])

        # purane format ki file (project_id / mention_count missing) par KeyError
        # nahi — pehle ye poore KG feature ko chup-chaap band kar deta tha
        with open(kg.GRAPH_FILE, "w", encoding="utf-8") as f:
            f.write('{"entities": [{"name": "Purani Entity"}], '
                    '"relationships": [{"from": "A", "to": "B"}], '
                    '"research_log": [{"question": "purana sawal"}]}')
        check("purane format par KeyError nahi",
              kg.get_entity_stats("proj_a")["total_entities"] == 0
              and kg.get_related_knowledge("purana sawal", "proj_a") == ""
              and kg.get_entity_graph("proj_a")["total_relationships"] == 0,
              "KeyError ya galat filter")
        check("purane format par bhi naya data likh sakta hai",
              kg.extract_and_store("naya sawal", answer, "proj_a")["saved"] is True,
              "save fail")

        with open(kg.GRAPH_FILE, "w", encoding="utf-8") as f:
            f.write("{ ye json hi nahi hai")
        check("corrupt graph file par crash nahi",
              kg.get_entity_graph("proj_a")["total_entities"] == 0, "crash")

        # adapter: graph fail ho to research NA ruke, aur cite bhi na ho
        adapter = KnowledgeGraphAdapter()
        kg.GRAPH_FILE = os.path.join(temp_dir, "fresh.json")
        adapter.store("AI bias kya hai", answer, "proj_c")
        note = adapter.related_note("AI bias kya hai", "proj_c")
        check("adapter ka hint block 'evidence nahi' bolta hai",
              "evidence nahi" in note and "cite nahi" in note, note[:90])
        disabled = KnowledgeGraphAdapter(enabled=False)
        check("KG band ho to khaali, exception nahi",
              disabled.related_note("x") == "" and disabled.stats() == {}
              and disabled.store("q", "a") is False, "disabled path toota")
    finally:
        kg.GRAPH_FILE = old_file
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── 16. depth modes (Spec 13 — quota rails) ──────────────────────────────────
def test_depth_modes():
    section("16. Depth modes (Spec 13 — 'Maximum' ka matlab unlimited NAHI)")
    from research_engine.depth import DEEP, MAXIMUM, QUICK, get_depth_config, quota_note

    check("QUICK/DEEP/MAXIMUM ka Gemini budget spec ke hisaab se 1/2/3 hai",
          (QUICK.gemini_calls, DEEP.gemini_calls, MAXIMUM.gemini_calls) == (1, 2, 3),
          f"{QUICK.gemini_calls}/{DEEP.gemini_calls}/{MAXIMUM.gemini_calls}")
    check("MAXIMUM bhi 20-call/day free tier ke andar hai (unlimited nahi)",
          MAXIMUM.gemini_calls <= 5, str(MAXIMUM.gemini_calls))
    check("depth badhne par sources aur rounds dono badhte hain",
          QUICK.max_sources < DEEP.max_sources < MAXIMUM.max_sources
          and QUICK.max_rounds <= DEEP.max_rounds <= MAXIMUM.max_rounds,
          f"{QUICK.max_sources}/{DEEP.max_sources}/{MAXIMUM.max_sources}")
    check("QUICK mein red team band hai (2 calls ke bina critique possible nahi)",
          QUICK.use_red_team is False and DEEP.use_red_team is True, "red team flag")
    check("books sirf MAXIMUM mein on hain (time/bandwidth budget)",
          MAXIMUM.use_books is True and DEEP.use_books is False
          and QUICK.use_books is False, "books flag")

    # preset mutation leak — ek request dusri request ka config na bigaade
    first = get_depth_config("DEEP")
    first.max_sources = 999
    check("preset copy milta hai, shared object nahi (ek request dusri ko na bigaade)",
          get_depth_config("DEEP").max_sources == DEEP.max_sources == 10,
          str(get_depth_config("DEEP").max_sources))
    check("anjaan mode name par DEEP fallback (crash nahi)",
          get_depth_config("ULTRA_MEGA").name == "DEEP"
          and get_depth_config(None).name == "DEEP", "fallback toota")
    check("mode name case-insensitive hai",
          get_depth_config("quick").gemini_calls == 1, "case handling")

    # ── CUSTOM ke safety rails — yahi asli quota bachane wala hissa hai ──
    greedy = get_depth_config("CUSTOM", {"gemini_calls": 500, "max_sources": 10_000,
                                         "max_rounds": 99, "max_per_connector": 50,
                                         "chars_per_source": 99_999,
                                         "max_fulltext": 400})
    check("CUSTOM ek hi sawal mein poora din ka quota nahi kha sakta (clamp)",
          greedy.gemini_calls == 5 and greedy.max_sources == 40
          and greedy.max_rounds == 4 and greedy.max_per_connector == 10
          and greedy.chars_per_source == 4000 and greedy.max_fulltext == 12,
          str(greedy.to_dict()))
    tiny = get_depth_config("CUSTOM", {"gemini_calls": 0, "max_sources": -5,
                                       "max_rounds": 0, "chars_per_source": 1})
    check("0/negative values bhi clamp hoti hain (kam se kam 1 call)",
          tiny.gemini_calls == 1 and tiny.max_sources == 1
          and tiny.max_rounds == 1 and tiny.chars_per_source == 300,
          str(tiny.to_dict()))
    check("CUSTOM ka naam CUSTOM rehta hai (report mein DEEP nahi dikhta)",
          tiny.name == "CUSTOM", tiny.name)
    check("1 call maangne par red team apne aap off (warna critique pass hi nahi bachta)",
          get_depth_config("CUSTOM", {"gemini_calls": 1,
                                      "use_red_team": True}).use_red_team is False,
          "red team rail toota")
    check("2+ calls par red team on reh sakta hai",
          get_depth_config("CUSTOM", {"gemini_calls": 2,
                                      "use_red_team": True}).use_red_team is True,
          "red team rail over-corrected")
    zero_fulltext = get_depth_config("CUSTOM", {"max_fulltext": 0})
    check("max_fulltext=0 allowed hai (user download poori tarah band kar sakta hai)",
          zero_fulltext.max_fulltext == 0, str(zero_fulltext.max_fulltext))
    check("anjaan CUSTOM key chup-chaap ignore hoti hai (crash nahi)",
          get_depth_config("CUSTOM", {"koi_aisi_key_nahi": 5,
                                      "gemini_calls": None}).gemini_calls == 2,
          "unknown key ne config toda")
    check("CUSTOM ki booleans user se aati hain",
          get_depth_config("CUSTOM", {"use_books": True,
                                      "use_papers": False}).use_books is True
          and get_depth_config("CUSTOM", {"use_papers": False}).use_papers is False,
          "boolean handling")

    # ── quota_note: honesty line jo user ko dikhti hai ──
    note = quota_note(MAXIMUM)
    check("quota note mein asli call budget aur free-tier limit dono likhi hai",
          "maximum 3 Gemini call" in note and "~20 calls/day" in note, note[:100])
    check("quota note batata hai ki full text kitne sources ka padha jayega",
          f"{MAXIMUM.max_fulltext} source(s) ka legally-free full text" in note,
          note[:140])
    check("quota note 'unlimited' ka dava nahi karta",
          "unlimited" not in note.lower(), note[:80])
    check("sawal/din ki ginti asli budget se nikalti hai, hardcoded nahi",
          "6 sawal/din" in quota_note(MAXIMUM)
          and "20 sawal/din" in quota_note(QUICK),
          quota_note(QUICK)[-40:])
    check("quota note network budget bhi batata hai (Spec 13 ka 'time' hissa)",
          f"{MAXIMUM.discovery_seconds}s ka wall-clock budget" in note, note[-160:])

    # ── API se CUSTOM ke saare knobs pahunchte hain ya nahi ──
    # Ye source-TEXT par check hai (fastapi import kiye bina), kyunki asli gap
    # yahi tha: depth.py saat knobs clamp karta tha par request model mein sirf
    # teen fields thi — yaani "user khud time/depth tay kar sake" (Spec 13)
    # aadha hi sach tha. Naya knob depth.py mein jodkar API bhoolna aasan hai,
    # isliye ye test dono ko bandhe rakhta hai.
    from research_engine.depth import BOOL_FIELDS, depth_limits
    routes_src = (pathlib.Path(__file__).parent / "api" / "agent_routes.py").read_text(
        encoding="utf-8")
    missing = [f for f in tuple(depth_limits()) + BOOL_FIELDS
               if f"{f}: Optional" not in routes_src]
    check("CUSTOM ka har knob /deep-research request model mein maujood hai",
          not missing, f"API se nahi bheje ja sakte: {missing}")
    check("depth_limits() wahi limits deta hai jo clamp mein lagti hain",
          depth_limits()["gemini_calls"] == (1, 5)
          and depth_limits()["discovery_seconds"] == (20, 600),
          str(depth_limits()))
    check("depth_limits() copy deta hai (API kabhi asli rails na badal de)",
          (depth_limits().pop("gemini_calls", None) is not None
           and "gemini_calls" in depth_limits()), "rails mutable hain")
    check("/depth-modes limits code se banata hai, hand-typed nahi",
          "depth_limits()" in routes_src and "\"limits\"" in routes_src,
          "disclosure hardcoded hai")


# ── 17. connector query building + failure honesty (live bugs, offline pin) ───
def test_connector_contracts():
    section("17. Connector contracts (live bugs — ab bina network pin hue)")
    from research_engine import orchestrator as orch_module
    from research_engine import content_fetcher as cf_module
    from research_engine.connectors import base as cbase
    from research_engine.connectors import book_connector as bc
    from research_engine.connectors import paper_connector as pc
    from research_engine.connectors import web_connector as wc
    from research_engine.source_discovery import SourceDiscovery

    QUERY = "algorithmic bias in healthcare risk prediction"

    # ── query terms: shared helper jispar arXiv aur guard dono khade hain ──
    terms = cbase.content_terms(QUERY)
    check("query se content words nikalte hain, stopwords ('in') hat jaate hain",
          terms == ["algorithmic", "bias", "healthcare", "risk", "prediction"],
          str(terms))
    check("Hinglish stopwords bhi hatti hain (kya/hai/ke)",
          cbase.content_terms("diabetes ka ilaj kya hai") == ["diabetes", "ilaj"],
          str(cbase.content_terms("diabetes ka ilaj kya hai")))
    check("term overlap halka stemming karta hai (models -> model)",
          cbase.term_overlap(["models", "bias"], "a bias model of care") == 2,
          str(cbase.term_overlap(["models", "bias"], "a bias model of care")))
    check("limit=None par saare terms milte hain (select_terms ko poori list chahiye)",
          len(cbase.content_terms(QUERY + " systematic review", limit=None)) == 7,
          str(cbase.content_terms(QUERY + " systematic review", limit=None)))
    # Devanagari: pehla regex sirf A-Za-z0-9 tha, to Hindi query par terms KHAALI
    # aate the — arXiv wapas purani buggy "poori sentence" query bhejta tha AUR
    # relevance guard bhi band ho jaata tha. Hindi mein poochhne par dono safety
    # net gayab — ye chhupa hua bug tha.
    hindi = cbase.content_terms("मधुमेह का इलाज क्या है")
    check("Devanagari query se bhi terms nikalte hain (guard band nahi hota)",
          hindi == ["मधुमेह", "इलाज"], str(hindi))
    # Doosri parat: matra/virama (ु े ्) Unicode combining marks hain, jinhe
    # Python ka \w word character nahi maanta. Sirf `[^\W_]` lagane par "मधुमेह"
    # ["मध","म","ह"] ban jaata tha aur 3-letter filter mein poora ud jaata tha —
    # yaani "fix" ke baad bhi Hindi terms khaali hi rehte the.
    check("matra/virama shabd ko todti nahi (मधुमेह ek hi term rehta hai)",
          "मधुमेह" in hindi and "मध" not in hindi, str(hindi))
    check("क्या/में/के jaise Hindi function words bhi stopword hain",
          cbase.content_terms("कैंसर के इलाज में AI की भूमिका")
          == ["कैंसर", "इलाज", "भूमिका"],
          str(cbase.content_terms("कैंसर के इलाज में AI की भूमिका")))
    check("Hindi query par relevance guard sach mein kaam karta hai",
          cbase.term_overlap(hindi, "मधुमेह के इलाज par ek adhyayan") == 2
          and cbase.term_overlap(hindi, "शेयर बाजार में जोखिम का अध्ययन") == 0,
          str(hindi))
    check("accent/hyphen wale English shabd bhi ek term rehte hain",
          cbase.content_terms("naïve Bayes co-operative state-of-the-art")
          == ["naïve", "bayes", "co-operative", "state-of-the-art"],
          str(cbase.content_terms("naïve Bayes co-operative state-of-the-art")))

    # ── select_terms: rounds ki query alag honi chahiye ──
    # planner round 2/3 mein steering words AAKHIR mein jodta hai. Pehle sirf
    # `content_terms(limit=5)` liya jaata tha, to teeno rounds ka arXiv query
    # bilkul ek jaisa banta tha — round 2/3 ki API calls bekaar jaa rahi thi.
    r1 = cbase.select_terms(QUERY, 5)
    r2 = cbase.select_terms(QUERY + " systematic review", 5)
    r3 = cbase.select_terms(QUERY + " contradictory findings", 5)
    check("select_terms aakhir wala steering word rakhta hai (round 2 ka matlab)",
          r2[-1] == "review" and len(r2) == 5, str(r2))
    check("round 1/2/3 ke arXiv terms alag hain (pehle teeno same the — chhupa bug)",
          r1 != r2 and r2 != r3 and r1 != r3, f"{r1} | {r2} | {r3}")
    check("cap se kam terms hon to sab rakhe jaate hain",
          cbase.select_terms("diabetes ilaj", 5) == ["diabetes", "ilaj"],
          str(cbase.select_terms("diabetes ilaj", 5)))

    # ── arXiv: LIVE BUG — healthcare query par portfolio-risk ka paper aaya ──
    built = pc.ArxivConnector.build_search_query(QUERY, 5)
    check("arXiv query AND se judti hai (poori sentence dheeli match nahi hoti)",
          built.count(" AND ") == 4 and built.startswith('all:"algorithmic"'), built)
    check("arXiv ka har term quote mein jaata hai",
          built.count('all:"') == 5, built)
    check("terms khatam ho jaayen to bhi query banti hai (crash nahi)",
          pc.ArxivConnector.build_search_query("the and of") == 'all:"the and of"',
          pc.ArxivConnector.build_search_query("the and of"))

    ARXIV_XML = b"""<feed xmlns="http://www.w3.org/2005/Atom">
     <entry>
      <id>http://arxiv.org/abs/1111.1111v1</id>
      <title>Sequential Design and Spatial Modeling for Portfolio Tail Risk
      Measurement</title>
      <summary>Estimating the left tail of portfolio loss with economic scenario
      generators and capital requirements.</summary>
      <published>2018-04-01T00:00:00Z</published>
      <author><name>A Author</name></author>
     </entry>
     <entry>
      <id>http://arxiv.org/abs/2222.2222v1</id>
      <title>Algorithmic Bias in Clinical Risk Prediction Models</title>
      <summary>We audit healthcare risk prediction algorithms for racial bias.
      </summary>
      <published>2023-06-02T00:00:00Z</published>
      <author><name>B Author</name></author>
     </entry>
    </feed>"""
    EMPTY_XML = b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    real_paper_get = pc.http_get
    seen_params = []
    # env restore crash-safe rakho — warna beech mein ek check toota to
    # baad ke checks jhoothe fail hone lagte hain (mutation test mein pakda gaya)
    saved_env = {k: os.environ.get(k) for k in
                 ("SEMANTIC_SCHOLAR_API_KEY", "GOOGLE_BOOKS_COUNTRY", "TAVILY_API_KEY",
                  "CONNECTOR_RETRIES", "CONNECTOR_READ_TIMEOUT",
                  "CONNECTOR_CONNECT_TIMEOUT")}

    def restore_env():
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    class _Resp:
        def __init__(self, content=b"", payload=None, status=200, headers=None):
            self.content = content
            self._payload = payload if payload is not None else {}
            self.status_code = status
            self.headers = headers or {}

        def json(self):
            return self._payload

    def fake_clock():
        """
        Nakli ghadi: sleep turant hota hai par ghadi aage badh jaati hai.
        arXiv ka throttle `time.time()` bhi padhta hai, isliye sirf `sleep` stub
        karna kaafi nahi — poora clock deterministic chahiye, warna suite ya to
        sach mein 3-3 second sota hai ya AttributeError deta hai.
        """
        state = {"t": 1000.0, "slept": []}

        def _sleep(seconds):
            state["slept"].append(seconds)
            state["t"] += seconds

        state["module"] = types.SimpleNamespace(
            sleep=_sleep, time=lambda: state["t"], monotonic=lambda: state["t"])
        return state

    real_paper_time = pc.time
    try:
        # arXiv ka throttle process-wide hai; test ko deterministic rakhne ke liye
        # nakli ghadi aur saaf slate se shuru karo
        clock = fake_clock()
        pc.time = clock["module"]
        pc.ArxivConnector._last_request_at = 0.0

        pc.http_get = lambda url, params=None, **kw: (
            seen_params.append(params) or _Resp(content=ARXIV_XML))
        result = pc.ArxivConnector().safe_search(QUERY, 3)
        titles = [r.title for r in result["records"]]
        check("arXiv ka asli live bug pakda gaya: portfolio-risk paper girta hai",
              not any("Portfolio" in t for t in titles), str(titles))
        check("sahi paper bacha rehta hai (guard sab kuch nahi kha jaata)",
              len(titles) == 1 and "Algorithmic Bias" in titles[0], str(titles))
        check("arXiv relevance se sort maangta hai (default = submission date)",
              seen_params[-1].get("sortBy") == "relevance", str(seen_params[-1]))
        check("guard kuch girayega, isliye arXiv thode extra results maangta hai",
              seen_params[-1].get("max_results", 0) > 3, str(seen_params[-1]))
        check("guard ne kya hataya, wo honestly note mein likha jaata hai",
              "relevance guard" in result["note"], result["note"])
        check("preprint kabhi peer-reviewed nahi dikhaya jaata",
              all(r.peer_reviewed is False for r in result["records"]), "peer flag")

        # ── C1: note ne guard ko GALAT blame kiya (har successful search par) ──
        # `dropped` pehle `[:max_results]` ke BAAD nikala jaata tha, yaani normal
        # limit ka blame bhi relevance guard par chala jaata tha. 4+ sahi results
        # par bhi note kehta tha "guard ne hataye" — jabki guard ne kuch nahi hataya.
        many = b'<feed xmlns="http://www.w3.org/2005/Atom">' + b"".join(
            (f"""<entry><id>http://arxiv.org/abs/90{i}.000{i}v1</id>
                 <title>Algorithmic Bias in Healthcare Risk Prediction part {i}</title>
                 <summary>healthcare bias and risk prediction audit {i}</summary>
                 <published>2024-01-0{i}T00:00:00Z</published>
                 <author><name>X Y</name></author></entry>""").encode()
            for i in range(1, 7)) + b"</feed>"
        pc.http_get = lambda url, params=None, **kw: _Resp(content=many)
        capped = pc.ArxivConnector().safe_search(QUERY, 3)
        check("6 relevant result + max_results=3 par sirf 3 lautte hain",
              capped["count"] == 3, str(capped["count"]))
        check("C1 fix: max_results ki limit ka blame relevance guard par nahi jaata",
              "guard ne hataye" not in capped["note"], capped["note"])
        check("cap lagne par note saaf kehta hai ki guard ne kuch nahi hataya",
              "max_results" in capped["note"]
              and "kuch nahi hataya" in capped["note"], capped["note"])
        check("sirf cap lagi ho to reason khaali rehta hai (ye failure nahi hai)",
              capped["reason"] == "", str(capped["reason"]))

        # ── I1: sab results guard ne hata diye = "khaali" NAHI, "chhaanta" ──
        pc.http_get = lambda url, params=None, **kw: _Resp(content=ARXIV_XML)
        filtered = pc.ArxivConnector().safe_search("quantum lattice cryptography", 3)
        check("sab result topic se door hon to reason 'filtered' hota hai",
              filtered["count"] == 0 and filtered["reason"] == "filtered",
              f"{filtered['count']} / {filtered['reason']}")
        check("'humne chhaanta' aur 'kuch nahi mila' ka farak note mein bhi likha hai",
              "alag baat hai" in filtered["note"], filtered["note"])

        # strict query par 0 mile to apne aap dheeli query se dobara try karo
        seen_params.clear()
        calls = {"n": 0}

        def _laddered(url, params=None, **kw):
            calls["n"] += 1
            seen_params.append(params)
            return _Resp(content=EMPTY_XML if calls["n"] == 1 else ARXIV_XML)

        pc.http_get = _laddered
        clock = fake_clock()                    # naya slate: sleeps yahin se ginte hain
        pc.time = clock["module"]
        pc.ArxivConnector._last_request_at = 0.0
        laddered = pc.ArxivConnector().safe_search(QUERY, 3)
        slept = clock["slept"]
        check("5 term par 0 mila to arXiv kam terms se dobara try karta hai",
              calls["n"] >= 2 and seen_params[0]["search_query"].count(" AND ")
              > seen_params[1]["search_query"].count(" AND "),
              f"{calls['n']} calls")
        check("dheeli query se mile results bhi guard se guzarte hain",
              len(laddered["records"]) == 1, str(laddered["count"]))
        check("arXiv ki 3-second guideline maani jaati hai (requests ke beech gap)",
              slept and all(s >= 3 for s in slept), str(slept))
        check("pehli query par sleep nahi hota (aam case slow na ho)",
              len(slept) == calls["n"] - 1, f"{len(slept)} sleeps / {calls['n']} calls")
        check("arXiv https par jaata hai (plain http kai network block karte hain)",
              "https://export.arxiv.org" in inspect.getsource(pc.ArxivConnector.search),
              "http:// mila")

        # ── I3: ladder ka aakhri padav 1 term hai (2 par rukna ek pakka 0 tha) ──
        # `all:"diabetes" AND all:"ilaj"` arXiv par hamesha 0 deta hai (Hinglish
        # shabd wahan nahi hai), par sirf `all:"diabetes"` se asli papers milte hain.
        seen_params.clear()
        calls["n"] = 0
        pc.http_get = lambda url, params=None, **kw: (
            seen_params.append(params) or _Resp(content=EMPTY_XML))
        clock = fake_clock()
        pc.time = clock["module"]
        pc.ArxivConnector._last_request_at = 0.0
        pc.ArxivConnector().safe_search("diabetes ka ilaj kya hai", 3)
        ands = [p["search_query"].count(" AND ") for p in seen_params]
        check("ladder aakhir mein single-term query bhejta hai (2 par nahi rukta)",
              ands and ands[-1] == 0, str(ands))
        check("ladder mein ek hi query do baar nahi jaati (bekaar API call nahi)",
              len({p["search_query"] for p in seen_params}) == len(seen_params),
              str([p["search_query"] for p in seen_params]))

        # ── C2: parallel queries ke note aapas mein mil jaate the ──
        # source_discovery._tasks EK HI connector object ko har query ke liye
        # submit karta hai (DEEP round 2 = 3 queries = 3 threads, ek object).
        # last_note/last_reason plain instance attribute the, to ek thread ka
        # "sabhi topic se door the" doosre thread ke SUCCESSFUL result par chipak
        # jaata tha — user ko us source ke baare mein ulta sach dikhta tha.
        pc.http_get = lambda url, params=None, **kw: _Resp(content=ARXIV_XML)
        clock = fake_clock()
        pc.time = clock["module"]
        pc.ArxivConnector._last_request_at = 0.0
        shared = pc.ArxivConnector()          # JAAN-BOOJH KAR ek hi object
        out: Dict[int, Dict] = {}
        lock = threading.Lock()

        def _worker(i: int):
            q = QUERY if i % 2 == 0 else "quantum lattice cryptography"
            res = shared.safe_search(q, 3)
            with lock:
                out[i] = res

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        check("8 parallel search ek hi connector object par chalti hain (crash nahi)",
              len(out) == 8, f"{len(out)} results")
        good = [r for i, r in out.items() if i % 2 == 0]
        bad = [r for i, r in out.items() if i % 2 == 1]
        check("C2: jo query safal thi uske note par doosri query ka faisla nahi chipka",
              all(r["count"] == 1 and "sabhi topic se door" not in r["note"]
                  for r in good), str([r["note"] for r in good])[:200])
        check("C2: jiske sab result chhante, sirf USKA reason 'filtered' hai",
              all(r["reason"] == "filtered" for r in bad)
              and all(r["reason"] == "" for r in good),
              str([(r["count"], r["reason"]) for r in out.values()]))
        check("count>0 aur 'filtered' kabhi ek saath nahi ho sakte (invariant)",
              all(not (r["count"] > 0 and r["reason"] == "filtered")
                  for r in out.values()), "invariant toota")

        # ── Crossref: LIVE BUG — 2025 ke SSRN DOI par year=None ──
        pick = pc.CrossrefConnector.pick_year
        check("year 'published' se milta hai (SSRN/preprint records ka case)",
              pick({"published": {"date-parts": [[2025, 3, 4]]}}) == 2025, "published")
        check("year 'issued' se bhi milta hai",
              pick({"issued": {"date-parts": [[2019]]}}) == 2019, "issued")
        check("aakhri sahara 'created' ki date-time string bhi chalti hai",
              pick({"created": {"date-time": "2021-07-02T00:00:00Z"}}) == 2021, "created")
        check("print date ho to created se pehle chuni jaati hai",
              pick({"published-print": {"date-parts": [[2016]]},
                    "created": {"date-parts": [[2020]]}}) == 2016, "precedence")
        # I10: pehle `published-print` ko `published-online` se OOPAR rakha tha.
        # Online-first papers (aaj ke journals mein aam) ka saal isse ek-do saal
        # aage khisak jaata tha, aur "kitna naya evidence hai" ka poora hisaab
        # galat ho jaata tha — recency scoring isi year par khadi hai.
        check("online-first paper ka saal online date se aata hai, print se nahi",
              pick({"published-online": {"date-parts": [[2023, 11]]},
                    "published-print": {"date-parts": [[2024, 2]]}}) == 2023,
              str(pick({"published-online": {"date-parts": [[2023, 11]]},
                        "published-print": {"date-parts": [[2024, 2]]}})))
        check("date kahin na ho to year None rehta hai (0 ya aaj ka saal nahi)",
              pick({"published-print": {"date-parts": [[None]]}}) is None, "empty")
        # NOTE: pehle ye check `f in _SELECT` (ek comma-joined STRING) tha —
        # "published" to "published-print" ke andar bhi mil jaata hai, isliye
        # wo assertion kabhi fail hi nahi ho sakti thi. Ab list par check hai.
        check("asli bug ki jad: har date field Crossref se maangi bhi jaati hai",
              all(f in pc.CrossrefConnector._SELECT_FIELDS
                  for f in pc.CrossrefConnector._DATE_FIELDS),
              str(pc.CrossrefConnector._DATE_FIELDS))
        check("select list se hi URL banti hai (string aur list alag na ho jaayen)",
              pc.CrossrefConnector._SELECT
              == ",".join(pc.CrossrefConnector._SELECT_FIELDS),
              pc.CrossrefConnector._SELECT)

        # ── I14: PubMed ka peer_reviewed pehle blanket True tha ──
        # PubMed mein editorial, letter, comment, news aur preprint bhi hote hain.
        # Un sabko "peer-reviewed" batana Spec §7 ke source-honesty rule ka
        # seedha ullanghan tha — evidence weight isi flag par chalti hai.
        peer = pc.PubMedConnector.peer_status
        check("journal article peer-reviewed maana jaata hai",
              peer(["Journal Article"]) is True, str(peer(["Journal Article"])))
        check("RCT / meta-analysis bhi peer-reviewed hain",
              peer(["Randomized Controlled Trial"]) is True
              and peer(["Meta-Analysis"]) is True, "trial/meta")
        check("I14: editorial ko peer-reviewed nahi kaha jaata",
              peer(["Editorial"]) is False, str(peer(["Editorial"])))
        check("letter/comment/preprint bhi peer-reviewed nahi hain",
              peer(["Letter"]) is False and peer(["Comment"]) is False
              and peer(["Preprint"]) is False, "letter/comment/preprint")
        check("mila-jula case ho to 'nahi' jeetta hai (safe taraf jhukte hain)",
              peer(["Journal Article", "Retracted Publication"]) is False,
              str(peer(["Journal Article", "Retracted Publication"])))
        check("pubtype hi na ho to None (jhoothi haan nahi, imaandar 'pata nahi')",
              peer([]) is None and peer(None) is None, str(peer([])))
        check("anjaan type par bhi None rehta hai",
              peer(["Dataset"]) is None, str(peer(["Dataset"])))

        # ── Semantic Scholar: key ho to header jaaye ──
        captured_headers = {}

        def _ss(url, params=None, headers=None, **kw):
            captured_headers["h"] = headers
            return _Resp(payload={"data": []})

        pc.http_get = _ss
        os.environ["SEMANTIC_SCHOLAR_API_KEY"] = "test-key-123"
        pc.SemanticScholarConnector().safe_search("x", 2)
        check("Semantic Scholar key .env mein ho to header mein jaati hai",
              (captured_headers["h"] or {}).get("x-api-key") == "test-key-123",
              str(captured_headers["h"]))
        os.environ.pop("SEMANTIC_SCHOLAR_API_KEY", None)
        no_key = pc.SemanticScholarConnector().safe_search("x", 2)
        check("bina key ke khaali result par wajah batayi jaati hai",
              "API key" in no_key["note"] and no_key["count"] == 0, no_key["note"])
    finally:
        pc.http_get = real_paper_get
        restore_env()

    # ── Google Books: LIVE BUG — India se country param ke bina 0 results ──
    params = bc.GoogleBooksConnector().build_params(QUERY, 3)
    check("Google Books ko country bheja jaata hai (iske bina India se khaali)",
          len(str(params.get("country", ""))) == 2, str(params))
    check("sirf books maangte hain (magazine noise nahi)",
          params.get("printType") == "books", str(params))
    check("maxResults API ki hard limit 40 par clamp hota hai",
          bc.GoogleBooksConnector().build_params("x", 500)["maxResults"] == 40,
          str(bc.GoogleBooksConnector().build_params("x", 500)["maxResults"]))
    try:
        # env khaali ho to default IN (user India mein hai) — par env jeetta hai
        os.environ.pop("GOOGLE_BOOKS_COUNTRY", None)
        check("env khaali ho to default country IN hai",
              bc.GoogleBooksConnector().build_params("x", 3)["country"] == "IN",
              "default country")
        os.environ["GOOGLE_BOOKS_COUNTRY"] = "us"
        check("country .env se badla ja sakta hai (US/UK users ke liye)",
              bc.GoogleBooksConnector().build_params("x", 3)["country"] == "US",
              "env override")
        # galat code chup-chaap jaane par API phir 0 results de deti hai —
        # yahi asli bug tha, isliye validation ke bina fix adhoora hai
        for bad in ("IND", "1N", "i", "  ", "in-IN"):
            os.environ["GOOGLE_BOOKS_COUNTRY"] = bad
            check(f"galat country code ({bad!r}) chup-chaap aage nahi jaata",
                  bc.GoogleBooksConnector().build_params("x", 3)["country"] == "IN",
                  bc.GoogleBooksConnector().build_params("x", 3)["country"])
        os.environ["GOOGLE_BOOKS_COUNTRY"] = " in "
        check("lowercase/space wala sahi code saaf karke maana jaata hai",
              bc.GoogleBooksConnector().build_params("x", 3)["country"] == "IN",
              "normalize")
    finally:
        restore_env()

    # ── Spec ka paywall rule: preview ko "full text" kabhi nahi kehna ──
    real_book_get_v = bc.http_get
    try:
        def _volumes(url, params=None, **kw):
            return _Resp(payload={"totalItems": 3, "items": [
                {"volumeInfo": {"title": "Public Domain Classic",
                                "infoLink": "http://books.example/1"},
                 "accessInfo": {"viewability": "ALL_PAGES_PUBLIC_DOMAIN",
                                "publicDomain": True}},
                {"volumeInfo": {"title": "Paywalled Textbook",
                                "infoLink": "http://books.example/2"},
                 "accessInfo": {"viewability": "PARTIAL", "publicDomain": False}},
                {"volumeInfo": {"title": "No Preview At All",
                                "infoLink": "http://books.example/3"},
                 "accessInfo": {"viewability": "NO_PAGES", "publicDomain": False}},
            ]})

        bc.http_get = _volumes
        vols = {r.title: r for r in bc.GoogleBooksConnector().search("x", 3)}
        check("public-domain book ka full text legally available maana jaata hai",
              vols["Public Domain Classic"].full_text_available is True,
              str(vols["Public Domain Classic"].full_text_available))
        check("PARTIAL preview ko full text NAHI kaha jaata (spec ka paywall rule)",
              vols["Paywalled Textbook"].full_text_available is False,
              str(vols["Paywalled Textbook"].full_text_available))
        check("NO_PAGES bhi full text nahi hai",
              vols["No Preview At All"].full_text_available is False,
              str(vols["No Preview At All"].full_text_available))
        check("snippet mein availability honestly likhi jaati hai",
              "sirf preview" in vols["Paywalled Textbook"].snippet
              and "full text legally available" in vols["Public Domain Classic"].snippet,
              vols["Paywalled Textbook"].snippet[-60:])
        check("book ka peer_reviewed None rehta hai (jhoothi haan nahi)",
              all(r.peer_reviewed is None for r in vols.values()), "peer flag")
    finally:
        bc.http_get = real_book_get_v

    # ── Internet Archive + Open Library: LIVE BUG — 8s timeout par fail ──
    real_book_get = bc.http_get
    book_calls = []
    try:
        bc.http_get = lambda url, params=None, timeout=None, **kw: (
            book_calls.append((url, timeout))
            or _Resp(payload={"response": {"docs": []}, "docs": [], "items": []}))
        bc.InternetArchiveConnector().safe_search("x", 3)
        bc.OpenLibraryConnector().safe_search("x", 3)
        timeouts = [t for _, t in book_calls]
        check("slow free sources ko (connect, read) tuple timeout milta hai",
              all(isinstance(t, tuple) and len(t) == 2 for t in timeouts),
              str(timeouts))
        check("read window purane 8s se bada hai (archive.org ka ReadTimeout fix)",
              all(t[1] > 8 for t in timeouts), str(timeouts))
        check("connect window bhi bada hai (open_library ka ConnectTimeout fix)",
              all(t[0] > 8 for t in timeouts), str(timeouts))
        gb = bc.GoogleBooksConnector().safe_search("x", 3)
        check("Google Books khaali laute to totalItems/country wajah likhta hai",
              "country=" in gb["note"], gb["note"])
    finally:
        bc.http_get = real_book_get

    # ── C4 + I8 + I12: env knobs sach mein un code paths tak pahunchte hain ──
    # C4: `_SLOW_TIMEOUT` book_connector mein hard-coded (15, 45) tha. Error
    # message user ko kehta tha "CONNECTOR_READ_TIMEOUT badha do", par usse
    # slow sources par koi asar hi nahi hota tha — jis knob ki salah di, wo
    # kaam hi nahi karta tha. Ye advice ko jhooth banata hai.
    check("C4: slow book sources base ke SLOW_TIMEOUT se judte hain (hard-code nahi)",
          bc._SLOW_TIMEOUT is cbase.SLOW_TIMEOUT,
          f"{bc._SLOW_TIMEOUT} vs {cbase.SLOW_TIMEOUT}")
    check("I8: full-text download bhi utna hi sabr karta hai jitna search",
          cf_module._TIMEOUT is cbase.SLOW_TIMEOUT,
          f"{cf_module._TIMEOUT} vs {cbase.SLOW_TIMEOUT}")
    check("SLOW_TIMEOUT default se kabhi kam nahi hota",
          cbase.SLOW_TIMEOUT[0] >= 15 and cbase.SLOW_TIMEOUT[1] >= 45,
          str(cbase.SLOW_TIMEOUT))
    try:
        os.environ["CONNECTOR_READ_TIMEOUT"] = "60"
        spec = importlib.util.spec_from_file_location(
            "research_engine.connectors._base_probe", cbase.__file__)
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        check("CONNECTOR_READ_TIMEOUT=60 general timeout badhata hai",
              probe.DEFAULT_TIMEOUT[1] == 60, str(probe.DEFAULT_TIMEOUT))
        check("C4: wahi knob slow sources ko bhi 60s deta hai (45 par nahi atkta)",
              probe.SLOW_TIMEOUT == (15, 60), str(probe.SLOW_TIMEOUT))
        os.environ["CONNECTOR_RETRIES"] = "0"
        os.environ.pop("CONNECTOR_READ_TIMEOUT", None)
        probe2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe2)
        check("I12: CONNECTOR_RETRIES=0 sach mein retry band karta hai",
              probe2.RETRIES == 0, str(probe2.RETRIES))
        os.environ["CONNECTOR_RETRIES"] = "-5"
        probe3 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe3)
        check("bekaar value (-5) par retry 0 par rukta hai, crash nahi",
              probe3.RETRIES == 0, str(probe3.RETRIES))
        os.environ["CONNECTOR_CONNECT_TIMEOUT"] = "abcd"
        probe4 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe4)
        check("galat timeout value par default lagta hai (module import fail nahi hota)",
              probe4.CONNECT_TIMEOUT == 10, str(probe4.CONNECT_TIMEOUT))
    finally:
        os.environ.pop("CONNECTOR_CONNECT_TIMEOUT", None)
        restore_env()

    # ── http_get: HTTP status ko honest exception banata hai ──
    fake_requests = types.ModuleType("requests")
    real_requests = sys.modules.get("requests")
    real_backoff = cbase._BACKOFF_SECONDS
    try:
        cbase._BACKOFF_SECONDS = 0        # test slow na ho
        sys.modules["requests"] = fake_requests

        for status, expected in ((429, cbase.RateLimited),
                                 (503, cbase.RateLimited),
                                 (403, cbase.AccessBlocked),
                                 (500, cbase.ConnectorHTTPError)):
            fake_requests.get = lambda *a, **k: _Resp(status=status)
            raised = None
            try:
                cbase.http_get("http://x", retries=0)
            except Exception as exc:
                raised = exc
            check(f"HTTP {status} -> {expected.__name__} (chup-chaap 0 results nahi)",
                  isinstance(raised, expected), f"{type(raised).__name__}")

        attempts = {"n": 0}

        class ConnectTimeout(Exception):
            pass

        def _always_timeout(*a, **k):
            attempts["n"] += 1
            raise ConnectTimeout("connect timeout")

        fake_requests.get = _always_timeout
        raised = None
        try:
            cbase.http_get("http://x", retries=1)
        except Exception as exc:
            raised = exc
        check("timeout par ek retry hoti hai (slow server ko dusra mauka)",
              attempts["n"] == 2, f"{attempts['n']} attempts")
        check("retry ke baad bhi fail ho to asli exception aage jaati hai",
              isinstance(raised, ConnectTimeout), type(raised).__name__)

        # ── I9: 429 par server ka Retry-After maana jaata hai (cap ke saath) ──
        # Pehle sirf fixed backoff tha. Rate-limited free API ko uske bataye
        # waqt se pehle dobara maarna = agla 429 pakka, yaani source hamesha
        # ke liye "ruka" reh jaata. Par header par blindly bharosa bhi nahi
        # kar sakte — kuch API 600s maang leti hain aur poora research atak jaata.
        cbase._BACKOFF_SECONDS = 1.5
        real_base_time = cbase.time
        try:
            for header, expected, why in (
                ({"Retry-After": "2"}, 2.0, "server ka 2s maana jaata hai"),
                ({"Retry-After": "600"}, 8.0, "600s ki demand cap par kati jaati hai"),
                ({"Retry-After": "0"}, 1.5, "0/negative par apna backoff chalta hai"),
                ({"Retry-After": "soon"}, 1.5, "garbage header par crash nahi"),
                ({}, 1.5, "header na ho to apna backoff"),
            ):
                clk = fake_clock()
                cbase.time = clk["module"]
                fake_requests.get = (
                    lambda *a, _h=header, **k: _Resp(status=429, headers=_h))
                try:
                    cbase.http_get("http://x", retries=1)
                except cbase.RateLimited:
                    pass
                check(f"I9: {why}", clk["slept"] == [expected], str(clk["slept"]))
        finally:
            cbase.time = real_base_time
            cbase._BACKOFF_SECONDS = 0

        # safe_search ka kaam: exception ko honest reason mein badalna
        class _Boom(cbase.BaseConnector):
            name = "boom"

            def search(self, query, max_results=3):
                raise ConnectTimeout("read timeout=45")

        boomed = _Boom().safe_search("x", 1)
        check("timeout ka reason 'timeout' likha jaata hai, 'khaali' nahi",
              boomed["reason"] == "timeout" and boomed["count"] == 0,
              str(boomed["reason"]))
        check("timeout par user ko batate hain ki source free hai, sirf slow",
              "slow" in boomed["error"], boomed["error"][:80])
    finally:
        cbase._BACKOFF_SECONDS = real_backoff
        if real_requests is not None:
            sys.modules["requests"] = real_requests
        else:
            sys.modules.pop("requests", None)

    # ── C3: Tavily bina key = "0 results" NAHI, "search chali hi nahi" ──
    # Pehle key na hone par WebConnector chupchaap khaali list lauta deta tha,
    # jisse discovery_note usko "khaali (search chali, result 0)" bucket mein
    # daal deta tha AUR research memory mein "chala par 0 result mila" likh
    # deta tha. Dono jhooth the — Tavily chali hi nahi thi.
    try:
        os.environ.pop("TAVILY_API_KEY", None)
        tav = wc.TavilyConnector().safe_search("x", 3)
        check("C3: Tavily key na ho to reason 'no_key' hai (khaali nahi)",
              tav["reason"] == "no_key" and tav["count"] == 0,
              f"{tav['reason']} / {tav['count']}")
        check("error mein saaf likha hai ki kaunsi key .env mein daalni hai",
              "TAVILY_API_KEY" in tav["error"], tav["error"][:120])
        check("'result nahi mila' se alag baat hai — ye user ko batate hain",
              "alag baat hai" in tav["error"], tav["error"][:120])
        check("no_key 'ruka' bucket mein jaata hai, 'khaali' mein nahi",
              "no_key" in SourceDiscovery._STOPPED_REASONS,
              str(SourceDiscovery._STOPPED_REASONS))
    finally:
        restore_env()

    # ── discovery note: 5 alag bucket (yahi asli honesty hai) ──
    note = SourceDiscovery.discovery_note([
        {"connector": "openalex", "count": 3, "error": "", "reason": ""},
        {"connector": "doaj", "count": 0, "error": "", "reason": ""},
        {"connector": "semantic_scholar", "count": 0,
         "error": "rate limited: HTTP 429", "reason": "rate_limited"},
        {"connector": "internet_archive", "count": 0,
         "error": "ReadTimeout", "reason": "timeout"},
        {"connector": "tavily", "count": 0,
         "error": "skipped: TAVILY_API_KEY nahi hai", "reason": "no_key"},
        {"connector": "pubmed", "count": 0, "error": "90s budget khatam",
         "reason": "deadline"},
        {"connector": "arxiv_alt", "count": 0, "error": "", "reason": "filtered"},
        {"connector": "crossref", "count": 0, "error": "KeyError: 'x'",
         "reason": "error"},
        {"connector": "arxiv", "count": 2, "error": "", "reason": "",
         "note": "5 mein se 3 relevance guard se hate"},
    ])
    check("jo mila wo count ke saath dikhta hai",
          "openalex(3)" in note, note)
    check("sach mein khaali (search chali, result 0) alag bucket mein hai",
          "khaali (search chali, result 0): doaj" in note, note)
    check("rate limit aur timeout 'ruka — search hi nahi hui' mein jaate hain",
          "ruka" in note and "semantic_scholar [API ne rate limit lagayi]" in note
          and "internet_archive [server slow tha]" in note, note)
    check("reason ab code-word nahi, seedhi Hinglish wajah hai",
          "rate_limited" not in note and "no_key" not in note, note)
    check("C3: no_key bhi 'ruka' mein dikhta hai, wajah ke saath",
          "tavily [API key nahi hai]" in note, note)
    check("deadline (budget khatam) bhi 'ruka' hai — humne dekha hi nahi",
          "pubmed [time budget khatam]" in note, note)
    check("'humne chhaanta' ka apna bucket hai (khaali se alag)",
          "chhaante gaye (result aaye par topic se door the): arxiv_alt" in note, note)
    check("code ki galti (KeyError) 'fail' mein alag rehti hai",
          "fail: crossref" in note, note)
    check("connector ka apna note bhi report tak pahunchta hai",
          "relevance guard" in note, note)
    check("khaali aur ruka kabhi ek hi bucket mein nahi milte",
          "khaali (search chali, result 0): doaj |" in note
          and "semantic_scholar" not in note.split("ruka")[0].split("khaali")[1],
          note)
    check("har stopped reason ke liye Hinglish text maujood hai (koi khaali na rahe)",
          all(r in SourceDiscovery._REASON_TEXT
              for r in SourceDiscovery._STOPPED_REASONS),
          str(sorted(SourceDiscovery._REASON_TEXT)))

    # ── I6: discovery ka wall-clock budget (Spec §13) ──
    # Gemini calls par rail pehle din se thi, network par koi rail nahi thi.
    # Ek atka connector poore research ko minute-bhar rok sakta tha, aur report
    # mein wo "0 results" jaisa dikhta tha.
    disco = SourceDiscovery(max_workers=4)
    fast_record = SourceRecord(title="fast one", url="http://fast.example/1",
                               snippet="ok", connector="fast")

    def _fast():
        return {"records": [fast_record],
                "log": [{"connector": "fast", "count": 1, "error": "", "reason": ""}]}

    def _stuck():
        time.sleep(3)
        return {"records": [], "log": [{"connector": "stuck", "count": 0}]}

    real_tasks = disco._tasks
    try:
        disco._tasks = lambda *a, **k: [("fast", _fast), ("stuck", _stuck)]
        started = time.time()
        res = disco.discover(["q"], {"web": False}, budget_seconds=1)
        elapsed = time.time() - started
        entries = {e.get("connector"): e for e in res["log"]}
        check("budget khatam hone par discover() wahin lautta hai (hang nahi)",
              elapsed < 2.5, f"{round(elapsed, 2)}s")
        check("I6: atka connector 'deadline' reason ke saath log hota hai",
              entries.get("stuck", {}).get("reason") == "deadline",
              str(entries.get("stuck")))
        check("deadline ka matlab report mein bhi likha hai ('dekha hi nahi gaya')",
              "dekha hi nahi gaya" in str(entries.get("stuck", {}).get("error")),
              str(entries.get("stuck", {}).get("error"))[:120])
        check("jo connector time par aa gaya, uske results bachte hain",
              [r.title for r in res["records"]] == ["fast one"],
              str([r.title for r in res["records"]]))
        check("discover() apna budget aur laga hua time dono batata hai",
              res.get("budget_seconds") == 1 and isinstance(res.get("seconds"), float),
              f"{res.get('budget_seconds')} / {res.get('seconds')}")
    finally:
        disco._tasks = real_tasks

    check("depth config network budget bhi deta hai (sirf Gemini calls nahi)",
          get_depth_config("quick").discovery_seconds
          < get_depth_config("deep").discovery_seconds
          < get_depth_config("maximum").discovery_seconds,
          f"{get_depth_config('quick').discovery_seconds} / "
          f"{get_depth_config('deep').discovery_seconds} / "
          f"{get_depth_config('maximum').discovery_seconds}")
    check("orchestrator depth ka budget discovery tak pahunchata hai",
          "budget_seconds=getattr(config, \"discovery_seconds\", None)"
          in inspect.getsource(orch_module.DeepResearchEngine),
          "budget wiring nahi mili")


# ── 18. source quality signals (Spec 7 — methodology/retraction/COI) ─────────
def test_quality_signals() -> None:
    section("18. Quality signals (Spec 7 — methodology, retraction, COI)")

    from research_engine import quality_signals as qs
    import research_engine.orchestrator as orch_module
    from research_engine.connectors.paper_connector import (
        CrossrefConnector, PubMedConnector,
    )
    from research_engine.content_fetcher import ContentFetcher
    from research_engine.dedup import DeduplicationEngine

    # ── methodology: publication type se (jo pehle se fetch ho raha tha) ──
    check("PubMed pubtype se RCT pehchana jaata hai",
          qs.methodology_from_pubtypes(
              ["Journal Article", "Randomized Controlled Trial"]) == "rct",
          qs.methodology_from_pubtypes(["Journal Article",
                                        "Randomized Controlled Trial"]))
    check("meta-analysis pubtype narrative review se upar jeetta hai",
          qs.methodology_from_pubtypes(["Review", "Meta-Analysis"]) == "meta_analysis",
          qs.methodology_from_pubtypes(["Review", "Meta-Analysis"]))
    check("editorial pubtype 'opinion' banta hai (research nahi)",
          qs.methodology_from_pubtypes(["Editorial"]) == "opinion",
          qs.methodology_from_pubtypes(["Editorial"]))
    check("khaali pubtype par methodology '' rehti hai (andaza nahi)",
          qs.methodology_from_pubtypes([]) == "" and qs.methodology_from_pubtypes(None) == "",
          "andaza laga liya")
    # Semantic Scholar camelCase deta hai — pehle ye chup-chaap "" ban jaata tha
    check("Semantic Scholar ka camelCase 'MetaAnalysis' bhi map hota hai",
          qs.methodology_from_pubtypes(["metaanalysis"]) == "meta_analysis",
          qs.methodology_from_pubtypes(["metaanalysis"]))
    check("Crossref 'editorial' type opinion banta hai, 'journal-article' kuch nahi",
          qs.methodology_from_work_type("editorial") == "opinion"
          and qs.methodology_from_work_type("journal-article") == "",
          f"{qs.methodology_from_work_type('editorial')} / "
          f"{qs.methodology_from_work_type('journal-article')}")

    # ── methodology: text se, par sirf explicit design shabdon par ──
    check("title mein 'systematic review and meta-analysis' -> meta_analysis",
          qs.methodology_from_text(
              "Statin therapy: a systematic review and meta-analysis") == "meta_analysis",
          qs.methodology_from_text("Statin therapy: a systematic review and meta-analysis"))
    check("'double-blind placebo-controlled' -> rct",
          qs.methodology_from_text("A double-blind, placebo-controlled study of X") == "rct",
          qs.methodology_from_text("A double-blind, placebo-controlled study of X"))
    check("'prospective cohort' -> cohort",
          qs.methodology_from_text("Diet and stroke: a prospective cohort study") == "cohort",
          qs.methodology_from_text("Diet and stroke: a prospective cohort study"))
    # word-boundary bug ka pin: substring match "phase inversion" ko trial bana deta
    check("'phase inversion' ko clinical trial nahi samajhta (word boundary)",
          qs.methodology_from_text("Phase inversion in polymer membranes") == "",
          qs.methodology_from_text("Phase inversion in polymer membranes"))
    check("aam webpage par methodology khaali rehti hai (thappa nahi lagata)",
          qs.methodology_from_text("10 best foods for winter — blog post") == "",
          qs.methodology_from_text("10 best foods for winter — blog post"))
    check("rank: meta-analysis > rct > cohort > opinion, unknown = -1",
          qs.methodology_rank("meta_analysis") > qs.methodology_rank("rct")
          > qs.methodology_rank("cohort") > qs.methodology_rank("opinion")
          and qs.methodology_rank("") == -1,
          "rank order galat")

    # ── retraction (Spec 7 signal #9) ──
    check("PubMed 'Retracted Publication' pubtype se retracted=True",
          qs.retraction_from_pubtypes(["Journal Article", "Retracted Publication"]) is True,
          str(qs.retraction_from_pubtypes(["Retracted Publication"])))
    check("retraction signal na mile to None (yaani 'pata nahi', False nahi)",
          qs.retraction_from_pubtypes(["Journal Article"]) is None,
          "False bol diya — ye 'clean hai' ka jhootha dava hota")
    check("title 'RETRACTED: ...' se retraction pakda jaata hai",
          qs.retraction_from_text("RETRACTED: Vaccines and autism") is True,
          str(qs.retraction_from_text("RETRACTED: Vaccines and autism")))
    check("retraction ke BAARE MEIN likha paper retracted nahi mana jaata",
          qs.retraction_from_text(
              "Trends in the retraction of cancer research papers") is None,
          "beech ka 'retraction' shabd galat flag laga raha hai")
    check("Crossref update-to/updated-by se retraction pakadta hai",
          qs.retraction_from_crossref(
              {"type": "journal-article",
               "updated-by": [{"type": "retraction"}]}) is True
          and qs.retraction_from_crossref({"type": "journal-article"}) is None,
          "crossref retraction detection fail")

    # ── replication (Spec 7 signal #8) — dava kamzor, isliye label bhi kamzor ──
    check("meta-analysis khud evidence synthesis hai",
          qs.replication_status("meta_analysis", "") == "evidence_synthesis",
          qs.replication_status("meta_analysis", ""))
    check("'failed to replicate' bhi replication SIGNAL hai (result nahi)",
          qs.replication_status("", "We failed to replicate the original finding")
          == "replication_signal",
          qs.replication_status("", "We failed to replicate the original finding"))
    check("replication label 'guarantee nahi' saaf likhta hai",
          "guarantee nahi" in qs.replication_label("replication_signal"),
          qs.replication_label("replication_signal"))

    # ── COI/funding (Spec 7 signal #10) — sirf full text par ──
    long_text = ("Introduction. " * 200 +
                 "Conflicts of interest: the authors declare none. "
                 "Funding: supported by a grant from ICMR.")
    check("full text mein COI statement mile to True",
          qs.coi_from_full_text(long_text) is True, "COI detect nahi hua")
    check("full text mein funding statement mile to True",
          qs.funding_from_full_text(long_text) is True, "funding detect nahi hua")
    check("full text bina COI statement -> False (padha, par nahi mila)",
          qs.coi_from_full_text("Introduction. " * 200) is False,
          "False ke bajaye kuch aur aaya")
    check("abstract-size text par COI ka jawab None hai (pata nahi)",
          qs.coi_from_full_text("Conflicts of interest: none.") is None,
          "chhote text par bhi jawab de diya — ye misleading hota")

    # ── enrich_record: ek hi jagah se sab sources ko same treatment ──
    rec = SourceRecord(title="RETRACTED: A randomized controlled trial of X",
                       snippet="We report an independent validation as well.")
    qs.enrich_record(rec)
    check("enrich_record teeno signal ek saath bharta hai",
          rec.methodology == "rct" and rec.retracted is True
          and rec.replication == "replication_signal",
          f"{rec.methodology} / {rec.retracted} / {rec.replication}")
    already = SourceRecord(title="A cohort study of Y", methodology="rct")
    qs.enrich_record(already)
    check("connector ne jo methodology bhari, enrich use overwrite nahi karta",
          already.methodology == "rct", already.methodology)

    # ── ranking: retracted source neeche jaata hai ──
    engine = RelevanceEngine()
    clean = SourceRecord(title="Statin therapy and stroke: a randomized controlled trial",
                         url="https://pubmed.ncbi.nlm.nih.gov/1/",
                         snippet="A large randomized controlled trial with 4000 patients "
                                 "showed a clear reduction in events, p < 0.01.",
                         source_type=SourceType.PAPER, peer_reviewed=True, year=2023,
                         doi="10.1/clean")
    bad = SourceRecord(title="RETRACTED: Vitamin megadose reverses diabetes in adults",
                       url="https://pubmed.ncbi.nlm.nih.gov/2/",
                       snippet="A randomized controlled trial claimed complete reversal "
                               "of type 2 diabetes after eight weeks, p < 0.01.",
                       source_type=SourceType.PAPER, peer_reviewed=True, year=2023,
                       doi="10.2/bad")
    ranked = engine.rank([bad, clean], "randomized controlled trial diabetes statin",
                         max_sources=5)
    check("retracted source ranking mein clean source se NEECHE jaata hai",
          len(ranked) == 2 and ranked[0].doi == "10.1/clean"
          and ranked[1].quality_score < ranked[0].quality_score,
          f"{[(r.doi, r.quality_score) for r in ranked]}")
    check("rank() khud enrich karta hai (connector bhoole to bhi signal aata hai)",
          bad.retracted is True and clean.methodology == "rct",
          f"{bad.retracted} / {clean.methodology}")
    # Note: yahan tier-1 domain/DOI/peer-review ke bonus jaan-boojh kar nahi
    # diye. Warna dono score 1.0 par clamp ho jaate the aur ye assertion
    # methodology ka farak dekh hi nahi paati — test khud jhootha PASS deta.
    plain = dict(url="https://example.org/paper", source_type=SourceType.PAPER,
                 snippet="Ek chhota sa abstract jisme koi evidence shabd nahi hai.")
    check("strong methodology ko quality bonus milta hai, opinion ko saza",
          engine.score_quality(SourceRecord(title="A", methodology="rct", **plain))
          > engine.score_quality(SourceRecord(title="A", **plain))
          > engine.score_quality(SourceRecord(title="A", methodology="opinion", **plain)),
          f"{engine.score_quality(SourceRecord(title='A', methodology='rct', **plain))} / "
          f"{engine.score_quality(SourceRecord(title='A', **plain))} / "
          f"{engine.score_quality(SourceRecord(title='A', methodology='opinion', **plain))}")

    # ── dedup duplicate girata hai to uska retraction flag NAHI girta ──
    notice = SourceRecord(title="RETRACTED: Vitamin megadose reverses diabetes in adults",
                          url="https://crossref.example/2", connector="crossref",
                          retracted=True, methodology="rct")
    twin = SourceRecord(title="Vitamin megadose reverses diabetes in adults",
                        url="https://openalex.example/2", connector="openalex")
    survivors = DeduplicationEngine().deduplicate([twin, notice])
    check("dedup ek hi kaam ko ek hi source maanta hai",
          len(survivors) == 1, f"{len(survivors)} bache")
    check("duplicate girane par retraction flag survivor par bach jaata hai",
          survivors[0].retracted is True and survivors[0].methodology == "rct",
          f"{survivors[0].connector}: retracted={survivors[0].retracted}, "
          f"methodology={survivors[0].methodology!r}")
    filled = SourceRecord(title="Same work different words here", methodology="cohort",
                          url="https://a.example/1")
    other = SourceRecord(title="Same work different words here", methodology="rct",
                         url="https://b.example/1")
    kept = DeduplicationEngine().deduplicate([filled, other])
    check("merge bhari hui methodology ko overwrite nahi karta",
          len(kept) == 1 and kept[0].methodology == "cohort", str(kept[0].methodology))

    # ── prompt/citation label: Gemini ko retraction pehle dikhe ──
    check("citation_label retraction ki chetavani SABSE PEHLE likhta hai",
          bad.citation_label().startswith("RETRACTION se juda"),
          bad.citation_label()[:80])
    check("citation_label mein methodology bhi jaati hai",
          "randomized controlled trial" in clean.citation_label(),
          clean.citation_label())

    # ── pack-level honest roll-up ──
    unknown = SourceRecord(title="Some news page", url="https://news.example/x",
                           snippet="short", source_type=SourceType.WEB)
    pack7 = EvidencePack(question="q", sources=[clean, bad, unknown])
    for index, source in enumerate(pack7.sources, 1):
        source.source_id = f"S{index}"
    counts = pack7.methodology_counts()
    check("methodology_counts unknown ko chhupata nahi",
          counts.get("unknown") == 1 and counts.get("rct") == 2,
          str(counts))
    check("methodology_counts strong-se-weak order mein aata hai",
          list(counts.keys())[0] == "rct", str(list(counts.keys())))
    note = pack7.quality_signal_note()
    check("quality note retraction ki CHETAVANI deta hai",
          "CHETAVANI" in note and "retraction" in note.lower(), note[:120])
    check("quality note batata hai kitne sources ka design pata NAHI chala",
          "1/3 sources ka study design metadata se pata nahi chala" in note, note[:200])
    check("quality note COI ki asli limit likhta hai (abstract mein hoti hi nahi)",
          "abstract mein nahi" in note, note[-160:])
    report7 = pack7.coverage_report()
    check("coverage report mein naye Spec-7 counts hain",
          report7["retracted_sources"] == 1
          and report7["strong_methodology_sources"] == 2
          and report7["coi_checked_sources"] == 0,
          f"{report7['retracted_sources']} / "
          f"{report7['strong_methodology_sources']} / "
          f"{report7['coi_checked_sources']}")
    check("source ka to_dict() methodology label + signals dono deta hai",
          clean.to_dict()["methodology_label"] == "randomized controlled trial"
          and "randomized controlled trial" in clean.to_dict()["quality_signals"],
          str(clean.to_dict().get("quality_signals")))

    # ── connector wiring (bina network) ──
    check("Crossref ab retraction fields bhi select karta hai",
          "update-to" in CrossrefConnector._SELECT_FIELDS
          and "updated-by" in CrossrefConnector._SELECT_FIELDS
          and "update-to" in CrossrefConnector._SELECT,
          CrossrefConnector._SELECT)
    check("PubMed connector pubtype se methodology nikalta hai (source check)",
          "methodology_from_pubtypes" in inspect.getsource(PubMedConnector.search),
          "pubtype se methodology wiring nahi mili")

    # ── ContentFetcher: full text ke signals ──
    signals = ContentFetcher.signals_from_text(long_text)
    check("ContentFetcher full text se COI + funding dono nikalta hai",
          signals["coi_disclosed"] is True and signals["funding_disclosed"] is True,
          str(signals))
    review_text = ("This review summarises the evidence. " * 60 +
                   "We searched for randomized controlled trials. " * 60)
    check("review ke discussion mein RCT likha ho to use RCT nahi bana deta",
          ContentFetcher.signals_from_text(review_text)["methodology"]
          != "rct",
          str(ContentFetcher.signals_from_text(review_text)["methodology"]))
    check("full-text signals record par lagte hain (enrich wiring)",
          'source.coi_disclosed = signals["coi_disclosed"]'
          in inspect.getsource(ContentFetcher.enrich),
          "COI wiring enrich() mein nahi mili")

    # ── final report line ──
    # NOTE (2026-08-20): ye line pehle machine-style thi ("strong design",
    # "RETRACTION signal: 1"). §11 ke baad audit insaan ke padhne layak Hinglish
    # mein likhti hai, aur signature (coverage, pack) ho gayi hai. Counts wahi
    # aate hain — sirf is test ki expectation naye format par laayi gayi hai,
    # koi feature nahi hataya gaya.
    # NOTE (2026-08-21, §14 denominators): counts wahi hain, par ab har ginti
    # apne denominator ke saath chhapti hai ("2/3 source ka study design mazboot
    # hai"). Bina denominator ke "2 source peer-reviewed hai" zyada mazboot lagta
    # tha jitna tha. Expectation naye format par laayi gayi hai — koi feature
    # hataya nahi gaya.
    quality_line = FinalSynthesizer._quality_line(report7, pack7)
    check("coverage section quality line asli counts se banti hai",
          "2/3 source ka study design mazboot hai" in quality_line
          and "1/3 source par retraction ka signal hai" in quality_line
          and "1/3 sources ka study design metadata se pata nahi chala"
          in quality_line,
          quality_line)
    check("orchestrator retracted source par top-level warning deta hai",
          "retraction/withdrawal ka signal hai"
          in inspect.getsource(orch_module.DeepResearchEngine),
          "retraction warning wiring nahi mili")


def test_dataset_connectors():
    section("19. Dataset connectors (Spec §2 + §11) — offline, bina network")
    from research_engine.connectors.dataset_connector import (
        DataGovConnector, DataGovInConnector, DatasetConnector,
        HuggingFaceDatasetsConnector, WHOGhoConnector, WorldBankConnector,
        ZenodoConnector, _as_list, _strip_html)
    from research_engine.connectors.base import ConnectorSkipped
    from research_engine.source_discovery import SourceDiscovery

    # ── helpers: HTML strip + list-normalize ──────────────────────────────────
    stripped = _strip_html("<p>hello <b>world</b> &amp; more</p>")
    check("_strip_html tags hata deta hai (koi < ya > nahi bachta)",
          "<" not in stripped and ">" not in stripped and "hello" in stripped,
          stripped)
    check("_as_list None ko khaali list banata hai", _as_list(None) == [], "")
    check("_as_list single object ko list mein wrap karta hai",
          _as_list("x") == ["x"], str(_as_list("x")))
    check("_as_list pehle se list ko waisa hi rakhta hai",
          _as_list([1, 2]) == [1, 2], str(_as_list([1, 2])))

    # ── Zenodo: hits.hits[] → SourceRecord ────────────────────────────────────
    ZENODO = {"hits": {"hits": [
        {"id": 12345,
         "links": {"self_html": "https://zenodo.org/records/12345"},
         "metadata": {
             "title": "Global Temperature Anomaly Dataset 1880-2023",
             "description": "<p>Monthly <b>gridded</b> temperature anomalies.</p>",
             "creators": [{"name": "Smith, J."}, {"name": "Lee, K."}],
             "publication_date": "2023-05-01",
             "doi": "10.5281/zenodo.12345"}},
        # links nahi, sirf doi → url doi.org par fallback kare
        {"id": 999, "metadata": {"title": "DOI-only record",
                                 "doi": "10.9999/xyz"}},
    ]}}
    zrecs = ZenodoConnector().parse(ZENODO)
    check("Zenodo do records parse karta hai", len(zrecs) == 2, str(len(zrecs)))
    z0 = zrecs[0]
    check("Zenodo title map hota hai",
          z0.title == "Global Temperature Anomaly Dataset 1880-2023", z0.title)
    check("Zenodo description ka HTML snippet mein strip hota hai",
          "<" not in z0.snippet and "gridded" in z0.snippet, z0.snippet)
    check("Zenodo creators authors ban jaate hain",
          z0.authors == ["Smith, J.", "Lee, K."], str(z0.authors))
    check("Zenodo publication_date se year nikalta hai", z0.year == 2023, str(z0.year))
    check("Zenodo doi map hota hai", z0.doi == "10.5281/zenodo.12345", z0.doi)
    check("Zenodo url self_html se aata hai",
          z0.url == "https://zenodo.org/records/12345", z0.url)
    check("Zenodo dataset = primary data (is_primary True)", z0.is_primary is True,
          str(z0.is_primary))
    check("Zenodo links na hon to doi.org par url fallback",
          zrecs[1].url == "https://doi.org/10.9999/xyz", zrecs[1].url)

    # ── data.gov (US CKAN): result.results[] ──────────────────────────────────
    DATAGOV = {"result": {"results": [
        {"name": "us-co2-emissions",
         "title": "U.S. CO2 Emissions by State",
         "notes": "Annual carbon dioxide emissions by U.S. state.",
         "organization": {"title": "Environmental Protection Agency"},
         "metadata_created": "2015-03-12T00:00:00.000Z"},
    ]}}
    drecs = DataGovConnector().parse(DATAGOV)
    check("data.gov ek record parse karta hai", len(drecs) == 1, str(len(drecs)))
    check("data.gov url slug (name) se banta hai",
          drecs[0].url == "https://catalog.data.gov/dataset/us-co2-emissions",
          drecs[0].url)
    check("data.gov snippet notes se aata hai",
          drecs[0].snippet.startswith("Annual carbon dioxide"), drecs[0].snippet)
    check("data.gov publisher organization.title se aata hai",
          drecs[0].publisher == "Environmental Protection Agency", drecs[0].publisher)
    check("data.gov metadata_created se year nikalta hai",
          drecs[0].year == 2015, str(drecs[0].year))

    # ── WHO GHO: value[] indicators ───────────────────────────────────────────
    WHO = {"value": [
        {"IndicatorCode": "WHOSIS_000001",
         "IndicatorName": "Life expectancy at birth (years)"},
        {"IndicatorCode": "", "IndicatorName": ""},          # dono khaali → skip
    ]}
    wrecs = WHOGhoConnector().parse(WHO)
    check("WHO GHO khaali indicator ko skip karta hai (sirf 1 bachta hai)",
          len(wrecs) == 1, str(len(wrecs)))
    check("WHO GHO title IndicatorName se aata hai",
          wrecs[0].title == "Life expectancy at birth (years)", wrecs[0].title)
    check("WHO GHO url asli resolvable data endpoint deta hai",
          wrecs[0].url == "https://ghoapi.azureedge.net/api/WHOSIS_000001", wrecs[0].url)
    check("WHO GHO publisher WHO hai",
          wrecs[0].publisher == "World Health Organization (GHO)", wrecs[0].publisher)

    # ── World Bank: defensive parser (nested identification.title) ────────────
    check("World Bank _first dotted key nested se padhta hai",
          WorldBankConnector._first({"a": {"b": "x"}}, "a.b") == "x", "")
    check("World Bank _first missing key par khaali deta hai",
          WorldBankConnector._first({"a": {}}, "a.b", "c") == "", "")
    WB = {"data": [
        {"identification": {"title": "GDP per capita (current US$)",
                            "description": "World Development Indicators series."},
         "id": "WB-GDP-PC", "last_updated_date": "2024-07-01"},
    ]}
    wbrecs = WorldBankConnector().parse(WB)
    check("World Bank title nested identification.title se aata hai",
          wbrecs and wbrecs[0].title == "GDP per capita (current US$)",
          str(wbrecs))
    check("World Bank snippet nested identification.description se",
          wbrecs[0].snippet.startswith("World Development Indicators"),
          wbrecs[0].snippet)
    check("World Bank url na ho to id se fallback banta hai",
          wbrecs[0].url == "https://datacatalog.worldbank.org/search/dataset/WB-GDP-PC",
          wbrecs[0].url)
    check("World Bank year last_updated_date se nikalta hai",
          wbrecs[0].year == 2024, str(wbrecs[0].year))
    # dict-wrapped rows ({"value": {"dataset":[...]}}) bhi handle ho
    WB2 = {"value": {"dataset": [{"title": "Wrapped Dataset"}]}}
    check("World Bank dict-wrapped 'dataset' array bhi parse hota hai",
          len(WorldBankConnector().parse(WB2)) == 1, "")
    check("World Bank title na ho to record banata hi nahi (jhooth nahi)",
          WorldBankConnector().parse({"data": [{"foo": 1}]}) == [], "")
    check("World Bank khaali payload par crash nahi (khaali list)",
          WorldBankConnector().parse({}) == [], "")

    # ── Hugging Face: JSON ARRAY ──────────────────────────────────────────────
    HF = [
        {"id": "imdb", "description": "Large Movie Review Dataset.",
         "author": "stanfordnlp", "lastModified": "2022-01-01T00:00:00.000Z"},
        {"id": "no-desc", "tags": ["task:classification", "size:1K"]},
    ]
    hrecs = HuggingFaceDatasetsConnector().parse(HF)
    check("HuggingFace JSON array ke dono records parse karta hai",
          len(hrecs) == 2, str(len(hrecs)))
    check("HuggingFace title repo id hai",
          hrecs[0].title == "imdb", hrecs[0].title)
    check("HuggingFace url datasets/<id> par banta hai",
          hrecs[0].url == "https://huggingface.co/datasets/imdb", hrecs[0].url)
    check("HuggingFace description na ho to tags se snippet banta hai",
          "task:classification" in hrecs[1].snippet, hrecs[1].snippet)
    check("HuggingFace is_primary None hai (primary/derived mix — jhooth nahi)",
          hrecs[0].is_primary is None, str(hrecs[0].is_primary))

    # ── data.gov.in: parse + honest skip (KEY nahi to search chali hi nahi) ────
    DGI = {"records": [
        {"title": "Rainfall in India 1901-2015", "desc": "Monthly rainfall data.",
         "source": "https://data.gov.in/resource/xyz"},
    ]}
    girecs = DataGovInConnector().parse(DGI)
    check("data.gov.in records[] parse karta hai",
          girecs and girecs[0].title == "Rainfall in India 1901-2015", str(girecs))
    check("data.gov.in snippet desc se, publisher India govt",
          girecs[0].snippet.startswith("Monthly rainfall")
          and "Government of India" in girecs[0].publisher, girecs[0].publisher)

    saved_key = os.environ.pop("DATA_GOV_IN_API_KEY", None)
    try:
        raised = False
        try:
            DataGovInConnector().search("rainfall")
        except ConnectorSkipped:
            raised = True
        check("data.gov.in bina key ConnectorSkipped raise karta hai (0-result nahi)",
              raised, "ConnectorSkipped nahi aaya")
        safe = DataGovInConnector().safe_search("rainfall")
        check("data.gov.in safe_search reason 'no_key' deta hai (honest ruka)",
              safe["reason"] == "no_key" and safe["count"] == 0, str(safe))

        # ── facade: by_name + only= (bina network, kyunki key nahi) ────────────
        facade = DatasetConnector()
        check("facade mein 6 dataset connectors hain",
              len(facade.connectors) == 6, str(len(facade.connectors)))
        check("facade by_name sahi connector deta hai",
              isinstance(facade.by_name("zenodo"), ZenodoConnector), "")
        check("facade by_name anjaan naam par None deta hai",
              facade.by_name("nope") is None, "")
        names = {c.name for c in facade.connectors}
        check("facade ke connector naam poore set hain",
              names == {"zenodo", "data_gov", "who_gho", "world_bank",
                        "huggingface", "data_gov_in"}, str(names))
        only = facade.search("rainfall", only=["data_gov_in"])
        check("facade {'records','log'} shape deta hai",
              set(only.keys()) == {"records", "log"}, str(only.keys()))
        check("facade only= filter respect karta hai (sirf ek log entry)",
              len(only["log"]) == 1 and only["log"][0]["reason"] == "no_key",
              str(only["log"]))
    finally:
        if saved_key is not None:
            os.environ["DATA_GOV_IN_API_KEY"] = saved_key

    # ── honesty invariants: har parsed dataset record par ─────────────────────
    all_records = zrecs + drecs + wrecs + wbrecs + hrecs + girecs
    check("har dataset record ka source_type DATASET hai",
          all(r.source_type == SourceType.DATASET for r in all_records),
          "koi record DATASET nahi tha")
    check("koi dataset record peer_reviewed=True nahi banata (None hi imaandaar)",
          all(r.peer_reviewed is None for r in all_records),
          "kisi record par peer_reviewed set tha")
    check("koi dataset record par jhoothi methodology stamp nahi hoti",
          all(r.methodology == "" for r in all_records),
          "kisi record par methodology thi")

    # ── planner: 'datasets' plan (Spec §2 + §11) ──────────────────────────────
    planner = ResearchPlanner()
    quick = get_depth_config("QUICK")
    deep = get_depth_config("DEEP")
    maximum = get_depth_config("MAXIMUM")

    med = planner.classify("kya green tea cancer se bachati hai?")
    tech = planner.classify("best machine learning model training data kaunsa hai")
    fin = planner.classify("India GDP inflation aur stock market trend")

    plan_quick = planner.connector_plan(med, quick)
    check("connector_plan hamesha 'datasets' key deta hai",
          "datasets" in plan_quick and isinstance(plan_quick["datasets"], list),
          str(plan_quick.get("datasets")))
    check("QUICK mode (use_datasets False) par datasets khaali",
          plan_quick["datasets"] == [], str(plan_quick["datasets"]))

    plan_med = planner.connector_plan(med, deep)
    check("DEEP + medical par zenodo+data_gov base rehte hain",
          {"zenodo", "data_gov"} <= set(plan_med["datasets"]),
          str(plan_med["datasets"]))
    check("DEEP + medical par who_gho aata hai",
          "who_gho" in plan_med["datasets"], str(plan_med["datasets"]))
    check("DEEP + medical par world_bank aata hai (medical bhi WB set mein)",
          "world_bank" in plan_med["datasets"], str(plan_med["datasets"]))
    check("DEEP mode data_gov_in NAHI daalta (key optional — sirf MAXIMUM)",
          "data_gov_in" not in plan_med["datasets"], str(plan_med["datasets"]))

    plan_tech = planner.connector_plan(tech, deep)
    check("DEEP + technical par huggingface aata hai",
          "huggingface" in plan_tech["datasets"], str(plan_tech["datasets"]))
    check("technical (non-medical) par who_gho nahi aata",
          "who_gho" not in plan_tech["datasets"], str(plan_tech["datasets"]))

    plan_fin = planner.connector_plan(fin, deep)
    check("DEEP + financial par world_bank aata hai",
          "world_bank" in plan_fin["datasets"], str(plan_fin["datasets"]))

    plan_max = planner.connector_plan(med, maximum)
    check("MAXIMUM par data_gov_in bhi plan mein aata hai (tab key relevant)",
          "data_gov_in" in plan_max["datasets"], str(plan_max["datasets"]))
    check("MAXIMUM par huggingface+world_bank hamesha",
          {"huggingface", "world_bank"} <= set(plan_max["datasets"]),
          str(plan_max["datasets"]))
    check("datasets list mein duplicate nahi (sorted set)",
          len(plan_max["datasets"]) == len(set(plan_max["datasets"])),
          str(plan_max["datasets"]))

    # ── depth: use_datasets flag + CUSTOM + BOOL_FIELDS ───────────────────────
    from research_engine.depth import BOOL_FIELDS
    check("use_datasets BOOL_FIELDS mein hai (CUSTOM se aa sake)",
          "use_datasets" in BOOL_FIELDS, str(BOOL_FIELDS))
    check("QUICK use_datasets False", quick.use_datasets is False, "")
    check("DEEP use_datasets True", deep.use_datasets is True, "")
    check("MAXIMUM use_datasets True", maximum.use_datasets is True, "")
    custom_off = get_depth_config("CUSTOM", {"use_datasets": False})
    check("CUSTOM use_datasets=False override chalta hai",
          custom_off.use_datasets is False, str(custom_off.use_datasets))
    custom_default = get_depth_config("CUSTOM", {})
    check("CUSTOM bina flag ke DEEP se use_datasets True inherit karta hai",
          custom_default.use_datasets is True, str(custom_default.use_datasets))

    # ── SourceDiscovery wiring: datasets tier task banta hai (bina network) ────
    disc = SourceDiscovery()
    check("SourceDiscovery.datasets ek DatasetConnector hai",
          isinstance(disc.datasets, DatasetConnector), "")
    tasks = disc._tasks(["climate data"],
                        {"web": False, "papers": [], "books": [],
                         "datasets": ["zenodo"]}, 3, 5)
    labels = [label for label, _ in tasks]
    check("_tasks datasets plan se 'zenodo' task banata hai",
          labels == ["zenodo"], str(labels))
    check("_tasks anjaan dataset naam par task nahi banata (by_name None)",
          disc._tasks(["x"], {"web": False, "papers": [], "books": [],
                              "datasets": ["nope"]}, 3, 5) == [], "")


def test_speech_to_text():
    section("20. Local speech-to-text (Spec §5) — offline, bina Whisper/network")
    from research_engine.processing import (SpeechToTextProcessor,
                                            TranscriptProcessor)
    from research_engine.processing.speech_to_text import (
        DISCLAIMER, INSTALL_HINT, SpeechToTextProcessor as STTClass,
        _cues_from_segments)

    stt = SpeechToTextProcessor()

    # ── availability: kabhi exception nahi, hamesha 3 keys ────────────────────
    avail = stt.available()
    check("available() ok/backend/reason teeno keys deta hai (crash nahi)",
          {"ok", "backend", "reason"} <= set(avail.keys()), str(avail.keys()))
    # sandbox mein koi Whisper backend nahi — honest 'unavailable' + install hint
    if not avail["ok"]:
        check("backend na ho to available() honest install hint deta hai",
              "faster-whisper" in avail["reason"], avail["reason"][:80])
    # INSTALL_HINT deterministic hai (environment se azaad) — dono backend bataye
    check("INSTALL_HINT dono free backends (faster-whisper + openai-whisper) likhta hai",
          "faster-whisper" in INSTALL_HINT and "openai-whisper" in INSTALL_HINT,
          INSTALL_HINT[:60])
    check("INSTALL_HINT saaf karta hai ki koi API key nahi (FREE + offline)",
          "API key nahi" in INSTALL_HINT, INSTALL_HINT[:120])

    # ── _cues_from_segments: pure helper (yahi STT ko citation se jodta hai) ───
    dict_segs = [{"start": 0, "text": "Namaste, aaj hum baat karenge."},
                 {"start": 5.9, "text": "  climate change ke baare mein.  "},
                 {"start": 12, "text": "   "}]                # khaali → skip
    cues = _cues_from_segments(dict_segs)
    check("dict segments cue-shape mein badalte hain (khaali text skip)",
          len(cues) == 2 and cues[0]["start"] == 0, str(cues))
    check("float start int seconds mein truncate hota hai (5.9 → 5)",
          cues[1]["start"] == 5 and cues[1]["text"] == "climate change ke baare mein.",
          str(cues[1]))

    class _Seg:                                    # faster-whisper Segment jaisa
        def __init__(self, start, text):
            self.start, self.text = start, text
    obj_cues = _cues_from_segments([_Seg(3, "object segment"), _Seg(9, "")])
    check("object segments (.start/.text) bhi handle hote hain",
          obj_cues == [{"start": 3, "text": "object segment"}], str(obj_cues))
    check("kharab start value crash nahi karta, 0 par gir jaata hai",
          _cues_from_segments([{"start": "abc", "text": "x"}])[0]["start"] == 0, "")
    check("negative start 0 par clamp hota hai",
          _cues_from_segments([{"start": -4, "text": "x"}])[0]["start"] == 0, "")
    check("None segments par khaali list (crash nahi)",
          _cues_from_segments(None) == [], "")

    # ── STT cues → TranscriptProcessor.chunk = citation-ready ─────────────────
    # Ye asli integration hai: model ke bina bhi, cue→chunk path proves ki
    # transcription citation timestamp ("0:00") ke saath aayegi.
    long_cues = [{"start": s, "text": f"line at {s}s"} for s in range(0, 300, 30)]
    chunks = TranscriptProcessor().chunk(long_cues, "podcast.mp3 (auto-transcribed)")
    check("STT cues timestamped chunks ban jaate hain",
          len(chunks) >= 2, str(len(chunks)))
    check("chunk header mein '(auto-transcribed)' rehta hai (citation imaandaar)",
          "(auto-transcribed)" in chunks[0]["header"], chunks[0]["header"])
    check("chunk locator timestamp format mein hai (0:00 se shuru)",
          chunks[0]["header"].endswith("0:00]"), chunks[0]["header"])

    # ── unavailable branch: transcribe/process_file honestly rukte hain ───────
    if not avail["ok"]:
        tr = stt.transcribe("/nonexistent/audio.mp3")
        check("backend na ho to transcribe ok=False + install-hint deta hai",
              tr["ok"] is False and "faster-whisper" in tr["error"], tr["error"][:60])
        check("transcribe fail par bhi disclaimer saath aata hai",
              tr["disclaimer"] == DISCLAIMER and tr["cues"] == [], "")
        pf = stt.process_file("/nonexistent/audio.mp3")
        check("process_file unavailable par ok=False, chunks khaali, source basename",
              pf["ok"] is False and pf["chunks"] == []
              and pf["source"] == "audio.mp3", str(pf.get("source")))

    # ── honesty: disclaimer 'best guess', verbatim NAHI ───────────────────────
    check("DISCLAIMER transcript ko 'best guess' batata hai, verbatim sach nahi",
          "best guess" in DISCLAIMER and "verbatim sach nahi" in DISCLAIMER,
          DISCLAIMER[:80])
    check("note() unavailable par saaf 'nahi chali' bolta hai",
          "nahi chali" in stt.note({"ok": False, "error": "x"}), "")

    # ── model size priority: WHISPER_MODEL env > default 'base' ───────────────
    check("default model size 'base' hai (laptop-friendly)",
          STTClass().model_size == "base", STTClass().model_size)
    saved_model = os.environ.pop("WHISPER_MODEL", None)
    try:
        os.environ["WHISPER_MODEL"] = "small"
        check("WHISPER_MODEL env model size override karta hai",
              STTClass().model_size == "small", STTClass().model_size)
        check("constructor arg env se bhi upar (explicit jeet-ta hai)",
              STTClass(model_size="medium").model_size == "medium", "")
    finally:
        if saved_model is None:
            os.environ.pop("WHISPER_MODEL", None)
        else:
            os.environ["WHISPER_MODEL"] = saved_model

    # ── wiring: __init__ export + routes.py surface (fastapi import kiye bina) ─
    from research_engine import processing as proc_pkg
    check("SpeechToTextProcessor processing package se export hota hai",
          "SpeechToTextProcessor" in proc_pkg.__all__, str(proc_pkg.__all__))
    routes_src = (pathlib.Path(__file__).parent / "api" / "routes.py").read_text(
        encoding="utf-8")
    check("/transcribe-audio endpoint routes.py mein maujood hai",
          '"/transcribe-audio"' in routes_src, "endpoint missing")
    check("transcribe-audio SpeechToTextProcessor use karta hai",
          "SpeechToTextProcessor" in routes_src, "STT import missing")
    check("STT na ho to endpoint 501 (honest) deta hai, jhootha 200 nahi",
          "status_code=501" in routes_src, "501 honest-fail missing")
    check("/processing-capabilities ab STT ki asli availability report karta hai",
          "bool(stt.get(\"ok\"))" in routes_src, "capability abhi hardcoded False hai")
    check("AUDIO_SUPPORTED mein common audio format (.mp3) hai",
          ".mp3" in routes_src and "AUDIO_SUPPORTED" in routes_src, "audio formats missing")


def test_verification_dataset_stats():
    section("21. VerificationEngine dataset + statistics awareness (Spec 11)")
    verifier = VerificationEngine()

    # ── fixtures ── (stats DIKHTE hue, plain, dataset, retracted)
    stat_source = SourceRecord(
        title="RCT of drug X",
        snippet="In a randomized trial (n = 240 participants), the effect was "
                "significant (p < 0.001, 95% CI 1.2-3.4, odds ratio 2.1).",
        connector="pubmed", source_type=SourceType.PAPER, source_id="S1")
    plain_source = SourceRecord(
        title="Opinion piece on drug X",
        snippet="Many people feel drug X works well in daily life, no numbers here.",
        connector="blog", source_type=SourceType.WEB, source_id="S2")
    dataset_source = SourceRecord(
        title="WHO diabetes prevalence indicator",
        url="https://ghoapi.azureedge.net/api/NCD_DIABETES",
        snippet="Age-standardized diabetes prevalence by country and year.",
        connector="who_gho", source_type=SourceType.DATASET, source_id="S3")
    retracted_source = SourceRecord(
        title="Withdrawn study on drug X",
        snippet="This study reported a strong effect.",
        connector="crossref", source_type=SourceType.PAPER, source_id="S4",
        retracted=True)

    pack = EvidencePack(question="does drug X work?",
                        sources=[stat_source, plain_source, dataset_source,
                                 retracted_source])

    # ── 1. statistics-presence audit (detect only, never invent) ──
    stats = verifier.audit_statistics(pack)
    check("stats audit ne 4 sources check kiye", stats["sources_checked"] == 4,
          str(stats))
    check("stat-heavy source detect hua", stats["sources_with_statistics"] >= 1,
          str(stats))
    markers = stats["markers_found"]
    check("p-value detect hui", markers["p_value"] >= 1, str(markers))
    check("confidence interval detect hui", markers["confidence_interval"] >= 1,
          str(markers))
    check("sample size detect hui", markers["sample_size"] >= 1, str(markers))
    check("effect size detect hui", markers["effect_size"] >= 1, str(markers))
    check("plain (bina-number) source ke stats count nahi hue",
          not any(e["source_id"] == "S2" for e in stats["per_source"]),
          str(stats["per_source"]))
    check("stats note honesty: 'invent' nahi karta bolta hai",
          "invent" in stats["note"], stats["note"])
    check("stats note honesty: 'poora text' na padhne ka caveat hai",
          "poora text" in stats["note"], stats["note"])
    # never-invent guarantee: audit sirf presence/count deta hai, koi raw number nahi
    check("stats audit numbers store nahi karta (sirf markers/count/note)",
          set(stats.keys()) == {"sources_checked", "sources_with_statistics",
                                "markers_found", "per_source", "note"},
          str(sorted(stats.keys())))

    empty_stats = verifier.audit_statistics(EvidencePack(question="q", sources=[]))
    check("khaali pack par stats audit crash nahi karta",
          empty_stats["sources_checked"] == 0, str(empty_stats))
    check("khaali pack par honest note", "Koi source nahi" in empty_stats["note"],
          empty_stats["note"])

    nostat_pack = EvidencePack(question="q", sources=[plain_source])
    nostat = verifier.audit_statistics(nostat_pack)
    check("bina stats ke pack par extra-saavdhani note",
          "saavdhani" in nostat["note"], nostat["note"])

    # ── 2. datasets = available data for verification ──
    data_lines = verifier.data_for_verification(pack)
    check("dataset source available-data mein list hua",
          any("S3" in d for d in data_lines), str(data_lines))
    check("non-dataset source available-data mein NAHI aaya",
          not any(d.startswith("[S1]") for d in data_lines), str(data_lines))
    check("dataset line mein connector (who_gho) hai",
          any("who_gho" in d for d in data_lines), str(data_lines))
    check("dataset line mein url hai",
          any("ghoapi" in d for d in data_lines), str(data_lines))
    no_data = verifier.data_for_verification(nostat_pack)
    check("bina dataset ke available-data khaali", no_data == [], str(no_data))

    # ── 3. honest limits on simulation / backtesting ──
    sim_limits = verifier.simulation_limits(
        "We ran a Monte Carlo simulation and backtested the strategy.")
    check("simulation/backtest par honest limit aaya", len(sim_limits) >= 1,
          str(sim_limits))
    check("limit text: engine KHUD nahi chalata",
          any("KHUD nahi" in l for l in sim_limits), str(sim_limits))
    plain_limits = verifier.simulation_limits("The sky is blue and water is wet.")
    check("bina simulation ke koi jhootha limit nahi", plain_limits == [],
          str(plain_limits))

    # ── 4. retraction flag (cited vs not-cited vs no-ids) ──
    rep_cited = verifier.verify("Drug X ka strong effect hai [S4].", pack,
                                citation_ok=True, ungrounded_count=0,
                                cited_ids=["S4"])
    retraction_fail = [c for c in rep_cited.checks
                       if c.name == "cited sources retraction-free"
                       and c.passed is False]
    check("cited retracted source FAIL check banata hai",
          len(retraction_fail) == 1, str([c.to_dict() for c in rep_cited.checks]))
    check("cited retracted source warning deta hai",
          any("retracted" in w.lower() for w in rep_cited.warnings),
          str(rep_cited.warnings))

    rep_notcited = verifier.verify("Drug X pe aur research chahiye [S1].", pack,
                                   citation_ok=True, ungrounded_count=0,
                                   cited_ids=["S1"])
    retraction_pass = [c for c in rep_notcited.checks
                       if c.name == "cited sources retraction-free"
                       and c.passed is True]
    check("retracted-but-not-cited par PASS check",
          len(retraction_pass) == 1,
          str([c.to_dict() for c in rep_notcited.checks]))

    rep_noids = verifier.verify("Drug X.", pack, citation_ok=True,
                                ungrounded_count=0)
    check("cited_ids na diya to bhi retraction warning aata hai",
          any("retraction" in w.lower() for w in rep_noids.warnings),
          str(rep_noids.warnings))

    # ── 5. verify() report ka naya shape ──
    d = rep_cited.to_dict()
    check("report dict mein 'statistics' key hai", "statistics" in d,
          str(sorted(d.keys())))
    check("report dict mein 'data_for_verification' key hai",
          "data_for_verification" in d, str(sorted(d.keys())))
    check("report dict mein 'limits' key hai", "limits" in d, str(sorted(d.keys())))
    check("report note mein 'invent nahi' honesty line hai",
          "invent" in d["note"], d["note"])

    # ── 6. synthesizer naye blocks render karta hai ──
    sim_pack = EvidencePack(question="q", sources=[stat_source, dataset_source])
    rep_sim = verifier.verify(
        "Humne ek simulation chalaya. Result: n = 240, p < 0.001 [S1].",
        sim_pack, citation_ok=True, ungrounded_count=0, cited_ids=["S1"])
    # NOTE (2026-08-20): §16 restructure mein `_verification_section` ka naam
    # aur jagah badal gayi — verification ab "## Research quality / technical
    # audit" ke andar `_numbers_check` + `_audit_section` se render hoti hai.
    # Ye check pehle "Statistics in sources"/"available data"/"LIMIT:" dhoondta
    # tha; teeno cheezein AB BHI report mein jaati hain (statistics aur dataset
    # list ko is commit mein wapas jodna pada — restructure ke waqt render hona
    # band ho gaya tha), sirf wording insaan ke layak ho gayi hai.
    rendered = FinalSynthesizer()._numbers_check(rep_sim.to_dict())
    check("verification section stats line dikhata hai",
          "Statistics in sources" in rendered, rendered[:200])
    check("verification section available-data (dataset) dikhata hai",
          "available data" in rendered.lower(), rendered[:400])
    audit = FinalSynthesizer()._audit_section(sim_pack, rep_sim.to_dict(), {})
    check("verification section LIMIT line dikhata hai",
          "koi simulation, backtest ya numerical forecast KHUD nahi chalata"
          in audit, audit[-600:])


def test_live_round2_fixes():
    """
    Doosre LIVE run (2026-08-17) ne 5 asli bug nikale. Ye section unhe bina
    network ke pin karti hai, taaki dobara na aa sakein:

      crossref    HTTP 400  — humara hi #30 select-field regression
      pubmed      0/3 relevant — `sort=relevance` nahi bheja tha
      arxiv       Hinglish ladder ka result guard khud kha jaata tha
      data_gov    HTTP 404  — CKAN API path badal gaya
      who_gho     0 result  — OData contains() case-sensitive hai
      huggingface 0 result  — poori sentence search= mein bhej rahe the
    """
    section("22. Doosre live run ke 5 bug (ab bina network pin hue)")
    from research_engine.connectors import base as cbase
    from research_engine.connectors import dataset_connector as dsc
    from research_engine.connectors import paper_connector as pc

    QUERY = "algorithmic bias in healthcare risk prediction"
    HINGLISH = "diabetes ka permanent ilaj kya hai"

    class _R:
        def __init__(self, payload=None, content=b""):
            self._payload = payload if payload is not None else {}
            self.content = content
            self.status_code = 200
            self.headers = {}

        def json(self):
            return self._payload

    def fake_clock():
        """Sleep turant, par ghadi aage — throttle time.time() bhi padhta hai."""
        state = {"t": 5000.0, "slept": []}

        def _sleep(seconds):
            state["slept"].append(seconds)
            state["t"] += seconds

        state["module"] = types.SimpleNamespace(
            sleep=_sleep, time=lambda: state["t"], monotonic=lambda: state["t"])
        return state

    real_paper_get, real_paper_time = pc.http_get, pc.time
    real_dsc_get = dsc.http_get
    try:
        clock = fake_clock()
        pc.time = clock["module"]
        pc.ArxivConnector._last_request_at = 0.0
        pc.PubMedConnector._last_request_at = 0.0

        # ── A. ConnectorHTTPError ab status carry karta hai ────────────────────
        # Pehle sirf message tha, to Crossref ko `"400" in str(exc)` karna padta —
        # aur "HTTP 500 ... 400 rows" jaisa message bhi match kar jaata.
        err = cbase.ConnectorHTTPError("HTTP 400", status=400)
        check("ConnectorHTTPError par status attribute hai (string parsing nahi)",
              err.status == 400, str(getattr(err, "status", None)))
        check("purana message format nahi badla (log/test wahi padhein)",
              str(err) == "HTTP 400", str(err))
        check("status na diya jaaye to None rehta hai (jhootha 0 nahi)",
              cbase.ConnectorHTTPError("boom").status is None, "")

        # base.http_get ASAL mein status pass karta hai ya nahi — ye alag se pin
        # karna zaroori hai. Baaki saare connector test http_get ko UPAR se mock
        # karte hain, to base.py ka ye layer bina apne test ke reh gaya tha
        # (mutation test ne pakda: `status=status` hataane par kuch nahi toota).
        # Yahan asli http_get ko ek nakli `requests` ke saath chalate hain.
        real_requests = sys.modules.get("requests")
        try:
            fake_resp = types.SimpleNamespace(status_code=400, headers={})
            sys.modules["requests"] = types.SimpleNamespace(
                get=lambda *a, **k: fake_resp)
            raised = None
            try:
                cbase.http_get("https://example.test/x", retries=0)
            except cbase.ConnectorHTTPError as exc:
                raised = exc
            check("base.http_get 400 ko status ke saath raise karta hai (wiring)",
                  raised is not None and raised.status == 400,
                  str(getattr(raised, "status", "no exception")))
            # 429 -> RateLimited (status field nahi, par alag exception class)
            fake_resp.status_code = 429
            rl = None
            try:
                cbase.http_get("https://example.test/x", retries=0)
            except cbase.RateLimited as exc:
                rl = exc
            check("base.http_get 429 ko RateLimited banata hai (0 result nahi)",
                  rl is not None, str(rl))
        finally:
            if real_requests is not None:
                sys.modules["requests"] = real_requests
            else:
                sys.modules.pop("requests", None)

        # ── B. Crossref: select field-list 400 par khud ko theek karta hai ────
        CROSSREF_OK = {"message": {"items": [
            {"title": ["Algorithmic bias in healthcare risk prediction"],
             "author": [{"given": "A", "family": "B"}],
             "issued": {"date-parts": [[2021, 3, 1]]},
             "container-title": ["JAMA"], "DOI": "10.1/abc",
             "URL": "https://doi.org/10.1/abc", "type": "journal-article",
             "publisher": "AMA"},
            {"title": ["Retracted study on risk scores"],
             "issued": {"date-parts": [[2019]]}, "DOI": "10.1/xyz",
             "type": "journal-article",
             "updated-by": [{"type": "retraction"}]},
        ]}}
        pc.CrossrefConnector.reset_select()
        seen = []

        def crossref_400_on_select(url, params=None, **kw):
            seen.append(dict(params or {}))
            if "select" in (params or {}):
                raise cbase.ConnectorHTTPError("HTTP 400", status=400)
            return _R(payload=CROSSREF_OK)

        pc.http_get = crossref_400_on_select
        first = pc.CrossrefConnector().safe_search(QUERY, 3)
        check("Crossref 400 par khaali haath nahi lautta (select hata kar dobara)",
              first["count"] == 2 and not first["error"],
              f"{first['count']} / {first['error']}")
        check("pehli koshish select ke saath hoti hai (bandwidth bachti hai)",
              "select" in seen[0], str(list(seen[0].keys())))
        check("doosri koshish bina select jaati hai",
              len(seen) == 2 and "select" not in seen[1], str(len(seen)))
        check("select fallback chhupaya nahi jaata — note mein saaf likha hai",
              "select" in first["note"], first["note"])
        check("retraction note select-note ko nigal nahi jaata (dono rehte hain)",
              "select" in first["note"] and "retraction" in first["note"],
              first["note"])

        seen.clear()
        second = pc.CrossrefConnector().safe_search(QUERY, 3)
        check("400 ek baar dekh liya to poore process mein select dobara nahi jaata",
              len(seen) == 1 and "select" not in seen[0], str(seen))
        check("flag lagne ke baad bhi records poore aate hain",
              second["count"] == 2, str(second["count"]))

        pc.CrossrefConnector.reset_select()
        pc.http_get = lambda url, params=None, **kw: (_ for _ in ()).throw(
            cbase.ConnectorHTTPError("HTTP 500", status=500))
        broke = pc.CrossrefConnector().safe_search(QUERY, 3)
        check("500 ko select-bug samajh kar nigla nahi jaata (asli error dikhta hai)",
              "HTTP 500" in broke["error"], broke["error"])
        check("500 ke baad select disable NAHI hota (galat sabak nahi seekha)",
              pc.CrossrefConnector.select_supported() is True, "flag off ho gaya")

        # ── C. PubMed: asli live bug — sort=relevance ─────────────────────────
        term5 = pc.PubMedConnector.build_term(QUERY, 5)
        check("PubMed term AND se judta hai (ATM ka OR expansion band)",
              term5.count(" AND ") == 4, term5)
        check("PubMed ka har term quote mein jaata hai (phrase search)",
              term5.count('"') == 10, term5)
        check("terms na milne par bhi term banta hai (crash nahi)",
              pc.PubMedConnector.build_term("the and of") == '"the and of"',
              pc.PubMedConnector.build_term("the and of"))
        check("khaali query par khaali term (bekaar API call nahi jaati)",
              pc.PubMedConnector.build_term("   ") == "", "")

        PM_SUMMARY = {"result": {
            "1": {"title": "Algorithmic bias in clinical risk prediction models",
                  "pubdate": "2021 Mar", "fulljournalname": "JAMA",
                  "pubtype": ["Journal Article", "Randomized Controlled Trial"],
                  "authors": [{"name": "A B"}],
                  "articleids": [{"idtype": "doi", "value": "10.1/pm"}]},
            "2": {"title": "The nephrologist in the present and near future",
                  "pubdate": "2026", "fulljournalname": "Nefrologia",
                  "pubtype": ["Editorial"]},
        }}
        pm_params = []

        def pubmed_ok(url, params=None, **kw):
            pm_params.append(dict(params or {}))
            if "esearch" in url:
                return _R(payload={"esearchresult": {"idlist": ["1", "2"]}})
            return _R(payload=PM_SUMMARY)

        pc.http_get = pubmed_ok
        pc.PubMedConnector._last_request_at = 0.0
        pm = pc.PubMedConnector().safe_search(QUERY, 3)
        titles = [r.title for r in pm["records"]]
        check("PubMed ka asli live bug: ab relevance se sort maanga jaata hai",
              pm_params[0].get("sort") == "relevance", str(pm_params[0]))
        check("guard kuch girayega, isliye PubMed thode extra ids maangta hai",
              pm_params[0].get("retmax", 0) > 3, str(pm_params[0]))
        check("off-topic nephrology paper guard se girta hai",
              not any("nephrologist" in t.lower() for t in titles), str(titles))
        check("on-topic paper bacha rehta hai",
              len(titles) == 1 and "Algorithmic bias" in titles[0], str(titles))
        check("guard ne kya hataya wo note mein honestly likha hai",
              "relevance guard" in pm["note"], pm["note"])
        check("pubtype se methodology aata hai (rct)",
              pm["records"][0].methodology == "rct",
              str(pm["records"][0].methodology))

        # editorial guard se gir gaya, to uski ginti note mein NAHI honi chahiye —
        # warna note un records ke baare mein bolta jo hum de hi nahi rahe
        check("hataye gaye records ki ginti note mein nahi aati",
              "editorial/letter/preprint" not in pm["note"], pm["note"])

        # sab off-topic -> 'filtered', "0 result" NAHI
        pc.http_get = pubmed_ok
        pc.PubMedConnector._last_request_at = 0.0
        pm_filtered = pc.PubMedConnector().safe_search("quantum lattice cryptography", 3)
        check("sab result topic se door hon to PubMed ka reason 'filtered' hai",
              pm_filtered["count"] == 0 and pm_filtered["reason"] == "filtered",
              f"{pm_filtered['count']} / {pm_filtered['reason']}")
        check("'chhaanta' aur 'kuch nahi mila' ka farak note mein likha hai",
              "alag baat hai" in pm_filtered["note"], pm_filtered["note"])

        # ladder: strict AND par 0 ids -> kam terms se dobara
        pm_terms = []

        def pubmed_ladder(url, params=None, **kw):
            if "esearch" in url:
                pm_terms.append(params["term"])
                got = params["term"].count(" AND ") == 0
                return _R(payload={"esearchresult": {"idlist": ["7"] if got else []}})
            return _R(payload={"result": {"7": {
                "title": "Diabetes remission after dietary intervention",
                "pubdate": "2022", "fulljournalname": "Lancet",
                "pubtype": ["Clinical Trial"]}}})

        pc.http_get = pubmed_ladder
        pc.PubMedConnector._last_request_at = 0.0
        pm_lad = pc.PubMedConnector().safe_search(HINGLISH, 3)
        check("strict AND par 0 mile to PubMed kam terms se dobara try karta hai",
              len(pm_terms) >= 2
              and pm_terms[0].count(" AND ") > pm_terms[-1].count(" AND "),
              str(pm_terms))
        check("ladder ek hi term dobara nahi bhejta (bekaar API call nahi)",
              len(set(pm_terms)) == len(pm_terms), str(pm_terms))
        check("Hinglish ladder ka result guard khud nahi kha jaata (asli bug)",
              pm_lad["count"] == 1, f"{pm_lad['count']} / {pm_lad['note']}")
        check("dheeli query chalne ki baat note mein saaf likhi hai",
              "dheeli query" in pm_lad["note"], pm_lad["note"])
        check("NCBI ke 3 req/sec ka gap maana jaata hai",
              pc.PubMedConnector._MIN_GAP_SECONDS >= 0.33,
              str(pc.PubMedConnector._MIN_GAP_SECONDS))
        check("esearch + esummary dono throttle se guzarte hain",
              inspect.getsource(pc.PubMedConnector.search).count("_throttle()") == 2,
              str(inspect.getsource(pc.PubMedConnector.search).count("_throttle()")))

        # guard ka bar sirf tab dheela hota hai jab query dheeli hui thi
        off = [SourceRecord(title="Portfolio tail risk", url="u", snippet="",
                            connector="pubmed", source_type=SourceType.PAPER)]
        check("strict query par 1-term match wala record ab bhi girta hai",
              pc.PubMedConnector.relevance_guard(off, QUERY, used_terms=5) == [],
              "guard dheela pad gaya")
        check("1-term wali query chali ho to 1 match kaafi hai",
              len(pc.PubMedConnector.relevance_guard(off, QUERY, used_terms=1)) == 1,
              "ladder ka fayda mar gaya")
        check("used_terms na do to purana sakht bar hi lagta hai",
              pc.PubMedConnector.relevance_guard(off, QUERY) == [], "")

        # ── D. arXiv: wahi Hinglish bug (ladder ka result guard kha jaata tha) ─
        HIT = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
               b'<id>http://arxiv.org/abs/1</id>'
               b'<title>Diabetes remission via dietary intervention</title>'
               b'<summary>A trial of remission in type 2 diabetes.</summary>'
               b'<published>2022-01-01T00:00:00Z</published></entry></feed>')
        EMPTY = b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        pc.http_get = lambda url, params=None, **kw: _R(
            content=EMPTY if params["search_query"].count(" AND ") else HIT)
        clock = fake_clock()
        pc.time = clock["module"]
        pc.ArxivConnector._last_request_at = 0.0
        ax = pc.ArxivConnector().safe_search(HINGLISH, 3)
        check("arXiv: Hinglish par dheeli query ka result ab zinda rehta hai",
              ax["count"] == 1, f"{ax['count']} / {ax['note']}")
        check("arXiv relaxed hone ki baat chhupata nahi (quality signal)",
              "dheeli query" in ax["note"], ax["note"])
        check("arXiv ka strict-case guard waisa hi sakht hai",
              pc.ArxivConnector.relevance_guard(off, QUERY, used_terms=5) == [], "")

        # ── E. data.gov: 404 par endpoint ladder ──────────────────────────────
        CKAN = {"result": {"results": [
            {"title": "Diabetes Surveillance System", "name": "diabetes-surveillance",
             "notes": "<p>State level diabetes prevalence.</p>",
             "metadata_created": "2020-02-02",
             "organization": {"title": "CDC"}}]}}
        dsc.DataGovConnector.remember_path(None)
        dg_urls = []
        dg_headers = []

        def datagov_404_then_ok(url, params=None, headers=None, **kw):
            dg_urls.append(url)
            dg_headers.append(headers or {})
            if url == dsc.DataGovConnector._CANDIDATES[0]:
                raise cbase.ConnectorHTTPError("HTTP 404", status=404)
            return _R(payload=CKAN)

        dsc.http_get = datagov_404_then_ok
        dg = dsc.DataGovConnector().safe_search("diabetes prevalence", 3)
        check("data.gov 404 par agla candidate path try hota hai",
              dg["count"] == 1 and len(dg_urls) == 2, f"{dg['count']} / {dg_urls}")
        # Akamai WAF bot-UA ko 404 deta hai — isliye browser-jaisa User-Agent
        # bhejna hi asli fix hai (endpoint badalna nahi). Ye pin isliye taaki
        # koi header hata de to test pakad le (warna fix cosmetic reh jaata).
        check("data.gov browser-jaisa User-Agent bhejta hai (Akamai WAF 404 ka fix)",
              "Mozilla" in (dg_headers[0] or {}).get("User-Agent", ""),
              str(dg_headers[0]))
        check("data.gov Accept: application/json bhejta hai",
              (dg_headers[0] or {}).get("Accept") == "application/json",
              str(dg_headers[0]))
        check("path badalne ki baat note mein likhi jaati hai",
              "path" in dg["note"] and "data mila" in dg["note"], dg["note"])
        check("dataset ka publisher organization se aata hai",
              dg["records"][0].publisher == "CDC", dg["records"][0].publisher)
        dg_urls.clear()
        dsc.DataGovConnector().safe_search("aur kuch", 3)
        check("sahi path yaad rehta hai (har call par 404 dobara nahi khaya jaata)",
              dg_urls == [dsc.DataGovConnector._CANDIDATES[1]], str(dg_urls))

        dsc.DataGovConnector.remember_path(None)
        dsc.http_get = lambda url, params=None, **kw: (_ for _ in ()).throw(
            cbase.ConnectorHTTPError("HTTP 404", status=404))
        dead = dsc.DataGovConnector().safe_search("x", 3)
        check("saare path 404 dein to khaali list NAHI, honest error milta hai",
              dead["count"] == 0 and "path nahi mila" in dead["error"],
              dead["error"])
        check("error saaf kehta hai ki search chali hi nahi thi",
              "alag baat hai" in dead["error"], dead["error"])
        dsc.DataGovConnector.remember_path(None)
        five_calls = []

        def datagov_500(url, params=None, **kw):
            five_calls.append(url)
            raise cbase.ConnectorHTTPError("HTTP 500", status=500)

        dsc.http_get = datagov_500
        five = dsc.DataGovConnector().safe_search("x", 3)
        check("404 ke alawa error chhupaya nahi jaata (500 seedha bahar)",
              "HTTP 500" in five["error"], five["error"])
        # ZAROORI: 500 server error hai, path-not-found NAHI — is par poora
        # candidate ladder chalana (3 bekaar call) galat hai. Fail-fast hona chahiye.
        check("500 par sirf pehla endpoint try hota hai (baaki candidate nahi)",
              len(five_calls) == 1, f"{len(five_calls)} calls: {five_calls}")
        check("500 ko 'path nahi mila' nahi bataya jaata (wo alag baat hai)",
              "path nahi mila" not in five["error"], five["error"])
        dsc.DataGovConnector.remember_path(None)

        # ── F. WHO GHO: OData contains() case-sensitive tha ───────────────────
        GHO_ROWS = [
            {"IndicatorCode": "NCD_DIA", "IndicatorName": "Diabetes prevalence (%)"},
            {"IndicatorCode": "NCD_DIA2",
             "IndicatorName": "Diabetes-attributable deaths in men aged 30-70 years"},
            {"IndicatorCode": "MAL_1", "IndicatorName": "Malaria incidence"},
        ]
        dsc.WHOGhoConnector.set_index(None)
        gho_calls = []

        def gho_ok(url, params=None, **kw):
            gho_calls.append(dict(params or {}))
            return _R(payload={"value": GHO_ROWS})

        dsc.http_get = gho_ok
        gho = dsc.WHOGhoConnector().safe_search("diabetes prevalence in adults", 3)
        gho_titles = [r.title for r in gho["records"]]
        check("WHO GHO ka asli bug: lowercase query Title-case naam se match karti hai",
              gho["count"] == 2, f"{gho['count']} / {gho['note']}")
        check("zyada term match karne wala indicator pehle aata hai",
              gho_titles[0] == "Diabetes prevalence (%)", str(gho_titles))
        check("case-sensitive OData filter ab nahi bheja jaata",
              all("$filter" not in p for p in gho_calls), str(gho_calls))
        check("indicator ka url asli data endpoint hai (locator imaandaar)",
              gho["records"][0].url.endswith("/api/NCD_DIA"),
              gho["records"][0].url)
        check("kitne indicator scan hue, wo note mein likha hai",
              "indicator" in gho["note"] and "3" in gho["note"], gho["note"])
        gho_calls.clear()
        dsc.WHOGhoConnector().safe_search("malaria", 3)
        check("registry per-process cache hota hai (har query par download nahi)",
              gho_calls == [], str(gho_calls))
        nomatch = dsc.WHOGhoConnector().safe_search("quantum lattice cryptography", 3)
        check("kuch match na kare to note kehta hai ki poora registry scan hua",
              nomatch["count"] == 0 and "registry scan" in nomatch["note"],
              nomatch["note"])
        check("match() bina network testable hai (top result short naam wala)",
              [r["IndicatorCode"] for r in
               dsc.WHOGhoConnector.match(GHO_ROWS, "DIABETES", 2)][0] == "NCD_DIA",
              str(dsc.WHOGhoConnector.match(GHO_ROWS, "DIABETES", 2)))
        dsc.WHOGhoConnector.set_index(None)

        # ── G. HuggingFace: poori sentence search= mein jaa rahi thi ──────────
        hf_terms = []

        def hf_ladder(url, params=None, **kw):
            hf_terms.append(params["search"])
            hit = params["search"].count(" ") == 0
            return _R(payload=[{"id": "org/diabetes-notes", "tags": ["health"],
                                "lastModified": "2024-01-01"}] if hit else [])

        dsc.http_get = hf_ladder
        hf = dsc.HuggingFaceDatasetsConnector().safe_search(QUERY, 3)
        check("HF ko poori sentence kabhi nahi bheji jaati (asli bug)",
              all(t != QUERY for t in hf_terms), str(hf_terms))
        check("HF keyword ladder chalta hai (3 -> 2 -> 1 term)",
              [t.count(" ") + 1 for t in hf_terms] == [3, 2, 1], str(hf_terms))
        check("ladder se mila dataset lauta diya jaata hai",
              hf["count"] == 1 and hf["records"][0].title == "org/diabetes-notes",
              str(hf["count"]))
        check("HF ka is_primary None rehta hai (curated bhi ho sakta hai)",
              hf["records"][0].is_primary is None, str(hf["records"][0].is_primary))
        check("relax hone ki baat note mein likhi hai", "'algorithmic'" in hf["note"],
              hf["note"])
        dsc.http_get = lambda url, params=None, **kw: _R(payload=[])
        hf0 = dsc.HuggingFaceDatasetsConnector().safe_search(QUERY, 3)
        check("HF par kuch na mile to note wajah batata hai (naam par search)",
              hf0["count"] == 0 and "NAAM par" in hf0["note"], hf0["note"])

        # ── H. World Bank 429: fix nahi, honest disclosure ────────────────────
        check("World Bank live 429 ke baad rate_limited=True hai",
              dsc.WorldBankConnector.rate_limited is True, "flag jhootha hai")
        check("World Bank free hi rehta hai (key nahi chahiye)",
              dsc.WorldBankConnector.free is True, "")
    finally:
        pc.http_get, pc.time = real_paper_get, real_paper_time
        dsc.http_get = real_dsc_get
        pc.CrossrefConnector.reset_select()
        dsc.DataGovConnector.remember_path(None)
        dsc.WHOGhoConnector.set_index(None)
        pc.ArxivConnector._last_request_at = 0.0
        pc.PubMedConnector._last_request_at = 0.0


# ── runner ───────────────────────────────────────────────────────────────────
def main() -> int:
    print("INFINITY RESEARCH AI — offline engine test (0 Gemini calls)")
    try:
        test_planner()
        test_dedup_and_relevance()
        pack, answer_text = test_evidence_and_citations()
        contradictions, consensus = test_contradictions(pack)
        verification = test_verification(pack)
        hypotheses, critique = test_critic_and_hypothesis()
        test_processing()
        test_memory()
        test_synthesizer(pack, contradictions, consensus, verification, hypotheses,
                         critique)
        test_end_to_end()
        test_content_fetcher()
        test_progress_tracker()
        test_discovery_chain()
        test_package_surface()
        test_knowledge_graph()
        test_depth_modes()
        test_connector_contracts()
        test_quality_signals()
        test_dataset_connectors()
        test_speech_to_text()
        test_verification_dataset_stats()
        test_live_round2_fixes()
    except Exception:
        print("\n!!! SUITE CRASH:")
        traceback.print_exc()
        FAILED.append(("suite crash", "exception"))

    section("RESULT")
    print(f"PASS: {len(PASSED)}   FAIL: {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  FAILED → {name}: {detail}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
