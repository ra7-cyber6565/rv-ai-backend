"""
Run ka STATUS aur user-facing wajah — §1, §9, §10.

Teen alag-alag dikkat ek hi jagah se theek hoti hai:

  §1  Adhoore run ko "poora" dikhana band. UI ko ek machine-readable status
      chahiye: `RESEARCH INCOMPLETE` / `PARTIAL` / `COMPLETE`.

  §9  User ko raw error kabhi nahi. Live report mein "Seedha jawab" ke neeche
      seedha ye chhapa tha:
          ResourceExhausted: 429 You exceeded your current quota ...
          quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier
      Ab wahan insaani Hinglish jaati hai, aur ye protobuf line report ke
      sabse NEECHE "technical details" mein.

  §10 Khaali template section nahi. Pehle har heading chhap jaati thi, chahe
      andar sirf "_(Reasoning model ne ye section nahi diya.)_" ho. 11 khaali
      heading padhne se user ko kuch nahi milta — behtar hai wo section chhod
      do aur EK jagah saaf likh do ki kaun-kaun sa hissa nahi ban paaya.

Ye module jaan-boojh kar pure-Python hai (koi model, koi network), taaki
offline test ho sake.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from .model_errors import HUMAN as _KIND_HUMAN
from .model_errors import classify_text as _classify_text

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
INCOMPLETE = "RESEARCH INCOMPLETE"

# §9 ka maanga hua text, shabd-ba-shabd. Jab wajah free-API-limit ho, yahi
# pehli line jaati hai (isse chhota ya "sudhaar kar" mat likhna).
QUOTA_BANNER = (
    "Ye research run complete nahi ho paaya kyunki AI reasoning model ki free "
    "API limit khatam ho gayi. Sources search ho gaye, lekin analysis, "
    "hypotheses aur final synthesis complete nahi hui. Isliye is result ko "
    "final answer na maanein."
)

# error-kind -> insaani wajah (banner ke pehle vaakya ke liye)
_CAUSE: Dict[str, str] = {
    "daily_quota": "AI reasoning model ki free API limit khatam ho gayi",
    "rate_limit": "AI reasoning model ki free API limit khatam ho gayi",
    "auth_failure": "AI reasoning model ki API key kaam nahi kar rahi",
    "model_not_found": "AI reasoning model ka naam is API key ke liye kaam nahi kar raha",
    "input_too_large": "research prompt model ki input/context limit se bada tha",
    "invalid_request": "reasoning request ka format provider ne accept nahi kiya",
    "request_timeout": "deep reasoning request provider ki waqt-seema mein poori nahi hui",
    "server_error": "AI reasoning model ka server apni taraf se error de raha tha",
    "transient_network": "network beech mein saath chhod gaya",
    "empty_response": "AI reasoning model ne khaali jawab bheja",
    "unknown": "AI reasoning model se poora jawab nahi mila",
}
_QUOTA_KINDS = ("daily_quota", "rate_limit")

# pass ka naam -> user ki bhasha
_PASS_WORDS: Dict[str, str] = {
    "analysis": "analysis",
    "critique": "red-team check",
    "hypothesis": "hypotheses",
    "synthesis": "final synthesis",
}

# Ye nishaan dikhe = line technical hai, user ke jawab mein nahi jaani chahiye.
_RAW_MARKERS: Tuple[str, ...] = (
    "traceback", "quota_id", "quota_metric", "retry_delay", "protobuf",
    "googleapis.com", "google.api_core", "grpc", "http 4", "http 5",
    "status code", "stacktrace", "none type", "nonetype", "<class",
    "model=", "try=", "generativelanguage", "api version", "v1beta",
)
_EXC_RE = re.compile(
    r"\b[A-Z][A-Za-z]*(?:Error|Exception|Exhausted|Denied|NotFound|Timeout|"
    r"Invalid[A-Za-z]*|Unauthenticated|Unavailable)\b")
_CODE_RE = re.compile(r"\b(4\d\d|5\d\d)\b")


def looks_technical(text: str) -> bool:
    """Kya ye line user ko dikhane layak NAHI hai?"""
    raw = str(text or "")
    low = raw.lower()
    if any(m in low for m in _RAW_MARKERS):
        return True
    if _EXC_RE.search(raw):
        return True
    if _CODE_RE.search(raw) and ("quota" in low or "limit" in low
                                 or "error" in low or "model" in low):
        return True
    return False


def split_messages(messages: Iterable) -> Tuple[List[str], List[str]]:
    """
    Ek list ko do hisson mein baanto: (user ko dikhane layak, technical).

    Order preserve hota hai aur DUPLICATE hat jaate hain — pichhli report mein
    ek hi 429 teen baar chhapa tha (teen pass, teen error).
    """
    human: List[str] = []
    tech: List[str] = []
    for item in messages or []:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        bucket = tech if looks_technical(text) else human
        if text not in bucket:
            bucket.append(text)
    return human, tech


def cause_line(failure_kind: str = "", failure_reason: str = "") -> str:
    """Banner ke pehle vaakya ka 'kyunki ...' hissa."""
    if failure_kind in _CAUSE:
        return _CAUSE[failure_kind]
    if failure_reason and not looks_technical(failure_reason):
        return " ".join(str(failure_reason).split())
    return _CAUSE["unknown"]


# ── raw error lines se kind/insaani wajah (jab ledger khaali ho) ─────────────
# Kyun zaroori hai: kuch code path (aur test ka fake) seedha `brain.errors`
# mein line daal dete hain, ledger ko chhue bina. Us halat mein pehle user ko
# KOI warning hi nahi milti thi — raw line §9 ke tahat hata di jaati thi aur
# uski jagah kuch nahi aata tha. Ab wajah raw text se hi padh lete hain.
_KIND_PRIORITY = (
    "auth_failure", "daily_quota", "rate_limit", "model_not_found",
    "input_too_large", "invalid_request", "request_timeout", "server_error",
    "transient_network", "empty_response",
)


def infer_kind(messages: Iterable) -> str:
    """Error lines dekh kar sabse zaroori error-kind lauta do ("" agar kuch na mile)."""
    found: List[str] = []
    for item in messages or []:
        text = str(item or "").strip()
        if not text:
            continue
        kind = _classify_text(text).kind
        if kind and kind != "unknown":
            found.append(kind)
    for kind in _KIND_PRIORITY:
        if kind in found:
            return kind
    return found[0] if found else ""


def human_reason(messages: Iterable) -> str:
    """Raw error lines ka insaani Hinglish matlab (user ko dikhane layak)."""
    kind = infer_kind(messages)
    return _KIND_HUMAN.get(kind, "") if kind else ""


def _pass_phrase(names: Sequence[str]) -> str:
    words = [_PASS_WORDS.get(n, n) for n in names if n]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " aur " + words[-1]


@dataclass
class RunStatus:
    """
    Ek run ka imaandaar status. `code` UI ke liye hai, `banner` insaan ke liye,
    `technical` sabse neeche ke liye.
    """
    code: str = COMPLETE
    reason: str = ""                              # ek line, insaani
    banner: str = ""                              # top par dikhne wala paragraph
    missing_passes: List[str] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    human_warnings: List[str] = field(default_factory=list)
    technical: List[str] = field(default_factory=list)
    failure_kind: str = ""

    @property
    def incomplete(self) -> bool:
        return self.code == INCOMPLETE

    @property
    def ok(self) -> bool:
        return self.code == COMPLETE

    def to_dict(self) -> Dict:
        return {
            "status": self.code,
            "reason": self.reason,
            # `banner` bhi yahan hona ZAROORI hai — synthesizer isi dict se
            # top-of-report banner uthata hai. Ye chhoot gaya tha, jiski wajah
            # se status INCOMPLETE hone par bhi report par purani generic line
            # ("Ye research run complete nahi hua.") lagti thi aur §9 ka maanga
            # hua vaakya kahin dikhta hi nahi tha.
            "banner": self.banner,
            "failure_kind": self.failure_kind,
            "missing_passes": list(self.missing_passes),
            "missing_sections": list(self.missing_sections),
            "technical_details": list(self.technical),
        }


def evaluate(planned_passes: Sequence[str] = (), done_passes: Sequence[str] = (),
             failure_kind: str = "", failure_reason: str = "",
             source_count: int = 0, errors: Iterable = (),
             technical_details: Iterable = ()) -> RunStatus:
    """
    Status nikaalo — INTENTION se nahi, jo SACH MEIN hua usse.

    RESEARCH INCOMPLETE kab:
      * ek bhi source nahi mila, ya
      * analysis ya final synthesis pass hi poora nahi hua (model failure ke saath)

    PARTIAL kab: kuch chhota hissa (red-team / hypotheses) chhoot gaya, par
    analysis + synthesis dono ho gaye.
    """
    planned = [p for p in planned_passes if p]
    done = {p for p in done_passes if p}
    missing = [p for p in planned if p not in done]
    human, tech = split_messages(errors)
    # Ledger na likha gaya ho to raw error text se hi kind nikaal lo — warna
    # banner "wajah saaf nahi hai" bolta, jabki line mein 429 saaf likha tha.
    if not failure_kind:
        failure_kind = infer_kind(list(errors or []) + list(technical_details or []))
    if not failure_reason:
        failure_reason = _CAUSE.get(failure_kind, "") if failure_kind else ""
    tech = tech + [" ".join(str(t).split()) for t in (technical_details or [])
                   if str(t or "").strip()]
    seen: List[str] = []
    for line in tech:
        if line not in seen:
            seen.append(line)
    tech = seen

    core_missing = [p for p in missing if p in ("analysis", "synthesis")]
    no_sources = source_count <= 0

    status = RunStatus(missing_passes=missing, human_warnings=human,
                       technical=tech, failure_kind=failure_kind or "")

    if no_sources:
        status.code = INCOMPLETE
    elif core_missing:
        # analysis/synthesis ke bina "final answer" kehna hi jhooth hai —
        # wajah model failure ho ya budget, user ke liye natija ek hi hai.
        status.code = INCOMPLETE
    elif missing:
        status.code = PARTIAL
    else:
        status.code = COMPLETE

    if status.code == COMPLETE:
        # Provider attempt beech mein fail hua aur bounded recovery baad mein
        # kaam kar gayi to failure event audit/accounting mein rehna chahiye,
        # lekin final run ko current failure label dena stale aur misleading hai.
        status.failure_kind = ""
        status.reason = ""
        status.banner = ""
        return status

    cause = cause_line(failure_kind, failure_reason)
    if no_sources and not failure_kind:
        cause = "sawal se related ek bhi bharosemand source nahi mila"

    if status.code == INCOMPLETE:
        if failure_kind in _QUOTA_KINDS and len(missing) >= 2:
            status.banner = QUOTA_BANNER
        else:
            gap = _pass_phrase(missing) or "reasoning ke steps"
            searched = ("Sources search ho gaye, lekin " if not no_sources
                        else "Source hi nahi mile, isliye ")
            status.banner = (
                f"Ye research run complete nahi ho paaya kyunki {cause}. "
                f"{searched}{gap} complete nahi hui. Isliye is result ko final "
                f"answer na maanein.")
        status.reason = f"{cause} — {_pass_phrase(missing) or 'reasoning'} adhoora raha"
    else:
        gap = _pass_phrase(missing)
        status.banner = (
            f"Is run ka bada hissa poora hua, par {gap} nahi ho paaya "
            f"({cause}). Isliye ise partial result maanein.")
        status.reason = f"{gap} nahi hua — {cause}"
    return status
