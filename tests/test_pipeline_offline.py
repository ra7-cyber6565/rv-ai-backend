"""
Poore pipeline ka CONTROLLED OFFLINE test — network, Gemini key, ya quota ke bina.

Kyun ye test chahiye tha: 2026-08-19 ka live test invalid nikla (off-topic
sources + Gemini 429), aur us halat mein bhi report "✅ VERIFIED" chhaap rahi
thi. Unit test ab relevance aur grading ko alag-alag pakadte hain, par asli
sawaal ye hai: POORA pipeline jud kar kya bolta hai? Yahi test wo dekhta hai.

Do scenario chalte hain, dono ek hi topic par (intermittent fasting + type 2
diabetes — jaan-boojh kar chuna, kyunki ispar free/open-access research bahut
hai, aur ye energy ka sawaal NAHI hai):

  A. HEALTHY  — on-topic sources, full text pada gaya, teeno reasoning pass
                chale. Yahan top label MILNA chahiye, warna hum bug ko "hamesha
                MIXED" se badal denge.
  B. WAHI PURANI FAILURE — off-topic sources (Gagea phool, WHO surgeons
                density), 0 full text, aur 3 mein se sirf 1 pass (quota).
                Yahan "VERIFIED"/"STRONG" ASAMBHAV hona chahiye, aur wajah
                jawab mein likhi honi chahiye.

Sirf ek boundary stub hota hai — Google ki call (`GeminiReasoning.generate`),
discovery (network), reader (network), aur vector search (ChromaDB). Baaki poora
asli code chalta hai: planner, query_builder, relevance, evidence, citation,
contradiction, verification, synthesizer.

Chalao:  python3 tests/test_pipeline_offline.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_reasoning  # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402

QUESTION = ("intermittent fasting type 2 diabetes par kya asar daalta hai, "
            "research kya kehti hai")

ON_TOPIC = [
    ("Intermittent fasting improves glycemic control in type 2 diabetes: a "
     "randomized trial",
     "https://pubmed.ncbi.nlm.nih.gov/33333333/",
     "In this randomized controlled trial, intermittent fasting reduced HbA1c "
     "in adults with type 2 diabetes over 12 months. Sample size 209.",
     True, "10.1001/if-t2d"),
    ("Time-restricted eating and insulin sensitivity: systematic review and "
     "meta-analysis",
     "https://doaj.org/article/abc",
     "Systematic review of 23 trials on intermittent fasting, insulin "
     "sensitivity and diabetes remission.",
     True, "10.1234/tre-meta"),
    ("Fasting glucose response to alternate-day fasting in diabetes patients",
     "https://www.nature.com/articles/adf-diabetes",
     "Cohort study measuring fasting glucose and weight in type 2 diabetes "
     "patients practising alternate-day fasting.",
     True, "10.1038/adf"),
    ("Intermittent fasting safety in diabetes: hypoglycaemia risk",
     "https://openalex.org/W999",
     "Review of hypoglycaemia events reported during intermittent fasting "
     "protocols among diabetes patients on insulin.",
     False, ""),
]

# Bilkul wahi kachra jo pichhle live test mein energy ke sawaal par aa gaya tha
OFF_TOPIC = [
    ("Gagea bohemica: taxonomic revision in the Balkans",
     "https://openalex.org/W1", "Botanical revision of the genus Gagea.",
     True, "10.1/gagea"),
    ("Density of surgeons per 100000 population, by country",
     "https://www.who.int/data/gho/indicator/surgeons",
     "Global Health Observatory indicator listing.", False, ""),
    ("China-Pakistan Economic Corridor: geopolitics of connectivity",
     "https://openalex.org/W2", "Analysis of CPEC infrastructure politics.",
     True, "10.1/cpec"),
    ("Estimates of the global burden of foodborne diseases",
     "https://www.who.int/publications/foodborne",
     "WHO report on foodborne disease burden.", True, "10.1/food"),
]


def _records(rows) -> list:
    out = []
    for title, url, snippet, peer, doi in rows:
        out.append(SourceRecord(
            title=title, url=url, snippet=snippet, connector="pubmed",
            source_type=SourceType.PAPER, peer_reviewed=peer, doi=doi,
            year=2024, full_text_available=bool(doi)))
    return out


def _is_top_label(level: str) -> bool:
    """
    "✅ VERIFIED" / "STRONG" wala top label hai ya nahi.

    Seedha `"VERIFIED" in level` likhna galat hai — "⚠️ UNVERIFIED" ke andar bhi
    "VERIFIED" chhupa hai, aur usse test jhoothi paas/fail deta hai.
    """
    return ("UNVERIFIED" not in level
            and ("VERIFIED" in level or "STRONG" in level))


# ── stubs (sirf network / Google ki seemaayein) ───────────────────────────────
class _FakeVectors:
    """ChromaDB ke bina — koi uploaded document nahi."""
    last_error = ""

    def retrieve(self, question, project_id, n_results=4):
        return {"context": "", "sources": []}


def _fake_discover(records):
    def discover(**kwargs):
        return {
            "records": list(records),
            "log": [{"connector": "pubmed", "count": len(records), "error": "",
                     "reason": "", "note": "", "seconds": 0.4}],
            "connectors_searched": ["pubmed", "openalex"],
            "seen_urls": {r.url for r in records},
        }
    return discover


def _fake_reader(read_ok: bool):
    """
    Reader network par jaata hai, isliye stub. `read_ok=False` wahi halat hai jo
    live test mein thi: 5 mein se 0 full text.
    """
    def enrich(pack, max_sources=3, budget_chars=2400):
        entries = []
        for s in pack.sources[:max_sources]:
            if read_ok:
                s.full_text_chars = 5000
                s.read_level = "full_text"
                entries.append({"source_id": s.source_id, "ok": True,
                                "chars": 5000, "reason": "", "title": s.title})
            else:
                entries.append({"source_id": s.source_id, "ok": False, "chars": 0,
                                "reason": "paywall — koi free route nahi mila",
                                "title": s.title})
        return {"attempted": len(entries),
                "succeeded": len([e for e in entries if e["ok"]]),
                "failed": len([e for e in entries if not e["ok"]]),
                "skipped": 0,
                "chars_read": sum(e["chars"] for e in entries),
                "note": "full text pada" if read_ok else "full text nahi mila",
                "entries": entries}
    return enrich


class _FakeGemini:
    """
    `GeminiReasoning.generate` ki jagah. Prompt dekh kar plausible output deta
    hai, aur `fail_after` ke baad wahi behave karta hai jo asli 429 karta hai:
    khaali string + error list mein entry (exception nahi — asli code bhi aisa
    hi karta hai).
    """

    def __init__(self, fail_after: int = 99):
        self.fail_after = fail_after
        self.prompts = []

    def __call__(self, brain, prompt, label=""):
        if brain.remaining <= 0:
            raise gemini_reasoning.QuotaExhausted(
                f"call budget ({brain.budget}) khatam — '{label}' skip hua")
        brain.calls_used += 1
        self.prompts.append((label, prompt))
        if brain.calls_used > self.fail_after:
            brain.errors.append(
                f"{label} failed: ResourceExhausted: 429 quota exceeded")
            return ""
        if label == "critique":
            return ("## Weaknesses\n- [S4] review hai, primary trial nahi.\n"
                    "## Missing Evidence\n- Lambi duration ka data nahi hai.\n"
                    "## Alternative Explanations\n- Weight loss hi asli wajah "
                    "ho sakti hai, fasting nahi.\n")
        if label == "synthesis":
            return (
                "## Seedha jawab\n"
                "Haan, intermittent fasting se type 2 diabetes mein sugar control "
                "thoda behtar hota hai [S1]. Par ye dawa ki jagah nahi hai.\n\n"
                "## Research se kya pata chala?\n"
                "### Fact\n"
                "- **[S1] Randomized trial:** HbA1c (3 mahine ka average sugar) kam hua.\n"
                "- **[S2] Meta-analysis:** 23 trials mein insulin sensitivity behtar mili.\n"
                "### Inference\n"
                "- [INFERENCE] Fayda zyadatar weight kam hone se aata hai [S3].\n\n"
                "## Ye kyun hota hai?\n"
                "Medicine aur biology dono taraf se yahi baat aati hai [S2].\n\n"
                "## Evidence kya kehta hai?\n"
                "Do mein se ek trial randomized tha, yaani logon ko lottery se group "
                "mila — isse bias kam hota hai [S1].\n\n"
                "## Iske against kya mila?\n"
                "Ek review mein fayda bahut chhota tha [S4].\n\n"
                "## Kya abhi unknown hai?\n"
                "Insulin lene wale patients mein sugar bahut neeche girne ka khatra "
                "kitna hai, ye saaf nahi [S4].\n\n"
                "## Final conclusion\n"
                "Insulin par chal rahe patients ka 2 saal ka trial chahiye. "
                "Apne doctor se baat kiye bina fasting shuru na karein.\n")
        return ("## Factual Findings\n- [ESTABLISHED] Fasting se HbA1c kam hua [S1].\n"
                "## Context & Mechanisms\nInsulin sensitivity behtar hoti hai [S2].\n"
                "## Cross-Disciplinary Connections\nMedicine + biology [S2].\n"
                "## Evidence Audit\n[STRONG EVIDENCE] [S1] [S2]\n"
                "## Source Relevance Check\nSources sawaal se match karte hain.\n")


def _run(records, read_ok: bool, fail_after: int = 99, mode: str = "MAXIMUM"):
    fake = _FakeGemini(fail_after=fail_after)
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="offline-test", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = _FakeVectors()
        engine.discovery.discover = _fake_discover(records)
        engine.reader.enrich = _fake_reader(read_ok)
        return engine.research(QUESTION, depth_mode=mode), fake
    finally:
        gemini_reasoning.GeminiReasoning.generate = original


# ── A. healthy run ───────────────────────────────────────────────────────────
def test_healthy_run_reaches_top_label():
    result, fake = _run(_records(ON_TOPIC), read_ok=True)
    level = result["evidence_level"]
    assert _is_top_label(level), level
    assert "MIXED" not in level, level
    cov = result["coverage"]
    assert cov["full_text_sources_read"] >= 1, cov
    assert cov["reasoning_passes"] == "3/3", cov["reasoning_passes"]
    assert cov["offtopic_dropped"] == 0, cov


def test_healthy_run_answer_has_real_sections():
    """
    §16 ka naya structure. (Pehle ye test purane numbered headings —
    "1. Seedha Jawab", "9. Verification Status" — dhoondta tha. Wo structure
    intel ke naye instruction se badal gaya hai: ab pehla section `## Seedha
    jawab` hai aur technical sab kuch aakhir mein. Feature kuch nahi hata,
    sirf test ki expectation naye structure par le aayi gayi hai.)
    """
    result, _ = _run(_records(ON_TOPIC), read_ok=True)
    answer = result["answer"]
    for heading in ("## Seedha jawab", "## Research se kya pata chala?",
                    "## Final conclusion", "## Sources",
                    "## Research quality / technical audit"):
        assert heading in answer, f"section gum: {heading}"
    # insaan pehle, technical baad mein — audit sabse aakhir mein hona chahiye
    assert answer.lstrip().startswith("## Seedha jawab"), answer[:80]
    assert answer.find("## Research quality / technical audit") > answer.find("## Sources")
    assert "[S1]" in answer


def test_topic_terms_are_about_the_question():
    result, fake = _run(_records(ON_TOPIC), read_ok=True)
    terms = result["coverage"]["topic_terms"]
    assert "fasting" in terms and "diabetes" in terms, terms


def test_prompts_carry_plain_language_rules():
    """Task: badi cheez ko lokal bhasha mein samjhana — prompt tak pahuncha?"""
    _, fake = _run(_records(ON_TOPIC), read_ok=True)
    labels = [label for label, _ in fake.prompts]
    assert "analysis" in labels and "synthesis" in labels, labels
    for label, prompt in fake.prompts:
        assert "SAMJHANE KA TARIKA" in prompt, f"{label} prompt mein style rule nahi"
        assert "BHASHA (sabse zaroori)" in prompt, f"{label} prompt mein bhasha rule nahi"
    synthesis = next(p for l, p in fake.prompts if l == "synthesis")
    assert "HINGLISH" in synthesis, "Hinglish sawaal par Hinglish rule nahi gaya"


# ── B. wahi purani failure ───────────────────────────────────────────────────
def test_offtopic_plus_quota_failure_cannot_be_verified():
    result, _ = _run(_records(OFF_TOPIC), read_ok=False, fail_after=1)
    level = result["evidence_level"]
    assert not _is_top_label(level), level
    # off-topic sab hat gaye, isliye pack khaali — aur ye saaf bola jaana chahiye
    assert "UNVERIFIED" in level or "MIXED" in level or "WEAK" in level, level


def test_offtopic_sources_are_dropped_from_the_pack():
    result, _ = _run(_records(OFF_TOPIC), read_ok=False, fail_after=1)
    titles = [s.get("title", "") for s in result["sources"]]
    assert not any("Gagea" in t for t in titles), titles
    assert not any("surgeons" in t.lower() for t in titles), titles


def test_partial_reasoning_is_reported_not_hidden():
    result, _ = _run(_records(ON_TOPIC), read_ok=True, fail_after=1)
    cov = result["coverage"]
    assert cov["reasoning_passes"] != "3/3", cov["reasoning_passes"]
    assert "adhoora" in cov["reasoning_note"], cov["reasoning_note"]
    level = result["evidence_level"]
    assert not _is_top_label(level), level
    assert "reasoning adhoora" in level, level


def test_zero_full_text_blocks_top_label():
    result, _ = _run(_records(ON_TOPIC), read_ok=False)
    level = result["evidence_level"]
    assert not _is_top_label(level), level
    assert "poora text nahi" in level, level
    assert result["coverage"]["full_text_sources_read"] == 0


def test_quota_failure_shows_warning_to_user():
    result, _ = _run(_records(ON_TOPIC), read_ok=True, fail_after=1)
    joined = " ".join(result.get("warnings", []))
    assert "429" in joined or "quota" in joined.lower(), joined


def test_quick_mode_does_not_get_fake_incomplete_reasoning():
    """
    QUICK mein sirf 1 pass PLAN hota hai. Use "2 pass nahi chale" batana jhooth
    hoga — reasoning gate ko budget se nahi, PLAN se compare karna chahiye.
    """
    result, _ = _run(_records(ON_TOPIC), read_ok=True, mode="QUICK")
    cov = result["coverage"]
    assert cov["reasoning_passes"] == "1/1", cov["reasoning_passes"]
    assert "adhoora" not in cov["reasoning_note"], cov["reasoning_note"]


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
