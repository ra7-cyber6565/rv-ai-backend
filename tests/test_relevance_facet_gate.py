"""Anchor-proximity + FOCUS guard + facet gate ke tests (#98 ka teesra hissa).

Teen parat, ek hi naapi hui bimari se:

  * **Anchor proximity** (`domain.StemBag` / `phrase_hit`) — 1617-token wale
    sawaal me "theories of language" aur "causal model" alag-alag jagah the,
    aur cs_ml ka do-shabd anchor "language model" HIT ho gaya. Usi ek jhoothe
    hit se poora sawaal strict "computer science" ban gaya.
  * **FOCUS guard** (`domain_focus_guard`) — 349-token sawaal me akela shabd
    "vibration" (jo wahan *spiritual claim* ke context me tha) poore sawaal ko
    strict `engineering` bana deta tha: search intent "vibration based
    condition monitoring bearing", gearbox ka paper 0.473 par top, aur Jung/
    attention/CIA ke sahi papers 0.000.
  * **Facet gate** (`relevance.facet_match`) — hissa-wise match se score UTHTA
    hai, isliye uthane ki shart sakht hai: do alag SAAF shabd poore mile, ya
    ek STRONG shabd. Warna gearbox ka paper "based + interpretation" par 0.355
    pa gaya tha (dono shabd snippet ke boilerplate se, root-guess par).

Do baatein jaan-boojh kar pin ki gayi hain:

  1. **Contrast pair se hi maap.** Har niyam ke do roop test hote hain — ek
     jisme wo niyam FAIL karta hai aur ek jisme PASS, sirf usi ek farak ke
     saath. Isse ye pata chalta hai ki faisla usi niyam ne liya, kisi doosre
     rule ne nahi.
  2. **Facet sirf score UTHATA hai, kisi gire hue source ko zinda nahi karta.**
     Hard-rejected source par facet compute hi nahi hota.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import domain as D                    # noqa: E402
from research_engine import domain_focus_guard as G        # noqa: E402
from research_engine import facets as F                    # noqa: E402
from research_engine.models import SourceRecord, SourceType  # noqa: E402
from research_engine.query_builder import is_generic_word  # noqa: E402
from research_engine.relevance import RelevanceEngine      # noqa: E402
from research_engine.source_kind import classify as classify_kind  # noqa: E402

# ---------------------------------------------------------------- fixtures

# Chaar numbered section — har hisse ka apna pehchaan-shabd.
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

# Q1 ki bimari ka chhota roop: 57 token, aur poore sawaal me `engineering` ka
# sirf ek nishaan — "vibration" — wo bhi spiritual daave ke context me.
INCIDENTAL_Q = (
    "Meri apni soch se batao ki log jab kehte hain ki sab kuch frequency aur "
    "vibration hai, to us daave ko kaise test kiya jaaye. Mann, dhyaan, aur "
    "aadmi ke andar ke badlaav ko samjhao, aur ye bhi likho ki is baat ka "
    "koi naapa hua saboot hai ya nahi, aur logon ne ye kahan se sikha.")

# Wahi sawaal + engineering ka ek SHARED anchor ("load"). Shared anchor profile
# khud "ye shabd doosre field bhi bolte hain" keh kar mark karta hai, isliye wo
# us field ka apna nishaan nahi gina jaata.
SHARED_ANCHOR_Q = INCIDENTAL_Q + " Aur dimag par pade load ka bhi zikr karo."

# Wahi akela nishaan, par chhote sawaal me — yahan wo shabd hi poora topic hai.
SHORT_INCIDENTAL = (
    "Log kehte hain sab kuch vibration hai — is daave ko kaise test karein, "
    "aur mann par kya asar padta hai?")

# Q2 ki bimari ka chhota roop: 137 token, `economics` ke sirf do nishaan
# ("market", "economic"), aur do doosre field ke trigger bhi maujood.
MULTI_Q = """Grand question: mujhe poora jawab chahiye, apni hi soch se, hissa-hissa karke.
1. Insaan ke mann aur dimag ka rishta: attention, yaadash aur aadat kaise bante hain,
   aur inhe badalne me kitna samay lagta hai.
2. Itihaas: puraane samaj me guru-shishya parampara se gyaan kaise aage badhta tha,
   aur uske likhit record aaj kahan milte hain.
