"""#190 — "poori kitab padh li" ka matlab "sabit ho gaya" nahi hota.

Naapi hui kharabi (fix se pehle): `claim_labels.line_verdict(...,
check_entailment=True)` — yaani wahi rasta jo orchestrator asli me chalata hai —
ek **bina-refereed kitab** ka metaphysical dawa `[ESTABLISHED]` rehne deta tha.
Wajah epistemic nahi, hosting ka ittefaaq thi: `relevance.score_quality` ke
`_TIER_3` host (jisme `archive.org` hai) ko 0.55 base milta hai, source ka
quality 0.530 ban jaata tha, aur `evidence_verification_legacy._quality_state`
ka darwaza 0.45 par khulta hai → A-E ke chaaron row True → ESTABLISHED.
Wahi kitab `example-press.com` par 0.430 par gir jaati thi.

Ye file dono taraf se pin karti hai: kharabi wapas na aaye, aur door itna chauda
na ho jaaye ki sansthagat page (CME/Fed — trading contract ki jaan) ya
peer-reviewed monograph bhi gir jaaye. Dawa kabhi HATAYA nahi jaata — sirf label
ESTABLISHED se SOURCE-REPORTED hota hai, citation waisi hi rehti hai.
"""
from __future__ import annotations

from research_engine.claim_labels import (ESTABLISHED, LABEL_RULE_PROMPT,
                                          REASON_STATEMENT_ONLY,
                                          SOURCE_REPORTED,
                                          STATEMENT_ONLY_KNOWN_LIMIT,
                                          STATEMENT_ONLY_TYPES, downgrade,
                                          human_note, line_verdict,
                                          merge_reports, proof_signal,
                                          statement_only_source)
from research_engine.evidence_verification_legacy import _quality_state
from research_engine.models import EvidencePack, SourceRecord, SourceType
from research_engine.relevance import RelevanceEngine

# Snippet ko itna lamba rakho ki depth/support check ka koi doosra bahana na bache.
_PAD = (" The passage is repeated at length and the argument is developed over "
        "several chapters with many examples and cross references to earlier "
        "sections of the same work.")

_CLAIM = "The astral body separates from the physical body in sleep"
_TERMS = ["astral", "body", "physical", "sleep", "gearbox", "tick", "size",
          "transition", "temperature"]


def _src(sid, *, title, url, snippet, stype, year=None, relevance=0.9,
         peer=None, doi="", methodology="", primary=None,
         level="full_text", quality=None) -> SourceRecord:
    """Quality asli engine se nikalti hai — apna number likhna jhooth hota.

    `quality=` sirf tab diya jaata hai jab test ka maqsad hi ek DIMENSION ko
    fail karana ho (A-E ki row-state naapne ke liye), aur wo test uska zikr
    apne docstring me karta hai.
    """
    source = SourceRecord(
        title=title, url=url, snippet=snippet + _PAD, source_type=stype,
        peer_reviewed=peer, read_level=level, relevance_score=relevance,
        doi=doi, methodology=methodology, is_primary=primary)
    source.source_id = sid
    if year:
        source.year = year
    if level == "full_text":
        source.full_text_chars = 6000
        source.full_text_available = True
    source.quality_score = (RelevanceEngine().score_quality(source)
                            if quality is None else float(quality))
    return source


def _pack(*sources: SourceRecord) -> EvidencePack:
    return EvidencePack(question="does the astral body separate during sleep",
                        sources=list(sources), topic_terms=_TERMS)


def _occult_book(sid="S1", *, year=1901,
                 url="https://archive.org/details/astralbody") -> SourceRecord:
    return _src(sid, title="The Astral Body and Other Astral Phenomena",
                url=url, snippet=_CLAIM + ".", stype=SourceType.BOOK, year=year)


def _peer_paper(sid="S3") -> SourceRecord:
    return _src(sid, title="Sleep physiology and body perception",
                url="https://www.nature.com/articles/s41586-024-00002",
                snippet=_CLAIM + ".", stype=SourceType.PAPER, year=2024,
                peer=True, doi="10.1038/s41586-024-00002")


def _line(*ids: str) -> str:
    cites = "".join(f"[{sid}]" for sid in ids)
    return f"[ESTABLISHED] {_CLAIM} {cites}."


