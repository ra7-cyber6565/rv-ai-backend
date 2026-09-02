"""#140 — MUSIC DIRECTION: "research padhi" ≠ "dhun bana kar sun li".

intel ki maang ka aakhri hissa: "use sab knowelege hona chahiye ... konsa tone
bnega music kaisa bnega". #128-#132 ne music direction ke KHAANE bana diye the
(tempo, scale/raag, vaadya, aawaz) — par wo khaane app ki apni pasand se bhar
rahe the. #140 ne unke peeche PADHI HUI, cited research jodi.

Is lane ka asli khatra ek hi hai, aur ye poori file usi ke peeche padi hai:

    BPM, raag ya taal jaisa number report me aa jaane ke baad line aisi
    lagti hai jaise app ne dhun banaayi, bajaayi aur sun kar tay kiya.
    Ek bhi line ("dhun mast banegi", "70 bpm rakho") us jhooth ko sach
    jaisa bana deti hai — aur wahi baat sabse aasaani se ghus jaati hai.

Isliye har test ek naapa hua jhooth rokta hai:

  1. QUERY par pabandi — lane ka naam whitelist se, family/style ka roop bandha
     hua, bol dhoondhne wali query kabhi nahi, aur budget alag taaki craft aur
     listener ki naapi hui coverage se ek slot bhi na chhine.
  2. KHAANE udhaar ke, copy ke nahi — songcraft ke wahi regex/label, warna do
     jagah do alag "music direction" ban jaate hain.
  3. PADHNA sirf CITED — bina source id koi line nahi; daawa karne wali line
     hatti hai aur uski GINTI chhapti hai; number SOURCE-REPORTED rehta hai.
  4. NAAP teen haalat me — chali nahi / chali par kuch nahi mila / mili. Aur ye
     naya check songcraft ke purane check ke SAATH chalta hai, uski jagah nahi.
  5. GINTI ALAG — craft, listener aur music ki ginti ek dher me nahi milti.
  6. REPORT/AUDIT — block sirf gaane ki farmaish par, par us haalat me seema
     HAMESHA, aur audit ki chhat us nayi line ko kaat na de.
  7. WIRING — planner/discovery/orchestrator/model/synthesizer ka contract.
  8. ₹0 — 0 Gemini call, 0 network, koi randomness nahi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import depth  # noqa: E402
from research_engine import listener_study as ls  # noqa: E402
from research_engine import music_study as ms  # noqa: E402
from research_engine import songcraft as sc  # noqa: E402
from research_engine.models import EvidencePack, ResearchResult  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402
from research_engine.planner import ResearchPlanner  # noqa: E402
from research_engine.source_discovery import SourceDiscovery  # noqa: E402
from research_engine.synthesizer_claude import FinalSynthesizer  # noqa: E402

SONG_Q = "hindi me ek sad gaana likho judaai wala"
NON_SONG_Q = "room temperature superconductivity ka mechanism samjhao"

TEMPO_TEXT = (
    "A slow tempo near 70 bpm is read as sad in listening research.")
SCALE_TEXT = (
    "Composers pick a minor scale when the intended mood is grief or loss.")
INSTRUMENT_TEXT = (
    "A bansuri and light tabla keep a sad ballad intimate without crowding.")
VOICE_TEXT = (
    "A female vocal with a soft delivery is common on such tracks.")
ARRANGE_TEXT = (
    "A sparse arrangement leaves space between phrases and feels intimate.")
KEY_TEXT = (
    "Producers often work in the key of C for this kind of ballad song.")
# Ye line JAAN-BOOJH kar do kaam karti hai: ek field regex bhi match karti hai
# (groove) aur bina-naap daawa bhi karti hai (melody ... mast). Sirf daawa hota
# to line field ke stage par hi gir jaati aur "drop hua" ka test jhootha GREEN
# de deta.
CLAIM_TEXT = (
    "The melody is mast and the tabla groove is perfect for this song.")
JUNK_TEXT = (
    "Subscribe to our newsletter for more tempo and groove tips today.")
SHORT_TEXT = "Slow tempo works."
OFFTOPIC_TEXT = (
    "Nothing relevant at all here about anything else entirely.")


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
    """`songcraft.StyleAsk` ki jagah — is lane ko sirf do field chahiye."""

    def __init__(self, tempo_family="slow", primary="sad_slow"):
        self.tempo_family = tempo_family
        self.primary = primary


def _pack(sources=(), question=SONG_Q, wanted=True):
    return ms.study(question, sources=list(sources), wanted=wanted)


def _read_source(name):
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "research_engine", name)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# ── 1. QUERY par pabandi ─────────────────────────────────────────────────────

def test_music_queries_stay_inside_the_known_lane_names():
    """Anjaan lane ka matlab: routing use pehchaanegi nahi.

    Us haalat me query chup-chaap web par gir jaati aur report me lane ka naam
    jhooth ban jaata ("kitaab se padha" jabki web se aaya).
    """
    assert sc.STUDY_LANES == ("web", "books", "papers", "media")
    for _query, lane, _why in ms.MUSIC_SEEDS:
        assert lane in sc.STUDY_LANES
    for row in ms.study_queries(_Ask(), limit=99):
        assert row["lane"] in sc.STUDY_LANES
        assert row["query"] and row["why"]


def test_every_music_query_is_new_work_not_craft_or_listener_work():
    """Wahi query dobara bhejne se do lane ek hi cheez padhti hain.

    Aur "music direction ki research" ki ginti craft/listener ke bal par badh
    jaati — wahi ginti-ka-jhooth jise ye poora batch rokta hai.
    """
    craft_rows = sc.study_queries(sc.style_of(SONG_Q), limit=99)
    craft_queries = {str(row["query"]).casefold() for row in craft_rows}
    listener_queries = {str(row["query"]).casefold()
                        for row in ls.study_queries(limit=99)}
    assert craft_queries and listener_queries      # dono lane sach me chalti
    for row in ms.study_queries(_Ask(), limit=99):
        low = row["query"].casefold()
        assert low not in craft_queries
        assert low not in listener_queries


def test_the_tempo_family_shapes_the_first_query_and_keeps_its_reason():
    """Family na lage to lane har gaane ke liye ek hi query bhejti hai."""
    rows = ms.study_queries(_Ask(tempo_family="mid"), limit=3)
    assert rows[0]["query"].startswith("mid ")
    assert rows[0]["lane"] == "papers"
    assert "'mid'" in rows[0]["why"]
    assert len(rows) == 3


def test_the_style_name_shapes_the_second_query():
    """Style na lage to "sad slow" aur "punjabi dance" ek hi research padhte."""
    rows = ms.study_queries(_Ask(primary="punjabi_dance"), limit=3)
    assert rows[1]["query"].startswith("punjabi dance ")
    assert rows[1]["lane"] == "books"
    assert "'punjabi dance'" in rows[1]["why"]


def test_a_free_text_family_or_style_can_never_become_a_network_query():
    """Ye pehli deewar hai, aur jaan-boojh kar hai.

    Family/style se query BANTI hai, isliye unka roop hi bandha hua hai: chhota
    ASCII shabd. Warna user ke shabd (ya gaane ka naam) query me chale jaate.
    Roop galat ho to wo hissa chhoot jaata hai — seeds phir bhi chalti hain.
    """
    assert ms.safe_family("slow") == "slow"
    assert ms.safe_family("  MID  ") == "mid"
    for bad in ("", "  ", "a", "slowest", "स्लो", "slow;rm -rf", "slow 2"):
        assert ms.safe_family(bad) == ""
    assert ms.safe_style("sad_slow") == "sad slow"
    assert ms.safe_style("  Sad_Slow ") == "sad slow"
    for bad in ("", "a", "x" * 24, "sad slow", "गम", "sad;rm"):
        assert ms.safe_style(bad) == ""
    rows = ms.study_queries(_Ask("tum hi ho song lyrics",
                                 "tum hi ho song lyrics"), limit=99)
    assert all("lyrics" not in r["query"].casefold() for r in rows)
    assert len(rows) == len(ms.MUSIC_SEEDS)


def test_a_lyrics_hunt_query_is_dropped_even_if_it_is_a_seed_shape():
    """Bol/karaoke/mp3 wali query is lane se network par nahi jaati."""
    original = ms.MUSIC_SEEDS
    try:
        ms.MUSIC_SEEDS = (
            ("tum hi ho song lyrics download mp3", "papers", "test"),
            ("raga bhava rasa indian classical music emotion theory", "books",
             "theek query"),
        )
        rows = ms.study_queries(limit=99)
        assert [r["query"] for r in rows] == [
            "raga bhava rasa indian classical music emotion theory"]
    finally:
        ms.MUSIC_SEEDS = original


def test_a_too_short_or_unknown_lane_query_never_ships():
    """Do chhoti pabandi jo chup-chaap todi ja sakti thi."""
    original = ms.MUSIC_SEEDS
    try:
        ms.MUSIC_SEEDS = (
            ("tempo", "papers", "bahut chhoti"),
            ("music tone and timbre study", "podcast", "anjaan lane"),
            ("music tempo rhythm arousal emotion perception research", "papers",
             "ok"),
        )
        rows = ms.study_queries(limit=99)
        assert [r["query"] for r in rows] == [
            "music tempo rhythm arousal emotion perception research"]
    finally:
        ms.MUSIC_SEEDS = original
    assert ms.MIN_QUERY_CHARS == 8


def test_the_same_query_is_never_shipped_twice():
    """Do baar wahi query = do baar wahi kharcha aur do baar wahi ginti."""
    original = ms.MUSIC_SEEDS
    try:
        seed = ("music tempo rhythm arousal emotion perception research",
                "papers", "a")
        ms.MUSIC_SEEDS = (seed, seed,
                          ("  Music   Tempo rhythm AROUSAL emotion perception "
                           "RESEARCH  ", "books", "b"))
        rows = ms.study_queries(limit=99)
        assert len(rows) == 1
    finally:
        ms.MUSIC_SEEDS = original


def test_the_music_budget_is_its_own_and_small():
    """Craft aur listener ka budget alag hai — yehi coverage bachata hai.

    Ek hi budget me se teen lane khaane lagein to craft ki naapi hui coverage
    chup-chaap gir jaati, aur "gaana likhne ka hunar" wali query kat jaati.
    """
    assert ms.MAX_MUSIC_QUERIES == 3
    assert ls.MAX_LISTENER_QUERIES == 3
    assert sc.MAX_STUDY_QUERIES == 6
    assert ms.MAX_MUSIC_QUERIES < sc.MAX_STUDY_QUERIES
    assert len(ms.study_queries(_Ask())) == 3
    assert len(ms.study_queries(_Ask(), limit=1)) == 1
    assert len(ms.study_queries(_Ask(), limit=0)) == 1


def test_the_plan_dict_says_query_bani_but_kuch_suna_nahi():
    """Query ban jaana padhna NAHI hai, aur padhna sunna NAHI hai."""
    plan = ms.study_plan(_Ask())
    lane = plan["music_study_lane"]
    assert len(plan["music_study"]) == 3
    assert lane["wanted"] is True and lane["query_count"] == 3
    assert lane["music_evidence_read"] is False
    assert lane["audio_generated"] is False and lane["tune_made"] is False
    assert lane["heard"] is False and lane["play_tested"] is False
    assert lane["lyrics_hunt_blocked"] is True
    assert lane["gemini_calls"] == 0 and lane["network_used_here"] is False
    assert set(lane["lanes"]) <= set(sc.STUDY_LANES)
    # Wahi plan `study()` ke jawab me bhi jaata hai. Ye jhande wahin se
    # orchestrator/audit tak pahunchte hain — plan khaali ho jaaye to "query bani
    # par padha nahi" ka hisaab chup-chaap gayab ho jaata hai.
    from_study = _pack([])["plan"]
    assert len(from_study["music_study"]) == 3
    assert from_study["music_study_lane"]["query_count"] == 3
    assert from_study["music_study_lane"]["music_evidence_read"] is False
    assert from_study["music_study_lane"]["lyrics_hunt_blocked"] is True


# ── 2. KHAANE udhaar ke, copy ke nahi ────────────────────────────────────────

def test_the_field_keys_come_from_songcraft_not_from_a_second_list():
    """Do jagah do list = do alag "music direction", aur dono aadhe sach.

    songcraft me ek naya khaana jud jaaye aur yahan na jude, to report kehti
    "is khaane par kuch nahi mila" jabki padha hi nahi gaya.
    """
    assert ms.SONGCRAFT_FIELD_KEYS == tuple(
        key for key, _regex in sc._MUSIC_FIELD_RES)
    assert ms.FIELD_KEYS == ms.SONGCRAFT_FIELD_KEYS + (ms.ARRANGEMENT_KEY,)
    assert len(ms.FIELD_KEYS) == len(sc.MUSIC_DIRECTION_FIELDS) + 1
    assert sc.MIN_MUSIC_FIELDS == 3


def test_the_field_labels_are_songcrafts_own_words():
    """Label badal gaya to user ko do naam dikhte ek hi cheez ke."""
    for key, label in zip(ms.SONGCRAFT_FIELD_KEYS, sc.MUSIC_DIRECTION_FIELDS):
        assert ms.FIELD_LABELS[key] == label
    assert ms.FIELD_LABELS[ms.ARRANGEMENT_KEY] == ms.ARRANGEMENT_LABEL
    assert set(ms.FIELD_LABELS) == set(ms.FIELD_KEYS)


def test_arrangement_is_the_only_extra_field_and_it_is_labelled_plainly():
    """Naya khaana chhup kar na jude — warna craft ka naap bhi hil jaata."""
    extra = [key for key in ms.FIELD_KEYS
             if key not in ms.SONGCRAFT_FIELD_KEYS]
    assert extra == [ms.ARRANGEMENT_KEY] == ["arrangement"]
    assert ms.field_of(ARRANGE_TEXT) == ms.ARRANGEMENT_KEY
    assert "khaali jagah" in ms.ARRANGEMENT_LABEL


def test_each_sentence_lands_on_the_field_it_is_really_about():
    """Galat khaane me chali gayi line report me galat salaah ban jaati hai."""
    assert ms.field_of(TEMPO_TEXT) == "tempo"
    assert ms.field_of(SCALE_TEXT) == "scale_or_raag"
    assert ms.field_of(INSTRUMENT_TEXT) == "instruments"
    assert ms.field_of(VOICE_TEXT) == "voice"
    assert ms.field_of(ARRANGE_TEXT) == "arrangement"


def test_a_sentence_about_nothing_musical_gets_no_field_at_all():
    """Har line ko koi khaana de dena = report bhar dena bina padhe."""
    assert ms.field_of(OFFTOPIC_TEXT) == ""
    assert ms.field_of("") == ""
    assert ms.field_of("   ") == ""


def test_the_cue_list_admits_it_is_incomplete():
    """"Is khaane par kuch nahi mila" ≠ "research me kuch nahi tha"."""
    assert ms.CUE_LIST_IS_NOT_EXHAUSTIVE is True
    assert ms.policy()["cue_list_is_not_exhaustive"] is True
    joined = " ".join(ms.limits())
    assert "list adhoori" in joined


# ── 3. PADHNA sirf CITED ─────────────────────────────────────────────────────

def test_a_line_without_a_source_id_never_becomes_guidance():
    """Bina citation ek baat "research kehti hai" ban jaati hai — wahi jhooth."""
    anon = _Src("", snippet=TEMPO_TEXT)
    good = _Src("S1", snippet=SCALE_TEXT)
    report = ms.music_guidance([anon, good])
    assert [row["source_id"] for row in report["lines"]] == ["S1"]
    assert report["sources_scanned"] == 2      # dono padhe gaye
    assert report["source_count"] == 1         # par ek hi cite ho saka


def test_every_reported_line_carries_its_source_id_everywhere():
    """Ek jagah citation gir jaaye to wahi line "app ki apni baat" ban jaati."""
    report = ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT),
                                _Src("S2", snippet=INSTRUMENT_TEXT)])
    pack = {"wanted": True, "guidance": report}
    for row in report["lines"]:
        assert row["source_id"] and row["text"]
        assert row["field"] in ms.FIELD_KEYS
        assert row["field_label"] == ms.FIELD_LABELS[row["field"]]
        assert row["url"] and row["connector"] and row["read_level"]
    for text in (ms.prompt_block(report), ms.music_section(pack),
                 "\n".join(ms.section_lines(report))):
        for row in report["lines"]:
            assert f"[{row['source_id']}]" in text


def test_a_line_that_promises_a_great_tune_is_dropped_and_counted():
    """Yehi wo line hai jo "app ne dhun sun li" ka jhooth banati hai.

    Sirf hata dena kaafi nahi — GINTI chhapni chahiye, warna audit me pata hi
    nahi chalta ki source me aisi baat thi.
    """
    report = ms.music_guidance([_Src("S1", snippet=CLAIM_TEXT)])
    assert sc.music_claims_in(CLAIM_TEXT)       # line sach me daawa karti hai
    assert ms.field_of(CLAIM_TEXT) == "tempo"   # aur field bhi match karti hai
    assert report["lines"] == []
    assert report["claim_lines_dropped"] == 1
    assert report["ran"] is True                # padha gaya, mila kuch nahi
    joined = " ".join(ms.limits(report))
    assert "1 line hataayi gayi" in joined


def test_junk_navigation_and_tiny_lines_never_become_guidance():
    """Cookie/subscribe wali line "research" ban jaana sabse sasta jhooth hai."""
    report = ms.music_guidance([_Src("S1", snippet=" ".join(
        [JUNK_TEXT, SHORT_TEXT, TEMPO_TEXT]))])
    assert [row["text"] for row in report["lines"]] == [TEMPO_TEXT]
    assert len(SHORT_TEXT) < sc.MIN_GUIDANCE_CHARS
    assert sc.MIN_GUIDANCE_CHARS == 30 and sc.MAX_GUIDANCE_CHARS == 240


def test_a_very_long_line_is_clipped_not_pasted_whole():
    """Poora paragraph chipak jaaye to prompt me rules ka dhyaan hat jaata hai.

    Aur report me ek line poore page jaisi dikhti hai — "bahut research padhi"
    ka jhootha ehsaas. Lambai ki chhat songcraft se aati hai (copy nahi).
    """
    long_line = ("A slow tempo is read as sad in listening research "
                 + "and the same holds across many recordings " * 8) + "."
    assert len(long_line) > sc.MAX_GUIDANCE_CHARS == 240
    report = ms.music_guidance([_Src("S1", snippet=long_line)])
    assert len(report["lines"]) == 1
    assert len(report["lines"][0]["text"]) == sc.MAX_GUIDANCE_CHARS
    assert report["lines"][0]["text"] in long_line


def test_the_same_sentence_from_two_sources_is_counted_once():
    """Wahi line do baar = report me "do baar research" ka jhooth."""
    report = ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT),
                                _Src("S2", snippet=TEMPO_TEXT)])
    assert len(report["lines"]) == 1
    assert report["source_count"] == 1
    assert report["sources_scanned"] == 2


def test_one_source_can_not_fill_the_whole_music_block():
    """Ek hi page se poora block bhar jaana "kai source se padha" jhooth deta."""
    report = ms.music_guidance([_Src("S1", snippet=" ".join(
        [TEMPO_TEXT, SCALE_TEXT, INSTRUMENT_TEXT]))])
    assert len(report["lines"]) == sc.MAX_GUIDANCE_PER_SOURCE == 2
    assert report["source_count"] == 1


def test_the_music_block_has_a_hard_ceiling_of_its_own():
    """Bahut si line = report me research ka dher, padhne wale ka bhrosa jhootha."""
    lines = [f"A slow tempo of {60 + i} bpm suits this sad recording line {i}."
             for i in range(8)]
    sources = [_Src(f"S{i // 2 + 1}", snippet=" ".join(lines[i:i + 2]))
               for i in range(0, 8, 2)]
    report = ms.music_guidance(sources)
    assert len(report["lines"]) == ms.MAX_MUSIC_LINES == 6
    assert ms.MAX_MUSIC_LINES < sc.MAX_GUIDANCE_LINES


def test_no_source_means_ran_false_and_that_is_not_ok():
    """"Chali nahi" ko "sab theek hai" kehna is poore batch ka mool jhooth hai."""
    empty = ms.music_guidance([])
    assert empty["ran"] is False
    assert empty["lines"] == [] and empty["source_count"] == 0
    assert empty["missing_fields"] == list(ms.FIELD_KEYS)
    row = ms.support_row(empty)
    assert row["status"] == sc.NOT_MEASURED
    assert "naapa hi nahi gaya" in row["note"]
    # Audit me bhi ye haalat apni alag line se dikhti hai — chaar hamesha wali
    # ke SAATH paanchvi. Ye line chhup jaaye to "chali nahi" aur "theek chali"
    # ek jaise padhte hain.
    lines = ms.limits(empty)
    assert len(lines) == ms.ALWAYS_LIMIT_LINES + 1 == 5
    assert "chali hi nahi" in " ".join(lines)


def test_a_source_with_nothing_musical_still_counts_as_read():
    """Padha aur kuch nahi mila — ye "padha hi nahi" se alag haalat hai."""
    report = ms.music_guidance([_Src("S1", snippet=OFFTOPIC_TEXT)])
    assert report["ran"] is True
    assert report["lines"] == [] and report["sources_scanned"] == 1
    assert ms.support_row(report)["status"] == sc.NOT_MET
    # Aur audit me saaf likha jaata hai ki source padhe gaye par music ki ek
    # bhi cited baat nahi mili — warna khaali block "sab theek hai" lagta hai.
    assert "ek bhi cited baat nahi mili" in " ".join(ms.limits(report))


def test_a_number_read_from_a_source_stays_source_reported():
    """BPM/key/taal app ka faisla ban jaaye — yahi sabse mehnga jhooth hai."""
    assert ms.reported_numbers_in(
        "The track sits at 92 BPM in the key of D with a 6/8 time feel.") == [
            "92 BPM", "key of D", "6/8 time"]
    assert ms.reported_numbers_in(OFFTOPIC_TEXT) == []
    report = ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT),
                                _Src("S2", snippet=KEY_TEXT)])
    assert report["reported_number_count"] == 2
    values = [row["value"] for row in report["reported_numbers"]]
    assert values == ["70 bpm", "key of C"]
    for row in report["reported_numbers"]:
        assert row["label"] == ms.REPORTED_NUMBER_LABEL == "SOURCE-REPORTED"
        assert row["source_id"] in ("S1", "S2")


def test_how_deep_the_source_was_read_is_never_rounded_up():
    """Snippet ko "poori kitaab padhi" kehna access-depth ka jhooth hai."""
    snippet = ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT)])
    assert snippet["full_text_source_count"] == 0
    assert snippet["lines"][0]["read_level"] == "snippet"
    joined = " ".join(ms.limits(snippet))
    assert "sirf snippet/abstract tha" in joined
    full = ms.music_guidance([_Src("S1", full_text=TEMPO_TEXT,
                                   read_level="full_text",
                                   connector="openlibrary")])
    assert full["full_text_source_count"] == 1
    assert full["lines"][0]["read_level"] == "full_text"
    assert full["lines"][0]["connector"] == "openlibrary"
    assert "sirf snippet/abstract tha" not in " ".join(ms.limits(full))


def test_a_users_own_file_is_marked_as_his_own_file():
    """User ki di hui copy "duniya ki research" nahi hai — label alag rehta."""
    report = ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT,
                                     connector="user_document")])
    assert report["lines"][0]["user_supplied"] is True
    assert ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT)])["lines"][0][
        "user_supplied"] is False


# ── 4. NAAP teen haalat me, aur naya check purane ke SAATH ───────────────────

def test_the_support_row_has_exactly_three_honest_states():
    """Do haalat ek ho jaayein to "chali nahi" chup-chaap "theek hai" ban jaata."""
    met = ms.support_row(ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT)]))
    assert met["status"] == sc.MET
    assert met["measured"] == "1 cited baat / 1 source"
    assert "ye saboot nahi ki dhun achhi lagegi" in met["note"]
    not_met = ms.support_row(ms.music_guidance([_Src("S1",
                                                     snippet=OFFTOPIC_TEXT)]))
    assert not_met["status"] == sc.NOT_MET
    assert not_met["measured"] == "0 cited baat / 1 source padhe"
    assert "bina padhi hui authority" in not_met["note"]
    not_measured = ms.support_row(ms.music_guidance([]))
    assert not_measured["status"] == sc.NOT_MEASURED
    # Teeno haalat me "kyu" ka jawab bhi pin hai: sirf NOT_MEASURED apni wajah
    # likhti hai ("padha hi nahi gaya"). Ye wajah gayab ho jaaye to audit me
    # "naapa nahi gaya" aur "naap fail hua" ek jaise padhte hain.
    assert not_measured["reason"] == "koi source padha hi nahi gaya"
    assert met["reason"] == "" and not_met["reason"] == ""
    assert {met["status"], not_met["status"], not_measured["status"]} == {
        sc.MET, sc.NOT_MET, sc.NOT_MEASURED}
    assert ms.support_row(None)["status"] == sc.NOT_MEASURED


def test_the_new_check_never_takes_the_old_checks_place():
    """songcraft ka `music_direction_present` waise hi chalta rehna chahiye.

    "jo phle bna h unko htana mt" — naya check uske SAATH aata hai. Ek doosre ki
    jagah le le to purani naapi hui coverage chup-chaap gir jaati hai.
    """
    assert ms.CHECK_NAME == "music_direction_cited"
    assert ms.COMPANION_CHECK_NAME == "music_direction_present"
    assert ms.CHECK_NAME != ms.COMPANION_CHECK_NAME
    assert ms.policy()["replaces_music_direction_present"] is False
    assert ms.policy()["merged_into_craft_guidance"] is False
    assert "music_direction_present" in _read_source("songcraft.py")
    record = ms.public_record(_pack([_Src("S1", snippet=TEMPO_TEXT)]))
    assert record["companion_check"] == ms.COMPANION_CHECK_NAME
    assert record["replaces_music_direction_present"] is False


def test_no_check_name_ever_claims_the_tune_works():
    """Aisa naam naap me aa jaaye to naap khud jhooth bol dega.

    Isliye do baat pin hai: ye naam kisi bhi haalat me report/record/support-row
    me nahi nikalte, aur songcraft ne bhi aisa koi check kabhi nahi banaya.
    """
    assert len(ms.FORBIDDEN_CHECK_NAMES) == 8
    assert ms.CHECK_NAME not in ms.FORBIDDEN_CHECK_NAMES
    assert ms.COMPANION_CHECK_NAME not in ms.FORBIDDEN_CHECK_NAMES
    assert ms.CHECK_NAME not in sc.FORBIDDEN_CHECK_NAMES
    assert ms.COMPANION_CHECK_NAME not in sc.FORBIDDEN_CHECK_NAMES
    packs = [_pack([_Src("S1", snippet=TEMPO_TEXT)]),
             _pack([_Src("S1", snippet=CLAIM_TEXT)]),
             _pack(sources=[]), ms.not_asked()]
    for banned in tuple(ms.FORBIDDEN_CHECK_NAMES) + tuple(
            sc.FORBIDDEN_CHECK_NAMES):
        for pack in packs:
            shown = " ".join([ms.music_section(pack), str(ms.public_record(
                pack)), " ".join(ms.music_limits(pack)),
                str(pack["support_row"]), pack["prompt_block"]])
            assert banned not in shown, banned



def test_what_this_lane_can_never_measure_is_written_down():
    """Jo naapa nahi ja sakta wo likha hona chahiye, warna log maan lete hain."""
    assert len(ms.CANNOT_MEASURE_EXTRA) == 3
    joined = " ".join(ms.CANNOT_MEASURE_EXTRA).casefold()
    assert "suna hi nahi" in joined
    assert "bpm" in joined
    assert "aawaz" in joined
    pack = _pack([_Src("S1", snippet=TEMPO_TEXT)])
    for line in ms.CANNOT_MEASURE_EXTRA:
        assert line in pack["cannot_measure"]


# ── 5. GINTI ALAG ────────────────────────────────────────────────────────────

def test_the_music_count_is_never_mixed_with_craft_or_listener():
    """Teen ginti ek dher me mil jaaye to teen lane ka sach ek jhooth ban jaata."""
    pack = _pack([_Src("S1", snippet=TEMPO_TEXT),
                  _Src("S2", snippet=INSTRUMENT_TEXT)])
    assert pack["music_line_count"] == 2
    assert pack["music_source_count"] == 2
    record = ms.public_record(pack)
    assert record["line_count"] == 2 and record["source_count"] == 2
    assert "craft_line_count" not in record
    assert "listener_line_count" not in record
    assert record["merged_into_craft_guidance"] is False


def test_the_dropped_claim_count_is_shown_not_swallowed():
    """Ginti chhup jaaye to "source saaf tha" ka jhooth ban jaata hai."""
    pack = _pack([_Src("S1", snippet=CLAIM_TEXT)])
    record = ms.public_record(pack)
    assert record["claim_lines_dropped"] == 1
    assert record["claim_lines_dropped_not_hidden"] is True
    assert ms.policy()["claim_lines_dropped_not_hidden"] is True


def test_music_evidence_read_is_false_until_something_is_actually_read():
    """"Query bani" ko "evidence padha" kehna sabse purana jhooth hai."""
    assert _pack(sources=[])["music_evidence_read"] is False
    assert _pack([_Src("S1", snippet=OFFTOPIC_TEXT)])[
        "music_evidence_read"] is False
    assert _pack([_Src("S1", snippet=TEMPO_TEXT)])[
        "music_evidence_read"] is True


# ── 6. REPORT, PROMPT aur AUDIT ki chhat ─────────────────────────────────────

def test_the_prompt_block_is_capped_and_always_carries_the_rules():
    """Prompt me line badh jaayein to model ka dhyaan rules se hat jaata hai."""
    lines = [f"A slow tempo of {60 + i} bpm suits this sad recording line {i}."
             for i in range(8)]
    sources = [_Src(f"S{i // 2 + 1}", snippet=" ".join(lines[i:i + 2]))
               for i in range(0, 8, 2)]
    report = ms.music_guidance(sources)
    block = ms.prompt_block(report)
    cited = [line for line in block.splitlines() if line.startswith("- (")]
    assert len(cited) <= ms.MAX_PROMPT_LINES == 5
    for rule in ms.PROMPT_RULES:
        assert rule in block
    assert len(ms.PROMPT_RULES) == 3


def test_the_empty_prompt_line_still_forbids_authority_numbers():
    """Kuch na padha ho to model apne se BPM/raag likh deta — wahi rokna hai.

    Aur is haalat me teen rule aur bhi zaroori hain, isliye ye khaali block bhi
    unhe leke aata hai — sirf ek "kuch nahi mila" line chhod dena kaafi nahi.
    """
    block = ms.prompt_block(ms.music_guidance([]))
    assert ms.EMPTY_PROMPT_LINE in block
    # Pehle KHUD us line par: pabandi usi ek line me honi chahiye, teeno rule ke
    # sahaare nahi — warna line "kuch nahi mila" tak sikud jaaye aur block ke
    # baaki shabd test ko GREEN rakhte rahein.
    only = ms.EMPTY_PROMPT_LINE.casefold()
    assert "padha nahi" in only
    assert "authority" in only
    assert "bpm" in only and "raag" in only
    low = block.casefold()
    assert "padha nahi" in low
    assert "authority" in low
    assert "bpm" in low and "raag" in low
    assert "[s" not in low                    # koi citation ho hi nahi sakti
    for rule in ms.PROMPT_RULES:
        assert rule in block
    assert ms.prompt_block(None) == block


def test_the_subheading_admits_no_tune_was_made():
    """Heading hi pehla sach hai — usi par log poora block padhte hain."""
    head = ms.MUSIC_SUBHEADING
    low = head.casefold()
    assert low.startswith("### ")
    assert "research" in low                  # source kahan se aaya
    assert "padhi" in low                     # padhi gayi, banayi nahi
    assert "koi dhun nahi bani" in low        # sabse zaroori admission
    for claim in ("naap", "test", "measur", "guarantee", "hit", "pakka",
                  "sunn", "proof", "saboot"):
        assert claim not in low, claim
    assert ms.music_section(
        _pack([_Src("S1", snippet=TEMPO_TEXT)])).startswith(head)


def test_the_section_stays_silent_when_the_song_was_never_asked_for():
    """Physics ke jawab me "kaunsa raag lagao" chipak jaana bakwaas hai."""
    not_asked = ms.not_asked()
    assert ms.music_section(not_asked) == ""
    assert ms.music_limits(not_asked) == []
    assert not_asked["wanted"] is False and not_asked["ran"] is False
    assert "gaane jaisi nahi" in not_asked["reason"]
    # Lane chali hi nahi to PAANCHON khaane khaali gine jaate hain — "koi khaana
    # khaali nahi" likh dena hi wo jhooth hai jo "sab dekh liya" jaisa lagta hai.
    blank = not_asked["guidance"]
    assert blank["missing_fields"] == list(ms.FIELD_KEYS)
    assert blank["missing_field_labels"] == [ms.FIELD_LABELS[key]
                                             for key in ms.FIELD_KEYS]
    quiet = _pack([_Src("S1", snippet=TEMPO_TEXT)], question=NON_SONG_Q,
                  wanted=False)
    assert ms.music_section(quiet) == ""
    assert ms.music_limits(quiet) == []
    assert ms.music_section(None) == "" and ms.music_limits(None) == []


def test_the_section_shows_the_counts_the_fields_and_the_numbers():
    """Report me ginti aur khaane dono chahiye — warna sirf bhaashan bachta hai."""
    text = ms.music_section(_pack([_Src("S1", snippet=TEMPO_TEXT),
                                   _Src("S2", snippet=KEY_TEXT)]))
    assert ms.MUSIC_SUBHEADING in text
    assert "2 (2 source se)" in text
    assert "tempo/feel" in text and "scale ya raag" in text
    assert "SOURCE-REPORTED" in text
    assert "70 bpm [S1]" in text
    assert "In khaano par is baar kuch nahi mila:" in text
    # Jawab ke andar wali chhoti list bhi wahi do baat leke aati hai: ginti, aur
    # "peeche PADHI HUI baat" — is shabd ke bina line "app ki apni salaah" jaisi
    # padhne lagti hai.
    short = ms.section_lines(ms.music_guidance([_Src("S1", snippet=TEMPO_TEXT),
                                               _Src("S2", snippet=KEY_TEXT)]))
    assert ("**Music direction ke peeche padhi hui baat:** 2 baat, 2 source se"
            == short[0])


def test_the_four_always_on_limits_are_always_on():
    """Ye chaar line hi "padhi hui research ≠ suni hui dhun" ko report me rakhti."""
    always = ms.limits()
    assert len(always) == 4 == ms.ALWAYS_LIMIT_LINES
    joined = " ".join(always)
    assert "audio_generated=False" in joined and "tune_made=False" in joined
    assert "heard=False" in joined and "play_tested=False" in joined
    assert "DUSRE gaanon" in joined           # research kisi aur par naapi gayi
    assert "list adhoori" in joined
    for pack in (_pack([_Src("S1", snippet=TEMPO_TEXT)]), _pack(sources=[]),
                 _pack([_Src("S1", snippet=CLAIM_TEXT)])):
        rows = ms.music_limits(pack)
        for line in always:
            assert line in rows


def test_the_always_on_ceiling_is_derived_not_typed_by_hand():
    """Hand-typed number list ke saath chup-chaap galat ho jaata hai."""
    assert ms.ALWAYS_LIMIT_LINES == len(ms._ALWAYS_LIMITS) == len(ms.limits())
    assert ms.SITUATIONAL_LIMIT_LINES == 5
    assert ms.MAX_AUDIT_LIMIT_LINES == (ms.ALWAYS_LIMIT_LINES
                                        + ms.SITUATIONAL_LIMIT_LINES) == 9


def test_the_audit_ceiling_does_not_cut_the_new_lines():
    """Chhoti chhat "kuch nahi padha"/"daawa hataayi" ko chup-chaap kaat deti.

    Worst case yahi hai: 4 hamesha wali + missing-khaane + SOURCE-REPORTED
    number + hataayi hui daawa-line + snippet-only = 8. Chhat isse chhoti hui to
    audit jhootha ho jaayega.
    """
    pack = _pack([_Src("S1", snippet=TEMPO_TEXT + " " + CLAIM_TEXT)])
    rows = ms.music_limits(pack)
    assert len(rows) == 8 <= ms.MAX_AUDIT_LIMIT_LINES
    assert rows[:ms.MAX_AUDIT_LIMIT_LINES] == rows      # ek line bhi nahi kati
    code = _read_source("synthesizer_claude.py")
    assert "[:MUSIC_MAX_AUDIT_LIMIT_LINES]" in code
    assert "music_limits(" in code
    assert "as MUSIC_MAX_AUDIT_LIMIT_LINES" in code
    for other in (_pack([_Src("S1", snippet=TEMPO_TEXT)]), _pack(sources=[]),
                  _pack([_Src("S1", snippet=CLAIM_TEXT)]),
                  _pack([_Src("S1", full_text=TEMPO_TEXT,
                              read_level="full_text")])):
        assert len(ms.music_limits(other)) <= ms.MAX_AUDIT_LIMIT_LINES


def test_the_audit_and_the_report_never_show_different_limits():
    """Report me 8 line aur record me 0 — ye do muh ki baat hai."""
    pack = _pack([_Src("S1", snippet=TEMPO_TEXT + " " + CLAIM_TEXT)])
    record = ms.public_record(pack)
    shown = list(ms.music_limits(pack))
    assert shown and record["limits"] == shown
    joined = " ".join(record["limits"])
    assert "tune_made=False" in joined            # sabse zaroori sach
    assert "1 line hataayi gayi" in joined        # hataayi hui line ka hisaab
    for line in ms.limits():                      # chaar hamesha wali
        assert line in record["limits"]


# ── 7. WIRING: planner, discovery, orchestrator, model, report ───────────────

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
    # "lane chal gayi" ka jhootha bharosa deti hai.
    def safe_search(self, query, max_results=3, **kw):
        return self.search(query, max_results, **kw)


def _tasks_for(music_entries, craft_entries=(), listener_entries=(),
               question="gaana likho"):
    discovery = SourceDiscovery()
    spy = _Spy()
    discovery.papers.by_name = lambda name: spy
    discovery.books.by_name = lambda name: spy
    discovery.media.by_name = lambda name: spy
    plan = {"web": True, "papers": ["arxiv"], "books": ["openlibrary"],
            "datasets": [], "patents": [], "markets": [],
            "craft_study": list(craft_entries),
            "listener_study": list(listener_entries),
            "music_study": list(music_entries)}
    tasks = discovery._tasks([question], plan, 3, 5)
    return [label for label, _fn in tasks], tasks, spy


def test_the_music_lane_gets_its_own_label_never_the_craft_one():
    """Label mil jaaye to audit me craft ki coverage badi hui dikhti hai."""
    labels, tasks, spy = _tasks_for([
        {"query": "music tempo emotion research study", "lane": "papers"}])
    assert "music_study_papers" in labels
    assert not [label for label in labels if label.startswith("craft_study")]
    assert not [label for label in labels if label.startswith("listener_study")]
    ran = 0
    for label, fn in tasks:
        if label == "music_study_papers":
            assert set(fn()) == {"records", "log"}
            ran += 1
    assert ran == 1
    assert spy.limits == [2]              # budget chhota hi rehna chahiye


def test_the_music_lane_stays_shut_when_the_plan_did_not_ask():
    """Ye lane sirf plan se khulta hai — asli sawaal ke evidence se nahi."""
    labels, _tasks, spy = _tasks_for([])
    assert not [label for label in labels if "music" in label]
    assert spy.seen == []


def test_a_query_already_sent_by_craft_or_listener_is_not_sent_again():
    """Do label ke saath wahi query = do baar kharcha, do baar ginti."""
    same = "music tempo emotion research study"
    labels, _tasks, _spy = _tasks_for(
        [{"query": same, "lane": "papers"}],
        craft_entries=[{"query": same, "lane": "papers"}])
    assert labels.count("craft_study_papers") == 1
    assert not [label for label in labels if label.startswith("music_study")]
    labels2, _t2, _s2 = _tasks_for(
        [{"query": same, "lane": "papers"}],
        listener_entries=[{"query": same, "lane": "papers"}])
    assert labels2.count("listener_study_papers") == 1
    assert not [label for label in labels2 if label.startswith("music_study")]


def test_a_lyrics_hunt_dies_at_the_discovery_wall_too():
    """Chauthi deewar: planner ke baad discovery me bhi."""
    labels, _tasks, _spy = _tasks_for([
        {"query": "music tempo emotion research study", "lane": "papers"},
        {"query": "tum hi ho full lyrics mp3", "lane": "papers"}])
    assert labels.count("music_study_papers") == 1


def test_the_discovery_tier_honours_the_small_music_budget():
    """Plan me chhe aa jaayein to bhi teen se zyada slot nahi mil sakte."""
    entries = [{"query": f"music emotion research number {i}", "lane": "papers"}
               for i in range(6)]
    labels, _tasks, _spy = _tasks_for(entries)
    assert len([l for l in labels if l.startswith("music_study")]) == (
        ms.MAX_MUSIC_QUERIES)


def test_the_planner_opens_the_lane_only_for_a_song_and_keeps_the_others_whole():
    """Teen lane saath chalti hain — kisi ka slot kisi ne nahi chheena."""
    planner = ResearchPlanner()
    config = depth.get_depth_config("DEEP")
    question = "sad punjabi gaana likho 8 line"
    song = planner.connector_plan({"question": question}, config, question)
    lane = song["music_study_lane"]
    assert lane["wanted"] is True and lane["is_song_request"] is True
    assert len(song["music_study"]) == ms.MAX_MUSIC_QUERIES
    assert len(song["craft_study"]) == sc.MAX_STUDY_QUERIES
    assert len(song["listener_study"]) == ls.MAX_LISTENER_QUERIES
    assert lane["music_evidence_read"] is False
    assert lane["audio_generated"] is False and lane["tune_made"] is False
    assert lane["heard"] is False and lane["play_tested"] is False
    assert lane["replaces_music_direction_present"] is False
    assert lane["gemini_calls"] == 0
    assert set(lane["lanes"]) <= set(sc.STUDY_LANES)
    plain = planner.connector_plan({"question": NON_SONG_Q}, config, NON_SONG_Q)
    assert plain["music_study"] == []
    assert plain["music_study_lane"]["wanted"] is False
    assert "gaane jaisi nahi" in plain["music_study_lane"]["reason"]
    # Chhoti depth par music ka budget bhi chhota hota hai. Ye chhat na ho to
    # QUICK me bhi teen extra query chali jaati hain — "jaldi jawab" ka matlab
    # khatam, aur intel ka ₹0/kam-kharch wala niyam sirf naam ka reh jaata hai.
    quick = depth.get_depth_config("QUICK")
    assert int(getattr(quick, "max_fulltext", 3) or 1) <= 1
    thin = planner.connector_plan({"question": question}, quick, question)
    assert thin["music_study_lane"]["wanted"] is True
    assert len(thin["music_study"]) == 1


def test_the_planner_shuts_the_lane_for_a_lyrics_hunt():
    """Bol maangne par music direction ki research bhi nahi maangi jaati.

    #186e ke baad NAAM wali bol-talaash bhi pakdi jaati hai — "arijit singh tum
    hi ho song lyrics likh do" pehle is gate se nikal jaati thi (yahi wo "jaani
    hui seema" thi jo is test me likhi rehti thi). Jo seema ab bachi hai wo
    `songcraft.LYRICS_HUNT_KNOWN_LIMIT` me saaf likhi hai: ek hi anjaan shabd
    plus koi teesra shabd. Wahan bhi lane khulne se koi bol network par nahi
    jaata: music query user ke shabd se nahi, seeds + `safe_family`/`safe_style`
    se banti hai. Ye test teeno baat pin karta hai.
    """
    planner = ResearchPlanner()
    config = depth.get_depth_config("DEEP")
    for caught in ("gaana likho aur tum hi ho ke gaane ke bol bhi de do",
                   "arijit singh tum hi ho song lyrics likh do"):
        assert sc.is_lyrics_hunt(caught) is True, caught
        # dono haalat me farmaish gaane ki hai — lane phir bhi band hoti hai
        assert craft.detect(caught).get("is_request") is True, caught
        plan = planner.connector_plan({"question": caught}, config, caught)
        assert plan["music_study"] == [], caught
        assert plan["music_study_lane"]["wanted"] is False, caught
        assert "BOL" in plan["music_study_lane"]["reason"], caught

    # Bachi hui seema: ek anjaan shabd ("chaleya") + doosre shabd. Guard yahan
    # jaan-boojh kar chup rehta hai (wahi shakal ek TOPIC ki bhi hoti hai), aur
    # is deewar ka kaam wahi purana hai — user ka shabd query me na jaaye.
    missed = "chaleya song lyrics likh do"
    assert sc.is_lyrics_hunt(missed) is False       # LYRICS_HUNT_KNOWN_LIMIT
    assert "anjaan shabd" in sc.LYRICS_HUNT_KNOWN_LIMIT
    leaky = planner.connector_plan({"question": missed}, config, missed)
    assert leaky["music_study"], missed
    for row in leaky["music_study"]:
        low = str(row["query"]).casefold()
        assert "lyrics" not in low and "chaleya" not in low


def test_the_orchestrator_and_result_wiring_stay_in_place():
    """Ye static contract wiring chup-chaap kat jaane se bachata hai."""
    orch = _read_source("orchestrator.py")
    assert "return music_study.not_asked()" in orch
    assert "music_study.study(question, sources=sources, wanted=True)" in orch
    assert 'if music_guidance_pack.get("wanted"):' in orch
    assert "music_report=passes.get(\"music_study\") or {}," in orch
    assert "music_study=music_study.public_record(" in orch
    # Purani do lane ka wiring bhi waise hi rehna chahiye.
    assert "listener_study=listener_study.public_record(" in orch
    assert "return listener_study.not_asked()" in orch
    syn = _read_source("synthesizer_claude.py")
    assert "music_text = music_section(music_report)" in syn
    # Naap CALL ke ANDAR hoti hai, poori file me kahin bhi needle dikh jaane par
    # nahi: `"music_report=music_report)"` jaisa needle agli baar koi naya kwarg
    # judte hi toot jaata hai — behaviour theek hone par bhi (#134 me listener ke
    # saath yahi hua tha).
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
    assert "music_report=music_report" in args
    # ek hi baar — do jagah pass hone par ek copy chup-chaap purani reh jaati hai
    assert args.count("music_report=music_report") == 1
    # aur purani lane usi call me saath rehni chahiye (jagah nahi cheeni gayi)
    assert "listener_report=listener_report" in args
    assert "music_report: Optional[Dict] = None" in syn
    assert "listener_text = listener_section(listener_report)" in syn
    models = _read_source("models.py")
    assert "music_study: Dict = field(default_factory=dict)" in models
    assert "listener_study: Dict = field(default_factory=dict)" in models


def test_the_public_record_is_json_safe_and_keeps_the_four_false_flags():
    """`ask` ek object hai — wo API par jaake serialize karte waqt tootta hai."""
    import json
    pack = _pack([_Src("S1", snippet=TEMPO_TEXT)])
    record = ms.public_record(pack)
    assert "ask" in record and isinstance(record["ask"], dict)
    json.dumps(record)                     # tootna nahi chahiye
    assert record["audio_generated"] is False and record["tune_made"] is False
    assert record["heard"] is False and record["play_tested"] is False
    assert record["music_direction_is_suggestion"] is True
    assert record["reported_numbers_are_source_reported"] is True
    assert record["ran"] is True and record["wanted"] is True
    empty = ms.public_record(ms.not_asked())
    json.dumps(empty)
    assert empty["wanted"] is False and empty["ran"] is False
    assert empty["limits"] == []
    assert ms.public_record("kuch bhi") == {}


def test_the_result_model_carries_the_record_without_breaking_to_dict():
    """Model me jagah na ho to poora record chup-chaap gir jaata hai."""
    import json
    record = ms.public_record(_pack([_Src("S1", snippet=TEMPO_TEXT)]))
    result = ResearchResult(question=SONG_Q, music_study=record)
    data = result.to_dict()
    json.dumps(data)
    assert data["music_study"]["line_count"] == 1
    assert data["music_study"]["tune_made"] is False
    assert data["music_study"]["support_row"]["check"] == ms.CHECK_NAME
    assert ResearchResult(question=NON_SONG_Q).to_dict()["music_study"] == {}


# ── 8. ASLI DARWAZA: orchestrator ka gate, report, aur ₹0 ────────────────────

def _engine_pack(sources):
    return EvidencePack(question=SONG_Q, sources=list(sources))


def test_the_orchestrator_gate_needs_both_song_signals():
    """Ek signal par khulne se nibandh/physics me bhi ye block ug aata hai."""
    src = [_Src("S1", snippet=TEMPO_TEXT)]
    for song in ("hindi me ek sad gaana likho judaai wala",
                 "punjabi dancing type gangstar gaana banao"):
        out = DeepResearchEngine._music_study(song, _engine_pack(src))
        assert out["wanted"] is True
        assert out["guidance"]["ran"] is True
        assert len(out["guidance"]["lines"]) == 1
        assert len(out["queries"]) == ms.MAX_MUSIC_QUERIES
        assert ms.MUSIC_SUBHEADING in ms.music_section(out)
    for other in (NON_SONG_Q, "is topic par nibandh likho",
                  "arijit singh tum hi ho gaane ke bol download karo"):
        out = DeepResearchEngine._music_study(other, _engine_pack(src))
        assert out["wanted"] is False and out["ran"] is False
        assert out["queries"] == []
        assert ms.music_section(out) == ""
        assert ms.music_limits(out) == []


def test_the_gate_survives_a_missing_pack():
    """Pack na ho to lane ko chup nahi hona chahiye — sirf khaali rehna chahiye."""
    out = DeepResearchEngine._music_study(SONG_Q, None)
    assert out["wanted"] is True
    assert out["guidance"]["ran"] is False
    assert ms.music_limits(out)               # seema phir bhi report me
    assert out["support_row"]["status"] == sc.NOT_MEASURED


def test_a_crash_inside_the_lane_still_shows_the_limits():
    """Chup ho jaana yahan "sab theek tha" ka jhooth ban jaata hai."""
    original = ms.study
    try:
        def boom(*_a, **_kw):
            raise RuntimeError("andar ki galti")
        ms.study = boom
        out = DeepResearchEngine._music_study(SONG_Q, _engine_pack(
            [_Src("S1", snippet=TEMPO_TEXT)]))
    finally:
        ms.study = original
    assert out["wanted"] is True          # farmaish gaane ki THI
    assert out["guidance"]["ran"] is False
    assert ms.music_limits(out)            # seema phir bhi report me jaati hai
    assert out["support_row"]["status"] == sc.NOT_MEASURED
    assert out["guidance"]["missing_fields"] == list(ms.FIELD_KEYS)


def test_the_final_answer_carries_the_block_only_for_a_song():
    """End-to-end: block gaane par aata hai, aur baaki har jawab me nahi."""
    base = dict(gemini_answer="Ye jawab hai.", evidence_level="MEDIUM",
                confidence_note="", contradictions=[], hypotheses=[],
                verification={}, coverage={}, honesty={}, consensus={})
    pack = EvidencePack(question=SONG_Q, sources=[])
    song_report = ms.study(SONG_Q, sources=[_Src("S1", snippet=TEMPO_TEXT)])
    with_block = FinalSynthesizer().assemble(pack=pack,
                                             music_report=song_report, **base)
    assert ms.MUSIC_SUBHEADING in with_block
    assert "[S1]" in with_block
    for line in ms.music_limits(song_report):
        assert line in with_block          # audit ki chhat kaat nahi rahi
    without = FinalSynthesizer().assemble(pack=pack,
                                          music_report=ms.not_asked(), **base)
    assert ms.MUSIC_SUBHEADING not in without
    assert "tune_made=False" not in without
    omitted = FinalSynthesizer().assemble(pack=pack, **base)
    assert ms.MUSIC_SUBHEADING not in omitted


def test_the_music_block_and_the_listener_block_can_stand_together():
    """Do block ek doosre ko kha jaayein to ek lane ka kaam gayab ho jaata hai."""
    base = dict(gemini_answer="Ye jawab hai.", evidence_level="MEDIUM",
                confidence_note="", contradictions=[], hypotheses=[],
                verification={}, coverage={}, honesty={}, consensus={})
    pack = EvidencePack(question=SONG_Q, sources=[])
    listener_report = ls.study(SONG_Q, sources=[_Src(
        "L1", snippet="Listeners report a stronger emotional response when a "
                      "melody matches a remembered life event.")])
    music_report = ms.study(SONG_Q, sources=[_Src("S1", snippet=TEMPO_TEXT)])
    text = FinalSynthesizer().assemble(pack=pack,
                                       listener_report=listener_report,
                                       music_report=music_report, **base)
    assert ms.MUSIC_SUBHEADING in text
    assert ls.LISTENER_SUBHEADING in text
    assert "[S1]" in text and "[L1]" in text


def test_the_same_input_gives_the_exact_same_output_every_time():
    """Randomness ho to naap "naap" nahi rehta — aur mutation test bekaar."""
    src = [_Src("S1", snippet=TEMPO_TEXT + " " + SCALE_TEXT),
           _Src("S2", snippet=INSTRUMENT_TEXT)]
    first = ms.study(SONG_Q, sources=src, ask=_Ask())
    for _ in range(3):
        again = ms.study(SONG_Q, sources=src, ask=_Ask())
        assert again["queries"] == first["queries"]
        assert again["section_lines"] == first["section_lines"]
        assert again["limits"] == first["limits"]
        assert again["prompt_block"] == first["prompt_block"]
        assert again["support_row"] == first["support_row"]


def test_this_whole_lane_costs_zero_rupees():
    """Ye lane research PADHTI hai — na model chalati hai, na khud network."""
    assert ms.GEMINI_CALLS == 0
    assert ms.NETWORK_USED is False
    assert ms.AUDIO_GENERATED is False and ms.TUNE_MADE is False
    assert ms.HEARD is False and ms.PLAY_TESTED is False
    assert ms.MUSIC_DIRECTION_IS_SUGGESTION is True
    pol = ms.policy()
    assert pol["gemini_calls"] == 0 and pol["network_used"] is False
    assert pol["randomness_used"] is False and pol["deterministic"] is True
    assert pol["provider_cost"] == "₹0"
    assert pol["hit_predicted"] is False
    assert pol["sound_quality_measured"] is False
    code = _read_source("music_study.py")
    for banned in ("import requests", "urllib.request", "genai", "httpx",
                   "import random", "random."):
        assert banned not in code, banned
    # `GEMINI_CALLS` naam chal sakta hai (wo ginti hai), model call nahi.
    assert "GEMINI_CALLS = 0" in code


def test_the_audio_flags_come_from_songcraft_so_they_can_not_drift():
    """Do jagah do jawab = ek jagah "dhun ban gayi" ka jhooth mumkin ho jaata."""
    assert ms.AUDIO_GENERATED is sc.AUDIO_GENERATED
    assert ms.MUSIC_DIRECTION_IS_SUGGESTION is (
        sc.MUSIC_DIRECTION_IS_SUGGESTION)