3. Bazaar aur samaj: market me log kaise faisle lete hain, aur economic dabaav ka
   aam aadmi par kya asar padta hai.
4. Sehat: dhyaan karne wale patients ke lakshan me kya badlaav dikhta hai.
5. Ganit aur computer: neural network se inhe naapne ki koshish kahan tak theek hai.
6. Evidence ka standard: har dave ke saath saboot ka level likho, aur jo cheez naapi
   nahi ja sakti usko saaf alag rakho, aur kahan se aaya wo bhi batao zaroor.
"""

# MULTI_Q ke teen variant — har ek me sirf EK paimana badalta hai.
MULTI_SHORT = """Chhota roop: market me log kaise faisle lete hain aur economic dabaav ka
aam aadmi par kya asar padta hai. Dhyaan karne wale patients ke lakshan me kya
badlaav dikhta hai, aur neural network se inhe naapna kahan tak theek hai.
"""
MULTI_NO_RIVALS = MULTI_Q.replace("patients", "logon").replace(
    "neural network", "ganit ke tarike")
MULTI_MORE_SIGNALS = MULTI_Q.replace(
    "aam aadmi par kya asar padta hai",
    "inflation aur unemployment par kya asar padta hai, aur GDP growth kaise "
    "badalti hai")

FOCUSED_Q = ("Kya room-temperature superconductivity ambient pressure par "
             "possible hai? Kaun se hydrides ka critical temperature sabse "
             "zyada hai?")


def _raw_plan(question: str):
    """Guard lagne se PEHLE ka faisla — `install()` ne `detect` badal diya hai."""
    return G._PREVIOUS(question)


def _rec(title: str, snippet: str = "", url: str = "https://arxiv.org/abs/1",
         connector: str = "arxiv", stype: SourceType = SourceType.PAPER,
         peer: bool = True) -> SourceRecord:
    s = SourceRecord(title=title, snippet=snippet, url=url, connector=connector,
                     source_type=stype, year=2023, peer_reviewed=peer)
    kv = classify_kind(title=s.title, snippet=s.snippet, url=s.url,
                       connector=s.connector, venue=s.venue,
                       publisher=s.publisher, doi=s.doi,
                       peer_reviewed=s.peer_reviewed)
    s.doc_kind, s.doc_kind_label = kv.kind, kv.label
    s.doc_kind_confidence = kv.confidence
    return s


def _match(title: str, body: str = "", question: str = BIG_Q):
    return RelevanceEngine().facet_match(_rec(title, body), question)


# ------------------------------------------------------ anchor ki proximity

def test_stems_carry_the_token_order_and_hyphen_parts():
    """`stems()` set ke saath KRAM bhi laata hai — proximity isi par chalti hai."""
    bag = D.stems("room-temperature language models are here")
    assert isinstance(bag, D.StemBag)
    assert {"room", "temperature", "language", "model"} <= set(bag)
    assert bag.seq[0] == "room-temperature"
    assert bag.seq.index("language") < bag.seq.index("model")


LONG_FAR = ("alpha beta gamma " * 20) + " language " + ("delta epsilon zeta " * 20) + " model "
LONG_NEAR = ("alpha beta gamma " * 30) + " language model " + ("delta epsilon " * 10)
SHORT_FAR = "language " + ("alpha beta " * 10) + " model"


def test_far_apart_words_do_not_make_a_two_word_anchor_hit():
    """Lambe text me dono shabd hone ka matlab wo PHRASE hona nahi hai."""
    bag = D.stems(LONG_FAR)
    assert len(bag.seq) > D._PROXIMITY_MIN_TOKENS
    assert {"language", "model"} <= set(bag)
    assert D.phrase_hit("language model", bag) is False


def test_the_same_two_words_close_together_still_hit():
    """Contrast pair — sirf ek farak: shabd paas-paas hain."""
    bag = D.stems(LONG_NEAR)
    assert len(bag.seq) > D._PROXIMITY_MIN_TOKENS
    assert D.phrase_hit("language model", bag) is True


def test_short_text_keeps_the_old_set_membership_behaviour():
    """Chhote text par proximity ki shart hi nahi lagti — purane benchmark
    (superconductivity 156, cross-domain 649) isi wajah se hile nahi."""
    bag = D.stems(SHORT_FAR)
    assert len(bag.seq) <= D._PROXIMITY_MIN_TOKENS
    assert D.phrase_hit("language model", bag) is True


def test_single_word_anchor_never_asks_for_proximity():
    bag = D.stems(LONG_FAR)
    assert D.phrase_hit("language", bag) is True
    assert D.phrase_hit("kangaroo", bag) is False


def test_phrase_whose_words_share_one_stem_is_a_single_lookup():
    """"model models" do shabd hain par ek hi stem — ismein doori ka sawaal
    hi nahi banta."""
    bag = D.stems(LONG_FAR)
    assert D.phrase_hit("model models", bag) is True


def test_a_plain_set_caller_is_not_changed_by_this_layer():
    """Jo caller apna saada `set` deta hai uska raasta bilkul purana hai."""
    assert D.phrase_hit("language model", {"language", "model"}) is True
    assert D.phrase_hit("language model", {"language"}) is False


def test_count_hits_and_matched_read_the_same_verdict():
    bag = D.stems("neuroplasticity and dopamine circuits in the brain")
    needles = ["dopamine circuit", "freemasonry", "brain"]
    assert D.matched(needles, bag) == ["dopamine circuit", "brain"]
    assert D.count_hits(needles, bag) == 2


# ------------------------------------------------------------- FOCUS guard

def test_one_incidental_signal_in_a_long_question_is_demoted():
    """Naapi hui Q1 bimari: 57-token sawaal, `engineering` ka sirf ek nishaan."""
    plan = _raw_plan(INCIDENTAL_Q)
    assert plan.key == "engineering" and plan.strict is True
    verdict = G.focus_verdict(INCIDENTAL_Q, plan)
    assert verdict["demote"] is True
    assert verdict["signals"] == 1
    assert verdict["tokens"] >= G._INCIDENTAL_MIN_TOKENS
    assert "vibration" in verdict["reason"]


def test_the_same_single_signal_survives_in_a_short_question():
    """Contrast pair: wahi akela shabd, sirf sawaal chhota — "LK-99 ka Tc kitna
    hai?" jaise sawaal me ek anchor hi poora topic hota hai."""
    plan = _raw_plan(SHORT_INCIDENTAL)
    verdict = G.focus_verdict(SHORT_INCIDENTAL, plan)
    assert verdict["signals"] == 1
    assert verdict["tokens"] < G._INCIDENTAL_MIN_TOKENS
    assert verdict["demote"] is False


