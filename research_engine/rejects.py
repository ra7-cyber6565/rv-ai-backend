"""#117 — Reject-list: kaunsi hypothesis hataayi gayi aur KYUN, naapi hui wajah ke saath.

Pehle kya hota tha (measured, 2026-08-26):
  * `HypothesisEngine.parse()` cap se zyada blocks CHUP-CHAAP phenk deta tha
    (`chunks[:cap]`) — user ko pata bhi nahi chalta ki model ne 4 bheji thi
    aur 3 hi chhapi.
  * jis block me `statement` nahi milta, wo bhi bina ek shabd ke gir jaata tha.
  * `honesty_check()` sirf WARNING deta tha — "adhoori hai" likh kar hypothesis
    delivered answer me poori izzat se chhapti rehti thi.
  * LAB (#116) ka `TESTED_FAIL` kahin bhi "isliye ise aage nahi badha rahe"
    nahi banta tha.

intel ki maang: "weak ko hatao — par kyu nikal rhe, kya strong proof h ki ye
kaam nhi krega". Isliye is module ka niyam:

  1. **Bina naap ke reject nahi.** Har reject record me `measured` dict hona
     ZAROORI hai. Jo drop naapa nahi ja saka use `unexplained_drop` kehte hain
     aur warning uthti hai — chup-chaap drop kabhi nahi.
  2. **Reject = "aage nahi badha rahe", DELETE nahi.** Hypothesis ka record
     rehta hai, uska text rehta hai, sirf uske saath wajah aur naap jud jaati
     hai. Kuch bhi mitaya nahi jaata.
  3. **Reject ka matlab "ye galat sabit ho gayi" NAHI hai.** `reopen_if` batata
     hai ki kis naap par ye wapas aa sakti hai.
  4. Zero Gemini call, zero network, ₹0 — sab kuch dicts padh kar.

Ye module Claude-owned hai. Banane wale: hypothesis.py (parse ke rejects),
lab.py (#116 ke verdict), orchestrator.py (ledger), synthesizer_claude.py
(answer me `###` block).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# ── stages ───────────────────────────────────────────────────────────────────
STAGE_PARSE = "parse"      # model ke text se hypothesis banate waqt hi gir gayi
STAGE_LAB = "lab"          # app ne khud test kiya aur fail hui (#116)
STAGE_QUALITY = "quality"  # deterministic quality check me nikli

STAGES = (STAGE_PARSE, STAGE_LAB, STAGE_QUALITY)

# ── reason codes ─────────────────────────────────────────────────────────────
OVER_EVIDENCE_CAP = "over_evidence_cap"
NO_STATEMENT_IN_BLOCK = "no_statement_in_block"
LAB_TEST_FAILED = "lab_test_failed"
NOT_TESTABLE_NO_PREDICTION = "not_testable_no_prediction"
SAFETY_RISKS_MISSING = "safety_risks_missing"
UNEXPLAINED_DROP = "unexplained_drop"

REJECT_CODES = (OVER_EVIDENCE_CAP, NO_STATEMENT_IN_BLOCK, LAB_TEST_FAILED,
                NOT_TESTABLE_NO_PREDICTION, SAFETY_RISKS_MISSING,
                UNEXPLAINED_DROP)

# ── "naapi hi nahi ja saki" — reject se ALAG baat ────────────────────────────
# #155e — gaana/creative maang par bani hypothesis jinka naap ASLI INSAAN par
# hota hai (GSR, EEG, dil ki dhadkan, 100 logon ka listening panel). Ye code
# jaan-boojh kar `REJECT_CODES` me NAHI hai: aisi hypothesis na hataayi jaati
# hai, na `rejected` list me jaati hai, na `kept` se nikalti hai. Ledger me wo
# apni alag `unmeasured` list me jaati hai — "yahan naapi nahi ja sakti" bolna
# aur "kamzor thi isliye nikaal di" bolna do bilkul alag baatein hain, aur dono
# ko ek list me daalna hi jhooth hota.
HUMAN_SUBJECT_ON_CRAFT_ASK = "human_subject_on_craft_ask"

UNMEASURED_CODES = (HUMAN_SUBJECT_ON_CRAFT_ASK,)

# Padhne wale ki bhasha me wajah. Har line me "kya naapa" ka ishaara hai —
# "adhoori thi" jaisa bemaani jumla yahan nahi chalega.
_REASON_TEXT: Dict[str, str] = {
    OVER_EVIDENCE_CAP:
        "Evidence ke hisaab se itni hypotheses banane ki ijaazat hi nahi thi — "
        "model ne zyada bheji thi, jo cap se bahar thi wo aage nahi gayi.",
    NO_STATEMENT_IN_BLOCK:
        "Is block me koi saaf 'statement' line hi nahi thi — jo daawa hi nahi "
        "likha, uska test bhi nahi ban sakta.",
    LAB_TEST_FAILED:
        "App ne khud (#116 LAB) iska hisaab chalaya aur naapa hua number daawe "
        "se ulta nikla — isliye ise aage nahi badhaya ja raha.",
    NOT_TESTABLE_NO_PREDICTION:
        "Na koi concrete test plan, na 'agar sach hai to kya dikhega' — aise "
        "idea ko galat sabit karna bhi possible nahi, isliye ye speculation hai.",
    SAFETY_RISKS_MISSING:
        "Ye medical/chemical/biological ya safety se judi baat hai par risks/"
        "safety check likhe hi nahi gaye — is haalat me aage badhana galat hai.",
    UNEXPLAINED_DROP:
        "Ye hypothesis list se nikal gayi par iski koi NAAPI HUI wajah nahi "
        "mili — ise bug maano, chup-chaap drop nahi chalega.",
    HUMAN_SUBJECT_ON_CRAFT_ASK:
        "Is daawe ko naapne ke liye ASLI INSAAN chahiye (body signal ya "
        "listening panel) — app ke paas na koi insaan hai na uska data, isliye "
        "iska PASS/FAIL yahan banana jhooth hota. Idea galat sabit NAHI hua; "
        "bane hue draft ka apna naap alag se hota hai.",
}

# Reject ka matlab "hamesha ke liye khatam" nahi. Kis naap par wapas aa sakti
# hai, ye har code ke saath likha jaata hai.
_REOPEN_IF: Dict[str, str] = {
    OVER_EVIDENCE_CAP:
        "Zyada aur behtar (full-text/peer-reviewed) sources milne par cap badhta "
        "hai — tab ye wapas aa sakti hai.",
    NO_STATEMENT_IN_BLOCK:
        "Ek saaf, ek-line ka daawa likha jaaye to ye dobara ban sakti hai.",
    LAB_TEST_FAILED:
        "Naya ya theek data aane par (ya daawe ka number badalne par) test "
        "dobara chalega — LAB ka fail asli duniya ka faisla nahi hai.",
    NOT_TESTABLE_NO_PREDICTION:
        "Ek naapne layak prediction (kya, kis par, kaunsa nateeja galat sabit "
        "karega) jud jaaye to ye phir se chal sakti hai.",
    SAFETY_RISKS_MISSING:
        "Risks + safety checks likhe jaayein aur qualified review ho, tab hi.",
    UNEXPLAINED_DROP: "Pehle wajah naapo — tab tak ise khula bug maano.",
    HUMAN_SUBJECT_ON_CRAFT_ASK:
        "Asli insaano par (ya kisi padhe hue published study ke apne numbers "
        "par) ye naap ho jaaye, to nateeja seedha jud sakta hai — tab tak ye "
        "khuli hui, na-naapi hui baat hai.",
}

# Ye codes delivered answer me hypothesis ko "aage nahi badhaya" bana dete hain.
BLOCKING_CODES = (SAFETY_RISKS_MISSING, LAB_TEST_FAILED,
                  NOT_TESTABLE_NO_PREDICTION, UNEXPLAINED_DROP)

# Ek hypothesis par ek se zyada baat lag sakti hai — pehla wahi jo sabse
# bhaari hai (safety sabse pehle). Baaki `also_codes` me darj rehte hain.
_CODE_PRIORITY = (SAFETY_RISKS_MISSING, LAB_TEST_FAILED,
                  NOT_TESTABLE_NO_PREDICTION)

REJECT_SUBHEADING = "### Kya-kya reject hua (aur kis naap par)"

DISCLAIMER = (
    "Reject ka matlab 'galat sabit ho gaya' NAHI hai — matlab sirf itna hai ki "
    "is run me iske aage badhne ki naapi hui wajah nahi bani. Har reject ke "
    "saath ye bhi likha hai ki kis haalat me ye wapas aa sakti hai."
)


@dataclass
class Reject:
    """Ek hypothesis ke reject hone ka poora record."""
    hypothesis_id: str = ""
    statement: str = ""
    stage: str = STAGE_QUALITY
    reason_code: str = UNEXPLAINED_DROP
    measured: Dict[str, Any] = field(default_factory=dict)
    evidence_ids: List[str] = field(default_factory=list)
    also_codes: List[str] = field(default_factory=list)
    index: int = 0

    @property
    def reason(self) -> str:
        return _REASON_TEXT.get(self.reason_code, _REASON_TEXT[UNEXPLAINED_DROP])

    @property
    def reopen_if(self) -> str:
        return _REOPEN_IF.get(self.reason_code, _REOPEN_IF[UNEXPLAINED_DROP])

    @property
    def blocking(self) -> bool:
        return self.reason_code in BLOCKING_CODES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "stage": self.stage,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "measured": dict(self.measured),
            "evidence_ids": list(self.evidence_ids),
            "also_codes": list(self.also_codes),
            "reopen_if": self.reopen_if,
            "blocking": self.blocking,
            # Ye do line kabhi nahi badalti: reject app ka faisla hai, duniya ka
            # nahi. Isliye na "disproved", na "galat sabit".
            "is_disproved": False,
            "app_decision_only": True,
        }


def _measured_ok(measured: Optional[Dict[str, Any]]) -> bool:
    """Naap sach me hai ya khaali dikhawa? Khaali string/None naap nahi hai."""
    if not isinstance(measured, dict) or not measured:
        return False
    return any(value is not None and value != "" and value != []
               for value in measured.values())


def make_reject(hypothesis_id: str = "", statement: str = "",
                stage: str = STAGE_QUALITY, reason_code: str = UNEXPLAINED_DROP,
                measured: Optional[Dict[str, Any]] = None,
                evidence_ids: Optional[Sequence[str]] = None,
                also_codes: Optional[Sequence[str]] = None,
                index: int = 0) -> Reject:
    """
    Reject banao — par **bina naap ke nahi**.

    Ye is poore module ka sabse zaroori guard hai: agar `measured` khaali hai,
    ya code hamari list me nahi hai, to record `unexplained_drop` ban jaata hai
    (aur ledger us par warning uthata hai). Yahi intel ki baat ka code-roop hai:
    "kyu nikal rhe, kya naap hai".
    """
    code = reason_code if reason_code in REJECT_CODES else UNEXPLAINED_DROP
    naap = dict(measured or {})
    if not _measured_ok(naap):
        naap = {"why_unexplained": "koi naap nahi mili",
                "original_reason_code": reason_code or "(khaali)"}
        code = UNEXPLAINED_DROP
    return Reject(hypothesis_id=str(hypothesis_id or "").strip(),
                  statement=str(statement or "").strip(),
                  stage=stage if stage in STAGES else STAGE_QUALITY,
                  reason_code=code, measured=naap,
                  evidence_ids=[str(e) for e in (evidence_ids or []) if e],
                  also_codes=[str(c) for c in (also_codes or []) if c],
                  index=int(index or 0))


def parse_rejects(records: Optional[Sequence[Dict[str, Any]]]) -> List[Reject]:
    """
    `HypothesisEngine.parse()` ne jo blocks gira diye, unke record.

    parse ke paas hypothesis id nahi hoti (id `enrich()` me banti hai), isliye
    yahan id khaali rehti hai aur pehchan `statement`/naap se hoti hai. Iska ek
    faayda hai: cap se bahar gira block bhi answer me dikh jaata hai, jo pehle
    kabhi dikhta hi nahi tha.
    """
    out: List[Reject] = []
    for position, row in enumerate(records or [], 1):
        if not isinstance(row, dict):
            continue
        out.append(make_reject(
            hypothesis_id=str(row.get("hypothesis_id") or ""),
            statement=str(row.get("statement") or ""),
            stage=STAGE_PARSE,
            reason_code=str(row.get("reason_code") or ""),
            measured=row.get("measured") if isinstance(row.get("measured"), dict)
            else None,
            index=int(row.get("index") or position)))
    return out


def _failing_lab_test(block: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """LAB block me se wahi test jo fail hua — uska naap wapas do."""
    if not isinstance(block, dict):
        return {}
    for test in block.get("tests") or []:
        if not isinstance(test, dict):
            continue
        if str(test.get("status") or "") == "TESTED_FAIL":
            return test
    return {}


def lab_rejects(hypotheses: Optional[Sequence[Dict[str, Any]]]) -> List[Reject]:
    """
    #116 ke `TESTED_FAIL` ko naapi hui reject wajah me badlo.

    Yahan hum LAB ke apne shabd hi uthate hain (`observed` vs `expected`) —
    apni taraf se koi number nahi banate. LAB ka fail asli duniya ka faisla
    nahi hai, isliye `reopen_if` wahi saaf batata hai.
    """
    out: List[Reject] = []
    for position, hypothesis in enumerate(hypotheses or [], 1):
        if not isinstance(hypothesis, dict):
            continue
        if str(hypothesis.get("lab_verdict") or "") != "TESTED_FAIL":
            continue
        block = hypothesis.get("lab") if isinstance(hypothesis.get("lab"),
                                                    dict) else {}
        test = _failing_lab_test(block)
        measured = {
            "lab_verdict": "TESTED_FAIL",
            "recipe": test.get("recipe") or "",
            "naapa_gaya": test.get("observed") or "",
            "daawa_tha": test.get("expected") or "",
            "verdict_reason": block.get("verdict_reason") or "",
        }
        out.append(make_reject(
            hypothesis_id=str(hypothesis.get("hypothesis_id") or ""),
            statement=str(hypothesis.get("statement") or ""),
            stage=STAGE_LAB, reason_code=LAB_TEST_FAILED, measured=measured,
            evidence_ids=test.get("evidence_ids") or [], index=position))
    return out


# `honesty_check()` wahi 15 char ki hadd rakhta hai — do jagah do hadd rakhna
# hi purani galti thi, isliye number ek jagah se aata hai.
MIN_RISK_CHARS = 15


UNMEASURED_SUBHEADING = "### Jo yahan NAAPI hi nahi ja saki (reject nahi)"

UNMEASURED_DISCLAIMER = (
    "Neeche wali hypotheses hataayi NAHI gayi — wo answer me apni jagah hain. "
    "Farq sirf itna hai ki inka test is machine ke andar ban hi nahi sakta, "
    "isliye inke saath koi PASS/FAIL nahi lagaya gaya. 'Naapi nahi ja saki' "
    "aur 'kamzor nikli' do alag baatein hain."
)


def unmeasured_records(hypotheses: Optional[Sequence[Dict[str, Any]]]
                       ) -> List[Dict[str, Any]]:
    """
    #155e — jinka LAB test ban hi nahi saka, unka apna alag record.

    Ye `rejected` list NAHI hai: yahan aane wali hypothesis `kept` me bhi rehti
    hai aur `apply_to_hypotheses` use `rejected=True` bhi nahi karta. Naap LAB
    ke apne block se uthaayi jaati hai (`human_subject_phrase`) — apni taraf se
    koi wajah nahi gadhi jaati, aur phrase wahi chhapta hai jo asli text me tha.
    """
    out: List[Dict[str, Any]] = []
    for position, hypothesis in enumerate(hypotheses or [], 1):
        if not isinstance(hypothesis, dict):
            continue
        block = hypothesis.get("lab")
        if not isinstance(block, dict) or not block.get("needs_human_subjects"):
            continue
        phrase = str(block.get("human_subject_phrase") or "").strip()
        out.append({
            "hypothesis_id": str(hypothesis.get("hypothesis_id") or ""),
            "statement": str(hypothesis.get("statement") or ""),
            "stage": STAGE_LAB,
            "reason_code": HUMAN_SUBJECT_ON_CRAFT_ASK,
            "reason": _REASON_TEXT[HUMAN_SUBJECT_ON_CRAFT_ASK],
            "reopen_if": _REOPEN_IF[HUMAN_SUBJECT_ON_CRAFT_ASK],
            "measured": {
                "lab_verdict": str(block.get("verdict") or ""),
                "rukne_wala_shabd": phrase,
                "test_bane": len(block.get("tests") or []),
            },
            # Ye chaar line kabhi nahi badalti — na reject, na proof, na faisla.
            "rejected": False,
            "removed_from_answer": False,
            "is_disproved": False,
            "app_decision_only": True,
            "index": position,
        })
    return out


def unmeasured_section(ledger: Optional[Dict[str, Any]]) -> str:
    """Ledger ki `unmeasured` list ka `###` block. Khaali par "" (koi shor nahi).

    `###` hi rehta hai — `##` karne par answer_order ek naya top-level section
    gin leta hai (#116/#117 ka wahi purana trap).
    """
    if not isinstance(ledger, dict) or not ledger.get("unmeasured"):
        return ""
    lines: List[str] = [UNMEASURED_SUBHEADING, "", UNMEASURED_DISCLAIMER, ""]
    for row in ledger["unmeasured"]:
        title = str(row.get("hypothesis_id") or "").strip() or "hypothesis"
        lines.append(f"**{title}** — naap yahan mumkin nahi")
        statement = str(row.get("statement") or "").strip()
        if statement:
            lines.append(f"- Daawa: {statement}")
        lines.append(f"- Kyun: {row.get('reason')}")
        measured = _measured_line(row.get("measured"))
        if measured:
            lines.append(f"- Naap: {measured}")
        lines.append(f"- Wapas kab: {row.get('reopen_if')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def quality_rejects(hypotheses: Optional[Sequence[Dict[str, Any]]]) -> List[Reject]:
    """
    Deterministic quality reject — sirf do haalat, dono naapi hui.

    1. safety-sensitive baat par risks likhe hi nahi (non-negotiable: medical/
       chemical/biological par risk check compulsory hai).
    2. na test plan na prediction — yaani ise galat sabit karna hi possible
       nahi. **Dono** shart zaroori hain: sirf "field missing hai" par reject
       nahi hota, wo warning ka kaam hai (honesty_check karta hai).
    """
    out: List[Reject] = []
    for position, hypothesis in enumerate(hypotheses or [], 1):
        if not isinstance(hypothesis, dict):
            continue
        hits: List[tuple] = []
        risks = str(hypothesis.get("risks") or "").strip()
        if hypothesis.get("safety_sensitive") and len(risks) < MIN_RISK_CHARS:
            hits.append((SAFETY_RISKS_MISSING, {
                "safety_sensitive": True,
                "risks_likhe_gaye_chars": len(risks),
                "kam_se_kam_chahiye_chars": MIN_RISK_CHARS,
            }))
        testable = bool(hypothesis.get("is_testable"))
        predicted = bool(hypothesis.get("has_prediction"))
        if not testable and not predicted:
            hits.append((NOT_TESTABLE_NO_PREDICTION, {
                "is_testable": False,
                "has_prediction": False,
                "test_plan_chars": len(str(hypothesis.get("experiment") or "").strip()),
                "falsification_chars": len(
                    str(hypothesis.get("falsification_test") or "").strip()),
            }))
        if not hits:
            continue
        order = {code: rank for rank, code in enumerate(_CODE_PRIORITY)}
        hits.sort(key=lambda pair: order.get(pair[0], 99))
        code, measured = hits[0]
        out.append(make_reject(
            hypothesis_id=str(hypothesis.get("hypothesis_id") or ""),
            statement=str(hypothesis.get("statement") or ""),
            stage=STAGE_QUALITY, reason_code=code, measured=measured,
            also_codes=[c for c, _ in hits[1:]], index=position))
    return out


def _keep_record(hypothesis: Dict[str, Any], position: int) -> Dict[str, Any]:
    """Jo rakhi gayi, uske saath bhi NAAP jaaye — "acchi lagi" wajah nahi hai."""
    provenance = hypothesis.get("provenance")
    facts = 0
    if isinstance(provenance, dict):
        facts = len(provenance.get("facts_used") or provenance.get("facts") or [])
    return {
        "hypothesis_id": str(hypothesis.get("hypothesis_id") or ""),
        "statement": str(hypothesis.get("statement") or ""),
        "index": position,
        "measured": {
            "lab_verdict": str(hypothesis.get("lab_verdict") or "NOT_RUN"),
            "confidence_band": hypothesis.get("confidence_band") or "",
            "is_testable": bool(hypothesis.get("is_testable")),
            "has_prediction": bool(hypothesis.get("has_prediction")),
            "evidence_facts_used": facts,
        },
        # Rakhna bhi saboot nahi hai — ye line kabhi na hate.
        "kept_is_not_proof": True,
    }


def _identity(hypothesis: Dict[str, Any], position: int) -> str:
    """id ho to id, warna statement — dedupe ka bharosemand tareeka."""
    hid = str(hypothesis.get("hypothesis_id") or "").strip()
    if hid:
        return f"id:{hid}"
    statement = str(hypothesis.get("statement") or "").strip()
    return f"text:{statement[:120]}" if statement else f"pos:{position}"


def build_ledger(hypotheses: Optional[Sequence[Dict[str, Any]]] = None,
                 parse_records: Optional[Sequence[Dict[str, Any]]] = None,
                 requested: int = 0,
                 gate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Poora reject-ledger: kya gaya, kis naap par, kya bacha, aur kya khula sawaal.

    LAB aur quality dono ek hi hypothesis par lag sakte hain — tab record ek hi
    banta hai (safety > lab > untestable) aur baaki wajah `also_codes` me darj
    rehti hai. Kuch bhi chhupta nahi, par ek hi baat do baar bhi nahi chhapti.
    """
    rows = [h for h in (hypotheses or []) if isinstance(h, dict)]
    picked: Dict[str, Reject] = {}
    order: List[str] = []
    rank = {code: index for index, code in enumerate(_CODE_PRIORITY)}
    for reject in lab_rejects(rows) + quality_rejects(rows):
        position = reject.index
        key = _identity(rows[position - 1], position) if 0 < position <= len(rows) \
            else f"pos:{position}"
        if key not in picked:
            picked[key] = reject
            order.append(key)
            continue
        old = picked[key]
        new_codes = [old.reason_code] + list(old.also_codes) + \
                    [reject.reason_code] + list(reject.also_codes)
        winner, loser = (reject, old) if rank.get(reject.reason_code, 99) < \
            rank.get(old.reason_code, 99) else (old, reject)
        winner.also_codes = [c for c in dict.fromkeys(new_codes)
                             if c != winner.reason_code]
        winner.measured = dict(winner.measured)
        for field_name, value in loser.measured.items():
            winner.measured.setdefault(field_name, value)
        winner.evidence_ids = list(dict.fromkeys(list(winner.evidence_ids)
                                                + list(loser.evidence_ids)))
        picked[key] = winner
    rejected_keys = set(picked)
    # Pehle parse-stage (jo answer tak pahunchi hi nahi), phir lab/quality —
    # padhne wale ke liye yahi kram sach ke kareeb hai.
    rejected = [r.to_dict() for r in parse_rejects(parse_records)]
    rejected += [picked[key].to_dict() for key in order]

    kept = [_keep_record(row, position) for position, row in enumerate(rows, 1)
            if _identity(row, position) not in rejected_keys]
    counts: Dict[str, int] = {}
    for row in rejected:
        code = str(row.get("reason_code") or UNEXPLAINED_DROP)
        counts[code] = counts.get(code, 0) + 1
    # #155e — ye list `rejected` se BAAHAR hai aur `kept` ko chhoti nahi karti:
    # jo yahan hai wo answer me bhi hai. Isliye counts me bhi nahi jodi jaati,
    # warna "itni reject hui" ki ginti jhoothi ho jaati.
    return _finish_ledger(rejected, kept, counts, rows, requested, gate,
                          unmeasured_records(rows))


def _finish_ledger(rejected: List[Dict[str, Any]], kept: List[Dict[str, Any]],
                   counts: Dict[str, int], rows: List[Dict[str, Any]],
                   requested: int,
                   gate: Optional[Dict[str, Any]],
                   unmeasured: Optional[List[Dict[str, Any]]] = None
                   ) -> Dict[str, Any]:
    """Ledger ka aakhiri hissa: warnings, note aur imaandaar disclaimer."""
    warnings: List[str] = []
    unexplained = [row.get("hypothesis_id") or row.get("statement") or "?"
                   for row in rejected
                   if row.get("reason_code") == UNEXPLAINED_DROP]
    if unexplained:
        warnings.append(
            f"{len(unexplained)} hypothesis bina naapi hui wajah ke list se nikli "
            "— ise bug maano, chup-chaap drop is app me allowed nahi hai.")
    if rows and not kept and rejected:
        warnings.append(
            "Saari hypotheses reject ho gayi — iska matlab 'sawaal ka jawab nahi "
            "hai' nahi, matlab is run me koi bhi hypothesis aage badhne layak "
            "naap par khadi nahi hui.")
    if requested and len(kept) < int(requested):
        line = (f"Aapne {int(requested)} maangi thi, {len(kept)} aage badhi "
                f"({len(rejected)} reject hui — wajah neeche naap ke saath hai).")
        if isinstance(gate, dict) and gate.get("reason"):
            line += f" Evidence ki haalat: {gate['reason']}"
        warnings.append(line)
    note = ""
    if not rejected:
        note = ("Is run me koi hypothesis reject nahi hui. Iska matlab 'sab sahi "
                "hai' NAHI hai — sirf itna ki reject karne wali naapi hui wajah "
                "kisi par nahi lagi.")
    return {
        "ran": True,
        "checked": len(rows),
        "rejected": rejected,
        "kept": kept,
        # #155e — na reject, na proof: sirf "yahan naapi nahi ja saki". Khaali
        # list bhi jaati hai taaki UI ko "key hi nahi hai" ka andaaza na lagana
        # pade (wahi niyam jo `apply_to_hypotheses` me hai).
        "unmeasured": list(unmeasured or []),
        "counts": counts,
        "blocking": len([r for r in rejected if r.get("blocking")]),
        "unexplained": len(unexplained),
        "warnings": warnings,
        "note": note,
        "disclaimer": DISCLAIMER,
        "gemini_calls": 0,
        "provider_cost": 0,
    }


def reject_map(ledger: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """id → reject record (sirf jinke paas id hai)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(ledger, dict):
        return out
    for row in ledger.get("rejected") or []:
        hid = str(row.get("hypothesis_id") or "").strip()
        if hid and hid not in out:
            out[hid] = row
    return out


def apply_to_hypotheses(hypotheses: Optional[Sequence[Dict[str, Any]]],
                        ledger: Optional[Dict[str, Any]]
                        ) -> List[Dict[str, Any]]:
    """
    Har hypothesis dict par reject ka nishaan lagao — **hataye bina**.

    Purani keys chhui nahi jaati, input dicts badalte nahi (copy banti hai).
    `rejected=False` bhi saaf likha jaata hai, taaki UI ko "key hi nahi hai"
    ka andaaza na lagana pade.
    """
    lookup = reject_map(ledger)
    out: List[Dict[str, Any]] = []
    for position, hypothesis in enumerate(hypotheses or [], 1):
        if not isinstance(hypothesis, dict):
            out.append(hypothesis)
            continue
        copy = dict(hypothesis)
        hid = str(copy.get("hypothesis_id") or "").strip()
        row = lookup.get(hid) if hid else None
        copy["rejected"] = bool(row)
        copy["reject_reason_code"] = str(row.get("reason_code")) if row else ""
        copy["reject_reason"] = str(row.get("reason")) if row else ""
        copy["reject_measured"] = dict(row.get("measured") or {}) if row else {}
        copy["reject_reopen_if"] = str(row.get("reopen_if")) if row else ""
        # Reject hone par bhi ye kabhi True nahi hota (#116 ka wahi niyam).
        copy["is_disproved"] = False
        out.append(copy)
    return out


def _measured_line(measured: Optional[Dict[str, Any]]) -> str:
    """Naap ko ek line me — jo khaali hai wo chhapta hi nahi."""
    bits = [f"{key}={value}" for key, value in (measured or {}).items()
            if value is not None and value != "" and value != []]
    return ", ".join(bits)


def reject_section(ledger: Optional[Dict[str, Any]]) -> str:
    """
    Answer ka `###` block: kya reject hua aur kis naap par.

    `###` hi rehna chahiye — `##` karne se answer_order ke top-level sections me
    ek naya section gin jaata hai (#116 me yahi trap tha).
    """
    if not isinstance(ledger, dict) or not ledger.get("rejected"):
        return ""
    lines: List[str] = [REJECT_SUBHEADING, "",
                        str(ledger.get("disclaimer") or DISCLAIMER), ""]
    for row in ledger["rejected"]:
        title = str(row.get("hypothesis_id") or "").strip()
        if not title:
            statement = str(row.get("statement") or "").strip()
            title = (statement[:60] + "…") if len(statement) > 60 else \
                (statement or "(bina naam wala block)")
        lines.append(f"**{title}** — ❌ aage nahi badhaya")
        statement = str(row.get("statement") or "").strip()
        if statement and statement not in title:
            lines.append(f"- Daawa: {statement}")
        lines.append(f"- Kyun: {row.get('reason')}")
        naap = _measured_line(row.get("measured"))
        if naap:
            lines.append(f"- Naap: {naap}")
        if row.get("evidence_ids"):
            lines.append("- Kis source par naapa: "
                         + ", ".join(f"[{e}]" for e in row["evidence_ids"]))
        also = [c for c in (row.get("also_codes") or [])]
        if also:
            lines.append("- Iske saath ye baat bhi thi: " + ", ".join(also))
        lines.append(f"- Wapas kab aa sakti hai: {row.get('reopen_if')}")
        lines.append("")
    for warning in ledger.get("warnings") or []:
        lines.append(f"- ⚠️ {warning}")
    if ledger.get("note"):
        lines.append(f"- {ledger['note']}")
    return "\n".join(lines).rstrip() + "\n"


def reject_limits(ledger: Optional[Dict[str, Any]]) -> List[str]:
    """Audit ke liye naapi hui line — boilerplate nahi."""
    if not isinstance(ledger, dict) or not ledger.get("ran"):
        return []
    out: List[str] = []
    rejected = ledger.get("rejected") or []
    kept = ledger.get("kept") or []
    if rejected:
        out.append(f"{len(rejected)} hypothesis reject hui, {len(kept)} aage badhi "
                   "— har reject ke saath naap aur 'wapas kab aa sakti hai' likha "
                   "hai. Reject ka matlab 'galat sabit' nahi hai.")
    for code, total in sorted((ledger.get("counts") or {}).items()):
        out.append(f"Reject wajah `{code}`: {total}")
    if ledger.get("unexplained"):
        out.append(f"{ledger['unexplained']} drop ki naapi hui wajah nahi mili — "
                   "ye khula bug hai, ise 'quality check' nahi maana ja sakta.")
    if kept and not rejected:
        out.append("Koi hypothesis reject nahi hui — iska matlab 'sab verified' "
                   "nahi, sirf itna ki reject ki naapi hui wajah kisi par nahi lagi.")
    return out







