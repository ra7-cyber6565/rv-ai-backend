"""FACET layer ke tests — ek bada sawaal = kai alag research sawaal (#98).

Naapi hui bimari jiske liye ye layer bani: 1617-token wale sawaal par
`relevance.topic_of()` sirf wahi aath shabd nikaalta tha jo har section me the
(model, consciousness, reality, human...), aur 15 sahi sources me se 11 ka
relevance 0.000 aa gaya. Facet layer sawaal ko uske apne dhaanche se hisson me
todti hai aur har hisse ki apni query banati hai.

Ye file teen baat pin karti hai:

  1. **Koi list nahi.** Har faisla bhasha ke dhaanche se hota hai (nayi line,
     numbered heading, vaakya, shabd ki lambai, kitne hisson me aaya). Isliye
     fixture me jaan-boojh kar aise shabd hain jo kisi list me nahi likhe
     ja sakte (neuroplasticity, individuation, freemasonry, dopamine-driven).
  2. **Chhote sawaal par NO-OP.** `MIN_QUESTION_TOKENS` se chhote sawaal par
     facet layer bilkul chalti hi nahi — purana behaviour jaisa ka waisa.
  3. **Sawaal ka nirdesh/nishedh query me nahi jaata.** "do not treat 'CIA
     investigated X' as 'CIA proved X'" se koi search query nahi banti.

Aur ek honesty pin: facet ek SEARCH PLAN hai, evidence nahi — `summary()` me
`model_used` False rehta hai aur note me saaf likha hota hai.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import facets as F                # noqa: E402
from research_engine.planner import ResearchPlanner    # noqa: E402


# Chaar numbered section + ek prastaavna. Heading ke neeche ki lines usi section
# ki hain (sticky heading), isliye 5 hisse bante hain.
BIG_Q = """Grand question: har hisse par alag research chahiye systematically.
1. Consciousness aur brain ka rishta: neuroplasticity ke saboot dekho aur
   individuation ki prakriya samjhao. Consciousness ke model ki tulna karo.
2. Secret societies aur power: freemasonry ka documented history dekho, aur
   "secret societies power networks" par kya likha gaya hai wo batao.
3. Dopamine aur attention: dopamine-driven feedback loops kaise short-term
   gratification banate hain, aur long-term meaning-making par kya asar hai.
   Dopamine ka asar dopamine ke apne circuit par bhi dekho.
4. Evidence standard: examine whether you must not treat "CIA investigated X"
   as "CIA proved X". Har claim ke saath evidence ka level likho.
