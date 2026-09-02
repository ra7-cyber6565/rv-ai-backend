"""#149 — MOOD LEXICON: bhaav ke shabd PADHI HUI source se seekho (cited).

Kyun ye file bani
-----------------
`craft.MOODS` haath se likhi hui ek band list hai. Usme "dukh" hai par "dard",
"aansu", "viraha", "gham-e-dil", "tootna" nahi. Isliye intel ka bilkul aam
sawaal — "dard bhara sad gaana likho" — par app ka bhaav wala naap `DATA_MISSING`
de deta tha: naap ka naam tha, naap nahi thi. Ye khaali jagah #141 ke audit me
khud pakdi gayi thi aur report-only chhodi gayi thi. Ab isi ka ilaaj hai.

Kaise seekhta hai (aur kaise NAHI)
----------------------------------
Seekhne ka ek hi tareeka hai: **jo source app ne asli me padhi hain, unme se
GLOSS uthana** — jaise "viraha (separation)", "rulaana, that is dukh",
"aansu means sadness". Ek taraf curated list ka shabd (ANCHOR) ho aur doosri
taraf theek EK naya shabd — tab hi jodi banti hai, aur us jodi ke saath source
id jaata hai. Bina source id koi shabd ledger me nahi aata.

Jo ye module JAAN-BOOJH KAR nahi karta:

  * **Andaza nahi.** Ek hi vaakya me do shabd saath aa gaye — isse jodi nahi
    banti. Sirf gloss ka DHAANCHA (bracket, "means", "also known as", "i.e.")
    jodi banata hai. Statistical co-occurrence = fabrication, wo yahan nahi hai.
  * **Ek source par bharosa nahi.** `CONFIRM_MIN = 2` — do ALAG source id se
    aaya shabd hi naap me lagta hai. Ek source wala shabd sirf HINT hai
    (`confirmed: False`) aur kisi bhi MET/NOT_MET ko chhoota nahi.
  * **Seekha shabd kisi line ko HATA nahi sakta.** `LEARNED_CUE_CAN_DROP_A_LINE
    = False`. SONG LAB ka `line_mood_conflict` (jo line DROP karta hai) sirf
    curated table par chalta hai. Seekha shabd sirf ye keh sakta hai "maanga hua
    bhaav MAUJOOD hai" — kabhi ye nahi ki "ulta bhaav hai, line hatao". Wajah
    seedhi hai: intel ki likhi line hataana sabse bhaari faisla hai, aur uske
    peeche padha hua synonym kaafi saboot nahi.
  * **Shabd milna bhaav nahi hota.** `LEARNED_CUE_IS_NOT_A_FEELING = True`.
    Ye module vocabulary badhata hai, "feeling aa gayi" ka saboot nahi deta.
  * **Purana kuch hataata nahi.** Curated `craft.MOODS` waisi hi rehti hai; ye
    uske UPAR jodta hai. Ledger khaali ho to app ka behaviour bilkul purana.
  * **0 Gemini call, 0 network.** Sirf pehle se padhi hui source ka text.

`ran: False` ka matlab "kuch padha hi nahi gaya" hai — "koi naya shabd nahi
hai" nahi. Aur `cues` khaali hone ka matlab "bhasha me synonym nahi hai" nahi;
sirf ye ki JO padha gaya usme gloss nahi mila.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# NOTE: `craft` aur `songcraft` JAAN-BOOJH KAR module ke top par import nahi
# kiye jaate — craft khud is module ko import karta hai. Andar (function ke
# andar) import karne se circular import ka koi khatra hi nahi bachta, aur
# "ek hi sach" bhi bacha rehta hai: anchor table craft.MOODS hi hai, uski copy
# yahan kabhi nahi banti.

# ── har baar report me jaane wale sach ───────────────────────────────────────
GEMINI_CALLS = 0                     # ek bhi model call nahi
NETWORK_USED = False                 # ye module sirf padha hua text dekhta hai
LEXICON_IS_LEARNED_NOT_COMPLETE = True   # jo padha gaya utna hi seekha
LEARNED_CUE_CAN_DROP_A_LINE = False      # seekha shabd line hata nahi sakta
LEARNED_CUE_IS_NOT_A_FEELING = True      # shabd milna feeling ka saboot nahi
CURATED_LIST_IS_NEVER_REPLACED = True    # purani list hataayi nahi jaati
GUESSED_FROM_CO_OCCURRENCE = False       # saath aa jaana = jodi nahi

CONFIRM_MIN = 2                # itni ALAG source id ke baad hi naap me lagta
MAX_SOURCES_SCANNED = 40       # itni source se aage nahi padhte (bounded)
MAX_SENTENCES_PER_SOURCE = 400
MAX_CUES = 24                  # ledger ki chhat
MAX_CUE_CHARS = 20
MIN_CUE_CHARS = 3
MAX_GLOSS_WORDS = 2            # gloss side me itne se zyada shabd = reject
MAX_EXAMPLES_PER_CUE = 3

# ── kachche shabd jo cue nahi ban sakte ──────────────────────────────────────
# Ye ek REJECT list hai, koi knowledge list nahi: inme se koi shabd bhaav ka
# naam nahi hai, ye sirf vaakya jodne wale shabd hain. Reject list ka adhoora
# hona jhooth nahi banata — jo chhoot jaata hai wo aage `admissible` ke doosre
# niyam (lambai, script, ginti) par phir se jaancha jaata hai.
_STOP_WORDS: Tuple[str, ...] = (
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "for", "with",
    "that", "this", "these", "those", "is", "are", "was", "were", "be", "been",
    "it", "its", "as", "at", "by", "from", "into", "than", "then", "such",
    "also", "known", "called", "means", "meaning", "literally", "etc", "eg",
    "ie", "see", "figure", "fig", "table", "chapter", "page", "vol", "no",
    "et", "al", "ibid", "op", "cit", "trans", "ed", "eds", "pp",
    "word", "words", "term", "terms", "concept", "sense", "type", "kind",
    "example", "examples", "e", "g", "i", "eng", "english", "hindi", "urdu",
    "sanskrit", "punjabi", "lit", "n", "adj", "v", "noun", "verb",
)

# Sirf akshar (latin ya Devanagari), beech me ek hyphen/apostrophe chal jaata.
_CUE_SHAPE_RE = re.compile(r"^[a-zऀ-ॿ]+(?:[-'‍][a-zऀ-ॿ]+)*$")
_WORD_SPLIT_RE = re.compile(r"[^a-zऀ-ॿ'\-]+")

# ── gloss ke dhaanche (yahi jodi banate hain) ────────────────────────────────
# Har pattern do hisse deta hai: (left, right). Anchor kisi bhi taraf ho sakta
# hai — dono taraf jaanchi jaati hain, kyunki kitaabein dono tarah likhti hain:
# "viraha (longing)" aur "longing (viraha)".
PATTERN_BRACKET = "bracket_gloss"          # viraha (judaai)
PATTERN_ALSO_KNOWN = "also_known_as"       # viraha, also known as judaai
PATTERN_MEANS = "means"                    # aansu means dukh
PATTERN_THAT_IS = "that_is"                # rulaana, i.e. dukh
PATTERN_NAMES = (PATTERN_BRACKET, PATTERN_ALSO_KNOWN, PATTERN_MEANS,
                 PATTERN_THAT_IS)

_BRACKET_RE = re.compile(
    r"(?<![\w'\-])([a-zऀ-ॿ][a-zऀ-ॿ'\-]{1,24})\s*"
    r"[\(\[]\s*([^\)\]]{2,40}?)\s*[\)\]]", re.IGNORECASE)
_ALSO_KNOWN_RE = re.compile(
    r"([\wऀ-ॿ'\-]{2,25})\s*,?\s*(?:is\s+)?(?:also\s+)?"
    r"(?:known|called|referred\s+to)\s+(?:as\s+)?([\wऀ-ॿ'\-]{2,25}"
    r"(?:\s+[\wऀ-ॿ'\-]{2,25})?)", re.IGNORECASE)
_MEANS_RE = re.compile(
    r"([\wऀ-ॿ'\-]{2,25})\s+(?:literally\s+)?"
    r"(?:means|translates\s+(?:to|as)|ka\s+matlab\s+hai|ka\s+arth\s+hai)\s+"
    r"([\wऀ-ॿ'\-]{2,25}(?:\s+[\wऀ-ॿ'\-]{2,25})?)",
    re.IGNORECASE)
_THAT_IS_RE = re.compile(
    r"([\wऀ-ॿ'\-]{2,25})\s*(?:,|—|--)\s*(?:i\.?e\.?|that\s+is)\s*,?\s*"
    r"([\wऀ-ॿ'\-]{2,25}(?:\s+[\wऀ-ॿ'\-]{2,25})?)",
    re.IGNORECASE)

_PATTERNS: Tuple[Tuple[str, Any], ...] = (
    (PATTERN_BRACKET, _BRACKET_RE),
    (PATTERN_ALSO_KNOWN, _ALSO_KNOWN_RE),
    (PATTERN_MEANS, _MEANS_RE),
    (PATTERN_THAT_IS, _THAT_IS_RE),
)

# ── reject ki wajah (ginti report me jaati hai — khaali jagah chhupti nahi) ──
REJECT_NO_ANCHOR = "no_anchor_mood_on_either_side"
REJECT_BOTH_SIDES_ANCHOR = "both_sides_already_known"
REJECT_GLOSS_TOO_LONG = "gloss_side_has_too_many_words"
REJECT_SHAPE = "not_a_word_shape"
REJECT_STOP_WORD = "stop_word"
REJECT_LENGTH = "too_short_or_too_long"
REJECT_ALREADY_KNOWN = "already_in_curated_list"
REJECT_AMBIGUOUS = "same_word_glossed_to_two_moods"
REJECT_NO_SOURCE_ID = "source_without_id"
REJECT_CAP = "ledger_cap_reached"
REJECT_REASONS: Tuple[str, ...] = (
    REJECT_NO_ANCHOR, REJECT_BOTH_SIDES_ANCHOR, REJECT_GLOSS_TOO_LONG,
    REJECT_SHAPE, REJECT_STOP_WORD, REJECT_LENGTH, REJECT_ALREADY_KNOWN,
    REJECT_AMBIGUOUS, REJECT_NO_SOURCE_ID, REJECT_CAP,
)
REJECT_HUMAN: Dict[str, str] = {
    REJECT_NO_ANCHOR: ("dono taraf koi jaana-pehchana bhaav nahi tha, isliye is "
                       "jodi ka matlab hi tay nahi ho paaya"),
    REJECT_BOTH_SIDES_ANCHOR: ("dono shabd pehle se list me hain — isse kuch "
                               "naya nahi seekha"),
    REJECT_GLOSS_TOO_LONG: ("gloss ki taraf poora vaakya tha, ek shabd nahi — "
                            "poore vaakya ko bhaav ka naam maan lena galat hoga"),
    REJECT_SHAPE: "shabd ki shakal hi shabd jaisi nahi thi (number/chinh mile)",
    REJECT_STOP_WORD: "vaakya jodne wala shabd tha, bhaav ka naam nahi",
    REJECT_LENGTH: "shabd bahut chhota ya bahut lamba tha",
    REJECT_ALREADY_KNOWN: "ye shabd curated list me pehle se hai",
    REJECT_AMBIGUOUS: ("ek hi shabd do alag bhaav ke saath gloss hua — do me se "
                       "kaunsa sahi hai, ye padhi hui source se tay nahi hota"),
    REJECT_NO_SOURCE_ID: ("source ke saath koi id nahi thi, aur bina citation "
                          "koi shabd ledger me nahi jaata"),
    REJECT_CAP: "ledger ki chhat bhar gayi thi",
}


# ── anchor table: EK HI SACH, copy nahi ──────────────────────────────────────
def _craft():
    """`craft` andar se import — module ke top par karna circular ho jaata."""
    from . import craft as _mod
    return _mod


def _songcraft():
    from . import songcraft as _mod
    return _mod


def anchor_map() -> Dict[str, str]:
    """curated variant (lower) → mood label. Har baar craft.MOODS se banta hai.

    Yahan is table ki COPY jaan-boojh kar nahi rakhi jaati: craft.MOODS badle to
    ye apne aap badle. Ek hi sach.
    """
    out: Dict[str, str] = {}
    for label, variants in _craft().MOODS:
        for variant in variants:
            token = str(variant or "").strip().lower()
            if token:
                out.setdefault(token, label)
    return out


def mood_labels() -> Tuple[str, ...]:
    """curated label ke naam — seekha shabd inhi me se kisi ka ho sakta hai."""
    return tuple(label for label, _variants in _craft().MOODS)


# ── shabd ki jaanch ──────────────────────────────────────────────────────────
def _words(side: str) -> List[str]:
    return [word for word in _WORD_SPLIT_RE.split(str(side or "").lower())
            if word]


def admissible(token: str) -> Tuple[bool, str]:
    """Naya shabd ledger me aane laayak hai ya nahi — wajah ke saath."""
    word = str(token or "").strip().lower().strip("-'")
    if not word:
        return False, REJECT_SHAPE
    if not _CUE_SHAPE_RE.match(word):
        return False, REJECT_SHAPE
    if word in _STOP_WORDS:
        return False, REJECT_STOP_WORD
    if len(word) < MIN_CUE_CHARS or len(word) > MAX_CUE_CHARS:
        return False, REJECT_LENGTH
    if word in anchor_map():
        return False, REJECT_ALREADY_KNOWN
    return True, ""


# Ek gloss ke ek pehlu (side) ka kirdaar.
ROLE_ANCHOR = "anchor"        # sab shabd pehle se jaane-pehchane
ROLE_CANDIDATE = "candidate"  # theek ek naya shabd, koi jaana-pehchana nahi
ROLE_NONE = "none"


def _side_role(side: str) -> Tuple[str, Any, str]:
    """Gloss ke ek pehlu ka kirdaar: anchor, candidate, ya kuch nahi.

    MIXED pehlu (ek jaana-pehchana + ek naya, jaise "dukh dard") jaan-boojh kar
    `ROLE_NONE` hai: us haalat me kaunsa shabd kis ka gloss hai ye tay nahi
    hota, aur andaza lagana hi fabrication hoga. Uski wajah
    `REJECT_GLOSS_TOO_LONG` girti hai — "gloss ki taraf ek shabd se zyada tha".
    """
    words = _words(side)
    core = [word for word in words if word not in _STOP_WORDS]
    if not core:
        return ROLE_NONE, None, REJECT_STOP_WORD
    if len(core) > MAX_GLOSS_WORDS:
        return ROLE_NONE, None, REJECT_GLOSS_TOO_LONG
    amap = anchor_map()
    known = [amap[word] for word in core if word in amap]
    fresh = [word for word in core if word not in amap]
    if known and not fresh:
        labels = sorted(set(known))
        # Ek hi taraf do alag bhaav (jaise "separation in love" → judaai + pyaar)
        # — naya shabd kis ka gloss hai, ye padhi hui line se tay nahi hota.
        if len(labels) != 1:
            return ROLE_NONE, None, REJECT_AMBIGUOUS
        return ROLE_ANCHOR, labels[0], ""
    if fresh and not known and len(fresh) == 1:
        return ROLE_CANDIDATE, fresh[0], ""
    return ROLE_NONE, None, REJECT_GLOSS_TOO_LONG


def evaluate_pair(left: str, right: str) -> Tuple[str, str, str]:
    """(label, naya_shabd, reject_wajah) — ek taraf anchor, doosri ek naya shabd."""
    left_role, left_load, left_why = _side_role(left)
    right_role, right_load, right_why = _side_role(right)
    if left_role == ROLE_ANCHOR and right_role == ROLE_ANCHOR:
        return "", "", REJECT_BOTH_SIDES_ANCHOR
    if left_role == ROLE_ANCHOR and right_role == ROLE_CANDIDATE:
        label, cue = left_load, right_load
    elif right_role == ROLE_ANCHOR and left_role == ROLE_CANDIDATE:
        label, cue = right_load, left_load
    elif left_role == ROLE_ANCHOR or right_role == ROLE_ANCHOR:
        # Anchor mil gaya par doosri taraf saaf ek shabd nahi tha.
        return "", "", (right_why if left_role == ROLE_ANCHOR else left_why)
    else:
        return "", "", REJECT_NO_ANCHOR
    ok, why = admissible(cue)
    if not ok:
        return "", "", why
    return label, cue, ""


def gloss_pairs(sentence: str) -> List[Tuple[str, str, str]]:
    """Ek vaakya me se (left, right, pattern) — sirf DHAANCHE se, andaze se nahi."""
    text = str(sentence or "")
    out: List[Tuple[str, str, str]] = []
    for name, regex in _PATTERNS:
        for match in regex.finditer(text):
            left = match.group(1) or ""
            right = match.group(2) or ""
            if left.strip() and right.strip():
                out.append((left.strip(), right.strip(), name))
    return out


# ── LEDGER: padhi hui source se cited shabd ──────────────────────────────────
def _read_level(source: Any) -> str:
    return str(getattr(source, "read_level", "") or "").strip().lower()


def _empty_rejects() -> Dict[str, int]:
    # Saari wajah 0 ke saath bhi likhi jaati hain — khaali jagah chhupti nahi.
    return {reason: 0 for reason in REJECT_REASONS}


def learn(sources: Iterable[Any] = (),
          ask: Optional[Any] = None) -> Dict[str, Any]:
    """Padhi hui source me se bhaav ke naye shabd — har shabd ke saath source id.

    `ran: False` ka matlab "koi source padhi hi nahi gayi" hai. `cues` khaali
    hone ka matlab "bhasha me synonym nahi hai" nahi — sirf ye ki JO padha gaya
    usme gloss ka dhaancha nahi mila.
    """
    songcraft = _songcraft()
    sources = list(sources or [])[:MAX_SOURCES_SCANNED]
    rejects = _empty_rejects()
    found: Dict[str, Dict[str, Any]] = {}
    banned: set = set()          # ek se zyada bhaav wale shabd — hamesha bahar
    scanned = 0
    full_text_sources = 0
    sentences_read = 0
    pairs_seen = 0

    for source in sources:
        text = songcraft._source_text(source)
        if not text:
            continue
        scanned += 1
        if _read_level(source) == "full_text":
            full_text_sources += 1
        source_id = str(getattr(source, "source_id", "") or "").strip()
        if not source_id:
            # id nahi to citation nahi, aur bina citation koi shabd nahi.
            rejects[REJECT_NO_SOURCE_ID] += 1
            continue
        for sentence in songcraft._sentences(text)[:MAX_SENTENCES_PER_SOURCE]:
            sentences_read += 1
            norm = songcraft._norm(sentence)
            if any(songcraft._cue_present(norm, junk)
                   for junk in songcraft._JUNK_CUES):
                continue
            for left, right, pattern in gloss_pairs(sentence):
                pairs_seen += 1
                label, cue, why = evaluate_pair(left, right)
                if why:
                    rejects[why] = rejects.get(why, 0) + 1
                    continue
                if cue in banned:
                    rejects[REJECT_AMBIGUOUS] += 1
                    continue
                row = found.get(cue)
                if row is None:
                    if len(found) >= MAX_CUES:
                        rejects[REJECT_CAP] += 1
                        continue
                    row = {"cue": cue, "label": label, "sources": set(),
                           "patterns": [], "examples": []}
                    found[cue] = row
                if row["label"] != label:
                    # Ek hi shabd do alag bhaav ke saath gloss hua — dono shak ke
                    # ghere me hain, isliye shabd poori tarah bahar.
                    banned.add(cue)
                    found.pop(cue, None)
                    rejects[REJECT_AMBIGUOUS] += 1
                    continue
                row["sources"].add(source_id)
                if pattern not in row["patterns"]:
                    row["patterns"].append(pattern)
                if len(row["examples"]) < MAX_EXAMPLES_PER_CUE:
                    clipped = sentence[:songcraft.MAX_GUIDANCE_CHARS].strip()
                    if all(clipped != old.get("text")
                           for old in row["examples"]):
                        row["examples"].append({"text": clipped,
                                                "source_id": source_id,
                                                "pattern": pattern})

    cues: List[Dict[str, Any]] = []
    for row in found.values():
        ids = sorted(row["sources"])
        cues.append({
            "cue": row["cue"],
            "label": row["label"],
            "source_count": len(ids),
            "source_ids": ids,
            "patterns": list(row["patterns"]),
            "examples": list(row["examples"]),
            "confirmed": len(ids) >= CONFIRM_MIN,
        })
    # Sabse zyada saboot wala shabd pehle; baraabari par naam se — kram har baar
    # ek jaisa (koi randomness nahi).
    cues.sort(key=lambda item: (not item["confirmed"],
                               -item["source_count"], item["cue"]))
    confirmed = [item for item in cues if item["confirmed"]]
    hints = [item for item in cues if not item["confirmed"]]

    if not scanned:
        note = ("bhaav ke shabd seekhne ke liye koi source padhi hi nahi gayi — "
                "isliye purani curated list hi chali (kuch ghada nahi gaya)")
    elif confirmed:
        note = (f"{len(confirmed)} naya bhaav-shabd {CONFIRM_MIN}+ alag padhi hui "
                f"source se aaya (har shabd ke saath source id hai); "
                f"{len(hints)} shabd sirf ek source se aaya isliye wo abhi hint "
                f"hai aur kisi naap me nahi lagta")
    else:
        note = (f"{scanned} source padhi gayi par {CONFIRM_MIN}+ source se "
                f"confirm hone wala koi naya bhaav-shabd nahi mila — "
                f"{len(hints)} hint mile, aur hint se koi naap nahi badalta")

    return {
        "ran": bool(scanned),
        "cues": cues,
        "confirmed_cues": [item["cue"] for item in confirmed],
        "hint_cues": [item["cue"] for item in hints],
        "confirmed_count": len(confirmed),
        "hint_count": len(hints),
        "labels_touched": sorted({item["label"] for item in confirmed}),
        "sources_scanned": scanned,
        "full_text_source_count": full_text_sources,
        "sentences_read": sentences_read,
        "pairs_seen": pairs_seen,
        "banned_cues": sorted(banned),
        "rejects": rejects,
        "reject_reasons": {reason: REJECT_HUMAN[reason]
                           for reason in REJECT_REASONS if rejects.get(reason)},
        "curated_label_count": len(mood_labels()),
        "confirm_min": CONFIRM_MIN,
        # Jhande — naam se hi seema dikhe.
        "lexicon_is_learned_not_complete": LEXICON_IS_LEARNED_NOT_COMPLETE,
        "learned_cue_can_drop_a_line": LEARNED_CUE_CAN_DROP_A_LINE,
        "learned_cue_is_not_a_feeling": LEARNED_CUE_IS_NOT_A_FEELING,
        "curated_list_is_never_replaced": CURATED_LIST_IS_NEVER_REPLACED,
        "guessed_from_co_occurrence": GUESSED_FROM_CO_OCCURRENCE,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "ask": (ask.to_dict() if hasattr(ask, "to_dict") else {}),
        "note": note,
    }


def confirmed_pairs(report: Optional[Dict[str, Any]] = None
                    ) -> Tuple[Tuple[str, str], ...]:
    """(label, shabd) jodiyan jo NAAP me lag sakti hain — sirf confirmed.

    Yahi ek darwaaza hai jisse seekha shabd naap tak jaata hai. Hint yahan se
    kabhi nahi nikalta, isliye ek source ka shabd kisi MET/NOT_MET ko chhoo hi
    nahi sakta.
    """
    data = report if isinstance(report, dict) else {}
    out: List[Tuple[str, str]] = []
    for item in data.get("cues") or []:
        if not isinstance(item, dict) or not item.get("confirmed"):
            continue
        label = str(item.get("label") or "").strip()
        cue = str(item.get("cue") or "").strip()
        if label and cue:
            out.append((label, cue))
    return tuple(out)


def hint_pairs(report: Optional[Dict[str, Any]] = None
               ) -> Tuple[Tuple[str, str], ...]:
    """Ek hi source se aaye shabd — sirf dikhane ke liye, naap ke liye NAHI."""
    data = report if isinstance(report, dict) else {}
    out: List[Tuple[str, str]] = []
    for item in data.get("cues") or []:
        if not isinstance(item, dict) or item.get("confirmed"):
            continue
        label = str(item.get("label") or "").strip()
        cue = str(item.get("cue") or "").strip()
        if label and cue:
            out.append((label, cue))
    return tuple(out)


# ── report ka mukh ───────────────────────────────────────────────────────────
STAGE = "mood_lexicon"
SUBHEADING = "### BHAAV KI SHABDAWALI — padhi hui source se seekhe shabd"
# 2 ginti ki line + 3 shabd + 1 reject ki line + 1 seema ki line = 7.
MAX_SECTION_LINES = 7


def not_run(reason: str = "") -> Dict[str, Any]:
    """Seekhna chala hi nahi — aur KYU nahi chala, saaf likha hua."""
    return {
        "ran": False,
        "cues": [],
        "confirmed_cues": [],
        "hint_cues": [],
        "confirmed_count": 0,
        "hint_count": 0,
        "labels_touched": [],
        "sources_scanned": 0,
        "full_text_source_count": 0,
        "sentences_read": 0,
        "pairs_seen": 0,
        "banned_cues": [],
        "rejects": _empty_rejects(),
        "reject_reasons": {},
        "confirm_min": CONFIRM_MIN,
        "lexicon_is_learned_not_complete": LEXICON_IS_LEARNED_NOT_COMPLETE,
        "learned_cue_can_drop_a_line": LEARNED_CUE_CAN_DROP_A_LINE,
        "learned_cue_is_not_a_feeling": LEARNED_CUE_IS_NOT_A_FEELING,
        "curated_list_is_never_replaced": CURATED_LIST_IS_NEVER_REPLACED,
        "guessed_from_co_occurrence": GUESSED_FROM_CO_OCCURRENCE,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "reason": reason or "koi source padhi hi nahi gayi",
        "note": ("bhaav ki shabdawali badhaayi nahi gayi — purani curated list "
                 "hi chali (kuch ghada nahi gaya)"),
    }


def policy() -> Dict[str, Any]:
    """Is hisse ka likha hua kanoon — report me jaata hai, badalta nahi."""
    return {
        "stage": STAGE,
        "learned_from": "already_read_source_text_only",
        "gloss_patterns": list(PATTERN_NAMES),
        "confirm_min": CONFIRM_MIN,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "lexicon_is_learned_not_complete": LEXICON_IS_LEARNED_NOT_COMPLETE,
        "learned_cue_can_drop_a_line": LEARNED_CUE_CAN_DROP_A_LINE,
        "learned_cue_is_not_a_feeling": LEARNED_CUE_IS_NOT_A_FEELING,
        "curated_list_is_never_replaced": CURATED_LIST_IS_NEVER_REPLACED,
        "guessed_from_co_occurrence": GUESSED_FROM_CO_OCCURRENCE,
        "reject_reasons": list(REJECT_REASONS),
        "max_cues": MAX_CUES,
        "max_sources_scanned": MAX_SOURCES_SCANNED,
        "measured_by": "offline_rules_in_mood_lexicon_py",
    }


def limits() -> Tuple[str, ...]:
    """Audit me jaane wali seemaayein — inhe chhupana khud ek jhooth hoga."""
    return (
        "Seekhe hue shabd sirf UTNE hain jitna app ne asli me padha "
        "(LEXICON_IS_LEARNED_NOT_COMPLETE = True) — 0 shabd milna \"bhasha me "
        "aur shabd nahi hain\" ka saboot nahi hai.",
        "Shabd sirf GLOSS ke dhaanche se seekha jaata hai (bracket, \"means\", "
        "\"also known as\", \"i.e.\"); ek hi vaakya me do shabd saath aa jaane "
        "se koi jodi nahi banti (GUESSED_FROM_CO_OCCURRENCE = False).",
        "Naap me sirf wo shabd lagta hai jo do ALAG source id se aaya ho; ek "
        "source wala shabd sirf hint hai aur kisi bhi nateeje ko nahi chhoota.",
        "Seekha hua shabd kisi line ko HATA nahi sakta "
        "(LEARNED_CUE_CAN_DROP_A_LINE = False) — ulta-bhaav wala DROP faisla "
        "sirf curated list par chalta hai, kyunki likhi hui line hataane ke "
        "liye padha hua synonym kaafi saboot nahi.",
        "Shabd mil jaana bhaav aa jaana nahi hota "
        "(LEARNED_CUE_IS_NOT_A_FEELING = True) — ye hissa sirf shabdawali "
        "badhata hai, feeling ka saboot nahi deta.",
        "Purani curated list hataayi nahi gayi "
        "(CURATED_LIST_IS_NEVER_REPLACED = True) — ledger khaali ho to app ka "
        "behaviour bilkul pehle jaisa rehta hai.",
        "Ek hi shabd do alag bhaav ke saath gloss ho to wo shabd poori tarah "
        "bahar kar diya jaata hai — padhi hui source se ye tay nahi hota ki "
        "kaunsa sahi hai.",
    )


MAX_AUDIT_LIMIT_LINES = len(limits())


def section_lines(report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Report me dikhane wali chhoti si sach-batao list."""
    data = report if isinstance(report, dict) else {}
    if not data.get("ran"):
        return ["Bhaav ki shabdawali nahi badhi: "
                + str(data.get("reason") or "koi source padhi hi nahi gayi")]
    rejects = data.get("rejects") or {}
    lines: List[str] = [
        f"{int(data.get('confirmed_count') or 0)} naya bhaav-shabd "
        f"{CONFIRM_MIN}+ padhi hui source se confirm hua; "
        f"{int(data.get('hint_count') or 0)} sirf hint hai (naap me nahi lagta)",
        f"{int(data.get('sources_scanned') or 0)} source me se "
        f"{int(data.get('sentences_read') or 0)} vaakya dekhe gaye, "
        f"{int(data.get('pairs_seen') or 0)} gloss jodi mili",
    ]
    for item in (data.get("cues") or [])[:MAX_SECTION_LINES - 4]:
        if not isinstance(item, dict):
            continue
        ids = ", ".join(item.get("source_ids") or [])
        lines.append(
            f"\"{item.get('cue')}\" → bhaav \"{item.get('label')}\" "
            f"({'confirmed' if item.get('confirmed') else 'hint'}, "
            f"source: {ids or 'nahi'})")
    dropped = sum(int(value or 0) for value in rejects.values())
    if dropped:
        why = ", ".join(sorted(key for key, value in rejects.items() if value))
        lines.append(f"{dropped} jodi chhod di gayi (wajah naapi hui hai: {why})")
    lines.append("Seekha shabd sirf \"maanga bhaav maujood hai\" keh sakta hai — "
                 "kisi line ko hataa nahi sakta, aur shabd milna feeling ka "
                 "saboot nahi hai.")
    return lines


