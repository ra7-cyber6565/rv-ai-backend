"""#155 — MAANGA HUA DELIVERABLE: gayab na ho, jhooth na bole, lane na mile.

Ye file ek hi live run se nikli hai (intel, 2026-08-30). Usne cinematic Punjabi
gaana maanga tha. CRAFT ne gaana banaya bhi aur naapa bhi, par uske baad
evidence-first boundary ne poora answer surface DOBARA banaya — aur us rebuild
me gaana kahin nahi tha. User ko "Seedha jawab" ki jagah ek cover-song CNN paper
ki line dikhi. Saath me teen aur jhooth chhap gaye: (a) "Second-order effects
chain (intro → verse 1 → chorus …) → nahi mili" — ek aisi cheez ki KAMI, jo
maangi hi nahi gayi thi; (b) `EVIDENCE NONE` ke saath "40 sources use hue"; aur
(c) LAB ne "shrota ka GSR 20% badhega" par TESTED_PASS de diya — evidence me
padi kisi aur cheez ke "41%" ko utha kar.

Isliye is file me chaar alag sach pin hote hain:

  #155b  Ban chuka deliverable jawab me DIKHE — apne alag `[CREATIVE-
         DELIVERABLE]` label ke saath, aur guard KHUD kuch na likhe. `MISSING`
         ka matlab "bana hi nahi" hai, "mila nahi" nahi.
  #155c  Lane isolation: BANANE ki farmaish ke bina gaane/media ki lane khule
         hi na, aur arrow (`a → b`) wala dhaancha "second-order effects" ki
         demand na samjha jaaye — par asli research sawaal ka bartaav 1 bit bhi
         na badle.
  #155d  State imaandaar rahe: "jawab COMPLETE" + "maangi hui cheez MISSING"
         ek saath ho to wo CONFLICT hai, aur do ginti (kachche source vs seedhe
         kaam ke source) ka farak ek line me likha ho.
  #155e  LAB gaane ko test kare, INSAAN ko nahi: jis hypothesis ka naap asli
         insaan/body-signal par hota hai, uska test BANTA HI NAHI — aur ye
         "hypothesis kamzor thi" nahi, "yahan naapi nahi ja sakti" hai.

Sabse important negative: non-craft farmaish (trading model, physics) par ye
poora batch answer ko CHHOOTA HI NAHI — text byte-identical laut jaata hai.
0 Gemini call, 0 network, koi randomness nahi.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import craft  # noqa: E402
from research_engine import deliverable_guard as dg  # noqa: E402
from research_engine import lab  # noqa: E402
from research_engine import media_study  # noqa: E402
from research_engine import rejects  # noqa: E402
from research_engine import requested  # noqa: E402
from research_engine import research_state as rs  # noqa: E402
from research_engine import songcraft  # noqa: E402
from research_engine.models import ResearchResult  # noqa: E402
from research_engine.orchestrator import DeepResearchEngine  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    """Wiring ka static naap — kram aur gate ASLI file me hain ya nahi.

    Poora orchestrator is sandbox me chal nahi sakta (network/Gemini/fastapi),
    isliye kram wahi file padh kar naapa jaata hai jisme likha hai. Ye
    "import ho gaya" jaisa khaali test nahi hai: index compare hote hain.
    """
    with open(os.path.join(_ROOT, name), encoding="utf-8") as handle:
        return handle.read()


# ── nakli answer + nakli craft report ────────────────────────────────────────
ANSWER = ("## Seedha jawab\n\nfoo bar baaz\n\n## Established Knowledge\n\n"
          "x\n\n## Audit\n\nold\n\n## Sources\n\n- a\n")
SONG = "[Intro]\nraat bhar sadkon pe chala\ntere shehar ki batti buji\n"


def craft_report(**kw):
    """CRAFT ka report jaisa `run_craft()` deta hai (test padhne me aasaan)."""
    base = {"ran": True, "status": "DRAFT_MEASURED_OK", "form": "SONG",
            "final_draft": SONG, "spec": {"form": "SONG", "label": "gaana"}}
    base.update(kw)
    return base


def guarded(answer=ANSWER, **kw):
    """`(answer, audit, public)` — teeno ek hi run se, taaki mel na toote."""
    record = dg.capture(craft_report(**kw))
    text, audit = dg.ensure(answer, record)
    return text, audit, dg.public_record(audit)


# ══ #155b — ban chuka deliverable jawab me dikhe ═════════════════════════════
def test_non_craft_ask_answer_byte_identical_aur_wahi_object():
    """Lane isolation ka sabse bada taala: trading maango to text na chhue."""
    text, audit = dg.ensure(ANSWER, dg.not_asked("trading model maanga tha"))
    assert text is ANSWER               # naya string bhi nahi bana
    assert audit["state"] == dg.NOT_ASKED
    assert audit["answer_changed"] is False
    assert audit["asked"] is False
    assert dg.warnings(audit) == []     # bina farmaish koi warning nahi


def test_capture_craft_chala_hi_nahi_to_not_asked():
    assert dg.capture({"ran": False, "reason": "farmaish nahi thi"})["asked"] \
        is False
    assert dg.capture(None)["asked"] is False
    assert dg.capture({})["asked"] is False
    # form hi na ho to bhi guard kuch maan kar nahi chalta
    assert dg.capture({"ran": True, "final_draft": SONG})["asked"] is False


def test_capture_naap_craft_ke_report_se_aati_hai_khud_nahi_ginta():
    record = dg.capture(craft_report())
    assert record["asked"] is True
    assert record["form"] == "SONG"
    assert record["label"] == "gaana"
    assert record["craft_status"] == "DRAFT_MEASURED_OK"
    assert record["draft_lines"] == 3          # khaali line nahi ginti
    assert record["draft"] == SONG


def test_gayab_gaana_wapas_lagta_hai_aur_label_alag_hota_hai():
    text, audit, _ = guarded()
    assert audit["state"] == dg.RESTORED
    assert audit["restored"] is True
    assert audit["answer_changed"] is True
    assert "raat bhar sadkon pe chala" in text
    assert dg.LABEL in text                    # [CREATIVE-DELIVERABLE]
    assert dg.NOT_EVIDENCE_LINE in text


def test_creative_label_kisi_claim_label_ki_tarah_nahi_ginta():
    """`[CREATIVE-DELIVERABLE]` claim-label table me nahi hai — ginti na badhe."""
    from research_engine import models
    table = getattr(models, "_LABEL_TO_CLAIM", {})
    inside = dg.LABEL.strip("[]").upper()
    assert inside not in {str(k).upper() for k in table}
    for banned in dg.BANNED_IN_BLOCK:
        assert banned.upper() != dg.LABEL.upper()


def test_gaana_seedhe_jawab_ke_baad_lagta_hai_sources_aakhir_me_rehte_hain():
    """Jagah bhi naapi jaati hai: gaana upar mile, `## Sources` aakhir me rahe."""
    text, audit, _ = guarded()
    assert audit["insert_position"] == "established_knowledge"
    i_direct = text.index("## Seedha jawab")
    i_song = text.index("raat bhar sadkon pe chala")
    i_est = text.index("## Established Knowledge")
    assert i_direct < i_song < i_est
    assert text.rstrip().endswith("- a")          # Sources abhi bhi aakhir me
    assert text.count(dg.DISPLAY_HEADING) == 1    # ek hi baar, dobara nahi


def test_pehle_se_maujood_gaana_dobara_nahi_chipkta():
    """Sabse gandi bug: same gaana do baar. Poora draft mile to haath na lage."""
    already = ANSWER.replace("foo bar baaz", SONG)
    text, audit = dg.ensure(already, dg.capture(craft_report()))
    assert text is already
    assert audit["state"] == dg.PRESENT
    assert audit["already_present"] is True
    assert audit["answer_changed"] is False
    assert audit["present_ratio"] == 1.0
    assert dg.warnings(audit) == []               # sab theek to chup raho


def test_thoda_badla_hua_gaana_bhi_maujood_ginta_hai():
    """Label/annotate pass line ke aage-peeche marker jodta hai — 80% kaafi."""
    five = "l1 alfa\nl2 beta\nl3 gama\nl4 delta\nl5 epsilon\n"
    rec = dg.capture(craft_report(final_draft=five))
    four = ANSWER.replace("foo bar baaz",
                          "l1 alfa\nl2 beta\nl3 gama\nl4 delta\nkuch aur")
    assert dg.present_ratio(four, rec) == 0.8
    text, audit = dg.ensure(four, rec)
    assert audit["state"] == dg.PRESENT and text is four
    # 60% par guard use naya maanta hai (chhat asli constant se naapi)
    three = ANSWER.replace("foo bar baaz", "l1 alfa\nl2 beta\nl3 gama")
    assert dg.present_ratio(three, rec) < dg._PRESENT_MIN_RATIO
    assert dg.ensure(three, rec)[1]["state"] == dg.RESTORED


def test_guard_dobara_chale_to_apna_section_pehchan_leta_hai():
    rec = dg.capture(craft_report())
    once, _ = dg.ensure(ANSWER, rec)
    twice, audit = dg.ensure(once, rec)
    assert twice is once                          # doosri baar kuch nahi badla
    assert audit["state"] == dg.PRESENT
    assert once.count(dg.HEADING) == 1
    # Aur wahi baat MISSING par bhi: draft khaali ho to guard ne sirf WAJAH likhi
    # thi, koi draft-line nahi — isliye "pehle se maujood" ka line-match yahan
    # kaam nahi kar sakta. Dobara chalne par doosra "bana hi nahi" block chipak
    # jaata to user ko do baar wahi bura khabar milti. Pehchan HEADING se hoti hai.
    empty = dg.capture(craft_report(final_draft="", status=craft.NO_DRAFT))
    first, first_audit = dg.ensure(ANSWER, empty)
    again, again_audit = dg.ensure(first, empty)
    assert first_audit["state"] == dg.MISSING
    assert again is first                         # dobara ek akshar nahi juda
    assert again_audit["state"] == dg.PRESENT
    assert first.count(dg.HEADING) == 1
    assert first.count("bana hi nahi") == 1


def test_bana_hi_nahi_to_guard_khud_kuch_nahi_likhta():
    """`MISSING` = "bana hi nahi", "mila nahi" nahi — aur banawat bilkul nahi."""
    text, audit, _ = guarded(final_draft="", status=craft.NO_DRAFT)
    assert audit["state"] == dg.MISSING
    assert audit["restored"] is False
    assert audit["answer_changed"] is True        # wajah likhi gayi
    assert audit["reason"] == dg._WHY_BY_STATUS[craft.NO_DRAFT]
    assert "bana hi nahi" in text
    assert "raat bhar sadkon pe chala" not in text
    assert dg.GUARD_WROTE_DELIVERABLE is False
    assert audit["guard_wrote_deliverable"] is False
    # research ka hissa jaisa tha waisa hi
    assert "## Established Knowledge" in text and "## Sources" in text
    assert dg.warnings(audit)[0].count(dg._WHY_BY_STATUS[craft.NO_DRAFT]) == 1


def test_har_craft_status_ki_apni_naapi_hui_wajah_hoti_hai():
    """Andaza nahi: anjaan status par bhi status ka naam likha jaata hai."""
    # keys CRAFT ke asli constants se aati hain, haath se likhi string se nahi
    assert set(dg._WHY_BY_STATUS) == {craft.NO_DRAFT, craft.NOT_RUN,
                                      craft.DRAFT_UNMEASURED, craft.DRAFT_WEAK,
                                      craft.DRAFT_OK}
    for status, why in dg._WHY_BY_STATUS.items():
        assert dg.why_missing({"craft_status": status}) == why
    assert dg.why_missing({"craft_status": "KUCH_NAYA"}) == "CRAFT status: KUCH_NAYA"
    assert dg.why_missing({"reason": "budget khatam"}) == "budget khatam"
    assert dg.why_missing({}) == "CRAFT ne koi status hi nahi diya"
    assert dg.why_missing(None)


def test_sirf_hash_wali_draft_bhi_missing_hai_khaali_section_nahi():
    """`#####` jaisa kachra draft: section khaali, isliye MISSING — chup nahi."""
    text, audit, _ = guarded(final_draft="#####\n",
                             status=craft.DRAFT_UNMEASURED)
    assert audit["state"] == dg.MISSING
    assert audit["reason"] == "draft me naapne laayak koi line nahi bachi"
    assert dg.build_section({"draft": "#####\n"})[0] == ""
    assert "#####" not in text


def test_evidence_label_wala_deliverable_jawab_me_nahi_lagta():
    """Fail-closed: label bacha reh gaya to section joda hi nahi jaata."""
    spec = {"form": "SONG", "label": "[VERIFIED] gaana"}
    text, audit, public = guarded(spec=spec)
    assert audit["state"] == dg.BLOCKED
    assert audit["blocked_token"] == "[VERIFIED]"
    assert text is ANSWER                         # research hissa chhua bhi nahi
    assert audit["answer_changed"] is False
    assert audit["restored"] is False
    assert "fail-closed" in audit["note"]
    assert any("fail-closed" in w for w in public["warnings"])


def test_draft_ke_andar_ka_label_de_fang_hota_hai_gaana_phenka_nahi_jaata():
    """Bracket badalta hai, likhawat bachti hai — aur ginti audit me jaati hai."""
    draft = "## [Intro]\n[SOURCE-REPORTED] raat bhar chala\nteri gali\n"
    text, audit, public = guarded(final_draft=draft)
    assert audit["state"] == dg.RESTORED
    assert audit["evidence_labels_neutralised"] == 1
    assert audit["heading_chars_neutralised"] == 1
    assert "(SOURCE-REPORTED) raat bhar chala" in text
    assert "[SOURCE-REPORTED]" not in text
    assert "raat bhar chala" in text              # likhawat hataayi nahi
    assert "## [Intro]" not in text               # naya section nahi bana
    assert "[Intro]" in text
    assert any("bracket badal diya" in w for w in public["warnings"])
    assert any("hataayi nahi" in w for w in public["warnings"])


def test_public_record_me_gaana_ka_text_kabhi_nahi_jaata():
    """UI/API ko naap milti hai, draft nahi — aur sach constants se aata hai."""
    _, audit, public = guarded()
    assert "draft" not in public and "final_draft" not in public
    assert "raat bhar sadkon pe chala" not in str(public)
    assert public["state"] == dg.RESTORED
    assert public["state_vocabulary"] == list(dg.STATES)
    assert public["gemini_calls"] == 0 and public["network_used"] is False
    assert public["is_evidence"] is False and public["counts_as_claim"] is False
    assert public["quality_proven"] is False
    assert public["schema_version"] == dg.SCHEMA_VERSION
    assert len(public["limits"]) == dg.MAX_AUDIT_LIMIT_LINES == len(dg.limits())
    assert public["limits"] == dg.limits()        # ek bhi seema nahi kati


def test_audit_ka_dhaancha_paanchon_haalat_me_ek_jaisa_rehta_hai():
    """Key gayab hona bhi jhooth hai — UI ko har run me wahi dhaancha mile."""
    runs = [dg.ensure(ANSWER, dg.not_asked())[1],
            guarded()[1],
            guarded(final_draft="")[1],
            guarded(spec={"form": "SONG", "label": "[FACT] geet"})[1],
            dg.ensure(ANSWER.replace("foo bar baaz", SONG),
                      dg.capture(craft_report()))[1]]
    assert {a["state"] for a in runs} == set(dg.STATES)
    base = set(dg._audit().keys())
    for a in runs:
        assert set(a.keys()) == base
        assert a["schema_version"] == dg.SCHEMA_VERSION


# ══ #155c — lane isolation: gaane ki lane trading me na khule ════════════════
SONG_ASK = ("hindi me ek sad gaana likho: intro -> verse 1 -> chorus -> "
            "verse 2 -> outro")
TRADE_ASK = ("US100 aur XAUUSD ke liye 15M-5M-1M scalping model banao, "
             "walk-forward aur monte carlo ke saath")
SCIENCE_ASK = ("second-order effects batao: mehngai -> byaaj -> nivesh, "
               "poori chain ke saath")


def test_craft_ka_taala_ek_hi_jagah_se_aata_hai():
    """Do jagah do shart likhna hi #155c ki asli wajah thi — ek hi darwaza."""
    asked = DeepResearchEngine._craft_asked
    assert asked(SONG_ASK) is True
    assert asked(TRADE_ASK) is False
    assert asked(SCIENCE_ASK) is False
    assert asked("") is False
    assert asked(None) is False                   # shak me lane BAND
    # taala craft.detect ka wahi faisla hai, apni alag copy nahi
    for q in (SONG_ASK, TRADE_ASK, SCIENCE_ASK):
        assert asked(q) is bool(craft.detect(q).get("is_request"))