"""

SHORT_Q = "dopamine aur attention ka rishta kya hai"


def _facet(key: str):
    for facet in F.build(BIG_Q):
        if facet.key == key:
            return facet
    raise AssertionError(f"facet {key} bana hi nahi")


# ------------------------------------------------------------- segmentation

def test_sticky_heading_keeps_a_section_together():
    """Heading ke neeche ki lines usi section ki hain — warna ek section do
    facet me tootta hai aur uske pehchaan-shabd alag ho jaate hain."""
    parts = F.segments(BIG_Q)
    assert len(parts) == 5
    dopamine_part = [p for p in parts if "dopamine-driven" in p]
    assert len(dopamine_part) == 1
    # teeno line ek hi hisse me: heading + do line
    assert "circuit" in dopamine_part[0] and "meaning-making" in dopamine_part[0]


def test_single_paragraph_question_is_split_on_sentences():
    """Jab koi seema hi nahi di gayi (ek hi paragraph), tab vaakya seema hai."""
    one_line = " ".join(
        [f"Sentence {i} me neuroplasticity aur dopamine ka rishta samjhao "
         f"aur individuation ki prakriya par saboot dekho." for i in range(6)])
    parts = F.segments(one_line)
    assert len(parts) > 1, "ek hi paragraph par bhi hisse banne chahiye"


def test_short_question_is_a_complete_no_op():
    assert F.build(SHORT_Q) == ()
    assert F.facet_queries(SHORT_Q) == []
    assert F.facet_terms(SHORT_Q) == []


def test_token_floor_decides_even_when_the_question_has_many_lines():
    """Sirf "kitne hisse" kaafi nahi — chhote sawaal par facet layer chalni hi
    nahi chahiye, warna 15-token sawaal bhi teen query me tootne lagta hai."""
    tiny = ("dopamine ka asar kya hai\nattention ka rishta kya hai\n"
            "neuroplasticity ke saboot dekho zara")
    assert len(F.segments(tiny)) >= 2
    assert len(F.tokens(tiny)) < F.MIN_QUESTION_TOKENS
    assert F.build(tiny) == ()


# ------------------------------------------------------------------- terms

def test_scaffold_words_never_become_terms():
    """"examine", "whether", "must", "systematically" nirdesh ke shabd hain —
    inse banayi query search engine ko koi topic nahi deti."""
    everything = {t for facet in F.build(BIG_Q) for t in facet.terms}
    for junk in ("examine", "whether", "must", "systematically", "following"):
        assert junk not in everything, f"scaffold term ban gaya: {junk}"


def test_hyphen_parts_become_their_own_terms():
    """Source me "dopamine" hyphen ke bina likha hota hai, isliye compound ke
    hisse bhi apne term bante hain."""
    terms = _facet("f4").terms
    assert "dopamine-driven" in terms
    assert "dopamine" in terms and "driven" in terms


def test_repeated_word_outranks_a_once_seen_word():
    """tf ka kaam: jo shabd hissa khud dohra raha hai wahi us hisse ka vishay
    hai. Dono par morphology boost barabar hai (dopamine hyphen-compound se,
    gratification "-ation" se), isliye faisla sirf ginti karti hai."""
    terms = list(_facet("f4").terms)
    assert terms.index("dopamine") < terms.index("gratification")


def test_strong_terms_need_length_concept_shape_and_low_df():
    """STRONG = akele match par bharosa. Chaar shart ek saath."""
    strong = set(_facet("f2").strong)
    assert "neuroplasticity" in strong and "individuation" in strong
    # chhota shabd strong nahi ban sakta (Zipf: chhota shabd aam bhasha ka hai)
    assert "brain" not in strong and "model" not in strong
    # discourse shabd kabhi strong nahi — har field ke abstract me aata hai
    assert "evidence" not in set(_facet("f5").strong)
    for facet in F.build(BIG_Q):
        for term in facet.strong:
            assert len(term) >= F.STRONG_TERM_MIN_LEN
            assert not F.is_discourse_word(term)
            assert facet.df_of(term) <= F.STRONG_MAX_DF


def test_a_word_in_four_sections_is_not_strong_even_if_it_looks_specialist():
    """STRONG ka df cap alag se naapa gaya: 13-section wale sawaal me
    structural cut 4 hai, isliye chaar hisson me aaya lamba concept-shabd terms
    me bacha rehta hai — par uska AKELA match kaafi nahi maana ja sakta, warna
    bilkul alag field ka paper andar aa jaata hai (naapa gaya: "information" 7
    hisson me tha aur usi ke akele match par gearbox ka paper 0.355 pa gaya)."""
    sections = []
    for i in range(1, 14):
        extra = "Neuroplasticity ke saboot dekho." if i <= 4 else ""
        sections.append(f"{i}. Section {i}: zeta{i}alpha, zeta{i}beta tatha "
                        f"zeta{i}gamma ke baare me batao. {extra}")
    facets = [f for f in F.build("\n".join(sections))
              if "neuroplasticity" in f.terms]
    assert facets, "chaar hisson wala shabd terms me rehna chahiye"
    for facet in facets:
        assert facet.df_of("neuroplasticity") > F.STRONG_MAX_DF
        assert "neuroplasticity" not in facet.strong


def test_structural_word_is_dropped_from_facets():
    """Jo shabd bahut hisson me hai wo sawaal ka DHAANCHA hai, kisi ek hisse ki
    pehchaan nahi — usko facet ke terms se nikaal diya jaata hai."""
    repeated = "\n".join(
        [f"{i}. Section {i}: consciousness ka model dekho aur zeta{i}alpha, "
         f"zeta{i}beta tatha zeta{i}gamma ke saboot par baat karo."
         for i in range(1, 8)])
    every = [set(f.terms) for f in F.build(repeated)]
    assert len(every) >= 4
    holds = sum(1 for terms in every if "consciousness" in terms)
    assert holds == 0, "har hisse me aane wala shabd pehchaan nahi ho sakta"
    # …aur us hisse ka apna shabd bacha rehna chahiye, warna filter ne sab kha liya
    assert any("zeta3alpha" in terms for terms in every)


# ----------------------------------------------------------- query safety

def test_query_safe_phrase_rejects_sentences_and_orders():
    assert F.is_query_safe_phrase("secret societies power networks") is True
    assert F.is_query_safe_phrase("quantum consciousness.") is False
    assert F.is_query_safe_phrase("your following task") is False
    assert F.is_query_safe_phrase(
        "one two three four five six seven eight") is False


def test_order_word_inside_a_phrase_kills_the_phrase():
    """Ek bhi nirdesh-shabd phrase ko aadesh bana deta hai — baaki shabd topic
    ke hon to bhi wo query me nahi jaana chahiye."""
    assert F.is_query_safe_phrase("dopamine circuit") is True
    assert F.is_query_safe_phrase("following dopamine circuit") is False


def test_single_letter_placeholder_is_not_a_query_phrase():
    """Naapa hua defect: lenses ka stopword set "x"/"y" ko bhi stopword maanta
    hai, isliye "CIA proved X" query me pahunch gaya tha — jabki is module ka
    wada ulta tha. Ek-akshar ka token placeholder hai; sirf asli connector
    ("a") chhoot paata hai."""
    assert F.is_query_safe_phrase("CIA proved X") is False
    assert F.is_query_safe_phrase("CIA investigated X") is False
    assert F.is_query_safe_phrase("a secret society network") is True


def test_no_facet_query_carries_a_placeholder_or_order():
    """End-to-end pin: nishedh-line se banne wali query kabhi search me nahi."""
    for query in F.facet_queries(BIG_Q, limit=F.MAX_FACETS):
        words = query.split()
        assert words, "khaali query nahi jaani chahiye"
        for word in words:
            assert len(word) > 1 or word.casefold() == "a", \
                f"placeholder query me: {query}"
        assert "examine" not in query and "whether" not in query


def test_facet_query_puts_topic_words_before_process_words():
    """Facet.query() me discourse/aam shabd baad me aate hain — "evidence
    investigated" se shuru hone wali query kisi topic ko nahi dhoondhti."""
    facet = _facet("f2")
    query = facet.query()
    assert query.split()[0] == "consciousness"
    words = _facet("f5").query().split()
    discourse = [i for i, w in enumerate(words) if F.is_discourse_word(w)]
    topics = [i for i, w in enumerate(words) if not F.is_discourse_word(w)]
    if discourse and topics:
        assert min(topics) < max(discourse)


