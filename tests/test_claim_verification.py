"""
§13 / point 7 — paanch alag verification check (A–E) ka regression test.

Ye test us purane bug ko pakadta hai jahan "citation verified" ka matlab sirf
itna tha ki `[S3]` naam ka source pack mein maujood hai. Yahan har check ALAG
assert hota hai, aur khaas taur par ye:

    * junk source (WHO maternal mortality) cite karne se claim verified NAHI hota
    * poora text padha gaya ho par support na mile to bhi ESTABLISHED nahi rehta
    * jab source ka text hi na ho, to check C imaandaari se "unknown" bolta hai
      (jhootha fail bhi nahi) — aur wo baat report ke denominator mein dikhti hai
    * [HYPOTHESIS]/[SPECULATION] lines ki ginti verification mein nahi hoti

Offline: koi network, koi API key, koi pytest. `python3 tests/test_claim_verification.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research_engine import claim_labels as CL              # noqa: E402
from research_engine import claim_verification as CV        # noqa: E402
from research_engine.models import (EvidencePack, Passage,  # noqa: E402
                                    SourceRecord, SourceType)

PASSED = 0
FAILED = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}" + (f" — {extra}" if extra else ""))


def eq(name: str, got, want) -> None:
    check(name, got == want, f"mila {got!r}, chahiye {want!r}")


SC_TEXT = ("Electrical resistance measurements show a superconducting transition "
           "temperature of 250 K in lanthanum hydride LaH10 under a pressure of "
           "170 GPa. The transition was confirmed by magnetic susceptibility. ")
WHO_TEXT = ("The global maternal mortality ratio declined by 34 percent between "
            "2000 and 2020 according to WHO estimates for 185 countries. ")


def build_pack() -> EvidencePack:
    """
    Ek hi pack jismein har haalat maujood hai — taaki test ka fixture wahi ho
    jo live run mein hota hai (acha paper, sirf-abstract paper, junk WHO page,
    retracted paper, aur bina text wala metadata-only record).
    """
    full = SourceRecord(
        title="Superconductivity at 250 K in lanthanum hydride", url="http://s1",
        snippet=SC_TEXT * 3, source_type=SourceType.PAPER, connector="arxiv",
        read_level="full_text", full_text_chars=48000, peer_reviewed=True,
        quality_score=0.72, relevance_score=0.81, source_id="S1")
    abstract = SourceRecord(
        title="Hydride superconductors: a review", url="http://s2",
        snippet=SC_TEXT * 2, source_type=SourceType.PAPER, connector="openalex",
        read_level="abstract", quality_score=0.55, relevance_score=0.64,
        source_id="S2")
    junk = SourceRecord(
        title="Trends in maternal mortality 2000-2020", url="http://s3",
        snippet=WHO_TEXT * 3, source_type=SourceType.WEB, connector="who_gho",
        read_level="snippet", quality_score=0.12, relevance_score=0.04,
        rejected_reason="domain mismatch: health statistics, sawaal "
                        "superconductivity ka hai", source_id="S3")
    retracted = SourceRecord(
        title="Room-temperature superconductivity in a carbonaceous sulfur hydride",
        url="http://s4", snippet=SC_TEXT * 3, source_type=SourceType.PAPER,
        read_level="full_text", full_text_chars=30000, retracted=True,
        quality_score=0.60, relevance_score=0.70, source_id="S4")
    thin = SourceRecord(
        title="Conference abstract listing", url="http://s5", snippet="",
        source_type=SourceType.PAPER, connector="crossref",
        quality_score=0.40, relevance_score=0.35, source_id="S5")
    streamed = SourceRecord(
        title="Big handbook of condensed matter physics", url="http://s6",
        snippet=SC_TEXT * 4, source_type=SourceType.PAPER,
        read_level="full_text", full_text_chars=90000, quality_score=0.50,
        relevance_score=0.55, pages_read=12, pages_total=520,
        read_note="520 pages mein se 12 sabse milte-julte pages padhe gaye",
        source_id="S6")
    pack = EvidencePack(sources=[full, abstract, junk, retracted, thin, streamed])
    pack.passages = [Passage(source_id="S1", text=SC_TEXT * 3, locator="p.4"),
                     Passage(source_id="S6", text=SC_TEXT * 4, locator="p.311")]
    return pack


PACK = build_pack()

CLAIM_SC = ("Lanthanum hydride LaH10 shows a superconducting transition "
            "temperature of 250 K at a pressure of 170 GPa")


def rec(*ids):
    return [PACK.by_id(i) for i in ids]


# ── A: citation exists ───────────────────────────────────────────────────────
def test_a_citation_exists():
    print("\nA — citation maujood hai")
    a = CV.check_a([], [], "koi citation nahi wali line")
    eq("citation hi nahi → fail", a.status, CV.FAIL)
    check("wajah bhi likhi hai", "koi [S#] citation nahi" in a.detail, a.detail)

    a = CV.check_a(["S99"], [], f"[FACT] {CLAIM_SC} [S99]")
    eq("bana hua ID → fail", a.status, CV.FAIL)
    check("ID likhi thi par source nahi — yahi baat likhi hai",
          "pack mein nahi mile" in a.detail, a.detail)

    a = CV.check_a(["S1"], rec("S1"))
    eq("asli ID → pass", a.status, CV.PASS)
    check("A ka pass 'sach' ka dava nahi karta, sirf maujoodgi ka",
          "maujood hai" in a.detail, a.detail)

    a = CV.check_a(["S1", "S99"], rec("S1"))
    eq("ek sahi ek galat → pass par disclosure ke saath", a.status, CV.PASS)
    check("missing ID chhupaya nahi gaya", "S99" in a.detail, a.detail)


# ── B: source relevant ──────────────────────────────────────────────────────
def test_b_source_relevant():
    print("\nB — source sawaal se juda hai")
    b = CV.check_b(rec("S1"))
    eq("relevant source → pass", b.status, CV.PASS)

    b = CV.check_b(rec("S3"))
    eq("reject hua junk source → fail", b.status, CV.FAIL)
    check("reject ki asli wajah report hoti hai",
          "domain mismatch" in b.detail, b.detail)

    b = CV.check_b([])
    eq("source hi nahi → unknown (fail nahi)", b.status, CV.UNKNOWN)

    low = SourceRecord(title="kuch aur", relevance_score=0.10, source_id="SX")
    b = CV.check_b([low])
    eq("relevance floor se neeche → fail", b.status, CV.FAIL)
    check("floor ka number bhi dikhta hai", "0.25" in b.detail, b.detail)


# ── C: claim entailed (yahi "asli support" hai) ──────────────────────────────
def test_c_claim_entailed():
    print("\nC — claim us source ke text se support hota hai")
    c, best = CV.check_c(f"[ESTABLISHED FACT] {CLAIM_SC} [S1]", rec("S1"), PACK)
    eq("cited text claim kehta hai → pass", c.status, CV.PASS)
    eq("best source wapas aata hai", best, "S1")
    check("numbers ka milaan report hota hai", "number" in c.detail, c.detail)

    c, best = CV.check_c(f"[ESTABLISHED FACT] {CLAIM_SC} [S3]", rec("S3"), PACK)
    eq("junk source par claim → fail", c.status, CV.FAIL)
    eq("fail par koi best source nahi", best, "")

    # Yahi sabse zaroori honesty: text hi na ho to jhootha faisla mat lo.
    c, best = CV.check_c(f"[FACT] {CLAIM_SC} [S5]", rec("S5"), PACK)
    eq("source ka text hi nahi → unknown", c.status, CV.UNKNOWN)
    check("aur wajah saaf likhi hai",
          "text humare paas nahi hai" in c.detail, c.detail)

    c, _ = CV.check_c("[FACT] haan [S1]", rec("S1"), PACK)
    eq("claim itna chhota ki matlab na nikle → unknown", c.status, CV.UNKNOWN)

    c, _ = CV.check_c(f"[FACT] {CLAIM_SC} [S1]", [], PACK)
    eq("koi source hi nahi → unknown", c.status, CV.UNKNOWN)

    # numbers galat hon to claim ka dava kamzor pad jaata hai
    wrong = ("Lanthanum hydride shows a superconducting transition temperature "
             "of 999 K at a pressure of 3 GPa")
    c1, _ = CV.check_c(f"[FACT] {CLAIM_SC} [S1]", rec("S1"), PACK)
    c2, _ = CV.check_c(f"[FACT] {wrong} [S1]", rec("S1"), PACK)
    check("sahi numbers wala claim galat numbers se behtar score karta hai",
          c1.status == CV.PASS and "3/3" in c1.detail and "0/2" in c2.detail,
          f"{c1.detail} || {c2.detail}")

    # deterministic: do baar chalao, wahi jawab
    again, _ = CV.check_c(f"[FACT] {CLAIM_SC} [S1]", rec("S1"), PACK)
    eq("deterministic (dobara chalane par wahi)", again.detail, c1.detail)


# ── D: reading depth ────────────────────────────────────────────────────────
def test_d_reading_depth():
    print("\nD — padhne ki gehrai kaafi hai")
    d = CV.check_d(rec("S1"))
    eq("full text → pass", d.status, CV.PASS)

    d = CV.check_d(rec("S2"))
    eq("sirf abstract → unknown (jhootha pass nahi)", d.status, CV.UNKNOWN)
    check("matlab bhi likha hai", "source-reported" in d.detail, d.detail)

    d = CV.check_d(rec("S3"))
    eq("sirf snippet → fail", d.status, CV.FAIL)

    d = CV.check_d(rec("S5"))
    eq("metadata-only → fail", d.status, CV.FAIL)

    # §12 ki honesty: page-by-page padhi gayi badi file par "poora padha" ka
    # dava akela nahi jaana chahiye — read_note saath jaata hai.
    d = CV.check_d(rec("S6"))
    eq("page-by-page streamed file → pass", d.status, CV.PASS)
    check("par kitne pages padhe, wo bhi saath likha hai",
          "520 pages" in d.detail and "12" in d.detail, d.detail)

    d = CV.check_d([])
    eq("source nahi → unknown", d.status, CV.UNKNOWN)


# ── E: source quality ───────────────────────────────────────────────────────
def test_e_source_quality():
    print("\nE — source ki quality kaafi hai")
    e = CV.check_e(rec("S1"))
    eq("acha paper → pass", e.status, CV.PASS)

    e = CV.check_e(rec("S4"))
    eq("sirf retracted source cite hua → fail", e.status, CV.FAIL)
    check("retraction ka naam liya gaya", "retracted" in e.detail.lower(), e.detail)

    e = CV.check_e(rec("S1", "S4"))
    eq("ek acha + ek retracted → pass", e.status, CV.PASS)
    check("phir bhi retraction ka disclosure jaata hai",
          "retracted" in e.detail.lower(), e.detail)

    e = CV.check_e(rec("S3"))
    eq("bahut kamzor quality → fail", e.status, CV.FAIL)

    mid = SourceRecord(title="adhoora", quality_score=0.28, source_id="SY")
    e = CV.check_e([mid])
    eq("beech ka score → unknown (na pass na fail)", e.status, CV.UNKNOWN)

    e = CV.check_e([])
    eq("source nahi → unknown", e.status, CV.UNKNOWN)


# ── verdict = paanchon check ka nateeja ──────────────────────────────────────
def test_verdicts():
    print("\nverdict — paanch check milkar kya kehte hain")
    cc = CV.verify_claim(f"[ESTABLISHED FACT] {CLAIM_SC} [S1]", PACK)
    eq("full text + support → genuine_support", cc.verdict, CV.GENUINE_SUPPORT)
    check("aur .genuine sirf C par tikta hai", cc.genuine is True)
    eq("best source bhi mila", cc.best_source, "S1")

    cc = CV.verify_claim(f"[SOURCE-REPORTED] {CLAIM_SC} [S2]", PACK)
    eq("sirf abstract → source_reported", cc.verdict, CV.SOURCE_REPORTED)
    check("verdict ki wajah mein gehrai ki baat hai",
          "abstract" in cc.reason, cc.reason)

    cc = CV.verify_claim(f"[ESTABLISHED FACT] {CLAIM_SC} [S3]", PACK)
    eq("junk source cite karke bhi verified nahi", cc.verdict, CV.CITED_ONLY)
    check("A pass hone ke baad bhi verdict nahi bana",
          cc.status("A") == CV.PASS and cc.genuine is False)

    cc = CV.verify_claim(f"[FACT] {CLAIM_SC}", PACK)
    eq("citation hi nahi → unsupported", cc.verdict, CV.UNSUPPORTED)

    cc = CV.verify_claim(f"[FACT] {CLAIM_SC} [S99]", PACK)
    eq("bana hua ID → unsupported", cc.verdict, CV.UNSUPPORTED)

    cc = CV.verify_claim(f"[ESTABLISHED FACT] {CLAIM_SC} [S4]", PACK)
    eq("sirf retracted source → cited_only", cc.verdict, CV.CITED_ONLY)

    cc = CV.verify_claim(f"[FACT] {CLAIM_SC} [S5]", PACK)
    eq("text hi nahi tha → cited_only (verified nahi)", cc.verdict, CV.CITED_ONLY)
    eq("aur C unknown rehta hai (jhootha fail nahi)",
       cc.status("C"), CV.UNKNOWN)

    cc = CV.verify_claim(f"[ESTABLISHED FACT] {CLAIM_SC} [S1]", None)
    eq("pack ke bina koi claim verified nahi ho sakta",
       cc.verdict, CV.UNSUPPORTED)

    d = CV.verify_claim(f"[ESTABLISHED FACT] {CLAIM_SC} [S1]", PACK).to_dict()
    check("to_dict mein paanchon check aate hain", len(d["checks"]) == 5)
    check("aur verdict ka Hinglish label bhi",
          "support" in d["verdict_label"], d["verdict_label"])


ANSWER = f"""## Seedha jawab
Superconductivity ka matlab bijli ka bina rukawat behna hai, aur yahi baat
neeche detail mein hai.

