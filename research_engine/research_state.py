"""
§20 — chaar ALAG state machine, aur unke beech ka conflict pakadne wala module.

Kaunsi galti isse rukti hai (dark-matter live run, 2026-08-21):
    Provider ka background job `FINISHED` hua, aur usi ek shabd ko teen matlab
    diye gaye: "jawab poora hai", "evidence strong hai", "idea naya hai".
    Report ke top par `COMPLETE` + `✅ VERIFIED` chhap gaya, jabki CMB/BBN/
    lensing raaste khaali the, 14 claims par `[NO-SOURCE]` tha aur prior-art
    search chali hi nahi thi.

Isliye ab chaar sawaal, chaar alag jawab, chaar alag vocabulary
(`models.py` ke whitelist se bahar ek bhi shabd nahi):

    1. job_status         — background kaam ka kya hua?   (process ki baat)
    2. answer_state       — user ka sawaal poora hua?     (contract ki baat)
    3. evidence_state     — saboot kitna mazboot hai?     (retrieval+check ki baat)
    4. novelty_state      — app ka idea naya hai?         (prior-art ki baat)

Aur ek paanchvi cheez jo pehle kahin nahi thi: **conflicts**. Do state ek
doosre se ulti baat kah rahi hon to use chhupaya nahi jaata — `conflicts` list
mein saaf likha jaata hai, aur `verified_allowed` False ho jaata hai.

Tri-state niyam yahan bhi zinda hai: jo check chala hi nahi uska matlab
`NOT CHECKED` hai, `zero` nahi.

Module jaan-boojh kar pure-Python hai (koi model, koi network) — offline test ho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .models import (ANSWER_COMPLETE, ANSWER_FAILED, ANSWER_INSUFFICIENT,
                     ANSWER_PARTIAL, ANSWER_STATES, EVIDENCE_MIXED,
                     EVIDENCE_MODERATE, EVIDENCE_NONE, EVIDENCE_NOT_CHECKED,
                     EVIDENCE_STATES, EVIDENCE_STRONG, EVIDENCE_WEAK,
                     JOB_FAILED, JOB_FINISHED, JOB_QUEUED, JOB_RECOVERED,
                     JOB_RUNNING, JOB_STATES, NOVELTY_POSSIBLE, NOVELTY_STATES,
                     NOVELTY_UNVERIFIED)

# ── insaani bhasha (UI aur audit block dono yahin se padhte hain) ────────────
JOB_EXPLAIN: Dict[str, str] = {
    JOB_QUEUED: "kaam line mein laga hai, shuru nahi hua",
    JOB_RUNNING: "kaam chal raha hai",
    JOB_FINISHED: ("background kaam khatam ho gaya — iska matlab jawab poora "
                   "hona NAHI hai"),
    JOB_FAILED: "background kaam beech mein toot gaya",
    JOB_RECOVERED: "connection toota tha, purana result history se wapas mila",
}

ANSWER_EXPLAIN: Dict[str, str] = {
    ANSWER_COMPLETE: "jo maanga gaya tha, wo saara diya gaya",
    ANSWER_PARTIAL: "kuch zaroori hissa nahi ban paaya",
    ANSWER_INSUFFICIENT: "sawaal ke layak evidence hi nahi mila",
    ANSWER_FAILED: "jawab ban hi nahi paaya",
}

EVIDENCE_EXPLAIN: Dict[str, str] = {
    EVIDENCE_STRONG: "aapas mein alag, mazboot sources ne ek hi baat kahi",
    EVIDENCE_MODERATE: "support hai par utna pukhta nahi",
    EVIDENCE_WEAK: "sources kam ya kamzor hain",
    EVIDENCE_MIXED: "support aur uske khilaaf, dono taraf ka evidence mila",
    EVIDENCE_NONE: "kaam mein aane laayak ek bhi source nahi mila",
    EVIDENCE_NOT_CHECKED: "evidence check chala hi nahi (ye 'kuch nahi mila' se ALAG hai)",
}

NOVELTY_EXPLAIN: Dict[str, str] = {
    NOVELTY_UNVERIFIED: "prior-art search nahi hui, isliye naya/purana kehna mana hai",
    NOVELTY_POSSIBLE: "dhoondhne par bhi paas ka match nahi mila",
}

# Whitelist ke bahar ka shabd chup-chaap "theek" nahi maana jaata: state banate
# hi validate hota hai, warna kal koi "MOSTLY VERIFIED" jaisa naya label bina
# gate ke ghus jaata.
_FAMILIES = (
    ("job_status", JOB_STATES),
    ("answer_state", ANSWER_STATES),
    ("evidence_state", EVIDENCE_STATES),
    ("novelty_state", NOVELTY_STATES),
)


@dataclass
class ResearchState:
    """Ek run ki chaar alag haalat + unke beech ke conflicts."""

    job_status: str = JOB_FINISHED
    answer_state: str = ANSWER_PARTIAL
    evidence_state: str = EVIDENCE_NOT_CHECKED
    novelty_state: str = NOVELTY_UNVERIFIED
    # Novelty har sawaal par laagu nahi hoti (app ne koi hypothesis hi na banayi ho).
    novelty_applicable: bool = False
    # Har state ke saath uski ek-line wajah — UI ise seedha dikha sakta hai.
    reasons: Dict[str, str] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)
    # ── #155d — do NAYI cheezein, dono default khaali ─────────────────────────
    # Khaali rehne par is class ka bartaav bilkul purana hai (koi nayi row nahi
    # chhapti, koi naya conflict nahi banta) — isliye ye ADD hai, badlav nahi.
    #
    # 1. `deliverable` = `deliverable_guard.public_record(...)`. Ye chaar research
    #    state mein SHAAMIL NAHI hai aur unhe badalta bhi nahi: "gaana ban gaya"
    #    ka matlab "evidence mazboot hai" nahi, aur "evidence kam hai" ka matlab
    #    "gaana nahi bana" nahi. Isi do-matlab wali mix ne pichhle live run mein
    #    gaane ko gayab karke bhi report ko bhara-bhara dikhaya tha.
    # 2. `counts` = kachche source aur seedhe kaam ke source ki ALAG ginti. Ek hi
    #    report mein "40 sources use hue" aur `EVIDENCE NONE` saath dikh chuke
    #    hain — dono sach the, par ek line wajah kahin likhi nahi thi.
    deliverable: Dict = field(default_factory=dict)
    counts: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, allowed in _FAMILIES:
            value = getattr(self, name)
            if value not in allowed:
                raise ValueError(
                    f"{name} ki value whitelist mein nahi hai: {value!r}. "
                    f"Allowed: {list(allowed)}")

    # ── faisle jo doosre module (aur final gate) padhte hain ─────────────────
    @property
    def verified_allowed(self) -> bool:
        """`✅ VERIFIED` top label kab-kab allowed hai (aur kabhi conflict par nahi)."""
        if self.conflicts:
            return False
        if self.answer_state != ANSWER_COMPLETE:
            return False
        return self.evidence_state in (EVIDENCE_STRONG, EVIDENCE_MODERATE)

    @property
    def answer_complete(self) -> bool:
        return self.answer_state == ANSWER_COMPLETE

    @property
    def job_done(self) -> bool:
        """Sirf process ki baat — jawab ke baare mein kuch NAHI kehta."""
        return self.job_status in (JOB_FINISHED, JOB_RECOVERED, JOB_FAILED)

    def to_dict(self) -> Dict:
        return {
            "job_status": self.job_status,
            "answer_state": self.answer_state,
            "evidence_state": self.evidence_state,
            "novelty_state": self.novelty_state,
            "novelty_applicable": self.novelty_applicable,
            "reasons": dict(self.reasons),
            "conflicts": list(self.conflicts),
            "verified_allowed": self.verified_allowed,
            # #155d — paanchvi/chhathvi cheez ALAG key mein. Chaar state ki
            # vocabulary ismein ghusti nahi, warna UI ise "paanchva state" samajh
            # kar VERIFIED ke hisaab mein le aata.
            "deliverable": dict(self.deliverable),
            "counts": dict(self.counts),
            # Ye line UI ke liye hai: chaar state ek jagah, ek hi vocabulary.
            "explain": {
                "job_status": JOB_EXPLAIN.get(self.job_status, ""),
                "answer_state": ANSWER_EXPLAIN.get(self.answer_state, ""),
                "evidence_state": EVIDENCE_EXPLAIN.get(self.evidence_state, ""),
                "novelty_state": NOVELTY_EXPLAIN.get(self.novelty_state, ""),
            },
        }


# ── 1. job status ────────────────────────────────────────────────────────────
def job_status_of(*, finished: bool = True, crashed: bool = False,
                  recovered: bool = False, running: bool = False,
                  queued: bool = False) -> str:
    """Sirf process dekh kar job ki haalat. Jawab ki quality se koi lena-dena nahi."""
    if queued:
        return JOB_QUEUED
    if running:
        return JOB_RUNNING
    if recovered:
        return JOB_RECOVERED
    if crashed:
        return JOB_FAILED
    return JOB_FINISHED if finished else JOB_RUNNING


# ── 2. answer completeness ───────────────────────────────────────────────────
# `requested.contract_ledger()` ka `result_state` pehle se hi teen haalat rakhta
# hai; usi ko §20 ki vocabulary mein badla jaata hai (do jagah do naam rakhne se
# hi purani gadbad hui thi).
_LEDGER_TO_ANSWER = {
    "COMPLETE": ANSWER_COMPLETE,
    "PARTIAL": ANSWER_PARTIAL,
    "INSUFFICIENT_EVIDENCE": ANSWER_INSUFFICIENT,
}


def answer_state_of(ledger: Optional[Dict] = None, *, answer_text: str = "",
                    source_count: int = 0) -> str:
    """Contract ledger se jawab ki haalat (job ke status se BILKUL alag)."""
    if not str(answer_text or "").strip():
        return ANSWER_FAILED
    led = ledger or {}
    state = _LEDGER_TO_ANSWER.get(str(led.get("result_state") or ""), "")
    if state:
        # Sources hi na hon to "PARTIAL" kehna narmi hai — evidence hi nahi tha.
        if state != ANSWER_COMPLETE and source_count <= 0:
            return ANSWER_INSUFFICIENT
        return state
    if led.get("answer_complete") is True:
        return ANSWER_COMPLETE
    if source_count <= 0:
        return ANSWER_INSUFFICIENT
    return ANSWER_PARTIAL


# ── 3. evidence state ────────────────────────────────────────────────────────
def evidence_state_of(*, source_count: int = 0,
                      usable_source_count: Optional[int] = None,
                      verification_ran: Optional[bool] = None,
                      supported_claims: Optional[int] = None,
                      unsupported_claims: Optional[int] = None,
                      contradictions: int = 0,
                      counter_search: Optional[bool] = None) -> str:
    """
    Evidence ki haalat — ginti se nahi, jaanch se.

    Tri-state ka poora samman: `verification_ran is None` ka matlab "check hua
    hi nahi" hai, aur uska jawab `NOT CHECKED` hai — `WEAK` nahi. Ye do cheezein
    milane se hi pichhli report "verified" bol gayi thi.
    """
    if source_count <= 0:
        return EVIDENCE_NONE
    if verification_ran is None:
        return EVIDENCE_NOT_CHECKED
    if verification_ran is False:
        return EVIDENCE_NOT_CHECKED
    usable = source_count if usable_source_count is None else usable_source_count
    if usable <= 0:
        return EVIDENCE_NONE
    supported = supported_claims or 0
    unsupported = unsupported_claims or 0
    if contradictions > 0 and supported > 0:
        return EVIDENCE_MIXED
    if supported <= 0:
        return EVIDENCE_WEAK
    # Counter-side dekhe bina "STRONG" kehna apne hi nateeje ki taraf jhukna hai.
    if counter_search is not True:
        return EVIDENCE_MODERATE if supported > unsupported else EVIDENCE_WEAK
    if usable >= 3 and supported >= 3 and unsupported <= supported // 3:
        return EVIDENCE_STRONG
    if supported > unsupported:
        return EVIDENCE_MODERATE
    return EVIDENCE_WEAK


# ── 4. novelty state ─────────────────────────────────────────────────────────
def novelty_state_of(hypotheses: Optional[Sequence[Dict]] = None) -> str:
    """
    App ke apne ideas ki sabse KAM daawe wali novelty haalat.

    Sabse kamzor status jeetta hai: ek hypothesis "POSSIBLY NOVEL" ho aur doosri
    "KNOWN IDEA", to poore run ko naya kehna galat hai. Aur jahan status hi nahi
    likha, wahan `NOVELTY UNVERIFIED` — khaali jagah ko "naya" nahi maanta.
    """
    items = [h for h in (hypotheses or []) if isinstance(h, dict)]
    if not items:
        return NOVELTY_UNVERIFIED
    found = [str(h.get("novelty_status") or "").strip() for h in items]
    found = [f for f in found if f in NOVELTY_STATES]
    if not found or len(found) < len(items):
        return NOVELTY_UNVERIFIED
    # NOVELTY_STATES ka kram jaan-boojh kar kamzor-se-mazboot nahi hai, isliye
    # "sabse kam daawa" ka apna kram yahan likha hai.
    weakest = (NOVELTY_UNVERIFIED, "REJECTED AS DUPLICATE", "KNOWN IDEA",
               "KNOWN VARIANT", "MINOR MODIFICATION", NOVELTY_POSSIBLE)
    for state in weakest:
        if state in found:
            return state
    return NOVELTY_UNVERIFIED

def prior_art_flag(hypotheses: Optional[Sequence[Dict]] = None) -> Optional[bool]:
    """
    Hypotheses ke apne record se: prior-art search chali thi ya nahi?

    Teen jawab, teen matlab — True (har hypothesis par chali), False (chali hi
    nahi), None (record hi nahi mila, yaani pata nahi). Conservative jaan-boojh
    kar hai: ek bhi hypothesis ka record na ho to poore run ko "chali thi" nahi
    kehte, warna novelty ka daawa bina saboot mazboot dikhne lagta.
    """
    items = [h for h in (hypotheses or []) if isinstance(h, dict)]
    if not items:
        return None
    flags: List[Optional[bool]] = []
    for item in items:
        record = item.get("novelty_search")
        if isinstance(record, dict) and "performed" in record:
            value = record.get("performed")
            flags.append(None if value is None else bool(value))
        else:
            flags.append(None)
    if flags and all(flag is True for flag in flags):
        return True
    if flags and all(flag is False for flag in flags):
        return False
    return None


# ── 5. conflicts ─────────────────────────────────────────────────────────────
# #155d ke do naam — ek jagah likhe hain taaki test aur UI dono yahin se padhein.
DELIVERABLE_ROW_TITLE = "Maanga hua deliverable"
DELIVERABLE_RULE_LINE = (
    "Ye chaar research state mein SHAAMIL NAHI hai: \"bana kar de diya\" ka "
    "matlab \"evidence mazboot hai\" nahi, aur \"evidence kam hai\" ka matlab "
    "\"jo banane ko kaha tha wo nahi bana\" nahi.")
COUNT_NOTE_TITLE = "Do ginti, do matlab"

# #155d — `deliverable_guard` apne state PREFIX ke saath bhejta hai
# (`DELIVERABLE_MISSING`), par is module ko wo guard import NAHI karna chahiye:
# guard `craft` ko import karta hai aur research_state sabse neeche ki layer hai.
# Isliye prefix yahan hata kar milaan hota hai, aur dono naam (`MISSING` aur
# `DELIVERABLE_MISSING`) chalte hain. Ye ek CONTRACT hai, andaaza nahi —
# `tests/test_deliverable_guard.py` guard ke ASLI constants se ise pin karta hai,
# taaki kal naam badle to test RED ho, ye check chup-chaap band na ho jaaye.
DELIVERABLE_PREFIX = "DELIVERABLE_"
UNDELIVERED_STATES = ("MISSING", "BLOCKED")


def deliverable_token(state) -> str:
    """`DELIVERABLE_MISSING` → `MISSING` (jo bhi aaye, waisa hi upper-case)."""
    token = str(state or "").strip().upper()
    if token.startswith(DELIVERABLE_PREFIX):
        token = token[len(DELIVERABLE_PREFIX):]
    return token


def undelivered(state) -> bool:
    """Maangi hui cheez jawab mein NAHI hai (MISSING/BLOCKED) — sirf ye do."""
    return deliverable_token(state) in UNDELIVERED_STATES


def deliverable_line(deliverable: Optional[Dict] = None) -> str:
    """`deliverable_guard` ke record se ek imaandaar row (na ho to khaali).

    Ye kuch tay nahi karta — sirf guard ne jo NAAPA hai use dikhata hai. Guard ka
    record na ho, ya usme "maanga hi nahi gaya" likha ho, to ye row chhapti hi
    nahi: bina maange "deliverable: nahi bana" likhna bhi ek jhooth hai.
    """
    rec = deliverable if isinstance(deliverable, dict) else {}
    if not rec or not rec.get("asked"):
        return ""
    state = deliverable_token(rec.get("state"))
    if not state:
        return ""
    why = str(rec.get("reason") or rec.get("note") or "")
    form = str(rec.get("form") or "")
    title = DELIVERABLE_ROW_TITLE + (f" ({form})" if form else "")
    return f"- {title}: **{state}**" + (f" — {why}" if why else "")


def count_note(counts: Optional[Dict] = None) -> str:
    """Kachche source vs seedhe kaam ke source — ek line mein farak.

    Kyun (2026-08-30, live song run): ek hi report mein `EVIDENCE NONE` aur "40
    sources use hue" saath chhapa. Dono sach the — 40 mile the, aur unme se
    sawaal ke seedhe kaam ka ek bhi nahi tha — par kahin ye ek line likhi nahi
    thi, isliye report apne aap se ulti lagti thi.

    Dono ginti ek jaisi ho, ya koi ginti na aayi ho, to line chhapti nahi.
    """
    data = counts if isinstance(counts, dict) else {}
    raw = data.get("raw_sources")
    direct = data.get("directly_relevant_sources")
    if raw is None or direct is None:
        return ""
    try:
        raw_n, direct_n = int(raw), int(direct)
    except (TypeError, ValueError):
        return ""
    if raw_n == direct_n:
        return ""
    return (f"{COUNT_NOTE_TITLE}: {raw_n} source DHOONDHE/utha kar padhe gaye, "
            f"par sawaal ke SEEDHE kaam ke inme se {direct_n} nikle. Neeche "
            f"evidence ki haalat is doosri ginti par tay hoti hai, pehli par "
            f"nahi — isliye 'itne source mile' aur 'evidence kam hai' dono ek "
            f"saath sach ho sakte hain.")


def detect_conflicts(job_status: str, answer_state: str, evidence_state: str,
                     novelty_state: str, *,
                     prior_art_search: Optional[bool] = None,
                     counter_search: Optional[bool] = None,
                     top_label: str = "",
                     deliverable: Optional[Dict] = None) -> List[str]:
    """
    Do state ek doosre se ulti baat kah rahi hon to use likh do.

    Ye "safai" nahi hai — koi state chup-chaap badli nahi jaati. Sirf ye kaha
    jaata hai ki ye combination bharosemand nahi hai, aur `verified_allowed`
    apne aap False ho jaata hai.
    """
    out: List[str] = []
    if job_status == JOB_FAILED and answer_state == ANSWER_COMPLETE:
        out.append("Job FAILED hai par jawab ko COMPLETE bataya gaya — "
                   "background kaam ka toot jaana jawab poora hone se ULTA hai.")
    if answer_state == ANSWER_COMPLETE and evidence_state == EVIDENCE_NOT_CHECKED:
        out.append("Jawab COMPLETE bataya gaya par evidence check hi nahi chala — "
                   "poora likh dena poora jaanch lena nahi hai.")
    if answer_state == ANSWER_COMPLETE and evidence_state == EVIDENCE_NONE:
        out.append("Jawab COMPLETE bataya gaya par kaam laayak ek bhi source nahi — "
                   "bina evidence 'poora jawab' nahi hota.")
    if evidence_state == EVIDENCE_STRONG and counter_search is not True:
        why = ("counter-side search nahi chali" if counter_search is False
               else "counter-side search ka koi record nahi hai")
        out.append(f"Evidence STRONG bataya gaya par {why} — sirf support-side "
                   "dekh kar 'strong' kehna apne hi nateeje ki taraf jhukna hai.")
    if novelty_state == NOVELTY_POSSIBLE and prior_art_search is not True:
        why = ("prior-art search nahi chali" if prior_art_search is False
               else "prior-art search ka koi record nahi hai")
        out.append(f"Novelty 'POSSIBLY NOVEL' bataya gaya par {why} — "
                   "na dhoondhna 'kuch nahi mila' nahi hai.")
    if novelty_state == NOVELTY_POSSIBLE and evidence_state in (
            EVIDENCE_NONE, EVIDENCE_NOT_CHECKED):
        out.append("App ke idea ko 'POSSIBLY NOVEL' kaha gaya jabki evidence ki "
                   "haalat " + evidence_state + " hai — dono ek saath nahi chal sakte.")
    label = str(top_label or "")
    if ("✅" in label or "VERIFIED" in label.replace("UNVERIFIED", "")) and \
            answer_state != ANSWER_COMPLETE:
        out.append(f"Top label '{label.strip()}' verified-jaisa hai par jawab "
                   f"{answer_state} hai — label jawab se aage nahi ja sakta.")
    # #155d — maangi hui cheez BANI hi nahi, par jawab "COMPLETE"? Ye asli
    # contradiction hai, aur ise dikhana hi is poore batch ka maqsad hai: pichhla
    # live run gaana gira kar bhi report ko bhara-bhara dikha gaya tha. State
    # yahan CHUP-CHAAP badalti nahi — sirf conflict likhta hai, jisse
    # `verified_allowed` apne aap False ho jaata hai.
    rec = deliverable if isinstance(deliverable, dict) else {}
    if rec.get("asked") and answer_state == ANSWER_COMPLETE:
        state = deliverable_token(rec.get("state"))
        if undelivered(state):
            why = str(rec.get("reason") or rec.get("note") or "").strip()
            out.append(
                "Jawab COMPLETE bataya gaya par jo cheez banane ko kaha gaya "
                f"tha wo jawab mein nahi hai (deliverable: {state})"
                + (f" — {why}" if why else "")
                + ". Research poori ho jaana maangi hui cheez ban jaana nahi hai.")
    return out


# ── ek jagah se poora state ──────────────────────────────────────────────────
def build_state(*, ledger: Optional[Dict] = None, answer_text: str = "",
                source_count: int = 0,
                usable_source_count: Optional[int] = None,
                verification_ran: Optional[bool] = None,
                supported_claims: Optional[int] = None,
                unsupported_claims: Optional[int] = None,
                contradictions: int = 0,
                counter_search: Optional[bool] = None,
                prior_art_search: Optional[bool] = None,
                hypotheses: Optional[Sequence[Dict]] = None,
                top_label: str = "",
                crashed: bool = False, recovered: bool = False,
                running: bool = False, queued: bool = False,
                finished: bool = True,
                deliverable: Optional[Dict] = None,
                raw_source_count: Optional[int] = None,
                directly_relevant_count: Optional[int] = None) -> ResearchState:
    """Chaaron state + conflicts ek hi jagah se — orchestrator isi ko bulata hai."""
    job = job_status_of(finished=finished, crashed=crashed, recovered=recovered,
                        running=running, queued=queued)
    answer = answer_state_of(ledger, answer_text=answer_text,
                             source_count=source_count)
    evidence = evidence_state_of(
        source_count=source_count, usable_source_count=usable_source_count,
        verification_ran=verification_ran, supported_claims=supported_claims,
        unsupported_claims=unsupported_claims, contradictions=contradictions,
        counter_search=counter_search)
    items = [h for h in (hypotheses or []) if isinstance(h, dict)]
    novelty = novelty_state_of(items)
    if prior_art_search is None:
        # Caller ne na bataya ho to hypotheses ke apne record se padh lo.
        prior_art_search = prior_art_flag(items)
    conflicts = detect_conflicts(job, answer, evidence, novelty,
                                 prior_art_search=prior_art_search,
                                 counter_search=counter_search,
                                 top_label=top_label,
                                 deliverable=deliverable)
    reasons = {
        "job_status": JOB_EXPLAIN.get(job, ""),
        "answer_state": ANSWER_EXPLAIN.get(answer, ""),
        "evidence_state": EVIDENCE_EXPLAIN.get(evidence, ""),
        "novelty_state": (NOVELTY_EXPLAIN.get(novelty)
                          or f"prior-art milaan ka natija: {novelty}"),
    }
    if not items:
        reasons["novelty_state"] = ("app ne is run mein koi apni hypothesis nahi "
                                   "banayi, isliye novelty ka sawaal hi nahi uthta")
    # #155d — dono ginti waisi hi rakhi jaati hain jaisi mili. Yahan kuch jodna,
    # ghatana ya "theek" karna mana hai: `count_note()` inhi do numbers se wajah
    # likhta hai, aur agar ek bhi number na aaya ho to wo line chhapti hi nahi
    # ("pata nahi" ko 0 likhna hi sabse purana jhooth tha).
    counts: Dict = {}
    if raw_source_count is not None:
        counts["raw_sources"] = int(raw_source_count)
    if directly_relevant_count is not None:
        counts["directly_relevant_sources"] = int(directly_relevant_count)
    if usable_source_count is not None:
        counts["usable_sources"] = int(usable_source_count)
    return ResearchState(job_status=job, answer_state=answer,
                         evidence_state=evidence, novelty_state=novelty,
                         novelty_applicable=bool(items), reasons=reasons,
                         conflicts=conflicts,
                         deliverable=dict(deliverable or {}),
                         counts=counts)


# ── audit block (report ke audit section ke andar chhapta hai) ───────────────
STATE_HEADING = "**Chaar alag haalat (ek doosre ka matlab nahi):**"
STATE_RULE_LINE = ("Job poora hona ≠ jawab poora hona ≠ evidence mazboot hona ≠ "
                   "idea naya hona. Chaaron alag se naapi jaati hain.")


def render_state_block(state) -> str:
    """
    §20 ka user-facing block. Chaar row, phir conflicts.

    Jaan-boojh kar chaaron row HAMESHA chhapti hain — chahe koi row "NOT CHECKED"
    ho. Jo check nahi hua, wo dikhna hi chahiye; chhupa dene se hi "sab theek
    hai" ka jhoota ehsaas banta tha.
    """
    data = state.to_dict() if hasattr(state, "to_dict") else dict(state or {})
    explain = data.get("explain") or {}
    reasons = data.get("reasons") or {}
    rows = (
        ("Background job", "job_status"),
        ("Jawab poora hua?", "answer_state"),
        ("Evidence ki haalat", "evidence_state"),
        ("App ke idea ki novelty", "novelty_state"),
    )
    lines = [STATE_HEADING, ""]
    for title, key in rows:
        value = str(data.get(key) or "")
        why = str(reasons.get(key) or explain.get(key) or "")
        lines.append(f"- {title}: **{value}**" + (f" — {why}" if why else ""))
    if not data.get("novelty_applicable", False):
        lines.append("  (novelty is run par laagu nahi — app ne koi apni "
                     "hypothesis nahi banayi)")
    lines.append("")
    lines.append(STATE_RULE_LINE)
    # #155d — do ginti ka farak. Ye chaar row ke NEECHE aata hai, unke andar
    # nahi: ye koi paanchvi state nahi, sirf ek wajah hai ki "itne source mile"
    # aur "evidence kam hai" dono ek saath kaise sach hain.
    note = count_note(data.get("counts"))
    if note:
        lines.append("")
        lines.append(note)
    # #155d — maangi hui cheez ki haalat. Alag block, alag niyam-line, taaki koi
    # ise chaar research state mein ginne ki galti na kare.
    row = deliverable_line(data.get("deliverable"))
    if row:
        lines.append("")
        lines.append(f"**{DELIVERABLE_ROW_TITLE} (alag baat hai):**")
        lines.append("")
        lines.append(row)
        lines.append("")
        lines.append(DELIVERABLE_RULE_LINE)
    conflicts = list(data.get("conflicts") or [])
    if conflicts:
        lines.append("")
        lines.append("**⚠️ State conflicts (inhe theek maan kar aage na badhein):**")
        lines.extend(f"- {c}" for c in conflicts)
        lines.append("")
        lines.append("Conflict hone par 'VERIFIED' jaisa top label allowed nahi hai.")
    return "\n".join(lines)


def state_warnings(state) -> List[str]:
    """Conflicts ko warning list ke liye taiyaar karta hai (UI banner ke liye)."""
    data = state.to_dict() if hasattr(state, "to_dict") else dict(state or {})
    return [f"§20 state conflict: {c}" for c in (data.get("conflicts") or [])]


def summary_line(state) -> str:
    """Ek line — log aur progress panel ke liye (raw error/secret kabhi nahi)."""
    data = state.to_dict() if hasattr(state, "to_dict") else dict(state or {})
    return (f"job={data.get('job_status')} | answer={data.get('answer_state')} | "
            f"evidence={data.get('evidence_state')} | "
            f"novelty={data.get('novelty_state')} | "
            f"conflicts={len(data.get('conflicts') or [])}")


def coerce(value) -> Optional[ResearchState]:
    """Dict ya ResearchState — dono se ResearchState banata hai (UI/tests ke liye)."""
    if isinstance(value, ResearchState):
        return value
    if not isinstance(value, dict) or not value:
        return None
    return ResearchState(
        job_status=str(value.get("job_status") or JOB_FINISHED),
        answer_state=str(value.get("answer_state") or ANSWER_PARTIAL),
        evidence_state=str(value.get("evidence_state") or EVIDENCE_NOT_CHECKED),
        novelty_state=str(value.get("novelty_state") or NOVELTY_UNVERIFIED),
        novelty_applicable=bool(value.get("novelty_applicable")),
        reasons=dict(value.get("reasons") or {}),
        conflicts=list(value.get("conflicts") or []),
        # #155d — dict se wapas banate waqt bhi ye dono saath aate hain, warna
        # UI/test round-trip par deliverable row aur ginti wali line gayab ho
        # jaati (aur gayab hona hi is batch ka asli bug tha).
        deliverable=dict(value.get("deliverable") or {}),
        counts=dict(value.get("counts") or {}),
    )


def inject_state_block(answer: str, state) -> str:
    """
    §20 block ko report ke audit section ke SHURU mein daal deta hai.

    Kyun audit ke andar aur kyun uske top par: chaar state "research quality"
    ki baat hain, user ke jawab ki nahi — par audit ke sabse neeche daal dene se
    ye technical dump ke saath dab jaata. Aur kyun baad mein inject: ye state
    contract ledger + quality counters ke FINAL numbers se banti hai, jo answer
    assemble hone ke baad hi pakke hote hain. Do jagah do ginti dikhne se
    bachne ke liye ek hi state object dono jagah jaata hai.

    Block do baar nahi lagta (idempotent), aur audit section na ho to block
    `## Sources` se pehle jaata hai — Sources hamesha aakhri section rehta hai.
    """
    from .answer_order import display_heading, section_start

    text = str(answer or "")
    block = render_state_block(state)
    if not text.strip():
        return block
    if STATE_HEADING in text:
        return text
    audit = section_start(text, "audit")
    if audit >= 0:
        line_end = text.find("\n", audit)
        if line_end < 0:
            return text.rstrip() + "\n\n" + block + "\n"
        head, rest = text[:line_end + 1], text[line_end + 1:]
        return head + "\n" + block + "\n" + rest.lstrip("\n")
    sources = text.find(f"## {display_heading('sources')}")
    if sources < 0:
        sources = section_start(text, "sources")
    if sources >= 0:
        return text[:sources] + block + "\n\n" + text[sources:]
    return text.rstrip() + "\n\n" + block + "\n"