def test_a_long_multi_domain_question_belongs_to_no_single_field():
    """Naapi hui Q2 bimari: 137 token, `economics` ke do nishaan, do rival."""
    plan = _raw_plan(MULTI_Q)
    assert plan.key == "economics" and plan.strict is True
    verdict = G.focus_verdict(MULTI_Q, plan)
    assert verdict["demote"] is True
    assert verdict["tokens"] >= G._LONG_QUESTION_TOKENS
    assert verdict["signals"] <= G._WEAK_SIGNALS_IN_LONG
    assert verdict["rivals"] >= G._MULTI_DOMAIN_RIVALS


def test_the_same_signals_in_a_shorter_question_keep_the_field():
    """Sirf lambai ka farak — 41 token par ye parat lagti hi nahi."""
    verdict = G.focus_verdict(MULTI_SHORT, _raw_plan(MULTI_SHORT))
    assert verdict["signals"] == 2 and verdict["rivals"] >= 2
    assert verdict["tokens"] < G._LONG_QUESTION_TOKENS
    assert verdict["demote"] is False


def test_enough_signals_defend_the_field_even_in_a_long_question():
    """Sirf nishaan ka farak — inflation/unemployment/GDP jud gaye."""
    verdict = G.focus_verdict(MULTI_MORE_SIGNALS, _raw_plan(MULTI_MORE_SIGNALS))
    assert verdict["tokens"] >= G._LONG_QUESTION_TOKENS
    assert verdict["signals"] > G._WEAK_SIGNALS_IN_LONG
    assert verdict["demote"] is False