def test_trading_sawaal_par_gaane_ki_lane_khulti_hi_nahi():
    """Model maango to gaane/media ka kaam "chal raha" dikhna hi nahi chahiye."""
    song = DeepResearchEngine._songcraft_study(TRADE_ASK, None)
    assert song["ran"] is False and song["wanted"] is False
    assert song["prompt_block"] == "" and song["queries"] == []
    assert song["guidance_source_count"] == 0
    assert "farmaish nahi thi" in song["note"]

    media = DeepResearchEngine._media_study(TRADE_ASK, None)
    assert media["ran"] is False and media["wanted"] is False
    assert not media["discovered"] and media["lines"] == []
    assert media_study.media_section(media) == ""
    assert media_study.media_limits(media) == []


def test_gaane_ki_farmaish_par_wahi_lane_khulti_hai():
    """Gate additive hai: craft ask par purana rasta jinda rehta hai.

    Farak `wanted` key se naapa jaata hai — gate band hone par `not_asked()`
    ka record aata hai (jisme `wanted` hota hai), khulne par asli study ka
    record aata hai (jisme wo key hi nahi hoti).
    """
    song = DeepResearchEngine._songcraft_study(SONG_ASK, None)
    assert song["ran"] is True
    assert song.get("wanted") is not False
    media = DeepResearchEngine._media_study(SONG_ASK, None)
    assert "wanted" not in media           # gate se nahi, asli study se aaya


