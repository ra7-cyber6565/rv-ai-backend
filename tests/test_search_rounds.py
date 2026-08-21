"""
§15 ka regression test — "search rounds LLM ke saath mar nahi sakte".

Asli shikayat ye thi: Gemini ka quota khatam hone par poora research thehar
jaata tha — jaise search bhi AI par depend karti thi. Search karna network ka
kaam hai, sochna LLM ka; dono ko ek doosre ka bandhak nahi hona chahiye.

Ye test wahi taala lagata hai:

    1. LLM BILKUL murda ho (har call fail) — tab bhi mode ke saare rounds
       chalein (MAXIMUM = 3).
    2. Round 2 aur 3 ki queries round 1 se ALAG hon (warna "round" ka koi
       matlab nahi — wahi search teen baar).
    3. Round 1 mein sirf kachra mile to use "kaafi evidence" na maana jaaye.
    4. Ek round khud crash kar jaaye (connector exception) to baaki rounds
       chalte rahein, jawab phir bhi bane, status imaandaar rahe, aur raw
       exception ka ek shabd bhi insaani jawab mein na aaye (point 9).
    5. Har round crash ho jaaye to bhi jawab + deterministic plan mile.
    6. Do baar chalane par wahi queries — koi randomness nahi.

Offline: koi network, koi API key, koi pytest.
`python3 tests/test_search_rounds.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import gemini_reasoning                  # noqa: E402
from research_engine.models import SourceRecord, SourceType    # noqa: E402
from research_engine.orchestrator import DeepResearchEngine    # noqa: E402

PASSED = 0
FAILED = 0

QUESTION = ("room temperature superconductor par latest research kya kehti hai, "
            "Tc kitna hai aur kitne pressure par")

# Round 2/3 mein hi kaam ka source milta hai — isse ye bhi sabit hota hai ki
# baad ke rounds sach mein value laate hain, sirf ginti ke liye nahi chalte.
GOOD_ROWS = [
    ("Room-temperature superconductivity in a carbonaceous sulfur hydride",
     "https://www.nature.com/articles/s41586-020-2801-z",
     "Superconductivity with a critical temperature Tc of 288 K observed in a "
     "carbonaceous sulfur hydride at 267 GPa.", True, "10.1038/s41586-020-2801-z"),
    ("Superconductivity at 250 K in lanthanum hydride under high pressure",
     "https://arxiv.org/abs/1812.01561",
     "LaH10 shows a superconducting critical temperature near 250 K at "
     "170 GPa, confirmed by resistance and isotope measurements.",
     True, "10.1038/s41586-019-1201-8"),
]

# Bilkul wahi kachra jo live benchmark mein aa gaya tha.
JUNK_ROWS = [
    ("Trends in maternal mortality 2000 to 2020",
     "https://www.who.int/publications/maternal-mortality",
     "WHO estimates of maternal mortality ratios by country.", True, "10.1/mmr"),
    ("Ferroelectricity in hafnium oxide thin films for memory devices",
     "https://openalex.org/W555",
     "HfO2 thin films show ferroelectric switching useful for FeRAM.",
     True, "10.1/hfo2"),
    ("Sunbed use and skin cancer risk: a population survey",
     "https://openalex.org/W777",
     "Survey of indoor tanning behaviour and melanoma incidence.",
     True, "10.1/sunbed"),
]


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def eq(name: str, got, want) -> None:
    check(name, got == want, f"mila {got!r}, chahiye {want!r}")


def _records(rows) -> list:
    """Har call par TAAZA objects — engine inhe mutate karta hai (read_level)."""
    return [SourceRecord(
        title=t, url=u, snippet=s, connector="openalex",
        source_type=SourceType.PAPER, peer_reviewed=peer, doi=doi, year=2024,
        full_text_available=bool(doi)) for t, u, s, peer, doi in rows]


# ── stubs: sirf network ki seemaayein ────────────────────────────────────────
class _FakeVectors:
    last_error = ""

    def retrieve(self, question, project_id, n_results=4):
        return {"context": "", "sources": []}


class _SpyDiscovery:
    """
    Round-aware discovery stub.

    `per_round`: round_no -> rows (kachra ya kaam ka).
    `crash_rounds`: in rounds mein connector exception phenkta hai — bilkul
    waise hi jaise asli duniya mein network/parse crash hota hai.
    """

    def __init__(self, per_round: dict, crash_rounds=()):
        self.per_round = per_round
        self.crash_rounds = set(crash_rounds)
        self.calls: list = []          # [(round_no, [queries])]

    def __call__(self, **kwargs):
        round_no = int(kwargs.get("round_no") or 1)
        self.calls.append((round_no, list(kwargs.get("queries") or [])))
        if round_no in self.crash_rounds:
            # Raw text jaan-boojh kar ganda hai — test yahi dekhta hai ki ye
            # user ke jawab tak na pahunche.
            raise RuntimeError(
                "ResourceExhausted: 429 grpc_status:8 quota_id: "
                "GenerateRequestsPerDayPerProject retry_delay { seconds: 31 }")
        records = _records(self.per_round.get(round_no, []))
        return {
            "records": records,
            "log": [{"connector": "openalex", "count": len(records), "error": "",
                     "reason": "", "note": "", "seconds": 0.3}],
            "connectors_searched": ["openalex", "arxiv"],
            "seen_urls": {r.url for r in records},
        }

    def rounds(self) -> list:
        return [r for r, _ in self.calls]

    def queries_for(self, round_no: int) -> list:
        for r, q in self.calls:
            if r == round_no:
                return q
        return []


def _fake_reader(read_ok: bool):
    def enrich(pack, max_sources=3, budget_chars=2400):
        entries = []
        for s in pack.sources[:max_sources]:
            if read_ok:
                s.full_text_chars = 6000
                s.read_level = "full_text"
                entries.append({"source_id": s.source_id, "ok": True,
                                "chars": 6000, "reason": "", "title": s.title})
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


class _DeadGemini:
    """
    LLM bilkul band. Asli 429 ki tarah: exception nahi, khaali string + errors
    list mein entry (yahi asli `gemini_reasoning` ka behaviour hai).
    """

    def __init__(self, fail_after: int = 0):
        self.fail_after = fail_after
        self.prompts: list = []

    def __call__(self, brain, prompt, label=""):
        if brain.remaining <= 0:
            raise gemini_reasoning.QuotaExhausted(
                f"call budget ({brain.budget}) khatam — '{label}' skip hua")
        brain.calls_used += 1
        self.prompts.append(label)
        if brain.calls_used > self.fail_after:
            brain.errors.append(
                f"{label} failed: ResourceExhausted: 429 quota exceeded "
                f"quota_id: GenerateRequestsPerDayPerProject")
            return ""
        return "## Factual Findings\n- [SOURCE-REPORTED] kuch mila [S1].\n"


def _run(per_round: dict, crash_rounds=(), read_ok: bool = True,
         fail_after: int = 0, mode: str = "MAXIMUM"):
    """Poora asli pipeline, sirf network+Google stubbed."""
    spy = _SpyDiscovery(per_round, crash_rounds=crash_rounds)
    fake = _DeadGemini(fail_after=fail_after)
    original = gemini_reasoning.GeminiReasoning.generate
    gemini_reasoning.GeminiReasoning.generate = \
        lambda self, prompt, label="": fake(self, prompt, label)
    try:
        engine = DeepResearchEngine(project_id="rounds-test", enable_kg=False,
                                    enable_memory=False)
        engine.vectors = _FakeVectors()
        engine.discovery.discover = spy
        engine.reader.enrich = _fake_reader(read_ok)
        return engine.research(QUESTION, depth_mode=mode), spy, fake
    finally:
        gemini_reasoning.GeminiReasoning.generate = original


def _human_part(answer: str) -> str:
    """Report ka wo hissa jo user padhta hai (technical block se pehle)."""
    return (answer or "").split("### Technical details")[0]


RAW_TOKENS = ("RuntimeError", "grpc_status", "quota_id", "retry_delay",
              "Traceback", "ResourceExhausted")


# ── 1. LLM murda ho, phir bhi saare rounds ──────────────────────────────────
def test_all_rounds_run_when_llm_is_dead():
    print("\nLLM band — phir bhi MAXIMUM ke teeno round chalte hain")
    result, spy, fake = _run({1: JUNK_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS})
    eq("teeno round chale", spy.rounds(), [1, 2, 3])
    eq("coverage bhi 3 round batata hai",
       result["coverage"]["research_rounds"], 3)
    check("LLM se ek bhi kaam ka jawab nahi aaya",
          result["status"] == "RESEARCH INCOMPLETE", result["status"])
    check("phir bhi round 2 ka kaam ka source pack mein pahuncha",
          any("hydride" in s.get("title", "").lower()
              or "Superconductivity" in s.get("title", "")
              for s in result["sources"]),
          str([s.get("title") for s in result["sources"]]))


def test_later_rounds_use_different_queries():
    print("\nround 2/3 ki queries round 1 se alag hain")
    _, spy, _ = _run({1: JUNK_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS})
    q1, q2, q3 = (spy.queries_for(1), spy.queries_for(2), spy.queries_for(3))
    check("teeno round ko queries mili", all([q1, q2, q3]), f"{q1}|{q2}|{q3}")
    check("round 2 round 1 ki nakal nahi hai", set(q2) != set(q1), f"{q1} vs {q2}")
    check("round 3 bhi alag hai", set(q3) != set(q1) and set(q3) != set(q2),
          f"{q3}")
    later = " ".join(q2 + q3).lower()
    check("baad ke round opposition-side bhi khojte hain",
          "contradictory" in later or "criticism" in later, later[:200])


def test_junk_round_one_is_not_treated_as_enough():
    print("\nround 1 mein sirf kachra — use 'kaafi evidence' nahi maana jaata")
    result, spy, _ = _run({1: JUNK_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS})
    check("round 1 par search ruki nahi", len(spy.rounds()) > 1, str(spy.rounds()))
    titles = " | ".join(s.get("title", "") for s in result["sources"])
    for junk in ("maternal mortality", "Ferroelectricity", "Sunbed"):
        check(f"kachra pack se bahar hai: {junk}", junk.lower() not in titles.lower(),
              titles)
    cov = result["coverage"]
    check("teeno kachra source honestly 'off-topic' gine gaye",
          cov["offtopic_dropped"] >= 3, str(cov.get("offtopic_dropped")))


# ── 2. ek round crash — baaki zinda ─────────────────────────────────────────
def test_crashed_round_does_not_kill_the_run():
    print("\nround 2 crash — round 3 phir bhi chalta hai aur jawab banta hai")
    result, spy, _ = _run({1: GOOD_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS},
                          crash_rounds=(2,))
    eq("crash ke baad bhi teeno round attempt hue", spy.rounds(), [1, 2, 3])
    check("jawab bana", len(result["answer"]) > 500, str(len(result["answer"])))
    check("sources bhi mile", len(result["sources"]) >= 1,
          str(len(result["sources"])))


def test_crash_warning_is_human_and_raw_text_stays_at_the_bottom():
    print("\ncrash ki warning insaani — raw exception sirf sabse neeche")
    result, _, _ = _run({1: GOOD_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS},
                        crash_rounds=(2,))
    joined = " ".join(result.get("warnings", []))
    check("warning mein saaf likha hai ki ek round poora nahi hua",
          "search round" in joined and "round 2" in joined, joined[:300])
    check("aur ye bhi ki utna data missing hai", "missing" in joined, joined[:300])
    for token in RAW_TOKENS:
        check(f"warning mein raw '{token}' nahi", token not in joined, joined[:200])
    human = _human_part(result["answer"])
    for token in RAW_TOKENS:
        check(f"insaani jawab mein raw '{token}' nahi", token not in human)
    check("par raw wajah report se gayab bhi nahi hui",
          any("discovery round 2 crashed" in t
              for t in result.get("technical_details", [])),
          str(result.get("technical_details"))[:300])
    check("aur wo sirf technical block mein hai",
          "grpc_status" in result["answer"].split("### Technical details")[-1],
          result["answer"][-500:])


def test_every_round_crash_still_gives_an_honest_plan():
    print("\nsaare round crash — jawab, imaandaar status aur deterministic plan")
    result, spy, _ = _run({1: GOOD_ROWS}, crash_rounds=(1, 2, 3))
    eq("teeno round attempt hue (pehle crash par ruke nahi)", spy.rounds(),
       [1, 2, 3])
    eq("koi source nahi mila, aur ye chhupaya nahi gaya",
       len(result["sources"]), 0)
    eq("status imaandaar hai", result["status"], "RESEARCH INCOMPLETE")
    check("jawab khaali template nahi hai", len(result["answer"]) > 500,
          str(len(result["answer"])))
    check("LLM ke bina bhi deterministic agla-kadam plan diya gaya",
          "agla-kadam plan" in result["answer"],
          result["answer"][:200])
    joined = " ".join(result.get("warnings", []))
    check("teeno round ki kami warning mein hai",
          "3 search round" in joined, joined[:300])
    for token in RAW_TOKENS:
        check(f"insaani jawab mein raw '{token}' nahi",
              token not in _human_part(result["answer"]))


def test_search_crash_is_not_blamed_on_the_llm():
    print("\nLLM theek ho aur search gire — dosh LLM par nahi jaata")
    result, spy, fake = _run({1: GOOD_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS},
                             crash_rounds=(2,), fail_after=99)
    eq("teeno reasoning pass chale", fake.prompts,
       ["analysis", "critique", "synthesis"])
    eq("status COMPLETE hi rehta hai", result["status"], "COMPLETE")
    check("failure_kind khaali hai (ye AI ki galti nahi thi)",
          not result.get("failure_kind"), str(result.get("failure_kind")))
    joined = " ".join(result.get("warnings", []))
    check("phir bhi search ki kami warning mein likhi hai",
          "search round" in joined, joined[:200])


def test_llm_dead_run_never_claims_verified():
    print("\nLLM band ho to top label kabhi nahi")
    result, _, _ = _run({1: GOOD_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS})
    level = result["evidence_level"]
    check("VERIFIED/STRONG nahi bola gaya",
          "UNVERIFIED" in level or "RESEARCH INCOMPLETE" in level
          or "MIXED" in level or "WEAK" in level, level)
    check("label mein hi RESEARCH INCOMPLETE likha hai",
          "RESEARCH INCOMPLETE" in level, level)


def test_rounds_are_deterministic():
    print("\n₹0 + determinism — do baar chalao, wahi queries")
    _, a, _ = _run({1: JUNK_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS})
    _, b, _ = _run({1: JUNK_ROWS, 2: GOOD_ROWS, 3: GOOD_ROWS})
    eq("dono run ki round+query list bilkul same", a.calls, b.calls)


def main() -> int:
    print("=" * 68)
    print("§15 — search rounds LLM ke bina bhi chalti rahein")
    print("=" * 68)
    test_all_rounds_run_when_llm_is_dead()
    test_later_rounds_use_different_queries()
    test_junk_round_one_is_not_treated_as_enough()
    test_crashed_round_does_not_kill_the_run()
    test_crash_warning_is_human_and_raw_text_stays_at_the_bottom()
    test_every_round_crash_still_gives_an_honest_plan()
    test_search_crash_is_not_blamed_on_the_llm()
    test_llm_dead_run_never_claims_verified()
    test_rounds_are_deterministic()
    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
