"""Lens layer ke tests — #82 "app khud soche" + #81 cross-lingual anchor.

Ye file DO baaton ko pin karti hai, dono intel ke shabdon se:

  1. "gimini ka use hi naa ho sochne me ... or gimini ka queta bhi khatam na ho"
     → lens selection ka default raasta model-free hai. Agar koi galti se
     model call wapas plug kare, `test_no_model_call_*` red ho jayega.

  2. "sirf unhe hi mt add krna ... unke baare me app khud se soch reserch kr ske"
     → lens un shabdon par bhi banta hai jo kisi list me likhe hi nahi. Isliye
     yahan jaan-boojh kar aise topic use hue hain jo intel ne kabhi nahi bataye
     (epigenetics, phenomenology, hermeticism, Prigogine, Talmud).

Aur ek honesty pin: lens ka naam EVIDENCE NAHI hai. Har plan par
`verified is False` aur `evidence_status` me saaf likha hota hai ki koi source
padha hi nahi gaya.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lenses as L                      # noqa: E402
from research_engine.depth import get_depth_config           # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.planner import ResearchPlanner          # noqa: E402
from research_engine.relevance import RelevanceEngine        # noqa: E402


def _boom(*_args, **_kwargs):
    raise AssertionError("model call hui — quota kharch hone lagi")


_EMPTY_JSON = ('{"disciplines": [], "frameworks": [], "thinkers": [], '
               '"source_families": [], "english_terms": [], "concepts": []}')


class _Spy:
    """Ginti karne wala stub. Sirf "exception phenkna" kaafi nahi hai —
    build_lens_plan har exception nigal leta hai, isliye galat wiring chhup
    jaati thi (mutation test me pakda gaya). Ab GINTI dekhi jaati hai."""

    def __init__(self, reply: str = _EMPTY_JSON):
        self.calls = 0
        self.reply = reply

    def __call__(self, *_args, **_kwargs) -> str:
        self.calls += 1
        return self.reply


# ── 1. Gemini-free by default ────────────────────────────────────────────────

def test_no_model_call_when_generate_missing():
    plan = L.build_lens_plan("psycho-cybernetics se self image kaise badalta hai")
    assert plan["model_used"] is False
    assert plan["method"] == "deterministic"
    assert plan["model_status"] == "not_attempted"


def test_no_model_call_when_allow_model_false():
    # generate diya gaya hai par allow_model False — ek bhi call nahi honi
    # chahiye. Yahi wo switch hai jo quota bachata hai.
    spy = _Spy()
    plan = L.build_lens_plan("neuroplasticity par evidence",
                             generate=spy, allow_model=False)
    assert spy.calls == 0
    assert plan["model_used"] is False
    assert plan["model_status"] == "not_attempted"


def test_planner_only_calls_model_when_explicitly_wired():
    planner = ResearchPlanner()
    assert planner.lens_generate is None
    spy = _Spy()
    plan = planner.lens_plan("flow state me kaise jaye")
    assert spy.calls == 0
    assert plan["model_used"] is False
    assert plan["model_status"] == "not_attempted"
    # switch on karne par hi — aur tab bhi ek sawaal par sirf EK call.
    planner.lens_generate = spy
    planner.lens_plan("dopamine loops kaise bante hain")
    planner.lens_plan("dopamine loops kaise bante hain")
    assert spy.calls == 1


# ── 2. Anjaan shabd bhi lens paate hain (koi topic list nahi) ────────────────

def test_unlisted_words_get_disciplines():
    cases = {
        "epigenetics se trauma agli peedhi me kaise jata hai": "genetics",
        "phenomenology consciousness ke baare me kya kehti hai": "phenomenology",
        "hermeticism ka modern psychology par asar": "history of esotericism",
        "thermodynamics ke second law ka matlab": "thermodynamics",
        "cryptography me lattice based schemes": "cryptography",
    }
    for question, expected in cases.items():
        disciplines, _ = L.morpheme_disciplines(question)
        assert expected in disciplines, (question, disciplines)


def test_longest_suffix_wins():
    # "epigenetics" me "netics" bhi hai. Pehle isi wajah se cybernetics aa jata
    # tha — galat lens. Sabse lamba suffix ("genetics") jeetna chahiye.
    disciplines, _ = L.morpheme_disciplines("epigenetics kya hai")
    assert "genetics" in disciplines
    assert "cybernetics" not in disciplines


def test_ology_word_is_its_own_field():
    disciplines, _ = L.morpheme_disciplines("phenomenology kya hai")
    assert "phenomenology" in disciplines


def test_tradition_marker_gives_public_domain_family():
    disciplines, families = L.morpheme_disciplines(
        "ved aur puran me time ka concept kya tha")
    assert "Indology" in disciplines
    assert any("public-domain" in fam for fam in families)


def test_marker_does_not_fire_on_english_lookalikes():
    # "proved", "solved", "involved" me "ved" chhupa hai; "municipal" me "muni".
    # Andha substring match physics ke sawaal ko Indology bana deta tha.
    for question in ("this proved that the solved problem involved observed data",
                     "municipal water supply moved to a new pipeline",
                     "sufficient evidence for digital marketing"):
        disciplines, families = L.morpheme_disciplines(question)
        assert disciplines == [], (question, disciplines)
        assert families == []


def test_non_indic_traditions_also_covered():
    # intel ne ye kabhi nahi bataye — phir bhi lens milna chahiye.
    for question, expected in (("talmud me interest par kya likha hai",
                                "Jewish studies"),
                               ("hadith ki authenticity kaise jaanchi jati hai",
                                "Islamic studies"),
                               ("avesta ke fire rituals", "Iranian studies")):
        disciplines, _ = L.morpheme_disciplines(question)
        assert expected in disciplines, (question, disciplines)


# ── 3. Framework naam — head noun se, list se nahi ──────────────────────────

def test_framework_head_nouns():
    cases = {
        "game theory se negotiation kaise jeete": "game theory",
        "attention residue kaam ki quality girata hai": "attention residue",
        "default mode network aur creativity": "default mode network",
        "flow state me enter kaise kare": "flow state",
        "dopamine loops se addiction": "dopamine loops",
        "hedonic treadmill se bahar": "hedonic treadmill",
        "prisoner's dilemma real life me": "prisoner dilemma",
        "bayes theorem ka intuition": "bayes theorem",
    }
    for question, expected in cases.items():
        assert expected in L.framework_phrases(question), (question,
                                                           L.framework_phrases(question))


# ── 4. Vyakti ke naam — cue se, naam-list se nahi ───────────────────────────

def test_thinker_from_honorific_and_possessive_and_english_cue():
    assert "barbara oakley" in L.thinker_candidates(
        "dr barbara oakley ke method se maths kaise sikhe")
    assert "neville goddard" in L.thinker_candidates(
        "neville goddard ki book kya sikhati hai")
    assert any("Prigogine" in name for name in L.thinker_candidates(
        "according to Ilya Prigogine dissipative structures kya hai"))


def test_thinker_adds_primary_writing_family_not_a_claim():
    plan = L.build_lens_plan("ramanujan ke notebooks me kya khaas tha")
    assert plan["thinkers"]
    assert any("primary writings" in fam for fam in plan["source_families"])
    assert plan["verified"] is False
    assert "not_citations" in plan["evidence_status"]


# ── 5. Guess ka wazan scoring par na pade ───────────────────────────────────

def test_scoring_vocabulary_excludes_guessed_disciplines_and_thinkers():
    plan = L.build_lens_plan("epigenetics se trauma kaise jata hai")
    assert "genetics" in plan["disciplines"]
    assert "genetics" not in L.scoring_vocabulary(plan)
    plan2 = L.build_lens_plan("dr barbara oakley ke method se maths")
    assert plan2["thinkers"]
    assert "barbara oakley" not in L.scoring_vocabulary(plan2)


def test_english_question_anchor_is_empty_no_op():
    for question in ("room temperature superconductivity latest evidence",
                     "dark matter direct detection null results",
                     "how to improve cognitive performance"):
        plan = L.build_lens_plan(question, base_query=question)
        assert L.scoring_query(plan) == "", (question, L.scoring_query(plan))


def test_expanded_query_is_identity_without_anchor():
    engine = RelevanceEngine()
    for text in ("dark matter", "", "room temperature superconductivity"):
        assert engine.expanded_query(text) == text


def test_set_scoring_anchor_changes_expansion_and_clears_cache():
    engine = RelevanceEngine()
    engine.topic_of("dimag tej kaise kare")
    engine.set_scoring_anchor("cognitive performance")
    assert engine._topic_cache == {}
    assert engine.expanded_query("dimag tej") == "dimag tej cognitive performance"
    # anchor already inside query → dobara nahi jodta
    assert engine.expanded_query("cognitive performance kaise badhaye") == \
        "cognitive performance kaise badhaye"


# ── 6. Search query banane ka contract ─────────────────────────────────────

def test_base_query_never_dropped_and_limit_respected():
    question = "game theory se negotiation kaise jeete"
    plan = L.build_lens_plan(question, base_query=question)
    for round_no in (1, 2, 3):
        queries = L.lens_queries(plan, base=question, round_no=round_no, limit=4)
        assert question in queries
        assert len(queries) <= 4
        assert len(queries) == len({q.casefold() for q in queries})


def test_round_two_adds_counter_evidence_query():
    question = "flow state me enter kaise kare"
    plan = L.build_lens_plan(question, base_query=question)
    joined = " | ".join(L.lens_queries(plan, base=question, round_no=2))
    assert "counter evidence" in joined


def test_plan_is_deterministic():
    question = "vedanta aur upanishadon me atman kya hai"
    first = L.build_lens_plan(question, base_query=question)
    second = L.build_lens_plan(question, base_query=question)
    assert first == second


# ── 7. Planner + cross-lingual acceptance ──────────────────────────────────

def _papers():
    rows = [
        ("Cognitive training and working memory performance: a randomized trial",
         "Randomized controlled trial of adaptive working memory training in "
         "healthy adults; measured cognitive performance outcomes."),
        ("Aerobic exercise improves brain performance and hippocampal volume",
         "Exercise intervention improved memory, attention and cognitive "
         "performance in older adults."),
        ("Bearing witness: oral history archives of coastal fishing communities",
         "Ethnographic oral history project documenting fishing village "
         "narratives and archival preservation practice."),
    ]
    return [SourceRecord(title=t, url=f"https://example.org/p{i}", snippet=s,
                         connector="openalex", source_type=SourceType.PAPER)
            for i, (t, s) in enumerate(rows)]


def test_planner_plan_exposes_lens_and_anchor():
    plan = ResearchPlanner().plan("dimag tej kaise kare",
                                  get_depth_config("QUICK"))
    assert isinstance(plan.get("lens"), dict)
    assert plan["lens"]["verified"] is False
    assert "cognitive" in (plan.get("lens_scoring_query") or "")


def test_devanagari_question_keeps_english_papers_and_drops_off_topic():
    planner = ResearchPlanner()
    config = get_depth_config("QUICK")
    for question in ("dimag tej kaise kare", "दिमाग तेज कैसे करें"):
        anchor = planner.plan(question, config).get("lens_scoring_query") or ""
        assert anchor, question
        engine = RelevanceEngine()
        engine.set_scoring_anchor(anchor)
        kept = engine.rank(_papers(), question, max_sources=10, max_per_origin=10)
        titles = [record.title for record in kept]
        assert len(kept) == 2, (question, titles)
        assert not any(title.startswith("Bearing witness") for title in titles)


def test_english_question_scores_unchanged_by_anchor():
    question = "how to improve cognitive performance"
    plain = RelevanceEngine()
    anchored = RelevanceEngine()
    anchored.set_scoring_anchor(
        ResearchPlanner().plan(question, get_depth_config("QUICK"))
        .get("lens_scoring_query") or "")
    left = [(s.title, round(s.relevance_score or 0.0, 6))
            for s in plain.rank(_papers(), question, max_sources=10,
                                max_per_origin=10)]
    right = [(s.title, round(s.relevance_score or 0.0, 6))
             for s in anchored.rank(_papers(), question, max_sources=10,
                                    max_per_origin=10)]
    assert left == right


def test_orchestrator_sets_anchor_before_any_ranking():
    """Live pipeline me anchor sach me lagta hai — sirf plan me padha nahi rehta.

    Ranking ``_discover`` ke andar hoti hai (evidence.build_pack → rank), isliye
    stub wahin lagaya hai: jo anchor us waqt tak set ho chuka hai, wahi ranking
    ko milega. Isse "code me line likhi hai" ke bajaye "chalti hai" pin hota hai.
    """
    from research_engine.orchestrator import DeepResearchEngine

    engine = DeepResearchEngine(enable_kg=False, enable_memory=False)
    seen = {}

    class _Stop(Exception):
        pass

    def fake_discover(question, plan, config, doc_records, job_id=None):
        seen["anchor"] = engine.evidence.relevance.scoring_anchor
        seen["plan_anchor"] = plan.get("lens_scoring_query")
        raise _Stop()

    engine._discover = fake_discover
    engine._document_records = lambda question, config: ([], "")
    try:
        engine.research("दिमाग तेज कैसे करें", depth_mode="QUICK", job_id=None)
    except Exception:
        pass

    assert "anchor" in seen, "_discover tak pipeline pahunchi hi nahi"
    assert seen["anchor"] == seen["plan_anchor"]
    assert "cognitive" in (seen["anchor"] or "")


# ── 8. Model raasta (band hai, par tootna nahi chahiye) ────────────────────

def test_model_json_is_accepted_but_never_verified():
    payload = ('```json\n{"disciplines": ["sleep science"], '
               '"frameworks": ["two process model"], "thinkers": [], '
               '"source_families": [], "english_terms": [], "concepts": []}\n```')
    plan = L.build_lens_plan("neend kaise sudhare", generate=lambda *_a, **_k: payload,
                             allow_model=True)
    assert plan["model_used"] is True
    assert "sleep science" in plan["disciplines"]
    assert plan["verified"] is False


def test_model_prose_is_rejected_and_falls_back():
    plan = L.build_lens_plan("neend kaise sudhare",
                             generate=lambda *_a, **_k: "Sleep is important because ...",
                             allow_model=True)
    assert plan["model_used"] is False
    assert "fell_back_to_deterministic" in plan["model_status"]


def test_model_sentence_items_are_dropped():
    payload = ('{"disciplines": ["Studies show that sleep improves memory '
               'consolidation in adults."], "frameworks": ["sleep science"], '
               '"thinkers": [], "source_families": [], "english_terms": [], '
               '"concepts": []}')
    plan = L.build_lens_plan("neend kaise sudhare", generate=lambda *_a, **_k: payload,
                             allow_model=True)
    assert plan["disciplines"] == [] or all(
        "Studies show" not in item for item in plan["disciplines"])
    assert "sleep science" in plan["frameworks"]


def test_prompt_block_carries_honesty_tail():
    plan = L.build_lens_plan("game theory se negotiation")
    block = L.prompt_block(plan)
    assert "not" in block.lower() and "citation" in block.lower()


# ── 9. Corpus-derived lens: app padhte-padhte seekhta hai (₹0) ──────────────
#
# Ye parat intel ki us baat ka jawab hai: "ekdum adwanch lvl soch ske or
# gimini ka queta bhi khatam na ho". Round 1 ke baad jo sources ASLI ME mile,
# unke author / venue / dohraye gaye phrase se agle round ki queries banti hain
# — bina ek bhi model call ke, aur bina kisi hand-typed list ke.

_CORPUS_ROWS = [
    ("Sleep restriction degrades attention and memory consolidation",
     "Experimental sleep restriction reduced sustained attention; memory "
     "consolidation during slow wave sleep was impaired.",
     ["Matthew Walker", "Bryce Mander"], "Journal of Cognitive Neuroscience"),
    ("Slow wave sleep and hippocampal memory consolidation in adults",
     "Overnight polysomnography showed slow wave sleep predicted memory "
     "consolidation gains.",
     ["Matthew Walker", "Robert Stickgold"], "Nature Reviews Neuroscience"),
    ("Circadian misalignment and cognitive performance in shift workers",
     "Shift work produced circadian misalignment and reduced sustained "
     "attention across the night shift.",
     ["Charles Czeisler"], "Sleep Medicine Reviews"),
    ("Oral history archives of coastal fishing communities",
     "Ethnographic archival preservation practice in fishing villages.",
     ["A Ghosh"], "Journal of Folklore Studies"),
]


def _corpus_records():
    records = [SourceRecord(title=title, url=f"https://example.org/c{i}",
                            snippet=snippet, connector="openalex",
                            source_type=SourceType.PAPER, authors=list(authors),
                            venue=venue, relevance_score=0.8)
               for i, (title, snippet, authors, venue) in enumerate(_CORPUS_ROWS)]
    # First two share Matthew Walker but represent different research families:
    # different lead groups/methods. Corpus phrase repetition must count those
    # families, not raw URLs or mirror-like papers from one lab.
    records[0].methodology = "experimental"
    records[1].authors = ["Robert Stickgold", "Matthew Walker"]
    records[1].methodology = "observational"
    return records


def test_corpus_thinker_needs_two_sources():
    # "Matthew Walker" do papers me hai → lens. "Charles Czeisler" ek me →
    # nahi, kyunki ek paper ka author us baat ka kendra hona saabit nahi karta.
    names = L.author_thinkers(_corpus_records())
    assert "Matthew Walker" in names
    assert not any("Czeisler" in name for name in names)
    assert not any("Ghosh" in name for name in names)


def test_corpus_discipline_from_venue_and_repeated_venue_ranks_first():
    fields = L.venue_disciplines(_corpus_records())
    assert "cognitive neuroscience" in fields
    assert "neuroscience" in fields
    # off-topic decoy ka journal sabse peechhe — lens_queries sirf [:2] leti hai
    assert fields.index("cognitive neuroscience") < fields.index("folklore studies")
    # noise shabd ("journal", "of", "reviews") field ka naam nahi bante
    assert all("journal" not in field for field in fields)


def test_corpus_framework_needs_two_distinct_sources():
    rows = _corpus_records()
    phrases = L.repeated_phrases(rows, question="neend kaise sudhare")
    assert "memory consolidation" in phrases
    assert "slow wave sleep" in phrases
    # sirf ek hi source me aayi baat framework nahi banti
    assert not any("fishing" in phrase for phrase in phrases)
    assert not any("archival" in phrase for phrase in phrases)


def test_corpus_framework_needs_two_independent_research_families():
    rows = [
        SourceRecord(
            title=f"Single-lab report {index}: quantum dream resonance",
            url=f"https://mirror{index}.example/paper",
            doi=f"10.1234/same-lab-{index}",
            snippet=("The quantum dream resonance protocol showed a repeated "
                     "result in the same laboratory."),
            authors=["Same Lab Author"],
            methodology="observational",
            source_type=SourceType.PAPER,
        )
        for index in range(3)
    ]
    phrases = L.repeated_phrases(rows, question="sleep and learning")
    assert "quantum dream resonance" not in phrases
    assert "dream resonance protocol" not in phrases
    corpus = L.lenses_from_sources(rows, question="sleep and learning")
    assert corpus["sources_seen"] == 3
    assert corpus["independent_families_seen"] == 1

    # A genuinely different lead group/method turns repetition into an
    # independent corpus signal.
    rows[-1].authors = ["Independent Group Author"]
    rows[-1].methodology = "experimental"
    assert "quantum dream resonance" in L.repeated_phrases(
        rows, question="sleep and learning")


def test_venue_ranking_counts_independent_families_not_same_lab_volume():
    rows = [
        SourceRecord(title=f"Echo {index}", url=f"https://z{index}.example/p",
                     authors=["Same Lab Author"], methodology="observational",
                     venue="Journal of Zeta Echo", source_type=SourceType.PAPER)
        for index in range(3)
    ]
    rows.extend([
        SourceRecord(title="Independent A", url="https://a.example/p",
                     authors=["Alpha Author"], methodology="experimental",
                     venue="Journal of Alpha Domain", source_type=SourceType.PAPER),
        SourceRecord(title="Independent B", url="https://b.example/p",
                     authors=["Beta Author"], methodology="observational",
                     venue="Journal of Alpha Domain", source_type=SourceType.PAPER),
    ])
    assert L.venue_disciplines(rows)[0] == "alpha domain"


def test_corpus_framework_trims_result_words_and_sub_phrases():
    phrases = L.repeated_phrases(_corpus_records(),
                                 question="neend kaise sudhare")
    # "reduced sustained attention" ka concept "sustained attention" hai
    assert "sustained attention" in phrases
    assert not any(phrase.startswith("reduced") for phrase in phrases)
    # "slow wave sleep" rakha gaya to "wave sleep"/"slow wave" dobara nahi
    assert "wave sleep" not in phrases
    assert "slow wave" not in phrases


def test_corpus_lens_makes_no_model_call():
    spy = _Spy()
    planner = ResearchPlanner()
    planner.lens_generate = spy
    planner.lens_plan("neend kaise sudhare")        # ye ek call (wired hai)
    before = spy.calls
    planner.absorb_corpus_lenses("neend kaise sudhare", _corpus_records())
    assert spy.calls == before, "corpus layer ne model call ki — quota khatam"


def test_corpus_lens_changes_next_round_queries():
    question = "neend kaise sudhare"
    planner = ResearchPlanner()
    plan_before = planner.lens_plan(question)
    before = planner.search_queries(question, plan_before, round_no=2)
    planner.absorb_corpus_lenses(question, _corpus_records())
    after = planner.search_queries(question, planner.lens_plan(question),
                                   round_no=2)
    assert after != before, "corpus lens se agli queries badli hi nahi"
    joined = " | ".join(after)
    assert "Matthew Walker" in joined


def test_corpus_lens_never_touches_scoring_or_verified():
    question = "neend kaise sudhare"
    base = L.build_lens_plan(question, base_query=question)
    merged = L.merge_corpus_lenses(
        base, L.lenses_from_sources(_corpus_records(), question=question))
    # scoring bilkul nahi hilti: apne hi retrieval ko inaam dena feedback loop
    # hai, aur ek run ke beech scoring badle to round-1/round-2 ke score
    # tulnaayog nahi rehte.
    assert L.scoring_query(merged) == L.scoring_query(base)
    assert "memory consolidation" not in L.scoring_vocabulary(merged)
    # aur lens ab bhi evidence NAHI hai
    assert merged["verified"] is False
    assert "not_citations" in merged["evidence_status"]
    assert merged["corpus_derived"] is True
    assert merged["corpus_sources_seen"] == 4
    assert merged["corpus_independent_families_seen"] == 4


def test_planner_scoring_anchor_survives_absorb():
    question = "दिमाग तेज कैसे करें"
    planner = ResearchPlanner()
    anchor_before = planner.plan(question,
                                 get_depth_config("QUICK"))["lens_scoring_query"]
    planner.absorb_corpus_lenses(question, _corpus_records())
    anchor_after = planner.plan(question,
                                get_depth_config("QUICK"))["lens_scoring_query"]
    assert anchor_after == anchor_before
    assert "cognitive" in (anchor_after or "")


def test_corpus_lens_survives_junk_records():
    class _Junk:
        pass
    plan = L.build_lens_plan("neend kaise sudhare")
    for bad in ([], None, [_Junk()], [None]):
        extra = L.lenses_from_sources(bad, question="neend kaise sudhare")
        merged = L.merge_corpus_lenses(plan, extra)
        assert merged["verified"] is False
    assert ResearchPlanner().absorb_corpus_lenses("x", None)["verified"] is False


def test_orchestrator_absorbs_corpus_lenses_between_rounds():
    """Live loop me absorb sach me chalta hai — sirf code me likha nahi hai.

    `_discover` ke andar network/LLM kuch nahi chahiye: discovery aur evidence
    dono stub hain, aur ginti dekhi jaati hai (raising stub chhup jaata,
    kyunki call try/except me hai).
    """
    from research_engine.orchestrator import DeepResearchEngine

    engine = DeepResearchEngine(enable_kg=False, enable_memory=False)
    records = _corpus_records()

    class _Pack:
        sources = records
        def document_sources(self):
            return []

    seen = {"absorb": 0, "given": None}
    original = engine.planner.absorb_corpus_lenses

    def spy_absorb(question, rows):
        seen["absorb"] += 1
        seen["given"] = list(rows)
        return original(question, rows)

    engine.planner.absorb_corpus_lenses = spy_absorb
    engine.discovery.discover = lambda **_kw: {
        "records": [], "log": [], "connectors_searched": ["openalex"],
        "seen_urls": set()}
    engine.evidence.build_pack = lambda **_kw: _Pack()
    engine.evidence.needs_another_round = lambda *_a, **_k: {"sufficient": False}

    config = get_depth_config("STANDARD")
    plan = engine.planner.plan("neend kaise sudhare", config)
    out = engine._discover("neend kaise sudhare", plan, config, [])

    assert out["rounds_run"] >= 2, out["rounds_run"]
    # aakhri round ke baad absorb nahi hota (agla round hi nahi hai)
    assert seen["absorb"] == out["rounds_run"] - 1, seen["absorb"]
    assert seen["given"] == records