# --------------------------------------------------------------------------
# 1. Kharabi khud (reproduce) — aur saboot ki wo kharabi asli me pahunch me thi
# --------------------------------------------------------------------------
def test_unrefereed_book_cannot_be_established_even_when_fully_read():
    book = _occult_book()
    verdict, why = line_verdict(_line("S1"), _pack(book), check_entailment=True)
    assert verdict == SOURCE_REPORTED, why
    assert REASON_STATEMENT_ONLY in why
    # Wajah user ko samajh aane wali bhasha me ho, sirf code na ho.
    assert "KATHAN" in why


def test_the_hole_was_reachable_quality_gate_would_have_passed_this_book():
    """Ye test upar wale test ko khokhla hone se bachata hai.

    Agar kal `score_quality` badal jaaye aur kitab ka quality 0.45 se neeche
    chala jaaye, to kitab kisi DOOSRI wajah se girne lagegi aur pehla test
    jhoothi tasalli dene lagega. Isliye wo asli hole yahan naapa hua hai.
    """
    book = _occult_book()
    assert book.quality_score >= 0.45, book.quality_score
    assert _quality_state(book) is True


def test_age_is_not_the_rule_a_2015_edition_falls_too():
    """Purane granth par shak, nayi kitab par bharosa — aisa niyam GALAT hota.

    Naapa hua sach: usi kitab ka 2015 edition quality 0.580 leta hai, yaani
    1901 se ZYADA. Isliye door refereeing ke signal par hai, saal par nahi.
    """
    modern = _occult_book("S1", year=2015,
                          url="https://archive.org/details/astral2015")
    assert modern.quality_score >= _occult_book().quality_score
    verdict, why = line_verdict(_line("S1"), _pack(modern),
                                check_entailment=True)
    assert verdict == SOURCE_REPORTED, why
    assert REASON_STATEMENT_ONLY in why


def test_recording_transcript_is_also_a_statement_not_a_proof():
    tape = _src("S4", title="Interview recording with a practitioner",
                url="https://archive.org/details/tape1",
                snippet=_CLAIM + ".", stype=SourceType.TRANSCRIPT, year=1975)
    verdict, why = line_verdict(_line("S4"), _pack(tape),
                                check_entailment=True)
    assert verdict == SOURCE_REPORTED, why
    assert REASON_STATEMENT_ONLY in why
    assert "transcript" in why


def test_door_shuts_on_the_default_path_too_not_only_strict_mode():
    """Ye source-eligibility ka niyam hai (patent jaisa), entailment ka nahi."""
    verdict, why = line_verdict(_line("S1"), _pack(_occult_book()),
                                check_entailment=False)
    assert verdict == SOURCE_REPORTED, why
    assert REASON_STATEMENT_ONLY in why


# --------------------------------------------------------------------------
# 2. Door ki chaudai — ye teen CASE GIRNE NAHI CHAHIYE
# --------------------------------------------------------------------------
def test_institutional_web_page_still_keeps_established():
    """CME/Fed/BIS jaisi sansthagat page `web` hoti hai — trading contract ki jaan."""
    cme = _src("S1", title="CME Group NQ contract specifications",
               url="https://www.cmegroup.com/markets/equities/nasdaq/nq.html",
               snippet=("The E-mini Nasdaq-100 futures contract has a tick size "
                        "of 0.25 index points worth 5.00 US dollars per tick."),
               stype=SourceType.WEB, year=2025, primary=True)
    line = "[ESTABLISHED] The tick size is 0.25 index points [S1]."
    verdict, why = line_verdict(line, _pack(cme), check_entailment=True)
    assert verdict == ESTABLISHED, why


def test_peer_reviewed_monograph_with_doi_still_keeps_established():
    """BOOK type hone par bhi refereeing ka signal ho to dawa strong reh sakta."""
    mono = _src("S1", title="Superconductivity in Layered Materials",
                url="https://link.springer.com/book/10.1007/978-3-030",
                snippet=("Measurements across 40 samples show the transition "
                         "temperature rises with applied pressure, p < 0.01."),
                stype=SourceType.BOOK, year=2021, peer=True,
                doi="10.1007/978-3-030", methodology="systematic_review")
    line = "[ESTABLISHED] The transition temperature rises with applied pressure [S1]."
    verdict, why = line_verdict(line, _pack(mono), check_entailment=True)
    assert verdict == ESTABLISHED, why


