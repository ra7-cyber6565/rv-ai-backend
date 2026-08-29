"""SONG LAB — bane hue draft ko app KHUD teen-chaar tareeke se testta hai.

#141. Aaj tak ka haal ye tha: `craft.measure` ek hi baar poore draft par 20 naap
chalata hai, aur `craft.run_craft` ek baar dobara likhwa leta hai. Do kami thi:

1. Naap POORE draft par thi. "Kaunsi LINE kamzor hai" ka koi jawab nahi tha,
   isliye "kamzor ko hataao" ka koi imaandaar tareeka bhi nahi tha.
2. Naap EK pass thi. intel ki maang saaf hai: "khud ko 3-4 tarah se test kre
   phir de". Ek pass ko chaar naam de dena jhooth hota — isliye yahan chaar ALAG
   test hain, har ek ka apna tareeka aur apna nateeja.

Is file ka poora kaam OFFLINE hai: 0 Gemini call, 0 network, koi randomness
nahi. Dobara likhwane ka kaam `craft.py` ka hai (wahi ek bounded model call) —
yahan se koi model call nahi jaati. Isliye "line hatai gayi" ek naapa hua faisla
hai, kisi model ki raay nahi.

Teen jhooth yahan structurally mumkin nahi:
  * "dhun ban gayi / sun kar dekha" — koi audio, koi tune, kuch bhaja nahi gaya.
  * "TESTED_PASS matlab gaana achha hai" — test sirf dhaancha aur andar ki
    consistency dekhte hain; asli sunne wale ka test baaki hai.
  * "line chupke se hata di" — har hatai gayi line apni code + naapi hui wajah
    ke saath ledger me jaati hai, aur agar hatane se naap GIR jaaye to hatai
    hi nahi jaati.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import craft
from . import songcraft
from . import lang_bridge
from .lab import (DATA_MISSING, NOT_RUN, NOT_TESTABLE_HERE, TESTED_FAIL,
                  TESTED_PASS)
# Rollup ka kram lab se hi udhaar — "kaun sab par bhaari padta hai" ka faisla
# do jagah do tarah se nahi hona chahiye.
from .lab import _ROLLUP_ORDER as _LAB_ROLLUP_ORDER

# ── kya yahan HOTA HI NAHI (ye jhande kabhi True nahi hote) ──────────────────
AUDIO_GENERATED = False        # koi audio file nahi banti
TUNE_MADE = False              # koi dhun nahi banti
HEARD = False                  # kuch suna nahi gaya
SUNG = False                   # kuch gaaya nahi gaya
LISTENER_TESTED = False        # kisi asli sunne wale par test nahi hua
HUMAN_REACTION_TESTED = False  # "logon ko pasand aayega" naapa hi nahi gaya
NETWORK_USED = False
RANDOMNESS_USED = False
MODEL_WRITTEN_CODE_EXECUTED = False
GEMINI_CALLS = 0               # is stage me ek bhi model call nahi
DETERMINISTIC = True
PROVIDER_COST = "₹0"

# Ye do jhande ULTE hain — inhe True rehna chahiye, warna stage ka matlab khatam.
TESTED_PASS_IS_NOT_QUALITY = True   # pass hona "achha hai" ka saboot nahi
EVERY_DROP_HAS_A_MEASURED_REASON = True

CANNOT_MEASURE: Tuple[str, ...] = (
    "gaana sun kar kaisa lagega",
    "line hatane se gaana behtar HUA ya nahi (ye sirf naap me behtar hai)",
    "kaunsi line logon ko yaad reh jaayegi",
    "gaana hit hoga ya nahi",
)

LAB_DISCLAIMER = (
    "Ye test app ne KHUD apne andar chalaya hai — sirf dhaancha aur andar ki "
    "consistency, ₹0, bina internet, bina kuch sune. TESTED_PASS ka matlab "
    "\"gaana achha hai\" NAHI hai; asli sunne wale ka test abhi baaki hai."
)


# ── ek LINE ka nateeja ──────────────────────────────────────────────────────
# Teen haalat, aur inka farak jaan-boojh kar hai:
#   KEEP — is line par koi naapi hui shikayat nahi mili.
#   FIX  — line kamzor NAAP par hai (matra/ghisa-pita/script), par baat kaam ki
#          ho sakti hai. Aisi line HATAI NAHI JAATI — hatane se gaane ka matlab
#          chala jaata hai. Ye redraft ki note me jaati hai.
#   DROP — line ne NIYAM toda: aisa daawa jo naapa hi nahi ja sakta ("hit
#          hoga"), ya jo bhaav maanga gaya tha uska ULTA. Yahi line hat sakti
#          hai, aur wo bhi ledger + cap ke saath.
LINE_KEEP = "KEEP"
LINE_FIX = "FIX"
LINE_DROP = "DROP"
LINE_STATUSES: Tuple[str, ...] = (LINE_KEEP, LINE_FIX, LINE_DROP)

CODE_APPEAL_CLAIM = "line_appeal_claim"
CODE_MUSIC_CLAIM = "line_music_claim"
CODE_MOOD_CONFLICT = "line_mood_conflict"
CODE_MATRA_OUTLIER = "line_matra_outlier"
CODE_CLICHE = "line_cliche"
CODE_SCRIPT_OFF = "line_script_off"

# code → (kya karna hai, insaani wajah). Ye table hi "kyu hataya" ka jawab hai.
_CODE_TABLE: Tuple[Tuple[str, str, str], ...] = (
    (CODE_APPEAL_CLAIM, LINE_DROP,
     "is line me aisa daawa hai jo naapa hi nahi ja sakta (hit/viral/sabko "
     "pasand) — gaane ke andar aisa daawa likhna mana hai"),
    (CODE_MUSIC_CLAIM, LINE_DROP,
     "is line me music ki quality ka daawa hai (dhun achhi lagegi jaisa) — "
     "yahan koi dhun bani hi nahi, isliye ye daawa jhooth hai"),
    (CODE_MOOD_CONFLICT, LINE_DROP,
     "jo bhaav maanga gaya tha, is line me uska ULTA bhaav hai"),
    (CODE_MATRA_OUTLIER, LINE_FIX,
     "is line ki matra baaki line se bahut hat kar hai — gaate waqt ye line "
     "atakti hai (ye andaza hai, chhand ka saboot nahi)"),
    (CODE_CLICHE, LINE_FIX,
     "is line me ghisa-pita shabd hai (list ADHOORI hai, isliye 0 milna "
     "\"naya hai\" nahi hota)"),
    (CODE_SCRIPT_OFF, LINE_FIX,
     "ye line maangi hui script me nahi hai"),
)

CODE_ACTION: Dict[str, str] = {code: action for code, action, _r in _CODE_TABLE}
CODE_REASON: Dict[str, str] = {code: reason for code, _a, reason in _CODE_TABLE}
DROP_CODES: Tuple[str, ...] = tuple(code for code, action, _r in _CODE_TABLE
                                    if action == LINE_DROP)
FIX_CODES: Tuple[str, ...] = tuple(code for code, action, _r in _CODE_TABLE
                                   if action == LINE_FIX)


def _median(values: Sequence[float]) -> float:
    """Beech ka number. Median hi liya jaata hai — ek lambi line average ko
    kheench leti hai, median ko nahi."""
    clean = sorted(float(v) for v in values or [])
    if not clean:
        return 0.0
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def _opposite_moods(asked: Sequence[str]) -> List[str]:
    """Maange hue bhaav ke ULTE bhaav — songcraft ki ek hi table se."""
    out: List[str] = []
    for mood in asked or []:
        for other in songcraft.MOOD_OPPOSITES.get(str(mood), ()):  # ek hi sach
            if other not in out:
                out.append(other)
    return out


def line_rows(draft: str, spec: Any = None) -> List[Dict[str, Any]]:
    """
    Har LINE ka apna nateeja — number aur wajah ke saath.

    Yahan naya naap-ka-dimaag nahi banaya gaya: matra `craft.matra_of` se,
    ghise-pite shabd `craft.cliches_in` se, daawe `craft.appeal_claims_in` /
    `songcraft.music_claims_in` se, bhaav `craft.mood_hints` se aate hain. Do
    jagah alag hisaab = do alag sach, isliye sab udhaar liya gaya hai.

    Matra ka faisla MEDIAN se hota hai (poore draft ka), aur wo bhi tab jab
    matra ka rule bana ho. Roman (Hinglish) par matra approx hai — us haalat me
    row par `approx: True` jaata hai.
    """
    body = str(draft or "")
    lines = craft.lines_of(body)
    if not lines:
        return []
    rule = craft.matra_rule_for(body)
    per_line = [craft.matra_of(line, rule) for line in lines] if rule else []
    median = _median(per_line)
    approx = rule == craft.MATRA_RULE_ROMAN
    asked_moods = list(getattr(spec, "mood_asked", ()) or [])
    opposites = _opposite_moods(asked_moods)
    target_script = str(getattr(spec, "target_script", "") or "")
    refrain = craft.refrain_of(body)
    refrain_key = str(refrain.get("line") or "")

    rows: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        codes: List[str] = []
        found: Dict[str, Any] = {}
        matra = per_line[index] if index < len(per_line) else 0
        if rule and median and abs(matra - median) > songcraft.SING_OUTLIER_TOL:
            codes.append(CODE_MATRA_OUTLIER)
            found["matra"] = matra
            found["matra_median"] = median
        claims = craft.appeal_claims_in(line)
        if claims:
            codes.append(CODE_APPEAL_CLAIM)
            found["appeal_claims"] = list(claims)
        music_claims = songcraft.music_claims_in(line)
        if music_claims:
            codes.append(CODE_MUSIC_CLAIM)
            found["music_claims"] = list(music_claims)
        if opposites:
            hit = [mood for mood in craft.mood_hints(line) if mood in opposites]
            if hit:
                codes.append(CODE_MOOD_CONFLICT)
                found["opposite_moods"] = hit
        cliches = craft.cliches_in(line)
        if cliches:
            codes.append(CODE_CLICHE)
            found["cliches"] = list(cliches)
        if target_script:
            script = lang_bridge.dominant_script(line)
            if script not in ("unknown", target_script):
                codes.append(CODE_SCRIPT_OFF)
                found["script"] = script
        actions = {CODE_ACTION.get(code, LINE_FIX) for code in codes}
        status = (LINE_DROP if LINE_DROP in actions else
                  LINE_FIX if actions else LINE_KEEP)
        rows.append({
            "line_no": index + 1,
            "text": line,
            "status": status,
            "codes": codes,
            "measured": found,
            "matra": matra,
            "is_refrain": bool(refrain_key)
                          and craft._norm_line(line) == refrain_key,
            "reasons": [CODE_REASON[code] for code in codes],
            "approx": bool(approx and CODE_MATRA_OUTLIER in codes),
            # Ye do line har row ke saath jaati hain — naap "achhi line" ka
            # saboot nahi, aur sunne wale ka test yahan hua hi nahi.
            "quality_proven": False,
            "human_reaction_untested": True,
        })
    return rows


# ── kitni line hat SAKTI hai ─────────────────────────────────────────────────
# Teen deewar, teeno alag wajah se:
#   cap   — ek baar me poore gaane ka thoda hissa hi hat sakta hai, warna "saaf
#           kiya" ki jagah "kaat diya" ho jaata hai.
#   floor — hatane ke baad gaana itna chhota na ho jaaye ki gaana hi na bache.
#   refrain — mukhda/hook kabhi nahi hatta; wahi gaane ki reedh hai.
MAX_DROP_SHARE = 0.20
MAX_DROPS = 4
MIN_LINES_AFTER_DROP = songcraft.MIN_LINES_FOR_SING   # ek hi sach, apna nahi
REFRAIN_NEVER_DROPPED = True

DROP_REFUSED_REFRAIN = "refrain_line"
DROP_REFUSED_FLOOR = "line_floor"
DROP_REFUSED_EXACT_COUNT = "exact_line_count_asked"
DROP_REFUSED_CAP = "cap_reached"
DROP_REFUSED_MEASURE_WORSE = "measure_would_get_worse"

REFUSE_REASON: Dict[str, str] = {
    DROP_REFUSED_REFRAIN:
        "ye mukhda/hook hai (sabse zyada dohraayi gayi line) — ise hatane se "
        "gaana hi bikhar jaata hai, isliye ise sirf FIX ki note me daala hai",
    DROP_REFUSED_FLOOR:
        "hatane ke baad line itni kam bach jaati ki gaana hi na rahe",
    DROP_REFUSED_EXACT_COUNT:
        "user ne THEEK itni line maangi thi — ek line hata dene se maangi hui "
        "ginti toot jaati, isliye ise hataaya nahi, BADALNA padega",
    DROP_REFUSED_CAP:
        "ek baar me itni line nahi hataayi jaati — baaki line redraft ki note "
        "me jaati hain",
    DROP_REFUSED_MEASURE_WORSE:
        "hataane par POORE draft ki naap gir rahi thi (fail badh rahe the ya "
        "naap hi kam ho rahi thi) — isliye ek bhi line hataayi NAHI gayi",
}



def _drop_floor(spec: Any = None) -> int:
    """Kam se kam kitni line bachni chahiye — spec ki maang bhi shaamil."""
    floor = int(MIN_LINES_AFTER_DROP)
    for attr in ("min_lines", "line_target"):
        want = int(getattr(spec, attr, 0) or 0)
        if want > floor:
            floor = want
    return floor


def _drop_cap(total: int) -> int:
    """Ek baar me hatane ki chhat. Chhote draft par bhi 1 line ki gunjaish rehti
    hai — usse aage floor aur naap-guard rok lete hain."""
    if total <= 0:
        return 0
    return max(1, min(MAX_DROPS, int(total * MAX_DROP_SHARE)))


def drop_plan(draft: str, spec: Any = None,
              rows: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Kaunsi line hat sakti hai — aur jo nahi hat rahi, wo KYU nahi hat rahi.

    Ye faisla sirf `line_rows` ke DROP wale codes par hota hai. FIX wali line
    yahan chhui hi nahi jaati (matra/cliché/script) — wo redraft ki note me
    jaati hai, kyunki aisi line hatane se baat chali jaati hai.

    Har entry me line ka number, uska text, code aur naapi hui wajah jaati hai.
    "Chupke se hata di" is dhaanche me mumkin nahi.
    """
    line_list = list(rows if rows is not None else line_rows(draft, spec))
    total = len(line_list)
    floor = _drop_floor(spec)
    exact = int(getattr(spec, "line_target", 0) or 0)
    cap = _drop_cap(total)
    dropped: List[Dict[str, Any]] = []
    refused: List[Dict[str, Any]] = []
    kept = total

    for row in line_list:
        if row.get("status") != LINE_DROP:
            continue
        codes = [code for code in row.get("codes", ()) if code in DROP_CODES]
        entry = {
            "line_no": row.get("line_no"),
            "text": row.get("text", ""),
            "codes": codes,
            "measured": dict(row.get("measured") or {}),
            "reasons": [CODE_REASON[code] for code in codes],
        }
        if REFRAIN_NEVER_DROPPED and row.get("is_refrain"):
            entry["refused"] = DROP_REFUSED_REFRAIN
        elif kept - 1 < floor:
            # Do alag wajah, do alag naam: "theek itni line maangi thi" aur
            # "gaana hi na bache". Dono ko ek naam dena padhne wale ko dhoka
            # dena hoga — pehli wali me line BADALNI hai, doosri me bachani.
            entry["refused"] = (DROP_REFUSED_EXACT_COUNT
                                if exact and floor == exact
                                else DROP_REFUSED_FLOOR)
            entry["floor"] = floor
        elif len(dropped) >= cap:
            entry["refused"] = DROP_REFUSED_CAP
            entry["cap"] = cap
        else:
            dropped.append(entry)
            kept -= 1
            continue
        entry["refused_reason"] = REFUSE_REASON[entry["refused"]]
        refused.append(entry)

    return {
        "total_lines": total,
        "cap": cap,
        "floor": floor,
        "dropped": dropped,
        "refused": refused,
        "drop_line_nos": [int(e["line_no"]) for e in dropped],
        "lines_after": kept,
        # Ye jhande drop-plan ke saath hi chalte hain — "hataya" ka matlab
        # "gaana behtar ho gaya" kabhi nahi.
        "every_drop_has_a_measured_reason": EVERY_DROP_HAS_A_MEASURED_REASON,
        "improvement_proven": False,
    }


