"""#132 — SONGCRAFT ke naap ka test: har imaandaari wali baat FALSIFIABLE ho.

#128-#131 ne gaane ke liye style/bhaav/register/music-direction ke naap jode. In
naapon ka sabse bada khatra ye hai ki wo CHUP-CHAAP paas hone lagein — "style
match ho gayi", "feeling aa gayi", "dhun mast banegi" — jabki asli me kuch padha
hi nahi gaya. Ye file usi khatre ke khilaaf khadi hai.

Is file ke kaam (har ek ek JHOOTH rokta hai):
  1. craft <-> songcraft ke literal ek hi rahein (do jagah likhe hain kyunki
     circular import se bachna tha), aur naye naap PURANE naapon ke AAGE juden —
     kisi purane naap ki jagah na lein,
  2. style/register/bhasha ki table sirf ADDRESSING rahe — "user ne kis cheez ka
     naam liya", na ki "us style ka gyaan aa gaya",
  3. kisi maujooda gaane ke BOL/file dhoondhne wali query bane hi na — planner
     aur source_discovery, dono deewar par,
  4. bina source id koi hidayat na jaaye, aur kuch padha na gaya ho to block
     saaf kahe "kuch padha nahi gaya" (apne aap se salaah na ghade),
  5. aathon naap ka MET/NOT_MET/NOT_MEASURED asli number se aaye, aur "naap
     chala hi nahi" kabhi "naap paas ho gaya" na bane (fail-closed),
  6. yahan koi AUDIO na bane, aur report/audit har baar ye sach likhe,
  7. `emotion_achieved` / `music_quality_ok` jaisa naam paida hi na ho,
  8. poora stage ₹0 aur 0 Gemini call par rahe, aur do baar chalane par bilkul
     wahi nateeja de.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft, depth, songcraft as sc  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402


# ── chhote helpers (koi network, koi randomness, koi model call) ─────────────
class _Src:
    """SourceRecord ka sirf wahi hissa jo songcraft duck-typed padhta hai."""

    def __init__(self, source_id, title="", snippet="", full_text="",
                 url="http://example.test/x", connector="books"):
        self.source_id = source_id
        self.title = title
        self.snippet = snippet
        self.full_text = full_text
        self.url = url
        self.connector = connector


class _Pack:
    def __init__(self, *sources):
        self.sources = list(sources)


_CRAFT_SENTENCE = (
    "In a pop song the chorus is usually 4 lines long, and the hook repeats "
    "3 times so that listeners remember the line.")
_JUNK_SENTENCE = (
    "We use cookies to improve your experience on this website. Please "
    "subscribe to our newsletter for daily offers today.")

_Q_SONG = "sad type ka punjabi gaana likho 4 line"

_SONG = ("raat gehri hai mera man akela\n"
         "chand bhi aaj lagta hai akela\n"
         "tanhai mere paas baith gayi\n"
         "ye kahani mere saath reh gayi")

# Music direction jawab me DRAFT KE BAHAR likhi jaati hai — naap bhi wahin
# dekhti hai. Yahan koi "dhun mast banegi" jaisa daawa nahi hai (warna
# `no_music_quality_claim` FAIL hoti — aur wo FAIL sahi hoti).
_MUSIC = ("\nMusic direction (sirf salaah, koi audio nahi bani):\n"
          "- Tempo: dheema, 70 bpm ke aas paas\n"
          "- Scale/raag: minor, raag bhairavi jaisa\n"
          "- Vaadya: guitar aur halka tabla\n"
          "- Aawaz: male vocal, akela\n")


def _fenced(body: str) -> str:
    return "Ye lo draft.\n\n```" + craft.DRAFT_FENCE + "\n" + body + "\n```\n"


def _answer(body: str = _SONG, music: str = _MUSIC) -> str:
    return _fenced(body) + music


def _facts(**block):
    """facts banane ka chhota tareeka.

    Kuch naap songcraft ke block se padhte hain (mood arc, register, style-fit,
    music direction) aur kuch craft ke apne top-level facts se (matra, refrain,
    draft ke mood) — dono jaan-boojh kar alag rakhe gaye hain, taaki ek hi
    cheez do jagah alag na nikle. Ye helper wahi baant karta hai.
    """
    top = {}
    for key in ("matra_per_line", "matra_rule", "moods", "refrain"):
        if key in block:
            top[key] = block.pop(key)
    top["songcraft"] = block
    return top


# ── 1. craft <-> songcraft: ek hi zubaan, aur naya kaam JODA gaya hai ────────
# songcraft circular import se bachne ke liye kuch literal DOBARA likhta hai.
# Do jagah likhi hui cheez chup-chaap alag ho jaana asli khatra hai: tab craft
# "MET" likhega aur songcraft "met", aur report jhooth bolegi.
def test_status_words_are_identical_in_both_modules():
    assert (sc.MET, sc.NOT_MET, sc.NOT_MEASURED) == (craft.MET, craft.NOT_MET,
                                                     craft.NOT_MEASURED)
    assert sc.CHECK_STATUSES == craft.CHECK_STATUSES
    assert sc.SONG_FORM == craft.FORMS[0].form_id == "song"
    assert sc.MATRA_RULE_ROMAN == craft.MATRA_RULE_ROMAN == "roman_vowel_approx"


def test_new_checks_are_added_at_the_end_and_replace_nothing():
    names = [name for name, _runner in craft.CHECKS]
    # aage jude hain — kisi purane naap ki jagah nahi li
    assert names[-len(sc.CHECK_NAMES):] == list(sc.CHECK_NAMES)
    for old in ("line_count", "stanza_count", "word_count", "matra_target",
                "matra_consistency", "rhyme", "refrain_hook",
                "over_repetition", "cliche_density", "script_match",
                "no_appeal_claim", "mood_words_present"):
        assert old in names, old
    assert len(names) == len(set(names))
    assert len(sc.CHECK_NAMES) == len(sc.CHECK_RUNNERS) == 8


def test_no_check_is_named_like_a_promise():
    # Naam khud ek daawa hota hai. `emotion_achieved` naam ka naap "feeling aa
    # gayi" padha jaata hai — aur wo cheez naapi hi nahi ja sakti.
    craft_names = [name for name, _runner in craft.CHECKS]
    for banned in sc.FORBIDDEN_CHECK_NAMES:
        assert banned not in sc.CHECK_NAMES, banned
        assert banned not in craft_names, banned
    assert "mood_spread" in sc.CHECK_NAMES
    assert "music_direction_present" in sc.CHECK_NAMES
    assert "emotion_achieved" in sc.FORBIDDEN_CHECK_NAMES
    assert "music_quality_ok" in sc.FORBIDDEN_CHECK_NAMES


def test_songcraft_limits_add_to_the_craft_list_instead_of_replacing_it():
    report = craft.run_craft(_Q_SONG, _answer())
    merged = list(report["cannot_measure"])
    for item in craft.CANNOT_MEASURE:
        assert item in merged, item
    for item in sc.CANNOT_MEASURE_EXTRA:
        assert item in merged, item
    assert len(merged) == len(craft.CANNOT_MEASURE) + len(sc.CANNOT_MEASURE_EXTRA)


# ── 2. imaandaari ke jhande: audio, cost, aur "quality proven" ───────────────
def test_no_audio_is_ever_made_here():
    assert sc.AUDIO_GENERATED is False
    assert sc.MUSIC_DIRECTION_IS_SUGGESTION is True
    policy = sc.policy()
    assert policy["audio_generated"] is False
    assert policy["music_direction_is_suggestion"] is True
    assert policy["existing_song_lyrics_fetched"] is False
    assert any("audio" in line.lower() for line in sc.limits())
    assert any("audio" in line.lower() for line in sc.CANNOT_MEASURE_EXTRA)


def test_policy_never_claims_quality_network_or_cost():
    policy = sc.policy()
    assert policy["network_used"] is False and sc.NETWORK_USED is False
    assert policy["gemini_calls"] == 0 and sc.GEMINI_CALLS == 0
    assert policy["randomness_used"] is False
    assert policy["deterministic"] is True
    assert policy["provider_cost"] == "₹0"
    assert policy["quality_proven"] is False
    assert policy["human_reaction_untested"] is True
    for flag in ("style_table_is_addressing_only", "style_list_is_not_exhaustive",
                 "image_list_is_not_exhaustive",
                 "register_list_is_not_exhaustive"):
        assert policy[flag] is True, flag


def test_limits_never_borrow_the_matra_word_approx():
    # Audit me "approx" ka ek hi matlab hai: matra roman akshar par gini gayi.
    # Doosri seema ke liye wahi lafz likhna padhne wale ko gumraah karta hai.
    joined = " ".join(sc.limits())
    assert "approx" not in joined
    assert "andaza" in joined
    assert "ADDRESSING" in joined


def test_the_unmeasurable_things_are_written_down_not_hidden():
    joined = " ".join(sc.CANNOT_MEASURE_EXTRA)
    assert "feeling" in joined            # sunne wale ka asar
    assert "copyright" in joined          # kisi maujooda gaane se milaan
    assert "dhun" in joined               # melody achhi banegi ya nahi
    assert len(sc.CANNOT_MEASURE_EXTRA) >= 6


# ── 3. style ki maang = ADDRESSING, gyaan NAHI ───────────────────────────────
def test_named_style_language_and_tempo_are_read_from_the_ask():
    ask = sc.style_of("sad type ka punjabi gaana likho 8 line")
    assert ask.styles == ["sad_slow"]
    assert ask.languages == ["punjabi"]
    assert ask.tempo_family == "slow"
    assert ask.primary_label and ask.style_labels
    assert ask.asked_anything() is True
    assert ask.study_terms()


def test_misspelled_asks_still_land_because_intel_types_them_that_way():
    assert sc.style_of("danceing type punjabi gaana").styles == ["dance_party"]
    assert sc.style_of("gangstar type rap likho").styles == ["rap_street"]
    assert sc.style_of("danceing type punjabi gaana").tempo_family == "fast"
    assert sc.style_of("gangstar type rap likho").tempo_family == "mid"


def test_a_cue_never_matches_inside_a_longer_word():
    # "sadak" me "sad" nahi ginna chahiye, warna raaste wala gaana bhi
    # chup-chaap "dukh bhara" ban jaayega.
    ask = sc.style_of("sadak par ek gaana likho")
    assert ask.styles == []
    assert ask.asked_anything() is False
    assert ask.notes and any("adhoori" in note for note in ask.notes)


def test_devanagari_ask_is_read_too():
    ask = sc.style_of("दुख भरा गाना लिखो")
    assert ask.question_script == "devanagari"
    assert "sad_slow" in ask.styles


def test_a_refused_register_is_not_treated_as_a_demand():
    # "aese nhi sudh hindi me" = mana kiya gaya hai. Ise maang samajh lena
    # seedha ulta kaam karega.
    plain = sc.style_of("shudh hindi me gaana likho")
    assert "shudh" in plain.registers
    assert "hindi" in plain.languages
    refused = sc.style_of("aese nhi sudh hindi me gaana likho")
    assert "shudh" not in refused.registers
    assert any("mana" in note for note in refused.notes)


def test_the_ask_dict_always_carries_the_four_honesty_lines():
    for question in ("sad punjabi gaana likho", "ek gaana likho", ""):
        row = sc.style_of(question).to_dict()
        assert row["style_table_is_addressing_only"] is True, question
        assert row["style_list_is_not_exhaustive"] is True, question
        assert row["audio_generated"] is False, question
        assert "tempo_note" in row


def test_tempo_is_only_the_name_of_the_ask_never_a_read_number():
    ask = sc.style_of("sad gaana likho")
    assert ask.tempo_family == "slow"
    assert "padha hua number nahi" in ask.to_dict()["tempo_note"]
    # aur koi MET/NOT_MET faisla tempo par nahi tikta: music direction me tempo
    # ka zikr na ho to bhi baaki teen khaane se naap MET ho jaati hai.
    facts = _facts(form=sc.SONG_FORM,
                   context="raag bhairavi, guitar aur tabla, male vocal")
    row = sc.run_check("music_direction_present", None, facts)
    assert row["status"] == sc.MET
    assert "tempo" not in row["measured"]


# ── 4. kisi maujooda gaane ke BOL kabhi nahi dhoondhe jaate ──────────────────
def test_lyrics_and_file_hunting_is_recognised():
    for query in ("lyrics of tum hi ho", "full lyrics tum hi ho",
                  "karaoke track hindi", "tum hi ho mp3",
                  "gaane ke bol download", "song download free"):
        assert sc.is_lyrics_hunt(query) is True, query


def test_craft_study_wording_is_not_mistaken_for_lyrics_hunting():
    for query in ("songwriting craft lyric writing guide",
                  "prosody meter syllable stress in song lyrics",
                  "music and emotion listener response research"):
        assert sc.is_lyrics_hunt(query) is False, query


def test_every_generated_query_passes_the_guard_itself():
    for question in ("sad punjabi gaana likho", "gangstar rap likho",
                     "danceing gaana banao", "ek gaana likho",
                     "shudh hindi me bhajan likho"):
        rows = sc.study_queries(sc.style_of(question))
        assert rows, question
        for row in rows:
            assert sc.is_lyrics_hunt(row["query"]) is False, row
            assert len(row["query"]) >= sc.MIN_STUDY_QUERY_CHARS, row
            assert row["lane"] in sc.STUDY_LANES, row
            assert row["why"], row


def test_style_specific_queries_come_first_and_the_limit_is_honoured():
    ask = sc.style_of("sad punjabi gaana likho")
    rows = sc.study_queries(ask)
    assert len(rows) <= sc.MAX_STUDY_QUERIES
    assert rows[0]["query"] == "sad ballad songwriting"
    queries = [row["query"] for row in rows]
    assert len(queries) == len(set(queries))
    assert len(sc.study_queries(ask, limit=1)) == 1
    # Bhasha bhi apni query laati hai — Punjabi maanga to Punjabi ka riwaaj
    # padha jaayega, sirf angrezi songwriting nahi.
    assert any("Punjabi" in query for query in queries)


def test_seed_queries_survive_even_when_no_style_was_named():
    rows = sc.study_queries(sc.style_of("ek gaana likho"))
    assert rows
    seeds = {query for query, _lane, _why in sc.CRAFT_STUDY_SEEDS}
    assert {row["query"] for row in rows} & seeds


def test_study_plan_tells_the_planner_the_truth():
    plan = sc.study_plan(sc.style_of("sad gaana likho"))
    assert plan["craft_study"] is True
    assert plan["lyrics_hunt_blocked"] is True
    assert plan["network_used_here"] is False
    assert plan["gemini_calls_here"] == 0
    assert (len(plan["craft_study_queries"]) == len(plan["craft_study_lanes"])
            == len(plan["craft_study_reasons"]))
    assert "bol" in plan["craft_study_note"]


# ── 5. hidayat sirf PADHI HUI baat se, source id ke saath ─────────────────────
def test_a_source_without_an_id_can_never_produce_guidance():
    # source id ke bina line ka koi hisaab nahi rehta — us line ko baad me
    # koi verify nahi kar sakta, isliye wo jaati hi nahi.
    guidance = sc.guidance_from([_Src("", snippet=_CRAFT_SENTENCE)])
    assert guidance["lines"] == []
    assert guidance["guidance_source_count"] == 0
    assert guidance["style_conventions_read"] is False


def test_guidance_lines_always_carry_their_source_id():
    guidance = sc.guidance_from([_Src("S1", snippet=_CRAFT_SENTENCE)])
    assert guidance["lines"]
    for line in guidance["lines"]:
        assert line["source_id"] == "S1"
        assert line["text"].strip()
    assert guidance["guidance_source_count"] == 1
    assert guidance["guidance_is_quoted_not_invented"] is True
    assert "source id" in guidance["read_note"]


def test_web_junk_is_not_mistaken_for_craft_guidance():
    guidance = sc.guidance_from([_Src("S2", snippet=_JUNK_SENTENCE)])
    assert guidance["lines"] == []
    assert guidance["guidance_source_count"] == 0
    assert guidance["sources_scanned"] == 1     # padha gaya, par kaam ka nahi tha
    # Craft ki baat HONI chahiye — koi bhi lambi saaf line hidayat nahi banti.
    plain = _Src("S3", snippet=("The train left the station in the morning and "
                                "the sky above the market was very grey."))
    assert sc.guidance_from([plain])["lines"] == []
    # Kachra + craft = phir bhi kachra (page ka footer craft ki kitaab nahi hai).
    mixed = _Src("S4", snippet=("Subscribe to our newsletter for more tips on "
                                "how the chorus hook and rhyme should work."))
    assert sc.guidance_from([mixed])["lines"] == []


def test_numbers_are_believed_only_when_a_source_says_them():
    guidance = sc.guidance_from([_Src("S1", snippet=_CRAFT_SENTENCE)])
    kinds = {(row["kind"], row["value"], row["source_id"])
             for row in guidance["numeric_conventions"]}
    assert ("lines_per_stanza", 4, "S1") in kinds
    assert ("refrain_times", 3, "S1") in kinds
    assert guidance["style_conventions_read"] is True
    nothing = sc.guidance_from([])
    assert nothing["numeric_conventions"] == []
    assert nothing["style_conventions_read"] is False
    assert nothing["sources_scanned"] == 0


def test_nothing_read_means_the_block_says_so_instead_of_inventing():
    guidance = sc.guidance_from([])
    assert "kuch padha nahi gaya" in guidance["read_note"]
    block = sc.guidance_prompt_block(guidance, sc.style_of("sad gaana likho"))
    assert sc.EMPTY_GUIDANCE_LINE in block
    assert "PADHI HUI SOURCE SE" not in block


def test_guidance_stays_bounded_per_source_and_overall():
    # Haddein NAAP ke saath pin hain: sirf "<= CONSTANT" likhne se constant
    # badal dene par test chup reh jaata (mutation test ne yahi pakda tha).
    assert (sc.MIN_GUIDANCE_CHARS, sc.MAX_GUIDANCE_CHARS,
            sc.MAX_GUIDANCE_LINES, sc.MAX_GUIDANCE_PER_SOURCE) == (30, 240, 8, 2)
    many = [_Src(f"S{n}", snippet=(f"The chorus in a {n}-bar pop song should "
                                   f"use concrete imagery and a singable line "
                                   f"length for the listener."))
            for n in range(1, 13)]
    guidance = sc.guidance_from(many)
    assert len(guidance["lines"]) == 8          # 12 source the, 8 par ruk gaya
    assert 0 < len(guidance["lines"]) <= sc.MAX_GUIDANCE_LINES
    for line in guidance["lines"]:
        assert len(line["text"]) <= sc.MAX_GUIDANCE_CHARS
        assert len(line["text"]) >= sc.MIN_GUIDANCE_CHARS
    one = sc.guidance_from([_Src("S1", snippet=(
        "A chorus should repeat its hook so the listener remembers it. "
        "Imagery in a verse must be concrete and sensory, not abstract. "
        "Meter and stress decide the syllable count of every sung line. "
        "Rhyme at the end of a line helps the singer land the phrase."))])
    assert len(one["lines"]) == 2               # chaar kaam ki line thi, do li
    assert 0 < len(one["lines"]) <= sc.MAX_GUIDANCE_PER_SOURCE
    # Chhoti line hidayat nahi banti — warna aadha vaakya "kitaab kehti hai"
    # ban jaata.
    short = _Src("S9", snippet="Hook repeats. Rhyme helps.")
    assert sc.guidance_from([short])["lines"] == []


# ── 6. prompt block: kya maanga gaya, aur kya likhna MANA hai ────────────────
def test_prompt_block_asks_for_music_direction_and_forbids_claims():
    block = sc.guidance_prompt_block(sc.guidance_from([]),
                                     sc.style_of("sad punjabi gaana likho"))
    for field in sc.MUSIC_DIRECTION_FIELDS:
        assert field in block, field
    assert "koi audio/dhun nahi banti" in block
    assert "bol copy mat karo" in block
    assert "Punjabi" in block
    assert "naapa hua" in block            # jhootha daawa = naapi hui FAIL


def test_prompt_block_quotes_read_lines_with_their_source_id():
    guidance = sc.guidance_from([_Src("S1", snippet=_CRAFT_SENTENCE)])
    block = sc.guidance_prompt_block(guidance, sc.style_of("sad gaana likho"))
    assert "[S1]" in block
    assert "padha hua number" in block
    assert sc.EMPTY_GUIDANCE_LINE not in block


def test_study_puts_the_whole_offline_pack_in_one_place():
    pack = sc.study("sad punjabi gaana likho",
                    sources=[_Src("S1", snippet=_CRAFT_SENTENCE)],
                    form=sc.SONG_FORM)
    assert pack["ran"] is True
    assert pack["gemini_calls"] == 0
    assert pack["network_used"] is False
    assert pack["audio_generated"] is False
    assert pack["guidance_source_count"] == 1
    assert pack["style_conventions_read"] is True
    assert "[S1]" in pack["prompt_block"]
    assert pack["ask_dict"]["styles"] == ["sad_slow"]
    assert list(pack["cannot_measure"]) == list(sc.CANNOT_MEASURE_EXTRA)


def test_study_without_sources_stays_honest_rather_than_helpful():
    pack = sc.study("sad gaana likho")
    assert pack["ran"] is True
    assert pack["guidance_source_count"] == 0
    assert pack["style_conventions_read"] is False
    assert sc.EMPTY_GUIDANCE_LINE in pack["prompt_block"]
    assert pack["queries"]                 # padhne ki koshish ka plan banta hai


# ── 7. aathon naap: asli number se MET/NOT_MET, warna NOT_MEASURED ───────────
def test_mood_spread_counts_stanzas_and_refuses_on_one_stanza():
    good = sc.run_check("mood_spread", None,
                        _facts(stanza_moods=[["dukh"], ["tanhai"]]))
    assert good["status"] == sc.MET and "2/2" in good["measured"]
    # MET ka matlab bhi imaandaar rehna chahiye: shabd faile hue hain, feeling
    # aa gayi — ye dono ek baat nahi.
    assert "saabit nahi" in good["note"]
    weak = sc.run_check("mood_spread", None,
                        _facts(stanza_moods=[["dukh"], [], [], []]))
    assert weak["status"] == sc.NOT_MET
    assert weak["reason"] == "mood_only_in_few_stanzas"
    lonely = sc.run_check("mood_spread", None, _facts(stanza_moods=[["dukh"]]))
    assert lonely["status"] == sc.NOT_MEASURED
    assert lonely["reason"] == "too_few_stanzas"


def test_mood_conflict_only_speaks_when_a_real_opposite_exists():
    none_asked = sc.run_check("mood_conflict_absent", None, _facts())
    assert none_asked["status"] == sc.NOT_MEASURED
    assert none_asked["reason"] == "no_mood_asked"
    clash = sc.run_check("mood_conflict_absent", None,
                         _facts(moods_asked=["dukh"], moods=["dukh", "khushi"]))
    assert clash["status"] == sc.NOT_MET
    assert clash["reason"] == "opposite_mood_present"
    # "judaai + pyaar" ek sad gaane me normal hai — use conflict kehna galat
    # hoga, isliye wo jodi table me hi nahi hai.
    fine = sc.run_check("mood_conflict_absent", None,
                        _facts(moods_asked=["dukh"], moods=["judaai", "pyaar"]))
    assert fine["status"] == sc.MET
    unknown = sc.run_check("mood_conflict_absent", None,
                           _facts(moods_asked=["pyaar"], moods=["pyaar"]))
    assert unknown["status"] == sc.NOT_MEASURED
    assert unknown["reason"] == "no_opposite_known"


def test_concrete_image_words_are_a_share_and_stay_marked_approx():
    strong = sc.run_check("concrete_image_words", None,
                          _facts(roman_tokens=["chai", "station", "baarish",
                                               "dard"]))
    assert strong["status"] == sc.MET and strong["approx"] is True
    thin = sc.run_check("concrete_image_words", None,
                        _facts(roman_tokens=["chai", "dard", "pyaar",
                                             "zindagi"]))
    assert thin["status"] == sc.NOT_MET and thin["reason"] == "too_abstract"
    assert thin["approx"] is True
    # list adhoori hai: koi cue na mile to "theek hai" nahi, "naapa nahi" hai
    blank = sc.run_check("concrete_image_words", None,
                         _facts(roman_tokens=["aage", "aagey"]))
    assert blank["status"] == sc.NOT_MEASURED
    assert blank["reason"] == "no_image_or_abstract_cue"
    empty = sc.run_check("concrete_image_words", None, _facts(roman_tokens=[]))
    assert empty["status"] == sc.NOT_MEASURED and empty["reason"] == "no_tokens"


def test_register_is_measured_only_where_an_honest_counter_exists():
    none_asked = sc.run_check("register_consistency", None, _facts())
    assert none_asked["status"] == sc.NOT_MEASURED
    assert none_asked["reason"] == "no_register_asked"
    # "street" lehja maanga gaya — par uska koi imaandaar counter nahi hai.
    # Aise waqt jhootha MET dene se behtar hai "naapa nahi" kehna.
    no_rule = sc.run_check("register_consistency", None,
                           _facts(registers=["street"],
                                  script_counts={"latin": 40}))
    assert no_rule["status"] == sc.NOT_MEASURED
    assert no_rule["reason"] == "no_numeric_register_rule"
    half = sc.run_check("register_consistency", None,
                        _facts(registers=["shudh"],
                               script_counts={"latin": 50, "devanagari": 50}))
    assert half["status"] == sc.NOT_MET
    assert half["reason"] == "english_share_too_high"
    clean = sc.run_check("register_consistency", None,
                         _facts(registers=["shudh"],
                                script_counts={"latin": 2, "devanagari": 98}))
    assert clean["status"] == sc.MET
    no_letters = sc.run_check("register_consistency", None,
                              _facts(registers=["shudh"], script_counts={}))
    assert no_letters["status"] == sc.NOT_MEASURED
    assert no_letters["reason"] == "no_letters"


def test_singability_uses_the_median_and_never_guesses_without_matra():
    even = sc.run_check("singability_line_outliers", None,
                        _facts(matra_per_line=[12, 12, 13, 12],
                               matra_rule=sc.MATRA_RULE_ROMAN))
    assert even["status"] == sc.MET
    assert even["approx"] is True          # roman se gini gayi matra approx hai
    edge = sc.run_check("singability_line_outliers", None,
                        _facts(matra_per_line=[12, 30, 12, 12],
                               matra_rule=sc.MATRA_RULE_ROMAN))
    assert edge["status"] == sc.MET        # 1/4 = 0.25, theek hadd par
    bad = sc.run_check("singability_line_outliers", None,
                       _facts(matra_per_line=[12, 30, 40, 12],
                              matra_rule=sc.MATRA_RULE_ROMAN))
    assert bad["status"] == sc.NOT_MET
    assert bad["reason"] == "line_length_outliers"
    # Hadd ki asli keemat bhi pin hai: 2/6 = 0.333 hadd (0.25) se upar hai,
    # isliye ye NOT_MET rehna chahiye. Sirf "bahut buri" haalat naapna kaafi
    # nahi tha — cap badha dene par wo test chup reh jaata tha.
    assert (sc.MAX_OUTLIER_SHARE, sc.SING_OUTLIER_TOL) == (0.25, 4)
    tilted = sc.run_check("singability_line_outliers", None,
                          _facts(matra_per_line=[12, 12, 12, 12, 30, 31],
                                 matra_rule=sc.MATRA_RULE_ROMAN))
    assert tilted["status"] == sc.NOT_MET
    assert tilted["reason"] == "line_length_outliers"
    short = sc.run_check("singability_line_outliers", None,
                         _facts(matra_per_line=[12, 12, 12],
                                matra_rule=sc.MATRA_RULE_ROMAN))
    assert short["status"] == sc.NOT_MEASURED
    assert short["reason"] == "matra_not_measurable"
    no_rule = sc.run_check("singability_line_outliers", None,
                           _facts(matra_per_line=[12, 12, 12, 12],
                                  matra_rule=""))
    assert no_rule["status"] == sc.NOT_MEASURED


def test_style_fit_stays_unmeasured_until_a_source_gave_a_real_number():
    nothing = sc.run_check("style_fit_structure", None,
                           _facts(stanza_line_counts=[4, 4]))
    assert nothing["status"] == sc.NOT_MEASURED
    assert nothing["reason"] == "style_conventions_not_read"
    assert "NAHI hai" in nothing["note"]      # "sab theek hai" nahi hai
    read_but_not_numeric = sc.run_check(
        "style_fit_structure", None,
        _facts(guidance_source_count=2, stanza_line_counts=[4, 4]))
    assert read_but_not_numeric["reason"] == "no_numeric_convention_read"


def test_style_fit_compares_the_draft_with_the_read_number():
    convention = [{"kind": "lines_per_stanza", "value": 4, "source_id": "S1"}]
    hit = sc.run_check("style_fit_structure", None,
                       _facts(numeric_conventions=convention,
                              stanza_line_counts=[4, 4]))
    assert hit["status"] == sc.MET
    assert "[S1] band 4 line: mila" in hit["measured"]
    miss = sc.run_check("style_fit_structure", None,
                        _facts(numeric_conventions=convention,
                               stanza_line_counts=[3, 5]))
    assert miss["status"] == sc.NOT_MET
    assert miss["reason"] == "read_convention_not_followed"
    hook = [{"kind": "refrain_times", "value": 3, "source_id": "S7"}]
    hook_hit = sc.run_check("style_fit_structure", None,
                            _facts(numeric_conventions=hook,
                                   refrain={"times": 3}))
    assert hook_hit["status"] == sc.MET
    hook_miss = sc.run_check("style_fit_structure", None,
                             _facts(numeric_conventions=hook,
                                    refrain={"times": 1}))
    assert hook_miss["status"] == sc.NOT_MET
    unknown_kind = sc.run_check("style_fit_structure", None,
                                _facts(numeric_conventions=[
                                    {"kind": "kuch_aur", "value": 9,
                                     "source_id": "S1"}]))
    assert unknown_kind["status"] == sc.NOT_MEASURED
    assert unknown_kind["reason"] == "convention_kind_unknown"


def test_music_direction_is_demanded_for_songs_only():
    poem = sc.run_check("music_direction_present", None,
                        _facts(form="poem", context=_MUSIC))
    assert poem["status"] == sc.NOT_MEASURED and poem["reason"] == "not_a_song"
    blank = sc.run_check("music_direction_present", None,
                         _facts(form=sc.SONG_FORM, context="  "))
    assert blank["status"] == sc.NOT_MEASURED
    assert blank["reason"] == "no_answer_text"


def test_music_direction_counts_named_fields_and_claims_nothing_more():
    full = sc.run_check("music_direction_present", None,
                        _facts(form=sc.SONG_FORM, context=_MUSIC))
    assert full["status"] == sc.MET
    assert "4/4 khaane" in full["measured"]
    assert "koi audio/dhun nahi bani" in full["note"]
    thin = sc.run_check("music_direction_present", None,
                        _facts(form=sc.SONG_FORM,
                               context="Tempo dheema rakho, guitar bajao."))
    assert thin["status"] == sc.NOT_MET
    assert thin["reason"] == "music_direction_incomplete"
    assert "scale_or_raag" in thin["note"] and "voice" in thin["note"]


def test_an_unmeasured_music_claim_is_itself_a_measured_failure():
    claim = sc.run_check("no_music_quality_claim", None,
                         _facts(form=sc.SONG_FORM,
                                context="Ye dhun mast banegi aur chartbuster "
                                        "hogi."))
    assert claim["status"] == sc.NOT_MET
    assert claim["reason"] == "unmeasured_music_claim"
    assert claim["measured"] == 2
    clean = sc.run_check("no_music_quality_claim", None,
                         _facts(form=sc.SONG_FORM, context=_MUSIC))
    assert clean["status"] == sc.MET and clean["measured"] == 0
    blank = sc.run_check("no_music_quality_claim", None,
                         _facts(form=sc.SONG_FORM, context=""))
    assert blank["status"] == sc.NOT_MEASURED
    assert blank["reason"] == "no_answer_text"


def test_music_claim_finder_names_the_exact_words_it_objected_to():
    found = sc.music_claims_in("dhun mast banegi aur ye chartbuster hoga")
    assert "chartbuster" in found
    assert any("dhun mast" in row for row in found)
    assert sc.music_claims_in("tempo dheema hai, guitar aur tabla") == []


# ── 8. fail-closed: "naap chala hi nahi" kabhi "naap paas ho gaya" nahi ──────
def test_a_broken_check_becomes_not_measured_never_met():
    # Aisi facts jo andar se naap ko toad deti hain: matra ki ginti me shabd
    # aa gaye. Nateeja NOT_MEASURED hona chahiye — MET kabhi nahi.
    rows = sc.measure_song(None, {"songcraft": {},
                                  "matra_per_line": ["a", "b", "c", "d"],
                                  "matra_rule": sc.MATRA_RULE_ROMAN})
    broken = [row for row in rows if row["reason"] == "check_error"]
    assert broken
    for row in broken:
        assert row["status"] == sc.NOT_MEASURED
        assert "kuch bhi" in row["note"]
    assert not [row for row in rows if row["status"] == sc.MET
                and row["reason"] == "check_error"]


def test_every_row_has_the_full_shape_and_a_reason_when_it_is_not_met():
    rows = sc.measure_song(None, {})
    assert [row["check"] for row in rows] == list(sc.CHECK_NAMES)
    for row in rows:
        assert set(row) == {"check", "status", "measured", "target", "reason",
                            "note", "approx"}
        assert row["status"] in sc.CHECK_STATUSES
        if row["status"] != sc.MET:
            assert row["reason"] and row["note"], row


def test_an_unknown_check_name_raises_instead_of_quietly_passing():
    for name in sc.FORBIDDEN_CHECK_NAMES:
        try:
            sc.run_check(name, None, _facts())
        except KeyError:
            pass
        else:
            raise AssertionError(f"{name} chup-chaap chal gaya")


def test_craft_measure_survives_a_broken_songcraft_block():
    # songcraft ka context banate waqt kuch toot jaaye to poora CRAFT stage
    # nahi girna chahiye — us haalat me gaane ke naap NOT_MEASURED ho jaate
    # hain (aur "sab theek" kabhi nahi kehte).
    original = sc.context_facts

    def _boom(*args, **kwargs):
        raise RuntimeError("jaan-boojh kar toda gaya")

    sc.context_facts = _boom
    try:
        measured = craft.measure(_SONG, craft.build_spec(_Q_SONG),
                                 context=_MUSIC)
    finally:
        sc.context_facts = original
    rows = {row["check"]: row for row in measured["checks"]}
    # jo naap songcraft ke block par tikte hain, wo sab NOT_MEASURED hone
    # chahiye (singability top-level matra se aata hai, isliye wo alag hai)
    for name in ("mood_spread", "mood_conflict_absent", "concrete_image_words",
                 "register_consistency", "style_fit_structure",
                 "music_direction_present", "no_music_quality_claim"):
        assert rows[name]["status"] != sc.MET, name
    assert measured["status"] in craft.DRAFT_STATUSES


# ── 9. craft ke saath juda hua asli nateeja ──────────────────────────────────
def _study_pack(read=True):
    sources = [_Src("S1", snippet=_CRAFT_SENTENCE)] if read else []
    return sc.study(_Q_SONG, sources=sources, form=sc.SONG_FORM)


def test_the_song_report_runs_all_eight_new_checks_at_zero_cost():
    report = craft.run_craft(_Q_SONG, _answer(), study=_study_pack())
    names = [row["check"] for row in report["checks"]]
    for name in sc.CHECK_NAMES:
        assert name in names, name
    assert report["gemini_calls"] == 0
    assert report["songcraft"]["audio_generated"] is False
    assert report["songcraft"]["music_direction_is_suggestion"] is True
    assert report["songcraft"]["gemini_calls"] == 0
    assert report["songcraft"]["network_used"] is False
    assert report["songcraft"]["style_conventions_read"] is True
    assert report["songcraft"]["guidance_source_count"] == 1


def test_the_section_shows_the_ask_the_read_numbers_and_the_no_audio_line():
    section = craft.craft_section(craft.run_craft(_Q_SONG, _answer(),
                                                 study=_study_pack()))
    assert "Style ki maang: sad / dard bhara (dheema)" in section
    assert "Bhasha: Punjabi" in section
    assert "[S1] lines_per_stanza=4" in section
    assert "koi audio/dhun NAHI bani" in section


def test_when_nothing_was_read_the_audit_refuses_to_claim_style_fit():
    dark = craft.run_craft(_Q_SONG, _answer(), study=_study_pack(read=False))
    rows = {row["check"]: row for row in dark["checks"]}
    assert rows["style_fit_structure"]["status"] == sc.NOT_MEASURED
    assert rows["style_fit_structure"]["reason"] == "style_conventions_not_read"
    limits = craft.craft_limits(dark)
    assert any("style match ho gayi' kahna jhooth hoga" in line
               for line in limits)
    # aur jab padha gaya ho, wahi line gayab ho jaati hai (naap se banti hai,
    # likhi hui nahi)
    lit = craft.craft_limits(craft.run_craft(_Q_SONG, _answer(),
                                            study=_study_pack()))
    assert not any("style match ho gayi' kahna jhooth hoga" in line
                   for line in lit)
    assert any("AUDIO_GENERATED = False" in line for line in lit)


def test_a_poem_is_never_asked_for_music_direction():
    poem = craft.run_craft("tanhai par 8 line ki kavita likho",
                           _fenced(_SONG))
    rows = {row["check"]: row for row in poem["checks"]}
    assert rows["music_direction_present"]["status"] == sc.NOT_MEASURED
    assert rows["music_direction_present"]["reason"] == "not_a_song"
    section = craft.craft_section(poem)
    assert "Style ki maang" not in section
    assert not any("AUDIO_GENERATED = False" in line
                   for line in craft.craft_limits(poem))


def test_a_music_quality_claim_in_the_answer_is_caught_and_named():
    boastful = craft.run_craft(
        _Q_SONG, _answer() + "\nIs gaane ki dhun mast banegi, chartbuster hai.",
        study=_study_pack())
    rows = {row["check"]: row for row in boastful["checks"]}
    assert rows["no_music_quality_claim"]["status"] == sc.NOT_MET
    assert rows["no_music_quality_claim"]["reason"] == "unmeasured_music_claim"
    assert boastful["status"] == craft.DRAFT_WEAK


def test_the_same_input_twice_gives_the_same_song_report():
    first = craft.run_craft(_Q_SONG, _answer(), study=_study_pack())
    second = craft.run_craft(_Q_SONG, _answer(), study=_study_pack())
    assert first["checks"] == second["checks"]
    assert first["songcraft"] == second["songcraft"]
    assert craft.craft_section(first) == craft.craft_section(second)
    assert craft.craft_limits(first) == craft.craft_limits(second)


# ── 10. do deewar: bol dhoondhne wali query kabhi nikalti hi nahi ────────────
def _plan_for(question, depth_name="DEEP"):
    planner = ResearchPlanner()
    config = depth.get_depth_config(depth_name)
    return planner.connector_plan({"question": question}, config,
                                  question=question)


def test_planner_opens_the_craft_study_lane_only_for_song_requests():
    plan = _plan_for("sad punjabi gaana likho 8 line")
    lane = plan["craft_study_lane"]
    assert lane["wanted"] is True and lane["is_song_request"] is True
    assert lane["lyrics_hunt_blocked"] is True
    assert lane["style_conventions_read"] is False   # plan padhna nahi hai
    assert lane["audio_generated"] is False
    assert lane["gemini_calls"] == 0
    assert 0 < len(plan["craft_study"]) <= sc.MAX_STUDY_QUERIES
    other = _plan_for("room temperature superconductivity par report banao")
    assert other["craft_study"] == []
    assert other["craft_study_lane"]["is_song_request"] is False
    # Farmaish honi KAAFI nahi — form gaana hona chahiye. Kavita/nibandh par
    # music-emotion ki kitaabein dhoondhna sirf budget kharch hai.
    for text in ("mere liye ek kavita likho baarish par 8 line",
                 "global warming par 500 shabd ka nibandh likho"):
        plan_other = _plan_for(text)
        assert plan_other["craft_study"] == [], text
        assert plan_other["craft_study_lane"]["is_song_request"] is False, text
        assert plan_other["craft_study_lane"]["wanted"] is False, text


def test_planner_refuses_the_lane_when_existing_lyrics_are_being_asked_for():
    plan = _plan_for("tum hi ho ke full lyrics do aur gaana likho")
    assert plan["craft_study"] == []
    lane = plan["craft_study_lane"]
    assert lane["wanted"] is False
    assert "copyright" in lane["reason"]


def test_quick_depth_gets_a_smaller_craft_study_budget():
    deep = _plan_for("sad punjabi gaana likho 8 line", "DEEP")
    quick = _plan_for("sad punjabi gaana likho 8 line", "QUICK")
    assert len(quick["craft_study"]) < len(deep["craft_study"])
    assert quick["craft_study"]                     # band nahi hui, chhoti hui
    assert quick["craft_study_lane"]["wanted"] is True


def test_every_planned_query_is_a_craft_query_not_a_lyrics_query():
    plan = _plan_for("gangstar type punjabi gaana likho")
    for entry in plan["craft_study"]:
        assert sc.is_lyrics_hunt(entry["query"]) is False, entry
        assert entry["lane"] in sc.STUDY_LANES


class _Spy:
    """Connector ka naatak — network ke bina, jo query aayi wo yaad rakhta hai."""

    name = "spy"

    def __init__(self):
        self.seen = []

    def search(self, query, limit=3, **kwargs):
        self.seen.append(str(query))
        return []


def _tasks_for(craft_entries, question="gaana likho"):
    discovery = SourceDiscovery()
    spy = _Spy()
    discovery.books.by_name = lambda name: spy
    discovery.papers.by_name = lambda name: spy
    plan = {"web": True, "papers": [], "books": [], "datasets": [],
            "patents": [], "markets": [], "craft_study": craft_entries}
    tasks = discovery._tasks([question], plan, 3, 5)
    return [label for label, _fn in tasks], spy


def test_discovery_drops_a_planted_lyrics_hunt_query():
    labels, _spy = _tasks_for([
        {"query": "songwriting craft lyric writing guide", "lane": "books"},
        {"query": "tum hi ho full lyrics", "lane": "books"},
        {"query": "karaoke track mp3 download", "lane": "web"},
    ])
    assert labels.count("craft_study_books") == 1
    assert "craft_study_web" not in labels


def test_discovery_routes_craft_study_to_the_lane_the_plan_named():
    labels, spy = _tasks_for([
        {"query": "songwriting craft lyric writing guide", "lane": "books"},
        {"query": "prosody meter syllable stress in song lyrics",
         "lane": "papers"},
    ])
    assert "craft_study_books" in labels and "craft_study_papers" in labels
    # duplicate query dobara network par nahi jaati
    dupes, _spy = _tasks_for([
        {"query": "songwriting craft lyric writing guide", "lane": "books"},
        {"query": "Songwriting Craft Lyric Writing Guide", "lane": "books"},
    ])
    assert dupes.count("craft_study_books") == 1
    assert isinstance(spy.seen, list)


def test_discovery_never_opens_the_lane_when_the_plan_has_none():
    labels, _spy = _tasks_for([])
    assert not [label for label in labels if label.startswith("craft_study")]


# ── 11. orchestrator: padha hua hissa, bina paisa bina jhooth ────────────────
def test_orchestrator_study_costs_nothing_and_stays_honest_without_sources():
    study = DeepResearchEngine._songcraft_study("sad punjabi gaana likho", None)
    assert study["ran"] is True
    assert study["gemini_calls"] == 0
    assert study["network_used"] is False
    assert study["audio_generated"] is False
    assert study["guidance_source_count"] == 0
    assert study["style_conventions_read"] is False
    assert sc.EMPTY_GUIDANCE_LINE in study["prompt_block"]


def test_orchestrator_study_turns_read_sources_into_cited_guidance():
    pack = _Pack(_Src("S1", snippet=_CRAFT_SENTENCE),
                 _Src("S2", snippet=_JUNK_SENTENCE))
    study = DeepResearchEngine._songcraft_study("sad gaana likho", pack)
    assert study["style_conventions_read"] is True
    assert study["guidance_source_count"] == 1        # junk source nahi gina
    assert "[S1]" in study["prompt_block"]
    assert study["gemini_calls"] == 0


def test_orchestrator_study_never_explodes_and_never_claims_success():
    class _AngryPack:
        @property
        def sources(self):
            raise RuntimeError("jaan-boojh kar toda gaya")

    study = DeepResearchEngine._songcraft_study("gaana likho", _AngryPack())
    assert study["ran"] is False              # "padha nahi gaya", "theek hai" nahi
    assert study["style_conventions_read"] is False
    assert study["guidance_source_count"] == 0
    assert study["gemini_calls"] == 0
    assert study["audio_generated"] is False
    assert study["prompt_block"] == ""


def test_the_whole_song_lane_is_deterministic_and_free():
    question = "sad punjabi gaana likho 8 line"
    pack = _Pack(_Src("S1", snippet=_CRAFT_SENTENCE))
    first = DeepResearchEngine._songcraft_study(question, pack)
    second = DeepResearchEngine._songcraft_study(question, pack)
    assert first["prompt_block"] == second["prompt_block"]
    assert first["guidance"]["lines"] == second["guidance"]["lines"]
    assert first["queries"] == second["queries"]
    assert _plan_for(question)["craft_study"] == _plan_for(question)["craft_study"]
    assert sc.policy()["provider_cost"] == "₹0"
    assert first["gemini_calls"] == second["gemini_calls"] == 0

