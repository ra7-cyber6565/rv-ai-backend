"""#122 — lens sirf DHOONDHNE me nahi, SOCHNE me bhi jaaye.

Naapa gaya defect (2026-08-26), intel ke sawaal se: "koi theory jaise
information theory ya game theory ... janta h to kya inka use bhi wo krta h".

  - `specialist_domains.detect_profiles('game theory se faisla kaise lein')` → `[]`
  - `lenses.framework_phrases(...)` → `['game theory']`
  - par wo naam sirf search query + relevance anchor tak jaata tha; reasoning
    prompt me lens ka ek shabd bhi nahi jaata tha, kyunki `lenses.prompt_block()`
    ko production me koi import hi nahi karta tha (sirf test).

Is file ke teen kaam hain:
  1. lens block reasoning prompt (analysis + hypothesis) me sach me jaata hai,
  2. jahan sochne ka koi ozaar nahi mila wahan prompt bilkul purana rehta hai
     (bekaar tokens nahi jaate),
  3. jo naam PAKKA nahi hai wo prompt me naam-le kar nahi jaata — kyunki
     possessive cue 'physics'/'market'/'company' ko bhi "thinker" bana deta hai.

Aur honesty pin: lens block me hamesha likha rehta hai ki ye naam citation nahi
hain, aur unse koi claim nahi banti.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lenses as L                       # noqa: E402
from research_engine.depth import get_depth_config            # noqa: E402
from research_engine.gemini_reasoning import GeminiReasoning  # noqa: E402
from research_engine.hypothesis import HypothesisEngine       # noqa: E402
from research_engine.models import (EvidencePack, SourceRecord,  # noqa: E402
                                    SourceType)
from research_engine.planner import ResearchPlanner           # noqa: E402


def _lens(question: str) -> dict:
    plan = ResearchPlanner().plan(question, get_depth_config("QUICK"))
    return plan.get("lens") or {}


def _pack() -> EvidencePack:
    source = SourceRecord(
        title="Cooperation under repeated interaction",
        url="https://journal-a.example/s1",
        snippet="Repeated interaction changes the payoff of defection.",
        connector="openalex", source_type=SourceType.PAPER,
        peer_reviewed=True, is_primary=True, read_level="full_text",
        full_text_chars=400, relevance_score=0.9, quality_score=0.8,
    )
    source.source_id = "S1"
    return EvidencePack(question="game theory se faisla kaise lein",
                        sources=[source], topic_terms=["game theory"])


# ── 1. block banta hai, aur usme ozaar ka niyam + honesty dono hain ──────────

def test_named_framework_reaches_the_reasoning_block():
    block = L.reasoning_block(_lens("game theory se faisla kaise lein"))
    assert "game theory" in block.casefold(), block


def test_block_says_apply_the_framework_as_a_tool():
    block = L.reasoning_block(_lens("game theory se faisla kaise lein"))
    assert "OZAAR" in block, block
    # "fit nahi hota to zabardasti mat lagao" — bina ise lens ek majboori
    # ban jaata hai, aur app har sawaal me framework thopne lagta hai.
    assert "zabardasti mat lagao" in block, block


def test_block_never_lets_a_lens_name_become_evidence():
    block = L.reasoning_block(_lens("information theory ka use kya hai"))
    assert "NOT citations" in block, block
    assert "[INFERENCE]" in block, block


def test_disciplines_from_word_shape_also_reach_the_block():
    block = L.reasoning_block(_lens("neuroplasticity se dimag kaise badalta hai"))
    assert "neuroscience" in block.casefold(), block


# ── 2. jahan ozaar nahi mila wahan block khaali (tokens bekaar na jaayein) ───

def test_plain_factual_question_gets_no_lens_block():
    # Sirf concept phrases (sawaal ke apne shabd) block nahi kholte — wo prompt
    # me pehle se maujood sawaal ka dohraav hote.
    assert L.reasoning_block(_lens("what is the melting point of iron")) == ""
    assert L.reasoning_block(_lens("kesar ka ilaaj kaise ho sakta hai")) == ""


def test_bad_input_gives_empty_block():
    assert L.reasoning_block(None) == ""          # type: ignore[arg-type]
    assert L.reasoning_block({}) == ""
    assert L.reasoning_block({"concepts": ["kesar"]}) == ""


def test_english_vocabulary_alone_does_not_open_the_block():
    # 'neend kaise sudhare' → english_terms ['sleep'], par sochne ka koi ozaar
    # nahi. Sirf translation vocabulary ke liye prompt me poora block bhejna
    # ~1050 characters ka faltu kharcha hai — aur model ko kuch naya nahi deta.
    plan = _lens("neend kaise sudhare")
    assert plan.get("english_terms"), plan
    assert not plan.get("frameworks") and not plan.get("disciplines"), plan
    assert L.reasoning_block(plan) == ""
    # Ek kachcha (possessive-derived) naam bhi block nahi kholta — wo naam khud
    # ek anumaan hai, uske liye tokens kharch karna galat hai.
    guessy = _lens("market ka niyam se neend kaise sudhare")
    assert guessy.get("thinkers") == ["market"], guessy.get("thinkers")
    assert guessy.get("english_terms"), guessy
    assert L.reasoning_block(guessy) == ""


# ── 3. naam sirf tab jab cue pakka ho (warna 'physics' bhi thinker ban jaata) ─

def test_a_cued_thinker_is_named_in_the_block():
    plan = _lens("according to Carl Jung shadow work kaise hota hai")
    assert plan.get("thinkers_confident") == ["Carl Jung"], plan.get("thinkers")
    block = L.reasoning_block(plan)
    assert "Carl Jung" in block, block
    # heading khud bataye ki sirf documented kaam ki baat ho rahi hai
    assert "documented work only" in block, block


def test_possessive_only_names_stay_out_of_the_prompt():
    # 'physics ki theory' me 'physics' search ke liye theek hai (galat guess ka
    # kharcha = 0 result), par prompt me naam le kar bhejna jhooth ban jaata.
    for question in ("physics ki theory kya hai",
                     "market ka niyam kya hai",
                     "company ke research paper me kya hai"):
        plan = _lens(question)
        assert plan.get("thinkers"), question          # search ko mila
        assert not plan.get("thinkers_confident"), question
        assert L.reasoning_block(plan) == "", question


def test_search_side_still_keeps_multiword_and_devanagari_names():
    # Ye naam prompt me nahi jaate, par search se gayab bhi nahi hone chahiye.
    assert _lens("leonardo da vinci ke notebook me kya likha hai"
                 ).get("thinkers") == ["leonardo da vinci"]
    assert _lens("रिचर्ड फाइनमैन की theory kya kehti hai"
                 ).get("thinkers") == ["रिचर्ड फाइनमैन"]


def test_possessive_name_is_not_listed_even_when_the_block_opens():
    # Yahan framework block khol deta hai, isliye "block khaali rehta hai" wali
    # suraksha kaam nahi karti — naam khud row me nahi aana chahiye.
    for question, guess in (
            ("market ka niyam samjhao aur game theory se faisla lo", "market"),
            ("physics ki theory aur game theory me farq kya hai", "physics")):
        plan = _lens(question)
        assert guess in (plan.get("thinkers") or []), plan.get("thinkers")
        block = L.reasoning_block(plan)
        assert block, question
        assert guess not in block.casefold(), block


# ── 4. jo sach me padha gaya usse aaya naam alag khaane me, claim ban kar nahi ─

def _corpus_records():
    """Teen alag research family (alag first author) — ek hi lab ka dohraav nahi."""
    rows = []
    groups = [("S1", "Anita Rao", "https://journal-a.example/1",
               "Journal of Conflict Resolution"),
              ("S2", "Boris Petrov", "https://press-b.example/2",
               "American Political Science Review"),
              ("S3", "Chen Wei", "https://society-c.example/3",
               "Nature Human Behaviour")]
    for source_id, lead, url, venue in groups:
        row = SourceRecord(
            title="Repeated interaction and the payoff of defection",
            url=url, connector="openalex", source_type=SourceType.PAPER,
            snippet="Repeated interaction changes the payoff of defection.",
            peer_reviewed=True, relevance_score=0.8, quality_score=0.7,
        )
        row.source_id = source_id
        row.authors = [lead, "Robert Axelrod"]
        row.venue = venue
        rows.append(row)
    return rows


def _merged_corpus_lens():
    corpus = L.lenses_from_sources(_corpus_records(),
                                   question="game theory se faisla kaise lein")
    return L.merge_corpus_lenses(_lens("game theory se faisla kaise lein"), corpus)


def test_corpus_names_reach_the_block_in_their_own_section():
    block = L.reasoning_block(_merged_corpus_lens())
    assert "FROM WHAT WAS ACTUALLY RETRIEVED" in block, block
    assert "Robert Axelrod" in block, block
    assert "repeated interaction" in block, block
    # section ka label khud kehta hai ki ye sirf pattern hai
    assert "only a pattern" in block, block
    assert "iska matlab ye NAHI ki" in block, block


def test_corpus_feedback_never_moves_the_scoring_anchor():
    # Warna app apni hi retrieval ko inaam dene lagta hai: jo mila usi ke shabd
    # se score badhta, aur mid-run score compare karna bemaani ho jaata.
    plan = _lens("game theory se faisla kaise lein")
    merged = _merged_corpus_lens()
    assert L.scoring_vocabulary(merged) == L.scoring_vocabulary(plan)
    assert "repeated interaction" not in L.scoring_vocabulary(merged)


def test_a_model_guessed_name_can_never_become_confident():
    # build_lens_plan ka model path: model se aaya naam bhi ek guess hai. Wo
    # search me jaa sakta hai, par prompt me naam le kar nahi.
    def fake_generate(prompt: str, purpose: str = "") -> str:
        return ('{"thinkers": ["Nikola Tesla"], "frameworks": [], '
                '"disciplines": [], "concepts": [], "english_terms": []}')

    plan = L.build_lens_plan("vibration se energy kaise nikalti hai",
                             generate=fake_generate)
    assert plan.get("model_used") is True, plan.get("model_status")
    assert "Nikola Tesla" in (plan.get("thinkers") or []), plan
    assert "Nikola Tesla" not in (plan.get("thinkers_confident") or []), plan
    assert "Nikola Tesla" not in L.reasoning_block(plan)


def test_confident_list_survives_the_model_merge():
    # `_merge` sirf apni limits wali keys aage bhejta hai — agar
    # `thinkers_confident` chhoot jaaye to model path par pakka naam chup-chaap
    # gayab ho jaata aur prompt patla ho jaata.
    def fake_generate(prompt: str, purpose: str = "") -> str:
        return '{"disciplines": ["psychology"]}'

    question = "according to Carl Jung shadow work kaise hota hai"
    plan = L.build_lens_plan(question, generate=fake_generate)
    assert plan.get("model_used") is True, plan.get("model_status")
    assert plan.get("thinkers_confident") == ["Carl Jung"], plan
    assert "Carl Jung" in L.reasoning_block(plan)


# ── 5. asli wiring: block sach me dono reasoning prompt me pahunchta hai ─────

FRAMEWORK_Q = "game theory se faisla kaise lein"
PLAIN_Q = "what is the melting point of iron"


def _plan(question: str) -> dict:
    return ResearchPlanner().plan(question, get_depth_config("QUICK"))


def _analysis_prompt(question: str, plan: dict) -> str:
    # __init__ provider setup maangta hai; prompt banane me self ka kaam nahi,
    # aur test ko koi API key nahi chhoona chahiye.
    engine = object.__new__(GeminiReasoning)
    return GeminiReasoning.prompt_analysis(engine, question, _pack(), plan)


def test_analysis_prompt_carries_the_lens_block():
    text = _analysis_prompt(FRAMEWORK_Q, _plan(FRAMEWORK_Q))
    assert "LENS PLAN" in text, text[-1200:]
    assert "game theory" in text.casefold()
    assert "OZAAR" in text


def test_hypothesis_prompt_carries_the_lens_block():
    plan = _plan(FRAMEWORK_Q)
    text = HypothesisEngine().prompt(FRAMEWORK_Q, "analysis text", _pack(),
                                     plan, count=2)
    assert "LENS PLAN" in text, text[-1200:]
    assert "OZAAR" in text


def test_lens_free_question_leaves_both_prompts_byte_identical():
    # Ozaar nahi mila to ek shabd bhi extra na jaaye — na khaali line, na spacing.
    plan = _plan(PLAIN_Q)
    stripped = dict(plan)
    stripped["lens"] = {}
    assert _analysis_prompt(PLAIN_Q, plan) == _analysis_prompt(PLAIN_Q, stripped)
    engine = HypothesisEngine()
    assert (engine.prompt(PLAIN_Q, "a", _pack(), plan, count=2)
            == engine.prompt(PLAIN_Q, "a", _pack(), stripped, count=2))
    assert "LENS PLAN" not in _analysis_prompt(PLAIN_Q, plan)