def test_without_other_fields_trigger_a_long_question_keeps_its_field():
    """Sirf rival ka farak — patients/neural network hata diye."""
    verdict = G.focus_verdict(MULTI_NO_RIVALS, _raw_plan(MULTI_NO_RIVALS))
    assert verdict["tokens"] >= G._LONG_QUESTION_TOKENS
    assert verdict["rivals"] < G._MULTI_DOMAIN_RIVALS
    assert verdict["demote"] is False


def test_shared_anchors_do_not_count_as_the_fields_own_signal():
    """"load" engineering ka anchor hai, par profile khud use SHARED batata hai
    — aisa shabd milne se sawaal us field ka nahi ho jaata."""
    plan = _raw_plan(SHARED_ANCHOR_Q)
    bag = D.stems(SHARED_ANCHOR_Q)
    assert "load" in D.matched(plan.profile.anchors, bag)
    assert "load" in [a.casefold() for a in plan.profile.shared_anchors]
    verdict = G.focus_verdict(SHARED_ANCHOR_Q, plan)
    assert verdict["matched_exclusive_anchors"] == ["vibration"]
    assert verdict["signals"] == 1
    assert verdict["demote"] is True


def test_a_question_with_no_field_needs_no_verdict():
    plan = _raw_plan("aaj mausam kaisa rahega bhai")
    assert plan.is_known is False
    verdict = G.focus_verdict("aaj mausam kaisa rahega bhai", plan)
    assert verdict["demote"] is False
    assert verdict["reason"] == "koi field profile match hi nahi hua"


def test_demoting_means_generic_not_a_hard_reject():
    """Demote ka matlab "is sawaal ka koi ek field nahi" hai — routing band
    nahi hoti, sirf strict hard-reject hat jaata hai. Aur jo field chhoota,
    wo rival ke roop me record rehta hai (chup-chaap gayab nahi hota)."""
    plan = G.guarded_detect(INCIDENTAL_Q)
    assert plan.key == D.GENERIC.key
    assert plan.strict is False
    assert plan.confidence == 0
    assert plan.focus_keys == ()
    assert "engineering" in [r.key for r in plan.rivals]


def test_a_focused_question_passes_straight_through():
    """Control: chhote, focused sawaal is parat se bilkul achhoote hain."""
    plan = G.guarded_detect(FOCUSED_Q)
    assert plan.key == "superconductivity"
    assert plan.strict is True


def test_install_is_idempotent_and_never_wraps_itself():
    """Do baar install() hone par recursion ban sakti thi — flag isi ke liye hai."""
    assert getattr(D, G._INSTALLED_FLAG, False) is True
    before = G._PREVIOUS
    G.install()
    assert D.detect is G.guarded_detect
    assert G._PREVIOUS is before
    assert G._PREVIOUS is not G.guarded_detect


# ------------------------------------------------------------- facet gate

def test_two_clean_exact_terms_open_the_gate():
    got = _match("Dopamine and gratification in reward circuits")
    assert got["key"] == "f4"
    assert got["score"] > 0.0
    assert {"dopamine", "gratification"} <= set(got["terms"])


def test_a_single_solid_term_is_not_enough():
    """Contrast pair — ek hi shabd jodne se faisla palta hai. Akela "circuit"
    kisi bhi mechanical paper me mil jaata hai, isliye wo saboot nahi."""
    assert _match("Helical gearbox circuit design")["score"] == 0.0
    assert _match("Helical gearbox circuit feedback design")["score"] > 0.0


def test_one_strong_term_alone_is_enough():
    """"individuation" jaisa shabd ittefaq se doosre field me nahi aata."""
    got = _match("Individuation in adult life")
    assert got["terms"] == ["individuation"]
    assert got["score"] > 0.0
    assert "individuation" in dict(
        (f.key, f.strong) for f in F.build(BIG_Q))["f2"]


def test_root_guess_helps_reading_but_never_opens_the_gate():
    """`_facet_terms_found` andaaza lagata hai ("neuroplastic" ←
    "neuroplasticity"), par gate sirf POORE mile shabd ginta hai — wahi andaaza
    research snippet ke aam boilerplate se bhi lag jaata hai."""
    engine = RelevanceEngine()
    terms = ("neuroplasticity", "consciousness")
    root_text = "neuroplastic changes and conscious control in rats"
    assert engine._facet_terms_found(terms, root_text) == list(terms)
    assert engine._facet_exact_found(terms, root_text) == []
    # end-to-end: sirf root-guess par match = koi lift nahi
    assert _match("Neuroplastic changes and conscious control")["score"] == 0.0
    # …aur poore shabd likhe hon to wahi source lift paata hai
    assert _match("Neuroplasticity and consciousness control")["score"] > 0.0