def test_gaane_ka_dhaancha_second_order_ki_demand_nahi_ginta():
    """Live run ka jhooth: "intro → verse → chorus" ko chain-demand samajh liya.

    Nateeja ye tha ki jawab me ek AISI cheez ki KAMI chhapi jo maangi hi nahi
    gayi thi. Ab wo arrow-dhaancha darj hota hai (chup-chaap nahi girta), par
    demand nahi banta.
    """
    req = requested.parse_requests(SONG_ASK)
    assert req["wants_second_order"] is False
    assert req["chain_steps"] == []
    rows = [r for r in req["suppressed"] if r["key"] == "second_order"]
    assert len(rows) == 1
    assert rows[0]["arrow_steps"] == ["intro", "verse 1", "chorus",
                                      "verse 2", "outro"]
    assert "second-order" in rows[0]["reason"].lower()   # wajah naapi hui hai
    # aur us kaami ka koi zikr jawab/prompt me nahi jaata
    ledger = requested.build_ledger(req)
    assert ledger["unmet"] == [] and ledger["lines"] == []
    assert "second-order" not in requested.prompt_block(req).lower()


def test_asli_research_sawaal_ka_bartaav_1_bit_bhi_nahi_badla():
    """Sabse important negative: chain ki asli farmaish waisi hi chalti hai."""
    req = requested.parse_requests(SCIENCE_ASK)
    assert req["wants_second_order"] is True
    assert req["chain_steps"] == ["mehngai", "byaaj", "nivesh"]
    assert req["suppressed"] == []                      # kuch daba nahi
    ledger = requested.build_ledger(req)
    assert [u["what"] for u in ledger["unmet"]] == \
        ["Second-order effects chain (mehngai → byaaj → nivesh)"]
    assert "second-order" in requested.prompt_block(req).lower()


