"""#121 — CRAFT stage: "bana kar do" wali maang par app apna draft KHUD naapta hai.

Naapa gaya defect: "hindi me gaana banao" par pipeline research karti thi, draft
likh deti thi, aur bas. Draft par koi naap nahi chalti thi — isliye "acha bana
hai" sirf model ka apna daawa reh jaata tha. intel ki maang: banane wali farmaish
par bhi wahi process chale (research → spec → draft → KHUD test → wajah ke saath
reject → dobara) aur aakhir me sach likha ho ki kya naapa gaya.

Is file ke kaam:
  1. stage sirf BANANE ki farmaish par chale — research ke sawaal (RPF paper,
     trading model, "math basic se strong kaise karun") is raste par aayein hi
     nahi,
  2. matra/tuk ka hisaab asli ho (Devanagari laghu-guru classical value par
     pin hai) aur roman wala hisaab HAMESHA "approx" label ke saath aaye,
  3. jo naapa nahi ja sakta (pasand, viral, dhun, copyright) wo naam se likha
     rahe — aur draft khud aisa daawa kare to wo ek FAIL check ho,
  4. jo cheez maangi hi nahi gayi uska check `NOT_MEASURED` ho — chuppi kabhi
     "sab theek" na bane, aur andar ki galti par bhi `MET` na aaye,
  5. dobara likhwana bounded ho (ek round), aur "behtar nahi tha" par purana
     draft hi rahe — revision hone se hi kuch acha nahi ho jaata,
  6. naap ka koi shabd LAB ke shabdon se na mile (TESTED_PASS padh kar koi
     gaane ko "proven" na samjhe), aur wiring (orchestrator → ResearchResult →
     synthesizer) sach me judi ho.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import answer_order, craft, lab  # noqa: E402
from research_engine import orchestrator, synthesizer_claude  # noqa: E402
from research_engine.models import ResearchResult  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name: str) -> str:
    with open(os.path.join(_ROOT, "research_engine", name),
              encoding="utf-8") as handle:
        return handle.read()


def _fenced(body: str) -> str:
    return "Ye lo.\n\n```" + craft.DRAFT_FENCE + "\n" + body + "\n```\n"


_SONG = ("raat gehri hai mera man akela\n"
         "chand bhi aaj lagta hai akela\n"
         "tanhai mere paas baith gayi\n"
         "ye kahani mere saath reh gayi\n"
         "raat gehri hai mera man akela\n"
         "door kahin ek diya jal raha\n"
         "mere andar bhi kuch chal raha\n"
         "raat gehri hai mera man akela")


# ── 1. detection: sirf BANANE ki farmaish ───────────────────────────────────
def test_song_request_detected():
    found = craft.detect("hindi me tanhai par 8 line ka gaana banao")
    assert found["is_request"] is True
    assert found["form"] == "song"


def test_research_questions_never_enter_craft():
    """Ye sabse zaroori guard hai: CRAFT normal research ko hijack na kare."""
    for question in (
            "room temperature superconductivity par latest research kya kehti hai",
            "math basic se strong kaise karun",
            "kaunsa business karu 2026 me",
            "Kabir ki kavita ke baare me batao",
            "Feynman ki kahani batao",
            "RPF SI exam ka syllabus kya hai",
            "nifty ka trading model kaise kaam karta hai",
            "gyan aur vigyan me farak kya hai",
            "mere gaon ka itihas batao"):
        assert craft.detect(question)["is_request"] is False, question


def test_make_verb_alone_is_not_enough():
    found = craft.detect("ek report banao superconductivity par")
    assert found["is_request"] is False
    assert found["reason"] == "no_form_word"


def test_form_word_alone_is_not_enough():
    found = craft.detect("is gaane ka matlab samjhao")
    assert found["is_request"] is False
    assert found["reason"] == "no_make_verb"


def test_devanagari_request_detected():
    found = craft.detect("हिंदी में तनहाई पर 16 मात्रा का गीत लिखो")
    assert found["is_request"] is True
    assert found["form"] == "song"


def test_plain_research_deliverable_words_are_kept_out_on_purpose():
    """
    "report/summary/note banao" pipeline ka aam kaam hai. Agar CRAFT wahan chal
    jaaye to model se draft ko fence me maanga jaayega aur poore structured
    jawaab ki shakal bigdegi — isliye ye shabd kisi form me nahi hain.
    """
    for word in ("report", "summary", "note", "blog", "post", "article",
                 "column", "overview"):
        # (a) exclusion table me naam se maujood — ye list chhoti ho gayi to
        # detect() ki doosri deewar chup-chaap kam shabdon par lagegi.
        assert word in craft.PROSE_DELIVERABLE_WORDS, word
        for form in craft.FORMS:
            assert word not in form.romans, (word, form.form_id)
        found = craft.detect(f"superconductivity par ek {word} banao")
        assert found["is_request"] is False, word
        assert found["reason"] == "no_form_word", word


def test_prose_word_inside_a_form_would_still_not_fire():
    """Dohri deewar: list me shabd wapas aa jaaye to bhi detect band rahe."""
    poisoned = craft.Form("essay", "test", ("report",))
    original = craft.FORMS
    try:
        craft.FORMS = (poisoned,) + original
        assert craft.detect("ek report banao")["is_request"] is False
    finally:
        craft.FORMS = original


def test_creative_forms_still_fire():
    wanted = {
        "climate change par nibandh likho": "essay",
        "ek chhoti kahani likho": "story",
        "job ke liye application likho": "letter",
        "school ke liye bhashan tayaar karo": "speech",
        "ek shayari likho": "poem",
        "chai brand ke liye tagline banao": "slogan",
        "do doston ka samvaad likho": "dialogue",
    }
    for question, form in wanted.items():
        found = craft.detect(question)
        assert found["is_request"] is True, question
        assert found["form"] == form, question


# ── 2. matra ka hisaab classical value par pin hai ──────────────────────────
def test_indic_matra_matches_classical_values():
    """Ye number chhand-shastra ki jaani-maani ginti hain — inhe badalna mana."""
    assert craft.matra_indic("प्रेम") == 3       # प्रे(2) + म(1)
    assert craft.matra_indic("सत्य") == 3        # स(guru, aage cluster) + त्य(1)
    assert craft.matra_indic("कमल") == 3         # teen laghu
    assert craft.matra_indic("जिंदगी") == 5      # जिं(2) + द(1) + गी(2)
    assert craft.matra_indic("मेरा नाम राम है") == 12


def test_anusvara_makes_a_syllable_guru():
    assert craft.matra_indic("अग") == 2
    assert craft.matra_indic("अंग") == 3


def test_other_indic_scripts_fold_onto_devanagari():
    """Gurmukhi/Bangla ke liye alag table nahi — code point fold hota hai."""
    assert craft.matra_indic("ਪ੍ਰੇਮ") == craft.matra_indic("प्रेम")


def test_roman_matra_is_labelled_approx_not_classical():
    assert craft.matra_rule_for("मेरा नाम") == craft.MATRA_RULE_INDIC
    assert craft.matra_rule_for("mera naam") == craft.MATRA_RULE_ROMAN
    assert craft.matra_rule_for("123 456") == ""
    # roman par hum swar-group ginte hain, laghu-guru nahi — isliye number alag
    # aata hai aur usko classical value ki tarah nahi bech sakte.
    assert craft.matra_roman("mera naam raam hai") != craft.matra_indic(
        "मेरा नाम राम है")


def test_matra_of_uses_the_named_rule():
    assert craft.matra_of("मेरा", craft.MATRA_RULE_INDIC) == 4
    assert craft.matra_of("mera", craft.MATRA_RULE_ROMAN) == 2
    assert craft.matra_of("मेरा") == craft.matra_of(
        "मेरा", craft.MATRA_RULE_INDIC)


def test_rhyme_key_is_from_the_last_vowel_group():
    assert craft.rhyme_key("meri jaan") == "aan"
    assert craft.rhyme_key("teri पहचान") == "aan"
    assert craft.rhyme_key("mera man") == "an"
    assert craft.rhyme_key("meri jaan") != craft.rhyme_key("mera man")


def test_scheme_and_coverage_are_measured_not_guessed():
    assert craft.scheme_of(["jaan", "pahchan", "man", "dhan"]) == "abbb"
    coverage, schemes = craft.rhyme_coverage("jaan\npahchan\nman\ndhan")
    assert coverage == 0.75
    assert schemes == ["abbb"]
    assert craft.rhyme_coverage("ek\ndo\nteen\nchar")[0] == 0.0


# ── 3. SPEC: sirf jo SAAF maanga gaya ───────────────────────────────────────
def test_spec_only_takes_explicit_targets():
    spec = craft.build_spec("hindi me tanhai par 8 line ka gaana banao")
    assert spec.line_target == 8
    # ye teen maange hi nahi gaye — isliye 0, andaza nahi
    assert spec.matra_target == 0
    assert spec.stanza_target == 0
    assert spec.word_target == 0
    assert spec.mood_asked == ["tanhai"]


def test_spec_never_claims_quality_or_appeal():
    spec = craft.build_spec("ek gaana banao")
    assert spec.to_dict()["quality_claim"] is False
    assert spec.to_dict()["appeal_claim"] is False


def test_spec_reads_hinglish_and_devanagari_counts_the_same_way():
    for question, field, value in (
            ("do antare ka gaana likho 150 shabd me", "stanza_target", 2),
            ("do antare ka gaana likho 150 shabd me", "word_target", 150),
            ("8 panktiyon ka geet likho", "line_target", 8),
            ("आठ पंक्ति का गीत लिखो", "line_target", 8),
            ("सोलह मात्रा का गीत लिखो", "matra_target", 16),
            ("दो अंतरे का गीत लिखो", "stanza_target", 2)):
        spec = craft.build_spec(question)
        assert getattr(spec, field) == value, (question, field)


def test_number_inside_a_word_does_not_become_a_target():
    """"loneliness" ke andar ka "one" + "line" mil kar line_target 1 banata tha."""
    spec = craft.build_spec("loneliness par ek gaana likho")
    assert spec.line_target == 0


def test_mood_word_is_not_matched_inside_a_bigger_word():
    """"maatraa" ke andar "maa" mil jaata tha aur maa ka gaana ban jaata tha."""
    spec = craft.build_spec("16 maatraa ka gaana banao")
    assert "maa" not in spec.mood_asked
    assert craft.build_spec("maa par bhajan likho").mood_asked[0] == "maa"


def test_user_can_switch_the_rhyme_check_off():
    on = craft.build_spec("ek gaana likho")
    off = craft.build_spec("ek gaana likho bina tuk ke")
    assert on.rhyme_required is True
    assert off.rhyme_required is False
    assert any("mana kiya" in note for note in off.notes)


# ── 4. naap: jo maanga tha wahi naapa, baaki NOT_MEASURED ───────────────────
def _measure_song(question: str, draft: str = _SONG):
    spec = craft.build_spec(question)
    assert spec is not None
    return craft.measure(draft, spec)


def _by_name(measured, name: str):
    for check in measured["checks"]:
        if check["check"] == name:
            return check
    raise AssertionError("check nahi mila: " + name)


def test_good_song_passes_the_checks_that_were_asked_for():
    measured = _measure_song("tanhai par 8 line ka gaana banao")
    assert measured["status"] == craft.DRAFT_OK
    assert _by_name(measured, "line_count")["status"] == craft.MET
    assert _by_name(measured, "rhyme")["status"] == craft.MET
    assert _by_name(measured, "refrain_hook")["status"] == craft.MET


def test_unasked_things_are_not_measured_never_met():
    """Chuppi ko "sab theek hai" padhna hi asli defect tha."""
    measured = _measure_song("tanhai par 8 line ka gaana banao")
    for name in ("stanza_count", "word_count", "matra_target", "script_match"):
        check = _by_name(measured, name)
        assert check["status"] == craft.NOT_MEASURED, name
        assert check["reason"], name          # wajah hamesha likhi ho
        assert check["note"], name


def test_every_check_carries_the_two_honest_lines():
    measured = _measure_song("tanhai par 8 line ka gaana banao")
    assert measured["checks"]
    for check in measured["checks"]:
        assert check["quality_proven"] is False, check["check"]
        assert check["human_reaction_untested"] is True, check["check"]


def test_roman_matra_check_is_flagged_approx():
    measured = _measure_song("16 matra ka gaana banao")
    check = _by_name(measured, "matra_target")
    assert check["approx"] is True
    assert measured["measured"]["matra_rule"] == craft.MATRA_RULE_ROMAN


def test_indic_matra_check_is_not_flagged_approx():
    draft = ("मेरा नाम राम है\nतेरा नाम काम है\n"
             "मेरा नाम राम है\nदिल में एक शाम है")
    measured = craft.measure(draft, craft.build_spec("१२ मात्रा का गीत लिखो"))
    check = _by_name(measured, "matra_target")
    assert check["approx"] is False
    assert measured["measured"]["matra_rule"] == craft.MATRA_RULE_INDIC


_BAD = ("ye gaana pakka hit hoga sabko pasand aayega\n"
        "dil ke armaan tere bina\nbas\nbas\nbas")


def test_weak_draft_fails_with_named_measured_reasons():
    measured = _measure_song("tanhai par 8 line ka 16 matra ka gaana banao",
                             _BAD)
    assert measured["status"] == craft.DRAFT_WEAK
    failed = {c["check"]: c for c in measured["checks"]
              if c["status"] == craft.NOT_MET}
    assert set(failed) == {"line_count", "matra_target", "matra_consistency",
                           "cliche_density", "no_appeal_claim",
                           "mood_words_present"}
    for name, check in failed.items():
        assert check["reason"], name
        assert check["note"], name
        assert check["target"] != "", name


def test_draft_claiming_it_will_be_a_hit_is_a_failed_check():
    """App ye daawa nahi karta; draft kare to wo bhi naap me FAIL hai."""
    measured = _measure_song("tanhai par gaana banao", _BAD)
    check = _by_name(measured, "no_appeal_claim")
    assert check["status"] == craft.NOT_MET
    assert check["reason"] == "unsupported_appeal_claim"
    assert craft.appeal_claims_in("ye superhit hoga") == ["superhit"]
    assert craft.appeal_claims_in(_SONG) == []


def test_script_mismatch_is_caught_only_when_the_question_had_a_script():
    devanagari = craft.measure("mera naam raam hai\nteri baat yaad hai",
                               craft.build_spec("तनहाई पर गीत लिखो"))
    check = _by_name(devanagari, "script_match")
    assert check["status"] == craft.NOT_MET
    assert check["measured"] == "latin"
    assert check["target"] == "devanagari"
    roman = _measure_song("tanhai par gaana banao")
    assert _by_name(roman, "script_match")["status"] == craft.NOT_MEASURED


def test_empty_and_missing_draft_are_their_own_states():
    spec = craft.build_spec("ek gaana banao")
    assert craft.measure("", spec)["status"] == craft.NO_DRAFT
    assert craft.measure("   \n ", spec)["status"] == craft.NO_DRAFT
    assert craft.measure(_SONG, None)["status"] == craft.NOT_RUN
    assert craft.measure("", spec)["checks"] == []


def test_a_broken_check_is_not_measured_never_met():
    """Andar ki galti par bhi kabhi MET nahi — fail-closed."""
    def explode(spec, facts):
        raise RuntimeError("jaan-boojh kar toda")

    original = craft.CHECKS
    try:
        craft.CHECKS = (("rhyme", explode),) + tuple(
            item for item in original if item[0] != "rhyme")
        measured = _measure_song("tanhai par 8 line ka gaana banao")
        check = _by_name(measured, "rhyme")
        assert check["status"] == craft.NOT_MEASURED
        assert check["reason"] == "check_error"
    finally:
        craft.CHECKS = original


def test_check_status_must_be_a_known_word():
    try:
        craft._check("kuch bhi", "PASSED")
    except AssertionError:
        pass
    else:
        raise AssertionError("galat status chup-chaap chala gaya")


def test_roll_up_order_weak_beats_ok_and_silence_is_its_own_state():
    original = craft.CHECKS
    spec = craft.build_spec("ek gaana banao")
    try:
        craft.CHECKS = (
            ("a", lambda s, f: craft._check("a", craft.MET, measured=1)),
            ("b", lambda s, f: craft._skip("b", "x", "y")),
        )
        assert craft.measure(_SONG, spec)["status"] == craft.DRAFT_OK
        craft.CHECKS = craft.CHECKS + (
            ("c", lambda s, f: craft._check("c", craft.NOT_MET, measured=2)),)
        assert craft.measure(_SONG, spec)["status"] == craft.DRAFT_WEAK
        craft.CHECKS = (("b", lambda s, f: craft._skip("b", "x", "y")),)
        assert craft.measure(_SONG, spec)["status"] == craft.DRAFT_UNMEASURED
    finally:
        craft.CHECKS = original


def test_the_never_measurable_list_stays_named():
    for must in ("pasand", "viral", "dhun", "copyright"):
        assert any(must in item for item in craft.CANNOT_MEASURE), must
    assert craft.CLICHE_LIST_IS_NOT_EXHAUSTIVE is True
    assert craft.MOOD_LIST_IS_NOT_EXHAUSTIVE is True
    # naam hi imaandaar hona chahiye: shabd milna bhaav aana nahi hai
    assert any(name == "mood_words_present" for name, _ in craft.CHECKS)
    assert not any(name == "mood_achieved" for name, _ in craft.CHECKS)


# ── 5. draft kahan se uthaya — audit ka text kabhi naapa na jaaye ───────────
_SPEC_SONG = None


def _song_spec():
    global _SPEC_SONG
    if _SPEC_SONG is None:
        _SPEC_SONG = craft.build_spec("ek gaana banao")
    return _SPEC_SONG


def test_marked_block_wins_over_any_other_fence():
    text = ("```python\nprint(1)\n```\n\n" + _fenced(_SONG))
    draft, source = craft.extract_draft(text, _song_spec())
    assert source == "marked_block"
    assert draft.startswith("raat gehri")


def test_plain_fence_is_the_second_choice():
    text = "baat ye hai.\n\n```\n" + _SONG + "\n```\n"
    draft, source = craft.extract_draft(text, _song_spec())
    assert source == "code_block"
    assert draft == _SONG


def test_verse_shape_is_only_a_guess_and_says_so():
    text = "ye jawab hai\n\n" + _SONG + "\n\n## Sources\n- https://x.example\n"
    draft, source = craft.extract_draft(text, _song_spec())
    assert source == "verse_shape_guess"
    assert draft == _SONG
    # non-verse form par ye andaza hota hi nahi
    assert craft.extract_draft(text, craft.build_spec(
        "ek kahani likho"))[1] == ""


def test_audit_prose_is_never_picked_up_as_a_draft():
    """Sabse bada khatra: number sahi, par kisi galat hisse ka."""
    audit = ("## AUDIT\n"
             "- kitne source pade gaye: 4\n"
             "- kitne claim VERIFIED hue: 2\n"
             "1. pehla point\n"
             "2. doosra point\n"
             "> quote wali line\n"
             "| table | row |\n"
             "https://example.org/paper\n")
    assert craft.extract_draft(audit, _song_spec()) == ("", "")


def test_too_short_or_missing_draft_returns_empty_not_a_guess():
    assert craft.extract_draft("bas do line\nsirf itna", _song_spec()) == ("", "")
    assert craft.extract_draft("", _song_spec()) == ("", "")
    assert craft.extract_draft(_SONG, None) == ("", "")


# ── 6. dobara likhwana bounded hai — aur "behtar" naapa jaata hai ───────────
_Q_HARD = "tanhai par 8 line ka 16 matra ka gaana banao"
_ANSWER_BAD = _fenced(_BAD)


def _reviser_of(body: str):
    def reviser(prompt: str) -> str:
        assert "chahiye" in prompt or "SHART" in prompt.upper() or prompt
        return "theek hai.\n\n" + _fenced(body)
    return reviser


def test_no_reviser_means_no_revision_and_the_report_says_why():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD)
    assert report["status"] == craft.DRAFT_WEAK
    assert report["revision"]["attempted"] is False
    assert report["revision"]["reason"] == "reviser_not_available"
    assert report["gemini_calls"] == 0
    assert report["revision"]["notes"]


def test_better_second_draft_is_kept():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=_reviser_of(_SONG))
    assert report["revision"]["ran"] is True
    assert report["revision"]["rounds"] == 1
    assert report["revision"]["kept"] == "doosra"
    assert report["final_draft"] == _SONG
    assert report["original_draft"] == _BAD
    assert report["gemini_calls"] == 1


def test_second_draft_that_only_hides_the_measurement_is_rejected():
    """
    Draft chhota kar dene se check "naapne laayak" hi nahi rehte aur fail ki
    ginti gir jaati hai. Ye behtar hona nahi, chhup jaana hai.
    """
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD,
                             reviser=_reviser_of("bas\nbas\nbas"))
    assert report["revision"]["kept"] == "pehla"
    assert report["revision"]["reason"] == "second_draft_measured_less"
    assert report["final_draft"] == _BAD


def test_equal_second_draft_keeps_the_first():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=_reviser_of(_BAD))
    assert report["revision"]["kept"] == "pehla"
    assert report["revision"]["reason"] == "second_draft_not_better"


def test_revision_is_capped_at_one_round():
    calls = []

    def reviser(prompt: str) -> str:
        calls.append(prompt)
        return "phir bhi kharab\n\n" + _fenced("bas\nbas\nbas\nbas")

    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=reviser)
    assert len(calls) == 1
    assert craft.MAX_REVISION_ROUNDS == 1
    assert report["revision"]["rounds"] <= 1
    assert report["gemini_calls"] == 1


def test_reviser_that_explodes_is_recorded_not_swallowed():
    def reviser(prompt: str) -> str:
        raise RuntimeError("model gir gaya")

    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=reviser)
    assert report["revision"]["attempted"] is True
    assert report["revision"]["ran"] is False
    assert report["revision"]["reason"] == "reviser_error"
    assert report["final_draft"] == _BAD


def test_reviser_that_returns_nothing_is_recorded():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=lambda p: "   ")
    assert report["revision"]["ran"] is False
    assert report["revision"]["reason"] == "reviser_returned_nothing"


def test_no_failure_means_no_revision_attempt():
    good = craft.run_craft("tanhai par 8 line ka gaana banao", _fenced(_SONG),
                           reviser=_reviser_of(_BAD))
    assert good["status"] == craft.DRAFT_OK
    assert good["revision"]["attempted"] is False
    assert good["revision"]["reason"] == "no_measured_failure"
    assert good["gemini_calls"] == 0


def test_missing_draft_is_not_sent_for_revision():
    report = craft.run_craft(_Q_HARD, "koi draft nahi diya gaya",
                             reviser=_reviser_of(_SONG))
    assert report["status"] == craft.NO_DRAFT
    assert report["revision"]["reason"] == "no_draft_to_revise"
    assert report["gemini_calls"] == 0


# ── 7. jawab me wahi draft dikhe jo naapa gaya ──────────────────────────────
def test_answer_is_updated_only_when_the_second_draft_won():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=_reviser_of(_SONG))
    new_text, changed = craft.apply_final_draft(_ANSWER_BAD, report)
    assert changed is True
    assert _SONG in new_text
    assert _BAD not in new_text
    # Kuch kaata nahi gaya: sirf draft ka hissa badla.
    assert new_text.replace(_SONG, _BAD) == _ANSWER_BAD


def test_answer_is_left_alone_when_the_first_draft_was_kept():
    for reviser in (None, _reviser_of(_BAD), _reviser_of("bas\nbas\nbas")):
        report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=reviser)
        assert report["revision"]["kept"] == "pehla"
        assert craft.apply_final_draft(_ANSWER_BAD, report) == (_ANSWER_BAD,
                                                                False)


def test_answer_is_left_alone_for_a_non_craft_question():
    report = craft.run_craft("superconductivity par ek report banao",
                             _ANSWER_BAD)
    assert report["ran"] is False
    assert craft.apply_final_draft(_ANSWER_BAD, report) == (_ANSWER_BAD, False)
    assert craft.apply_final_draft(_ANSWER_BAD, None) == (_ANSWER_BAD, False)
    assert craft.apply_final_draft(_ANSWER_BAD, {}) == (_ANSWER_BAD, False)


def test_answer_is_left_alone_if_the_old_draft_is_not_in_the_text():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD, reviser=_reviser_of(_SONG))
    assert report["revision"]["kept"] == "doosra"
    other = "kuch aur hi likha hai yahan par\n"
    assert craft.apply_final_draft(other, report) == (other, False)


def test_kept_pehla_is_obeyed_even_if_the_report_carries_another_draft():
    """
    Faisla `kept` par hota hai, sirf "do draft alag hain" par nahi. Warna koi
    aisi report (jo ban gayi/ban sakti hai) jismein pehla draft rakha gaya ho,
    chup-chaap doosra draft jawab me chipka degi — aur naap pehle draft ki hogi.
    """
    hand_made = {"ran": True, "revision": {"kept": "pehla"},
                 "original_draft": _BAD, "final_draft": _SONG}
    assert craft.apply_final_draft(_ANSWER_BAD, hand_made) == (_ANSWER_BAD,
                                                               False)


# ── 8. policy, determinism aur ₹0 ───────────────────────────────────────────
def test_policy_says_exactly_what_this_stage_did_and_did_not_do():
    policy = craft.POLICY.to_dict()
    assert policy == {
        "network_used": False,
        "randomness_used": False,
        "model_written_code_executed": False,
        "deterministic": True,
        "provider_cost": "₹0",
        "revision_rounds_max": 1,
        "measured_by": "offline_rules_in_craft_py",
        "structure_only": True,
        "quality_proven": False,
        "human_reaction_untested": True,
    }
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD)
    assert report["policy"] == policy
    assert report["provider_cost"] == "₹0"


def test_the_measurement_itself_never_spends_a_gemini_call():
    for question, answer in (
            (_Q_HARD, _ANSWER_BAD),
            ("tanhai par 8 line ka gaana banao", _fenced(_SONG)),
            ("do antare ka gaana likho", "koi draft nahi"),
            ("superconductivity par ek report banao", _ANSWER_BAD)):
        assert craft.run_craft(question, answer)["gemini_calls"] == 0


def test_same_input_gives_the_identical_report_twice():
    first = craft.run_craft(_Q_HARD, _ANSWER_BAD)
    second = craft.run_craft(_Q_HARD, _ANSWER_BAD)
    assert first == second
    assert craft.craft_section(first) == craft.craft_section(second)
    assert craft.craft_limits(first) == craft.craft_limits(second)


# ── 9. jo likha jaata hai wo naap se aata hai, generic nahi ─────────────────
def test_section_is_a_sub_block_not_a_new_top_heading():
    assert craft.CRAFT_SUBHEADING.startswith("### ")
    assert not craft.CRAFT_SUBHEADING.startswith("## ")
    body = craft.craft_section(craft.run_craft(_Q_HARD, _ANSWER_BAD))
    assert body.startswith(craft.CRAFT_SUBHEADING)
    assert "\n## " not in body


def test_section_is_empty_when_the_stage_did_not_run():
    for report in (None, {}, {"ran": False},
                   craft.run_craft("superconductivity par report banao",
                                   _ANSWER_BAD)):
        assert craft.craft_section(report) == ""
        assert craft.craft_limits(report) == []


def test_section_carries_the_status_the_disclaimer_and_the_failed_checks():
    report = craft.run_craft(_Q_HARD, _ANSWER_BAD)
    body = craft.craft_section(report)
    assert craft.DRAFT_WEAK in body
    assert "pasand" in body.lower()
    for name in ("line_count", "matra_target", "no_appeal_claim"):
        assert "`" + name + "`" in body
    assert "`reviser_not_available`" in body
    for item in craft.CANNOT_MEASURE:
        assert item in body


def test_limits_come_from_the_measured_state_not_a_generic_line():
    weak = craft.craft_limits(craft.run_craft(_Q_HARD, _ANSWER_BAD))
    joined = " ".join(weak)
    assert "3 dhaanche wale naap target par the aur 6 nahi" in joined
    assert "approx" in joined
    assert "reviser_not_available" in joined

    missing = craft.craft_limits(craft.run_craft(_Q_HARD, "koi draft nahi"))
    assert any("naapne laayak draft nahi mila" in line for line in missing)
    assert not any("dhaanche wale naap target par" in line
                   for line in missing)

    devanagari = craft.craft_limits(craft.run_craft(
        "१६ मात्रा का गाना बनाओ",
        _fenced("मेरा नाम राम है\nतेरा नाम श्याम है")))
    assert not any("approx" in line for line in devanagari)


def test_every_report_shape_carries_the_audio_and_similarity_limit():
    for question, answer in ((_Q_HARD, _ANSWER_BAD),
                             ("tanhai par 8 line ka gaana banao",
                              _fenced(_SONG)),
                             (_Q_HARD, "koi draft nahi mila")):
        limits = craft.craft_limits(craft.run_craft(question, answer))
        assert any("koi audio nahi bana" in line for line in limits)


# ── 10. CRAFT aur LAB ke shabd alag hain (naap ghul-mil na jaaye) ───────────
_LAB_WORDS = ("TESTED_PASS", "TESTED_FAIL", "NOT_TESTABLE_HERE",
              "DATA_MISSING", "PROVEN", "VERIFIED")


def test_craft_never_borrows_lab_or_proof_words():
    reports = [craft.run_craft(_Q_HARD, _ANSWER_BAD),
               craft.run_craft(_Q_HARD, _ANSWER_BAD,
                               reviser=_reviser_of(_SONG)),
               craft.run_craft("tanhai par 8 line ka gaana banao",
                               _fenced(_SONG)),
               craft.run_craft(_Q_HARD, "koi draft nahi")]
    for report in reports:
        blob = repr(report) + craft.craft_section(report) + " ".join(
            craft.craft_limits(report))
        for word in _LAB_WORDS:
            assert word not in blob, word


def test_craft_statuses_are_its_own_words():
    assert craft.CHECK_STATUSES == (craft.MET, craft.NOT_MET,
                                    craft.NOT_MEASURED)
    assert set(craft.DRAFT_STATUSES) == {
        craft.DRAFT_OK, craft.DRAFT_WEAK, craft.DRAFT_UNMEASURED,
        craft.NO_DRAFT, craft.NOT_RUN}
    for word in _LAB_WORDS:
        assert word not in craft.DRAFT_STATUSES
        assert word not in craft.CHECK_STATUSES


# ── 11. wiring: stage sach me pipeline se juda hai (na ki bas maujood hai) ──
def test_orchestrator_runs_the_stage_and_carries_its_report():
    src = _src("orchestrator.py")
    assert "from . import craft" in src
    assert '"craft": {}' in src
    # Draft ko fence me maangna sirf CRAFT wali farmaish par.
    assert 'if craft.detect(question).get("is_request"):' in src
    assert "craft.DRAFT_INSTRUCTION" in src
    assert 'out["craft"] = craft.run_craft(' in src
    assert "craft.apply_final_draft(" in src
    assert 'out["craft"]["answer_updated"]' in src
    # Naap jawab BANNE ke baad hoti hai, par call-ginti likhne se PEHLE —
    # warna revision ka ek call hisaab me hi nahi aata.
    assert src.index('out["craft"] = craft.run_craft(') < src.index(
        'out["calls"] = brain.calls_used')
    # Report do jagah jaati hai: answer banane wale ke paas aur result me.
    assert "craft_report=passes.get(\"craft\")" in src
    assert "craft=passes.get(\"craft\")" in src


def test_the_revision_call_uses_the_budget_that_already_exists():
    src = _src("orchestrator.py")
    where = src.index('out["craft"] = craft.run_craft(')
    window = src[max(0, where - 900):where]
    # Naya budget nahi banta: usi brain se, aur sirf tab jab call bacha ho.
    assert "brain.remaining >= 1" in window
    assert 'brain.generate(prompt, "craft_redraft")' in window
    assert "QuotaExhausted" in window


def test_synthesizer_puts_the_block_in_the_lab_section_and_the_audit_tail():
    src = _src("synthesizer_claude.py")
    assert "from .craft import craft_limits, craft_section" in src
    assert "craft_report: Optional[Dict] = None" in src
    assert "craft_text = craft_section(craft_report)" in src
    assert "craft_limits(craft_report)[:5]" in src
    # LAB wale section (index 5) ke andar, apni nayi `##` heading banaye bina.
    lab_at = src.index("elif index == 5:")
    next_at = src.index("elif index == 9:")
    assert lab_at < src.index("craft_text = craft_section(craft_report)") < next_at
    # assemble se _audit_section tak report pahunchti hai.
    assert "craft_report=craft_report)" in src


def test_result_object_keeps_the_craft_report():
    src = _src("models.py")
    assert "craft: Dict = field(default_factory=dict)" in src


# ── 12. jo maanga jaata hai wahi padha ja sakta hai (loop band hai) ─────────
def test_the_instruction_asks_for_exactly_the_block_the_extractor_reads():
    assert craft.DRAFT_FENCE in craft.DRAFT_INSTRUCTION
    assert "```" + craft.DRAFT_FENCE in craft.DRAFT_INSTRUCTION
    # Wahi block extractor bhi dhoondta hai — instruction aur reader alag na ho.
    text = ("meri baat.\n\n```" + craft.DRAFT_FENCE + "\n" + _SONG
            + "\n```\n\nbaad ki baat.")
    draft, source = craft.extract_draft(text, _song_spec())
    assert source == "marked_block"
    assert draft == _SONG


def test_the_instruction_forbids_the_claim_that_cannot_be_measured():
    lowered = craft.DRAFT_INSTRUCTION.lower()
    for word in ("hit", "viral", "pasand"):
        assert word in lowered
    assert "naapa hi nahi ja sakta" in craft.DRAFT_INSTRUCTION









