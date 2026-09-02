"""#149 — BHAAV KI SHABDAWALI: shabd padhi hui source se seekho, band list se nahi.

`craft.MOODS` haath se likhi hui band list hai. Usme "dukh" hai par "dard",
"aansu", "viraha", "tootna" nahi — isliye intel ka bilkul aam sawaal ("dard bhara
sad gaana likho") par bhaav ka naap `DATA_MISSING` de deta tha: naap ka NAAM tha,
naap nahi thi. Ye khaali jagah #141 ke audit me khud pakdi gayi thi.

Is file ka kaam sirf "naya shabd mil gaya" dikhana NAHI hai — asli kaam ye pin
karna hai ki naya shabd kitna kam haq rakhta hai:

  1. Shabd sirf GLOSS ke dhaanche se seekha jaaye (bracket, "means", "also known
     as", "i.e."). Ek hi vaakya me do shabd saath aa jaana jodi nahi banata —
     wo andaza hai, aur andaza hi fabrication hai.
  2. Do ALAG source id ke bina shabd naap me na lage (`CONFIRM_MIN`). Ek source
     ka shabd sirf HINT hai aur kisi MET/NOT_MET ko chhoo nahi sakta.
  3. **Seekha hua shabd kisi LINE KO HATA na sake.** Line hataana sabse bhaari
     faisla hai; uske liye padha hua paryaayvaachi kaafi saboot nahi. DROP ka
     adhikaar curated list ke paas hi rehta hai — aur ye test us mechanism ko
     curated shabd se chala kar bhi dikhata hai, warna "kuch nahi hataya" wala
     test khaali (vacuous) ho jaata.
  4. Purani curated list se kuch HATAYA na jaaye: ledger khaali/None ho to app ka
     behaviour bit-ke-bit purana rahe.
  5. Bina source id kuch na seekha jaaye, aur ek hi shabd do bhaav ke saath gloss
     ho to wo shabd poori tarah bahar ho.
  6. ₹0: 0 Gemini call, 0 network, koi randomness nahi.
  7. WIRING sach me judi ho: craft (spec/naap/report) → songlab (arc) →
     orchestrator (gate + result) → synthesizer (block + audit ki seema).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import mood_lexicon as ml  # noqa: E402
from research_engine import songcraft  # noqa: E402
from research_engine import songlab as sl  # noqa: E402
from research_engine import synthesizer_claude as sc  # noqa: E402
from research_engine.models import ResearchResult  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name: str) -> str:
    with open(os.path.join(_ROOT, "research_engine", name),
              encoding="utf-8") as handle:
        return handle.read()


# ── nakli source (jo "padhi hui" maani jaati hain) ──────────────────────────
class Src:
    def __init__(self, source_id: str, snippet: str,
                 read_level: str = "snippet"):
        self.source_id = source_id
        self.title = "song writing notes"
        self.snippet = snippet
        self.url = "https://example.org/%s" % (source_id or "x")
        self.connector = "test"
        self.read_level = read_level


def learn(*pairs, **kwargs):
    """(source_id, text) jodiyon se ledger — test padhne me aasaan rahe."""
    return ml.learn([Src(sid, text) for sid, text in pairs], **kwargs)


# aansu → dukh aur muskaan → khushi, dono DO alag source se (confirmed).
# tootna sirf EK source se (hint) — isse "hint kuch nahi chhoota" naapa jaata.
LEDGER = learn(
    ("s1", "In these lyrics aansu, that is dukh, returns in every antara."),
    ("s2", "Here aansu means dukh for the listener."),
    ("s3", "The writer notes muskaan, that is khushi, in the mukhda."),
    ("s4", "Here muskaan means khushi in this refrain."),
    ("s5", "The word tootna (dukh) appears once in this book."),
)

# ── farmaish + draft ────────────────────────────────────────────────────────
# Q_SAD me curated shabd "sad" hai → mood_asked me "dukh" aata hai (curated).
# Q_LEARNED me curated koi bhaav-shabd nahi, sirf SEEKHA hua "aansu" hai — isse
# `mood_asked_learned` ka poora raasta naapa jaata hai.
Q_SAD = "sad hindi gaana likho judaai par"
Q_LEARNED = "aansu wala hindi gaana likho judaai par"
Q_POEM = "tanhai par ek kavita likho"
Q_OTHER = "dark matter ka saboot kya hai"

HOOK = "beete lamhon ki baat reh gayi"
# 9 line, teen band — bhaav ka shabd sirf SEEKHA hua "aansu" hai, curated koi
# nahi. Purane behaviour me isi draft par arc `DATA_MISSING` deta tha.
DRAFT = "\n".join([
    HOOK, "aansu meri palkon par ruke", "raat gehri hai ghadi ruki",
    "", HOOK, "aansu ne likha mera naam", "door kahin ek diya jal raha",
    "", HOOK, "aansu bhi ab sookh gaye", "ye kahani saath reh gayi",
])
# Ek line me SEEKHA hua ulta bhaav (muskaan → khushi).
DRAFT_LEARNED_OPPOSITE = DRAFT.replace("aansu bhi ab sookh gaye",
                                       "muskaan bhi ab door ho gayi")
# Wahi line, par CURATED ulta bhaav (khushi) — mechanism zinda hai ya nahi.
DRAFT_CURATED_OPPOSITE = DRAFT.replace("aansu bhi ab sookh gaye",
                                       "khushi bhi ab door ho gayi")


def spec_of(question: str, ledger=None):
    return craft.build_spec(question, craft.detect(question),
                            mood_ledger=ledger)


def checks_of(draft: str, spec) -> dict:
    return {row["check"]: row["status"]
            for row in craft.measure(draft, spec)["checks"]}


SPEC_SAD = spec_of(Q_SAD, LEDGER)
SPEC_SAD_PLAIN = spec_of(Q_SAD)
SPEC_LEARNED = spec_of(Q_LEARNED, LEDGER)
SPEC_LEARNED_PLAIN = spec_of(Q_LEARNED)


# ══ 1. SEEKHNE KE NIYAM (ledger) ════════════════════════════════════════════
def test_bracket_gloss_learns_a_cue():
    report = learn(("a1", "The poet uses viraha (judaai) throughout."),
                   ("a2", "Again viraha (judaai) closes the antara."))
    assert ("judaai", "viraha") in ml.confirmed_pairs(report)


def test_all_four_gloss_patterns_can_learn():
    seen = set()
    for text in ("Here viraha (judaai) is used.",
                 "The term viraha is also known as judaai.",
                 "In this book viraha means judaai.",
                 "The poet writes viraha, that is judaai."):
        report = learn(("x1", text), ("x2", text.replace("Here", "Again")))
        cues = {item["cue"]: item for item in report["cues"]}
        assert "viraha" in cues, text
        seen.update(cues["viraha"]["patterns"])
    assert seen == set(ml.PATTERN_NAMES), sorted(seen)


def test_co_occurrence_never_learns_a_pair():
    # Dono shabd ek hi vaakya me hain, par gloss ka dhaancha nahi hai.
    report = learn(("c1", "In this stanza dukh and viraha both appear often."),
                   ("c2", "Again dukh and viraha appear side by side."))
    assert report["ran"] is True
    assert report["cues"] == []
    assert report["guessed_from_co_occurrence"] is False


def test_one_source_stays_a_hint_and_touches_no_measurement():
    report = learn(("h1", "The word tootna (dukh) appears in the refrain."))
    assert ml.confirmed_pairs(report) == ()
    assert ("dukh", "tootna") in ml.hint_pairs(report)
    assert report["hint_count"] == 1 and report["confirmed_count"] == 0


def test_two_distinct_sources_confirm_a_cue():
    report = learn(("d1", "Here aansu means dukh."),
                   ("d2", "The poet writes aansu, that is dukh."))
    row = report["cues"][0]
    assert row["source_count"] == ml.CONFIRM_MIN == 2
    assert row["source_ids"] == ["d1", "d2"] and row["confirmed"] is True


def test_same_source_twice_never_confirms():
    report = learn(("only", "Here aansu means dukh. Also aansu (dukh) again."))
    row = report["cues"][0]
    assert row["source_ids"] == ["only"] and row["confirmed"] is False
    assert ml.confirmed_pairs(report) == ()


def test_source_without_id_learns_nothing():
    report = learn(("", "Here aansu means dukh."),
                   ("", "The poet writes aansu, that is dukh."))
    # Padhi gayi thi (`ran` True), par citation ke bina ek shabd bhi nahi liya.
    assert report["ran"] is True and report["cues"] == []
    assert report["rejects"][ml.REJECT_NO_SOURCE_ID] == 2


def test_ambiguous_cue_is_thrown_out_completely():
    # tootna do alag bhaav ke saath gloss hua — teesri baar sahi bhaav aane par
    # bhi wapas nahi aata (`banned`), kyunki kaunsa sahi hai ye tay nahi hota.
    report = learn(("b1", "The word tootna (dukh) is common."),
                   ("b2", "The word tootna (khushi) is common."),
                   ("b3", "The word tootna (dukh) is common again."))
    assert "tootna" in report["banned_cues"]
    assert "tootna" not in report["confirmed_cues"] + report["hint_cues"]
    assert report["rejects"][ml.REJECT_AMBIGUOUS] >= 2


def test_both_sides_already_known_learns_nothing_new():
    report = learn(("k1", "Here dukh (gham) is the mood of this lyric."))
    assert report["cues"] == []
    assert report["rejects"][ml.REJECT_BOTH_SIDES_ANCHOR] == 1


def test_full_sentence_gloss_is_rejected():
    text = "Here dukh (the state of being far away from a lover) is used."
    report = learn(("l1", text), ("l2", text))
    assert report["cues"] == []
    assert report["rejects"][ml.REJECT_GLOSS_TOO_LONG] >= 1


def test_mixed_side_is_not_guessed():
    # "dukh dard" — ek jaana-pehchana + ek naya. Kaunsa kis ka gloss hai, ye
    # tay nahi hota, isliye kuch nahi seekha jaata.
    ok, why = ml._side_role("dukh dard")[0], ml._side_role("dukh dard")[2]
    assert ok == ml.ROLE_NONE and why == ml.REJECT_GLOSS_TOO_LONG


def test_one_side_with_two_different_moods_is_never_an_anchor():
    # "judaai pyaar" ek hi taraf par do ALAG bhaav — naya shabd kis ka gloss hai
    # ye padhi hui line se tay nahi hota. Pehla bhaav uthaa lena andaza hoga.
    role, load, why = ml._side_role("judaai pyaar")
    assert role == ml.ROLE_NONE and load is None
    assert why == ml.REJECT_AMBIGUOUS
    text = "The word virah (judaai pyaar) appears here."
    report = learn(("m1", text), ("m2", text))
    assert report["cues"] == [] and report["confirmed_cues"] == []
    assert "virah" not in report["hint_cues"]


def test_a_long_all_known_side_is_still_too_long_to_be_an_anchor():
    # "dukh gham dard" teen shabd — teeno curated, ek hi bhaav ka. Phir bhi
    # MAX_GLOSS_WORDS ki seema chalti hai: itne bade side me kaun kis ka gloss
    # hai, ye dhaanche se saaf nahi hota.
    assert ml.MAX_GLOSS_WORDS == 2
    role, load, why = ml._side_role("dukh gham udaas")
    assert role == ml.ROLE_NONE and load is None
    assert why == ml.REJECT_GLOSS_TOO_LONG
    text = "The word virah (dukh gham udaas) is used by the poet."
    report = learn(("n1", text), ("n2", text))
    assert report["cues"] == [] and report["confirmed_cues"] == []
    # `_side_role` ne side hi khaarij kar diya, isliye jodi ko anchor hi nahi
    # mila — wajah naapi hui hai, chhupi nahi.
    assert report["rejects"][ml.REJECT_NO_ANCHOR] >= 1


def test_stop_word_never_becomes_a_cue():
    report = learn(("t1", "Here dukh (the) is written."), ("t2", "dukh (the)."))
    assert report["cues"] == []
    assert report["rejects"][ml.REJECT_STOP_WORD] >= 1
    assert ml.admissible("also") == (False, ml.REJECT_STOP_WORD)


def test_curated_word_is_never_relearned():
    assert ml.admissible("gham") == (False, ml.REJECT_ALREADY_KNOWN)
    report = learn(("g1", "Here udaas means gham in this book."),
                   ("g2", "Again udaas means gham."))
    assert report["rejects"][ml.REJECT_BOTH_SIDES_ANCHOR] >= 1


def test_cue_length_and_shape_limits():
    assert ml.admissible("ab") == (False, ml.REJECT_LENGTH)
    assert ml.admissible("a" * (ml.MAX_CUE_CHARS + 1))[1] == ml.REJECT_LENGTH
    assert ml.admissible("dard2") == (False, ml.REJECT_SHAPE)
    assert ml.admissible("12") == (False, ml.REJECT_SHAPE)
    assert ml.admissible("dard") == (True, "")


def test_devanagari_cue_is_learnable():
    report = learn(("v1", "यहाँ दुख (आँसू) लिखा गया है।"),
                   ("v2", "फिर दुख (आँसू) आता है।"))
    assert ("dukh", "आँसू") in ml.confirmed_pairs(report)


def test_ledger_has_a_ceiling_and_says_so():
    glosses = " ".join("Here dukh (%s) is used." % ("zx" + chr(97 + i))
                       for i in range(ml.MAX_CUES + 6))
    report = learn(("cap1", glosses), ("cap2", glosses))
    assert len(report["cues"]) == ml.MAX_CUES
    assert report["rejects"][ml.REJECT_CAP] > 0


def test_only_bounded_number_of_sources_are_scanned():
    many = [Src("id%d" % i, "Here aansu means dukh.")
            for i in range(ml.MAX_SOURCES_SCANNED + 5)]
    report = ml.learn(many)
    assert report["sources_scanned"] == ml.MAX_SOURCES_SCANNED


def test_every_reject_reason_is_printed_even_when_zero():
    report = learn(("z1", "Here aansu means dukh."))
    assert set(report["rejects"]) == set(ml.REJECT_REASONS)
    # Sirf jo asli me giri, uski insaani wajah likhi jaati hai.
    assert all(report["rejects"][key] for key in report["reject_reasons"])


def test_cue_order_is_deterministic_and_evidence_first():
    report = LEDGER
    assert [item["cue"] for item in report["cues"]][:2] == ["aansu", "muskaan"]
    assert report["cues"][-1]["cue"] == "tootna"          # hint sabse aakhir
    assert ml.learn([Src(s, t) for s, t in
                     (("s1", "Here aansu means dukh."),
                      ("s2", "Also aansu (dukh)."))])["cues"] == \
        ml.learn([Src(s, t) for s, t in
                  (("s1", "Here aansu means dukh."),
                   ("s2", "Also aansu (dukh)."))])["cues"]


def test_the_most_cited_cue_comes_first_not_the_alphabet():
    # zakhm 3 source, bebasi 2, muskaan 2, aansu sirf 1 (hint). Kram SABOOT ka
    # hai: zyada source pehle, baraabari par naam se, hint hamesha aakhir me.
    # Sirf naam se sort karne par kram aansu, bebasi, muskaan, zakhm hota.
    report = learn(
        ("z1", "Here zakhm means dukh."),
        ("z2", "Also zakhm (dukh)."),
        ("z3", "The poet writes zakhm, that is dukh."),
        ("b1", "Here bebasi means dukh."),
        ("b2", "Also bebasi (dukh)."),
        ("m1", "Here muskaan means khushi."),
        ("m2", "Also muskaan (khushi)."),
        ("a1", "Here aansu means dukh."),
    )
    assert [item["cue"] for item in report["cues"]] == [
        "zakhm", "bebasi", "muskaan", "aansu"]
    assert [item["source_count"] for item in report["cues"]] == [3, 2, 2, 1]
    assert report["hint_cues"] == ["aansu"]


def test_examples_carry_source_id_and_pattern():
    row = LEDGER["cues"][0]
    assert row["examples"] and len(row["examples"]) <= ml.MAX_EXAMPLES_PER_CUE
    for example in row["examples"]:
        assert example["source_id"] in row["source_ids"]
        assert example["pattern"] in ml.PATTERN_NAMES
        assert row["cue"] in example["text"].lower()


def test_anchor_table_is_derived_from_craft_not_copied():
    # craft.MOODS badle to anchor_map apne aap badle — do jagah do sach nahi.
    original = craft.MOODS
    try:
        craft.MOODS = original + (("testmood", ("testcue",)),)
        assert ml.anchor_map()["testcue"] == "testmood"
        assert "testmood" in ml.mood_labels()
        assert ml.admissible("testcue") == (False, ml.REJECT_ALREADY_KNOWN)
    finally:
        craft.MOODS = original
    assert "testcue" not in ml.anchor_map()


def test_curated_list_is_never_trimmed():
    labels = [label for label, _variants in craft.MOODS]
    for must in ("dukh", "khushi", "judaai", "tanhai", "pyaar"):
        assert must in labels
    assert LEDGER["curated_label_count"] == len(labels)
    assert LEDGER["curated_list_is_never_replaced"] is True


# ══ 2. REPORT KA SACH (kya likha jaata hai) ═════════════════════════════════
def test_not_run_says_why_and_counts_zero():
    report = ml.not_run("farmaish gaane ki nahi thi")
    assert report["ran"] is False
    assert report["reason"] == "farmaish gaane ki nahi thi"
    assert report["confirmed_count"] == 0 and report["cues"] == []
    assert set(report["rejects"]) == set(ml.REJECT_REASONS)
    assert ml.confirmed_pairs(report) == () and ml.hint_pairs(report) == ()


def test_none_and_empty_report_are_safe():
    for empty in (None, {}, {"cues": None}):
        assert ml.confirmed_pairs(empty) == ()
        assert ml.hint_pairs(empty) == ()
        assert ml.public_record(empty)["ran"] is False
        assert ml.section_lines(empty)[0].startswith("Bhaav ki shabdawali nahi")


def test_a_junk_ledger_is_treated_as_no_ledger_not_as_a_crash():
    # Non-dict par bhi crash nahi — kyunki ek andar ki galti ka natija "app ka
    # jawab hi na aaye" nahi hona chahiye. Behaviour bilkul #149 se pehle jaisa.
    for junk in ("nope", 7, [], ("a", "b"), 0.5, True):
        assert ml.confirmed_pairs(junk) == ()
        assert ml.hint_pairs(junk) == ()
        assert ml.public_record(junk)["ran"] is False
        assert ml.section_lines(junk)[0].startswith("Bhaav ki shabdawali nahi")
        assert ml.mood_section({"mood_lexicon": junk}) == ""


def test_zero_cost_and_no_network_everywhere():
    for report in (LEDGER, ml.not_run("x"), ml.policy(), ml.public_record(LEDGER)):
        assert report["gemini_calls"] == 0
        assert report["network_used"] is False
    assert ml.GEMINI_CALLS == 0 and ml.NETWORK_USED is False


def test_policy_writes_the_three_hard_rules():
    policy = ml.policy()
    assert policy["confirm_min"] == 2
    assert policy["learned_cue_can_drop_a_line"] is False
    assert policy["learned_cue_is_not_a_feeling"] is True
    assert policy["guessed_from_co_occurrence"] is False
    assert policy["curated_list_is_never_replaced"] is True
    assert policy["learned_from"] == "already_read_source_text_only"
    assert list(policy["gloss_patterns"]) == list(ml.PATTERN_NAMES)


def test_limits_spell_out_the_drop_rule_and_the_word_vs_feeling_gap():
    lines = ml.limits()
    assert ml.MAX_AUDIT_LIMIT_LINES == len(lines)
    joined = " ".join(lines)
    assert "LEARNED_CUE_CAN_DROP_A_LINE = False" in joined
    assert "HATA nahi sakta" in joined
    assert "GUESSED_FROM_CO_OCCURRENCE = False" in joined
    assert "LEXICON_IS_LEARNED_NOT_COMPLETE = True" in joined
    assert "CURATED_LIST_IS_NEVER_REPLACED = True" in joined


def test_section_lines_are_bounded_and_cite_source_ids():
    lines = ml.section_lines(LEDGER)
    assert 0 < len(lines) <= ml.MAX_SECTION_LINES
    cue_lines = [line for line in lines if line.startswith("\"")]
    assert cue_lines, lines
    for line in cue_lines:
        assert "source: " in line
        assert "confirmed" in line or "hint" in line
    assert any("s1" in line and "s2" in line for line in cue_lines)
    assert "hataa nahi sakta" in lines[-1]


def test_section_says_a_hint_is_not_a_measurement():
    lines = " ".join(ml.section_lines(LEDGER))
    assert "hint" in lines and "naap me nahi lagta" in lines


def test_a_big_ledger_still_cannot_flood_the_answer_block():
    # 6 shabd seekhe gaye to bhi block ki lambai fixed hai — jawab me hissa
    # chhota rehta hai, aur aakhri seema-line kabhi kat kar bahar nahi jaati.
    report = learn(
        ("f1", "Here zakhm means dukh. Also bebasi (dukh). And viraag means dukh."),
        ("f2", "Here zakhm means dukh. Also bebasi (dukh). And viraag means dukh."),
        ("f3", "Here kasak means dukh. Also tapan (dukh). And khalish means dukh."),
        ("f4", "Here kasak means dukh. Also tapan (dukh). And khalish means dukh."),
    )
    assert report["confirmed_count"] == 6
    lines = ml.section_lines(report)
    assert 0 < len(lines) <= ml.MAX_SECTION_LINES
    cue_lines = [line for line in lines if line.startswith("\"")]
    assert len(cue_lines) == ml.MAX_SECTION_LINES - 4
    assert "hataa nahi sakta" in lines[-1]


def test_public_record_never_claims_a_feeling():
    record = ml.public_record(LEDGER)
    assert record["feeling_proven"] is False
    assert record["learned_cue_is_not_a_feeling"] is True
    assert record["learned_cue_can_drop_a_line"] is False
    assert record["confirmed_count"] == 2 and record["hint_count"] == 1
    assert record["confirmed_cues"] == ["aansu", "muskaan"]
    assert record["pairs_rejected"] == sum(LEDGER["rejects"].values())
    # Bade text (examples/vaakya) chhote record me nahi jaate.
    assert "cues" not in record and "examples" not in record


def test_note_never_claims_the_language_is_finished():
    empty = learn(("n1", "This page has no gloss at all."))
    assert empty["confirmed_count"] == 0
    assert "nahi mila" in empty["note"]
    assert empty["lexicon_is_learned_not_complete"] is True


# ══ 3. CRAFT KI TAAR (spec → naap) ══════════════════════════════════════════
def test_mood_hints_widens_only_when_learned_is_passed():
    line = "aansu meri palkon par ruke"
    assert craft.mood_hints(line) == []
    assert craft.mood_hints(line, learned=[["dukh", "aansu"]]) == ["dukh"]


def test_mood_hints_keeps_curated_first_and_never_repeats_a_label():
    text = "gham bhi hai aur aansu bhi"
    wide = craft.mood_hints(text, learned=[["dukh", "aansu"]])
    assert wide[0] == "dukh" and wide.count("dukh") == 1


def test_mood_hints_ignores_broken_pairs_instead_of_crashing():
    text = "aansu meri palkon par ruke"
    junk = [None, (), ("dukh",), ("", "aansu"), ("dukh", ""), 7,
            ["dukh", "aansu"]]
    assert craft.mood_hints(text, learned=junk) == ["dukh"]


def test_spec_keeps_asked_curated_and_learned_in_a_separate_field():
    # Yahi wo taala hai jisse `songlab._opposite_moods(spec.mood_asked)` chaudi
    # nahi hoti: seekha bhaav alag field me baithta hai.
    assert SPEC_LEARNED.mood_asked == ["judaai"]
    assert SPEC_LEARNED.mood_asked_learned == ["dukh"]
    assert ["dukh", "aansu"] in SPEC_LEARNED.mood_learned
    assert SPEC_LEARNED_PLAIN.mood_asked == ["judaai"]
    assert SPEC_LEARNED_PLAIN.mood_asked_learned == []
    assert SPEC_LEARNED_PLAIN.mood_learned == []


def test_learned_mood_is_never_silently_added_it_says_so_in_notes():
    note = [line for line in SPEC_LEARNED.notes if "padhi hui source" in line]
    assert note and "dukh" in note[0]
    assert "HATAYI nahi jaayegi" in note[0]
    assert not [line for line in SPEC_LEARNED_PLAIN.notes
                if "padhi hui source" in line]


def test_spec_to_dict_carries_all_three_mood_fields():
    row = SPEC_LEARNED.to_dict()
    assert row["mood_asked"] == ["judaai"]
    assert row["mood_asked_learned"] == ["dukh"]
    assert ["dukh", "aansu"] in row["mood_learned"]


def test_draft_facts_keeps_curated_moods_separate_from_wide():
    facts = craft.draft_facts(DRAFT, learned=[["dukh", "aansu"]])
    assert facts["moods"] == []                      # curated me kuch nahi
    assert facts["moods_wide"] == ["dukh"]           # seekhe shabd se mila
    assert facts["moods_learned_only"] == ["dukh"]
    plain = craft.draft_facts(DRAFT)
    assert plain["moods"] == [] and plain["moods_wide"] == []
    assert plain["moods_learned_only"] == []


def test_learned_cue_can_turn_mood_words_from_not_met_to_met():
    assert checks_of(DRAFT, SPEC_SAD_PLAIN)["mood_words_present"] == craft.NOT_MET
    assert checks_of(DRAFT, SPEC_SAD)["mood_words_present"] == craft.MET


def test_learned_cue_can_prove_mood_spread_across_stanzas():
    # Purana behaviour: teen band me bhaav ka koi curated shabd nahi tha.
    assert checks_of(DRAFT, SPEC_SAD_PLAIN)["mood_spread"] == craft.NOT_MET
    assert checks_of(DRAFT, SPEC_SAD)["mood_spread"] == craft.MET
    stanzas = craft.measure(DRAFT, SPEC_SAD)["measured"]["stanza_moods"]
    assert len(stanzas) == 3 and all(row == ["dukh"] for row in stanzas)


def test_question_side_learned_cue_also_reaches_the_measurement():
    # "aansu wala gaana" — farmaish me curated bhaav-shabd nahi hai.
    assert checks_of(DRAFT, SPEC_LEARNED)["mood_words_present"] == craft.MET


def test_measured_block_names_which_moods_came_from_read_sources():
    measured = craft.measure(DRAFT, SPEC_SAD)["measured"]
    assert measured["moods_in_draft"] == []
    assert measured["moods_in_draft_wide"] == ["dukh"]
    assert measured["moods_from_read_sources"] == ["dukh"]
    assert ["dukh", "aansu"] in measured["mood_cues_learned"]


def test_without_a_ledger_measurement_is_bit_for_bit_the_old_one():
    for empty in (None, {}, ml.not_run("x")):
        spec = spec_of(Q_SAD, empty)
        assert spec.to_dict() == SPEC_SAD_PLAIN.to_dict()
        assert craft.measure(DRAFT, spec)["measured"] == \
            craft.measure(DRAFT, SPEC_SAD_PLAIN)["measured"]


def test_run_craft_prints_the_ledger_it_actually_measured_with():
    body = "```\n" + DRAFT + "\n```"
    report = craft.run_craft(Q_SAD, body, mood_ledger=LEDGER)
    assert report["mood_lexicon"]["ran"] is True
    assert report["mood_lexicon"]["confirmed_cues"] == ["aansu", "muskaan"]
    assert report["mood_lexicon_record"]["confirmed_count"] == 2
    assert report["mood_lexicon_record"]["feeling_proven"] is False


def test_run_craft_without_a_ledger_says_so_instead_of_faking_one():
    report = craft.run_craft(Q_SAD, "```\n" + DRAFT + "\n```")
    assert report["mood_lexicon"]["ran"] is False
    assert "nahi diya gaya" in report["mood_lexicon"]["reason"]
    assert report["mood_lexicon_record"]["ran"] is False
    assert report["mood_lexicon_record"]["confirmed_count"] == 0


def test_run_craft_ignores_a_junk_ledger_without_crashing():
    for junk in ("nope", 7, [], {"cues": "nope"}):
        report = craft.run_craft(Q_SAD, "```\n" + DRAFT + "\n```",
                                 mood_ledger=junk)
        assert report["ran"] is True
        assert report["mood_lexicon_record"]["confirmed_count"] == 0


# ══ 4. SONG LAB KI TAAR (arc test + line hataana) ═══════════════════════════
def test_arc_was_data_missing_before_and_passes_with_read_words():
    before = sl.test_mood_arc(DRAFT, SPEC_SAD_PLAIN)
    after = sl.test_mood_arc(DRAFT, SPEC_SAD)
    assert before["status"] == sl.DATA_MISSING
    assert after["status"] == sl.TESTED_PASS
    assert after["observed"]["share"] == 1.0
    assert after["observed"]["stanzas_with_asked_mood"] == 3


def test_arc_keeps_curated_and_learned_asked_moods_visible_separately():
    observed = sl.test_mood_arc(DRAFT, SPEC_SAD)["observed"]
    assert observed["asked_curated"] == ["dukh", "judaai"]
    assert observed["asked_learned"] == []
    assert observed["learned_cue_can_drop_a_line"] is False
    assert observed["mood_list_is_not_exhaustive"] is True
    learned_side = sl.test_mood_arc(DRAFT, SPEC_LEARNED)["observed"]
    assert learned_side["asked_curated"] == ["judaai"]
    assert learned_side["asked_learned"] == ["dukh"]


def test_arc_stays_not_testable_when_no_mood_was_asked_at_all():
    spec = spec_of("hindi gaana likho barish par", LEDGER)
    assert spec.mood_asked == [] and spec.mood_asked_learned == []
    assert sl.test_mood_arc(DRAFT, spec)["status"] == sl.NOT_TESTABLE_HERE


def test_arc_opposite_side_is_still_only_curated():
    # Seekha "muskaan" (khushi) maange hue dukh ka ULTA hai — par wo test ko
    # fail nahi kar sakta, warna us fail se line hataane ki wajah ban jaati.
    learned_side = sl.test_mood_arc(DRAFT_LEARNED_OPPOSITE, SPEC_SAD)
    assert learned_side["status"] == sl.TESTED_PASS
    assert learned_side["observed"]["conflicts"] == []
    # Wahi line curated shabd "khushi" ke saath — mechanism zinda hai.
    curated_side = sl.test_mood_arc(DRAFT_CURATED_OPPOSITE, SPEC_SAD)
    assert curated_side["status"] == sl.TESTED_FAIL
    assert curated_side["observed"]["conflicts"]


def test_a_learned_word_never_puts_a_drop_code_on_a_line():
    codes = {code for row in sl.line_rows(DRAFT_LEARNED_OPPOSITE, SPEC_SAD)
             for code in row["codes"]}
    assert sl.CODE_MOOD_CONFLICT not in codes
    assert not [row for row in sl.line_rows(DRAFT_LEARNED_OPPOSITE, SPEC_SAD)
                if row["status"] == sl.LINE_DROP]


def test_a_curated_word_still_puts_the_drop_code_on_the_same_line():
    rows = sl.line_rows(DRAFT_CURATED_OPPOSITE, SPEC_SAD)
    hit = [row for row in rows if sl.CODE_MOOD_CONFLICT in row["codes"]]
    assert len(hit) == 1 and hit[0]["status"] == sl.LINE_DROP
    assert sl.CODE_MOOD_CONFLICT in sl.DROP_CODES


def test_drop_plan_drops_nothing_for_a_learned_word_but_does_for_curated():
    learned_plan = sl.drop_plan(DRAFT_LEARNED_OPPOSITE, SPEC_SAD)
    assert learned_plan["dropped"] == [] and learned_plan["drop_line_nos"] == []
    curated_plan = sl.drop_plan(DRAFT_CURATED_OPPOSITE, SPEC_SAD)
    assert curated_plan["drop_line_nos"] == [8]
    assert curated_plan["every_drop_has_a_measured_reason"] is True


def test_song_lab_rollup_improves_only_through_the_positive_side():
    plain = sl.run_song_lab(DRAFT, SPEC_SAD_PLAIN)
    with_ledger = sl.run_song_lab(DRAFT, SPEC_SAD)
    rows_plain = {row["test"]: row["status"] for row in plain["tests"]}
    rows_led = {row["test"]: row["status"] for row in with_ledger["tests"]}
    assert rows_plain[sl.TEST_MOOD_ARC] == sl.DATA_MISSING
    assert rows_led[sl.TEST_MOOD_ARC] == sl.TESTED_PASS
    # Baaki teen test jaise the waise hi — ledger ne kisi aur naap ko nahi chhua.
    for name in sl.TEST_NAMES:
        if name != sl.TEST_MOOD_ARC:
            assert rows_plain[name] == rows_led[name], name


def test_a_learned_ask_counts_as_the_mood_being_present_in_every_stanza():
    # Q_LEARNED me curated bhaav-shabd nahi hai; "aansu" SEEKHA hua hai. Positive
    # side me wo ginta hai — teeno antare me maanga bhaav mila.
    row = sl.test_mood_arc(DRAFT, SPEC_LEARNED)
    measured = row["measured"]
    assert row["status"] == sl.TESTED_PASS
    assert measured["asked"] == ["judaai", "dukh"]
    assert measured["asked_curated"] == ["judaai"]
    assert measured["asked_learned"] == ["dukh"]
    assert measured["stanzas"] == 3 and measured["stanzas_with_asked_mood"] == 3
    assert measured["share"] == 1.0
    assert all(stanza["asked_present"] == ["dukh"] for stanza in measured["arc"])


def test_a_learned_ask_never_manufactures_an_opposite_mood():
    # Ye #149 ka sabse bhaari taala: `opposites` SIRF curated ask se banta hai.
    # Agar seekha hua "dukh" bhi ulta-bhaav banata, to curated "khushi" wali line
    # par conflict aata, arc TESTED_FAIL hota, aur us fail se line hataane ki
    # wajah ban jaati — padha hua synonym itna bada saboot nahi hai.
    measured = sl.test_mood_arc(DRAFT_CURATED_OPPOSITE, SPEC_LEARNED)["measured"]
    assert SPEC_LEARNED.mood_asked_learned == ["dukh"]
    assert measured["opposites"] == []
    assert measured["conflicts"] == []
    assert sl.test_mood_arc(DRAFT_CURATED_OPPOSITE,
                            SPEC_LEARNED)["status"] == sl.TESTED_PASS
    rows = sl.line_rows(DRAFT_CURATED_OPPOSITE, SPEC_LEARNED)
    assert [row["status"] for row in rows] == [sl.LINE_KEEP] * 9
    assert sl.drop_plan(DRAFT_CURATED_OPPOSITE, SPEC_LEARNED)["dropped"] == []


# ══ 5. ASLI WIRING (orchestrator → result → answer → audit) ═════════════════
class Pack:
    """Nakli evidence pack — sirf `sources` chahiye."""

    def __init__(self, sources):
        self.sources = list(sources)


class BrokenPack:
    @property
    def sources(self):
        raise RuntimeError("pack toot gaya")


PACK = Pack([Src("s1", "In these lyrics aansu, that is dukh, hai."),
             Src("s2", "Here aansu means dukh.")])


def test_lane_opens_only_on_a_song_request():
    report = DeepResearchEngine._mood_lexicon(Q_SAD, PACK)
    assert report["ran"] is True
    assert ("dukh", "aansu") in ml.confirmed_pairs(report)


def test_lane_stays_shut_for_non_song_questions_and_says_why():
    for question in (Q_OTHER, Q_POEM, ""):
        report = DeepResearchEngine._mood_lexicon(question, PACK)
        assert report["ran"] is False
        assert report["reason"] == "farmaish gaane ki nahi thi"
        assert ml.confirmed_pairs(report) == ()


def test_a_broken_pack_says_nothing_was_read_not_nothing_was_found():
    report = DeepResearchEngine._mood_lexicon(Q_SAD, BrokenPack())
    assert report["ran"] is False
    assert "galti se seekhi nahi ja saki" in report["reason"]
    # "kuch nahi mila" wala jhooth yahan nahi likha jaata.
    assert "nahi mila" not in report["reason"]


def test_no_pack_at_all_means_nothing_was_read_and_nothing_is_claimed():
    report = DeepResearchEngine._mood_lexicon(Q_SAD, None)
    # `ran` seedhe "kitni source padhi gayi" se banta hai — 0 source par ye
    # False rehta hai, kyunki "kuch nahi mila" kehna jhooth hota.
    assert report["ran"] is False
    assert report["cues"] == [] and report["sources_scanned"] == 0
    assert ml.confirmed_pairs(report) == ()
    assert ml.section_lines(report)[0].startswith("Bhaav ki shabdawali nahi")


def test_the_lane_costs_nothing_even_when_it_runs():
    report = DeepResearchEngine._mood_lexicon(Q_SAD, PACK)
    assert report["gemini_calls"] == 0 and report["network_used"] is False


def test_result_object_has_a_mood_lexicon_field_that_defaults_to_empty():
    assert "mood_lexicon: Dict = field(default_factory=dict)" in _src("models.py")
    result = ResearchResult(question="q", answer="a")
    assert result.mood_lexicon == {}
    assert result.to_dict()["mood_lexicon"] == {}
    filled = ResearchResult(question="q", answer="a",
                            mood_lexicon=ml.public_record(LEDGER))
    assert filled.to_dict()["mood_lexicon"]["confirmed_count"] == 2
    assert filled.to_dict()["mood_lexicon"]["feeling_proven"] is False


def test_orchestrator_learns_once_and_hands_the_same_ledger_to_craft():
    # Do jagah do baar seekhne se do alag record ban jaate — isliye ek hi
    # ledger banta hai aur wahi craft ko jaata hai.
    src = _src("orchestrator.py")
    assert "from . import mood_lexicon" in src
    assert "mood_ledger = self._mood_lexicon(question, pack)" in src
    assert src.count("mood_lexicon.learn(") == 1
    assert "mood_ledger=mood_ledger" in src
    assert '"mood_lexicon": mood_ledger,' in src
    assert "mood_lexicon=mood_lexicon.public_record(" in src


def test_the_answer_block_stays_empty_until_something_was_really_learned():
    assert ml.mood_section(None) == "" and ml.mood_section({}) == ""
    assert ml.mood_section({"mood_lexicon": ml.not_run("x")}) == ""
    assert ml.mood_limits({"mood_lexicon": ml.not_run("x")}) == []
    assert ml.mood_limits(None) == []
    assert ml.report_of("kachra") == {} and ml.report_of({"mood_lexicon": 7}) == {}


def test_the_answer_block_and_the_audit_come_from_one_craft_report():
    report = craft.run_craft(Q_SAD, "```\n" + DRAFT + "\n```",
                             mood_ledger=LEDGER)
    text = ml.mood_section(report)
    assert text.startswith(ml.SUBHEADING)
    assert "\"aansu\"" in text and "source: s1, s2" in text
    assert "hataa nahi sakta" in text
    assert ml.mood_limits(report) == list(ml.limits())
    # Jo ledger naap me laga, usi ka record chhapta hai.
    assert report["mood_lexicon"]["confirmed_cues"] == ["aansu", "muskaan"]


def test_the_answer_prints_the_mood_block_next_to_craft_never_instead_of_it():
    src = _src("synthesizer_claude.py")
    assert "from .mood_lexicon import mood_limits, mood_section" in src
    craft_at = src.index("craft_text = craft_section(craft_report)")
    mood_at = src.index("mood_text = mood_section(craft_report)")
    assert craft_at < mood_at
    assert "parts.append(craft_text)" in src
    assert "parts.append(music_text)" in src          # music block bacha hua hai
    assert "parts.append(mood_text)" in src
    assert src.index("music_text = music_section(") < mood_at


def test_the_audit_tail_never_silently_cuts_a_new_mood_limit_line():
    # Haath se likhi ginti [:7] ho jaati to aage jodi gayi seema-line chup-chaap
    # kat jaati — isliye ginti module se hi aati hai.
    src = _src("synthesizer_claude.py")
    assert ("from .mood_lexicon import MAX_AUDIT_LIMIT_LINES as "
            "MOOD_MAX_AUDIT_LIMIT_LINES") in src
    where = src.index("for mood_line in mood_limits(")
    tail = src[where:where + 200]
    assert tail.count("[:MOOD_MAX_AUDIT_LIMIT_LINES]") == 1
    assert "craft_report" in tail
    assert ml.MAX_AUDIT_LIMIT_LINES == len(ml.limits())


def test_craft_reads_the_ledger_but_never_builds_one_itself():
    src = _src("craft.py")
    assert "from . import lang_bridge, mood_lexicon, songcraft" in src
    assert src.count("mood_lexicon.confirmed_pairs(mood_ledger)") == 1
    assert '"mood_lexicon_record": mood_lexicon.public_record(mood_ledger),' in src
    # craft khud kabhi seekhta nahi — ledger bahar (orchestrator) se aata hai.
    # `learn(` ka naam sirf samjhaane wali line me aa sakta hai, code me nahi.
    for line in src.splitlines():
        if "mood_lexicon.learn(" in line:
            assert "`" in line, line


def test_the_opposite_and_drop_paths_call_mood_hints_without_learned():
    # Ye poore #149 ka sabse bhaari niyam hai, isliye code me hi pin kiya jaata
    # hai: jo raaste line hataate hain wo curated list ke bina kuch nahi karte.
    songcraft_src = _src("songcraft.py")
    assert "learned" not in songcraft_src.split("def _check_mood_conflict")[1][:900]
    lab_src = _src("songlab.py")
    body = lab_src.split("def _opposite_moods")[1][:600]
    assert "learned" not in body
    rows = lab_src.split("def line_rows")[1][:2500]
    assert "mood_asked_learned" not in rows


def test_songcraft_gets_only_the_curated_ask():
    # Doosra leak-raasta: `songcraft.style_of(moods=...)` ka `ask.moods`
    # `context_facts` me jaata hai aur wahi `_check_mood_conflict` ka ULTA-bhaav
    # set banata hai. Isliye yahan seekha shabd bhejna mana hai.
    src = _src("craft.py")
    assert "moods=spec.mood_asked)" in src
    assert "moods=spec.mood_asked_learned" not in src
    assert "moods=spec.mood_asked + " not in src
    ask = songcraft.style_of(Q_SAD, moods=SPEC_SAD.mood_asked)
    assert "dukh" in list(getattr(ask, "moods", []) or [])


def test_the_curated_tuple_is_the_same_object_after_learning():
    before = craft.MOODS
    learn(("q1", "Here viraha (judaai) is used."),
          ("q2", "Again viraha (judaai) is used."))
    assert craft.MOODS is before
    assert len(craft.MOODS) == len(before)


def test_nothing_here_is_random_two_runs_are_identical():
    pairs = (("s1", "In these lyrics aansu, that is dukh, returns."),
             ("s2", "Here aansu means dukh for the listener."))
    first, second = learn(*pairs), learn(*pairs)
    assert first == second
    assert craft.measure(DRAFT, SPEC_SAD) == craft.measure(DRAFT, SPEC_SAD)
    assert (sl.test_mood_arc(DRAFT, SPEC_SAD)
            == sl.test_mood_arc(DRAFT, SPEC_SAD))
    assert ml.section_lines(first) == ml.section_lines(second)







