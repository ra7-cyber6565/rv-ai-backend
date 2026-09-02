"""Naam-aur-kriti filter ke tests (#97/F5 ka pinning, #98).

intel ki shart: "m kaise bhi question puch skta hu ... agar mene naam naa bhi
de rkaha ho to bhi wo soche khud se". Iska matlab do taraf ki zimmedari hai:

  1. Jo naam/kriti intel ne KABHI nahi bataye, wo bhi pakde jaayein
     (Marcus Aurelius, Ibn Khaldun, Kojiki, Muqaddimah, Tao of Physics).
  2. Sawaal ke TUKDE naam/kriti na banein — "CIA investigated X", "Human
     Reality", "Mandatory Evidence Standard", "consciousness-and",
     "frequency/vibration" — kyunki inse search query banti thi aur quota bhi
     jaata tha, aur galat lane bhi khulti thi.

Har faisla bhasha ke DHAANCHE se hota hai (case-consistency, determiner,
suffix, sawaal-shabd, hyphen ka adhoora hissa, quote-span), kisi topic/kitab/
vyakti ki list se NAHI. Isliye yahan jaan-boojh kar aise naam use hue hain jo
kisi list me nahi likhe ja sakte.

Honesty pin: ye sirf SEARCH lens hai. Naam mil jaana evidence nahi hai, aur
inse koi claim nahi banti — wo kaam claim_labels/claim_verification ka hai.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import classics as C   # noqa: E402
from research_engine import lenses as L     # noqa: E402


# Ek lamba, heading-bhara sawaal — intel ke Grand-Unified sawaal ka chhota
# roop. Isme jaan-boojh kar wo saari bimariyan hain jo probe me naapi gayi thin.
LONG_Q = """Final Challenge
The Grand Unified Human Reality Problem
Person A ke paas 20 saal hai. Human reality aur inner reality ko examine karo.
Mandatory Evidence Standard follow karna hai: mere paas evidence hona chahiye.
Carl Jung ne shadow ke baare me likha, aur Neville Goddard's imagination
theory bhi dekho. Yaad rakho: CIA investigated X ka matlab CIA proved X. nahi.
consciousness-and-vibration jaise dangling shabd search me nahi jaane chahiye.
Psycho-Cybernetics book bhi padho. frequency/vibration ka dava mat karo.
"""


# ---------------------------------------------------------------- person names

def test_name_plus_work_run_keeps_only_the_person():
    """"Marcus Aurelius Meditations" → vyakti "Marcus Aurelius", kriti alag."""
    got = L._person_name_from_run(
        "Marcus Aurelius Meditations",
        "Explain Marcus Aurelius Meditations ka saar", False,
        prev_word="Explain")
    assert got == "Marcus Aurelius"


def test_three_word_heading_is_not_a_person():
    """"New World Order" heading hai — teesra shabd kriti-jaisa nahi hai."""
    assert L._person_name_from_run(
        "New World Order", "New World Order kya hai", False,
        prev_word="rakho") == ""


def test_determiner_makes_it_a_concept_not_a_person():
    """"the Divine Spark" — vyakti ke naam ke aage determiner nahi lagta."""
    assert L._person_name_from_run(
        "Divine Spark", "the Divine Spark kya hai", False,
        prev_word="the") == ""


def test_line_start_run_is_a_heading():
    assert L._person_name_from_run(
        "Final Challenge", "Final Challenge\nab batao", True,
        prev_word="") == ""


def test_word_also_written_lowercase_is_a_common_word():
    """Case-consistency: jo shabd sawaal me chhote akshar me bhi hai, wo naam
    nahi. (Naapa gaya: Human/Evidence lowercase bhi aate hain, Carl/Jung nahi.)"""
    assert L._person_name_from_run(
        "Human Reality", "human reality ke saath Human Reality", False,
        prev_word="par") == ""


def test_case_consistency_is_the_deciding_signal_on_its_own():
    """Contrast pair — ek hi run, sirf ek farq: wahi shabd sawaal me chhote
    akshar me bhi hai ya nahi. Baaki koi niyam (suffix/framework/stopword) is
    jodi par lagu nahi hota, isliye ye check akele naapa jaata hai."""
    run = "Deep Water"
    with_lower = "deep water ke baare me Deep Water bhi likha hai"
    without_lower = "Deep Water ke baare me batao"
    assert L._person_name_from_run(run, with_lower, False, prev_word="me") == ""
    assert L._person_name_from_run(
        run, without_lower, False, prev_word="me") == "Deep Water"


def test_framework_head_noun_is_not_a_person():
    assert L._person_name_from_run(
        "Flow State", "Flow State kya hai", False, prev_word="par") == ""


def test_real_two_word_name_survives():
    assert L._person_name_from_run(
        "Carl Jung", "Carl Jung ne kaha", False, prev_word="par") == "Carl Jung"


def test_long_question_thinkers_have_no_headings():
    """Lambe sawaal me sirf asli naam — heading/standard ke tukde nahi."""
    got = L.thinker_candidates(LONG_Q)
    assert "Carl Jung" in got and "Neville Goddard" in got
    joined = " | ".join(got).casefold()
    for junk in ("human reality", "final challenge", "mandatory evidence",
                 "grand unified", "inner reality", "strategy problem"):
        assert junk not in joined, f"heading thinker ban gaya: {junk}"


def test_unnamed_people_are_found_by_structure_only():
    """Ye naam kisi list me nahi hain — cue bhasha se aata hai."""
    assert L.thinker_candidates("swami vivekananda ke vichar") == [
        "vivekananda", "swami vivekananda"]
    assert L.thinker_candidates(
        "naval ravikant ki philosophy kya hai") == ["naval ravikant"]
    assert L.thinker_candidates("ramanujan ke notebooks me kya tha") == [
        "ramanujan"]


# ------------------------------------------------------- search-term safety

def test_sentence_fragment_is_not_a_search_term():
    """Poore vaakya/placeholder search query nahi ban sakte."""
    assert L.is_search_term_safe("CIA investigated X") is False
    assert L.is_search_term_safe("quantum consciousness.") is False
    assert L.is_search_term_safe("kya hai; batao") is False


def test_slash_and_comma_terms_are_split_junk():
    """"frequency/vibration" ek search phrase nahi hai — dono shabd alag se
    pehle hi aate hain, isliye joda hua roop sirf khaali result laata tha."""
    assert L.is_search_term_safe("frequency/vibration") is False
    assert L.is_search_term_safe("mind, body") is False
    assert L.is_search_term_safe("reality (maya)") is False


def test_dangling_hyphen_compound_is_rejected():
    """"consciousness-and" ka doosra hissa stopword hai → adhoora compound."""
    assert L.is_search_term_safe("consciousness-and") is False
    assert L.is_search_term_safe("self-image") is True


def test_name_particles_are_allowed_short_pieces():
    """"ibn"/"de" chhote hain par naam ka hissa hain — inhe girana galat tha."""
    assert L.is_search_term_safe("ibn khaldun") is True
    assert L.is_search_term_safe("de broglie") is True
    assert L.is_search_term_safe("a b c") is False


def test_overlong_phrase_is_rejected():
    assert L.is_search_term_safe("one two three four five six seven") is False


def test_lens_concepts_carry_no_fragments():
    """deterministic_lenses ke concepts/frameworks bhi usi gate se guzarte hain."""
    lens = L.deterministic_lenses(LONG_Q)
    blob = " | ".join(lens["concepts"] + lens["frameworks"]).casefold()
    for junk in ("cia investigated", "cia proved", "consciousness-and",
                 "frequency/vibration"):
        assert junk not in blob, f"fragment lens me pahunch gaya: {junk}"
    # Asli compound zinda rehte hain, warna filter ne kaam ki cheez kha li.
    assert any("psycho-cybernetics" == c.casefold() for c in lens["concepts"])


# ----------------------------------------------------------- work-name filter

def test_question_fragments_are_not_work_names():
    assert C.is_work_like_name("CIA investigated X") is False
    assert C.is_work_like_name("kya kehti hai") is False
    assert C.is_work_like_name("x y") is False


def test_bare_generic_text_word_is_not_a_work():
    """"book"/"granth" akela kriti ka naam nahi hai."""
    assert C.is_work_like_name("book") is False
    assert C.is_work_like_name("granth") is False


def test_real_titles_pass_the_work_filter():
    assert C.is_work_like_name("bhagavad gita") is True
    assert C.is_work_like_name("tao of physics") is True
    assert C.is_work_like_name("psycho-cybernetics") is True


def test_title_like_needs_every_content_word_capitalised():
    assert C._title_like("Psycho Cybernetics") is True
    assert C._title_like("The Tao Of Physics") is True
    assert C._title_like("tao of physics") is False
    assert C._title_like("Psycho") is False


def test_near_text_cue_counts_only_text_words_and_read_cues():
    """Naapa hua defect: lambe sawaal me "explain" 3 token door tha, isliye
    summary cue ko title-signal maanna "self-image" ko kriti bana deta tha."""
    assert C._near_text_cue("self-image wali book ka summary do",
                            "self-image") is True
    assert C._near_text_cue("aap explain karo ki self-image ka asar kya hai",
                            "self-image") is False


def test_quoted_only_separates_titles_from_scare_quotes():
    """Quote me ek hi baar aaya phrase title ka signal hai; jo bahar bhi
    dohraya jaaye wo aam shabd hai."""
    assert C._quoted_only('"vigyan bhairav" me shwas par kya kaha hai',
                          "vigyan bhairav") is True
    assert C._quoted_only('"reality" kya hai aur reality ka matlab batao',
                          "reality") is False


# ------------------------------------------------------- work_candidates end2end

def test_look_back_skips_joiner_and_stops_before_question_words():
    """Naapa hua defect: "ke" par look-back turant ruk jaata tha, isliye
    "bhagavad gita ke chapter 2" par ek bhi kriti-naam nahi banta tha. Aur
    "muqaddimah kis saal" me sawaal-shabd naam me ghus jaata tha."""
    assert C.work_candidates(
        "Bhagavad Gita ke chapter 2 me kya likha hai") == ["bhagavad gita"]
    assert C.work_candidates(
        "muqaddimah granth me kis saal ka zikr hai") == ["muqaddimah"]


def test_leading_function_words_are_stripped_but_name_particles_are_not():
    """"The Tao of Physics book" → "tao of physics" (connector beech me chalega),
    par "ibn khaldun" ka "ibn" kabhi nahi kata."""
    assert C.work_candidates(
        "The Tao of Physics book kya kehti hai") == ["tao of physics"]
    assert C.work_candidates(
        "ibn khaldun ka granth padhna hai kojiki ke saath") == [
            "ibn khaldun granth"]


def test_two_word_lead_drops_its_leading_article():
    """Sirf leading-strip is jodi par kaam karti hai: "The Tao book" ka lead
    ['the','tao'] hai, aur "the tao" search karne ka koi fayda nahi."""
    assert C.work_candidates("The Tao book kya kehti hai") == ["tao"]
    assert C.work_candidates("a raja yoga book do") == ["raja yoga"]


def test_name_plus_capitalised_work_branch():
    assert "Marcus Aurelius Meditations" in C.work_candidates(
        "Explain Marcus Aurelius Meditations ka saar")


def test_person_join_never_uses_a_division_word():
    """"Bhagavad Gita ke chapter 2" jaisa join kriti nahi banata — chapter/
    verse/edition bantwaare ke shabd hain, naam ka hissa nahi."""
    for name in C.work_candidates("Bhagavad Gita ke chapter 2 me kya likha hai"):
        low = name.casefold()
        for part in ("chapter", "verse", "edition", "volume", "page"):
            assert part not in low, f"division word naam me: {name}"


def test_quoted_title_opens_the_lane_without_any_list():
    assert C.work_candidates(
        '"vigyan bhairav" me shwas par kya kaha hai') == ["vigyan bhairav"]
    assert C.work_candidates("book raja yoga ka summary do") == ["raja yoga"]


def test_hyphen_compound_needs_a_title_or_text_cue():
    """Contrast pair: text-shabd paas ho to compound kriti hai, sirf summary
    cue ho to nahi. Dono ek hi shabd par naape gaye."""
    assert C.work_candidates("self-image wali book ka summary do") == [
        "self-image"]
    assert C.work_candidates(
        "aap explain karo ki self-image ka asar kya hai") == []


def test_placeholder_sentence_never_becomes_a_work():
    assert C.work_candidates("CIA investigated X aur uske baad kya hua") == []
    assert C.work_candidates(
        '"reality" kya hai aur reality ka matlab batao') == []


def test_long_question_works_stay_clean():
    """Lambe sawaal me sirf wahi kriti jo user ne khud likhi (title-case),
    heading/placeholder nahi."""
    got = C.work_candidates(LONG_Q)
    assert any(name.casefold() == "psycho-cybernetics" for name in got)
    blob = " | ".join(got).casefold()
    for junk in ("cia investigated", "human reality", "mandatory evidence",
                 "consciousness-and", "final challenge"):
        assert junk not in blob, f"junk kriti ban gayi: {junk}"


def test_off_topic_technical_question_opens_no_text_lane():
    """Control: mechanical sawaal par granth-lane bilkul nahi khulni chahiye."""
    assert C.work_candidates(
        "gearbox helical gear efficiency calculation") == []


def test_work_candidates_is_deterministic():
    """Ek hi sawaal do baar → wahi jawab. (Lens/ledger ka koi hidden state
    beech me na aaye.)"""
    question = "nagarjuna ke mool granth me kya likha hai"
    first = C.work_candidates(question)
    assert first == C.work_candidates(question) == ["nagarjuna"]