def public_record(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Audit ke liye chhota, saaf record — number aur jhande, bina bade text."""
    data = report if isinstance(report, dict) else {}
    rejects = data.get("rejects") or {}
    return {
        "ran": bool(data.get("ran")),
        "confirmed_count": int(data.get("confirmed_count") or 0),
        "hint_count": int(data.get("hint_count") or 0),
        "confirmed_cues": list(data.get("confirmed_cues") or []),
        "labels_touched": list(data.get("labels_touched") or []),
        "sources_scanned": int(data.get("sources_scanned") or 0),
        "sentences_read": int(data.get("sentences_read") or 0),
        "pairs_seen": int(data.get("pairs_seen") or 0),
        "pairs_rejected": sum(int(value or 0) for value in rejects.values()),
        "rejects": dict(rejects),
        "confirm_min": CONFIRM_MIN,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "lexicon_is_learned_not_complete": LEXICON_IS_LEARNED_NOT_COMPLETE,
        "learned_cue_can_drop_a_line": LEARNED_CUE_CAN_DROP_A_LINE,
        "learned_cue_is_not_a_feeling": LEARNED_CUE_IS_NOT_A_FEELING,
        "curated_list_is_never_replaced": CURATED_LIST_IS_NEVER_REPLACED,
        "guessed_from_co_occurrence": GUESSED_FROM_CO_OCCURRENCE,
        "feeling_proven": False,
    }


# ── synthesizer ka mukh: CRAFT ki report se BHAAV-SHABDAWALI ka hissa ───────
# Ye hissa CRAFT ke saath chalta hai (craft ko hi ledger diya jaata hai),
# isliye uski report craft ki report me `mood_lexicon` key par baithti hai.
# Synthesizer ko alag pass nahi chahiye — wahi craft_report kaafi hai. Isse ek
# jhooth apne aap band ho jaata hai: jis ledger se naap chali, usi ka record
# chhapta hai; do alag ledger ke do alag record nahi ho sakte.
MOOD_KEY = "mood_lexicon"


def report_of(craft_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """CRAFT ki report ke andar se bhaav-shabdawali ka hissa — na mile to khaali."""
    if not isinstance(craft_report, dict):
        return {}
    inner = craft_report.get(MOOD_KEY)
    return inner if isinstance(inner, dict) else {}


def mood_section(craft_report: Optional[Dict[str, Any]] = None) -> str:
    """
    Jawab me chhapne wala block. Shabdawali sach me na seekhi gayi ho to ""
    (khaali) — bina naap ka heading chhapna khud ek jhooth hai.
    """
    report = report_of(craft_report)
    if not report.get("ran"):
        return ""
    out: List[str] = [SUBHEADING, ""]
    for line in section_lines(report):
        out.append("- " + line if not line.startswith(("  ", "- ")) else line)
    return "\n".join(out)


def mood_limits(craft_report: Optional[Dict[str, Any]] = None) -> List[str]:
    """Audit ki seemaayein — sirf tab jab shabdawali sach me seekhi gayi ho."""
    if not report_of(craft_report).get("ran"):
        return []
    return list(limits())