def test_ordinary_peer_reviewed_paper_control_keeps_established():
    verdict, why = line_verdict(_line("S3"), _pack(_peer_paper()),
                                check_entailment=True)
    assert verdict == ESTABLISHED, why


def test_statement_only_scope_is_type_limited_on_both_sides():
    """Sirf book/transcript par door lagta hai — baaki type par NAHI."""
    assert STATEMENT_ONLY_TYPES == ("book", "transcript")
    for stype in (SourceType.BOOK, SourceType.TRANSCRIPT):
        bare = _src("S9", title="t", url="https://archive.org/details/x",
                    snippet="claim.", stype=stype, year=1901)
        assert statement_only_source(bare) is True, stype
    for stype in (SourceType.WEB, SourceType.PAPER, SourceType.DOCUMENT,
                  SourceType.DATASET):
        other = _src("S9", title="t", url="https://example.org/x",
                     snippet="claim.", stype=stype, year=2020)
        assert statement_only_source(other) is False, stype


# --------------------------------------------------------------------------
# 3. Chhoot ke chaar naapne-layak signal — har ek apna NAAM deta hai
# --------------------------------------------------------------------------
def test_proof_signal_names_each_escape_route():
    base = dict(title="t", url="https://archive.org/details/x",
                snippet="claim.", stype=SourceType.BOOK, year=1901)
    assert proof_signal(_src("S1", peer=True, **base)) == "peer_reviewed"
    assert proof_signal(_src("S1", doi="10.1000/x", **base)) == "doi"
    signal = proof_signal(_src("S1", methodology="rct", **base))
    assert signal.startswith("methodology:") and "rct" in signal
    assert proof_signal(_src("S1", primary=True, **base)) == "primary_record"
    # Bina kisi signal wali kitab: koi naam nahi, isliye door lagta hai.
    assert proof_signal(_src("S1", **base)) == ""
    assert proof_signal(None) == ""


def test_weak_methodology_is_not_an_escape_route():
    """`opinion`/`narrative_review` asli study design nahi hain."""
    for weak in ("opinion", "narrative_review", "qualitative"):
        book = _src("S1", title="t", url="https://archive.org/details/x",
                    snippet=_CLAIM + ".", stype=SourceType.BOOK, year=1901,
                    methodology=weak)
        assert proof_signal(book) == "", weak
        verdict, why = line_verdict(_line("S1"), _pack(book),
                                    check_entailment=True)
        assert verdict == SOURCE_REPORTED, (weak, why)


def test_each_escape_signal_actually_restores_established():
    for kwargs in ({"peer": True}, {"doi": "10.1000/x"},
                   {"methodology": "cohort"}, {"primary": True}):
        book = _src("S1", title="Superconductivity in Layered Materials",
                    url="https://archive.org/details/x", snippet=_CLAIM + ".",
                    stype=SourceType.BOOK, year=1901, **kwargs)
        assert statement_only_source(book) is False, kwargs
        verdict, why = line_verdict(_line("S1"), _pack(book),
                                    check_entailment=True)
        assert verdict == ESTABLISHED, (kwargs, why)


# --------------------------------------------------------------------------
# 4. Mili-juli citation — kitab akeli line ko utha nahi sakti
# --------------------------------------------------------------------------
def test_mixed_citation_book_row_cannot_carry_the_line_alone():
    """A-E ka facade "koi ek row poori pass hui" par verified kehta hai.

    Isliye `[S1 kitab][S2 paper]` wali line kitab ki row se pass ho sakti thi,
    chahe paper is dawe se related hi na ho. Naya row-level guard ye band karta.
    """
    offtopic = _src("S2", title="Gearbox lubrication in wind turbines",
                    url="https://www.nature.com/articles/s41586-024-09999",
                    snippet="Gearbox lubricant viscosity falls with temperature.",
                    stype=SourceType.PAPER, year=2024, relevance=0.05,
                    peer=True, doi="10.1038/x")
    verdict, why = line_verdict(_line("S1", "S2"),
                                _pack(_occult_book(), offtopic),
                                check_entailment=True)
    assert verdict != ESTABLISHED, why
    assert REASON_STATEMENT_ONLY in why


