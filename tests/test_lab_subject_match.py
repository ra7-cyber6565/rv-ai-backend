"""#188b — JHOOTHA PASS band: "number mil gaya" ≠ "IS daawe ka number mil gaya".

#188a ke audit me ek reproducible jhootha nateeja naapa gaya tha. SCIENCE run
(craft_ask=False), hypothesis "Listeners ki GSR 20% se zyada badhegi jab chorus
aayega", aur evidence me sirf perovskite solar cell ke do paper:

    RESULT threshold  TESTED_PASS  all_measurements_satisfy
           expected='> 20 %'  observed='26.1 % [S1], 24.5 % [S2]'

Yaani solar cell ki efficiency se GSR ka daawa "test pass" ho gaya. Wajah:
`_run_threshold` sirf DIMENSION milata tha, aur "percent" kisi bhi cheez ka hota
hai. Jhoota PASS na-chale test se zyada khatarnaak hai — isliye ye file dono
naye taalo ke peeche padi hai, aur SAATH me ye bhi pin karti hai ki purana sahi
rasta ek akshar bhi nahi badla:

  A. TAALA 1 (`body_signal_hit`) — bina-unit naap par insaani signal ka daawa
     (GSR/EEG/HRV/cortisol/listening test/"10 logon par") app ke andar PASS nahi
     ban sakta. Ye #155e ke craft-time darwaze ki JAGAH nahi hai — wo abhi bhi
     spec banne se pehle rokta hai; ye grading ke waqt rokta hai, har run me.
  B. TAALA 2 (`subject_overlap`) — percent/bina-unit number ka VISHAY bhi daawe
     se milna chahiye. Context = number ki apni line + usi source ka title,
     kyunki "[S1] 26.1%" me koi topic shabd hi nahi hota. Topic shabd app ke
     apne `query_hygiene.content_tokens` se aate hain — koi nayi keyword list
     nahi banayi gayi.
  C. SEEMA — dono taale sirf `percent` / `bare:*` par lagte hain. Physical
     dimension (K, Pa, J, m, s) par purana rasta bilkul waisa hi chalta hai, aur
     iski naapi hui wajah yahan pin hai: "Tc 250 K se zyada hoga" ke topic shabd
     sirf ['family'] nikalte hain (2-akshar ka symbol tokenizer se nikal jaata
     hai), to overlap maangte hi ek SAHI test DATA_MISSING ho jaata.
  D. CHHUPAO MAT — jo number chhode gaye wo `observed`, `evidence_ids`, `numbers`
     aur `detail` — chaaron jagah ginti ke saath dikhte hain.

Sab kuch OFFLINE aur ₹0 — na Gemini, na network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import lab  # noqa: E402
from research_engine import query_hygiene  # noqa: E402


class _Src:
    """Sirf wahi field jo `lab.evidence_text()` padhta hai."""

    def __init__(self, source_id, title, snippet="", full_text=""):
        self.source_id = source_id
        self.title = title
        self.snippet = snippet
        self.full_text = full_text


class _Pack:
    def __init__(self, sources):
        self.sources = list(sources)


def _threshold(statement, sources, craft=False, question=None):
    """Ek hypothesis ka threshold nateeja (na mile to None)."""
    hypothesis = {"hypothesis_id": "RV-HYP-1", "statement": statement,
                  "reasoning": "naap ke liye"}
    policy = lab.LabPolicy(craft_ask=craft)
    specs = lab.plan_specs(hypothesis, _Pack(sources), policy,
                           question=question if question is not None else statement)
    for spec in specs:
        if spec.recipe == "threshold":
            return lab.run_specs([spec], policy)[0]
    return None


SOLAR = (_Src("S1", "Perovskite solar cell efficiency reached 26.1% in 2024"),
         _Src("S2", "Module efficiency of 24.5% reported under standard test"))


# ── A. wahi bimari jo #188a me naapi gayi thi ────────────────────────────────
def test_gsr_claim_no_longer_passes_on_solar_cell_percentages():
    """Naapi hui kharabi: GSR ka daawa perovskite ke % se PASS ho jaata tha."""
    result = _threshold("Listeners ki GSR 20% se zyada badhegi jab chorus aayega",
                        SOLAR)
    assert result is not None, "threshold spec banna hi chahiye"
    assert result.status == lab.DATA_MISSING, result.status
    assert result.status != lab.TESTED_PASS
    assert result.reason_code == lab.REASON_HUMAN_SIGNAL, result.reason_code
    # Wajah me wahi phrase naam se aana chahiye jis par roka gaya.
    assert "GSR" in result.detail
    # Aur solar cell ka number nateeje ka saboot ban kar nahi ghusna chahiye.
    assert "26.1" not in result.observed


def test_gsr_claim_rollup_is_not_pass_end_to_end():
    """Facade se bhi (run_lab) is hypothesis ka rollup PASS nahi hona chahiye."""
    hypothesis = {"hypothesis_id": "RV-HYP-1",
                  "statement": "Listeners ki GSR 20% se zyada badhegi",
                  "reasoning": "arousal badhta hai"}
    report = lab.run_lab("gaane ka asar", [hypothesis], pack=_Pack(SOLAR))
    rows = [row for row in (report.get("hypotheses") or [])
            if row.get("hypothesis_id") == "RV-HYP-1"]
    assert rows, report.keys()
    assert rows[0].get("status") != lab.TESTED_PASS, rows[0]


def test_body_signal_list_is_narrow_on_purpose():
    """Ye list JAAN-BOOJH KAR chhoti hai — warna sahi science mar jaata."""
    for text in ("pulse duration 30 fs", "Sloan Digital Sky Survey",
                 "subjects of the study were rocks", "interview transcript",
                 "volunteers helped translate", "saliva of the reagent"):
        assert lab.body_signal_hit(text) == "", text
    for text in ("GSR rose sharply", "EEG alpha band", "cortisol level",
                 "listening test with 30 people", "10 logon par test",
                 "HRV dropped", "shrota ka asar", "dil ki dhadkan"):
        assert lab.body_signal_hit(text) != "", text


# ── B. vishay milna zaroori hai (percent har cheez ka hota hai) ──────────────
def test_percent_with_matching_subject_still_grades():
    """Sahi rasta zinda: efficiency ka daawa efficiency ke % se naapa jaata hai."""
    result = _threshold("Is cell ki efficiency 20% se zyada hogi", SOLAR)
    assert result.status == lab.TESTED_PASS, (result.status, result.reason_code)
    assert result.reason_code == "all_measurements_satisfy"
    assert result.evidence_ids == ["S1", "S2"], result.evidence_ids


def test_percent_without_matching_subject_is_data_missing():
    """Revenue growth ka daawa solar cell ke % se kabhi PASS na ho."""
    result = _threshold("Company ka revenue growth 20% se zyada hoga", SOLAR)
    assert result.status == lab.DATA_MISSING, result.status
    assert result.reason_code == lab.REASON_SUBJECT_MISMATCH, result.reason_code
    # Chhupao mat: jo number mile the wo ginti ke saath dikhne chahiye.
    assert "26.1" in result.observed and "24.5" in result.observed
    assert result.evidence_ids == ["S1", "S2"], result.evidence_ids
    assert result.numbers.get("off_topic_numbers") == 2, result.numbers
    assert result.numbers.get("graded_numbers") == 0, result.numbers


def test_off_topic_numbers_are_named_even_when_verdict_is_pass():
    """On-topic par faisla, par chhoda hua number wajah me naam se aaye."""
    sources = list(SOLAR) + [_Src("S3", "India inflation eased to 12% last year")]
    result = _threshold("Is cell ki efficiency 20% se zyada hogi", sources)
    assert result.status == lab.TESTED_PASS, (result.status, result.reason_code)
    assert result.evidence_ids == ["S1", "S2"], result.evidence_ids
    assert "S3" not in result.evidence_ids
    assert "12 %" in result.detail and "[S3]" in result.detail
    assert "chhoda gaya" in result.detail


def test_subject_can_come_from_the_source_title_line():
    """"[S4] 26.1%" akeli line me topic shabd nahi hota — title bhi padha jaaye."""
    matching = _Src("S4", "Perovskite solar cell efficiency record",
                    snippet="Reached 26.1% in 2024")
    result = _threshold("Is cell ki efficiency 20% se zyada hogi", [matching])
    assert result.status == lab.TESTED_PASS, (result.status, result.reason_code)
    # Wahi snippet, par title ka vishay badal do → wapas DATA_MISSING.
    other = _Src("S4", "Quarterly logistics dashboard",
                 snippet="Reached 26.1% in 2024")
    flipped = _threshold("Is cell ki efficiency 20% se zyada hogi", [other])
    assert flipped.status == lab.DATA_MISSING, flipped.status
    assert flipped.reason_code == lab.REASON_SUBJECT_MISMATCH, flipped.reason_code


# ── C. purana sahi rasta ek akshar bhi na badle ──────────────────────────────
def test_physical_dimension_path_is_untouched():
    """K/Pa/J waale number apna vishay khud batate hain — wahan shart nahi."""
    result = _threshold("Critical temperature 250 K se zyada hoga",
                        [_Src("S9", "Superconducting transition temperature "
                                    "Tc = 288 K measured")])
    assert result.status == lab.TESTED_PASS, (result.status, result.reason_code)
    assert result.evidence_ids == ["S9"], result.evidence_ids


def test_two_char_symbol_is_the_measured_reason_for_narrow_scope():
    """Naapi hui wajah: "Tc" tokenizer se nikal jaata hai, isliye scope chhota."""
    tokens = query_hygiene.content_tokens("Is family ka Tc 250 K se zyada hoga.")
    assert "tc" not in tokens and "Tc" not in tokens, tokens
    # Isi wajah se temperature par overlap NAHI maanga gaya — warna ye sahi
    # test DATA_MISSING ho jaata.
    result = _threshold("Is family ka Tc 250 K se zyada hoga.",
                        [_Src("S1", "Tc 260 K reported"),
                         _Src("S2", "onset near 265 K")])
    assert result.status == lab.TESTED_PASS, (result.status, result.reason_code)
    assert result.evidence_ids == ["S1", "S2"], result.evidence_ids


def test_human_word_on_physical_dimension_still_grades():
    """Taala 1 sirf bina-unit naap par — 305 K ka number phir bhi naapa jaaye."""
    result = _threshold("Skin temperature 300 K se zyada hoga",
                        [_Src("S10", "Sensor logged 305 K on the surface")])
    assert result.status == lab.TESTED_PASS, (result.status, result.reason_code)
    assert lab.body_signal_hit("Skin temperature 300 K se zyada hoga") != ""


# ── D. helper ka likha hua contract ──────────────────────────────────────────
def test_needs_subject_match_contract():
    assert lab.needs_subject_match("percent") is True
    assert lab.needs_subject_match("bare:citations") is True
    for dimension in ("temperature", "pressure", "energy", "length", "time",
                      "mass", "magnetic_field", "speed", "", None):
        assert lab.needs_subject_match(dimension) is False, dimension


def test_subject_overlap_uses_stems_and_ignores_junk():
    assert lab.subject_overlap("Listeners ki GSR badhegi",
                               "Listener panel notes") != ""
    assert lab.subject_overlap("Company ka revenue growth 20% se zyada",
                               "Perovskite solar cell efficiency") == ""
    # Junk/meta shabd se jhootha rishta na bane (query_hygiene.JUNK ka faayda).
    assert lab.subject_overlap("Company ka growth 20% se zyada hoga",
                               "kaam dhyaan se jaldi karo 26.1%") == ""


def test_tagged_quantities_old_shape_is_preserved():
    """Purana (tag, quantity) aakar zinda hai, aur asli parser ek hi hai."""
    text = lab.evidence_text(_Pack(SOLAR), lab.LabPolicy())
    pairs = lab._tagged_quantities(text, "percent")
    rows, titles = lab._tagged_rows(text, "percent")
    assert pairs == [(tag, quantity) for tag, quantity, _line in rows]
    assert all(len(pair) == 2 for pair in pairs), pairs
    assert [tag for tag, _q in pairs] == ["S1", "S2"], pairs
    assert titles["S1"].startswith("Perovskite"), titles


def test_tagged_rows_title_is_the_first_line_of_that_source():
    source = _Src("S5", "Alpha title line", snippet="Beta snippet 30% here",
                  full_text="Gamma full text 40% here")
    text = lab.evidence_text(_Pack([source]), lab.LabPolicy())
    rows, titles = lab._tagged_rows(text, "percent")
    assert titles["S5"] == "Alpha title line", titles
    assert [line for _t, _q, line in rows] == ["Beta snippet 30% here",
                                               "Gamma full text 40% here"], rows


def test_new_reason_codes_are_distinct_and_named():
    codes = {lab.REASON_HUMAN_SIGNAL, lab.REASON_SUBJECT_MISMATCH}
    assert len(codes) == 2, codes
    assert all(code and code == code.strip() for code in codes), codes
    assert "no_matching_measurement" not in codes


# ── E. #155e ka darwaza, ginti, aur likhi hui seema ──────────────────────────
def test_craft_time_door_155e_still_closes_first():
    """Craft farmaish par spec banti hi nahi — wo purana pehra waisa hi hai."""
    hypothesis = {"hypothesis_id": "RV-HYP-1",
                  "statement": "Listeners ki GSR 20% se zyada badhegi",
                  "reasoning": "arousal"}
    specs = lab.plan_specs(hypothesis, _Pack(SOLAR),
                           lab.LabPolicy(craft_ask=True), question="gaana")
    assert specs == [], specs
    assert lab.human_subject_phrase(hypothesis) != ""


def test_no_percent_in_evidence_keeps_the_old_reason():
    result = _threshold("Company ka revenue growth 20% se zyada hoga",
                        [_Src("S6", "Sample cost 40 dollars")])
    assert result.status == lab.DATA_MISSING, result.status
    assert result.reason_code == "no_matching_measurement", result.reason_code


def test_result_is_deterministic_and_status_is_from_the_closed_list():
    first = _threshold("Company ka revenue growth 20% se zyada hoga", SOLAR)
    second = _threshold("Company ka revenue growth 20% se zyada hoga", SOLAR)
    assert first.to_dict() == second.to_dict()
    assert first.status in lab.LAB_STATUSES, first.status
    assert first.to_dict()["is_established_fact"] is False
    assert first.to_dict()["real_world_experiment_pending"] is True


def test_known_limits_are_written_down_not_hidden():
    for note in (lab.SUBJECT_MATCH_KNOWN_LIMIT, lab.HUMAN_SIGNAL_KNOWN_LIMIT):
        assert isinstance(note, str) and len(note) > 60, note
    assert "percent" in lab.SUBJECT_MATCH_KNOWN_LIMIT
    assert "GSR" in lab.HUMAN_SIGNAL_KNOWN_LIMIT