def test_creative_brief_toot_jaaye_to_research_ka_rasta_khula_rehta_hai():
    """Fail-open: shak me research ka purana bartaav, band nahi."""
    assert requested.creative_brief(SONG_ASK) is True
    assert requested.creative_brief(SCIENCE_ASK) is False
    assert requested.creative_brief("") is False
    assert requested.creative_brief(None) is False


# ══ #155d — state imaandaar: "COMPLETE + gaana gayab" = CONFLICT ═════════════
_LEDGER = {"answer_complete": True}
_ANSWER_MIN = "## Seedha jawab\n\nfoo\n\n## Sources\n\n- a\n"


def state_of(deliverable, **kw):
    """Ek COMPLETE + strong-evidence run, sirf deliverable ka hissa badalta hai."""
    args = dict(ledger=_LEDGER, answer_text=_ANSWER_MIN, source_count=40,
                finished=True, verification_ran=True, supported_claims=6,
                unsupported_claims=0, counter_search=True,
                deliverable=deliverable)
    args.update(kw)
    return rs.build_state(**args)


def test_jawab_complete_par_gaana_gayab_hona_conflict_hai():
    """Pichhla live run bhara-bhara dikha tha jabki gaana gir gaya tha."""
    for state in (dg.MISSING, dg.BLOCKED):
        st = state_of({"state": state, "asked": True, "label": "gaana",
                       "reason": "wajah-x"})
        assert st.answer_state == "COMPLETE"      # state chup-chaap badli nahi
        assert len(st.conflicts) == 1
        assert rs.deliverable_token(state) in st.conflicts[0]
        assert "wajah-x" in st.conflicts[0]
        assert st.verified_allowed is False       # conflict ka asar naapa gaya