def clean_draft(draft: str, drop_line_nos: Sequence[int]) -> str:
    """
    Bataayi hui line hata kar draft dobara jodo — antare ke khaali line bache
    rahen.

    Ginti `craft.lines_of` jaise hi hoti hai (khaali line ginti me nahi aati),
    warna number kisi doosri line par lag jaate. Text RAW rakha jaata hai
    (bullet ka nishaan waapas nahi likha jaata) — hum hata rahe hain, likh nahi
    rahe.
    """
    drops = {int(n) for n in drop_line_nos or ()}
    if not drops:
        return str(draft or "")
    out: List[str] = []
    seen = 0
    for raw in str(draft or "").splitlines():
        if craft._BULLET_RE.sub("", raw).strip():
            seen += 1
            if seen in drops:
                continue
            out.append(raw)
            continue
        # Ek antara poora hat jaane par do khaali line saath nahi rehni chahiye
        if out and out[-1].strip():
            out.append("")
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _drop_is_not_worse(after: Optional[Dict[str, Any]],
                       before: Optional[Dict[str, Any]]) -> bool:
    """
    Line hatane ke baad NAAP giri to nahi?

    `craft._revision_is_better` naye draft se "sakht behtar" maangta hai —
    wahan sahi hai, kyunki wahan model ne dobara likha tha. Yahan maang alag
    hai: line isliye hat rahi hai ki usne NIYAM toda tha, isliye barabari bhi
    manzoor hai. Par giravat kabhi manzoor nahi — na fail badhein, na naap khud
    kam ho jaaye (chhota draft = kuch check naapne laayak hi nahi bachte, aur
    fail ki ginti apne aap gir jaati hai; wo "behtar" nahi, chhup jaana hai).

    Hisaab craft ke apne `_score` / `_unmeasured_count` se hota hai — do jagah
    do tarah ka score nahi.
    """
    if not after:
        return False
    if after.get("status") not in (craft.DRAFT_OK, craft.DRAFT_WEAK,
                                   craft.DRAFT_UNMEASURED):
        return False
    if craft._unmeasured_count(after) > craft._unmeasured_count(before):
        return False
    return craft._score(after) <= craft._score(before)


