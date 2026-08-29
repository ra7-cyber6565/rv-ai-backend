"""#141 — SONG LAB: "bana diya" ≠ "khud test kar liya".

intel ki maang ka wahi hissa jo abhi tak adhoora tha: "khud ko 3-4 tarah se test
kre phir de" aur "kyu nikal rhe kya strong proof h ye kaam nhi krega". #121 ne
CRAFT ka naap bana diya tha, par wo naap POORE draft par ek hi pass thi — isliye
do jhooth khule pade the:

    1. "Chaar tarah se test kiya" — jabki ek hi pass ko chaar naam de dena kaafi
       hota. Isliye yahan chaaron test ka `method` ALAG likha hua hona chahiye
       aur chaaron ka nateeja alag cheez par aana chahiye.
    2. "Kamzor line hata di" — bina ye bataye ki kaunsi line, kis naapi hui
       wajah se, aur hatane ke BAAD naap giri ya nahi. Chupke se line kaat dena
       "saaf kiya" jaisa dikhta hai, hota "kaat diya" hai.

Is file ke kaam:
  1. LINE ka nateeja — KEEP/FIX/DROP, aur DROP sirf TOOTE NIYAM par (jhootha
     daawa, dhun ka daawa, ulta bhaav); matra/ghisa-pita/script wali kamzori
     HATAAI nahi jaati, wo redraft ki note me jaati hai.
  2. HATAANA khud naapa hua ho — cap, floor, refrain ki roK, aur hatane ke baad
     poore draft ki dobara naap; naap giri to hataana WAAPAS.
  3. Paanch alag "hataaya nahi ja saka" ke paanch ALAG code aur alag wajah — do
     bilkul alag halaat ko ek naam dena padhne wale ko dhoka dena hai.
  4. Chaar test asli me alag hon, aur "naapa hi nahi ja saka" `TESTED_FAIL` na
     ban jaaye (bhaav ka shabd na milna FAIL nahi, DATA_MISSING hai).
  5. Test USI draft par chalen jo DIYA jaayega (`tested_draft: after_drop`) —
     warna "pass wala draft" aur "diya gaya draft" alag ho jaate.
  6. Koi naya naap-ka-dimaag na bane: matra/cliché/daawa/bhaav/score/rollup sab
     craft/songcraft/lab se udhaar — do jagah do sach nahi.
  7. ₹0 aur imaandaari: 0 Gemini call, 0 network, koi randomness nahi, koi dhun
     nahi, kuch suna nahi gaya — aur report/audit me ye seemaayein likhi hui.
  8. WIRING sach me judi ho: craft → song_lab, orchestrator → ResearchResult,
     synthesizer → block + audit ki seema.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import lab  # noqa: E402
from research_engine import songcraft  # noqa: E402
from research_engine import songlab as sl  # noqa: E402
from research_engine.models import ResearchResult  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name: str) -> str:
    with open(os.path.join(_ROOT, "research_engine", name),
              encoding="utf-8") as handle:
        return handle.read()


def _brace_slice(src: str, needle: str) -> str:
    """Call ke andar ka hissa — closing paren GIN kar, ginti se nahi.

    Purane static test ek "jaadui" character-count ki khidki lete the aur agar
    beech me ek line jud jaati to TOOT jaate the (halaanki behaviour theek
    rehta). Yahan bracket asli me match kiya jaata hai.
    """
    start = src.index(needle)
    depth = 0
    for index in range(start, len(src)):
        char = src[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return src[start:index + 1]
    raise AssertionError("NEEDLE-BAD: bracket band nahi hua: " + needle)


# ── farmaish (spec) ─────────────────────────────────────────────────────────
# Chaar alag farmaish jaan-boojh kar: ek me THEEK 8 line maangi gayi (floor ==
# line_target, isliye "ginti toot jaayegi" wali roK), ek khuli farmaish (floor
# sirf min_lines se), ek me 2 antara, aur ek Devanagari me (target_script tabhi
# bharta hai jab sawaal khud non-latin ho).
Q_EXACT = "hindi me tanhai par 8 line ka 16 matra ka gaana banao"
Q_OPEN = "hindi me tanhai par gaana banao"
Q_SAD = "sad hindi gaana likho judaai par 2 antara mukhda ke saath"
Q_DEVA = "तनहाई पर हिंदी में गाना लिखो"
Q_POEM = "tanhai par ek kavita likho"


def _spec(question: str):
    return craft.build_spec(question, craft.detect(question))


SPEC_EXACT = _spec(Q_EXACT)
SPEC_OPEN = _spec(Q_OPEN)
SPEC_SAD = _spec(Q_SAD)
SPEC_DEVA = _spec(Q_DEVA)
SPEC_POEM = _spec(Q_POEM)

# ── draft (jo naapa jaayega) ────────────────────────────────────────────────
HOOK = "tanhai mere paas baith gayi"

# 8 line, hook teen baar, koi naapi hui shikayat nahi — "sab KEEP" ka base.
CLEAN = "\n".join([
    HOOK,
    "raat gehri hai mera man akela",
    "chand bhi aaj lagta hai akela",
    HOOK,
    "door kahin ek diya jal raha",
    "mere andar bhi kuch chal raha",
    HOOK,
    "ye kahani mere saath reh gayi",
])

# Naapa hua jhooth: "hit hoga / sabko pasand aayega" — ye DROP wala code hai.
APPEAL_LINE = "ye gaana pakka hit hoga sabko pasand aayega"
# Dhun ka daawa — yahan koi dhun bani hi nahi, isliye ye bhi DROP.
MUSIC_LINE = "iski dhun bahut sureeli lagegi"
# Maanga hua bhaav "tanhai" tha; is line me uska ULTA bhaav hai.
MOOD_LINE = "dosti hi meri duniya hai yaaron"
# Ghisa-pita — kamzori hai, jhooth nahi; isliye FIX (hataayi NAHI jaayegi).
CLICHE_LINE = "dil ke armaan tere bina adhoore"

CLAIM_AT_5 = CLEAN.replace("door kahin ek diya jal raha", APPEAL_LINE)
CLICHE_AT_8 = CLEAN.replace("ye kahani mere saath reh gayi", CLICHE_LINE)
MUSIC_AT_5 = CLEAN.replace("door kahin ek diya jal raha", MUSIC_LINE)
MOOD_AT_5 = CLEAN.replace("door kahin ek diya jal raha", MOOD_LINE)

# Refrain hi jhootha daawa kar rahi hai — hook kabhi hataya nahi jaata, isliye
# teeno baar "hataaya NAHI ja saka" wali entry aani chahiye.
REFRAIN_CLAIMS = "\n".join([
    APPEAL_LINE,
    "raat gehri hai mera man akela",
    APPEAL_LINE,
    "chand bhi aaj lagta hai akela",
    APPEAL_LINE,
    HOOK,
])

# 10 line, teen line niyam tod rahi hain, par cap sirf 2 hai (10 * 0.20).
CAP_DRAFT = "\n".join([
    HOOK,
    APPEAL_LINE,
    "raat gehri hai mera man akela",
    "ye gaana zaroor viral hoga",
    "chand bhi aaj lagta hai akela",
    MUSIC_LINE,
    "door kahin ek diya jal raha",
    "mere andar bhi kuch chal raha",
    HOOK,
    "ye kahani mere saath reh gayi",
])

# 6 line — ek line hatane par 5 bachti, aur floor 6 hai (min_lines).
FLOOR_DRAFT = "\n".join([
    HOOK,
    "raat gehri hai mera man akela",
    APPEAL_LINE,
    "chand bhi aaj lagta hai akela",
    HOOK,
    "ye kahani mere saath reh gayi",
])

# Do antare, aakhri line jhootha daawa — hataane par naap SUDHARTI hai, isliye
# hataana asli me lagta hai (`applied: True`).
APPLIED_DRAFT = "\n".join([
    "gham ki raat lambi hai yaar",
    HOOK,
    "judaai ka dard yahi hai",
    APPEAL_LINE,
    "",
    "udaas shaam dhal gayi hai",
    HOOK,
    "gham ka saaya reh gaya hai",
    "ye kahani aage badhi hai",
])

# Wahi jhootha daawa, par ab wo DOOSRE antare ki AKELI line hai. Hataane par
# antara hi khatam ho jaata hai (2 antara maange the) — naap GIR jaati hai,
# isliye ek bhi line hataayi NAHI jaani chahiye.
REVERT_DRAFT = "\n".join([
    "gham ki raat lambi hai yaar",
    HOOK,
    "judaai ka dard yahi hai",
    "udaas shaam dhal gayi hai",
    HOOK,
    "gham ka saaya reh gaya hai",
    "",
    APPEAL_LINE,
])

# ── padhi hui baat (study) ──────────────────────────────────────────────────
class _Src:
    """Duck-typed source — `songcraft.guidance_from` isi shape par padhta hai."""

    def __init__(self, source_id: str, text: str) -> None:
        self.source_id = source_id
        self.title = ""
        self.snippet = text
        self.url = "https://example.org/" + source_id
        self.connector = "test_stub"


REAL_CONVENTION_TEXT = (
    "In this tradition a verse is usually four lines long, and writers should "
    "keep the chorus repeating 3 times across the song.")


def _study(conventions, sources=1):
    """Haath se bana guidance — `songlab._study_block` isi ko seedha padhta hai."""
    return {"numeric_conventions": list(conventions),
            "guidance_source_count": int(sources)}


STUDY_NONE = _study([], sources=0)
STUDY_READ_NO_NUMBER = _study([], sources=3)
STUDY_STANZA_4 = _study([{"kind": "lines_per_stanza", "value": 4,
                          "source_id": "src-1"}])
STUDY_STANZA_3 = _study([{"kind": "lines_per_stanza", "value": 3,
                          "source_id": "src-1"}])
STUDY_HOOK_2 = _study([{"kind": "refrain_times", "value": 2,
                        "source_id": "src-2"}])
STUDY_HOOK_9 = _study([{"kind": "refrain_times", "value": 9,
                        "source_id": "src-2"}])
STUDY_UNKNOWN_KIND = _study([{"kind": "bpm", "value": 70,
                              "source_id": "src-3"}])


def _row_of(rows, line_no):
    for row in rows:
        if row.get("line_no") == line_no:
            return row
    raise AssertionError("line %s ka row hi nahi mila" % line_no)


# ══════════════════════════════════════════════════════════════════════════════
# 1. LINE ka nateeja — KEEP / FIX / DROP
# ══════════════════════════════════════════════════════════════════════════════
def test_clean_song_has_no_complaint_on_any_line():
    rows = sl.line_rows(CLEAN, SPEC_EXACT)
    assert len(rows) == 8
    assert [row["status"] for row in rows] == [sl.LINE_KEEP] * 8
    assert all(row["codes"] == [] and row["reasons"] == [] for row in rows)


def test_every_line_row_says_out_loud_that_naap_is_not_quality():
    # Sabse aasaan jhooth: "line KEEP hai" padh kar log "line achhi hai" samajh
    # lein. Isliye ye do sach HAR row ke saath chalte hain, chaahe status kuch
    # bhi ho.
    for draft in (CLEAN, CLAIM_AT_5, CLICHE_AT_8):
        rows = sl.line_rows(draft, SPEC_EXACT)
        assert rows
        for row in rows:
            assert row["quality_proven"] is False
            assert row["human_reaction_untested"] is True


def test_appeal_claim_line_is_a_drop_not_a_fix():
    row = _row_of(sl.line_rows(CLAIM_AT_5, SPEC_EXACT), 5)
    assert sl.CODE_APPEAL_CLAIM in row["codes"]
    assert row["status"] == sl.LINE_DROP
    assert row["measured"]["appeal_claims"]
    # Wajah insaani zubaan me likhi ho — code ka naam padhne wale ke liye wajah
    # nahi hota.
    assert any("naapa hi nahi ja sakta" in reason for reason in row["reasons"])


def test_music_quality_claim_is_a_drop_because_no_tune_was_made():
    row = _row_of(sl.line_rows(MUSIC_AT_5, SPEC_EXACT), 5)
    assert sl.CODE_MUSIC_CLAIM in row["codes"]
    assert row["status"] == sl.LINE_DROP
    assert row["measured"]["music_claims"]


def test_opposite_mood_line_is_a_drop():
    row = _row_of(sl.line_rows(MOOD_AT_5, SPEC_EXACT), 5)
    assert sl.CODE_MOOD_CONFLICT in row["codes"]
    assert row["status"] == sl.LINE_DROP
    assert row["measured"]["opposite_moods"]


def test_cliche_line_is_only_a_fix_never_a_drop():
    # Ghisa-pita shabd kamzori hai, jhooth nahi. Aisi line hata dene se gaane ki
    # BAAT chali jaati hai — isliye ye sirf redraft ki note me jaati hai.
    row = _row_of(sl.line_rows(CLICHE_AT_8, SPEC_EXACT), 8)
    assert sl.CODE_CLICHE in row["codes"]
    assert row["status"] == sl.LINE_FIX
    assert sl.CODE_CLICHE not in sl.DROP_CODES


def test_line_in_the_wrong_script_is_a_fix_and_names_the_script():
    deva = "\n".join([
        "तनहाई मेरे पास बैठ गई",
        "रात गहरी है मन अकेला",
        "tanhai mere paas baith gayi roman me",
        "चाँद भी आज लगता है अकेला",
        "तनहाई मेरे पास बैठ गई",
        "ये कहानी मेरे साथ रह गई",
    ])
    assert SPEC_DEVA.target_script == "devanagari"
    row = _row_of(sl.line_rows(deva, SPEC_DEVA), 3)
    assert sl.CODE_SCRIPT_OFF in row["codes"]
    assert row["status"] == sl.LINE_FIX
    assert row["measured"]["script"] == "latin"


def test_a_line_that_breaks_a_rule_and_is_also_weak_is_still_a_drop():
    # DROP aur FIX dono code ek hi line par lag sakte hain (lambi daawe wali line
    # matra par bhi bahar hoti hai). Aisi haalat me FIX jeet jaana khatarnaak
    # hota: jhooth report me bacha reh jaata.
    row = _row_of(sl.line_rows(CLAIM_AT_5, SPEC_EXACT), 5)
    assert sl.CODE_MATRA_OUTLIER in row["codes"]
    assert sl.CODE_APPEAL_CLAIM in row["codes"]
    assert sl.CODE_ACTION[sl.CODE_MATRA_OUTLIER] == sl.LINE_FIX
    assert row["status"] == sl.LINE_DROP


def test_the_hook_line_is_flagged_as_refrain():
    rows = sl.line_rows(CLEAN, SPEC_EXACT)
    assert [row["line_no"] for row in rows if row["is_refrain"]] == [1, 4, 7]


def test_no_lines_means_no_rows_instead_of_a_fake_zero_report():
    assert sl.line_rows("", SPEC_EXACT) == []
    assert sl.line_rows("   \n\n  ", SPEC_EXACT) == []


def test_roman_matra_is_labelled_approx_because_it_is_a_guess():
    # Roman (Hinglish) me matra ka hisaab approx hai. Us andaze par "line atakti
    # hai" likhna theek hai, par label ke BINA likhna over-claim hoga.
    row = _row_of(sl.line_rows(CLAIM_AT_5, SPEC_EXACT), 5)
    assert craft.matra_rule_for(CLAIM_AT_5) == craft.MATRA_RULE_ROMAN
    assert row["approx"] is True
    # Jis line par matra ki shikayat nahi, us par approx ka label bhi nahi —
    # warna label ka matlab hi khatam.
    assert _row_of(sl.line_rows(CLEAN, SPEC_EXACT), 2)["approx"] is False


def test_every_code_has_exactly_one_action_and_one_human_reason():
    codes = set(sl.CODE_ACTION)
    assert codes == set(sl.CODE_REASON)
    assert set(sl.DROP_CODES) | set(sl.FIX_CODES) == codes
    # Ek code dono list me nahi ho sakta — warna "hataana hai ya sudhaarna hai"
    # ka jawab do ho jaata.
    assert not set(sl.DROP_CODES) & set(sl.FIX_CODES)
    assert len(set(sl.CODE_REASON.values())) == len(codes)
    for code, reason in sl.CODE_REASON.items():
        assert len(reason) > 30, code


def test_only_broken_rules_can_ever_be_dropped():
    # Ye poore stage ka sabse zaroori faisla hai: line sirf tab hatti hai jab
    # usme JHOOTH ho (naapa na ja sakne wala daawa, dhun ka daawa, ulta bhaav).
    # Kamzori par hataana = "kaat kar naap sudhaarna", jo khud ek dhokha hai.
    assert set(sl.DROP_CODES) == {sl.CODE_APPEAL_CLAIM, sl.CODE_MUSIC_CLAIM,
                                  sl.CODE_MOOD_CONFLICT}
    assert set(sl.FIX_CODES) == {sl.CODE_MATRA_OUTLIER, sl.CODE_CLICHE,
                                 sl.CODE_SCRIPT_OFF}


# ══════════════════════════════════════════════════════════════════════════════
# 2. HATAANA khud naapa hua hai — cap, floor, refrain, aur dobara naap
# ══════════════════════════════════════════════════════════════════════════════
def test_drop_cap_is_a_share_with_a_hard_ceiling_and_a_one_line_floor():
    assert sl.MAX_DROP_SHARE == 0.20
    assert sl.MAX_DROPS == 4
    assert sl._drop_cap(0) == 0
    # Chhote draft par bhi ek line ki gunjaish rehti hai — usse aage floor aur
    # naap-guard rokte hain, cap nahi.
    assert sl._drop_cap(1) == 1
    assert sl._drop_cap(5) == 1
    assert sl._drop_cap(10) == 2
    # Chhat MAX_DROPS par hai: 40 line par bhi 8 nahi, 4 hi.
    assert sl._drop_cap(20) == 4
    assert sl._drop_cap(40) == 4


def test_line_floor_is_borrowed_from_songcraft_and_raised_by_the_ask():
    # "Gaana kehne laayak kitni line" ka jawab songcraft me pehle se hai. Yahan
    # apna doosra number likhne se do jagah do sach ban jaate.
    assert sl.MIN_LINES_AFTER_DROP is songcraft.MIN_LINES_FOR_SING
    assert sl._drop_floor(None) == songcraft.MIN_LINES_FOR_SING
    # Farmaish zyada maange to floor uthta hai (8 line maangi thi).
    assert SPEC_EXACT.line_target == 8
    assert sl._drop_floor(SPEC_EXACT) == 8
    assert sl._drop_floor(SPEC_OPEN) == SPEC_OPEN.min_lines == 6


def test_the_hook_is_never_dropped_even_when_it_lies():
    plan = sl.drop_plan(REFRAIN_CLAIMS, SPEC_OPEN)
    assert sl.REFRAIN_NEVER_DROPPED is True
    assert plan["dropped"] == []
    refused = plan["refused"]
    assert len(refused) == 3
    assert {entry["refused"] for entry in refused} == {sl.DROP_REFUSED_REFRAIN}
    for entry in refused:
        assert "mukhda/hook" in entry["refused_reason"]
        assert sl.CODE_APPEAL_CLAIM in entry["codes"]


def test_exact_count_refusal_is_a_different_answer_from_the_floor_refusal():
    # Dono me line bachti hai, par user ko karna ALAG kaam hai: "theek 8 line
    # maangi thi" par line BADALNI hai, aur "gaana hi na bache" par bachani hai.
    # Ek naam de dena padhne wale ko dhoka dena hoga.
    exact = sl.drop_plan(CLAIM_AT_5, SPEC_EXACT)
    assert exact["floor"] == 8 == exact["total_lines"]
    assert exact["dropped"] == []
    assert [entry["refused"] for entry in exact["refused"]] == [
        sl.DROP_REFUSED_EXACT_COUNT]
    assert "maangi hui ginti" in exact["refused"][0]["refused_reason"]

    floor = sl.drop_plan(FLOOR_DRAFT, SPEC_OPEN)
    assert floor["floor"] == 6 == floor["total_lines"]
    assert floor["dropped"] == []
    assert [entry["refused"] for entry in floor["refused"]] == [
        sl.DROP_REFUSED_FLOOR]
    assert floor["refused"][0]["floor"] == 6
    assert (exact["refused"][0]["refused_reason"]
            != floor["refused"][0]["refused_reason"])


def test_cap_stops_the_third_drop_and_says_so_by_name():
    plan = sl.drop_plan(CAP_DRAFT, SPEC_OPEN)
    assert plan["total_lines"] == 10
    assert plan["cap"] == 2
    assert plan["drop_line_nos"] == [2, 4]
    assert plan["lines_after"] == 8
    assert [entry["refused"] for entry in plan["refused"]] == [
        sl.DROP_REFUSED_CAP]
    # Cap teeno tarah ke toote niyam par saath milkar lagti hai — teesri line
    # dhun ka daawa thi, phir bhi cap usi ginti me hai.
    assert plan["refused"][0]["line_no"] == 6
    assert plan["refused"][0]["cap"] == 2
    assert sl.CODE_MUSIC_CLAIM in plan["refused"][0]["codes"]


def test_all_five_refusal_codes_have_five_different_written_reasons():
    codes = (sl.DROP_REFUSED_REFRAIN, sl.DROP_REFUSED_FLOOR,
             sl.DROP_REFUSED_EXACT_COUNT, sl.DROP_REFUSED_CAP,
             sl.DROP_REFUSED_MEASURE_WORSE)
    assert len(set(codes)) == 5
    assert set(sl.REFUSE_REASON) == set(codes)
    assert len(set(sl.REFUSE_REASON.values())) == 5
    for code in codes:
        assert len(sl.REFUSE_REASON[code]) > 40, code


def test_fix_lines_are_never_touched_by_the_drop_plan():
    # Ye plan sirf DROP wale code dekhta hai. Agar FIX bhi yahan aa jaaye to
    # "kamzor line kaat di" chalu ho jaata.
    plan = sl.drop_plan(CLICHE_AT_8, SPEC_OPEN)
    assert plan["dropped"] == []
    assert plan["refused"] == []
    assert plan["lines_after"] == plan["total_lines"] == 8


def test_every_dropped_entry_carries_number_text_code_and_measured_reason():
    plan = sl.drop_plan(CAP_DRAFT, SPEC_OPEN)
    assert plan["dropped"]
    for entry in plan["dropped"]:
        assert isinstance(entry["line_no"], int)
        assert entry["text"].strip()
        assert entry["codes"] and all(code in sl.DROP_CODES
                                      for code in entry["codes"])
        assert entry["reasons"] == [sl.CODE_REASON[code]
                                    for code in entry["codes"]]
        assert isinstance(entry["measured"], dict)
        # Hataayi hui line par "refused" nahi hota — dono ek hi dher me mil
        # jaayen to "hataaya" aur "hataaya nahi" ka farq mit jaata.
        assert "refused" not in entry
    assert sl.EVERY_DROP_HAS_A_MEASURED_REASON is True
    assert plan["every_drop_has_a_measured_reason"] is True
    # "Hataaya" ka matlab "behtar ho gaya" kabhi nahi.
    assert plan["improvement_proven"] is False


def test_clean_draft_counts_lines_the_way_craft_does_and_keeps_stanza_gaps():
    body = "pehli line\nteesri nahi doosri\n\nteesra hissa\nchautha hissa"
    assert sl.clean_draft(body, []) == body
    out = sl.clean_draft(body, [2])
    assert out == "pehli line\n\nteesra hissa\nchautha hissa"
    # Poora antara hat jaane par do khaali line saath nahi bachti.
    assert sl.clean_draft(body, [1, 2]) == "teesra hissa\nchautha hissa"
    assert "\n\n\n" not in sl.clean_draft(body, [1, 2])


def test_applying_a_drop_reports_the_count_before_and_after():
    out = sl.apply_drops(APPLIED_DRAFT, SPEC_SAD)
    assert out["applied"] is True
    assert out["plan"]["drop_line_nos"] == [4]
    assert out["draft"] != APPLIED_DRAFT
    assert APPEAL_LINE not in out["draft"]
    # "Kya saboot hai" ka jawab yahan NUMBER me hai — pehle ki ginti aur baad ki
    # ginti, dono report me.
    assert out["before_counts"] and out["after_counts"]
    assert (out["after_counts"].get(craft.NOT_MET, 0)
            < out["before_counts"].get(craft.NOT_MET, 0))
    # Aur usi saans me ye bhi likha hai ki ye "gaana behtar ho gaya" nahi hai.
    assert "saboot NAHI" in out["note"]


def test_a_drop_that_would_lower_the_measure_is_taken_back():
    out = sl.apply_drops(REVERT_DRAFT, SPEC_SAD)
    # Plan ne line hataane laayak maani thi (line_no khaali line ko nahi ginta,
    # isliye ye 7vi content line hai)...
    assert out["plan"]["drop_line_nos"] == [7]
    # ...par naap gir rahi thi, isliye ek bhi line hataayi nahi gayi.
    assert out["applied"] is False
    assert out["draft"] == REVERT_DRAFT
    assert out["dropped"] == []
    assert [entry["refused"] for entry in out["refused"]] == [
        sl.DROP_REFUSED_MEASURE_WORSE]
    assert (out["after_counts"].get(craft.NOT_MEASURED, 0)
            > out["before_counts"].get(craft.NOT_MEASURED, 0))
    assert "naap gir rahi thi" in out["note"]


def test_a_smaller_draft_never_counts_as_a_better_draft():
    # Line hatane se naapne laayak cheezein hi kam ho jaayen to fail apne aap
    # gir jaate hain. Wo "behtar" nahi, chhup jaana hai — aur yahi sabse aasaani
    # se green dikhne wala jhooth hai.
    before = {"status": craft.DRAFT_WEAK,
              "counts": {craft.MET: 5, craft.NOT_MET: 3, craft.NOT_MEASURED: 2}}
    same = {"status": craft.DRAFT_WEAK,
            "counts": {craft.MET: 5, craft.NOT_MET: 3, craft.NOT_MEASURED: 2}}
    hidden = {"status": craft.DRAFT_WEAK,
              "counts": {craft.MET: 5, craft.NOT_MET: 0, craft.NOT_MEASURED: 5}}
    # Barabari manzoor hai (line NIYAM todne par hat rahi hai, naap sudhaarne ke
    # liye nahi)...
    assert sl._drop_is_not_worse(same, before) is True
    # ...par naap khud kam ho jaana manzoor nahi.
    assert sl._drop_is_not_worse(hidden, before) is False
    assert sl._drop_is_not_worse(None, before) is False


def test_no_broken_rule_and_a_refused_drop_are_two_different_notes():
    # Chuppi se sabse bada dhokha yahi hota: "kisi ne niyam nahi toda" aur "toda
    # tha par hata nahi paaye" — dono par "koi line nahi hataayi" likh dena.
    clean = sl.apply_drops(CLEAN, SPEC_EXACT)
    assert clean["applied"] is False
    assert clean["refused"] == []
    assert "kisi line ne niyam nahi toda" in clean["note"]

    blocked = sl.apply_drops(CLAIM_AT_5, SPEC_EXACT)
    assert blocked["applied"] is False
    assert len(blocked["refused"]) == 1
    assert "niyam tod rahi thi par hataayi nahi ja saki" in blocked["note"]
    assert clean["note"] != blocked["note"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. CHAAR ALAG TEST — chaar naam nahi, chaar tareeqe
# ══════════════════════════════════════════════════════════════════════════════
def test_there_are_four_tests_and_four_different_written_methods():
    assert len(sl.TEST_NAMES) == 4 == len(set(sl.TEST_NAMES))
    assert set(sl.TEST_METHOD) == set(sl.TEST_NAMES)
    methods = [sl.TEST_METHOD[name] for name in sl.TEST_NAMES]
    # Chaar alag tareeqa likha hona chahiye. Ek hi vaakya char baar likh dena
    # "chaar test" ka naam bech dena hoga.
    assert len(set(methods)) == 4
    for method in methods:
        assert len(method) > 25


def test_every_test_row_carries_its_method_and_the_honesty_flags():
    report = sl.run_song_lab(CLEAN, SPEC_EXACT)
    assert report["tests"]
    for row in report["tests"]:
        assert row["method"] == sl.TEST_METHOD[row["test"]]
        assert row["quality_proven"] is False
        assert row["heard"] is False
        assert row["human_reaction_tested"] is False
        assert row["reason"].strip()


def test_structure_test_recounts_the_text_itself():
    row = sl.test_structure(CLEAN, SPEC_EXACT)
    assert row["test"] == sl.TEST_STRUCTURE
    assert row["status"] == lab.TESTED_PASS
    assert row["measured"]["lines"] == row["measured"]["craft_lines"] == 8
    # Do jagah ki ginti ka MILAAN hi is test ka asli kaam hai.
    assert row["measured"]["stanzas"] == row["measured"]["craft_stanzas"]


# Bhaav ka koi shabd nahi — na "tanhai", na "akela". Ye haalat FAIL nahi honi
# chahiye: shabd-list adhoori hai, isliye "bhaav nahi hai" kehna over-claim hai.
ZERO_CUE = "\n".join([
    "raat gehri hai mera man khoya",
    "chand bhi aaj chhupa baitha hai",
    "door kahin ek diya jal raha",
    "mere andar bhi kuch chal raha",
])

# Teen antare, bhaav sirf pehle me (share 1/3) — ye asli FAIL hai, kyunki shabd
# draft ki apni zubaan me maujood hai, bas phaila nahi.
THIN_MOOD = "\n".join([
    HOOK,
    "raat gehri hai mera man khoya",
    "",
    "chand bhi aaj chhupa baitha hai",
    "door kahin ek diya jal raha",
    "",
    "mere andar bhi kuch chal raha",
    "ye kahani mere saath reh gayi",
])

# Koi line dohraayi hi nahi gayi.
NO_REPEAT = "\n".join([
    HOOK,
    "raat gehri hai mera man khoya",
    "chand bhi aaj chhupa baitha hai",
    "door kahin ek diya jal raha",
])

# Hook aata hai, par pehli baar 60% par — der se aane wali line hook ka kaam
# nahi karti.
LATE_HOOK = "\n".join([
    "raat gehri hai mera man khoya",
    "chand bhi aaj chhupa baitha hai",
    "door kahin ek diya jal raha",
    HOOK,
    "mere andar bhi kuch chal raha",
    HOOK,
])

# Ek gaana jisme kisi bhaav ka naam liya hi nahi gaya (mood_asked khaali).
Q_NO_MOOD = "hindi me barish par gaana banao"
SPEC_NO_MOOD = _spec(Q_NO_MOOD)


def test_structure_test_fails_when_the_asked_count_is_not_there():
    row = sl.test_structure(THIN_MOOD, SPEC_EXACT)
    assert row["status"] == lab.TESTED_FAIL
    assert "8 line maangi thi, 6 hain" in row["reason"]
    assert row["expected"]["line_target"] == 8


def test_structure_test_says_data_missing_instead_of_failing_an_empty_draft():
    row = sl.test_structure("   ", SPEC_EXACT)
    assert row["status"] == lab.DATA_MISSING
    assert row["status"] != lab.TESTED_FAIL


def test_mood_test_is_not_run_at_all_when_no_mood_was_asked():
    # Bina maang par "bhaav sahi hai" likhna muft ka pass hota.
    row = sl.test_mood_arc(CLEAN, SPEC_NO_MOOD)
    assert row["status"] == lab.NOT_TESTABLE_HERE
    assert row["status"] not in (lab.TESTED_PASS, lab.TESTED_FAIL)


def test_zero_mood_words_is_data_missing_not_a_fail():
    # Yahi wo jagah hai jahan aasaani se over-claim ho jaata: shabd na milna
    # "bhaav nahi hai" nahi hai — hamari shabd-list adhoori hai.
    assert sl.MOOD_ZERO_CUE_IS_NOT_A_FAIL is True
    row = sl.test_mood_arc(ZERO_CUE, SPEC_EXACT)
    assert row["status"] == lab.DATA_MISSING
    assert row["measured"]["stanzas_with_asked_mood"] == 0
    assert row["measured"]["mood_list_is_not_exhaustive"] is True
    assert "shabd-list adhoori hai" in row["reason"]


def test_opposite_mood_anywhere_is_a_real_fail_because_the_word_is_there():
    # Ulta bhaav milna POSITIVE khoj hai — shabd maujood hai, isliye ye FAIL hi
    # rehna chahiye, DATA_MISSING nahi.
    row = sl.test_mood_arc(MOOD_AT_5, SPEC_EXACT)
    assert row["status"] == lab.TESTED_FAIL
    assert row["measured"]["conflicts"]
    assert "ULTA bhaav" in row["reason"]


def test_mood_in_only_one_of_three_stanzas_fails_on_the_borrowed_share():
    row = sl.test_mood_arc(THIN_MOOD, SPEC_EXACT)
    assert row["status"] == lab.TESTED_FAIL
    assert row["measured"]["stanzas"] == 3
    assert row["measured"]["stanzas_with_asked_mood"] == 1
    # Bar songcraft ka hai — songlab apna doosra number nahi rakhta.
    assert row["expected"]["min_share"] is songcraft.MIN_MOOD_STANZA_SHARE
    assert row["measured"]["share"] < songcraft.MIN_MOOD_STANZA_SHARE


def test_mood_test_counts_stanzas_not_the_whole_draft():
    # Ek hi antare me bhaav ke paanch shabd bhar dene se poora gaana us bhaav ka
    # nahi ho jaata — isliye arc me HAR antare ki apni entry honi chahiye.
    row = sl.test_mood_arc(THIN_MOOD, SPEC_EXACT)
    arc = row["measured"]["arc"]
    assert [entry["stanza"] for entry in arc] == [1, 2, 3]
    assert arc[0]["asked_present"] == ["tanhai"]
    assert arc[1]["asked_present"] == [] and arc[2]["asked_present"] == []


def test_hook_test_is_not_run_when_no_hook_was_asked():
    row = sl.test_hook(CLEAN, SPEC_POEM)
    assert row["status"] == lab.NOT_TESTABLE_HERE
    assert "maanga hi nahi" in row["reason"]


def test_hook_test_says_data_missing_when_there_is_nothing_to_repeat_in():
    row = sl.test_hook(HOOK, SPEC_EXACT)
    assert row["status"] == lab.DATA_MISSING
    assert row["status"] != lab.TESTED_FAIL


def test_a_line_that_never_returns_is_not_a_hook():
    row = sl.test_hook(NO_REPEAT, SPEC_EXACT)
    assert row["status"] == lab.TESTED_FAIL
    assert row["measured"]["times"] == 1 < sl.HOOK_MIN_TIMES
    assert "dohraayi hi nahi" in row["reason"]


def test_a_hook_that_arrives_too_late_fails_on_position_not_on_count():
    row = sl.test_hook(LATE_HOOK, SPEC_EXACT)
    assert row["status"] == lab.TESTED_FAIL
    # Ginti theek hai (2 baar), fail sirf JAGAH par hai — do alag wajah hain.
    assert row["measured"]["times"] >= sl.HOOK_MIN_TIMES
    assert row["measured"]["position"] > sl.HOOK_MAX_POSITION
    assert "par aaya" in row["reason"]


def test_hook_pass_still_refuses_to_say_the_hook_will_catch_on():
    row = sl.test_hook(CLEAN, SPEC_EXACT)
    assert row["status"] == lab.TESTED_PASS
    assert row["measured"]["times"] == 3
    assert row["measured"]["position"] == 0.0
    assert "\"hook pakdega\" ka nahi" in row["reason"]
    assert any("yaad reh jaayegi" in item for item in sl.CANNOT_MEASURE)


def test_nothing_read_and_read_but_no_number_are_two_different_data_missing():
    # Dono me test chal nahi paaya, par WAJAH bilkul alag hai — aur yahi farq
    # study lane ko daant deta hai ("padha hi nahi" vs "padha par number nahi").
    nothing = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD, study=STUDY_NONE)
    read = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD,
                               study=STUDY_READ_NO_NUMBER)
    assert nothing["status"] == read["status"] == lab.DATA_MISSING
    assert "koi source padhi hi nahi gayi" in nothing["reason"]
    assert "source padhi gayi par usme koi asli number" in read["reason"]
    assert nothing["reason"] != read["reason"]
    assert read["measured"]["sources_read"] == 3


def test_convention_test_never_invents_a_number_and_carries_the_source_id():
    row = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD, study=STUDY_STANZA_4)
    assert row["status"] == lab.TESTED_PASS
    assert [record["source_id"] for record in row["measured"]["conventions"]] \
        == ["src-1"]
    assert "SOURCE-REPORTED" in row["reason"]


def test_stanza_convention_needs_every_stanza_not_just_one():
    # Yahi wo jagah hai jahan songlab craft se JAAN-BOOJH KAR sakht hai.
    assert sl.STRICTER_THAN_STYLE_FIT is True
    row = sl.test_conventions(CLEAN, SPEC_EXACT, study=STUDY_STANZA_4)
    assert row["status"] == lab.TESTED_FAIL
    assert row["measured"]["stanza_line_counts"] == [8]
    assert row["measured"]["conventions"][0]["bar"] == "saare band"
    assert "[src-1]" in row["reason"]

    good = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD, study=STUDY_STANZA_4)
    assert good["measured"]["stanza_line_counts"] == [4, 4]
    assert good["status"] == lab.TESTED_PASS


def test_songlab_does_not_replace_crafts_own_style_check():
    # "Naya sakht test aa gaya, purana hata do" — yahi feature-loss hota hai.
    assert sl.REPLACES_STYLE_FIT_CHECK is False
    assert sl.policy()["replaces_style_fit_check"] is False
    # Craft/songcraft ka apna check aaj bhi maujood hai.
    assert "style_fit_structure" in _src("songcraft.py")


def test_hook_convention_is_a_floor_not_an_exact_match():
    # Hook ki ginti par sakht/naram ka sawaal hi nahi — padha hua number FLOOR
    # hai. 2 baar chahiye tha, 2 aaya → pass; 9 chahiye tha → fail.
    ok = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD, study=STUDY_HOOK_2)
    assert ok["status"] == lab.TESTED_PASS
    assert ok["measured"]["conventions"][0]["bar"] == ">= padha hua number"
    bad = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD, study=STUDY_HOOK_9)
    assert bad["status"] == lab.TESTED_FAIL
    assert "hook 9 baar chahiye tha, 2 baar aaya" in bad["reason"]


def test_an_unknown_kind_of_number_is_not_quietly_called_a_pass():
    row = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD,
                              study=STUDY_UNKNOWN_KIND)
    assert row["status"] == lab.DATA_MISSING
    assert "kism samajh nahi aaya" in row["reason"]


def test_convention_test_reads_the_shape_that_songcraft_really_produces():
    # Haath se bane guidance par bharosa karna aadha kaam hai — asli
    # `songcraft.guidance_from` ka shape bhi isi test se hokar jaana chahiye,
    # warna do jagah do shape ban jaate.
    real = songcraft.guidance_from([_Src("s1", REAL_CONVENTION_TEXT)])
    assert real["guidance_source_count"] == 1
    assert real["numeric_conventions"]
    for record in real["numeric_conventions"]:
        assert record["source_id"] == "s1"
        assert isinstance(record["value"], int)
    # Wrapped ({"guidance": ...}) aur seedha — dono chalne chahiye.
    wrapped = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD,
                                  study={"guidance": real})
    direct = sl.test_conventions(APPLIED_DRAFT, SPEC_SAD, study=real)
    assert wrapped["status"] == direct["status"]
    assert wrapped["status"] in (lab.TESTED_PASS, lab.TESTED_FAIL)


# ══════════════════════════════════════════════════════════════════════════════
# 4. POORA LAB — gating, kram, aur dobara-likhwane ki note
# ══════════════════════════════════════════════════════════════════════════════
def test_song_lab_does_not_run_on_a_poem_or_without_a_spec_or_draft():
    for draft, spec, needle in ((CLEAN, SPEC_POEM, "gaane ki nahi"),
                                (CLEAN, None, "spec hi nahi bani"),
                                ("   ", SPEC_EXACT, "draft hi nahi mila")):
        report = sl.run_song_lab(draft, spec)
        assert report["ran"] is False
        assert report["status"] == lab.NOT_RUN
        assert needle in report["reason"]
        assert report["tests"] == [] and report["line_rows"] == []


# Ek hi draft me dono haalat: line 5 niyam tod rahi hai (par THEEK 8 line maangi
# thi, isliye hataai nahi ja sakti) aur line 8 sirf kamzor hai (FIX).
MIXED_DRAFT = CLEAN.replace("door kahin ek diya jal raha", APPEAL_LINE).replace(
    "ye kahani mere saath reh gayi", CLICHE_LINE)


def test_not_run_report_still_carries_the_policy_and_the_limits():
    # "Chala nahi" ka matlab "sach chhupa lo" nahi hai.
    report = sl.not_run("koi wajah")
    assert report["status_reason"]
    assert report["reason"] == "koi wajah"
    assert report["policy"]["gemini_calls"] == 0
    assert list(report["limits"]) == list(sl.limits())
    assert report["cannot_measure"] == list(sl.CANNOT_MEASURE)
    assert report["disclaimer"] == sl.LAB_DISCLAIMER
    assert sum(report["counts"].values()) == 0
    # Bina naap ka prompt/heading nahi chhapta.
    assert sl.prompt_block(report) == ""
    assert sl.section_lines(report) == ["SONG LAB chala nahi: koi wajah"]


def test_the_four_tests_run_on_the_draft_that_will_be_delivered():
    # Agar test HATAANE SE PEHLE wale draft par chalte, to "test pass" wala
    # draft aur "diya gaya" draft do alag cheez hote — yahi sabse chupa hua
    # jhooth hai.
    report = sl.run_song_lab(APPLIED_DRAFT, SPEC_SAD)
    assert report["tested_draft"] == "after_drop"
    assert report["draft_changed"] is True
    assert APPEAL_LINE in report["draft_in"]
    assert APPEAL_LINE not in report["draft_out"]
    structure = [row for row in report["tests"]
                 if row["test"] == sl.TEST_STRUCTURE][0]
    # 8 line andar gayi thin, 1 hataayi — test ne 7 hi gini.
    assert structure["measured"]["lines"] == 7


def test_every_report_counts_exactly_four_tests():
    for draft, spec in ((CLEAN, SPEC_EXACT), (APPLIED_DRAFT, SPEC_SAD),
                        (THIN_MOOD, SPEC_EXACT), (MIXED_DRAFT, SPEC_EXACT)):
        report = sl.run_song_lab(draft, spec)
        assert len(report["tests"]) == 4
        assert sum(report["counts"].values()) == 4
        assert [row["test"] for row in report["tests"]] == list(sl.TEST_NAMES)


def test_one_fail_beats_everything_and_the_order_comes_from_lab():
    # Do jagah do tarah ka rollup = do sach. Kram lab se hi udhaar hona chahiye.
    assert sl._LAB_ROLLUP_ORDER is lab._ROLLUP_ORDER
    assert sl.rollup([{"status": lab.TESTED_PASS},
                      {"status": lab.TESTED_FAIL}]) == lab.TESTED_FAIL
    assert sl.rollup([{"status": lab.TESTED_PASS},
                      {"status": lab.DATA_MISSING}]) == lab.TESTED_PASS
    assert sl.rollup([{"status": lab.DATA_MISSING},
                      {"status": lab.NOT_TESTABLE_HERE}]) == lab.DATA_MISSING
    assert sl.rollup([]) == lab.NOT_RUN


def test_a_failing_test_and_a_refused_drop_both_reach_the_redraft_notes():
    report = sl.run_song_lab(MIXED_DRAFT, SPEC_EXACT)
    notes = report["redraft_notes"]
    assert len(notes) == 2
    # Kamzor line ka sudhaar.
    assert notes[0].startswith("Line 8 theek karo")
    assert "ghisa-pita" in notes[0]
    # Aur wo line jo niyam tod rahi thi par hataai nahi ja saki — poori wajah
    # ke saath, taaki "chupke se ignore" mumkin na rahe.
    assert notes[1].startswith("Line 5 niyam tod rahi hai par hatai nahi")
    assert sl.REFUSE_REASON[sl.DROP_REFUSED_EXACT_COUNT] in notes[1]
    assert APPEAL_LINE in notes[1]


def test_a_dropped_line_never_comes_back_through_the_notes():
    report = sl.run_song_lab(APPLIED_DRAFT, SPEC_SAD)
    assert report["drop"]["dropped"]
    assert report["redraft_notes"] == []
    block = sl.prompt_block(report)
    assert APPEAL_LINE not in block
    assert "Hataayi gayi line waapas mat likho" in block


def test_a_failed_test_is_named_in_the_notes_with_its_measured_reason():
    report = sl.run_song_lab(THIN_MOOD, SPEC_EXACT)
    notes = report["redraft_notes"]
    assert any(sl.TEST_STRUCTURE in note for note in notes)
    assert any(sl.TEST_HOOK in note for note in notes)
    assert any("1/3 antare me dikha" in note for note in notes)
    # DATA_MISSING wala test note me nahi aata — wo shikayat nahi hai.
    assert not any(sl.TEST_CONVENTION in note for note in notes)


def test_the_same_draft_measured_twice_gives_the_same_report():
    assert sl.DETERMINISTIC is True
    assert sl.RANDOMNESS_USED is False
    assert sl.run_song_lab(MIXED_DRAFT, SPEC_EXACT) == \
        sl.run_song_lab(MIXED_DRAFT, SPEC_EXACT)


# ══════════════════════════════════════════════════════════════════════════════
# 5. IMAANDAARI — ₹0, koi dhun nahi, aur seema likhi hui
# ══════════════════════════════════════════════════════════════════════════════
def test_this_stage_makes_no_tune_spends_nothing_and_hears_nothing():
    for flag in (sl.AUDIO_GENERATED, sl.TUNE_MADE, sl.HEARD, sl.SUNG,
                 sl.LISTENER_TESTED, sl.HUMAN_REACTION_TESTED,
                 sl.NETWORK_USED, sl.RANDOMNESS_USED,
                 sl.MODEL_WRITTEN_CODE_EXECUTED):
        assert flag is False
    assert sl.GEMINI_CALLS == 0
    assert sl.PROVIDER_COST == "₹0"
    # Ye do jhande ULTE hain — True rehna zaroori hai.
    assert sl.TESTED_PASS_IS_NOT_QUALITY is True
    assert sl.EVERY_DROP_HAS_A_MEASURED_REASON is True
    # Is file me koi model/network ka naam hi nahi hona chahiye.
    src = _src("songlab.py")
    for banned in ("requests", "httpx", "urllib", "random.", "genai",
                   "gemini_reasoning"):
        assert banned not in src


def test_the_policy_says_all_of_it_in_one_place():
    policy = sl.policy()
    assert policy["stage"] == "song_lab"
    assert policy["gemini_calls"] == 0 and policy["deterministic"] is True
    assert policy["provider_cost"] == "₹0"
    assert policy["tested_pass_is_not_quality"] is True
    assert policy["refrain_never_dropped"] is sl.REFRAIN_NEVER_DROPPED
    assert policy["max_drop_share"] == sl.MAX_DROP_SHARE
    assert policy["max_drops"] == sl.MAX_DROPS
    assert policy["min_lines_after_drop"] == sl.MIN_LINES_AFTER_DROP
    assert policy["tests"] == list(sl.TEST_NAMES)
    assert policy["measured_by"] == "offline_rules_in_songlab_py"


def test_what_cannot_be_measured_is_written_down_not_left_out():
    assert len(sl.CANNOT_MEASURE) >= 4
    joined = " | ".join(sl.CANNOT_MEASURE)
    assert "hit hoga" in joined
    assert "sun kar kaisa lagega" in joined
    # "Hataane se gaana BEHTAR hua" — yahi wo daawa hai jo sabse aasaani se
    # nikal jaata; isliye ye saaf mana likha hona chahiye.
    assert any("behtar" in item for item in sl.CANNOT_MEASURE)


def test_the_audit_limits_name_every_soft_spot_of_this_stage():
    text = " | ".join(sl.limits())
    assert sl.MAX_AUDIT_LIMIT_LINES == len(sl.limits()) >= 8
    assert "AUDIO_GENERATED = False" in text
    assert "HUMAN_REACTION_TESTED = False" in text
    # Kamzor line hataayi NAHI jaati — ye seema chhup jaaye to "saaf kar diya"
    # jaisa jhooth ban jaata hai.
    assert "HATAI NAHI JAATI" in text
    assert "list adhoori hai" in text
    assert "SOURCE-REPORTED" in text
    assert "DATA_MISSING hai, FAIL nahi" in text


def test_the_prompt_block_is_bounded_and_says_so_when_it_cuts():
    many = {"ran": True,
            "redraft_notes": ["note %d" % index for index in range(14)]}
    block = sl.prompt_block(many).splitlines()
    # heading + 10 note + overflow + aakhri hidayat
    assert len(block) == sl.MAX_PROMPT_NOTES + 3
    assert "- note 9" in block
    assert "- note 10" not in block
    assert any("aur 4 baatein" in line for line in block)


def test_no_complaint_does_not_become_a_compliment_in_the_prompt():
    block = sl.prompt_block({"ran": True, "redraft_notes": []})
    assert sl.EMPTY_PROMPT_LINE in block
    assert "NAHI hai" in sl.EMPTY_PROMPT_LINE
    assert sl.prompt_block({"ran": False, "redraft_notes": ["x"]}) == ""
    assert sl.prompt_block(None) == ""


def test_the_audit_record_carries_numbers_not_the_song_itself():
    report = sl.run_song_lab(MIXED_DRAFT, SPEC_EXACT)
    record = sl.public_record(report)
    flat = repr(record)
    # Gaane ka text audit record me nahi jaana chahiye (wo jawab me hai).
    assert HOOK not in flat
    assert APPEAL_LINE not in flat
    assert record["tests_run"] == 4
    assert record["test_names"] == list(sl.TEST_NAMES)
    assert record["drops_refused"] == 1
    assert record["lines_dropped"] == 0
    assert record["quality_proven"] is False
    assert record["heard"] is False and record["audio_generated"] is False
    assert record["gemini_calls"] == 0 and record["provider_cost"] == "₹0"


def test_the_audit_record_of_a_stage_that_never_ran_says_not_run():
    record = sl.public_record(None)
    assert record["ran"] is False
    assert record["status"] == lab.NOT_RUN
    assert record["tests_run"] == 0 and record["test_names"] == []


def test_the_printed_block_shows_each_test_with_its_own_method_and_reason():
    report = sl.run_song_lab(MIXED_DRAFT, SPEC_EXACT)
    lines = sl.section_lines(report)
    text = "\n".join(lines)
    for name in sl.TEST_NAMES:
        assert name in text
        assert sl.TEST_METHOD[name] in text
    assert "3 pass" in text and "1 data hi nahi" in text
    assert "1 sudhaarni hain" in text
    # Refused line ka hisaab bhi chhapta hai — chupaana mumkin nahi.
    assert "hatai NAHI gayi" in text
    # Aur aakhir me wahi sach: koi dhun nahi bani.
    assert "koi dhun nahi bani" in lines[-1]


def test_a_real_drop_prints_the_count_before_and_after():
    report = sl.run_song_lab(APPLIED_DRAFT, SPEC_SAD)
    text = "\n".join(sl.section_lines(report))
    assert "Line 4 hataayi" in text
    assert "naap dobara chalayi gayi aur wo giri nahi" in text
    assert str(report["drop"]["before_counts"]) in text
    assert str(report["drop"]["after_counts"]) in text


def test_the_answer_block_stays_empty_until_the_lab_really_ran():
    # Bina naap ka heading chhapna khud ek jhooth hai.
    assert sl.songlab_section(None) == ""
    assert sl.songlab_section({}) == ""
    assert sl.songlab_section({"song_lab": sl.not_run("x")}) == ""
    assert sl.songlab_limits({"song_lab": sl.not_run("x")}) == []
    assert sl.songlab_limits(None) == []


def test_the_answer_block_and_the_audit_come_from_one_craft_report():
    report = sl.run_song_lab(APPLIED_DRAFT, SPEC_SAD)
    craft_report = {"song_lab": report}
    assert sl.report_of(craft_report) is report
    assert sl.report_of({"song_lab": "not a dict"}) == {}
    text = sl.songlab_section(craft_report)
    assert text.startswith(sl.SONG_LAB_SUBHEADING)
    assert sl.SONG_LAB_KEY == "song_lab"
    assert sl.songlab_limits(craft_report) == list(sl.limits())


# ══════════════════════════════════════════════════════════════════════════════
# 6. WIRING — file me likha hona hi kaafi nahi, judi honi chahiye
# ══════════════════════════════════════════════════════════════════════════════
def test_craft_imports_songlab_inside_the_function_to_break_the_cycle():
    src = _src("craft.py")
    where = src.index("def _songlab_module(")
    body = src[where:src.index("def _song_lab_pass(")]
    # Top-level import cycle bana deta (songlab khud craft ko import karta hai),
    # isliye import function ke ANDAR hona chahiye.
    assert "from . import songlab as _songlab" in body
    assert "from . import songlab" not in src[:where]
    # Aur import fail hone par chup nahi rehna — wajah naam se likhni hai.
    assert '"song_lab_module_import_failed"' in src


def test_song_lab_runs_before_the_one_bounded_revision_call():
    # Baad me chalta to uski line-level note us call me jaa hi nahi paati —
    # ya doosri Gemini call lagti. Dono galat.
    src = _src("craft.py")
    run = src[src.index("def run_craft("):src.index("def apply_final_draft(")]
    lab_at = run.index("lab_report, draft, measured = _song_lab_pass(")
    prompt_at = run.index("prompt = revision_prompt_block(")
    call_at = run.index("new_text = str(reviser(prompt)")
    assert lab_at < prompt_at < call_at


def test_the_revision_prompt_carries_both_the_study_and_the_lab_notes():
    src = _src("craft.py")
    call = _brace_slice(src, "revision_prompt_block(spec, measured,")
    assert "guidance_blocks=guidance_blocks" in call
    assert "lab_notes=lab_notes" in call
    # Aur note wahin se aati hai jahan naapi gayi thi.
    assert 'lab_notes = [str(note) for note in (lab_report.get("redraft_notes")' \
        in src


def test_both_shapes_of_the_craft_report_carry_a_song_lab_key():
    src = _src("craft.py")
    # Stage chala hi nahi — phir bhi key maujood, warna padhne wala "naap nahi
    # hui" aur "stage nahi chala" me farq nahi kar paayega.
    assert '"song_lab": {"ran": False, "status": NOT_RUN,' in src
    assert '"reason": "craft_stage_not_run"' in src
    # Aur asli report me wahi lab_report jo FINAL draft ka hai.
    assert '"song_lab": lab_report,' in src
    empty = craft.run_craft("aaj mausam kaisa hai", "kuch bhi")
    assert empty["song_lab"]["ran"] is False


def test_the_orchestrator_takes_the_record_from_the_same_craft_report():
    # Doosra pass chalane se do alag draft ke do alag record ban jaate — isliye
    # source wahi ek craft report hai.
    src = _src("orchestrator.py")
    assert "from . import songlab" in src
    call = _brace_slice(src, "songlab.public_record(")
    assert "songlab.report_of(" in call
    assert 'passes.get("craft")' in call
    assert "songlab.run_song_lab(" not in src


def test_the_result_object_has_a_song_lab_field_that_defaults_to_empty():
    assert "song_lab: Dict = field(default_factory=dict)" in _src("models.py")
    result = ResearchResult(question="q", answer="a")
    assert result.song_lab == {}
    assert result.to_dict()["song_lab"] == {}
    filled = ResearchResult(question="q", answer="a",
                            song_lab={"ran": True, "status": lab.TESTED_PASS})
    assert filled.to_dict()["song_lab"]["status"] == lab.TESTED_PASS


def test_the_answer_prints_song_lab_right_after_craft_and_never_instead_of_it():
    src = _src("synthesizer_claude.py")
    assert "from .songlab import songlab_limits, songlab_section" in src
    craft_at = src.index("craft_text = craft_section(craft_report)")
    lab_at = src.index("songlab_text = songlab_section(craft_report)")
    assert craft_at < lab_at
    # craft ka block hataya nahi gaya — SONG LAB uske SAATH chalta hai.
    assert "parts.append(craft_text)" in src
    assert "parts.append(songlab_text)" in src


def test_the_audit_tail_never_silently_cuts_a_new_limit_line():
    # Haath se likhi ginti [:8] ho jaati to nayi seema-line chup-chaap kat
    # jaati. Isliye ginti songlab se hi aani chahiye.
    src = _src("synthesizer_claude.py")
    assert ("from .songlab import MAX_AUDIT_LIMIT_LINES as "
            "SONGLAB_MAX_AUDIT_LIMIT_LINES") in src
    call = _brace_slice(src, "songlab_limits(")
    assert "craft_report" in call
    tail = src[src.index("for songlab_line in songlab_limits("):]
    assert tail[:200].count("[:SONGLAB_MAX_AUDIT_LIMIT_LINES]") == 1
    assert sl.MAX_AUDIT_LIMIT_LINES == len(sl.limits())