def test_deliverable_ban_gaya_to_koi_conflict_nahi_banta():
    """Ulta jhooth bhi mana hai: bana hua deliverable shak paida na kare."""
    for state in (dg.RESTORED, dg.PRESENT):
        st = state_of({"state": state, "asked": True, "label": "gaana"})
        assert st.conflicts == []
        assert st.verified_allowed is True
    # bina farmaish to row hi nahi chhapti
    st = state_of({"state": dg.NOT_ASKED, "asked": False})
    assert st.conflicts == [] and st.verified_allowed is True
    assert rs.deliverable_line({"state": dg.NOT_ASKED, "asked": False}) == ""
    assert rs.deliverable_line(None) == "" and rs.deliverable_line({}) == ""


def test_deliverable_row_chaar_haalat_se_alag_dikhta_hai():
    """"Bana kar de diya" ≠ "evidence mazboot" — dono ek table me na mile."""
    st = state_of({"state": dg.MISSING, "asked": True, "label": "gaana",
                   "reason": "wajah-x"})
    block = rs.render_state_block(st)
    assert rs.STATE_HEADING in block
    assert rs.DELIVERABLE_ROW_TITLE in block
    assert rs.DELIVERABLE_RULE_LINE in block
    # deliverable ka hissa chaar-haalat ki list ke BAAD aata hai
    assert block.index(rs.STATE_HEADING) < block.index(rs.DELIVERABLE_ROW_TITLE)
    assert "**MISSING**" in block and "wajah-x" in block


def test_do_ginti_ka_farak_ek_line_me_likha_hota_hai():
    """`EVIDENCE NONE` ke saath "40 sources use hue" — wahi live jhooth."""
    st = state_of({"state": dg.RESTORED, "asked": True, "label": "gaana"},
                  raw_source_count=40, directly_relevant_count=3)
    assert st.counts == {"raw_sources": 40, "directly_relevant_sources": 3}
    note = rs.count_note(st.counts)
    assert note.startswith(rs.COUNT_NOTE_TITLE)
    assert "40" in note and "3" in note
    assert note in rs.render_state_block(st)
    # adhoori ginti par ye line banti hi nahi (aadha sach bhi jhooth hai)
    assert rs.count_note(None) == "" and rs.count_note({}) == ""
    assert rs.count_note({"raw_sources": 40}) == ""
    assert rs.count_note(state_of({}).counts) == ""


