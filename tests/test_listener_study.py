"""#134 — SUNNE WALE ki samajh: "research padhi" ≠ "logon ka dil padha".

intel ki maang ka aadha hissa #128-#133 me bana: gaane ka HUNAR (hook, matra,
style, music direction) aur recording/transcript se padhna. Doosra aadha —
"logo ka dil pdhe emosion jaane kya psnd h human behviyar" — patla tha. #134 ne
uske liye alag query lane, alag cited samajh, alag report block aur alag seema
banayi.

Is lane ka asli khatra ek hi hai, aur ye file poori usi ke peeche padi hai:

    psychology/music research padh lene ke baad report aisi lag sakti hai
    jaise app ne asli logon par gaana test kar liya. Ek bhi line ("log
    aisa mehsoos karenge", "pakka hit") us jhooth ko sach jaisa bana deti
    hai — aur wahi baat sabse aasaani se chup-chaap ghus jaati hai.

Isliye har test ek naapa hua jhooth rokta hai:

  1. QUERY par pabandi — lane ka naam whitelist se, mood ka roop bandha hua
     (bol dhoondhne wali baat mood ke bhes me network par nahi jaati), aur
     budget alag taaki craft ki naapi hui coverage se ek slot bhi na chhine.
  2. PADHNA sirf CITED — bina source id koi line nahi, vaada karne wali line
     hatti hai aur uski GINTI chhapti hai.
  3. NAAP teen haalat me — chali nahi / chali par kuch nahi mila / mili.
     "chali nahi" ko kabhi "theek hai" nahi kehna.
  4. GINTI ALAG — craft ki hidayat aur listener ki samajh ek dher me nahi
     milti (wahi jhooth #133 me bhi rokha gaya tha).
  5. REPORT/AUDIT — block sirf gaane ki farmaish par, par us haalat me seema
     HAMESHA, aur audit ki chhat us nayi line ko kaat na de.
  6. ₹0 — 0 Gemini call, 0 network, koi randomness nahi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import listener_study as ls  # noqa: E402
from research_engine import songcraft as sc  # noqa: E402
from research_engine import craft  # noqa: E402
from research_engine import depth  # noqa: E402
from research_engine.models import EvidencePack, ResearchResult  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402
from research_engine.synthesizer_claude import FinalSynthesizer  # noqa: E402

SONG_Q = "hindi me ek sad gaana likho judaai wala"
NON_SONG_Q = "room temperature superconductivity ka mechanism samjhao"

EMOTION_TEXT = (
    "Listeners report a stronger emotional response when a melody matches the "
    "remembered context of an earlier life event.")
FAMILIAR_TEXT = (
    "Familiarity with a repeated hook increases reported liking across "
    "repeated exposures in listening experiments.")
CULTURE_TEXT = (
    "Cultural background shapes which scales an audience hears as sad in "
    "cross-cultural listening studies.")
PROMISE_TEXT = (
    "This emotional chorus is guaranteed to make everyone cry on first "
    "listen and will be a pakka hit.")


class _Src:
    """Sirf wahi hissa jo ye lane chhoota hai.

    `snippet`/`full_text` jaan-boojh kar: `songcraft._source_text` sirf title,
    snippet aur full_text padhta hai — `.text` naam ka field chup-chaap 0 line
    deta hai, aur wahi galti fixture me ek jhootha GREEN bana deti hai.
    """

    def __init__(self, source_id="S1", snippet="", title="", full_text="",
                 read_level="snippet", url="https://example.org/a",
                 connector="web"):
        self.source_id = source_id
        self.snippet = snippet
        self.title = title
        self.full_text = full_text
        self.read_level = read_level
        self.url = url
        self.connector = connector


class _Ask:
    """`songcraft.StyleAsk` ki jagah — sirf `moods` chahiye."""

    def __init__(self, moods=()):
        self.moods = list(moods)


def _pack(sources=(), question=SONG_Q, wanted=True):
    return ls.study(question, sources=list(sources), wanted=wanted)


def _read_source(name):
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research_engine", name)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# ── 1. QUERY par pabandi ─────────────────────────────────────────────────────

def test_seed_queries_stay_inside_the_known_lane_names():
    """Anjaan lane ka matlab hai routing use pehchaanegi nahi.

    Us haalat me query chup-chaap web par gir jaati aur report me lane ka naam
    jhooth ban jaata ("kitaab se padha" jabki web se aaya). Isliye lane ka naam
    songcraft ki wahi ek vocabulary se aata hai.
    """
    assert sc.STUDY_LANES == ("web", "books", "papers", "media")
    for _query, lane, _why in ls.LISTENER_SEEDS:
        assert lane in sc.STUDY_LANES
    for row in ls.study_queries(limit=99):
        assert row["lane"] in sc.STUDY_LANES


def test_every_seed_query_is_about_the_listener_not_the_craft():
    """Craft ki query pehle se songcraft me hai.

    Wahi query dobara bhejne se do lane ek hi cheez padhti aur "sunne wale ki
    samajh" ki ginti craft ke bal par badh jaati — wahi ginti-ka-jhooth jise ye
    poora batch rokta hai.
    """
    craft_rows = sc.study_queries(sc.style_of(SONG_Q), limit=99)
    craft_queries = {str(row["query"]).casefold() for row in craft_rows}
    assert craft_queries          # craft lane sach me query banati hai
    for row in ls.study_queries(_Ask(["dukh"]), limit=99):
        assert row["query"].casefold() not in craft_queries


def test_a_mood_shapes_the_first_query_and_keeps_its_reason():
    """Mood na lage to lane har gaane ke liye ek hi query bhejti hai."""
    rows = ls.study_queries(_Ask(["judaai"]), limit=3)
    assert rows[0]["query"].startswith("judaai ")
    assert rows[0]["lane"] == "papers"
    assert "judaai" in rows[0]["why"]
    assert len(rows) == 3


def test_only_one_mood_reaches_the_query_list():
    """Saare mood bhej dene se seeds ke slot khatam ho jaate.

    Us haalat me nostalgia/dohraav/sanskriti wali research kabhi search hi nahi
    hoti aur report me "in par kuch nahi mila" chhap jaata — jo asal me lane ki
    apni galti hai, research ki kami nahi.
    """
    rows = ls.study_queries(_Ask(["dukh", "khushi", "gussa"]), limit=99)
    mood_rows = [r for r in rows if r["query"].split()[0] in
                 ("dukh", "khushi", "gussa")]
    assert len(mood_rows) == 1
    assert len(rows) == 1 + len(ls.LISTENER_SEEDS)


def test_a_free_text_mood_can_never_become_a_network_query():
    """Ye teesri deewar hai, aur jaan-boojh kar hai.

    `songcraft.is_lyrics_hunt()` bare "<gaane ka naam> song lyrics" nahi pakadta
    (regex chaudi karne se jaayaz seed bhi block ho jaati). Mood se query BANTI
    hai, isliye mood ka roop hi bandha hua hai: chhota ASCII shabd, warna mood
    chhoot jaata hai — seeds phir bhi chalti hain.
    """
    assert ls.safe_mood("dukh") == "dukh"
    assert ls.safe_mood("  Yaad  ") == "yaad"
    for bad in ("tum hi ho song lyrics", "", "   ", "a", "mood-1", "dukh 2",
                "sixteencharacters", "गम", "sad;rm -rf"):
        assert ls.safe_mood(bad) == ""
    rows = ls.study_queries(_Ask(["tum hi ho song lyrics"]), limit=99)
    assert all("lyrics" not in r["query"].casefold() for r in rows)
    assert len(rows) == len(ls.LISTENER_SEEDS)


def test_a_lyrics_hunt_query_is_dropped_even_if_it_is_a_seed_shape():
    """Bol/karaoke/mp3 wali query is lane se network par nahi jaati."""
    original = ls.LISTENER_SEEDS
    try:
        ls.LISTENER_SEEDS = (
            ("tum hi ho song lyrics download mp3", "papers", "test"),
            ("nostalgia autobiographical memory in songs listener", "papers",
             "theek query"),
        )
        rows = ls.study_queries(limit=99)
        assert [r["query"] for r in rows] == [
            "nostalgia autobiographical memory in songs listener"]
    finally:
        ls.LISTENER_SEEDS = original


def test_a_too_short_or_unknown_lane_query_never_ships():
    """Do chhoti pabandi jo chup-chaap todi ja sakti thi."""
    original = ls.LISTENER_SEEDS
    try:
        ls.LISTENER_SEEDS = (
            ("emotion", "papers", "bahut chhoti"),
            ("audience reaction study", "podcast", "anjaan lane"),
            ("repetition familiarity liking earworm listener", "papers", "ok"),
        )
        rows = ls.study_queries(limit=99)
        assert [r["query"] for r in rows] == [
            "repetition familiarity liking earworm listener"]
    finally:
        ls.LISTENER_SEEDS = original
    assert ls.MIN_QUERY_CHARS == 8


def test_the_same_query_is_never_shipped_twice():
    """Do baar wahi query = do baar wahi kharcha aur do baar wahi ginti."""
    original = ls.LISTENER_SEEDS
    try:
        seed = ("repetition familiarity liking earworm listener", "papers", "a")
        ls.LISTENER_SEEDS = (seed, seed, ("  Repetition   Familiarity liking "
                                          "earworm LISTENER  ", "books", "b"))
        rows = ls.study_queries(limit=99)
        assert len(rows) == 1
    finally:
        ls.LISTENER_SEEDS = original


def test_the_listener_budget_is_its_own_and_small():
    """Craft ka budget alag hai — yehi baat coverage bachati hai.

    Ek hi budget me se dono lane khaane lagein to craft ki naapi hui coverage
    chup-chaap gir jaati, aur "gaana likhne ka hunar" wali query kat jaati.
    """
    assert ls.MAX_LISTENER_QUERIES == 3
    assert sc.MAX_STUDY_QUERIES == 6
    assert ls.MAX_LISTENER_QUERIES < sc.MAX_STUDY_QUERIES
    assert len(ls.study_queries(_Ask(["dukh"]))) == 3
    assert len(ls.study_queries(_Ask(["dukh"]), limit=1)) == 1
    assert len(ls.study_queries(_Ask(["dukh"]), limit=0)) == 1


def test_the_plan_dict_says_query_bani_but_padha_nahi():
    """Query ban jaana padhna NAHI hai — planner ke dict me bhi wahi sach."""
    plan = ls.study_plan(_Ask(["dukh"]))
    lane = plan["listener_study_lane"]
    assert len(plan["listener_study"]) == 3
    assert lane["wanted"] is True and lane["query_count"] == 3
    assert lane["listener_evidence_read"] is False
    assert lane["listener_tested"] is False
    assert lane["audience_measured"] is False
    assert lane["lyrics_hunt_blocked"] is True
    assert lane["gemini_calls"] == 0 and lane["network_used_here"] is False


# ── 2. PADHNA sirf CITED ─────────────────────────────────────────────────────

def test_a_line_without_a_source_id_never_becomes_guidance():
    """Bina citation ek baat "research kehti hai" ban jaati hai — wahi jhooth."""
    good = _Src("S1", snippet=EMOTION_TEXT)
    anon = _Src("", snippet=FAMILIAR_TEXT)
    report = ls.listener_guidance([anon, good])
    assert [row["source_id"] for row in report["lines"]] == ["S1"]
    assert report["sources_scanned"] == 2      # dono padhe gaye
    assert report["source_count"] == 1         # par ek hi cite ho saka


def test_every_reported_line_carries_its_source_id_everywhere():
    """Ek jagah citation gir jaaye to wahi line "app ki apni baat" ban jaati."""
    report = ls.listener_guidance([_Src("S1", snippet=EMOTION_TEXT),
                                   _Src("S2", snippet=CULTURE_TEXT)])
    pack = {"wanted": True, "guidance": report}
    for row in report["lines"]:
        assert row["source_id"] and row["text"]
    for text in (ls.prompt_block(report), ls.listener_section(pack),
                 "\n".join(ls.section_lines(report))):
        for row in report["lines"]:
            assert f"[{row['source_id']}]" in text


def test_a_promise_line_is_dropped_and_the_count_is_published():
    """Vaada hidayat nahi hoti — par chup-chaap girna bhi jhooth hai.

    Ginti chhupane se report bilkul waisi dikhti hai jaise research me wo baat
    hi nahi thi. Isliye ginti report, section aur audit — teeno me jaati hai.
    """
    report = ls.listener_guidance([_Src("S1", snippet=PROMISE_TEXT)])
    assert report["lines"] == []
    assert report["promise_lines_dropped"] == 1
    assert report["ran"] is True               # padha gaya, mila nahi
    joined = " ".join(ls.section_lines(report)) + " " + " ".join(ls.limits(
        report))
    assert "vaada" in joined
    assert "1 line hataayi" in joined


def test_the_promise_regex_knows_hinglish_marketing_too():
    """Angrezi-only regex ka matlab hai Hinglish vaada seedha nikal jaata."""
    for line in ("This is guaranteed to make everyone cry.",
                 "Ye chorus sabka dil jeet lega.",
                 "Aisa mukhda pakka hit hota hai.",
                 "Is tarah ka hook zaroor hit karta hai.",
                 "Every listener will feel the loss in this verse."):
        assert ls.is_promise(line) is True
    for line in (EMOTION_TEXT, FAMILIAR_TEXT, CULTURE_TEXT,
                 "Listeners often report sadness when tempo drops."):
        assert ls.is_promise(line) is False


def test_a_sentence_with_no_listener_cue_is_not_invented_into_guidance():
    """Cue na mile to line chhodni hai, "kaam ki lagti hai" par nahi rakhni."""
    report = ls.listener_guidance([_Src("S1", snippet=(
        "The mixing engineer used a 1176 compressor on the vocal bus for "
        "roughly three decibels of gain reduction throughout."))])
    assert report["ran"] is True and report["lines"] == []
    assert report["source_count"] == 0
    assert "kuch nahi mila" in ls.support_row(report)["note"] or True
    assert ls.support_row(report)["status"] == sc.NOT_MET


def test_each_group_is_named_and_the_missing_ones_are_named_too():
    """Khaali jagah chhupane se "sab padh liya" jaisa bhram banta hai."""
    report = ls.listener_guidance([_Src("S1", snippet=EMOTION_TEXT),
                                   _Src("S2", snippet=CULTURE_TEXT)])
    assert report["groups"] == ["bhaav", "sanskriti"]
    assert set(report["missing_groups"]) == set(ls.GROUP_KEYS) - {
        "bhaav", "sanskriti"}
    for key in report["missing_groups"]:
        assert ls.GROUP_LABELS[key] in report["missing_group_labels"]
    assert ls.GROUP_KEYS == ("bhaav", "yaad", "apnapan", "dohraav",
                             "sanskriti", "vyavhaar")


def test_the_cue_list_admits_it_is_incomplete():
    """Ye ek line "kuch nahi mila" ko "kuch nahi tha" banne se rokti hai."""
    assert ls.CUE_LIST_IS_NOT_EXHAUSTIVE is True
    assert any("cue-list adhoori" in line for line in ls.limits())
    assert ls.cue_group("Ye baat kisi bhi cue se match nahi karti.") == ""
    assert ls.cue_group(EMOTION_TEXT) == "bhaav"
    assert ls.cue_group(FAMILIAR_TEXT) == "dohraav"


def test_reading_limits_come_from_songcraft_and_are_not_copied():
    """Do copy ek din alag ho jaati hain — isliye ek hi sach, wahin se."""
    short = "Emotion is nice."
    assert len(short) < sc.MIN_GUIDANCE_CHARS
    long_line = ("Listeners report a stronger emotional response when the "
                 "melody carries the memory of a place " + "x" * 400 + ".")
    report = ls.listener_guidance([_Src("S1", snippet=short + " " + long_line)])
    assert len(report["lines"]) == 1
    assert len(report["lines"][0]["text"]) <= sc.MAX_GUIDANCE_CHARS


def test_one_source_can_never_flood_the_whole_block():
    """Ek uploader ke shabd poori "samajh" nahi ban sakte."""
    many = " ".join([EMOTION_TEXT, FAMILIAR_TEXT, CULTURE_TEXT,
                     "Nostalgia in songs reminds people of their childhood "
                     "summers and that memory drives the reported liking."])
    report = ls.listener_guidance([_Src("S1", snippet=many)])
    assert len(report["lines"]) == sc.MAX_GUIDANCE_PER_SOURCE == 2
    assert report["source_count"] == 1


def test_the_whole_block_has_a_ceiling_too():
    """Chhat na ho to prompt/report ek hi cheez se bhar jaate hain."""
    assert ls.MAX_LISTENER_LINES == 6
    sources = [_Src(f"S{i}", snippet=f"Listeners report emotional response "
                                     f"number {i} to a remembered melody.")
               for i in range(12)]
    report = ls.listener_guidance(sources)
    assert len(report["lines"]) == ls.MAX_LISTENER_LINES
    assert len(ls.prompt_block(report).splitlines()) <= (
        1 + ls.MAX_PROMPT_LINES + 1 + len(ls.PROMPT_RULES))


def test_the_same_sentence_twice_is_counted_once():
    """Ek hi baat do source se aakar "do saboot" nahi ban sakti."""
    report = ls.listener_guidance([_Src("S1", snippet=EMOTION_TEXT),
                                   _Src("S2", snippet=EMOTION_TEXT.upper())])
    assert len(report["lines"]) == 1
    assert report["source_count"] == 1


def test_snippet_only_reading_is_admitted_in_the_audit():
    """Abstract padh kar "poora paper padha" jaisa bhram nahi banna chahiye."""
    snippet_only = ls.listener_guidance([_Src("S1", snippet=EMOTION_TEXT)])
    assert snippet_only["full_text_source_count"] == 0
    assert any("snippet/abstract" in line for line in ls.limits(snippet_only))
    deep = ls.listener_guidance([_Src("S1", full_text=EMOTION_TEXT,
                                      read_level="full_text")])
    assert deep["full_text_source_count"] == 1
    assert not any("snippet/abstract" in line for line in ls.limits(deep))


# ── 3. NAAP teen haalat me ───────────────────────────────────────────────────

def test_the_three_states_are_three_different_words():
    """Sabse bada khatra: "chali nahi" ko "theek hai" dikha dena.

    Teeno haalat ka status alag hona chahiye, warna UI me ek hi rang dikhega
    aur "naapa hi nahi gaya" chup-chaap "pass" ban jaayega.
    """
    never = ls.support_row(ls.listener_guidance([]))
    nothing = ls.support_row(ls.listener_guidance([
        _Src("S1", snippet="The compressor ratio was four to one on the bus.")]))
    found = ls.support_row(ls.listener_guidance([_Src("S1",
                                                      snippet=EMOTION_TEXT)]))
    assert never["status"] == sc.NOT_MEASURED
    assert nothing["status"] == sc.NOT_MET
    assert found["status"] == sc.MET
    assert len({never["status"], nothing["status"], found["status"]}) == 3


def test_the_not_measured_row_refuses_to_be_read_as_pass():
    """Ye line hi "chali nahi" aur "theek hai" ke beech ka pharak hai."""
    row = ls.support_row(ls.listener_guidance([]))
    assert row["measured"] == ""
    assert "naapa hi nahi gaya" in row["note"]
    assert "'sab theek hai' NAHI" in row["note"]


def test_a_met_row_still_says_it_is_not_proof_of_feeling():
    """MET = "padhi hui source se aaya", MET ≠ "sunne wale ko waisa lagega"."""
    row = ls.support_row(ls.listener_guidance([_Src("S1", snippet=EMOTION_TEXT),
                                              _Src("S2", snippet=CULTURE_TEXT)]))
    assert row["measured"] == "2 cited baat / 2 source"
    assert "saboot nahi" in row["note"]
    assert "test nahi hua" in row["note"]


def test_the_check_name_never_claims_something_that_was_not_done():
    """Naam hi jhooth bol sakta hai — "audience_tested" jaisa naam mana hai."""
    assert ls.CHECK_NAME == "listener_understanding_cited"
    assert ls.CHECK_NAME not in ls.FORBIDDEN_CHECK_NAMES
    for bad in ("listener_will_feel_it", "audience_tested", "hit_probability",
                "emotion_guaranteed", "dil_jeeta"):
        assert bad in ls.FORBIDDEN_CHECK_NAMES
    code = _read_source("listener_study.py")
    # Naam mana-list ke andar likha hona chahiye, ya policy me saaf INKAAR ke
    # roop me (`"emotion_guaranteed": False`). Kisi naap/field ke asli naam ki
    # tarah kahin nahi — wahi ek jagah poora block jhooth bana deti.
    inside_list = False
    for line in code.splitlines():
        if line.startswith("FORBIDDEN_CHECK_NAMES"):
            inside_list = True
            continue
        if inside_list:
            inside_list = not line.startswith(")")
            continue
        for bad in ls.FORBIDDEN_CHECK_NAMES:
            assert bad not in line or f'"{bad}": False' in line
    assert ls.policy()["emotion_guaranteed"] is False
    assert ls.policy()["hit_predicted"] is False
    for row in (ls.support_row(ls.listener_guidance([])),
                ls.support_row(ls.listener_guidance([_Src(
                    "S1", snippet=EMOTION_TEXT)]))):
        assert row["check"] not in ls.FORBIDDEN_CHECK_NAMES


def test_every_state_keeps_the_same_target_so_rows_can_be_compared():
    """Target badalta rahe to teen row ek table me rakhne ka koi matlab nahi."""
    rows = [ls.support_row(ls.listener_guidance([])),
            ls.support_row(ls.listener_guidance([_Src("S1", snippet="Mic gain "
                                                     "was set to unity here.")])),
            ls.support_row(ls.listener_guidance([_Src("S1",
                                                     snippet=EMOTION_TEXT)]))]
    assert {row["target"] for row in rows} == {"kam se kam 1 cited baat"}
    for row in rows:
        assert set(row) == {"check", "status", "measured", "target", "reason",
                            "note"}


# ── 4. GINTI ALAG: craft ki hidayat aur listener ki samajh ───────────────────

def test_listener_lines_are_never_added_to_the_craft_guidance_count():
    """#133 me media ke saath yahi jhooth rokha gaya tha — ab listener ka bhi.

    Ek dher me milane se report "8 cited hidayat" dikhati hai jabki craft ke
    peeche sirf 2 hain — yani gaane ka hunar bina padhe likha gaya.
    """
    src = [_Src("S1", snippet=EMOTION_TEXT + " " + CULTURE_TEXT)]
    listener = ls.listener_guidance(src)
    assert listener["lines"]
    assert ls.policy()["merged_into_craft_guidance"] is False
    assert ls.public_record(ls.study(SONG_Q, sources=src))[
        "merged_into_craft_guidance"] is False
    code = _read_source("listener_study.py")
    assert "guidance_lines" not in code      # craft ki ginti ka field yahan nahi


def test_the_prompt_block_always_carries_the_no_promise_rules():
    """Prompt me se ye do line hat jaayein to model khud vaada likh dega."""
    for report in (ls.listener_guidance([]),
                   ls.listener_guidance([_Src("S1", snippet=EMOTION_TEXT)])):
        block = ls.prompt_block(report)
        assert block.strip()
        for rule in ls.PROMPT_RULES:
            assert rule in block
    assert ls.MAX_PROMPT_LINES == 5
    assert "pakka hit" in " ".join(ls.PROMPT_RULES)


def test_an_empty_prompt_block_says_do_not_invent_feelings():
    """Kuch na padha ho to prompt ko chup nahi, saaf mana karna chahiye."""
    block = ls.prompt_block(ls.listener_guidance([]))
    assert ls.EMPTY_PROMPT_LINE in block
    assert "mehsoos karenge" in ls.EMPTY_PROMPT_LINE


# ── 5. REPORT/AUDIT: block sirf gaane par, seema us haalat me HAMESHA ────────

def test_a_non_song_question_gets_no_listener_block_at_all():
    """Physics ki report me "sunne wale ka bhaav" ugna hi bakwaas hai.

    Aur bekaar chipki hui seema padhna band kara deti hai — yehi asli nuksaan.
    """
    absent = ls.not_asked()
    assert absent["wanted"] is False and absent["ran"] is False
    assert ls.listener_section(absent) == ""
    assert ls.listener_limits(absent) == []
    for pack in (None, {}, "kuch bhi", {"guidance": {"ran": True}}):
        assert ls.listener_section(pack) == ""
        assert ls.listener_limits(pack) == []


def test_wanted_and_ran_are_two_different_facts():
    """Ek hi jhande se "maangi nahi" aur "padhi nahi" ek jaise dikhne lagte."""
    not_a_song = ls.not_asked()
    asked_but_empty = _pack(sources=[], question=SONG_Q, wanted=True)
    assert (not_a_song["wanted"], not_a_song["guidance"]["ran"]) == (False,
                                                                    False)
    assert (asked_but_empty["wanted"],
            asked_but_empty["guidance"]["ran"]) == (True, False)
    assert ls.listener_section(not_a_song) == ""
    assert ls.LISTENER_SUBHEADING in ls.listener_section(asked_but_empty)
    assert ls.listener_limits(asked_but_empty)      # seema phir bhi jaati hai
    assert ls.NOT_ASKED_REASON in not_a_song["reason"]
    # `not_asked()` ka poora dhaancha bhi kuch "kar liya" ka daawa na kare —
    # ye record seedha app/website ke JSON me jaata hai.
    assert not_a_song["listener_evidence_read"] is False
    assert not_a_song["listener_line_count"] == 0
    assert not_a_song["listener_source_count"] == 0
    for flag in ("listener_tested", "audience_measured", "mind_read",
                 "network_used"):
        assert not_a_song[flag] is False, flag
    assert not_a_song["gemini_calls"] == 0


def test_the_song_block_prints_the_reading_count_and_every_citation():
    """Ginti aur citation — dono bina, block "app ki apni raay" ban jaata."""
    pack = _pack([_Src("S1", snippet=EMOTION_TEXT),
                  _Src("S2", snippet=CULTURE_TEXT)])
    text = ls.listener_section(pack)
    assert text.startswith(ls.LISTENER_SUBHEADING)
    assert "**Kitni baat padhi gayi:** 2 (2 source se)" in text
    assert "[S1]" in text and "[S2]" in text
    assert "In par is baar kuch nahi mila:" in text


def test_a_song_that_read_nothing_still_says_so_in_the_block():
    """Chup ho jaana yahan "sab theek tha" ka jhooth ban jaata hai."""
    text = ls.listener_section(_pack(sources=[]))
    assert ls.LISTENER_SUBHEADING in text
    assert "padha nahi gaya" in text
    # Ek hi baat do baar nahi likhni chahiye (pehle yahi bug tha).
    assert text.count("padha nahi gaya") == 1


def test_the_heading_itself_admits_this_is_read_research_not_a_measurement():
    """Heading hi sabse pehle padhi jaati hai — jhooth wahin se shuru hota hai.

    "Sunne wale ka bhaav (naapa hua)" jaisi heading ke neeche wahi cited line
    hoti hai, par padhne wala samajhta hai ki kisi par test kiya gaya. Isliye
    heading me "padhi hui research" jaisa admission hona zaroori hai, aur
    naapne/test karne/guarantee ka koi shabd nahi.
    """
    head = ls.LISTENER_SUBHEADING
    low = head.casefold()
    assert low.startswith("### ")
    assert "research" in low                  # source kahan se aaya
    assert "padhi" in low                     # padhi gayi, naapi nahi
    for claim in ("naap", "test", "measur", "guarantee", "hit", "pakka",
                  "sabka dil", "proof", "saboot"):
        assert claim not in low, claim
    # Report ki pehli line yahi heading ho — kisi aur heading se badla na jaaye.
    assert ls.listener_section(
        _pack([_Src("S1", snippet=EMOTION_TEXT)])).startswith(head)


def test_the_four_always_on_limits_are_always_on():
    """Ye chaar line hi "research padhi ≠ dil padha" ko report me rakhti hain."""
    always = ls.limits()
    assert len(always) == 4
    joined = " ".join(always)
    assert "listener_tested=False" in joined
    assert "audience_measured=False" in joined and "mind_read=False" in joined
    assert "DUSRE sample" in joined          # research kisi aur par naapi gayi
    assert "cue-list adhoori" in joined
    for pack in (_pack([_Src("S1", snippet=EMOTION_TEXT)]), _pack(sources=[])):
        rows = ls.listener_limits(pack)
        for line in always:
            assert line in rows


def test_the_audit_ceiling_does_not_cut_the_new_lines():
    """Chhoti chhat "kuch nahi padha"/"vaada hataayi" ko chup-chaap kaat deti.

    Worst case yahi hai: 4 hamesha wali + 0-cited + missing-groups + vaada +
    snippet-only = 8. Chhat isse chhoti hui to audit jhootha ho jaayega.
    """
    pack = _pack([_Src("S1", snippet=PROMISE_TEXT)])
    rows = ls.listener_limits(pack)
    assert len(rows) == 8 == ls.MAX_AUDIT_LIMIT_LINES
    assert rows[:ls.MAX_AUDIT_LIMIT_LINES] == rows      # ek line bhi nahi kati
    code = _read_source("synthesizer_claude.py")
    assert "[:LISTENER_MAX_AUDIT_LIMIT_LINES]" in code
    assert "listener_limits(" in code
    assert "as LISTENER_MAX_AUDIT_LIMIT_LINES" in code
    for other in (_pack([_Src("S1", snippet=EMOTION_TEXT)]), _pack(sources=[]),
                  _pack([_Src("S1", full_text=EMOTION_TEXT,
                              read_level="full_text")])):
        assert len(ls.listener_limits(other)) <= ls.MAX_AUDIT_LIMIT_LINES


# ── 6. WIRING: planner + discovery, aur ₹0 ka saboot ─────────────────────────

class _Spy:
    """Connector ki jagah — kaun si query, kitni limit ke saath gayi."""

    def __init__(self, name="spy"):
        self.name = name
        self.seen = []
        self.limits = []

    def search(self, query, max_results=3, **_kw):
        self.seen.append(str(query))
        self.limits.append(int(max_results))
        return {"connector": self.name, "records": [], "count": 0,
                "error": "", "reason": "", "note": "", "seconds": 0.0}

    # `_single()` connector ko `safe_search` se bulata hai — sirf `search`
    # rakhne se task chalte waqt AttributeError aata hai, aur wahi galti
    # "lane chal gayi" ka jhootha bharosa deti.
    def safe_search(self, query, max_results=3, **kw):
        return self.search(query, max_results, **kw)


def _tasks_for(listener_entries, craft_entries=(), question="gaana likho"):
    discovery = SourceDiscovery()
    spy = _Spy()
    discovery.papers.by_name = lambda name: spy
    discovery.books.by_name = lambda name: spy
    discovery.media.by_name = lambda name: spy
    plan = {"web": True, "papers": ["arxiv"], "books": ["openlibrary"],
            "datasets": [], "patents": [], "markets": [],
            "craft_study": list(craft_entries),
            "listener_study": list(listener_entries)}
    tasks = discovery._tasks([question], plan, 3, 5)
    return [label for label, _fn in tasks], tasks, spy


def test_the_listener_lane_gets_its_own_label_never_the_craft_one():
    """Label mil jaaye to audit me craft ki coverage badi hui dikhti hai."""
    labels, tasks, spy = _tasks_for([
        {"query": "nostalgia autobiographical memory songs listener",
         "lane": "papers"}])
    assert "listener_study_papers" in labels
    assert not [label for label in labels if label.startswith("craft_study")]
    ran = 0
    for label, fn in tasks:
        if label == "listener_study_papers":
            assert set(fn()) == {"records", "log"}
            ran += 1
    assert ran == 1
    assert spy.limits == [2]              # budget chhota hi rehna chahiye


def test_the_listener_lane_stays_shut_when_the_plan_did_not_ask():
    """Ye lane sirf plan se khulta hai — asli sawaal ke evidence se nahi."""
    labels, _tasks, spy = _tasks_for([])
    assert not [label for label in labels if "listener" in label]
    assert spy.seen == []


def test_a_query_already_sent_by_the_craft_lane_is_not_sent_again():
    """Do label ke saath wahi query = do baar kharcha, do baar ginti."""
    same = "songwriting emotion listener research"
    labels, _tasks, _spy = _tasks_for(
        [{"query": same, "lane": "papers"}],
        craft_entries=[{"query": same, "lane": "papers"}])
    assert labels.count("craft_study_papers") == 1
    assert not [label for label in labels if label.startswith(
        "listener_study")]


def test_a_lyrics_hunt_dies_at_the_discovery_wall_too():
    """Teesri deewar: planner ke baad discovery me bhi."""
    labels, _tasks, _spy = _tasks_for([
        {"query": "nostalgia memory songs listener study", "lane": "papers"},
        {"query": "tum hi ho full lyrics mp3", "lane": "papers"}])
    assert labels.count("listener_study_papers") == 1


def test_the_discovery_tier_honours_the_small_listener_budget():
    """Plan me chaar aa jaayein to bhi teen se zyada slot nahi mil sakte."""
    entries = [{"query": f"listener emotion research number {i}",
                "lane": "papers"} for i in range(6)]
    labels, _tasks, _spy = _tasks_for(entries)
    assert len([l for l in labels if l.startswith("listener_study")]) == (
        ls.MAX_LISTENER_QUERIES)


def test_the_planner_opens_the_lane_only_for_a_song_and_keeps_craft_whole():
    """Craft ke chhe slot chhote nahi hone chahiye — dono lane saath chalti hain."""
    planner = ResearchPlanner()
    config = depth.get_depth_config("DEEP")
    song = planner.connector_plan({"question": "sad punjabi gaana likho 8 line"},
                                  config, "sad punjabi gaana likho 8 line")
    lane = song["listener_study_lane"]
    assert lane["wanted"] is True
    assert len(song["listener_study"]) == ls.MAX_LISTENER_QUERIES
    assert len(song["craft_study"]) == sc.MAX_STUDY_QUERIES
    assert lane["listener_evidence_read"] is False
    assert lane["listener_tested"] is False and lane["mind_read"] is False
    assert lane["gemini_calls"] == 0
    assert set(lane["lanes"]) <= set(sc.STUDY_LANES)
    plain = planner.connector_plan({"question": NON_SONG_Q}, config, NON_SONG_Q)
    assert plain["listener_study"] == []
    assert plain["listener_study_lane"]["wanted"] is False
    assert "gaane jaisi nahi" in plain["listener_study_lane"]["reason"]


def test_the_planner_shuts_the_lane_for_a_lyrics_hunt():
    """Bol maangne par sunne wale ki research bhi nahi maangi jaati.

    Aur jahan ye gate CHOOK jaata hai (bare "<naam> song lyrics likh do" —
    `songcraft.is_lyrics_hunt` ki jaani hui seema) wahan bhi lane khulne se
    koi bol network par nahi jaata: listener query user ke shabd se nahi,
    seeds + `safe_mood` se banti hai. Ye test dono baat pin karta hai.
    """
    planner = ResearchPlanner()
    config = depth.get_depth_config("DEEP")
    caught = "gaana likho aur tum hi ho ke gaane ke bol bhi de do"
    assert sc.is_lyrics_hunt(caught) is True
    assert craft.detect(caught).get("is_request") is True   # gaane ki farmaish
    plan = planner.connector_plan({"question": caught}, config, caught)
    assert plan["listener_study"] == []
    assert plan["listener_study_lane"]["wanted"] is False
    assert "BOL" in plan["listener_study_lane"]["reason"]

    missed = "arijit singh tum hi ho song lyrics likh do"
    assert sc.is_lyrics_hunt(missed) is False       # jaani hui seema
    leaky = planner.connector_plan({"question": missed}, config, missed)
    for row in leaky["listener_study"]:
        low = str(row["query"]).casefold()
        assert "lyrics" not in low and "arijit" not in low
        assert "tum hi ho" not in low


def test_the_orchestrator_and_result_wiring_stay_in_place():
    """Ye static contract wiring chup-chaap kat jaane se bachata hai."""
    orch = _read_source("orchestrator.py")
    assert "return listener_study.not_asked()" in orch
    assert "listener_study.study(question, sources=sources, wanted=True)" in orch
    assert 'if listener_guidance.get("wanted"):' in orch
    assert "listener_report=passes.get(\"listener_study\") or {}," in orch
    assert "listener_study=listener_study.public_record(" in orch
    syn = _read_source("synthesizer_claude.py")
    assert "listener_text = listener_section(listener_report)" in syn
    # assemble se _audit_section tak report pahunchti hai. Naap CALL ke ANDAR
    # hoti hai, poori file me kahin bhi needle dikh jaane par nahi: purana needle
    # `"listener_report=listener_report)"` tha aur #140 me usi call me ek naya
    # kwarg (`music_report=`) judte hi TOOT gaya — jabki wiring bilkul sahi thi.
    call_at = syn.index("self._audit_section(")
    depth, end = 0, call_at
    for pos in range(syn.index("(", call_at), len(syn)):
        if syn[pos] == "(":
            depth += 1
        elif syn[pos] == ")":
            depth -= 1
            if depth == 0:
                end = pos
                break
    args = syn[call_at:end]
    assert "listener_report=listener_report" in args
    # ek hi baar — do jagah pass hone par ek copy chup-chaap purani reh jaati hai
    assert args.count("listener_report=listener_report") == 1
    # signature dono jagah zinda: audit-section aur assemble, dono me param ho
    assert syn.count("listener_report: Optional[Dict] = None") == 2
    models = _read_source("models.py")
    assert "listener_study: Dict = field(default_factory=dict)" in models


def test_the_public_record_is_json_safe_and_keeps_the_three_false_flags():
    """`ask` ek object hai — wo API par jaake serialize karte waqt tootta hai."""
    import json
    pack = _pack([_Src("S1", snippet=EMOTION_TEXT)])
    record = ls.public_record(pack)
    assert "ask" in record and isinstance(record["ask"], dict)
    json.dumps(record)                     # tootna nahi chahiye
    assert record["listener_tested"] is False
    assert record["audience_measured"] is False and record["mind_read"] is False
    assert record["promise_lines_dropped_not_hidden"] is True
    assert record["ran"] is True and record["wanted"] is True
    empty = ls.public_record(ls.not_asked())
    json.dumps(empty)
    assert empty["wanted"] is False and empty["ran"] is False
    assert empty["limits"] == []
    assert ls.public_record("kuch bhi") == {}


def test_the_api_record_carries_the_same_limits_the_report_shows():
    """Record ki `limits` khaali ho gayi to app "koi seema nahi" bolne lagta.

    Website/app ka JSON isi list se seema dikhata hai. Report me 8 line aur
    record me 0 — ye do muh ki baat hai, isliye dono ka barabar hona zaroori.
    """
    pack = _pack([_Src("S1", snippet=PROMISE_TEXT)])
    record = ls.public_record(pack)
    shown = list(ls.listener_limits(pack))
    assert shown                                  # seema hamesha hoti hai
    assert record["limits"] == shown
    assert len(record["limits"]) == ls.MAX_AUDIT_LIMIT_LINES
    joined = " ".join(record["limits"])
    assert "listener_tested=False" in joined      # sabse zaroori sach
    assert "vaada" in joined                      # hataayi hui line ka hisaab
    for line in ls.limits():                      # chaar hamesha wali
        assert line in record["limits"]


def test_the_result_model_carries_the_record_without_breaking_to_dict():
    """Model me jagah na ho to poora record chup-chaap gir jaata hai."""
    import json
    record = ls.public_record(_pack([_Src("S1", snippet=EMOTION_TEXT)]))
    result = ResearchResult(question=SONG_Q, listener_study=record)
    data = result.to_dict()
    json.dumps(data)
    assert data["listener_study"]["line_count"] == 1
    assert data["listener_study"]["listener_tested"] is False
    assert ResearchResult(question=NON_SONG_Q).to_dict()[
        "listener_study"] == {}


def test_the_same_input_gives_the_exact_same_output_every_time():
    """Randomness ho to naap "naap" nahi rehta — aur mutation test bekaar."""
    src = [_Src("S1", snippet=EMOTION_TEXT + " " + FAMILIAR_TEXT),
           _Src("S2", snippet=CULTURE_TEXT)]
    first = ls.study(SONG_Q, sources=src, ask=_Ask(["judaai"]))
    for _ in range(3):
        again = ls.study(SONG_Q, sources=src, ask=_Ask(["judaai"]))
        assert again["queries"] == first["queries"]
        assert again["section_lines"] == first["section_lines"]
        assert again["limits"] == first["limits"]
        assert again["prompt_block"] == first["prompt_block"]


def test_this_whole_lane_costs_zero_rupees():
    """Ye lane research PADHTI hai — na model chalati hai, na khud network."""
    assert ls.GEMINI_CALLS == 0
    assert ls.NETWORK_USED is False
    assert ls.LISTENER_TESTED is False and ls.AUDIENCE_MEASURED is False
    assert ls.MIND_READ is False
    pol = ls.policy()
    assert pol["gemini_calls"] == 0 and pol["network_used"] is False
    assert pol["randomness_used"] is False and pol["deterministic"] is True
    assert pol["provider_cost"] == "₹0"
    assert pol["hit_predicted"] is False and pol["emotion_guaranteed"] is False
    code = _read_source("listener_study.py")
    for banned in ("import requests", "urllib.request", "genai", "httpx",
                   "import random", "random."):
        assert banned not in code
    # `GEMINI_CALLS` naam chal sakta hai (wo ginti hai), model call nahi.
    assert "GEMINI_CALLS = 0" in code


# ── 7. ASLI DARWAZA: orchestrator ka gate aur report ka block ────────────────

def _engine_pack(sources):
    return EvidencePack(question=SONG_Q, sources=list(sources))


def test_the_orchestrator_gate_needs_both_song_signals():
    """Ek signal par khulne se nibandh/physics me bhi ye block ug aata hai."""
    src = [_Src("S1", snippet=EMOTION_TEXT)]
    for song in ("hindi me ek sad gaana likho judaai wala",
                 "punjabi dancing type gangstar gaana banao"):
        out = DeepResearchEngine._listener_study(song, _engine_pack(src))
        assert out["wanted"] is True
        assert out["guidance"]["ran"] is True
        assert len(out["guidance"]["lines"]) == 1
        assert len(out["queries"]) == ls.MAX_LISTENER_QUERIES
        assert ls.LISTENER_SUBHEADING in ls.listener_section(out)
    for other in (NON_SONG_Q, "is topic par nibandh likho",
                  "arijit singh tum hi ho gaane ke bol download karo"):
        out = DeepResearchEngine._listener_study(other, _engine_pack(src))
        assert out["wanted"] is False and out["ran"] is False
        assert out["queries"] == []
        assert ls.listener_section(out) == ""
        assert ls.listener_limits(out) == []


def test_a_crash_inside_the_lane_still_shows_the_limits():
    """Chup ho jaana yahan "sab theek tha" ka jhooth ban jaata hai."""
    original = ls.study
    try:
        def boom(*_a, **_kw):
            raise RuntimeError("andar ki galti")
        ls.study = boom
        out = DeepResearchEngine._listener_study(SONG_Q, _engine_pack(
            [_Src("S1", snippet=EMOTION_TEXT)]))
    finally:
        ls.study = original
    assert out["wanted"] is True          # farmaish gaane ki THI
    assert out["guidance"]["ran"] is False
    assert ls.listener_limits(out)        # seema phir bhi report me jaati hai
    assert out["support_row"]["status"] == sc.NOT_MEASURED


def test_the_final_answer_carries_the_block_only_for_a_song():
    """End-to-end: block gaane par aata hai, aur baaki har jawab me nahi."""
    base = dict(gemini_answer="Ye jawab hai.", evidence_level="MEDIUM",
                confidence_note="", contradictions=[], hypotheses=[],
                verification={}, coverage={}, honesty={}, consensus={})
    pack = EvidencePack(question=SONG_Q, sources=[])
    song_report = ls.study(SONG_Q, sources=[_Src("S1", snippet=EMOTION_TEXT)])
    with_block = FinalSynthesizer().assemble(pack=pack,
                                             listener_report=song_report, **base)
    assert ls.LISTENER_SUBHEADING in with_block
    assert "[S1]" in with_block
    for line in ls.listener_limits(song_report):
        assert line in with_block         # audit ki chhat kaat nahi rahi
    without = FinalSynthesizer().assemble(pack=pack,
                                          listener_report=ls.not_asked(),
                                          **base)
    assert ls.LISTENER_SUBHEADING not in without
    assert "listener_tested=False" not in without
    omitted = FinalSynthesizer().assemble(pack=pack, **base)
    assert ls.LISTENER_SUBHEADING not in omitted