def test_mixed_citation_with_a_real_supporting_paper_stays_established():
    """Door narrow hai: sahi paper saath ho to dawa strong hi rehta hai."""
    verdict, why = line_verdict(_line("S1", "S3"),
                                _pack(_occult_book(), _peer_paper()),
                                check_entailment=True)
    assert verdict == ESTABLISHED, why


def test_allowed_row_must_pass_all_four_dimensions_not_just_relevance():
    """Guard "koi ek dimension" par khush na ho — chaaron ek hi row par chahiye.

    Yahan paper on-topic hai (relevance/support/depth theek), par uski
    source-quality jaan-boojh kar low rakhi gayi hai (E dimension fail). Kitab
    ki row chaaron par True hai. Agar guard sirf relevance dekhta, to line
    ESTABLISHED reh jaati — yaani wahi purana chhed dobara khul jaata.
    """
    weak_paper = _src("S2", title="Sleep physiology and body perception",
                      url="https://example-journal.com/s2",
                      snippet=_CLAIM + ".", stype=SourceType.PAPER, year=2024,
                      quality=0.10)
    verdict, why = line_verdict(_line("S1", "S2"),
                                _pack(_occult_book(), weak_paper),
                                check_entailment=True)
    assert verdict != ESTABLISHED, why
    assert REASON_STATEMENT_ONLY in why


def test_patent_keeps_its_own_older_reason_code():
    """Patent ka darwaza purana hai — dono wajah alag dikhni chahiye."""
    patent = _src("S1", title="Method for astral separation",
                  url="https://patents.google.com/patent/US1234567",
                  snippet=_CLAIM + ".", stype=SourceType.PATENT, year=2001)
    assert patent.is_patent is True
    assert statement_only_source(patent) is False
    verdict, why = line_verdict(_line("S1"), _pack(patent),
                                check_entailment=True)
    assert verdict == SOURCE_REPORTED, why
    assert "LEGAL" in why
    assert REASON_STATEMENT_ONLY not in why


def test_patent_door_wins_over_statement_door_on_duck_typed_records():
    """Precedence ka pin — dono darwaze ke beech kram tay hona chahiye.

    Naapa hua sach: `models.SourceRecord.is_patent` khud `source_type ==
    PATENT` se banta hai, isliye ek asli SourceRecord kabhi ek waqt me patent
    AUR book nahi ho sakta. `statement_only_source` duck-typed record leta hai
    (sab kuch `getattr` se padha jaata hai), isliye precedence yahin naapi gayi
    hai — code me bhi likha hai ki wo line SourceRecord ke liye redundant hai.
    """
    class _Stub:
        is_patent = True
        source_type = "book"
        peer_reviewed = None
        doi = ""
        methodology_rank = -1
        is_primary = None

    assert statement_only_source(_Stub()) is False
    plain = _Stub()
    plain.is_patent = False
    assert statement_only_source(plain) is True


# --------------------------------------------------------------------------
# 5. Imaandaar ginti — kitab ki wajah se gira dawa "A-E fail" NAHI hai
# --------------------------------------------------------------------------
def test_downgrade_counts_statement_only_separately_from_ae_failure():
    text, report = downgrade(_line("S1"), _pack(_occult_book()),
                             check_entailment=True)
    assert report["downgraded"] == 1
    assert report["to_source_reported"] == 1
    assert report["statement_only"] == 1
    # Kitab wale rasta me A-E verifier tak baat hi nahi pahunchti, isliye
    # use "A-E chala aur fail hua" likhna jhooth hota.
    assert report["a_e_checked"] == 0
    assert report["a_e_failed"] == 0
    assert "kathan" in report["note"]
    assert "[SOURCE-REPORTED]" in text


def test_mixed_citation_case_does_count_as_a_real_ae_failure():
    """Wahan A-E asli me chali thi (paper ka full text tha), isliye ginti sahi."""
    offtopic = _src("S2", title="Gearbox lubrication in wind turbines",
                    url="https://www.nature.com/articles/s41586-024-09999",
                    snippet="Gearbox lubricant viscosity falls with temperature.",
                    stype=SourceType.PAPER, year=2024, relevance=0.05,
                    peer=True, doi="10.1038/x")
    _, report = downgrade(_line("S1", "S2"),
                          _pack(_occult_book(), offtopic),
                          check_entailment=True)
    assert report["a_e_checked"] == 1
    assert report["a_e_failed"] == 1
    assert report["statement_only"] == 1