def test_deliverable_token_guard_ke_asli_constants_se_bandha_hai():
    """`DELIVERABLE_` prefix guard ke naam se aata hai, haath se nahi."""
    for state in dg.STATES:
        assert state.startswith(rs.DELIVERABLE_PREFIX)
        token = rs.deliverable_token(state)
        assert token == state[len(rs.DELIVERABLE_PREFIX):]
        assert rs.undelivered(state) is (token in rs.UNDELIVERED_STATES)
    assert set(rs.UNDELIVERED_STATES) == {rs.deliverable_token(dg.MISSING),
                                          rs.deliverable_token(dg.BLOCKED)}
    assert rs.deliverable_token(None) == "" and rs.deliverable_token("") == ""
    assert rs.deliverable_token("  deliverable_missing ") == "MISSING"
    assert rs.undelivered("MISSING") is True      # prefix ke bina bhi chalta hai
    assert rs.undelivered("KUCH_NAYA") is False


def test_state_ka_round_trip_deliverable_aur_ginti_nahi_khota():
    """UI JSON se wapas aane par row/ginti gayab ho jaana bhi chup jhooth hai."""
    st = state_of({"state": dg.MISSING, "asked": True, "label": "gaana",
                   "reason": "wajah-x"},
                  raw_source_count=40, directly_relevant_count=3)
    back = rs.coerce(st.to_dict())
    assert back.deliverable == st.deliverable
    assert back.counts == st.counts
    assert back.conflicts == st.conflicts
    assert rs.render_state_block(back) == rs.render_state_block(st)


# ══ #155e — LAB gaane ko test kare, INSAAN ko nahi ═══════════════════════════
class _Src:
    def __init__(self, sid, text):
        self.source_id = sid
        self.title = self.snippet = self.full_text = text


class _Pack:
    def __init__(self, rows):
        self.sources = rows


# Evidence me ek moti ginti — purana rasta isi "41%" ko utha kar "20% se zyada"
# wale daawe par TESTED_PASS de deta tha (asli live run me yahi hua).
_PACK = _Pack([_Src("S1", "In this study the measured value was 41% overall, "
                          "with 320 K reported in table 2.")])
_HUMAN = {
    "hypothesis_id": "RV-HYP-1",
    "statement": "Is gaane ka chorus sunne walon ka GSR 20% se zyada badha dega.",
    "reasoning": "Sad songs par skin conductance badhta hai.",
    "experiment": "30 volunteers par listening test karke GSR naapo.",
    "falsification_test": "Agar GSR na badhe to daawa galat.",
    "is_testable": True, "has_prediction": True,
}
_CRAFTABLE = {
    "hypothesis_id": "RV-HYP-2",
    "statement": "Draft ke 20% se zyada lines me thos jagah ka naam aayega.",
    "reasoning": "Concreteness = 6/24 lines, yaani 25%.",
    "experiment": "Draft ki lines gin kar naapo.",
    "falsification_test": "20% se kam nikle to daawa galat.",
    "is_testable": True, "has_prediction": True,
}


def test_insaan_par_naapne_wala_daawa_reject_nahi_alag_channel_hai():
    """"Hataaya gaya" aur "yahan naapa nahi ja sakta" do alag baat hain."""
    code = rejects.HUMAN_SUBJECT_ON_CRAFT_ASK
    assert len(rejects.REJECT_CODES) == 6         # reject-ginti nahi badhi
    assert code not in rejects.REJECT_CODES
    assert code not in rejects.BLOCKING_CODES
    assert code in rejects.UNMEASURED_CODES
    assert lab.HUMAN_SUBJECT_ON_CRAFT == code     # ek hi string, do jagah nahi


def test_craft_ask_ke_bina_lab_ka_purana_rasta_bilkul_wahi_hai():
    assert lab.LabPolicy().craft_ask is False
    assert lab.LabPolicy().to_dict()["craft_ask"] is False
    assert lab.plan_specs(_HUMAN, _PACK, lab.LabPolicy(), "gaana likho") != []


def test_gaane_ki_farmaish_par_insaan_wale_daawe_ka_test_banta_hi_nahi():
    """Darwaza dhaanche ka hai: spec hi nahi banti, PASS/FAIL ka sawaal hi nahi."""
    shut = lab.LabPolicy(craft_ask=True)
    assert lab.plan_specs(_HUMAN, _PACK, shut, "gaana likho") == []
    # doosri (draft par naapi ja sakne wali) hypothesis par darwaza khula hai
    assert lab.plan_specs(_CRAFTABLE, _PACK, shut, "gaana likho") != []