class _StubFacet:
    """Sirf `strong` chahiye — gate ka faisla isi par tikta hai."""

    def __init__(self, strong=()):
        self.strong = tuple(strong)


def test_generic_and_discourse_words_cannot_open_the_gate():
    """Naapa gaya defect: gearbox ka paper "based + interpretation" par 0.355
    pa gaya tha. "level" aam shabd hai aur "evidence" har field ke abstract me
    aata hai — do aise shabd milkar bhi ek nahi ginte."""
    engine = RelevanceEngine()
    assert is_generic_word("level") is True
    assert F.is_discourse_word("evidence") is True
    assert engine._facet_gate_ok(_StubFacet(), ["level", "evidence"]) is False
    assert engine._facet_gate_ok(_StubFacet(), ["level", "dopamine"]) is False
    assert engine._facet_gate_ok(_StubFacet(), ["dopamine", "circuit"]) is True
    # ek STRONG shabd akela chalta hai, aur wo chhoot sirf strong par hai
    assert engine._facet_gate_ok(
        _StubFacet(["neuroplasticity"]), ["neuroplasticity"]) is True
    assert engine._facet_gate_ok(_StubFacet(["individuation"]), ["dopamine"]) is False


def test_title_terms_weigh_more_than_body_terms():
    """Shirshak me shabd hona zyada matlab rakhta hai (0.65 vs 0.35) — snippet
    ke boilerplate se hone wale match ko poora credit nahi milta."""
    in_title = _match("Dopamine and gratification", "")
    in_body = _match("A completely unrelated header here",
                     "Dopamine and gratification are discussed")
    assert in_title["terms"] == in_body["terms"]
    assert in_title["lexical"] > in_body["lexical"]
    assert in_title["score"] > in_body["score"]


def test_a_full_multi_word_phrase_earns_a_bonus():
    """Sawaal me jo phrase user ne khud quote kiya, wo POORA milna alag baat
    hai — wahi shabd bikhre hue milne se zyada."""
    whole = _match("Secret societies power networks and freemasonry history")
    scattered = _match(
        "Secret societies and their power inside freemasonry networks history")
    assert whole["phrase"] == "secret societies power networks"
    assert scattered["phrase"] == ""
    assert whole["terms"] == scattered["terms"]
    base = whole["lexical"] * 0.55 + whole["semantic"] * 0.45
    assert whole["score"] >= round(base, 4) + 0.09
    assert whole["score"] > scattered["score"]


def test_a_short_question_has_no_facets_at_all():
    """Facet layer chhote sawaal par NO-OP hai — tab `facet_match` khaali dict
    deta hai, zero-shape nahi (kuch naapa hi nahi gaya)."""
    assert _match("dopamine reward", "", question="dopamine kya hai") == {}


def test_no_match_returns_an_honest_zero_shape():
    """Match na hone par bhi ye batata hai ki kitne hisse dekhe gaye the."""
    got = _match("Helical gearbox lubrication and bearing wear")
    assert got["score"] == 0.0
    assert got["terms"] == [] and got["matched_terms"] == 0
    assert got["key"] == "" and got["label"] == ""
    assert got["facet_count"] == len(F.build(BIG_Q))


def test_facet_cache_is_bounded_and_matches_a_fresh_build():
    """Cache sirf raftaar ke liye hai — jawab wahi rehta hai jo taaza build se
    aata, aur 40 alag sawaal ke baad bhi memory nahi bhagti."""
    engine = RelevanceEngine()
    template = (
        "Section {i}: mujhe is hisse par poora research chahiye, aur har claim "
        "ke saath saboot ka level likho, taaki baad me koi shaq na rahe, aur ye "
        "bhi batao ki neuroplasticity par kaun kaun se prayog hue hain aur unka "
        "nateeja kya nikla, aur individuation ki prakriya me kya farak aaya, aur "
        "dopamine-driven loops ka asar kitna naapa gaya tha zaroor likho abhi.")
    biggest = 0
    for i in range(40):
        engine.facets_of(template.format(i=i))
        biggest = max(biggest, len(engine._facet_cache))
    assert biggest <= 17, f"cache bandh nahi hui: {biggest}"
    one = template.format(i=1)
    assert engine.facets_of(one) is engine.facets_of(one)
    assert engine.facets_of(one) == F.build(engine.expanded_query(one))