def test_merge_reports_carries_statement_only_from_both_passes():
    _, depth = downgrade(_line("S1"), _pack(_occult_book()),
                         check_entailment=True)
    merged = merge_reports({"checked": 1, "to_unverified": 0,
                            "statement_only": 2, "details": [], "note": ""},
                           depth)
    assert merged["statement_only"] == 3


def test_human_note_says_it_in_normal_language():
    _, report = downgrade(_line("S1"), _pack(_occult_book()),
                          check_entailment=True)
    note = human_note(report)
    assert "bina-refereed kitab" in note
    assert "KATHAN" in note
    assert "hataya nahi" in note


def test_human_note_stays_quiet_when_no_book_was_involved():
    _, report = downgrade(_line("S3"), _pack(_peer_paper()),
                          check_entailment=True)
    assert report["statement_only"] == 0
    assert "bina-refereed kitab" not in human_note(report)


# --------------------------------------------------------------------------
# 6. Kuch chhupta ya girta nahi — sirf label badalta hai
# --------------------------------------------------------------------------
def test_claim_text_and_citation_survive_the_downgrade():
    line = _line("S1")
    text, _ = downgrade(line, _pack(_occult_book()), check_entailment=True)
    assert _CLAIM in text
    assert "[S1]" in text
    assert "[ESTABLISHED]" not in text
    # Sirf label ka hissa badla — baaki line bit-identical.
    assert text.replace("[SOURCE-REPORTED]", "[ESTABLISHED]") == line


def test_repeat_runs_are_deterministic():
    pack = _pack(_occult_book(), _peer_paper())
    body = "\n".join([_line("S1"), _line("S3")])
    first = downgrade(body, pack, check_entailment=True)
    second = downgrade(body, pack, check_entailment=True)
    assert first[0] == second[0]
    assert first[1]["statement_only"] == second[1]["statement_only"] == 1
    # Do line, ek giri ek bachi — mixed answer par door select hi hota hai.
    assert first[1]["downgraded"] == 1


# --------------------------------------------------------------------------
# 7. Seema likhi hui ho, chhupi na ho
# --------------------------------------------------------------------------
def test_known_limit_is_written_down_and_names_the_untouched_types():
    limit = STATEMENT_ONLY_KNOWN_LIMIT
    assert limit.strip()
    assert "web" in limit
    # Har chhoote hue type ka naam likha ho — "kuch type" likh dena kaafi nahi.
    for untouched in ("document", "dataset", "encyclopedia", "paper"):
        assert untouched in limit, untouched
    assert "peer_reviewed" in limit and "is_primary" in limit
    assert "DOI" in limit and "methodology_rank" in limit
    # Point 3: koi keyword/content list nahi banayi gayi.
    assert "list NAHI" in limit or "list nahi" in limit
    # Point 4: dawa hataya nahi jaata — sirf label badalta hai.
    assert "HATTA nahi" in limit or "hataya nahi" in limit
    assert "SOURCE-REPORTED" in limit


def test_reason_code_literal_is_stable_and_distinct_from_the_patent_reason():
    """Constant ka NAAM assert karna kaafi nahi tha — value bhi pin karo.

    Warna koi bhi `REASON_STATEMENT_ONLY = "no_full_text"` kar de aur audit me
    kitab wali wajah purani depth-wali wajah se mil jaaye, par test green rahe.
    """
    assert REASON_STATEMENT_ONLY == "book_statement_not_experimental_proof"
    _, why = line_verdict(_line("S1"), _pack(_occult_book()),
                          check_entailment=True)
    assert "book_statement_not_experimental_proof" in why


def test_label_rule_prompt_teaches_the_book_rule_to_the_model():
    assert "KITAB" in LABEL_RULE_PROMPT
    assert "KATHAN" in LABEL_RULE_PROMPT
    assert "SOURCE-REPORTED" in LABEL_RULE_PROMPT