def test_rukne_ki_wajah_asli_shabd_ke_saath_darj_hoti_hai():
    phrase = lab.human_subject_phrase(_HUMAN)
    haystack = (_HUMAN["statement"] + _HUMAN["reasoning"]
                + _HUMAN["experiment"]).lower()
    assert phrase and phrase.lower() in haystack   # shabd asli text se aaya
    assert lab.human_subject_phrase(_CRAFTABLE) == ""
    assert lab.human_subject_phrase(None) == "" and lab.human_subject_phrase({}) == ""

    run = lab.run_lab("mujhe sad hindi gaana likh do", [_HUMAN, _CRAFTABLE],
                      pack=_PACK, craft_ask=True)
    block = {b["hypothesis_id"]: b for b in run["hypotheses"]}["RV-HYP-1"]
    assert block["verdict"] == lab.NOT_TESTABLE_HERE
    assert block["verdict_reason"] == rejects.HUMAN_SUBJECT_ON_CRAFT_ASK
    assert block["human_subject_phrase"] == phrase
    assert block["needs_human_subjects"] is True
    assert block["tests"] == []                    # koi test chala hi nahi
    assert "galat sabit nahi" in block["detail"]
    assert "TESTED_PASS" not in str(block) and "TESTED_FAIL" not in str(block)
    assert run["counts"][lab.NOT_TESTABLE_HERE] == 1
    assert run["policy"]["craft_ask"] is True
    assert run["gemini_calls"] == 0 and run["provider_cost"] == 0
    # SONG LAB ka rasta batana zaroori hai — warna "kar hi nahi sakte" lagta hai
    assert "SONG LAB" in block["detail"]
    # aur draft par naapi ja sakne wali hypothesis par test asli me chala
    other = {b["hypothesis_id"]: b for b in run["hypotheses"]}["RV-HYP-2"]
    assert other["tests"] != []


def test_wahi_hypothesis_science_run_par_purane_rasta_se_jaati_hai():
    """Sabse important negative: science/trading run ek akshar nahi badalta."""
    run = lab.run_lab("GSR aur skin conductance par kya evidence hai",
                      [_HUMAN, _CRAFTABLE], pack=_PACK)
    block = {b["hypothesis_id"]: b for b in run["hypotheses"]}["RV-HYP-1"]
    assert block["verdict_reason"] != rejects.HUMAN_SUBJECT_ON_CRAFT_ASK
    assert block["tests"] != []
    assert "needs_human_subjects" not in block
    assert "human_subject_phrase" not in block
    assert run["policy"]["craft_ask"] is False
    assert not [l for l in lab.lab_limits(run) if "ASLI INSAAN" in l]


def test_ledger_me_unmeasured_alag_list_hai_reject_nahi():
    run = lab.run_lab("mujhe sad hindi gaana likh do", [_HUMAN, _CRAFTABLE],
                      pack=_PACK, craft_ask=True)
    merged = lab.merge_into_hypotheses([_HUMAN, _CRAFTABLE], run)
    ledger = rejects.build_ledger(merged)
    code = rejects.HUMAN_SUBJECT_ON_CRAFT_ASK
    assert code not in [r["reason_code"] for r in ledger["rejected"]]
    assert code not in ledger["counts"]            # reject-ginti jhoothi na ho
    assert len(ledger["unmeasured"]) == 1
    row = ledger["unmeasured"][0]
    assert row["hypothesis_id"] == "RV-HYP-1"
    assert row["measured"]["rukne_wala_shabd"] == lab.human_subject_phrase(_HUMAN)
    assert row["rejected"] is False and row["is_disproved"] is False
    assert row["removed_from_answer"] is False
    assert row["reopen_if"].strip()                # wapas kab — khaali nahi
    assert "RV-HYP-1" in [k.get("hypothesis_id") for k in ledger["kept"]]
    marked = rejects.apply_to_hypotheses(merged, ledger)
    mark = {m["hypothesis_id"]: m for m in marked}["RV-HYP-1"]
    assert mark["rejected"] is False and mark["reject_reason_code"] == ""


def test_unmeasured_section_ka_dhaancha_aur_khaali_par_chuppi():
    run = lab.run_lab("mujhe sad hindi gaana likh do", [_HUMAN, _CRAFTABLE],
                      pack=_PACK, craft_ask=True)
    ledger = rejects.build_ledger(lab.merge_into_hypotheses(
        [_HUMAN, _CRAFTABLE], run))
    section = rejects.unmeasured_section(ledger)
    # `###` — `##` hota to answer_order me ek phantom top-level section aa jaata
    assert section.startswith("### ") and "\n## " not in section
    assert lab.human_subject_phrase(_HUMAN) in section
    assert "hataayi NAHI" in section and "Wapas kab" in section
    assert rejects.unmeasured_section(None) == ""
    assert rejects.unmeasured_section({}) == ""
    # bina craft wale run me key maujood par khaali (gayab hona bhi jhooth hai)
    sci = lab.run_lab("GSR par kya evidence hai", [_HUMAN], pack=_PACK)
    assert rejects.build_ledger(
        lab.merge_into_hypotheses([_HUMAN], sci))["unmeasured"] == []