def test_facets_are_deterministic_across_cache_clear():
    """Cache hone ke baad bhi wahi jawab — koi hidden state nahi."""
    first = [f.to_dict() for f in F.build(BIG_Q)]
    F.build.cache_clear()
    assert [f.to_dict() for f in F.build(BIG_Q)] == first


def test_summary_is_a_plan_not_evidence():
    info = F.summary(BIG_Q)
    assert info["model_used"] is False
    assert info["method"] == "deterministic_segment_idf"
    assert info["count"] == len(F.build(BIG_Q))


# --------------------------------------------------------- planner wiring

def test_rounds_rotate_over_facets_without_repeating():
    planner = ResearchPlanner()
    first = planner.facet_search_queries(BIG_Q, round_no=1)
    second = planner.facet_search_queries(BIG_Q, round_no=2)
    assert first and second
    assert len(first) == planner.FACET_QUERIES_PER_ROUND
    assert not (set(first) & set(second)), "ek hi query do round me gayi"
    assert set(first) | set(second) <= set(F.facet_queries(BIG_Q, limit=99))


def test_round_beyond_the_last_facet_wraps_instead_of_dying():
    planner = ResearchPlanner()
    late = planner.facet_search_queries(BIG_Q, round_no=99)
    assert late, "round 99 par bhi kuch query jaani chahiye"
    assert set(late) <= set(F.facet_queries(BIG_Q, limit=99))


def test_facet_budget_follows_depth():
    """QUICK par fan-out nahi (jawab turant chahiye), gehre mode me poora sawaal."""
    planner = ResearchPlanner()
    got = {name: planner.facet_round_budget({"depth": {"name": name}})
           for name in ("QUICK", "STANDARD", "DEEP", "MAXIMUM", "MARATHON")}
    assert got == {"QUICK": 1, "STANDARD": 2, "DEEP": 3,
                   "MAXIMUM": 4, "MARATHON": 4}
    assert planner.facet_round_budget(None) == planner.FACET_QUERIES_PER_ROUND
    assert planner.facet_round_budget({"depth": {"name": "kuch-bhi"}}) == \
        planner.FACET_QUERIES_PER_ROUND


def test_planner_is_a_no_op_on_short_questions():
    planner = ResearchPlanner()
    assert planner.facet_search_queries(SHORT_Q, round_no=1) == []
    assert planner.facet_search_queries("", round_no=1) == []