def test_two_questions_with_the_same_opening_get_their_own_facets():
    """Cache key poora sawaal padhta hai — sirf shuruaat dekhne se do alag
    sawaal ek doosre ka plan chura lete."""
    engine = RelevanceEngine()
    head = ("Section ek: mujhe is hisse par poora research chahiye aur har claim "
            "ke saath saboot ka level likho, taaki baad me koi shaq na rahe, aur "
            "jitna mila hai utna hi likho, apni taraf se kuch mat jodo, phir aage "
            "badho. ")
    q_mind = head + ("Ab neuroplasticity ke prayog aur individuation ki prakriya "
                     "par kya kya likha gaya hai wo saaf batao, dopamine circuit "
                     "feedback aur attention training ke natije bhi jodo, aur "
                     "kaun sa prayog kitne logon par hua wo likho.")
    q_power = head + ("Ab freemasonry ke documented history aur secret societies "
                      "power networks par kya likha gaya hai wo saaf batao, unke "
                      "charter aur membership record bhi jodo, aur kaun sa dawa "
                      "kis dastavez se aaya wo likho.")
    first = engine.facets_of(q_mind)
    second = engine.facets_of(q_power)
    assert first != second
    assert second == F.build(engine.expanded_query(q_power))


def test_changing_the_scoring_anchor_clears_the_facet_cache():
    """Anchor badalne se sawaal ka scoring-roop badal jaata hai — purane hisse
    reuse karna chup-chaap galat jawab hota."""
    engine = RelevanceEngine()
    engine.facets_of(BIG_Q)
    assert engine._facet_cache
    engine.set_scoring_anchor("consciousness attention research")
    assert engine._facet_cache == {}
    assert engine.expanded_query(BIG_Q) != BIG_Q
    # wahi anchor dobara set karne par kuch nahi hota (bekaar cache-clear nahi)
    engine.facets_of(BIG_Q)
    engine.set_scoring_anchor("consciousness attention research")
    assert engine._facet_cache


def test_facet_lift_is_discounted_below_the_facet_score():
    """Hissa poore sawaal ke barabar nahi maana jaata — lift par discount lagta
    hai, aur `relevance_parts` me dono number alag-alag likhe rehte hain."""
    engine = RelevanceEngine()
    s = _rec("Secret societies power networks: freemasonry documented history",
             "We analysed 1200 records of freemasonry lodges and measured "
             "network density of 0.34 across 40 cities.")
    score = engine.score_relevance(s, BIG_Q)
    parts = s.relevance_parts
    facet_score = parts["facet"]["score"]
    assert facet_score > 0.0
    assert parts["facet_lift"] == round(facet_score * engine._FACET_DISCOUNT, 4)
    assert parts["facet_lift"] < facet_score
    assert score >= parts["facet_lift"]


def test_a_hard_rejected_source_is_never_revived_by_a_facet():
    """Sabse zaroori pin: jo source domain/subject/no-data gate se gir gaya, wo
    gira hi rehta hai — chahe uske title me sawaal ke shabd bhare hon."""
    engine = RelevanceEngine()
    s = _rec("A blog opinion: consciousness is just neuroplasticity vibes",
             "no numbers here, just my personal individuation take",
             url="https://blog.test/x", connector="web", stype=SourceType.WEB,
             peer=False)
    assert engine.score_relevance(s, BIG_Q) == 0.0
    parts = s.relevance_parts
    assert parts["hard_rejected"] is True
    assert parts.get("facet") is None
    assert not parts.get("facet_lift")
    assert [r["code"] for r in parts["rejections"]] == ["NO_DATA_WEB"]
    # …jabki wahi title facet gate akele paar kar leta hai — yaani rok gate ki hai
    assert _match("Consciousness and neuroplasticity")["score"] > 0.0