- [ESTABLISHED FACT] {CLAIM_SC} [S1]
- [SOURCE-REPORTED] {CLAIM_SC} [S2]
- [ESTABLISHED FACT] Room temperature superconductivity at ambient pressure is confirmed in a copper based compound [S3]
- [EVIDENCE] {CLAIM_SC} [S5]
- [FACT] Superconducting cables se transmission loss lagbhag zero ho jaata hai
- [HYPOTHESIS] Hydrogen-rich lattice ki high phonon frequency hi zyada Tc deti hai [S1]
- [SPECULATION] Ambient pressure par ye kabhi mil sakta hai [S3]
"""


def test_answer_report():
    print("\nverify_answer — poore answer ka imaandaar denominator")
    rep = CV.verify_answer(ANSWER, PACK)
    eq("sirf fact/evidence family gini gayi (hypothesis/speculation nahi)",
       rep.total, 5)
    eq("ek claim par asli support mila", rep.genuine, 1)
    eq("ek sirf source-reported level par", rep.source_reported, 1)
    eq("do mein citation thi par support nahi", rep.cited_only, 2)
    eq("ek par koi valid source hi nahi", rep.unsupported, 1)
    eq("ek claim ka support check ho hi nahi saka (citation sahi thi, text nahi)",
       rep.unknown_entailment, 1)
    check("genuine ratio denominator ke saath aata hai",
          0 < rep.genuine_ratio < 1, rep.genuine_ratio)

    counts = rep.check_counts()
    check("A ka pass C ke pass se ZYADA hai — yahi purana bug tha",
          counts["A"][CV.PASS] > counts["C"][CV.PASS],
          f"A={counts['A']} C={counts['C']}")
    for key in ("A", "B", "C", "D", "E"):
        eq(f"{key} ke teeno counter ka jod total ke barabar",
           sum(counts[key].values()), rep.total)

    # Do overclaim: junk source par ESTABLISHED, aur bina source wala [FACT].
    eq("strong label wale dono jhoothe dave pakde gaye", len(rep.overclaims), 2)
    reasons = " | ".join(o.reason for o in rep.overclaims)
    check("junk source ki wajah likhi hai", "domain mismatch" in reasons, reasons)
    check("bina citation wale FACT ki wajah bhi likhi hai",
          "koi [S#] citation nahi" in reasons, reasons)


def test_note_and_block():
    print("\nnote()/block() — user ko dikhne wali bhasha")
    rep = CV.verify_answer(ANSWER, PACK)
    note = rep.note()
    check("note mein denominator hai", "5 labelled claim" in note, note)
    check("note batata hai kaunsa check ho hi nahi saka",
          "HO HI NAHI SAKA" in note, note)

    block = rep.block()
    for key in ("A", "B", "C", "D", "E"):
        check(f"block mein {key} ka apna line hai", f"**{key}**" in block)
    check("block saaf likhta hai ki sirf C asli support hai",
          "Sirf check **C**" in block, block[:200])
    check("overclaim ki chetavani block mein dikhti hai", "⚠️" in block)
    check("block mein raw status word (pass/fail) akela nahi chhoda",
          "check nahi ho saka" in block)

    empty = CV.verify_answer("bas ek normal line, koi label nahi hai yahan", PACK)
    eq("koi labelled claim nahi → total 0", empty.total, 0)
    check("aur note jhooth nahi bolta",
          "chala hi nahi" in empty.note(), empty.note())


def test_opt_in_label_gate():
    print("\nlabel gate — entailment ka opt-in taala")
    # S1 ka poora text padha gaya hai, isliye purana gate isse ESTABLISHED
    # rehne deta tha — chahe us text mein ye baat ho ya na ho.
    line = ("- [ESTABLISHED FACT] Superconducting cables se poore desh ki "
            "transmission loss zero ho gayi hai [S1]")
    check("junk-matching line par entailment gate lagta hai",
          CV.entailment_blocked(line, PACK) is True)
    check("asli support wali line par gate nahi lagta",
          CV.entailment_blocked(f"[ESTABLISHED FACT] {CLAIM_SC} [S1]", PACK) is False)
    check("jahan text hi nahi (S5), wahan gate chup rehta hai",
          CV.entailment_blocked(f"[ESTABLISHED FACT] {CLAIM_SC} [S5]", PACK) is False)
    check("pack ke bina gate kuch nahi kehta",
          CV.entailment_blocked(line, None) is False)

    plain, rep_off = CL.downgrade(line, PACK)
    check("default (opt-in off) purana behaviour rakhta hai",
          "[ESTABLISHED FACT]" in plain, plain)
    eq("aur kuch downgrade nahi hota", rep_off["downgraded"], 0)

    gated, rep_on = CL.downgrade(line, PACK, check_entailment=True)
    check("gate on karne par label neeche aata hai",
          "[SOURCE-REPORTED]" in gated and "[ESTABLISHED FACT]" not in gated, gated)
    eq("aur ye alag counter mein ginta hai", rep_on["entailment_blocked"], 1)
    check("note mein wajah insaani bhasha mein hai",
          "support nahi mila" in rep_on["note"], rep_on["note"])

    good = f"- [ESTABLISHED FACT] {CLAIM_SC} [S1]"
    kept, rep_good = CL.downgrade(good, PACK, check_entailment=True)
    check("sahi claim ka ESTABLISHED gate ke baad bhi bacha rehta hai",
          "[ESTABLISHED FACT]" in kept, kept)
    eq("us par koi downgrade nahi", rep_good["downgraded"], 0)


def test_report_block_in_answer():
    print("\nsynthesizer — A–E block report mein saaf chhapta hai")
    from research_engine.synthesizer import FinalSynthesizer

    rep = CV.verify_answer(ANSWER, PACK)
    text = FinalSynthesizer()._claim_check_block(rep.to_dict())
    check("block bana", bool(text.strip()))
    check("total claim ka number dikhta hai", "**5**" in text, text[:160])
    for key in ("A", "B", "C", "D", "E"):
        check(f"{key} ka line report mein hai", f"**{key}**" in text)
    check("'sirf C asli support hai' wali baat report mein bhi hai",
          "sirf **C**" in text, text[-400:])
    check("check-nahi-ho-saka wali baat chhupayi nahi gayi",
          "HO HI NAHI SAKA" in text, text)
    check("overclaim ki chetavani report mein hai", "⚠️" in text)
    check("koi raw jargon (entailment/proxy) user ko nahi dikhta",
          "entailment" not in text.lower() and "proxy" not in text.lower())

    eq("khaali report par section chhapti hi nahi",
       FinalSynthesizer()._claim_check_block({}), "")
    eq("None par bhi crash nahi",
       FinalSynthesizer()._claim_check_block(None), "")


def test_zero_cost_and_offline():
    print("\n₹0 + offline — koi network, koi API key")
    import inspect
    src = inspect.getsource(CV)
    for bad in ("requests.", "httpx", "urlopen", "genai", "openai", "api_key",
                "http://", "https://"):
        check(f"module mein '{bad}' nahi hai", bad not in src)
    check("sirf deterministic helpers use hote hain",
          "import random" not in src and "time.time" not in src)


def main() -> int:
    print("=" * 68)
    print("§13 — claim verification A–E")
    print("=" * 68)
    test_a_citation_exists()
    test_b_source_relevant()
    test_c_claim_entailed()
    test_d_reading_depth()
    test_e_source_quality()
    test_verdicts()
    test_answer_report()
    test_note_and_block()
    test_opt_in_label_gate()
    test_report_block_in_answer()
    test_zero_cost_and_offline()
    print("\n" + "=" * 68)
    print(f"{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())







