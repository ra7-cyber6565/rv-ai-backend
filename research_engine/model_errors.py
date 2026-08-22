"""
Model error ka ASLI matlab — §7.

Live failure jise ye file theek karti hai:

    ResourceExhausted: 429 You exceeded your current quota ...
    quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier
    retry_delay { seconds: 21 }

Purana code is message ko "transient" maan kar 3 baar retry karta tha, phir
agle model par jaa kar wahi 3 baar — kul 9 bekaar HTTP calls, 6 second sleep,
aur aakhir mein khaali "" (na wajah, na status). DIN ka quota khatam hone par
21 second rukne se kuch nahi badalta: wo model AAJ ke liye gaya.

Ab har error ka ek verdict banta hai jo saaf batata hai:
    * usi model par dobara koshish karni chahiye ya nahi
    * doosre model par jaana chahiye ya nahi
    * is model ko is run ke liye band kar dena chahiye ya nahi
    * poori reasoning rokni chahiye ya nahi (sirf auth failure par)
    * user ko Hinglish mein kya kehna hai (raw protobuf NAHI — §9)

Ye file jaan-boojh kar sirf TEXT dekhti hai, exception class nahi: Google ki
library version ke hisaab se alag-alag class phenkti hai, par message mein code
(429/404/403) aur quota_id hamesha aata hai. Isliye ye offline testable hai.

₹0 rule: yahan koi paid model/service suggest nahi hoti. Fallback sirf usi free
tier ke doosre model par hota hai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── kinds (§7 ki list) ───────────────────────────────────────────────────────
TRANSIENT = "transient_network"
RATE_LIMIT = "rate_limit"
DAILY_QUOTA = "daily_quota"
MODEL_NOT_FOUND = "model_not_found"
INPUT_TOO_LARGE = "input_too_large"
INVALID_REQUEST = "invalid_request"
AUTH = "auth_failure"
SERVER = "server_error"
EMPTY = "empty_response"
UNKNOWN = "unknown"

KINDS = (TRANSIENT, RATE_LIMIT, DAILY_QUOTA, MODEL_NOT_FOUND, INPUT_TOO_LARGE,
         INVALID_REQUEST, AUTH, SERVER, EMPTY, UNKNOWN)

# Har kind ka insaani matlab — user ko yahi dikhta hai, stack trace nahi.
HUMAN: Dict[str, str] = {
    TRANSIENT: "network thoda laDkhaDa gaya (connection/timeout)",
    RATE_LIMIT: "ek minute ki free rate limit lag gayi (per-minute cap)",
    DAILY_QUOTA: "aaj ke liye is model ki free daily limit khatam ho gayi",
    MODEL_NOT_FOUND: "ye model naam is API key ke liye maujood nahi hai",
    INPUT_TOO_LARGE: "research prompt is model ki input/context limit se bada tha",
    INVALID_REQUEST: "reasoning request ka format/provider validation accept nahi hua",
    AUTH: "API key galat hai ya usse permission nahi mili",
    SERVER: "Google ke server ne apni taraf se error diya (5xx)",
    EMPTY: "model ne khaali jawab bheja",
    UNKNOWN: "wajah saaf nahi hai",
}

_DAILY_MARKERS = (
    "perday", "per day", "per-day", "daily limit", "daily quota",
    "requests per day", "generaterequestsperday", "free_tier_requests",
    "free tier requests", "quota exceeded for quota metric",
)
_MINUTE_MARKERS = (
    "perminute", "per minute", "per-minute", "requests per minute",
    "generaterequestsperminute", "input token count per minute",
    "tokens per minute",
)
_QUOTA_MARKERS = ("429", "quota", "resource_exhausted", "resourceexhausted",
                  "rate limit", "ratelimit", "too many requests")
_INPUT_TOO_LARGE_MARKERS = (
    "input token count exceeds", "input tokens exceed", "too many input tokens",
    "request too large", "payload too large", "request payload size exceeds",
    "context length", "context window", "maximum context", "max context",
    "token limit exceeded", "exceeds the maximum number of tokens",
)
_INVALID_REQUEST_MARKERS = ("invalid argument", "invalidargument", "bad request", "400")
_MODEL_WORD_MARKERS = ("model", "models/", "generative model")
_MODEL_MISSING_MARKERS = (
    "not found", "notfound", "is not supported", "model not supported",
    "unknown model", "unknown name", "does not exist",
)
_AUTH_MARKERS = ("api key not valid", "api_key_invalid", "401", "403",
                 "permission denied", "permissiondenied", "unauthenticated",
                 "unauthorized", "api key expired")
_SERVER_MARKERS = ("500", "502", "503", "504", "internal error", "internal server",
                   "unavailable", "backend error", "service is currently")
_TRANSIENT_MARKERS = ("timeout", "timed out", "deadline", "connection",
                      "temporarily", "ssl", "broken pipe", "reset by peer",
                      "dns", "network")

_RETRY_RES = (
    re.compile(r"retry_delay\s*\{\s*seconds:\s*(\d+)", re.I),
    re.compile(r"retry(?:\s+in|\s+after)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*s", re.I),
    re.compile(r"retry-after[\"'\s:]+(\d+)", re.I),
)


@dataclass
class ErrorVerdict:
    """Ek error par poora faisla — kya karna hai aur user ko kya batana hai."""
    kind: str = UNKNOWN
    retry_same_model: bool = False
    try_other_model: bool = True
    disable_model: bool = False       # is run mein is model ko chhodo
    permanent: bool = False           # naam hi galat hai — poore process ke liye chhodo
    stop_all: bool = False            # sirf auth: aur koshish bekaar hai
    retry_after: float = 0.0
    detail: str = ""                  # technical line (report ke sabse neeche)

    @property
    def human(self) -> str:
        return HUMAN.get(self.kind, HUMAN[UNKNOWN])

    def to_dict(self) -> Dict:
        return {"kind": self.kind, "human": self.human,
                "retry_same_model": self.retry_same_model,
                "try_other_model": self.try_other_model,
                "disable_model": self.disable_model,
                "permanent": self.permanent, "stop_all": self.stop_all,
                "retry_after": self.retry_after, "detail": self.detail[:300]}


def retry_after_seconds(text: str) -> float:
    for rx in _RETRY_RES:
        m = rx.search(text or "")
        if m:
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _has(text: str, markers) -> bool:
    return any(m in text for m in markers)


def classify_text(text: str, detail: str = "") -> ErrorVerdict:
    """Error ke text se verdict. (Exception ke bina bhi testable.)"""
    low = " ".join((text or "").lower().split())
    v = ErrorVerdict(detail=detail or (text or "")[:300])

    if not low:
        v.kind = UNKNOWN
        v.retry_same_model = True
        return v

    # 1. AUTH — sabse pehle. Key galat ho to doosra model bhi nahi chalega,
    #    isliye poori reasoning wahin rok dena imaandaar hai.
    if _has(low, _AUTH_MARKERS):
        v.kind = AUTH
        v.retry_same_model = False
        v.try_other_model = False
        v.stop_all = True
        return v

    # 2. INPUT/CONTEXT TOO LARGE — model zinda ho sakta hai. Caller ek baar
    #    source evidence ko compact karke isi model par safe retry kar sakta hai.
    if _has(low, _INPUT_TOO_LARGE_MARKERS):
        v.kind = INPUT_TOO_LARGE
        v.retry_same_model = True
        v.try_other_model = True
        return v

    # 3. MODEL NOT FOUND — sirf model-specific signal par. Generic
    #    InvalidArgument/unsupported text ko model naam ki maut mat banao:
    #    location, payload aur request validation bhi wahi words use karte hain.
    model_word = _has(low, _MODEL_WORD_MARKERS)
    model_missing = _has(low, _MODEL_MISSING_MARKERS)
    if model_word and (model_missing or "404" in low):
        v.kind = MODEL_NOT_FOUND
        v.retry_same_model = False
        v.disable_model = True
        v.permanent = True
        return v

    # 4. INVALID REQUEST — permanent model failure nahi. Doosra model/provider
    #    try ho sakta hai, lekin isi unchanged request ka blind retry bekaar hai.
    if _has(low, _INVALID_REQUEST_MARKERS):
        v.kind = INVALID_REQUEST
        v.retry_same_model = False
        v.try_other_model = True
        return v

    # 5. QUOTA — asli farak: DIN ka quota vs MINUTE ki rate limit.
    if _has(low, _QUOTA_MARKERS):
        v.retry_after = retry_after_seconds(low)
        if _has(low, _DAILY_MARKERS) and not _has(low, _MINUTE_MARKERS):
            v.kind = DAILY_QUOTA
            v.retry_same_model = False      # aaj ke liye khatam — rukna bekaar
            v.disable_model = True
            return v
        if _has(low, _MINUTE_MARKERS):
            v.kind = RATE_LIMIT
            v.retry_same_model = True
            return v
        # 429 par per-day/per-minute ka zikr na ho: ek baar ruk kar dekhte hain,
        # phir agla model. (Andhe 3 retry nahi.)
        v.kind = RATE_LIMIT
        v.retry_same_model = True
        return v

    # 4. SERVER 5xx — Google ki taraf ki dikkat, retry ka matlab banta hai.
    if _has(low, _SERVER_MARKERS):
        v.kind = SERVER
        v.retry_same_model = True
        return v

    # 5. Network/timeout
    if _has(low, _TRANSIENT_MARKERS):
        v.kind = TRANSIENT
        v.retry_same_model = True
        return v

    if "khaali" in low or "empty response" in low:
        v.kind = EMPTY
        v.retry_same_model = True
        return v

    v.kind = UNKNOWN
    v.retry_same_model = True
    return v


def classify(exc: BaseException) -> ErrorVerdict:
    text = f"{type(exc).__name__}: {exc}"
    return classify_text(text, detail=text)


# ── run-level ledger (§14 ka honest API accounting bhi isse milta hai) ───────
@dataclass
class FailureLedger:
    """
    Ek run mein kaun sa model kis wajah se gira — ginti ke saath.
    Report isse do cheezein banati hai: user-facing wajah (§9) aur audit (§14).
    """
    events: List[Dict] = field(default_factory=list)
    disabled: Dict[str, str] = field(default_factory=dict)   # model -> kind

    def add(self, model: str, label: str, verdict: ErrorVerdict,
            attempt: int = 1) -> None:
        self.events.append({"model": model, "label": label, "kind": verdict.kind,
                            "attempt": attempt, "human": verdict.human,
                            "detail": verdict.detail[:300]})
        if verdict.disable_model:
            self.disabled[model] = verdict.kind

    def kinds(self) -> List[str]:
        out: List[str] = []
        for e in self.events:
            if e["kind"] not in out:
                out.append(e["kind"])
        return out

    def worst_kind(self) -> str:
        """User ko batane ke liye sabse maayne wala kind."""
        order = (AUTH, DAILY_QUOTA, RATE_LIMIT, INPUT_TOO_LARGE,
                 INVALID_REQUEST, MODEL_NOT_FOUND, SERVER, TRANSIENT, EMPTY,
                 UNKNOWN)
        present = set(self.kinds())
        for k in order:
            if k in present:
                return k
        return ""

    def is_empty(self) -> bool:
        return not self.events

    def summary(self) -> str:
        if not self.events:
            return ""
        by_kind: Dict[str, int] = {}
        for e in self.events:
            by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
        bits = [f"{HUMAN.get(k, k)} ×{n}" for k, n in by_kind.items()]
        note = "; ".join(bits)
        if self.disabled:
            note += (" | is run mein band kiye gaye model: "
                     + ", ".join(sorted(self.disabled)))
        return note

    def to_dict(self) -> Dict:
        return {"events": self.events[:20], "disabled": dict(self.disabled),
                "worst_kind": self.worst_kind(), "summary": self.summary()}