def test_audit_ki_seema_line_naapi_hui_hai_aur_kat_nahi_sakti():
    """Nayi seema-line list me AAKHIR me judti hai — chhat asli ginti se aati hai."""
    body = _src("research_engine/lab.py").split("def lab_limits(", 1)[1] \
        .split("\n    return limits", 1)[0]
    appends = len([ln for ln in body.split("\n")
                   if ln.strip().startswith("limits.append(")])
    assert lab.MAX_AUDIT_LIMIT_LINES == appends
    run = lab.run_lab("mujhe sad hindi gaana likh do", [_HUMAN, _CRAFTABLE],
                      pack=_PACK, craft_ask=True)
    limits = lab.lab_limits(run)
    assert len(limits) <= lab.MAX_AUDIT_LIMIT_LINES
    human = [ln for ln in limits if "ASLI INSAAN" in ln]
    assert len(human) == 1
    assert lab.human_subject_phrase(_HUMAN) in human[0]
    assert "kamzor thi" in human[0]                # "hataayi" se farq saaf


# ══ wiring — kram aur gate ASLI file me hain ya nahi ═════════════════════════
def test_guard_answer_ke_rebuild_ke_baad_aur_state_block_se_pehle_chalta_hai():
    """Kram hi is batch ka poora matlab hai: pehle chala to gaana phir kat jaata."""
    src = _src("research_engine/orchestrator.py")
    assert "from . import deliverable_guard" in src
    i_rebuild = src.index("# 6c-3.")
    i_ledger = src.index("answer = quality.inject_ledger_block(answer, c_ledger)")
    i_guard = src.index(
        "deliverable_record = deliverable_guard.capture(passes.get(\"craft\")")
    i_state = src.index("# 10c.")
    assert i_rebuild < i_ledger < i_guard < i_state
    assert "answer, deliverable_audit = deliverable_guard.ensure(" in src
    assert "deliverable_public = deliverable_guard.public_record(" in src
    assert "for line in deliverable_guard.warnings(deliverable_audit):" in src
    # ek hi baar — do jagah chalna hi "dobara chipak gaya" bug ki jad hai
    assert src.count("deliverable_guard.ensure(") == 1


def test_state_block_ko_guard_ka_record_aur_dono_ginti_jaati_hain():
    src = _src("research_engine/orchestrator.py")
    assert "raw_source_count=len(pack.sources)," in src
    assert ("directly_relevant_count=quality_ctx.get(\"directly_relevant_sources\"),"
            in src)
    assert src.count("deliverable=deliverable_public,") == 2   # state + result


def test_dono_craft_lane_ek_hi_taale_ke_peeche_hain():
    """#155c ki jad: alag-alag shart — isliye ab ek hi helper, do jagah."""
    src = _src("research_engine/orchestrator.py")
    assert src.count("if not DeepResearchEngine._craft_asked(question):") == 2
    assert "craft_ask=DeepResearchEngine._craft_asked(question))" in src
    assert src.count("def _craft_asked(") == 1


def test_synthesizer_me_unmeasured_block_reject_list_ke_baad_aata_hai():
    syn = _src("research_engine/synthesizer_claude.py")
    assert ("from .rejects import reject_limits, reject_section, "
            "unmeasured_section") in syn
    i_rej = syn.index("reject_text = reject_section(reject_report)")
    i_unm = syn.index("unmeasured_text = unmeasured_section(reject_report)")
    assert i_rej < i_unm
    assert syn.index("if unmeasured_text:") > i_unm       # khaali par chuppi
    assert syn.count("unmeasured_section(") == 1
    # chhat module se, hard-code `[:4]` se nahi (warna nayi line chup-chaap katti)
    assert ("from .lab import MAX_AUDIT_LIMIT_LINES as LAB_MAX_AUDIT_LIMIT_LINES"
            in syn)
    assert "lab_limits(lab_report)[:LAB_MAX_AUDIT_LIMIT_LINES]" in syn
    assert "lab_limits(lab_report)[:4]" not in syn


def test_result_object_me_deliverable_ka_apna_khaana_hai():
    """`ResearchResult` me jagah na ho to UI/API tak naap pahunch hi nahi sakti."""
    result = ResearchResult(question="q", answer="a")
    assert result.deliverable == {}
    assert isinstance(ResearchResult(question="q", answer="a",
                                     deliverable={"state": dg.RESTORED}
                                     ).deliverable, dict)