def apply_drops(draft: str, spec: Any = None, study: Any = None,
                context: str = "",
                rows: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Plan bana, line hataa, phir POORE draft ko dobara naapo — aur agar naap
    giri to hataana WAAPAS le lo.

    Yahi wo jagah hai jahan "kyu nikaal rahe ho, kya saboot hai" ka jawab
    number me milta hai: pehle ki ginti, baad ki ginti, aur faisla. Naap gir
    rahi ho to ek bhi line nahi hatti aur wajah ledger me chali jaati hai.
    """
    body = str(draft or "")
    plan = drop_plan(body, spec, rows=rows)
    before = craft.measure(body, spec, study=study, context=context)
    result: Dict[str, Any] = {
        "ran": True,
        "applied": False,
        "draft": body,
        "before_counts": dict((before or {}).get("counts") or {}),
        "after_counts": {},
        "plan": plan,
        "dropped": [],
        "refused": list(plan["refused"]),
        "note": "",
    }
    if not plan["dropped"]:
        # Yahan do haalat bilkul alag hain aur inhe mila dena jhooth hoga:
        # "kisi ne niyam nahi toda" vs "toda tha par hataaya nahi ja saka".
        result["note"] = (
            "kisi line ne niyam nahi toda — isliye ek bhi line hataayi nahi "
            "gayi" if not plan["refused"] else
            f"{len(plan['refused'])} line niyam tod rahi thi par hataayi nahi "
            f"ja saki (har ek ki wajah likhi hui hai) — wo redraft ki note me "
            f"gayi hai")
        return result

    cleaned = clean_draft(body, plan["drop_line_nos"])
    after = craft.measure(cleaned, spec, study=study, context=context)
    result["after_counts"] = dict((after or {}).get("counts") or {})
    if not _drop_is_not_worse(after, before):
        for entry in plan["dropped"]:
            blocked = dict(entry)
            blocked["refused"] = DROP_REFUSED_MEASURE_WORSE
            blocked["refused_reason"] = REFUSE_REASON[DROP_REFUSED_MEASURE_WORSE]
            result["refused"].append(blocked)
        result["note"] = ("hataane par naap gir rahi thi — draft jaisa tha "
                          "waisa hi rakha gaya")
        return result

    result["applied"] = True
    result["draft"] = cleaned
    result["dropped"] = list(plan["dropped"])
    result["note"] = (f"{len(plan['dropped'])} line hataayi gayi; poore draft "
                      f"ki naap giri nahi (ye \"gaana behtar ho gaya\" ka "
                      f"saboot NAHI hai)")
    return result


# ── CHAAR ALAG TEST ─────────────────────────────────────────────────────────
# "Chaar tarah se test kiya" ka matlab chaar NAAM nahi hota. Isliye har test ka
# `method` alag likha hua hai, aur chaaron alag cheez par chalte hain:
#   1. dhaancha  — text ko dobara gin kar craft ki ginti se milaan (andar ki
#                  consistency; do hisaab aapas me na milen to FAIL)
#   2. bhaav-arc — antara-dar-antara bhaav ka phailav + ulta bhaav
#   3. hook      — dohraav ki ginti + wo pehli baar kahan aaya
#   4. convention— PADHI HUI source ke asli number se milaan (kuch padha hi
#                  nahi to DATA_MISSING — yahi test study lane ko daant deta hai)
TEST_STRUCTURE = "structure_recount"
TEST_MOOD_ARC = "mood_arc_across_stanzas"
TEST_HOOK = "hook_returns_and_lands_early"
TEST_CONVENTION = "matches_read_conventions"
TEST_NAMES: Tuple[str, ...] = (TEST_STRUCTURE, TEST_MOOD_ARC, TEST_HOOK,
                               TEST_CONVENTION)

TEST_METHOD: Dict[str, str] = {
    TEST_STRUCTURE: "raw text se dobara ginti, phir craft ki ginti se milaan",
    TEST_MOOD_ARC: "har antare ka bhaav alag se, phir share aur ulta bhaav",
    TEST_HOOK: "sabse zyada dohraayi line ki ginti + pehli baar ki jagah",
    TEST_CONVENTION: "padhi hui source ke asli number se draft ka milaan",
}

HOOK_MIN_TIMES = 2        # ek baar aayi line "wapas aana" nahi hai
HOOK_MAX_POSITION = 0.5   # hook pehle aadhe hisse me shuru ho

# Bhaav ke shabd ki list (craft.MOODS) poori duniya ki zubaan nahi hai. Jab
# maange hue bhaav ka ek bhi shabd draft me na mile, hum "bhaav nahi hai" aur
# "hamari list me shabd nahi hai" me farq nahi kar sakte — is haalat me FAIL
# likhna over-claim hai, isliye status DATA_MISSING jaata hai. Ulta bhaav milna
# iske ulat POSITIVE khoj hai (shabd maujood hai), wo FAIL hi rehta hai.
MOOD_ZERO_CUE_IS_NOT_A_FAIL = True


def _test_row(name: str, status: str, observed: Any = "", expected: Any = "",
              reason: str = "", measured: Optional[Dict[str, Any]] = None
              ) -> Dict[str, Any]:
    return {
        "test": name,
        "status": status,
        "method": TEST_METHOD.get(name, ""),
        "observed": observed,
        "expected": expected,
        "reason": reason,
        "measured": dict(measured or {}),
        # Har row ke saath ye sach jaata hai — pass hona quality nahi hai.
        "quality_proven": False,
        "heard": HEARD,
        "human_reaction_tested": HUMAN_REACTION_TESTED,
    }


def _recount(draft: str) -> Tuple[int, int]:
    """Line aur antare ki GINTI, apne aap se — craft ke facts ko dekhe bina.

    Poora matlab isi me hai: agar ye ginti `craft.draft_facts` se na mile to
    kahin ek hisaab galat hai, aur us haalat me chup rehna sabse bada jhooth
    hota. Isliye milaan na hone par test FAIL hota hai.

    "Line kya hai" ki PARIBHASHA craft se hi li gayi hai (bullet ka nishaan
    hata kar khaali bachne wali line line nahi hoti) — warna sirf paribhasha ke
    farak se jhootha FAIL aata. GINTI ka tareeqa apna hai, wahi naapa ja raha
    hai.
    """
    lines = 0
    stanzas = 0
    inside = False
    for raw in str(draft or "").splitlines():
        if craft._BULLET_RE.sub("", raw).strip():
            lines += 1
            if not inside:
                stanzas += 1
                inside = True
        else:
            inside = False
    return lines, stanzas


def test_structure(draft: str, spec: Any = None) -> Dict[str, Any]:
    """Test 1 — dhaancha: dobara ginti + spec ki maang."""
    body = str(draft or "").strip()
    if not body:
        return _test_row(TEST_STRUCTURE, DATA_MISSING,
                         reason="draft hi nahi mila, isliye ginti hi nahi hui")
    lines, stanzas = _recount(body)
    facts = craft.draft_facts(body)
    measured = {"lines": lines, "stanzas": stanzas,
                "craft_lines": facts.get("line_count"),
                "craft_stanzas": facts.get("stanza_count")}
    if (lines != facts.get("line_count")
            or stanzas != facts.get("stanza_count")):
        return _test_row(
            TEST_STRUCTURE, TESTED_FAIL, observed=measured,
            expected="dono ginti ek jaisi",
            reason="app ke andar do jagah ki ginti aapas me nahi mil rahi — "
                   "aisi haalat me kisi bhi naap par bharosa nahi kiya ja "
                   "sakta",
            measured=measured)
    problems: List[str] = []
    want_lines = int(getattr(spec, "line_target", 0) or 0)
    want_min = int(getattr(spec, "min_lines", 0) or 0)
    want_stanzas = int(getattr(spec, "stanza_target", 0) or 0)
    if want_lines and lines != want_lines:
        problems.append(f"{want_lines} line maangi thi, {lines} hain")
    if want_min and lines < want_min:
        problems.append(f"kam se kam {want_min} line chahiye thi, {lines} hain")
    if want_stanzas and stanzas != want_stanzas:
        problems.append(f"{want_stanzas} antara maanga tha, {stanzas} hain")
    if problems:
        return _test_row(TEST_STRUCTURE, TESTED_FAIL, observed=measured,
                         expected={"line_target": want_lines,
                                   "min_lines": want_min,
                                   "stanza_target": want_stanzas},
                         reason="; ".join(problems), measured=measured)
    return _test_row(TEST_STRUCTURE, TESTED_PASS, observed=measured,
                     expected="ginti aapas me mile aur maang par ho",
                     reason="dono ginti ek jaisi hain aur maangi hui ginti "
                            "poori hai (ye likhawat achhi hone ka saboot nahi)",
                     measured=measured)


def test_mood_arc(draft: str, spec: Any = None) -> Dict[str, Any]:
    """
    Test 2 — bhaav ka arc: maanga hua bhaav kitne antare me hai, aur kahin uska
    ULTA to nahi.

    Ye poore draft ki mood-ginti se alag cheez hai: ek antare me "dukh" ke
    paanch shabd bhar dene se poora gaana sad nahi ho jaata. Isliye ginti
    ANTARE par hoti hai, aur share `songcraft.MIN_MOOD_STANZA_SHARE` se naapa
    jaata hai (wahi ek sach, apna doosra number nahi).
    """
    body = str(draft or "").strip()
    if not body:
        return _test_row(TEST_MOOD_ARC, DATA_MISSING,
                         reason="draft hi nahi mila")
    asked = [str(m) for m in (getattr(spec, "mood_asked", ()) or [])]
    # #149: padhi hui source se seekhe bhaav SIRF "maanga bhaav mila" ginne me
    # jodte hain. `opposites` neeche curated `asked` se hi banta hai — warna ek
    # seekha hua shabd is test ko TESTED_FAIL bana deta, aur us fail se line
    # hataane ki wajah ban jaati. Seekhe shabd par wo haq nahi hai.
    learned_asked = [str(m) for m in
                     (getattr(spec, "mood_asked_learned", ()) or [])
                     if str(m) not in asked]
    learned_pairs = [list(pair) for pair in
                     (getattr(spec, "mood_learned", ()) or [])]
    asked_all = asked + learned_asked
    if not asked_all:
        return _test_row(TEST_MOOD_ARC, NOT_TESTABLE_HERE,
                         reason="user ne kisi bhaav ka naam hi nahi liya — "
                                "isliye \"bhaav sahi hai\" naapa nahi ja sakta")
    stanzas = craft.stanzas_of(body)
    if not stanzas:
        return _test_row(TEST_MOOD_ARC, DATA_MISSING,
                         reason="antare bane hi nahi")
    opposites = _opposite_moods(asked)
    hits = 0
    conflicts: List[Dict[str, Any]] = []
    arc: List[Dict[str, Any]] = []
    for index, stanza in enumerate(stanzas):
        block = "\n".join(stanza)
        moods = craft.mood_hints(block)
        wide = craft.mood_hints(block, learned=learned_pairs)
        on = [mood for mood in asked_all if mood in wide]
        against = [mood for mood in moods if mood in opposites]
        if on:
            hits += 1
        if against:
            conflicts.append({"stanza": index + 1, "opposite_moods": against})
        arc.append({"stanza": index + 1, "moods": moods, "asked_present": on,
                    "opposite_present": against,
                    "moods_wide": wide})
    share = round(hits / len(stanzas), 4)
    measured = {"stanzas": len(stanzas), "stanzas_with_asked_mood": hits,
                "share": share, "asked": asked_all, "opposites": opposites,
                "arc": arc, "conflicts": conflicts,
                # Seekhe shabd alag se dikhte hain, taaki koi ye na samjhe ki
                # curated list badal di gayi.
                "asked_curated": asked,
                "asked_learned": learned_asked,
                "learned_cue_can_drop_a_line": False,
                # Shabd dikhna bhaav aa jaana nahi hai — ye sach saath chalta hai.
                "mood_list_is_not_exhaustive": craft.MOOD_LIST_IS_NOT_EXHAUSTIVE}
    expected = {"min_share": songcraft.MIN_MOOD_STANZA_SHARE,
                "opposite_moods_allowed": 0}
    if conflicts:
        return _test_row(TEST_MOOD_ARC, TESTED_FAIL, observed=measured,
                         expected=expected,
                         reason=f"{len(conflicts)} antare me maange hue bhaav "
                                f"ka ULTA bhaav hai",
                         measured=measured)
    if hits == 0 and MOOD_ZERO_CUE_IS_NOT_A_FAIL:
        # Poore draft me maange hue bhaav ka EK BHI shabd nahi mila. Do bilkul
        # alag baatein yahan ek jaisi dikhti hain: (a) gaana asli me us bhaav ka
        # nahi hai, (b) gaana us bhaav ka hai par shabd hamari list me nahi hai
        # ("rota raha" list ke "dukh" variants me nahi hai). Inme farq karne ka
        # koi naap hamare paas nahi hai, isliye "FAIL" likhna khud ek jhooth
        # hoga. Jab kam se kam ek antare me shabd mila ho, tab PHAILAV naapa ja
        # sakta hai — kyunki shabd draft ki apni zubaan me maujood hai.
        return _test_row(TEST_MOOD_ARC, DATA_MISSING, observed=measured,
                         expected=expected,
                         reason="maange hue bhaav ka koi shabd poore draft me "
                                "nahi mila; shabd-list adhoori hai, isliye "
                                "\"bhaav nahi hai\" kehna galat hoga — ye naapa "
                                "hi nahi ja saka",
                         measured=measured)
    if share < songcraft.MIN_MOOD_STANZA_SHARE:
        return _test_row(TEST_MOOD_ARC, TESTED_FAIL, observed=measured,
                         expected=expected,
                         reason=f"maanga hua bhaav sirf {hits}/{len(stanzas)} "
                                f"antare me dikha (chahiye tha kam se kam "
                                f"{songcraft.MIN_MOOD_STANZA_SHARE:.0%})",
                         measured=measured)
    return _test_row(TEST_MOOD_ARC, TESTED_PASS, observed=measured,
                     expected=expected,
                     reason="bhaav poore gaane me phaila hai aur kahin ulta "
                            "bhaav nahi mila (shabd se naapa gaya hai, dil se "
                            "nahi)",
                     measured=measured)


def test_hook(draft: str, spec: Any = None) -> Dict[str, Any]:
    """
    Test 3 — hook: sabse zyada dohraayi gayi line kitni baar aayi, aur pehli
    baar kahan.

    Do cheez naapi jaati hain aur dono JAGAH/GINTI ki hain: "hook pakdega ya
    nahi" yahan naapa hi nahi ja sakta (`CANNOT_MEASURE` me likha hai). Jab
    hook maanga hi na gaya ho to test NOT_TESTABLE_HERE rehta hai — us haalat me
    pass likhna muft ka pass hota.
    """
    body = str(draft or "").strip()
    if not body:
        return _test_row(TEST_HOOK, DATA_MISSING, reason="draft hi nahi mila")
    if not bool(getattr(spec, "hook_required", False)):
        return _test_row(TEST_HOOK, NOT_TESTABLE_HERE,
                         reason="is farmaish me hook/mukhda maanga hi nahi "
                                "gaya tha")
    refrain = craft.refrain_of(body)
    total = int(refrain.get("total_lines") or 0)
    if total < HOOK_MIN_TIMES:
        return _test_row(TEST_HOOK, DATA_MISSING,
                         reason="itni line hi nahi hain ki dohraav dekha ja "
                                "sake")
    times = int(refrain.get("times") or 0)
    position = float(refrain.get("position") or 0.0)
    measured = {"refrain_line": refrain.get("line", ""), "times": times,
                "position": position, "total_lines": total}
    expected = {"min_times": HOOK_MIN_TIMES,
                "max_position": HOOK_MAX_POSITION}
    problems: List[str] = []
    if times < HOOK_MIN_TIMES:
        problems.append(f"koi line dohraayi hi nahi gayi (sabse zyada {times} "
                        f"baar) — hook wapas aana chahiye")
    elif position > HOOK_MAX_POSITION:
        problems.append(f"hook pehli baar gaane ke {position:.0%} par aaya — "
                        f"itni der me aane wali line hook ka kaam nahi karti")
    if problems:
        return _test_row(TEST_HOOK, TESTED_FAIL, observed=measured,
                         expected=expected, reason="; ".join(problems),
                         measured=measured)
    return _test_row(TEST_HOOK, TESTED_PASS, observed=measured,
                     expected=expected,
                     reason=f"hook {times} baar aata hai aur pehli baar "
                            f"{position:.0%} par — ye sirf JAGAH aur GINTI ka "
                            f"naap hai, \"hook pakdega\" ka nahi",
                     measured=measured)


def _study_block(study: Any) -> Dict[str, Any]:
    """`songcraft.study(...)` ya seedha guidance — dono chalte hain."""
    if isinstance(study, dict):
        inner = study.get("guidance")
        if isinstance(inner, dict):
            return inner
        return study
    inner = getattr(study, "guidance", None)
    if isinstance(inner, dict):
        return inner
    return {}


# Test 4 ka bar craft ke `style_fit_structure` se JAAN-BOOJH KAR sakht hai, aur
# dono saath chalte hain (ek doosre ki jagah nahi lete):
#   craft  — "kisi EK band me wo ginti mil gayi" par MET (draft-level flag)
#   songlab— "SAARE band us ginti par hain" par PASS (LAB-level nateeja)
# hook ki ginti dono jagah ek hi tarah naapi jaati hai (>= padha hua number) —
# usme sakht/naram ka sawaal hi nahi.
STRICTER_THAN_STYLE_FIT = True
REPLACES_STYLE_FIT_CHECK = False


def test_conventions(draft: str, spec: Any = None,
                     study: Any = None) -> Dict[str, Any]:
    """
    Test 4 — padhi hui source ke ASLI NUMBER se milaan.

    Yahi test study lane ko daant deta hai: agar craft/music/listener me se
    kisi ne kuch PADHA hi nahi, to yahan `DATA_MISSING` aata hai — "sab theek
    hai" nahi. Number kabhi khud se nahi ghada jaata; jo record source se aaya
    uska `source_id` saath chalta hai.
    """
    body = str(draft or "").strip()
    if not body:
        return _test_row(TEST_CONVENTION, DATA_MISSING,
                         reason="draft hi nahi mila")
    block = _study_block(study)
    conventions = list(block.get("numeric_conventions") or [])
    read_sources = int(block.get("guidance_source_count") or 0)
    if not conventions:
        return _test_row(
            TEST_CONVENTION, DATA_MISSING,
            observed={"guidance_source_count": read_sources},
            expected="kam se kam ek padha hua number",
            reason=("style/craft ke baare me koi source padhi hi nahi gayi, "
                    "isliye kis convention se milaayen — pata nahi"
                    if not read_sources else
                    "source padhi gayi par usme koi asli number (kitni line ka "
                    "band, hook kitni baar) nahi mila"),
            measured={"conventions": [], "sources_read": read_sources})
    stanza_counts = [len(stanza) for stanza in craft.stanzas_of(body)]
    refrain_times = int((craft.refrain_of(body).get("times") or 0))
    verdicts: List[Dict[str, Any]] = []
    failed: List[str] = []
    for record in conventions:
        kind = str(record.get("kind") or "")
        value = int(record.get("value") or 0)
        tag = str(record.get("source_id") or "")
        if kind == "lines_per_stanza":
            hit = bool(stanza_counts) and all(n == value for n in stanza_counts)
            verdicts.append({"kind": kind, "value": value, "source_id": tag,
                             "observed": stanza_counts, "matched": hit,
                             "bar": "saare band"})
            if not hit:
                failed.append(f"[{tag}] har band {value} line ka nahi hai "
                              f"(mile: {stanza_counts})")
        elif kind == "refrain_times":
            hit = refrain_times >= value
            verdicts.append({"kind": kind, "value": value, "source_id": tag,
                             "observed": refrain_times, "matched": hit,
                             "bar": ">= padha hua number"})
            if not hit:
                failed.append(f"[{tag}] hook {value} baar chahiye tha, "
                              f"{refrain_times} baar aaya")
    measured = {"conventions": verdicts, "sources_read": read_sources,
                "stanza_line_counts": stanza_counts,
                "refrain_times": refrain_times,
                "stricter_than_style_fit": STRICTER_THAN_STYLE_FIT,
                "replaces_style_fit_check": REPLACES_STYLE_FIT_CHECK}
    if not verdicts:
        return _test_row(TEST_CONVENTION, DATA_MISSING, observed=measured,
                         reason="padhe hue number ka kism samajh nahi aaya — "
                                "milaan chalaya hi nahi gaya",
                         measured=measured)
    if failed:
        return _test_row(TEST_CONVENTION, TESTED_FAIL, observed=measured,
                         expected="padhi hui source ke number",
                         reason="; ".join(failed), measured=measured)
    return _test_row(TEST_CONVENTION, TESTED_PASS, observed=measured,
                     expected="padhi hui source ke number",
                     reason="draft padhi hui convention par poora utar raha "
                            "hai (convention SOURCE-REPORTED hai — apni salaah "
                            "nahi)",
                     measured=measured)


# ── sab mila kar ek nateeja ──────────────────────────────────────────────────
_STATUS_REASON: Dict[str, str] = {
    TESTED_FAIL: "chaar test me se kam se kam ek FAIL hua",
    TESTED_PASS: "jitne test chal paaye, sab pass hue (asli sunne wale ka test "
                 "abhi baaki hai)",
    DATA_MISSING: "koi test isliye nahi chal paaya ki naapne ki cheez hi nahi "
                  "mili",
    NOT_TESTABLE_HERE: "in test me se koi bhi is farmaish par lag hi nahi "
                       "sakta tha",
    NOT_RUN: "SONG LAB chalaya hi nahi gaya",
}


def rollup(rows: Sequence[Dict[str, Any]]) -> str:
    """Chaar test ka ek nateeja. Ek FAIL sab par bhaari padta hai (lab jaisa)."""
    present = {str(row.get("status") or "") for row in rows or ()}
    for status in _LAB_ROLLUP_ORDER:
        if status in present:
            return status
    return NOT_RUN


def redraft_notes(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Dobara likhwane ke liye note — FIX wali line, aur wo DROP jo hui hi nahi.

    Hataayi hui line yahan nahi aati (wo ja chuki hai). Jo line naap par kamzor
    thi par hatai nahi ja sakti thi, uska poora hisaab yahin se model tak
    pahunchta hai — isliye "chupke se ignore" mumkin nahi.
    """
    out: List[str] = []
    data = report or {}
    for row in data.get("line_rows") or []:
        if row.get("status") != LINE_FIX:
            continue
        why = "; ".join(row.get("reasons") or [])
        out.append(f"Line {row.get('line_no')} theek karo — {why}: "
                   f"\"{row.get('text', '')}\"")
    for entry in (data.get("drop") or {}).get("refused") or []:
        out.append(f"Line {entry.get('line_no')} niyam tod rahi hai par hatai "
                   f"nahi ja saki ({entry.get('refused_reason', '')}) — ise "
                   f"khud badal kar likho: \"{entry.get('text', '')}\"")
    for row in data.get("tests") or []:
        if row.get("status") == TESTED_FAIL:
            out.append(f"Test \"{row.get('test')}\" fail hua — "
                       f"{row.get('reason', '')}")
    return out


def policy() -> Dict[str, Any]:
    """Is stage ka likha hua kanoon — report me jaata hai, badalta nahi."""
    return {
        "stage": "song_lab",
        "audio_generated": AUDIO_GENERATED,
        "tune_made": TUNE_MADE,
        "heard": HEARD,
        "sung": SUNG,
        "listener_tested": LISTENER_TESTED,
        "human_reaction_tested": HUMAN_REACTION_TESTED,
        "network_used": NETWORK_USED,
        "randomness_used": RANDOMNESS_USED,
        "model_written_code_executed": MODEL_WRITTEN_CODE_EXECUTED,
        "gemini_calls": GEMINI_CALLS,
        "deterministic": DETERMINISTIC,
        "provider_cost": PROVIDER_COST,
        "tested_pass_is_not_quality": TESTED_PASS_IS_NOT_QUALITY,
        "every_drop_has_a_measured_reason": EVERY_DROP_HAS_A_MEASURED_REASON,
        "replaces_style_fit_check": REPLACES_STYLE_FIT_CHECK,
        "max_drop_share": MAX_DROP_SHARE,
        "max_drops": MAX_DROPS,
        "min_lines_after_drop": MIN_LINES_AFTER_DROP,
        "refrain_never_dropped": REFRAIN_NEVER_DROPPED,
        "tests": list(TEST_NAMES),
        "measured_by": "offline_rules_in_songlab_py",
    }


def not_run(reason: str = "") -> Dict[str, Any]:
    """SONG LAB nahi chala — aur KYU nahi chala, ye saaf likha hua."""
    return {
        "ran": False,
        "status": NOT_RUN,
        "status_reason": _STATUS_REASON[NOT_RUN],
        "reason": reason or "farmaish gaane ki nahi thi",
        "draft_in": "",
        "draft_out": "",
        "line_rows": [],
        "drop": {},
        "tests": [],
        "redraft_notes": [],
        "counts": {status: 0 for status in
                   (TESTED_PASS, TESTED_FAIL, DATA_MISSING, NOT_TESTABLE_HERE)},
        "policy": policy(),
        "cannot_measure": list(CANNOT_MEASURE),
        "disclaimer": LAB_DISCLAIMER,
        "limits": list(limits()),
    }


def run_song_lab(draft: str, spec: Any = None, study: Any = None,
                 context: str = "") -> Dict[str, Any]:
    """
    SONG LAB — ek hi jagah se: line ka naap, naapi hui hataai, chaar test.

    Kram jaan-boojh kar yahi hai: pehle line-dar-line naap, phir hataana (jo
    khud dobara naap kar rukta hai), aur test us draft par jo SACH ME diya
    jaayega. Ulta karne se "test pass wale draft" aur "diye gaye draft" alag ho
    jaate — yahi wo jhooth hai jo yahan mumkin nahi.

    Gaane ke alawa kisi form par ye stage chalta hi nahi (`NOT_RUN`) — dusri
    likhawat par ye naap galat hote.
    """
    body = str(draft or "").strip()
    if spec is None:
        return not_run("spec hi nahi bani — CRAFT chala hi nahi")
    if str(getattr(spec, "form", "") or "") != songcraft.SONG_FORM:
        return not_run(f"farmaish gaane ki nahi thi "
                       f"(form: {getattr(spec, 'form', '') or 'pata nahi'})")
    if not body:
        return not_run("draft hi nahi mila — naapne ke liye kuch nahi tha")

    rows = line_rows(body, spec)
    drop = apply_drops(body, spec, study=study, context=context, rows=rows)
    final = str(drop.get("draft") or body)
    tests = [
        test_structure(final, spec),
        test_mood_arc(final, spec),
        test_hook(final, spec),
        test_conventions(final, spec, study=study),
    ]
    status = rollup(tests)
    counts = {name: sum(1 for row in tests if row.get("status") == name)
              for name in (TESTED_PASS, TESTED_FAIL, DATA_MISSING,
                           NOT_TESTABLE_HERE)}
    report: Dict[str, Any] = {
        "ran": True,
        "status": status,
        "status_reason": _STATUS_REASON.get(status, ""),
        "draft_in": body,
        "draft_out": final,
        "draft_changed": final != body,
        "line_rows": rows,
        "line_counts": {name: sum(1 for row in rows
                                  if row.get("status") == name)
                        for name in LINE_STATUSES},
        "drop": drop,
        "tests": tests,
        "counts": counts,
        # Naap us draft par hui jo diya jaayega — dono alag nahi ho sakte.
        "tested_draft": "after_drop",
        "policy": policy(),
        "cannot_measure": list(CANNOT_MEASURE),
        "disclaimer": LAB_DISCLAIMER,
        "limits": list(limits()),
    }
    report["redraft_notes"] = redraft_notes(report)
    return report


def limits() -> Tuple[str, ...]:
    """Audit me jaane wali seemaayein — inhe chhupana khud ek jhooth hoga."""
    return (
        "SONG LAB ne koi audio/dhun nahi banayi aur kuch suna nahi "
        "(AUDIO_GENERATED = False, HEARD = False) — chaaron test sirf likhawat "
        "ke dhaanche aur andar ki consistency par hain.",
        "TESTED_PASS ka matlab \"gaana achha hai\" nahi hai; asli sunne wale "
        "par test hua hi nahi (HUMAN_REACTION_TESTED = False).",
        "Hatai gayi line \"kharaab\" thi ye saboot nahi — itna hi ki usne ek "
        "likha hua niyam toda (jhoothi tareef ka daawa, ulta bhaav, ya dhun ka "
        "daawa).",
        "Matra/cliché/script wali kamzor line HATAI NAHI JAATI — wo redraft ki "
        "note me jaati hai, kyunki wahan naap kamzor hai par baat kaam ki ho "
        "sakti hai.",
        "Ghise-pite shabd aur bhaav ki list adhoori hai (craft se aayi hui) — "
        "0 milna \"naya hai\" nahi hota.",
        "Padhi hui convention SOURCE-REPORTED hai; wo \"sahi tareeqa\" ka "
        "saboot nahi, aur kuch padha na gaya ho to test DATA_MISSING rehta hai.",
        "Bhaav ka test shabd se hota hai: maange hue bhaav ka ek bhi shabd na "
        "mile to status DATA_MISSING hai, FAIL nahi — kyunki \"bhaav nahi hai\" "
        "aur \"shabd hamari list me nahi hai\" me farq karne ka naap nahi hai.",
        "\"Dhun ka daawa\" wali pakad songcraft ki ek hi list se aati hai; us "
        "list ke bahar ke shabd chhoot sakte hain, isliye code na lagna \"line "
        "me koi daawa nahi\" ka saboot nahi.",
    )


def section_lines(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Report me dikhane wali chhoti si sach-batao list."""
    data = report or {}
    if not data.get("ran"):
        return ["SONG LAB chala nahi: " + str(data.get("reason") or
                                              "farmaish gaane ki nahi thi")]
    counts = data.get("counts") or {}
    line_counts = data.get("line_counts") or {}
    drop = data.get("drop") or {}
    lines: List[str] = [
        f"Apne test ka nateeja: {data.get('status')} — "
        f"{data.get('status_reason', '')}",
        f"Chaar alag test: {counts.get(TESTED_PASS, 0)} pass, "
        f"{counts.get(TESTED_FAIL, 0)} fail, "
        f"{counts.get(DATA_MISSING, 0)} data hi nahi, "
        f"{counts.get(NOT_TESTABLE_HERE, 0)} yahan lag hi nahi sakta.",
        f"Line-dar-line: {line_counts.get(LINE_KEEP, 0)} theek, "
        f"{line_counts.get(LINE_FIX, 0)} sudhaarni hain, "
        f"{line_counts.get(LINE_DROP, 0)} niyam tod rahi thin.",
    ]
    for row in data.get("tests") or []:
        lines.append(f"  • {row.get('test')} [{row.get('status')}] "
                     f"({row.get('method', '')}): {row.get('reason', '')}")
    if drop.get("dropped"):
        for entry in drop["dropped"]:
            lines.append(f"  – Line {entry.get('line_no')} hataayi: "
                         f"{'; '.join(entry.get('reasons') or [])} "
                         f"— \"{entry.get('text', '')}\"")
        lines.append("Hataane ke baad poore draft ki naap dobara chalayi gayi "
                     "aur wo giri nahi: pehle " + str(drop.get("before_counts"))
                     + ", baad me " + str(drop.get("after_counts")) + ".")
    else:
        lines.append("Koi line hataayi nahi gayi — " +
                     str(drop.get("note") or "wajah likhi hui hai"))
    for entry in drop.get("refused") or []:
        lines.append(f"  – Line {entry.get('line_no')} hatai NAHI gayi: "
                     f"{entry.get('refused_reason', '')}")
    lines.append("Yahan koi dhun nahi bani aur kuch suna nahi gaya — ye test "
                 "sirf likhawat ke dhaanche ke hain.")
    return lines


MAX_PROMPT_NOTES = 10
EMPTY_PROMPT_LINE = ("SONG LAB me is draft par koi naapi hui shikayat nahi "
                     "mili — iska matlab \"gaana achha hai\" NAHI hai.")


def prompt_block(report: Optional[Dict[str, Any]] = None) -> str:
    """
    Dobara likhwane ke liye block — sirf NAAPI HUI baat, bounded.

    Yahan se koi model call nahi jaati; ye sirf text banata hai. Ek hi bounded
    redraft `craft.run_craft` karta hai, aur ye block usi prompt me jud sakta
    hai. Koi tareef, koi "achha likho" jaisi khaali salaah nahi — jo naapa gaya
    wahi.
    """
    data = report or {}
    if not data.get("ran"):
        return ""
    notes = list(data.get("redraft_notes") or [])
    out: List[str] = ["SONG LAB (app ke apne naap) — ye baatein theek karo:"]
    if not notes:
        out.append("- " + EMPTY_PROMPT_LINE)
    for note in notes[:MAX_PROMPT_NOTES]:
        out.append("- " + note)
    if len(notes) > MAX_PROMPT_NOTES:
        out.append(f"- (aur {len(notes) - MAX_PROMPT_NOTES} baatein — sabse "
                   f"pehle upar wali theek karo)")
    out.append("Hataayi gayi line waapas mat likho. \"Hit hoga\", \"sabko "
               "pasand aayega\" jaisa koi daawa gaane me mat likho — wo naapa "
               "hi nahi ja sakta.")
    return "\n".join(out)


def public_record(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Audit ke liye chhota, saaf record — number aur jhande, bina bade text."""
    data = report or {}
    drop = data.get("drop") or {}
    return {
        "ran": bool(data.get("ran")),
        "status": str(data.get("status") or NOT_RUN),
        "tests_run": len(data.get("tests") or []),
        "test_names": [str(row.get("test") or "")
                       for row in data.get("tests") or []],
        "counts": dict(data.get("counts") or {}),
        "line_counts": dict(data.get("line_counts") or {}),
        "lines_dropped": len(drop.get("dropped") or []),
        "drops_refused": len(drop.get("refused") or []),
        "draft_changed": bool(data.get("draft_changed")),
        "audio_generated": AUDIO_GENERATED,
        "tune_made": TUNE_MADE,
        "heard": HEARD,
        "human_reaction_tested": HUMAN_REACTION_TESTED,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "provider_cost": PROVIDER_COST,
        "quality_proven": False,
        "every_drop_has_a_measured_reason": EVERY_DROP_HAS_A_MEASURED_REASON,
    }


# ── synthesizer ka mukh: CRAFT ki report se SONG LAB ka hissa ───────────────
# SONG LAB craft ke ANDAR chalta hai, isliye uski report craft ki report me
# `song_lab` key par baithti hai. Synthesizer ko doosra pass nahi chahiye —
# wahi craft_report kaafi hai. Isse ek jhooth apne aap band ho jaata hai: jo
# draft craft ne diya, usi ka SONG LAB record chhapta hai; do alag draft ke do
# alag record nahi ho sakte.
SONG_LAB_SUBHEADING = "### SONG LAB — app ne khud is gaane ko naapa"
SONG_LAB_KEY = "song_lab"
MAX_AUDIT_LIMIT_LINES = len(limits())


def report_of(craft_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """CRAFT ki report ke andar se SONG LAB ka hissa — na mile to khaali."""
    if not isinstance(craft_report, dict):
        return {}
    inner = craft_report.get(SONG_LAB_KEY)
    return inner if isinstance(inner, dict) else {}


def songlab_section(craft_report: Optional[Dict[str, Any]] = None) -> str:
    """
    Jawab me chhapne wala block. Gaana na bana ho to "" (khaali) — bina naap ka
    heading chhapna khud ek jhooth hai.
    """
    report = report_of(craft_report)
    if not report.get("ran"):
        return ""
    out: List[str] = [SONG_LAB_SUBHEADING, ""]
    for line in section_lines(report):
        out.append("- " + line if not line.startswith(("  ", "- ")) else line)
    return "\n".join(out)


def songlab_limits(craft_report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit ki seemaayein — sirf tab jab SONG LAB sach me chala ho."""
    if not report_of(craft_report).get("ran"):
        return []
    return list(limits())
