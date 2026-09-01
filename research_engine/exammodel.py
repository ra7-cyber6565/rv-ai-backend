"""EXAM / PADHAI ka model — farmaish parse, contract, aur ASLI naap.

Kyun ye file bani (#171): "RPF SI ka paper banao" aur "math basic se strong
kaise karun" jaisi farmaish aaj tak AAM raste par chalti thi. Naapa gaya
(#171a audit): dono par `domain` khaali, koi specialist lane nahi, koi contract
nahi — yaani jawab me ye kabhi tay nahi hota tha ki *poora syllabus cover hua
ya nahi*, *answer key hai ya nahi*, *do question ek jaise hain ya nahi*, ya
*plan ka time jodne par bharosa hai ya nahi*. `exam_intelligence.py` bhi hai
par wo sirf `api/exam_routes.py` se chalta hai aur usme user ko purane paper
ka structured data KHUD bhejna padta hai — chat ki farmaish se wo kabhi nahi
chalta.

Is file ka kaam trademodel.py ke jaisa hi hai, aur jaan-boojh kar usi shakl
me likha gaya hai:

    ask_of()   → farmaish kya thi (exam, subject, level, ginti, bhasha, kind)
    lane_queries() → padhne ke liye query BANATA hai (chalata nahi)
    naap ke funcs → coverage / difficulty / duplicate / solvability / time
    gate()     → har contract point par MET / NOT_MET / NOT_MEASURED

Do niyam jo yahan sabse zaroori hain:

1.  DERIVE, NEVER DECLARE. Insaan ke padhne wala `observed` string kabhi
    wapas parse nahi hota; faisla structured number se hota hai.
2.  NAAP na ho to NOT_MEASURED — "theek hai" nahi. App ka banaya paper asli
    exam paper nahi hai, aur app ki banayi answer key official key nahi hai;
    ye dono baat jawab me hamesha likhi jaati hai.

Ek bhi Gemini call nahi, ek bhi network call nahi, ₹0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "exammodel-1"


# ── contract point ke teen haal (trademodel wala hi shabd) ───────────────────
MET = "MET"
NOT_MET = "NOT_MET"
NOT_MEASURED = "NOT_MEASURED"
CHECK_STATUSES: Tuple[str, ...] = (MET, NOT_MET, NOT_MEASURED)


# ── IMAANDAARI ke pakke sach (ye badalte nahi) ───────────────────────────────
PAPER_IS_PRACTICE_ONLY = True     # app ka banaya paper practice ke liye hai
IS_EXAM_AUTHORITY = False         # app kisi board/commission ka hissa nahi
ANSWER_KEY_IS_APP_MADE = True     # key app ne banayi, official key nahi
QUESTION_PREDICTION_PROMISED = False  # "yahi question aayega" ka waada nahi
SCORE_PROMISED = False            # kitne number aayenge ka waada nahi
LEAKED_PAPER_USED = False         # leak/paid question bank nahi chhua
NETWORK_USED = False              # query BANATA hai, chalata nahi
GEMINI_CALLS = 0                  # is stage me ek bhi model call nahi
DETERMINISTIC = True
PROVIDER_COST = "₹0"

NOT_OFFICIAL_NOTE = ("Ye paper app ne PRACTICE ke liye banaya hai — kisi board "
                     "ya commission ka asli paper nahi, aur answer key bhi app "
                     "ki banayi hui hai (official key nahi).")

# Jo ₹0 par naapa hi nahi ja sakta — ye kabhi MET nahi hoga.
CANNOT_MEASURE: Tuple[str, ...] = (
    "aane wale exam ka asli paper",
    "official answer key jo abhi chhapi hi nahi",
    "student ke asli number",
    "paid question bank aur coaching ka andar ka material",
)


# ── chhote helper (trademodel/songcraft wali aadat) ──────────────────────────
_WORD_RE = re.compile(r"[a-z0-9ऀ-ॿ]+")


def _norm(text: Any) -> str:
    """Lowercase + ek-space — cue milane ke liye."""
    return " ".join(str(text or "").lower().split())


def _has(norm_text: str, cue: str) -> bool:
    """Poora shabd milta hai ya nahi (beech me nahi ghusna)."""
    if not cue:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(cue) + r"(?![a-z0-9])",
                     norm_text) is not None


def _matched(norm_text: str, cues: Iterable[str]) -> List[str]:
    return [cue for cue in cues if _has(norm_text, cue)]


def _words(text: Any) -> List[str]:
    return _WORD_RE.findall(_norm(text))


_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM_WORDS: Dict[str, int] = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5,
    "panch": 5, "chhah": 6, "cheh": 6, "saat": 7, "aath": 8, "nau": 9,
    "das": 10, "dus": 10, "bees": 20, "pachas": 50, "pachaas": 50,
    "sau": 100, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20,
    "fifty": 50, "hundred": 100,
}


def _int_near(norm_text: str, cues: Sequence[str], limit: int = 4) -> int:
    """`<ginti> <cue>` ya `<cue> <ginti>` — digit, Devanagari ank ya shabd.

    `limit` = kitne shabd door tak dekhein. 0 = mila hi nahi.
    """
    tokens = _norm(norm_text).translate(_DEV_DIGITS).split()
    for index, token in enumerate(tokens):
        bare = token.strip(".,:;()[]")
        if bare not in cues:
            continue
        window = ([tokens[max(0, index - step)] for step in range(1, limit + 1)]
                  + tokens[index + 1:index + 1 + limit])
        for near in window:
            digits = re.sub(r"[^0-9]", "", near)
            if digits:
                return int(digits[:4])
            if near in _NUM_WORDS:
                return _NUM_WORDS[near]
    return 0


# ── EXAM ka naam: band list se azaadi ────────────────────────────────────────
# Yahan koi "sab exam ki list" nahi hai — aur ho bhi nahi sakti. Do raste hain:
#   1. saaf-saaf exam wala shabd ("exam", "pariksha", "bharti", "tier", ...)
#   2. ACRONYM shakl ka naam (RPF, SSC, CGL, NEET, UPSC) — shakl se pehchana
#      jaata hai, kisi list se nahi. Isliye kal naya exam aaye to bhi chalega.
EXAM_LIST_IS_NOT_EXHAUSTIVE = True

_EXAM_WORD_CUES: Tuple[str, ...] = (
    "exam", "exams", "pariksha", "pareeksha", "priksha", "paper", "question",
    "questions", "prashn", "prshn", "mock", "test", "quiz", "practice",
    "bharti", "bharati", "vacancy", "recruitment", "notification", "syllabus",
    "silabus", "tier", "prelims", "prelim", "mains", "main", "board",
    "entrance", "admission", "cutoff", "cut-off", "omr", "objective",
)
_LEVEL_CUES: Tuple[str, ...] = (
    "class", "kaksha", "std", "standard", "grade", "tier", "level", "stage",
    "paper", "prelims", "mains", "basic", "beginner", "shuruaat", "advance",
    "advanced", "intermediate",
)
# Acronym shakl: 2-6 bade akshar, ya ANK ke saath ("CGL", "SI", "NTPC", "10th").
_ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})(?![a-z])")
# Bahut aam bade-akshar shabd jo exam ka naam nahi hote — inhe naam maan lena
# jhooth hota (naapa gaya: "PDF me MATH ka paper banao" me teen "naam" ban
# rahe the).
_ACRONYM_STOP: Tuple[str, ...] = (
    "PDF", "AI", "OK", "HI", "MATH", "MATHS", "GK", "GS", "ME", "TO", "OR",
    "KA", "KI", "KE", "HE", "IT", "IS", "AND", "THE", "FOR", "NOT", "NEW",
    "OMR", "MCQ", "MCQS", "PAPER", "TEST", "EXAM", "PLAN", "HINDI", "ENGLISH",
)


def exam_names(question: str) -> List[str]:
    """Exam ka naam — ACRONYM ki shakl se, kisi hand-typed list se nahi."""
    text = str(question or "")
    found: List[str] = []
    for token in _ACRONYM_RE.findall(text):
        if token in _ACRONYM_STOP or token in found:
            continue
        found.append(token)
    return found


def exam_word_cues(question: str) -> List[str]:
    return _matched(_norm(question), _EXAM_WORD_CUES)


# ── LANE KA TAALA: do signal chahiye, ek nahi ────────────────────────────────
# trademodel/market lane ka wahi niyam. Sirf "exam" likha hona kaafi nahi
# (warna "exam ka stress kaise kam kare" bhi paper banane lag jaayega), aur
# sirf "banao" kaafi nahi (warna gaana/nibandh exam lane me ghus jaayega).
_EXAM_RE = re.compile(
    r"\bexam[s]?\b|\bpariksha\b|\bpareeksha\b|\bsyllabus\b|\bsilabus\b|"
    r"\bquestion\s+paper\b|\bprashn\s*patra\b|\bmock\s+test\b|\bmock\b|"
    r"\bpractice\s+(?:paper|set|test)\b|\bprevious\s+year\b|\bpyq[s]?\b|"
    r"\bsample\s+paper\b|\bmodel\s+paper\b|\bboard\s+exam\b|\btier[-\s]?\d\b|"
    r"\bprelims\b|\bmains\b|\bcut[-\s]?off\b|\bnegative\s+marking\b|"
    r"\bstudy\s+plan\b|\btime\s*table\b|\btimetable\b|\brevision\b|"
    r"\bpadhai\b|\bpadhaai\b|\bpdhai\b|\btayyari\b|\btaiyari\b|\bpreparation\b",
    re.IGNORECASE)
# "kuch BANAO / kaise karun" — bina iske exam shabd sirf topic hai.
_WANT_RE = re.compile(
    r"\bbanao\b|\bbnao\b|\bbanaa?o\b|\bbana\s+do\b|\bbna\s+do\b|"
    r"\bbana\s+kar\b|\btayyar\s+kar\b|\bcreate\b|\bgenerate\b|\bbuild\b|"
    r"\bdesign\b|\bset\s+banao\b|\bde\s+do\b|\bchahiye\b|\bkaise\s+kar\w*\b|"
    r"\bkaise\s+padh\w*\b|\bstrong\s+kar\w*\b|\bplan\b|\btime\s*table\b|"
    r"\bprepare\b|\bpreparation\b|\bstrategy\b|\bschedule\b",
    re.IGNORECASE)
# "SEEKHNE" ki maang — "banao" se alag rakhi gayi hai, jaan-boojh kar.
# Kyun alag: subject ka naam (math/science/polity) akela padhai ka saboot nahi
# hai, aur "banao" ke saath jodne par "hindi me gaana banao" bhi exam lane me
# ghus jaata. Isliye subject-waala rasta sirf is SEEKHNE ki maang par khulta
# hai. #171b probe me naapa gaya: "math basic se strong kaise karun 30 din me"
# is shart ke bina lane se bahar reh gaya tha.
_LEARN_RE = re.compile(
    r"\bstrong\s+kar\w*\b|\bmajboot\b|\bmazboot\b|\bimprove\b|"
    r"\bkaise\s+(?:padh|pdh|seekh|sikh|yaad|prepare|karu|karun|karoon|"
    r"kru|karna)\w*\b|\bbasic\s+se\b|\bbasics\s+se\b|\bzero\s+se\b|"
    r"\bshuru\s+se\b|\bshuruaat\s+se\b|\bmaster\s+kar\w*\b|\bkamzor\b|"
    r"\bkamjor\b|\bweak\b|\bconcept\s+clear\b|\bsudhar\w*\b|"
    r"\bpakka\s+kar\w*\b|\bclear\s+kar\w*\b",
    re.IGNORECASE)

NOT_ASKED_REASON = ("farmaish exam/padhai jaisi nahi lagi, isliye exam-study "
                    "lane nahi kholi")


def _exam_signal(text: str) -> bool:
    """Exam ki cheez ka naam mila ya nahi — regex se YA exam-shabd se.

    Ek hi jagah se `is_request` aur `request_reason` dono poochhte hain (do
    jagah do faisla = agli baar wahi bug).
    """
    return bool(_EXAM_RE.search(text)) or bool(exam_word_cues(text))


def _subject_learn_signal(text: str) -> bool:
    """Subject ka naam + SEEKHNE ki saaf maang = padhai ki farmaish.

    Dono shart zaroori hain. Subject list wahi purani `SUBJECTS` table hai,
    koi nayi haath se likhi list nahi.
    """
    return bool(subject_cues(text)) and bool(_LEARN_RE.search(text))


def is_request(question: str) -> bool:
    """Exam/padhai ki farmaish hai ya nahi — DO signal par, ek par nahi.

    Do raste, dono me do-do shart: (exam cheez + banane/seekhne ki maang)
    YA (subject ka naam + seekhne ki maang).
    """
    text = str(question or "")
    if _exam_signal(text) and bool(_WANT_RE.search(text)):
        return True
    return _subject_learn_signal(text)


def request_reason(question: str) -> str:
    """Taala khula ya band — aur KYUN. Dono hamesha likhe jaate hain."""
    text = str(question or "")
    exam = _exam_signal(text)
    want = bool(_WANT_RE.search(text))
    subject = bool(subject_cues(text))
    learn = bool(_LEARN_RE.search(text))
    if exam and want:
        return ("exam-study lane chali — sawaal me exam/padhai ki cheez ka naam "
                "bhi hai aur kuch BANANE ya seekhne ki maang bhi")
    if subject and learn:
        return ("exam-study lane chali — subject ka naam hai aur use seekhne/"
                "strong karne ki saaf maang hai")
    if exam and not want:
        return ("exam ki baat hai par kuch banane/seekhne ki maang nahi — ye "
                "padhne ka sawaal maana gaya, exam lane nahi kholi")
    if subject and not learn:
        return ("subject ka naam hai par seekhne/strong karne ki maang nahi — "
                "sirf naam se exam lane nahi kholi")
    if want and not exam:
        return ("kuch banane ki maang hai par exam/padhai ki koi cheez ka naam "
                "nahi — exam lane nahi kholi")
    return NOT_ASKED_REASON


# ── farmaish ki KISM: paper, plan, ya dono ───────────────────────────────────
KIND_PAPER = "paper"     # "question paper / mock / practice set banao"
KIND_PLAN = "plan"       # "kaise strong karun / time-table / study plan"
KIND_BOTH = "both"       # dono maange gaye
KIND_NONE = ""
KINDS: Tuple[str, ...] = (KIND_PAPER, KIND_PLAN, KIND_BOTH)

_PAPER_CUES: Tuple[str, ...] = (
    "paper", "papers", "question", "questions", "prashn", "prshn", "mcq",
    "mcqs", "quiz", "mock", "test", "set", "sets", "practice", "sample",
    "objective", "omr", "worksheet", "assignment",
)
_PLAN_CUES: Tuple[str, ...] = (
    "plan", "planning", "timetable", "schedule", "routine", "strategy",
    "roadmap", "kaise", "kese", "strong", "improve", "sudhar", "revision",
    "revise", "tayyari", "taiyari", "preparation", "prepare", "padhai",
    "padhaai", "pdhai", "syllabus", "cover", "complete", "poora", "pura",
)

# ── SUBJECT: list poori nahi hai, aur ye baat likhi jaati hai ────────────────
SUBJECT_LIST_IS_NOT_EXHAUSTIVE = True
SUBJECTS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("maths", "ganit/maths",
     ("math", "maths", "mathematics", "ganit", "gnit", "arithmetic", "algebra",
      "geometry", "trigonometry", "calculus", "mensuration", "statistics")),
    ("reasoning", "reasoning/tarkshakti",
     ("reasoning", "tarkshakti", "tark", "logical", "logic", "aptitude",
      "puzzle", "series", "analogy")),
    ("gk", "GK/samanya gyan",
     ("gk", "gs", "general knowledge", "samanya gyan", "samanya", "current "
      "affairs", "current", "static gk")),
    ("science", "vigyan/science",
     ("science", "vigyan", "vigyaan", "physics", "chemistry", "biology",
      "bhautiki", "rasayan", "jeev")),
    ("english", "English",
     ("english", "angrezi", "grammar", "vocabulary", "comprehension")),
    ("hindi_subject", "Hindi (vishay)",
     ("vyakaran", "vyakran", "hindi vyakaran", "samas", "sandhi", "muhavare")),
    ("history", "itihas/history",
     ("history", "itihas", "itihaas", "medieval", "ancient", "modern india")),
    ("geography", "bhugol/geography",
     ("geography", "bhugol", "bhoogol", "map", "climate", "river")),
    ("polity", "rajvyavastha/polity",
     ("polity", "rajvyavastha", "samvidhan", "constitution", "civics")),
    ("economy", "arthvyavastha/economy",
     ("economy", "arthvyavastha", "economics", "budget", "gdp")),
    ("computer", "computer",
     ("computer", "computers", "ms office", "excel", "internet")),
    ("law", "kanoon/law",
     ("law", "kanoon", "ipc", "crpc", "act", "constitutional law")),
)
SUBJECT_KEYS: Tuple[str, ...] = tuple(key for key, _l, _c in SUBJECTS)
_SUBJECT_LABELS: Dict[str, str] = {key: label for key, label, _c in SUBJECTS}
# Dikhane ka label aur DHOONDHNE ka shabd ek nahi hai. Label Hinglish rehta hai
# (jawab me wahi padha jaata), par search term English rakha gaya hai: board/
# commission ki apni syllabus PDF aur pattern page English naam se hi milte
# hain. #171b probe me naapa gaya — label se anchor banane par query
# "ganit official syllabus notification pdf" bani thi, jo official page tak
# nahi le jaati.
_SUBJECT_SEARCH: Dict[str, str] = {
    "maths": "mathematics",
    "reasoning": "reasoning aptitude",
    "gk": "general knowledge",
    "science": "science",
    "english": "English language",
    "hindi_subject": "Hindi grammar",
    "history": "history",
    "geography": "geography",
    "polity": "polity constitution",
    "economy": "economy",
    "computer": "computer knowledge",
    "law": "law",
}


def subject_cues(question: str) -> List[str]:
    """Kaun-kaun subject ka naam saaf mila (kram fix, taaki naap dohraye)."""
    norm = _norm(question)
    return [key for key, _label, cues in SUBJECTS if _matched(norm, cues)]


# ── bhasha: sirf wahi jo saaf maangi gayi ────────────────────────────────────
LANG_HINDI = "hindi"
LANG_ENGLISH = "english"
LANG_BOTH = "bilingual"
_HINDI_CUES: Tuple[str, ...] = ("hindi", "hindee", "devanagari", "हिंदी")
_ENGLISH_CUES: Tuple[str, ...] = ("english", "angrezi", "अंग्रेजी")


def language_of(question: str) -> str:
    """Paper kis bhasha me maanga gaya — na maanga ho to khaali (jhooth nahi)."""
    norm = _norm(question)
    hindi = bool(_matched(norm, _HINDI_CUES))
    english = bool(_matched(norm, _ENGLISH_CUES))
    if hindi and english:
        return LANG_BOTH
    if hindi:
        return LANG_HINDI
    if english:
        return LANG_ENGLISH
    return ""


# ── ginti ke cue (question, marks, minute, din) ──────────────────────────────
_QCOUNT_CUES: Tuple[str, ...] = ("question", "questions", "prashn", "prshn",
                                 "sawaal", "sawal", "mcq", "mcqs", "q")
_MARK_CUES: Tuple[str, ...] = ("marks", "mark", "ank", "number", "numbers")
_MINUTE_CUES: Tuple[str, ...] = ("minute", "minutes", "min", "mins")
_HOUR_CUES: Tuple[str, ...] = ("hour", "hours", "ghanta", "ghante", "hr", "hrs")
_DAY_CUES: Tuple[str, ...] = ("din", "day", "days", "dino", "dinon")
_WEEK_CUES: Tuple[str, ...] = ("hafta", "hafte", "week", "weeks", "saptah")

_NEGATIVE_RE = re.compile(
    r"\bnegative\s+marking\b|\bnegative\s+mark\b|\bminus\s+marking\b|"
    r"\brinatmak\b|\b1/4\s*mark\b|\b0\.25\s*mark\b", re.IGNORECASE)
_KEY_RE = re.compile(
    r"\banswer\s*key\b|\bans\s*key\b|\buttar\s*kunji\b|\bkey\s+bhi\b|"
    r"\bsolution[s]?\b|\bhal\b|\bsamjha\w*\b|\bstep\s*by\s*step\b|"
    r"\bexplanation\b", re.IGNORECASE)
_SOLUTION_RE = re.compile(
    r"\bstep\s*by\s*step\b|\bsolution[s]?\b|\bhal\s+ke\s+saath\b|"
    r"\bsamjha\s*kar\b|\bexplanation\b|\bmethod\b|\btarika\b", re.IGNORECASE)
_DIFFICULTY_RE = re.compile(
    r"\beasy\b|\bmedium\b|\bhard\b|\bdifficult\b|\baasan\b|\bkathin\b|"
    r"\bmushkil\b|\bdifficulty\b|\blevel\s+wise\b|\bmix\b|\bmixed\b",
    re.IGNORECASE)
_PATTERN_RE = re.compile(
    r"\bprevious\s+year\b|\bpyq[s]?\b|\bpichhle\s+saal\b|\bpichle\s+saal\b|"
    r"\bpast\s+paper[s]?\b|\bpattern\b|\btrend\b|\bexam\s+pattern\b|"
    r"\bweightage\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExamAsk:
    """Farmaish me jo SAAF maanga gaya — na kam, na zyada."""

    asked: bool = False
    reason: str = NOT_ASKED_REASON
    kind: str = KIND_NONE
    exams: Tuple[str, ...] = ()
    subjects: Tuple[str, ...] = ()
    subject_labels: Tuple[str, ...] = ()
    level: str = ""
    language: str = ""
    question_count: int = 0
    total_marks: int = 0
    duration_minutes: int = 0
    days_available: int = 0
    negative_marking: bool = False
    wants_answer_key: bool = False
    wants_solutions: bool = False
    wants_difficulty_mix: bool = False
    wants_past_pattern: bool = False
    matched_cues: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asked": self.asked,
            "reason": self.reason,
            "kind": self.kind,
            "exams": list(self.exams),
            "subjects": list(self.subjects),
            "subject_labels": list(self.subject_labels),
            "level": self.level,
            "language": self.language,
            "question_count": self.question_count,
            "total_marks": self.total_marks,
            "duration_minutes": self.duration_minutes,
            "days_available": self.days_available,
            "negative_marking": self.negative_marking,
            "wants_answer_key": self.wants_answer_key,
            "wants_solutions": self.wants_solutions,
            "wants_difficulty_mix": self.wants_difficulty_mix,
            "wants_past_pattern": self.wants_past_pattern,
            "matched_cues": list(self.matched_cues),
            "exam_list_is_not_exhaustive": EXAM_LIST_IS_NOT_EXHAUSTIVE,
            "subject_list_is_not_exhaustive": SUBJECT_LIST_IS_NOT_EXHAUSTIVE,
            "paper_is_practice_only": PAPER_IS_PRACTICE_ONLY,
            "answer_key_is_app_made": ANSWER_KEY_IS_APP_MADE,
        }


_CLASS_RE = re.compile(
    r"\b(?:class|kaksha|std|standard|grade)\s*(\d{1,2})\b", re.IGNORECASE)
_TIER_RE = re.compile(r"\btier[-\s]?(\d)\b|\bpaper[-\s]?(\d)\b", re.IGNORECASE)
_STAGE_RE = re.compile(r"\bprelims?\b|\bmains?\b", re.IGNORECASE)


def level_of(question: str) -> str:
    """Level wahi jo saaf likha ho — "class 10", "tier 1", "prelims"."""
    text = str(question or "")
    got = _CLASS_RE.search(text)
    if got:
        return f"class-{int(got.group(1))}"
    got = _TIER_RE.search(text)
    if got:
        number = got.group(1) or got.group(2)
        label = "tier" if got.group(1) else "paper"
        return f"{label}-{int(number)}"
    got = _STAGE_RE.search(text)
    if got:
        return _norm(got.group(0)).rstrip("s")
    norm = _norm(text)
    if _matched(norm, ("basic", "beginner", "shuruaat", "zero se", "zero")):
        return "basic"
    if _matched(norm, ("advance", "advanced")):
        return "advanced"
    return ""


def kind_of(question: str) -> str:
    """Paper maanga, plan maanga, ya dono — cue ki ginti se, andaaze se nahi."""
    norm = _norm(question)
    paper = bool(_matched(norm, _PAPER_CUES))
    plan = bool(_matched(norm, _PLAN_CUES))
    if paper and plan:
        return KIND_BOTH
    if paper:
        return KIND_PAPER
    if plan:
        return KIND_PLAN
    return KIND_NONE


def ask_of(question: str) -> ExamAsk:
    """Poori farmaish ek jagah — ek bhi Gemini call nahi."""
    text = str(question or "")
    norm = _norm(text)
    reason = request_reason(text)
    if not is_request(text):
        return ExamAsk(asked=False, reason=reason)

    subjects = subject_cues(text)
    hours = _int_near(norm, _HOUR_CUES)
    minutes = _int_near(norm, _MINUTE_CUES)
    if not minutes and hours:
        minutes = hours * 60
    days = _int_near(norm, _DAY_CUES)
    weeks = _int_near(norm, _WEEK_CUES)
    if not days and weeks:
        days = weeks * 7

    cues = sorted(set(exam_word_cues(text) + _matched(norm, _PAPER_CUES)
                      + _matched(norm, _PLAN_CUES) + _matched(norm, _LEVEL_CUES)))
    return ExamAsk(
        asked=True,
        reason=reason,
        kind=kind_of(text),
        exams=tuple(exam_names(text)),
        subjects=tuple(subjects),
        subject_labels=tuple(_SUBJECT_LABELS[key] for key in subjects),
        level=level_of(text),
        language=language_of(text),
        question_count=_int_near(norm, _QCOUNT_CUES),
        total_marks=_int_near(norm, _MARK_CUES),
        duration_minutes=minutes,
        days_available=days,
        negative_marking=bool(_NEGATIVE_RE.search(text)),
        wants_answer_key=bool(_KEY_RE.search(text)),
        wants_solutions=bool(_SOLUTION_RE.search(text)),
        wants_difficulty_mix=bool(_DIFFICULTY_RE.search(text)),
        wants_past_pattern=bool(_PATTERN_RE.search(text)),
        matched_cues=tuple(cues),
    )


# ── PADHNE ka lane: query BANATA hai, chalata nahi ───────────────────────────
# Trading me "institutional-first" tha; yahan "OFFICIAL-first" hai — jo board
# ya commission khud chhapta hai wahi syllabus ka sach hai, coaching ka blog
# nahi. Lane ka naam label me jaata hai taaki audit me dikhe kaun kya laaya.
LANE_OFFICIAL = "official"      # board/commission ka apna syllabus/notification
LANE_TEXTBOOK = "textbook"      # NCERT jaisi padhne wali kitaab / curriculum
LANE_PEDAGOGY = "pedagogy"      # kaise padhein — research (spacing, testing)
LANE_PRACTICE = "practice"      # khule practice/PYQ resource
STUDY_LANES: Tuple[str, ...] = (LANE_OFFICIAL, LANE_TEXTBOOK, LANE_PEDAGOGY,
                                LANE_PRACTICE)
MAX_STUDY_QUERIES = 12
QUICK_STUDY_QUERIES = 4

# Pedagogy lane ki query TOPIC se nahi, TAREEQE se bani hai — ye wahi cheez hai
# jo "math basic se strong kaise karun" ka asli jawab deti hai (spaced
# repetition, retrieval practice, interleaving, deliberate practice).
_PEDAGOGY_QUERIES: Tuple[str, ...] = (
    "spaced repetition retrieval practice learning research",
    "interleaving practice problems mathematics learning study",
    "deliberate practice skill acquisition evidence",
    "formative assessment feedback learning gains study",
)


def _subject_terms(ask: ExamAsk) -> List[str]:
    """Subject ke naam DHOONDHNE layak shakl me (khaali ho to khaali).

    `_SUBJECT_SEARCH` me na mile to label ka pehla hissa hi le liya jaata hai —
    naya subject jodne par query khaali nahi rehni chahiye.
    """
    terms: List[str] = []
    for key in ask.subjects:
        term = _SUBJECT_SEARCH.get(key, "")
        if not term:
            term = _SUBJECT_LABELS.get(key, "").split("/")[0].strip()
        if term:
            terms.append(term)
    return terms


def _anchor(ask: ExamAsk) -> str:
    """Query ka anchor: exam ka naam pehle, warna subject, warna level."""
    if ask.exams:
        return " ".join(ask.exams[:2])
    terms = _subject_terms(ask)
    if terms:
        return terms[0]
    return ask.level.replace("-", " ") if ask.level else ""


def _study_groups(ask: Optional[ExamAsk] = None
                  ) -> List[Tuple[str, str, List[str]]]:
    """(lane, why, queries) — OFFICIAL pehle, phir kitaab, phir tareeqa."""
    ask = ask or ExamAsk()
    if not ask.asked:
        return []
    anchor = _anchor(ask)
    level = ask.level.replace("-", " ")
    subjects = _subject_terms(ask)
    groups: List[Tuple[str, str, List[str]]] = []

    official: List[str] = []
    if anchor:
        official.append(f"{anchor} official syllabus notification pdf")
    # #171d ke probe me naapa gaya kharcha: "math basic se strong kaise karun"
    # par bhi "mathematics exam pattern marks negative marking official" chali
    # jaati thi. Us farmaish me na kisi exam ka naam hai, na paper maanga gaya
    # hai — yaani pattern/negative-marking ka kaam hi nahi. Query HATAAYI nahi
    # gayi, sirf apni jagah maangti hai: exam ka naam ho, ya paper ki farmaish
    # ho. RPF SI wale ask par ye pehle jaisi hi chalti hai.
    if anchor and (ask.exams or ask.kind in (KIND_PAPER, KIND_BOTH)):
        official.append(f"{anchor} exam pattern marks negative marking official")
    if anchor and level:
        official.append(f"{anchor} {level} syllabus official")
    if official:
        groups.append((LANE_OFFICIAL,
                       "syllabus ka sach board/commission ka apna document hai",
                       official))

    textbook: List[str] = []
    for term in subjects[:3]:
        textbook.append(f"{term} {level} syllabus textbook chapters list".strip())
    if not subjects and anchor:
        textbook.append(f"{anchor} recommended textbook chapters")
    if textbook:
        groups.append((LANE_TEXTBOOK,
                       "topic ka asli daayra padhne wali kitaab se aata hai",
                       textbook))

    if ask.kind in (KIND_PLAN, KIND_BOTH):
        groups.append((LANE_PEDAGOGY,
                       "kaise padhein ka jawab research se aata hai, raay se nahi",
                       list(_PEDAGOGY_QUERIES)))

    practice: List[str] = []
    if ask.kind in (KIND_PAPER, KIND_BOTH) and anchor:
        practice.append(f"{anchor} previous year question paper pdf official")
        for term in subjects[:2]:
            practice.append(f"{anchor} {term} question types weightage")
    if practice:
        groups.append((LANE_PRACTICE,
                       "purane paper se sirf DHAANCHA padha jaata hai, bol nahi",
                       practice))
    return groups


def _dedup(rows: Sequence[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
    seen: set = set()
    out: List[Dict[str, str]] = []
    for row in rows:
        query = " ".join(str(row.get("query") or "").split())
        key = query.lower()
        if not query or key in seen:
            continue
        seen.add(key)
        out.append({"query": query, "lane": str(row.get("lane") or ""),
                    "why": str(row.get("why") or "")})
        if len(out) >= max(0, int(limit)):
            break
    return out


def lane_queries(ask: Optional[ExamAsk] = None,
                 limit: int = MAX_STUDY_QUERIES) -> List[Dict[str, str]]:
    """{"query","lane","why"} ki chhoti list — official pehle.

    Round-robin trademodel wali wajah se hai: flat kram me pedagogy ki chaar
    query pehle aa jaati aur user ka apna exam ka official syllabus budget se
    bahar gir jaata. Har pass OFFICIAL se shuru hota hai.
    """
    groups = _study_groups(ask)
    if not groups:
        return []
    depth = max((len(queries) for _l, _w, queries in groups), default=0)
    rows: List[Dict[str, str]] = []
    for index in range(depth):
        for lane, why, queries in groups:
            if index < len(queries):
                rows.append({"query": queries[index], "lane": lane, "why": why})
    return _dedup(rows, limit)


def lead_queries(ask: Optional[ExamAsk] = None, limit: int = 3) -> List[str]:
    """Round-1 ke pehle chand slot — official document sabse pehle."""
    rows: List[Dict[str, str]] = []
    for lane, why, queries in _study_groups(ask):
        rows.extend({"query": q, "lane": lane, "why": why} for q in queries)
    return [row["query"] for row in _dedup(rows, limit)]


# ═════════════════════════════════════════════════════════════════════════════
# ASLI NAAP — yahan se aage sirf naapi hui cheezein hain
# ═════════════════════════════════════════════════════════════════════════════
# Wajah (#171a): pehle "syllabus cover hua" ya "difficulty mix hai" ka faisla
# jawab ke SHABD dekh kar hota tha. Shabd likhna aasaan hai, isliye wo naap
# nahi thi. Neeche ke funcs paper ko PADH kar ginti karte hain.

# reason code (naap kyun nahi hui — hamesha likha jaata hai)
NO_PAPER = "no_paper"
NO_SYLLABUS = "no_syllabus"
FEW_QUESTIONS = "few_questions"
NO_KEY = "no_key"
NO_NUMERIC = "no_numeric"
NO_EVALUATOR = "no_evaluator"
NO_PLAN = "no_plan"
NO_TIME_BUDGET = "no_time_budget"
NO_TOPIC_WEIGHT = "no_topic_weight"

MIN_QUESTIONS_FOR_SPLIT = 4
DUPLICATE_SIMILARITY = 0.8
DIFFICULTY_IS_PROXY = True
EASY = "easy"
MEDIUM = "medium"
HARD = "hard"
DIFFICULTY_BANDS: Tuple[str, ...] = (EASY, MEDIUM, HARD)
EASY_MAX_SCORE = 2.0
MEDIUM_MAX_SCORE = 4.0

# ── #171e — LAB ki chhat: "kitna kaafi hai" EK hi jagah tay hoti hai ──────────
# Yahi niyam trade lane par bhi hai (`market_data` me chhat, `lab.LabPolicy` me
# uska mirror). Do jagah do value rakhne se report kis chhat par tiki hai ye
# pata hi nahi chalta, aur chupke se dono alag ho jaati hain. In numbers ko
# badalna JAAN-BOOJH KAR liya faisla hai — koi test inhe khud dheela nahi karta.
LAB_MIN_COVERAGE_SHARE = 0.8   # syllabus ke itne hisse par question chahiye
LAB_MAX_BAND_SHARE = 0.8       # ek hi difficulty band me itna se zyada = mix nahi
LAB_MAX_DUPLICATE_PAIRS = 0    # ek bhi ek-jaisi jodi paper me nahi chalegi
LAB_MIN_SOLVED_SHARE = 1.0     # jo ginti wala hissa chala, wo banna hi chahiye

# Question ki shuruaat: "1." / "1)" / "Q1." / "Q.1" / "प्रश्न 1"
_Q_START_RE = re.compile(
    r"^\s*(?:(?:Q|Que|Ques|प्रश्न|प्र)\s*\.?\s*)?(\d{1,3})\s*[.)\]:-]\s+(.*)$")
# Option: "(a) ...", "a) ...", "A. ...", "(1) ..."
_OPTION_RE = re.compile(
    r"(?:^|\s)\(?([a-dA-D1-4])\)?\s*[.)]\s*(?=\S)")
# Answer key ek hi line me: "Ans: b", "Answer - (c)", "उत्तर: b"
_ANS_RE = re.compile(
    r"(?:ans|answer|उत्तर|uttar|key)\s*[:\-–]?\s*\(?([a-dA-D1-4])\)?",
    re.IGNORECASE)
_SOLUTION_LINE_RE = re.compile(
    r"^\s*(?:sol|soln|solution|hal|हल|step[s]?|व्याख्या|explanation)\b",
    re.IGNORECASE)
_MARK_LINE_RE = re.compile(r"\[(\d{1,3})\s*(?:marks?|ank|अंक)\]", re.IGNORECASE)
_TOPIC_TAG_RE = re.compile(r"\[(?:topic|vishay|विषय)\s*[:\-]\s*([^\]]{1,60})\]",
                           re.IGNORECASE)
_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_EXPR_RE = re.compile(
    r"(\d+(?:\.\d+)?(?:\s*[-+*/]\s*\d+(?:\.\d+)?){1,8})")


@dataclass(frozen=True)
class Question:
    """Ek question — jaisa paper me ASLI me likha tha."""

    number: int = 0
    text: str = ""
    options: Tuple[str, ...] = ()
    answer: str = ""
    solution: str = ""
    marks: float = 0.0
    topic: str = ""

    @property
    def has_options(self) -> bool:
        return len(self.options) >= 2

    @property
    def has_answer(self) -> bool:
        return bool(self.answer)

    @property
    def has_solution(self) -> bool:
        return bool(self.solution.strip())

    @property
    def numbers(self) -> Tuple[float, ...]:
        return tuple(float(hit) for hit in _NUMBER_TOKEN_RE.findall(self.text))

    def to_dict(self) -> Dict[str, Any]:
        return {"number": self.number, "text": self.text,
                "options": list(self.options), "answer": self.answer,
                "solution": self.solution, "marks": self.marks,
                "topic": self.topic}


def _options_in(line: str) -> List[str]:
    """Ek line me kitne option hain — label ke kram se, ginti se nahi.

    "(a) 4 (b) 6 (c) 8 (d) 10" ek hi line me aata hai, aur kabhi alag-alag
    line me. Dono shakl chalti hain kyunki hum label ki JAGAH dekhte hain.
    """
    labels = [hit.group(1).lower() for hit in _OPTION_RE.finditer(line)]
    out: List[str] = []
    for label in labels:
        if label not in out:
            out.append(label)
    return out


def questions_from_text(text: Any) -> List[Question]:
    """Paper ke text se question nikaalo — ginti bhi yahin se aati hai.

    Ek question ka block agli numbered line par khatam hota hai. Answer aur
    solution usi block me dhoondhe jaate hain, aur agar paper ke aakhir me
    alag ANSWER KEY hai to wo `apply_answer_key()` se judti hai.

    ANSWER KEY ka hissa yahan se KAAT diya jaata hai. Wajah naapi hui: key ki
    line "1. b" bhi numbered line hai, isliye wo naya question ban jaati thi
    aur 20 question ke paper me 40 question ginne lagte the.
    """
    blob = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cut = _KEY_BLOCK_RE.search(blob)
    if cut:
        blob = blob[:cut.start()]
    lines = blob.split("\n")
    blocks: List[Tuple[int, List[str]]] = []
    for line in lines:
        start = _Q_START_RE.match(line)
        if start:
            blocks.append((int(start.group(1)), [start.group(2)]))
        elif blocks:
            blocks[-1][1].append(line)

    out: List[Question] = []
    for number, body in blocks:
        options: List[str] = []
        answer = ""
        solution_lines: List[str] = []
        stem: List[str] = []
        marks = 0.0
        topic = ""
        in_solution = False
        for index, line in enumerate(body):
            mark_hit = _MARK_LINE_RE.search(line)
            if mark_hit and not marks:
                marks = float(mark_hit.group(1))
            topic_hit = _TOPIC_TAG_RE.search(line)
            if topic_hit and not topic:
                topic = " ".join(topic_hit.group(1).split())
            if _SOLUTION_LINE_RE.match(line):
                in_solution = True
            ans_hit = _ANS_RE.search(line)
            if ans_hit and not answer:
                answer = ans_hit.group(1).lower()
            if in_solution:
                solution_lines.append(line.strip())
                continue
            found = _options_in(line)
            if found:
                options.extend(label for label in found if label not in options)
                continue
            if index == 0 or line.strip():
                stem.append(line.strip())
        clean_stem = " ".join(part for part in stem if part)
        clean_stem = _MARK_LINE_RE.sub("", clean_stem)
        clean_stem = _TOPIC_TAG_RE.sub("", clean_stem)
        clean_stem = _ANS_RE.sub("", clean_stem)
        out.append(Question(number=number,
                            text=" ".join(clean_stem.split()),
                            options=tuple(options),
                            answer=answer,
                            solution=" ".join(solution_lines).strip(),
                            marks=marks,
                            topic=topic))
    return out


_KEY_BLOCK_RE = re.compile(
    r"(?:answer\s*key|ans\s*key|uttar\s*kunji|उत्तर\s*कुंजी)\s*[:\-]?",
    re.IGNORECASE)
_KEY_PAIR_RE = re.compile(r"(\d{1,3})\s*[.)\-:]?\s*\(?([a-dA-D1-4])\)?")


def answer_key_from_text(text: Any) -> Dict[int, str]:
    """Paper ke aakhir wali ANSWER KEY — "1-b 2-c 3-a" bhi chalti hai."""
    blob = str(text or "")
    hit = _KEY_BLOCK_RE.search(blob)
    if not hit:
        return {}
    tail = blob[hit.end():]
    pairs: Dict[int, str] = {}
    for number, letter in _KEY_PAIR_RE.findall(tail):
        key = int(number)
        if key not in pairs:
            pairs[key] = letter.lower()
    return pairs


def apply_answer_key(questions: Sequence[Question],
                     key: Optional[Dict[int, str]] = None) -> List[Question]:
    """Alag key ko question se jodo — jise pehle se answer hai wo nahi badalta."""
    table = dict(key or {})
    out: List[Question] = []
    for question in questions:
        if question.answer or question.number not in table:
            out.append(question)
            continue
        out.append(Question(number=question.number, text=question.text,
                            options=question.options,
                            answer=table[question.number],
                            solution=question.solution, marks=question.marks,
                            topic=question.topic))
    return out


# ── SYLLABUS ka daayra: topic kahan se aaye ─────────────────────────────────
_TOPIC_LINE_RE = re.compile(
    r"^\s*(?:unit|chapter|topic|module|part|adhyay|अध्याय|इकाई)?\s*"
    r"(?:[0-9IVXivx]{1,4})?\s*[.):\-]?\s*(.{3,80}?)\s*$")
_TOPIC_SPLIT_RE = re.compile(r"[,;•·•]|\s{2,}|\s[-–]\s")
_TOPIC_STOP: Tuple[str, ...] = (
    "syllabus", "exam pattern", "notification", "index", "contents",
    "download", "advertisement", "table of contents", "page", "note",
)


def syllabus_topics(text: Any, limit: int = 60) -> List[str]:
    """Padhe hue syllabus se topic ki list — chhota-mota safai ke saath.

    Ye list SOURCE se aati hai (official syllabus PDF/page ka text), app ke
    dimaag se nahi. Isliye jab syllabus padha hi na gaya ho, list khaali
    rehti hai aur coverage NOT_MEASURED ho jaati hai — yahi imaandaar haal
    hai.
    """
    topics: List[str] = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = " ".join(raw.split())
        if not line or len(line) < 3:
            continue
        for piece in _TOPIC_SPLIT_RE.split(line):
            got = _TOPIC_LINE_RE.match(" ".join(piece.split()))
            if not got:
                continue
            topic = " ".join(got.group(1).split()).strip(" .:-–")
            low = topic.lower()
            if len(topic) < 3 or len(_words(topic)) > 8:
                continue
            if any(stop == low or stop in low for stop in _TOPIC_STOP):
                continue
            if low in {existing.lower() for existing in topics}:
                continue
            topics.append(topic)
            if len(topics) >= max(1, int(limit)):
                return topics
    return topics


_TOKEN_STOP: Tuple[str, ...] = (
    "ka", "ki", "ke", "ko", "me", "mein", "se", "hai", "ho", "kya", "kaun",
    "the", "of", "in", "is", "a", "an", "and", "for", "to", "what", "which",
    "following", "nimn", "nimnlikhit",
)


def _topic_tokens(value: Any) -> set:
    return {word for word in _words(value)
            if len(word) > 2 and word not in _TOKEN_STOP}


@dataclass(frozen=True)
class CoverageSplit:
    """Syllabus ke kitne topic par ASLI me question bana."""

    ok: bool = False
    reason_code: str = ""
    topics: int = 0
    covered: int = 0
    questions: int = 0
    rows: Tuple[Dict[str, Any], ...] = ()
    uncovered: Tuple[str, ...] = ()

    @property
    def covered_share(self) -> Optional[float]:
        if not self.ok or not self.topics:
            return None
        return round(self.covered / self.topics, 4)

    @property
    def full_coverage(self) -> Optional[bool]:
        share = self.covered_share
        if share is None:
            return None
        return bool(self.covered == self.topics)

    @property
    def paper_too_small(self) -> Optional[bool]:
        """Question hi topic se kam hain — to poora cover MUMKIN hi nahi tha."""
        if not self.ok or not self.topics:
            return None
        return bool(self.questions < self.topics)

    @property
    def reason(self) -> str:
        if not self.ok:
            return self.reason_code
        if self.full_coverage:
            return ""
        if self.paper_too_small:
            return (f"{self.topics} topic ke liye sirf {self.questions} question "
                    f"the — {self.topics - self.covered} topic bina question rah gaye")
        return f"{self.topics - self.covered} topic par ek bhi question nahi bana"

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason_code": self.reason_code,
                "reason": self.reason, "topics": self.topics,
                "covered": self.covered, "questions": self.questions,
                "covered_share": self.covered_share,
                "full_coverage": self.full_coverage,
                "paper_too_small": self.paper_too_small,
                "uncovered": list(self.uncovered),
                "rows": [dict(row) for row in self.rows]}


TOPIC_MATCH_TOKENS = 2       # kam se kam itne shabd milein tabhi "cover" maana
TOPIC_MATCH_SHARE = 0.6      # ya topic ke itne hisse ke shabd milein


def _covers(topic: str, question: Question) -> bool:
    """Question is topic ka hai ya nahi — shabd ke MILAN se, tag ke bharose nahi.

    Do raste: (a) question par [Topic: X] tag ho, (b) topic ke shabd question
    me milein. Do shabd (ya topic ka 60% hissa) — ek aam shabd par "cover"
    maan lena jhooth hota (naapa gaya: "number" ek shabd se 9 topic cover
    dikhne lagte the).
    """
    wanted = _topic_tokens(topic)
    if not wanted:
        return False
    if question.topic and _topic_tokens(question.topic) & wanted:
        return True
    have = _topic_tokens(question.text)
    hit = wanted & have
    if not hit:
        return False
    need = min(max(1, TOPIC_MATCH_TOKENS), len(wanted))
    if len(hit) >= need:
        return True
    return bool(len(hit) / len(wanted) >= TOPIC_MATCH_SHARE)


def coverage_split(topics: Sequence[str] = (),
                   questions: Sequence[Question] = ()) -> CoverageSplit:
    """Syllabus ke har topic par ginti — asli naap, likhe daawe se nahi."""
    clean_topics = [" ".join(str(topic).split()) for topic in topics
                    if str(topic).strip()]
    if not clean_topics:
        return CoverageSplit(ok=False, reason_code=NO_SYLLABUS)
    if not questions:
        return CoverageSplit(ok=False, reason_code=NO_PAPER,
                             topics=len(clean_topics))
    rows: List[Dict[str, Any]] = []
    uncovered: List[str] = []
    covered = 0
    for topic in clean_topics:
        hits = [question.number for question in questions
                if _covers(topic, question)]
        rows.append({"topic": topic, "questions": len(hits),
                     "question_numbers": list(hits)})
        if hits:
            covered += 1
        else:
            uncovered.append(topic)
    return CoverageSplit(ok=True, topics=len(clean_topics), covered=covered,
                         questions=len(questions), rows=tuple(rows),
                         uncovered=tuple(uncovered))


# ── DIFFICULTY: proxy naap, aur ye baat saaf likhi jaati hai ─────────────────
def difficulty_score(question: Question) -> float:
    """Naapne layak proxy: kitne shabd + kitne ank + kitne marks.

    Ye insaan ka faisla NAHI hai. Isliye `DIFFICULTY_IS_PROXY` hamesha True
    jaata hai aur jawab me likha jaata hai ki ye kis cheez se naapa gaya.
    """
    words = len(_words(question.text))
    numbers = len(question.numbers)
    score = (words / 12.0) + float(numbers)
    if question.marks:
        score += max(0.0, float(question.marks) - 1.0) / 2.0
    return round(score, 4)


def difficulty_band(question: Question) -> str:
    score = difficulty_score(question)
    if score <= EASY_MAX_SCORE:
        return EASY
    if score <= MEDIUM_MAX_SCORE:
        return MEDIUM
    return HARD


@dataclass(frozen=True)
class DifficultySplit:
    ok: bool = False
    reason_code: str = ""
    questions: int = 0
    counts: Dict[str, int] = field(default_factory=dict)

    @property
    def bands_used(self) -> Optional[int]:
        if not self.ok:
            return None
        return sum(1 for band in DIFFICULTY_BANDS if self.counts.get(band))

    @property
    def shares(self) -> Dict[str, Optional[float]]:
        if not self.ok or not self.questions:
            return {band: None for band in DIFFICULTY_BANDS}
        return {band: round(self.counts.get(band, 0) / self.questions, 4)
                for band in DIFFICULTY_BANDS}

    @property
    def mixed(self) -> Optional[bool]:
        """Ek hi band me sab question = mix nahi hua."""
        used = self.bands_used
        if used is None:
            return None
        return bool(used >= 2)

    @property
    def reason(self) -> str:
        if not self.ok:
            return self.reason_code
        if self.mixed:
            return ""
        band = next((name for name in DIFFICULTY_BANDS
                     if self.counts.get(name)), "")
        return f"saare question ek hi band me gire ({band})"

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason_code": self.reason_code,
                "reason": self.reason, "questions": self.questions,
                "counts": {band: self.counts.get(band, 0)
                           for band in DIFFICULTY_BANDS},
                "shares": self.shares, "bands_used": self.bands_used,
                "mixed": self.mixed, "is_proxy": DIFFICULTY_IS_PROXY}


def difficulty_split(questions: Sequence[Question] = ()) -> DifficultySplit:
    if not questions:
        return DifficultySplit(ok=False, reason_code=NO_PAPER)
    if len(questions) < MIN_QUESTIONS_FOR_SPLIT:
        return DifficultySplit(ok=False, reason_code=FEW_QUESTIONS,
                               questions=len(questions))
    counts: Dict[str, int] = {band: 0 for band in DIFFICULTY_BANDS}
    for question in questions:
        counts[difficulty_band(question)] += 1
    return DifficultySplit(ok=True, questions=len(questions), counts=counts)


# ── DUPLICATE: do question ek jaise hain ya nahi — shabd ke overlap se ────────
def _similarity(left: Question, right: Question) -> float:
    """Jaccard overlap. Ginti nahi, MILAN ka hissa."""
    a = _topic_tokens(left.text)
    b = _topic_tokens(right.text)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


@dataclass(frozen=True)
class DuplicateSplit:
    ok: bool = False
    reason_code: str = ""
    questions: int = 0
    threshold: float = DUPLICATE_SIMILARITY
    pairs: Tuple[Dict[str, Any], ...] = ()

    @property
    def duplicate_pairs(self) -> Optional[int]:
        if not self.ok:
            return None
        return len(self.pairs)

    @property
    def clean(self) -> Optional[bool]:
        count = self.duplicate_pairs
        if count is None:
            return None
        return bool(count == 0)

    @property
    def reason(self) -> str:
        if not self.ok:
            return self.reason_code
        if self.clean:
            return ""
        first = self.pairs[0]
        return (f"{len(self.pairs)} jodi ek jaisi nikli — jaise Q{first['left']} "
                f"aur Q{first['right']} (overlap {first['similarity']})")

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason_code": self.reason_code,
                "reason": self.reason, "questions": self.questions,
                "threshold": self.threshold, "clean": self.clean,
                "duplicate_pairs": self.duplicate_pairs,
                "pairs": [dict(pair) for pair in self.pairs]}


def duplicate_split(questions: Sequence[Question] = (),
                    threshold: float = DUPLICATE_SIMILARITY) -> DuplicateSplit:
    """Har jodi ka overlap naapa jaata hai — 120 question par 7140 jodi, sasta."""
    if not questions:
        return DuplicateSplit(ok=False, reason_code=NO_PAPER,
                              threshold=threshold)
    if len(questions) < 2:
        return DuplicateSplit(ok=False, reason_code=FEW_QUESTIONS,
                              questions=len(questions), threshold=threshold)
    pairs: List[Dict[str, Any]] = []
    for index, left in enumerate(questions):
        for right in list(questions)[index + 1:]:
            score = _similarity(left, right)
            if score >= threshold:
                pairs.append({"left": left.number, "right": right.number,
                              "similarity": score})
    return DuplicateSplit(ok=True, questions=len(questions),
                          threshold=threshold, pairs=tuple(pairs))


# ── SOLVABILITY: numeric question ka jawab CHAL kar dekha gaya ya nahi ────────
@dataclass(frozen=True)
class SolvabilitySplit:
    ok: bool = False
    reason_code: str = ""
    numeric_questions: int = 0
    checked: int = 0
    solved: int = 0
    failed: Tuple[Dict[str, Any], ...] = ()

    @property
    def solved_share(self) -> Optional[float]:
        if not self.ok or not self.checked:
            return None
        return round(self.solved / self.checked, 4)

    @property
    def all_solvable(self) -> Optional[bool]:
        share = self.solved_share
        if share is None:
            return None
        return bool(self.solved == self.checked)

    @property
    def reason(self) -> str:
        if not self.ok:
            return self.reason_code
        if self.all_solvable:
            return ""
        return (f"{self.checked - self.solved} question ka ginti wala hissa "
                f"chala kar dekha to nahi bana")

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason_code": self.reason_code,
                "reason": self.reason,
                "numeric_questions": self.numeric_questions,
                "checked": self.checked, "solved": self.solved,
                "solved_share": self.solved_share,
                "all_solvable": self.all_solvable,
                "failed": [dict(row) for row in self.failed]}


def expressions_in(question: Question) -> List[str]:
    """Question me se ginti wale expression — jaise "12 + 7 * 3"."""
    out: List[str] = []
    for hit in _EXPR_RE.finditer(question.text):
        piece = " ".join(hit.group(0).split())
        if piece and piece not in out:
            out.append(piece)
    return out


def solvability_split(questions: Sequence[Question] = (),
                      evaluate: Optional[Any] = None) -> SolvabilitySplit:
    """Ginti wale question ko ASLI me chala kar dekha jaata hai.

    `evaluate` bahar se aata hai (lab.py `SafeNumericExecutor().evaluate`
    bhejta hai). Na mile to jawab `NOT_MEASURED` — apna calculator likh kar
    "check ho gaya" kehna jhooth hota.
    """
    if not questions:
        return SolvabilitySplit(ok=False, reason_code=NO_PAPER)
    if evaluate is None:
        return SolvabilitySplit(ok=False, reason_code=NO_EVALUATOR)
    rows = [(question, expressions_in(question)) for question in questions]
    numeric = [(question, exprs) for question, exprs in rows if exprs]
    if not numeric:
        return SolvabilitySplit(ok=False, reason_code=NO_NUMERIC)
    solved = 0
    failed: List[Dict[str, Any]] = []
    for question, exprs in numeric:
        bad = ""
        for expression in exprs:
            try:
                result = evaluate(expression)
            except Exception as exc:               # evaluator ka apna rona
                bad = f"{type(exc).__name__}"
                break
            if not isinstance(result, dict) or not result.get("ok"):
                bad = str((result or {}).get("error") or "not ok") \
                    if isinstance(result, dict) else "bad result"
                break
        if bad:
            failed.append({"number": question.number, "error": bad})
        else:
            solved += 1
    return SolvabilitySplit(ok=True, numeric_questions=len(numeric),
                            checked=len(numeric), solved=solved,
                            failed=tuple(failed))


# ── STUDY PLAN: time jodne par bharosa hai ya nahi ───────────────────────────
DAILY_MINUTES_CEILING = 600      # 10 ghante se zyada roz = plan asli nahi hai
DEFAULT_DAILY_MINUTES = 180      # ask me na likha ho to 3 ghante maana jaata hai

# "Day 3", "Din 3", "Week 2", "Hafta 2", "दिन 3"
_PLAN_LABEL_RE = re.compile(
    r"\b(?:day|din|दिन|week|hafta|हफ्ता|saptah)\s*[-:]?\s*(\d{1,3})\b",
    re.IGNORECASE)
# "60 min", "90 minutes", "1.5 hours", "2 ghante", "45 मिनट"
_PLAN_MINUTES_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|min|मिनट)\b", re.IGNORECASE)
_PLAN_HOURS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|ghante?|ghanta|घंटे|घंटा)\b",
    re.IGNORECASE)


def _minutes_in(line: str) -> float:
    """Ek line me likha hua time — minute me. Ghanta bhi minute banta hai."""
    total = 0.0
    for hit in _PLAN_MINUTES_RE.finditer(line):
        total += float(hit.group(1))
    for hit in _PLAN_HOURS_RE.finditer(line):
        total += float(hit.group(1)) * 60.0
    return round(total, 2)


def plan_rows_from_text(text: Any) -> List[Dict[str, Any]]:
    """Plan ki line se row banti hai — likhi hui line se, andaaze se nahi.

    Row banne ki ek hi shart: line me kaam ka naam ho. Time mila to row me
    minute jaata hai, na mila to `minutes` 0 rehta hai aur naap NOT_MEASURED
    hoti hai — "roz 2 ghante padho" maan lena naap nahi hai.
    """
    rows: List[Dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        body = line.lstrip("-*•·• \t")
        if len(body) < 4:
            continue
        label_hit = _PLAN_LABEL_RE.search(body)
        minutes = _minutes_in(body)
        if not label_hit and not minutes:
            continue
        label = ""
        if label_hit:
            label = " ".join(label_hit.group(0).split())
        topic = body
        if label_hit:
            topic = (body[:label_hit.start()] + body[label_hit.end():])
        topic = topic.strip(" -:–—,").strip()
        rows.append({"label": label, "topic": topic, "minutes": minutes,
                     "line": body})
    return rows


@dataclass(frozen=True)
class PlanSplit:
    ok: bool = False
    reason_code: str = ""
    rows: int = 0
    timed_rows: int = 0
    total_minutes: float = 0.0
    minutes_available: float = 0.0
    daily_ceiling: float = float(DAILY_MINUTES_CEILING)
    worst_day: str = ""
    worst_day_minutes: float = 0.0

    @property
    def load_share(self) -> Optional[float]:
        if not self.ok or not self.minutes_available:
            return None
        return round(self.total_minutes / self.minutes_available, 4)

    @property
    def fits(self) -> Optional[bool]:
        share = self.load_share
        if share is None:
            return None
        return bool(self.total_minutes <= self.minutes_available)

    @property
    def day_realistic(self) -> Optional[bool]:
        """Kisi ek din ka bojh insaani hadd me hai ya nahi."""
        if not self.ok:
            return None
        if not self.worst_day:
            return None
        return bool(self.worst_day_minutes <= self.daily_ceiling)

    @property
    def reason(self) -> str:
        if not self.ok:
            return self.reason_code
        parts: List[str] = []
        if self.fits is False:
            parts.append(f"plan ka time {self.total_minutes:.0f} min hai par "
                         f"mila hua time {self.minutes_available:.0f} min")
        if self.day_realistic is False:
            parts.append(f"{self.worst_day} par {self.worst_day_minutes:.0f} min "
                         f"ka bojh (hadd {self.daily_ceiling:.0f} min)")
        return "; ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reason_code": self.reason_code,
                "reason": self.reason, "rows": self.rows,
                "timed_rows": self.timed_rows,
                "total_minutes": self.total_minutes,
                "minutes_available": self.minutes_available,
                "load_share": self.load_share, "fits": self.fits,
                "daily_ceiling": self.daily_ceiling,
                "worst_day": self.worst_day,
                "worst_day_minutes": self.worst_day_minutes,
                "day_realistic": self.day_realistic}


def plan_time_split(rows: Sequence[Dict[str, Any]] = (),
                    minutes_available: float = 0.0) -> PlanSplit:
    """Plan ka jodha hua time vs asli me mila hua time."""
    clean = [dict(row) for row in rows if str(row.get("line") or
                                              row.get("topic") or "").strip()]
    if not clean:
        return PlanSplit(ok=False, reason_code=NO_PLAN)
    timed = [row for row in clean if float(row.get("minutes") or 0) > 0]
    if not timed:
        return PlanSplit(ok=False, reason_code=NO_TOPIC_WEIGHT,
                         rows=len(clean))
    if float(minutes_available or 0) <= 0:
        return PlanSplit(ok=False, reason_code=NO_TIME_BUDGET,
                         rows=len(clean), timed_rows=len(timed),
                         total_minutes=round(sum(float(row["minutes"])
                                                 for row in timed), 2))
    per_day: Dict[str, float] = {}
    for row in timed:
        label = str(row.get("label") or "")
        if label:
            per_day[label] = per_day.get(label, 0.0) + float(row["minutes"])
    worst_day, worst_minutes = "", 0.0
    for label, minutes in sorted(per_day.items()):
        if minutes > worst_minutes:
            worst_day, worst_minutes = label, round(minutes, 2)
    return PlanSplit(ok=True, rows=len(clean), timed_rows=len(timed),
                     total_minutes=round(sum(float(row["minutes"])
                                             for row in timed), 2),
                     minutes_available=round(float(minutes_available), 2),
                     worst_day=worst_day, worst_day_minutes=worst_minutes)


def minutes_available_of(ask: Optional[ExamAsk] = None,
                         daily_minutes: float = DEFAULT_DAILY_MINUTES) -> float:
    """Farmaish me jitne din mile, unka kul time. Din na mile to 0 (naap nahi)."""
    if ask is None or not ask.days_available:
        return 0.0
    return round(float(ask.days_available) * float(daily_minutes), 2)


# ── SOURCE ki pehchaan: official pehle, phir kitaab, phir padhne ki research ──
# Ye host-list ROUTING/PEHCHAAN ke liye hai, "sach kaun bolta hai" ke liye nahi.
# Board ka apna page official HONE se uska har jumla sach nahi ho jaata — bas
# itna tay hota hai ki syllabus wahan se aaya, coaching blog se nahi.
OFFICIAL_HOST_HINTS: Tuple[str, ...] = (
    ".gov.in", ".nic.in", ".gov", ".edu", "cbse", "ncert", "nta.ac.in",
    "upsc", "ssc.", "ssc.nic", "rrbcdg", "indianrailways", "rpf",
    "ibps.in", "sbi.co.in", "bihar", "mpsc", "tnpsc", "kpsc", "wbpsc",
    "ugc", "aicte", "nios", "navodaya", "ncte",
)
OFFICIAL_HOST_LIST_IS_NOT_EXHAUSTIVE = True
TEXTBOOK_SOURCE_TYPES: Tuple[str, ...] = ("book", "classic_text")
PEDAGOGY_SOURCE_TYPES: Tuple[str, ...] = ("paper",)
DEEP_READ_LEVELS: Tuple[str, ...] = ("claims", "full_text")

# Padhne ki research ke shabd — inhe naam se dhoondha jaata hai, kyunki ek
# aam paper "exam" ke baare me ho sakta hai par PADHAI ke tareeqe par nahi.
PEDAGOGY_TERMS: Tuple[str, ...] = (
    "spaced repetition", "spacing effect", "retrieval practice",
    "testing effect", "interleaving", "interleaved practice",
    "deliberate practice", "formative assessment", "mastery learning",
    "worked example", "cognitive load", "desirable difficulty",
    "distributed practice", "self explanation", "feedback intervention",
)


def _text_of(value: Any) -> str:
    return str(value or "")


def _lines(text: Any) -> List[str]:
    return [line for line in _text_of(text).splitlines() if line.strip()]


def _source_field(source: Any, name: str) -> str:
    value = getattr(source, name, None)
    if value is None and isinstance(source, dict):
        value = source.get(name)
    if hasattr(value, "value"):          # Enum
        value = value.value
    return str(value or "")


def _source_blob(source: Any) -> str:
    return " ".join((_source_field(source, "title"),
                     _source_field(source, "snippet"),
                     _source_field(source, "url")))


def official_sources(sources: Iterable[Any] = ()) -> List[Dict[str, str]]:
    """Board/commission/university ka apna page — host ke nishaan se."""
    out: List[Dict[str, str]] = []
    for source in sources or ():
        url = _source_field(source, "url").lower()
        host = next((hint for hint in OFFICIAL_HOST_HINTS if hint in url), "")
        if host:
            out.append({"source_id": _source_field(source, "source_id"),
                        "host": host,
                        "read_level": _source_field(source, "read_level")})
    return out


def textbook_sources(sources: Iterable[Any] = ()) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for source in sources or ():
        stype = _source_field(source, "source_type").lower()
        if stype in TEXTBOOK_SOURCE_TYPES:
            out.append({"source_id": _source_field(source, "source_id"),
                        "read_level": _source_field(source, "read_level")})
    return out


def pedagogy_sources(sources: Iterable[Any] = ()) -> List[Dict[str, str]]:
    """Padhai ke TAREEQE par source — vishay ke shabd se, sirf type se nahi."""
    out: List[Dict[str, str]] = []
    for source in sources or ():
        norm = _norm(_source_blob(source))
        terms = _matched(norm, PEDAGOGY_TERMS)
        if terms:
            out.append({"source_id": _source_field(source, "source_id"),
                        "term": terms[0],
                        "read_level": _source_field(source, "read_level")})
    return out


def deeply_read(sources: Iterable[Any] = ()) -> List[str]:
    """Sirf wahi source jinka asli text/claims padha gaya — mila hua nahi."""
    return [_source_field(source, "source_id") for source in sources or ()
            if _source_field(source, "read_level") in DEEP_READ_LEVELS]


# ── CONTRACT: exam/padhai ki farmaish par kya-kya hona chahiye ───────────────
# Har naap ka apna point hai. Do naap ek dabbe me daal dena ginti sundar bana
# deta hai, par phir ek MET doosre ka jhooth chhupa leta hai — trademodel me
# yahi sabaq mila tha, isliye wahi kaida yahan bhi hai.
GROUP_SCOPE = "scope"
GROUP_SOURCES = "sources"
GROUP_PAPER = "paper"
GROUP_PLAN = "plan"
GROUP_HONESTY = "honesty"
GROUPS: Tuple[str, ...] = (GROUP_SCOPE, GROUP_SOURCES, GROUP_PAPER,
                           GROUP_PLAN, GROUP_HONESTY)


@dataclass(frozen=True)
class ContractPoint:
    point_id: str
    label: str
    group: str
    needs: str            # MET kehne ke liye kya HONA chahiye (saaf shabdon me)
    blocked_by: str = ""  # aisi rukaawat jo is app me structurally hai


CONTRACT: Tuple[ContractPoint, ...] = (
    # ── scope ────────────────────────────────────────────────────────────────
    ContractPoint("exam_scope",
                  "kaunsa exam / subject / level — naam se pakda gaya",
                  GROUP_SCOPE,
                  "exam ka naam ya subject ya level me se kam se kam ek mila ho"),
    ContractPoint("deliverable_kind",
                  "jo maanga (paper / plan / dono) wahi bana",
                  GROUP_SCOPE,
                  "farmaish ka kind aur jo bana wo dono milte hon"),
    ContractPoint("language_honoured",
                  "bhasha waisi hi jaisi maangi gayi thi",
                  GROUP_SCOPE,
                  "hindi maangi to hindi, bilingual maanga to dono script"),
    ContractPoint("question_count_honoured",
                  "jitne question maange gaye, utne asli me bane",
                  GROUP_SCOPE,
                  "maangi hui ginti aur paper me parse hue question barabar hon"),
    # ── sources ──────────────────────────────────────────────────────────────
    ContractPoint("official_syllabus_source",
                  "board/commission ka apna syllabus ya notification padha gaya",
                  GROUP_SOURCES,
                  "kam se kam ek official host wala source id ke saath"),
    ContractPoint("textbook_source",
                  "padhne wali asli kitaab / curriculum ka source",
                  GROUP_SOURCES,
                  "kam se kam ek book/classic-text source"),
    ContractPoint("pedagogy_evidence",
                  "kaise padhein — spacing / retrieval / interleaving ki research",
                  GROUP_SOURCES,
                  "padhai ke tareeqe par kam se kam ek source, naam se"),
    ContractPoint("read_arguments_not_summaries",
                  "asli text padha gaya, sirf snippet nahi",
                  GROUP_SOURCES,
                  "read level claims/full_text ho, sirf title-snippet nahi"),
    # ── paper ────────────────────────────────────────────────────────────────
    ContractPoint("syllabus_coverage",
                  "syllabus ke har topic par question bana",
                  GROUP_PAPER,
                  "syllabus ke topic aur paper ke question ka asli milan, ginti ke saath"),
    ContractPoint("difficulty_mix",
                  "aasan / darmiyana / mushkil — teeno tarah ke question",
                  GROUP_PAPER,
                  "kam se kam do band me question, aur ye likha ho ki naap proxy hai"),
    ContractPoint("no_duplicate_questions",
                  "do question ek jaise nahi",
                  GROUP_PAPER,
                  "har jodi ka overlap naapa gaya ho aur hadd se neeche ho"),
    ContractPoint("answer_key_present",
                  "har question ka jawab (key) maujood",
                  GROUP_PAPER,
                  "jitne question, utne answer — aur key app ki banayi hai ye likha ho"),
    ContractPoint("solutions_stepwise",
                  "hal step-by-step likha gaya, sirf jawab nahi",
                  GROUP_PAPER,
                  "jin question par solution maanga gaya, un par hal ki line ho"),
    ContractPoint("question_solvable",
                  "ginti wale question ASLI me chala kar dekhe gaye",
                  GROUP_PAPER,
                  "numeric question ka expression evaluator se chala ho aur bana ho"),
    ContractPoint("marks_and_time",
                  "kul marks aur kitna waqt — dono likhe",
                  GROUP_PAPER,
                  "total marks aur duration dono paper me saaf likhe hon"),
    ContractPoint("negative_marking_stated",
                  "negative marking ka niyam saaf",
                  GROUP_PAPER,
                  "negative marking ka ya number ya 'nahi hai' saaf likha ho"),
    ContractPoint("past_pattern_evidence",
                  "purane paper ka pattern source ke saath",
                  GROUP_PAPER,
                  "pattern ka daawa kisi official/padhe hue source par tika ho"),
    ContractPoint("key_matched_official",
                  "app ki key official answer key se milayi gayi",
                  GROUP_PAPER,
                  "app ki key aur official key ka farak, question ke hisaab se",
                  "aane wale exam ki official key chhapti hi nahi — ye MET ho hi nahi sakta"),
    # ── plan ─────────────────────────────────────────────────────────────────
    ContractPoint("plan_rows_exist",
                  "plan me asli row — kaam ka naam aur uska waqt",
                  GROUP_PLAN,
                  "kam se kam ek row jisme kaam aur minute dono likhe hon"),
    ContractPoint("plan_time_budget",
                  "plan ka jodha hua time mile hue time me fit",
                  GROUP_PLAN,
                  "plan ka total minute aur mila hua minute — dono naape gaye hon"),
    ContractPoint("plan_daily_realistic",
                  "ek din ka bojh insaani hadd me",
                  GROUP_PLAN,
                  "sabse bhaari din ka minute hadd se neeche ho"),
    ContractPoint("weak_area_first",
                  "kamzori pehle — basic se shuruaat",
                  GROUP_PLAN,
                  "diagnostic/basic/kamzor topic pehle aane ka saaf kram"),
    ContractPoint("practice_and_review",
                  "practice aur dohraai (revision) dono plan me",
                  GROUP_PLAN,
                  "practice/test aur revision/spacing dono ka apna slot"),
    ContractPoint("progress_check",
                  "aage badha ya nahi — naapne ka tareeqa plan me",
                  GROUP_PLAN,
                  "mock/score/accuracy jaisa ek naapne wala step likha ho"),
    # ── honesty ──────────────────────────────────────────────────────────────
    ContractPoint("not_official_stated",
                  "'ye official paper/key nahi hai' saaf likha",
                  GROUP_HONESTY,
                  "practice-only aur official-nahi — dono baat likhi ho"),
    ContractPoint("no_question_prediction",
                  "'yahi question aayega' jaisa daawa nahi",
                  GROUP_HONESTY,
                  "aisa ek bhi vaakya na ho"),
    ContractPoint("no_score_promise",
                  "'itne number aa jaayenge' ka waada nahi",
                  GROUP_HONESTY,
                  "score/rank/selection ka koi waada na ho"),
    ContractPoint("honest_final_decision",
                  "source kaafi na ho to paper/plan gadha nahi jaata",
                  GROUP_HONESTY,
                  "ya poora deliverable saboot ke saath, ya saaf inkaar with missing list"),
)
CONTRACT_POINTS: int = len(CONTRACT)
CONTRACT_IDS: Tuple[str, ...] = tuple(point.point_id for point in CONTRACT)
CONTRACT_BY_ID: Dict[str, ContractPoint] = {p.point_id: p for p in CONTRACT}
# Jo point is app me structurally MET ho hi nahi sakte — inhe chhupaya nahi
# jaata, naam se ginne jaate hain.
STRUCTURALLY_BLOCKED: Tuple[str, ...] = tuple(
    point.point_id for point in CONTRACT if point.blocked_by)


# ── PAPER / PLAN ke text-cue: ye sirf "likha gaya ya nahi" naapte hain ───────
# In par ek hi bharosa hai: shabd MAUJOOD hai ya nahi. Isse zyada ka daawa nahi
# kiya jaata — jahan asli naap mumkin thi (coverage, difficulty, duplicate,
# solvability, time) wahan ye cue GRADE nahi karte.
_TOTAL_MARKS_RE = re.compile(
    r"(?:total\s*marks?|kul\s*(?:marks?|ank)|maximum\s*marks?|पूर्णांक)"
    r"\s*[:\-–]?\s*(\d{1,4})", re.IGNORECASE)
_DURATION_LINE_RE = re.compile(
    r"(?:time|duration|samay|अवधि|समय)\s*(?:allowed|limit)?\s*[:\-–]?\s*"
    r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|min|hours?|hrs?|hr|ghante?|घंटे|मिनट)",
    re.IGNORECASE)
_NEG_STATED_RE = re.compile(
    r"negative\s*marking\s*[:\-–]?\s*"
    r"(?:(\d+(?:[./]\d+)?)|nahi|no|none|nil|not\s*applicable)", re.IGNORECASE)
_PRACTICE_ONLY_RE = re.compile(
    r"\b(?:practice|abhyas|mock|sample)\b[^.\n]{0,40}\b(?:only|ke\s*liye|hi)\b"
    r"|\bpractice[-\s]only\b", re.IGNORECASE)
_NOT_OFFICIAL_RE = re.compile(
    r"\bofficial\b[^.\n]{0,30}\b(?:nahi|not)\b"
    r"|\bnot\b[^.\n]{0,20}\bofficial\b"
    r"|\basli\s*(?:paper|exam)\s*nahi\b", re.IGNORECASE)
_PREDICTION_RE = re.compile(
    r"\byahi\s*question\b[^.\n]{0,20}\b(?:aayeg|ayeg)\w*"
    r"|\bexam\s*me\s*(?:yahi|ye\s*hi)\b"
    r"|\bguaranteed\s*question\b"
    r"|\bpakka\s*(?:yahi|ye)\s*(?:question|sawaal)\b"
    r"|\bsame\s*questions?\s*will\s*(?:come|appear)\b", re.IGNORECASE)
_SCORE_PROMISE_RE = re.compile(
    r"\b(?:selection|naukri|job)\s*(?:pakk[ai]|guaranteed|confirm)\b"
    r"|\b(?:rank|marks?|score)\b[^.\n]{0,20}\b(?:pakk[ai]|guaranteed)\b"
    r"|\byou\s*will\s*(?:score|clear|pass|qualify)\b"
    r"|\b100\s*%\s*(?:marks?|result|selection)\b", re.IGNORECASE)

_BASIC_FIRST_CUES: Tuple[str, ...] = (
    "basic", "buniyadi", "diagnostic", "kamzor", "weak", "foundation",
    "fundamental", "shuruaat", "beginner", "concept clear", "revise basics",
)
_ADVANCED_CUES: Tuple[str, ...] = (
    "advanced", "hard", "mushkil", "full length", "full-length", "full mock",
    "previous year full", "high level", "expert",
)
_PRACTICE_CUES: Tuple[str, ...] = (
    "practice", "abhyas", "questions solve", "solve", "pyq", "mock",
    "test", "worksheet", "problem set", "sawaal",
)
_REVIEW_CUES: Tuple[str, ...] = (
    "revision", "revise", "dohra", "dohraai", "review", "recall",
    "spaced", "flashcard", "backlog",
)
_PROGRESS_CUES: Tuple[str, ...] = (
    "score", "accuracy", "percentage", "mock score", "sectional score",
    "progress", "track", "naap", "analysis", "error log", "weekly test",
)


def marks_and_time_in(text: Any) -> Dict[str, Any]:
    """Kul marks aur waqt — likhi hui line se nikaale gaye number."""
    blob = _text_of(text)
    marks_hit = _TOTAL_MARKS_RE.search(blob)
    time_hit = _DURATION_LINE_RE.search(blob)
    minutes = 0.0
    if time_hit:
        value = float(time_hit.group(1))
        unit = (time_hit.group(2) or "").lower()
        minutes = value * 60.0 if unit.startswith(("h", "g", "घ")) else value
    return {"total_marks": int(marks_hit.group(1)) if marks_hit else 0,
            "duration_minutes": round(minutes, 2)}


def negative_marking_stated(text: Any) -> bool:
    return bool(_NEG_STATED_RE.search(_text_of(text)))


def not_official_stated(text: Any) -> Dict[str, bool]:
    blob = _text_of(text)
    return {"practice_only": bool(_PRACTICE_ONLY_RE.search(blob)),
            "not_official": bool(_NOT_OFFICIAL_RE.search(blob))}


def prediction_claims(text: Any) -> List[str]:
    """'Yahi question aayega' jaisi baat — ye khud ek FAIL hai."""
    return [" ".join(hit.group(0).split())
            for hit in _PREDICTION_RE.finditer(_text_of(text))]


def score_promises(text: Any) -> List[str]:
    return [" ".join(hit.group(0).split())
            for hit in _SCORE_PROMISE_RE.finditer(_text_of(text))]


def _row_hits(rows: Sequence[Dict[str, Any]], cues: Sequence[str]) -> List[int]:
    """Kaun-kaunsi row me ye cue mila — index ke saath (kram bhi naapa jaata)."""
    out: List[int] = []
    for index, row in enumerate(rows or ()):
        norm = _norm(row.get("line") or row.get("topic") or "")
        if _matched(norm, cues):
            out.append(index)
    return out


def order_split(rows: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Basic pehle aaya ya advanced — kram ASLI row ke index se naapa jaata."""
    if not rows:
        return {"ok": False, "reason_code": NO_PLAN}
    basic = _row_hits(rows, _BASIC_FIRST_CUES)
    advanced = _row_hits(rows, _ADVANCED_CUES)
    if not basic and not advanced:
        return {"ok": False, "reason_code": NO_TOPIC_WEIGHT,
                "basic_rows": 0, "advanced_rows": 0}
    first_basic = basic[0] if basic else None
    first_advanced = advanced[0] if advanced else None
    if first_advanced is None:
        basic_first: Optional[bool] = True
    elif first_basic is None:
        basic_first = False
    else:
        basic_first = bool(first_basic < first_advanced)
    return {"ok": True, "basic_rows": len(basic), "advanced_rows": len(advanced),
            "first_basic_row": first_basic, "first_advanced_row": first_advanced,
            "basic_first": basic_first,
            "reason": "" if basic_first else
                      "advanced/full-mock basic se pehle rakha gaya"}


def habit_split(rows: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Practice, dohraai aur naapne ka step — kitni row me asli me hai."""
    if not rows:
        return {"ok": False, "reason_code": NO_PLAN}
    practice = _row_hits(rows, _PRACTICE_CUES)
    review = _row_hits(rows, _REVIEW_CUES)
    progress = _row_hits(rows, _PROGRESS_CUES)
    return {"ok": True, "practice_rows": len(practice),
            "review_rows": len(review), "progress_rows": len(progress),
            "both": bool(practice and review)}


# ── NAAP: har contract point ka apna evaluator ───────────────────────────────
NOT_ASKED_FOR = "not_asked_for"       # ye cheez farmaish me hi nahi thi
NO_SOURCES = "no_sources"             # source list hi nahi aayi
_DEV_RE = re.compile(r"[ऀ-ॿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _no(reason_code: str, observed: str) -> Dict[str, Any]:
    """NOT_MEASURED — wajah code ke saath. 'Theek hai' kabhi default nahi."""
    return {"status": NOT_MEASURED, "observed": observed, "reason": reason_code}


def _not_wanted(what: str) -> Dict[str, Any]:
    return _no(NOT_ASKED_FOR, f"{what} farmaish me maanga hi nahi gaya tha")


def _wants_paper(ctx: Dict[str, Any]) -> bool:
    ask: ExamAsk = ctx["ask"]
    return bool(ask.kind in (KIND_PAPER, KIND_BOTH) or ctx["questions"])


def _wants_plan(ctx: Dict[str, Any]) -> bool:
    ask: ExamAsk = ctx["ask"]
    return bool(ask.kind in (KIND_PLAN, KIND_BOTH) or ctx["plan_rows"])


def _c_exam_scope(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ask: ExamAsk = ctx["ask"]
    found = list(ask.exams) + list(ask.subject_labels) + (
        [ask.level] if ask.level else [])
    if not found:
        return {"status": NOT_MET,
                "observed": "farmaish me exam ka naam, subject aur level — teeno "
                            "me se ek bhi pakda nahi gaya",
                "reason": "kis cheez ka paper/plan hai ye tay nahi hua"}
    return {"status": MET,
            "observed": "pakda gaya: " + ", ".join(found),
            "reason": ""}


def _c_deliverable_kind(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ask: ExamAsk = ctx["ask"]
    if not ask.kind:
        return _no(NOT_ASKED_FOR, "farmaish me paper/plan me se kuch tay nahi tha")
    made: List[str] = []
    if ctx["questions"]:
        made.append(KIND_PAPER)
    if ctx["plan_rows"]:
        made.append(KIND_PLAN)
    if not made:
        return {"status": NOT_MET,
                "observed": f"maanga gaya {ask.kind}, bana kuch bhi nahi",
                "reason": "deliverable khaali reh gaya"}
    wanted = ([KIND_PAPER, KIND_PLAN] if ask.kind == KIND_BOTH else [ask.kind])
    missing = [name for name in wanted if name not in made]
    if missing:
        return {"status": NOT_MET,
                "observed": f"maanga gaya {ask.kind}, bana {'+'.join(made)}",
                "reason": "reh gaya: " + ", ".join(missing)}
    return {"status": MET,
            "observed": f"maanga gaya {ask.kind}, bana {'+'.join(made)}",
            "reason": ""}


def _c_language(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ask: ExamAsk = ctx["ask"]
    if not ask.language:
        return _no(NOT_ASKED_FOR, "bhasha farmaish me nahi maangi gayi thi")
    blob = ctx["deliverable"]
    if not blob.strip():
        return _no(NO_PAPER, "naapne ke liye koi deliverable text nahi aaya")
    dev = bool(_DEV_RE.search(blob))
    latin = bool(_LATIN_RE.search(blob))
    observed = (f"maangi {ask.language}; deliverable me devanagari="
                f"{'haan' if dev else 'nahi'}, latin="
                f"{'haan' if latin else 'nahi'}")
    if ask.language == LANG_HINDI:
        ok = dev
    elif ask.language == LANG_ENGLISH:
        ok = latin
    else:
        ok = dev and latin
    return {"status": MET if ok else NOT_MET, "observed": observed,
            "reason": "" if ok else "maangi hui bhasha ka script hi nahi mila"}


def _c_question_count(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ask: ExamAsk = ctx["ask"]
    if not ask.question_count:
        return _no(NOT_ASKED_FOR, "ginti farmaish me nahi maangi gayi thi")
    made = len(ctx["questions"])
    observed = f"maange {ask.question_count}, parse hue {made}"
    if made == ask.question_count:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": f"{abs(ask.question_count - made)} question ka farak"}


def _src_point(key: str, label: str):
    """Source ki ek family — mili to MET, source aaye hi nahi to NOT_MEASURED."""
    def check(ctx: Dict[str, Any]) -> Dict[str, Any]:
        if not ctx["sources"]:
            return _no(NO_SOURCES, "naapne ke liye source list hi nahi aayi")
        rows = ctx[key]
        if not rows:
            return {"status": NOT_MET,
                    "observed": f"{len(ctx['sources'])} source aaye, {label} "
                                f"ek bhi nahi",
                    "reason": f"{label} ke bina ye point MET nahi ho sakta"}
        ids = [str(row.get("source_id") or "?") for row in rows][:4]
        return {"status": MET,
                "observed": f"{len(rows)} {label}: " + ", ".join(ids),
                "reason": ""}
    return check


def _c_deep_read(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not ctx["sources"]:
        return _no(NO_SOURCES, "naapne ke liye source list hi nahi aayi")
    deep = ctx["deep"]
    observed = (f"{len(ctx['sources'])} source me se {len(deep)} ka asli text/"
                f"claims padha gaya")
    if not deep:
        return {"status": NOT_MET, "observed": observed,
                "reason": "sirf title/snippet par paper banana padhna nahi hai"}
    return {"status": MET, "observed": observed, "reason": ""}


def _c_syllabus_coverage(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    split: CoverageSplit = ctx["coverage"]
    if not split.ok:
        return _no(split.reason_code,
                   "syllabus ke topic aur paper ka milan naapa nahi ja saka")
    observed = (f"{split.topics} topic me se {split.covered} par question bana "
                f"(share {split.covered_share}), paper me {split.questions} "
                f"question")
    if split.full_coverage:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed, "reason": split.reason}


def _c_difficulty_mix(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    split: DifficultySplit = ctx["difficulty"]
    if not split.ok:
        return _no(split.reason_code, "difficulty ka mix naapa nahi ja saka")
    counts = split.counts
    observed = ("; ".join(f"{band}={counts.get(band, 0)}"
                          for band in DIFFICULTY_BANDS)
                + " (ye naap PROXY hai: stem ke shabd + ank + marks se)")
    if split.mixed:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed, "reason": split.reason}


def _c_no_duplicates(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    split: DuplicateSplit = ctx["duplicate"]
    if not split.ok:
        return _no(split.reason_code, "duplicate ka overlap naapa nahi ja saka")
    observed = (f"{split.questions} question ki har jodi naapi gayi (hadd "
                f"{split.threshold}), ek jaisi jodi {split.duplicate_pairs}")
    if split.clean:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed, "reason": split.reason}


def _c_answer_key(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    questions = ctx["questions"]
    if not questions:
        return _no(NO_PAPER, "paper me se ek bhi question parse nahi hua")
    answered = [q.number for q in questions if q.has_answer]
    observed = (f"{len(questions)} question me se {len(answered)} par jawab hai "
                f"(key APP ne banayi hai, official key nahi)")
    if len(answered) == len(questions):
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": f"{len(questions) - len(answered)} question bina jawab"}


def _c_solutions(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    questions = ctx["questions"]
    if not questions:
        return _no(NO_PAPER, "paper me se ek bhi question parse nahi hua")
    solved = [q.number for q in questions if q.has_solution]
    if not ctx["ask"].wants_solutions and not solved:
        return _not_wanted("step-by-step hal")
    observed = (f"{len(questions)} question me se {len(solved)} par hal ki line "
                f"mili")
    if len(solved) == len(questions):
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": f"{len(questions) - len(solved)} question par sirf jawab, "
                      f"hal nahi"}


def _c_solvable(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    split: SolvabilitySplit = ctx["solvability"]
    if not split.ok:
        return _no(split.reason_code,
                   "ginti wale question chala kar dekhe nahi ja sake")
    observed = (f"{split.checked} numeric question chalaye gaye, {split.solved} "
                f"bane (share {split.solved_share})")
    if split.all_solvable:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed, "reason": split.reason}


def _c_marks_and_time(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    if not ctx["paper"].strip():
        return _no(NO_PAPER, "paper ka text hi nahi aaya")
    found = ctx["marks_time"]
    observed = (f"total marks={found['total_marks'] or 'nahi likha'}, "
                f"duration={found['duration_minutes'] or 'nahi likha'} min")
    if found["total_marks"] and found["duration_minutes"]:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": "marks ya waqt me se ek likha hi nahi gaya"}


def _c_negative_marking(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_paper(ctx):
        return _not_wanted("paper")
    if not ctx["paper"].strip():
        return _no(NO_PAPER, "paper ka text hi nahi aaya")
    stated = ctx["negative_stated"]
    observed = ("negative marking ka niyam likha hai" if stated
                else "negative marking ka zikr nahi")
    if stated:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": "galat jawab par kitna katega — ye bataye bina paper "
                      "practice ke liye adhoora hai"}


def _c_past_pattern(ctx: Dict[str, Any]) -> Dict[str, Any]:
    claimed = bool(_PATTERN_RE.search(ctx["deliverable"]))
    if not ctx["ask"].wants_past_pattern and not claimed:
        return _not_wanted("purane paper ka pattern")
    backing = list(ctx["official"]) + [{"source_id": sid} for sid in ctx["deep"]]
    observed = (f"pattern ka zikr={'haan' if claimed else 'nahi'}, uske peeche "
                f"official/padhe hue source={len(backing)}")
    if not ctx["sources"]:
        return _no(NO_SOURCES, "pattern ka daawa naapne ke liye source nahi aaye")
    if backing:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": "pattern ka daawa bina padhe hue source par tika hai"}


def _c_key_matched_official(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Ye point jaan-boojh kar kabhi MET nahi hota — aur ye chhupaya nahi jaata."""
    return _no("official_key_unavailable",
               "aane wale exam ki official answer key maujood hi nahi hoti, "
               "isliye app ki key usse milayi nahi ja sakti")


def _c_plan_rows(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_plan(ctx):
        return _not_wanted("study plan")
    rows = ctx["plan_rows"]
    if not rows:
        return {"status": NOT_MET,
                "observed": "plan me ek bhi aisi line nahi jisme kaam aur waqt ho",
                "reason": NO_PLAN}
    timed = [row for row in rows if float(row.get("minutes") or 0) > 0]
    observed = f"{len(rows)} row bani, {len(timed)} me waqt bhi likha hai"
    if timed:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": "kis kaam ko kitna waqt — likha hi nahi gaya"}


def _c_plan_time_budget(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_plan(ctx):
        return _not_wanted("study plan")
    split: PlanSplit = ctx["plan_split"]
    if not split.ok:
        return _no(split.reason_code, "plan ka waqt jodha nahi ja saka")
    observed = (f"plan ka total {split.total_minutes:.0f} min vs mila hua "
                f"{split.minutes_available:.0f} min (load {split.load_share})")
    if split.fits:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed, "reason": split.reason}


def _c_plan_daily(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_plan(ctx):
        return _not_wanted("study plan")
    split: PlanSplit = ctx["plan_split"]
    if not split.ok or split.day_realistic is None:
        return _no(split.reason_code or NO_TIME_BUDGET,
                   "kisi ek din ka bojh naapa nahi ja saka (din ka label nahi mila)")
    observed = (f"sabse bhaari {split.worst_day}: "
                f"{split.worst_day_minutes:.0f} min (hadd "
                f"{split.daily_ceiling:.0f} min)")
    if split.day_realistic:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed, "reason": split.reason}


def _c_weak_area_first(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_plan(ctx):
        return _not_wanted("study plan")
    found = ctx["order"]
    if not found.get("ok"):
        return _no(str(found.get("reason_code") or NO_PLAN),
                   "basic aur advanced ka kram naapa nahi ja saka")
    observed = (f"basic/diagnostic row={found['basic_rows']} (pehli "
                f"{found['first_basic_row']}), advanced row="
                f"{found['advanced_rows']} (pehli {found['first_advanced_row']})")
    if found.get("basic_first"):
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": str(found.get("reason") or "")}


def _c_practice_and_review(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_plan(ctx):
        return _not_wanted("study plan")
    found = ctx["habit"]
    if not found.get("ok"):
        return _no(str(found.get("reason_code") or NO_PLAN),
                   "practice aur dohraai ki row naapi nahi ja saki")
    observed = (f"practice row={found['practice_rows']}, revision row="
                f"{found['review_rows']}")
    if found.get("both"):
        return {"status": MET, "observed": observed, "reason": ""}
    missing = ("revision/dohraai" if found["practice_rows"] else "practice")
    return {"status": NOT_MET, "observed": observed,
            "reason": f"{missing} ka apna slot plan me nahi hai"}


def _c_progress_check(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _wants_plan(ctx):
        return _not_wanted("study plan")
    found = ctx["habit"]
    if not found.get("ok"):
        return _no(str(found.get("reason_code") or NO_PLAN),
                   "aage badhne ka naap plan me dhoondha nahi ja saka")
    observed = f"naapne wali row={found['progress_rows']}"
    if found["progress_rows"]:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": "mock/score/accuracy jaisa koi naapne wala step nahi"}


def _c_not_official_stated(ctx: Dict[str, Any]) -> Dict[str, Any]:
    blob = ctx["deliverable"]
    if not blob.strip():
        return _no(NO_PAPER, "naapne ke liye koi deliverable text nahi aaya")
    found = ctx["honesty"]
    observed = (f"practice-only likha={'haan' if found['practice_only'] else 'nahi'}"
                f", official-nahi likha="
                f"{'haan' if found['not_official'] else 'nahi'}")
    if found["practice_only"] and found["not_official"]:
        return {"status": MET, "observed": observed, "reason": ""}
    return {"status": NOT_MET, "observed": observed,
            "reason": "dono baat saaf likhni zaroori hai, warna user ise asli "
                      "paper samajh sakta hai"}


def _c_no_prediction(ctx: Dict[str, Any]) -> Dict[str, Any]:
    blob = ctx["deliverable"]
    if not blob.strip():
        return _no(NO_PAPER, "naapne ke liye koi deliverable text nahi aaya")
    hits = ctx["predictions"]
    if not hits:
        return {"status": MET,
                "observed": "'yahi question aayega' jaisa ek bhi vaakya nahi",
                "reason": ""}
    return {"status": NOT_MET,
            "observed": f"{len(hits)} aisa vaakya mila: " + "; ".join(hits[:3]),
            "reason": "app ke paas aane wale paper ki jaankari nahi hai"}


def _c_no_score_promise(ctx: Dict[str, Any]) -> Dict[str, Any]:
    blob = ctx["deliverable"]
    if not blob.strip():
        return _no(NO_PAPER, "naapne ke liye koi deliverable text nahi aaya")
    hits = ctx["promises"]
    if not hits:
        return {"status": MET,
                "observed": "score/rank/selection ka koi waada nahi",
                "reason": ""}
    return {"status": NOT_MET,
            "observed": f"{len(hits)} waada mila: " + "; ".join(hits[:3]),
            "reason": "kitne number aayenge ye app tay nahi kar sakta"}


_REFUSAL_CUES: Tuple[str, ...] = (
    "nahi bana sakta", "nahi bana paaya", "kaafi source nahi", "syllabus nahi mila",
    "source nahi mile", "adhoora", "incomplete", "cannot build", "not enough",
    "missing", "reh gaya", "nahi kar saka",
)


def _c_honest_final_decision(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """SABSE AAKHIR me naapa jaata hai: kuch fail tha to bhi de diya gaya?

    Isliye `measure()` me iska kram badalna is point ko andha kar dega — wo
    baat wahan bhi likhi hai. "Diya gaya" ka faisla TEXT se nahi, asli
    deliverable se hota hai (parse hue question / plan ki row), kyunki text me
    "paper" shabd likh dena paper banana nahi hai.
    """
    delivered = bool(ctx["questions"] or ctx["plan_rows"])
    refused = bool(_matched(_norm(ctx["deliverable"]), _REFUSAL_CUES))
    failed = list(ctx["_hard_fail_ids"])
    if not delivered and not refused:
        return _no("no_decision",
                   "na deliverable bana na saaf inkaar likha gaya — imaandaari "
                   "naapi hi nahi ja saki")
    observed = (f"deliverable={'diya gaya' if delivered else 'nahi diya'}, "
                f"inkaar/missing likha={'haan' if refused else 'nahi'}, "
                f"NOT_MET point={len(failed)}")
    if delivered and failed:
        return {"status": NOT_MET, "observed": observed,
                "reason": "poora na hone ke bawajood deliverable de diya gaya: "
                          + ", ".join(failed[:6])}
    return {"status": MET, "observed": observed, "reason": ""}



_EVALUATORS: Dict[str, Any] = {
    "exam_scope": _c_exam_scope,
    "deliverable_kind": _c_deliverable_kind,
    "language_honoured": _c_language,
    "question_count_honoured": _c_question_count,
    "official_syllabus_source": _src_point("official", "official source"),
    "textbook_source": _src_point("textbook", "kitaab/curriculum source"),
    "pedagogy_evidence": _src_point("pedagogy", "padhai-tareeqe ki research"),
    "read_arguments_not_summaries": _c_deep_read,
    "syllabus_coverage": _c_syllabus_coverage,
    "difficulty_mix": _c_difficulty_mix,
    "no_duplicate_questions": _c_no_duplicates,
    "answer_key_present": _c_answer_key,
    "solutions_stepwise": _c_solutions,
    "question_solvable": _c_solvable,
    "marks_and_time": _c_marks_and_time,
    "negative_marking_stated": _c_negative_marking,
    "past_pattern_evidence": _c_past_pattern,
    "key_matched_official": _c_key_matched_official,
    "plan_rows_exist": _c_plan_rows,
    "plan_time_budget": _c_plan_time_budget,
    "plan_daily_realistic": _c_plan_daily,
    "weak_area_first": _c_weak_area_first,
    "practice_and_review": _c_practice_and_review,
    "progress_check": _c_progress_check,
    "not_official_stated": _c_not_official_stated,
    "no_question_prediction": _c_no_prediction,
    "no_score_promise": _c_no_score_promise,
    "honest_final_decision": _c_honest_final_decision,
}


# ── NAAP: ek hi jagah, ek hi kram, har point ka apna nateeja ─────────────────
def measure(ask: Optional[ExamAsk] = None, paper: Any = "", plan: Any = "",
            syllabus: Any = "", sources: Iterable[Any] = (),
            evaluate: Optional[Any] = None) -> Dict[str, Any]:
    """Contract ke har point ko naapo. Default MET nahi — default NOT_MEASURED.

    `honest_final_decision` jaan-boojh kar SABSE AAKHIR me naapa jaata hai,
    kyunki uska sawaal hi ye hai: "jo point fail hue, unke bawajood deliverable
    de diya gaya ya nahi". Kram badalna is point ko andha kar dega.
    """
    missing_eval = [pid for pid in CONTRACT_IDS if pid not in _EVALUATORS]
    if missing_eval:
        raise AssertionError(
            "contract point bina naap ke reh gaya: " + ", ".join(missing_eval))

    ask = ask or ExamAsk(asked=False, reason=NOT_ASKED_REASON)
    paper_text = _text_of(paper)
    plan_text = _text_of(plan)
    source_list = list(sources or ())
    questions = apply_answer_key(questions_from_text(paper_text),
                                 answer_key_from_text(paper_text))
    topics = syllabus_topics(syllabus)
    plan_rows = plan_rows_from_text(plan_text)
    minutes = minutes_available_of(ask)
    if not minutes and ask.duration_minutes:
        minutes = float(ask.duration_minutes)
    ctx: Dict[str, Any] = {
        "ask": ask,
        "paper": paper_text,
        "plan": plan_text,
        "syllabus": _text_of(syllabus),
        # Dono deliverable ka jodha hua text — honesty ke cue isi par naape
        # jaate hain, kyunki "official nahi hai" ki line kisi bhi hisse me ho
        # sakti hai.
        "deliverable": (paper_text + "\n" + plan_text).strip(),
        "sources": source_list,
        "questions": questions,
        "topics": topics,
        "plan_rows": plan_rows,
        "official": official_sources(source_list),
        "textbook": textbook_sources(source_list),
        "pedagogy": pedagogy_sources(source_list),
        "deep": deeply_read(source_list),
        "coverage": coverage_split(topics, questions),
        "difficulty": difficulty_split(questions),
        "duplicate": duplicate_split(questions),
        "solvability": solvability_split(questions, evaluate=evaluate),
        "plan_split": plan_time_split(plan_rows, minutes),
        "order": order_split(plan_rows),
        "habit": habit_split(plan_rows),
        "marks_time": marks_and_time_in(paper_text),
        "negative_stated": negative_marking_stated(paper_text),
        "honesty": not_official_stated(paper_text + "\n" + plan_text),
        "predictions": prediction_claims(paper_text + "\n" + plan_text),
        "promises": score_promises(paper_text + "\n" + plan_text),
        "_hard_fail_ids": [],
    }

    checks: List[Dict[str, Any]] = []
    for point in CONTRACT:
        result = dict(_EVALUATORS[point.point_id](ctx))
        status = result.get("status")
        if status not in CHECK_STATUSES:
            status = NOT_MEASURED
            result["reason"] = ("naap ka nateeja pehchana nahi gaya, isliye "
                               "NOT_MEASURED (jhoothe MET se behtar)")
        row = {"point_id": point.point_id, "label": point.label,
               "group": point.group, "status": status,
               "expected": result.get("expected") or point.needs,
               "observed": result.get("observed") or "",
               "reason": result.get("reason") or ""}
        if point.blocked_by:
            row["blocked_by"] = point.blocked_by
        checks.append(row)
        if status == NOT_MET:
            ctx["_hard_fail_ids"].append(point.point_id)

    by_status = {name: [row["point_id"] for row in checks
                        if row["status"] == name] for name in CHECK_STATUSES}
    return {
        "schema": SCHEMA_VERSION,
        "asked": bool(ask.asked),
        "contract_points": CONTRACT_POINTS,
        "checks": checks,
        "met": by_status[MET],
        "not_met": by_status[NOT_MET],
        "not_measured": by_status[NOT_MEASURED],
        "met_count": len(by_status[MET]),
        "not_met_count": len(by_status[NOT_MET]),
        "not_measured_count": len(by_status[NOT_MEASURED]),
        "structurally_blocked": list(STRUCTURALLY_BLOCKED),
        "questions_parsed": len(questions),
        "syllabus_topics": len(topics),
        "plan_rows": len(plan_rows),
        "coverage": ctx["coverage"].to_dict(),
        "difficulty": ctx["difficulty"].to_dict(),
        "duplicate": ctx["duplicate"].to_dict(),
        "solvability": ctx["solvability"].to_dict(),
        "plan_time": ctx["plan_split"].to_dict(),
        "official_source_count": len(ctx["official"]),
        "textbook_source_count": len(ctx["textbook"]),
        "pedagogy_source_count": len(ctx["pedagogy"]),
        "deeply_read_count": len(ctx["deep"]),
        "prediction_claims": list(ctx["predictions"]),
        "score_promises": list(ctx["promises"]),
        "paper_is_practice_only": PAPER_IS_PRACTICE_ONLY,
        "is_exam_authority": IS_EXAM_AUTHORITY,
        "answer_key_is_app_made": ANSWER_KEY_IS_APP_MADE,
        "question_prediction_promised": QUESTION_PREDICTION_PROMISED,
        "score_promised": SCORE_PROMISED,
        "leaked_paper_used": LEAKED_PAPER_USED,
        "difficulty_is_proxy": DIFFICULTY_IS_PROXY,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "deterministic": DETERMINISTIC,
        "provider_cost": PROVIDER_COST,
        "not_official_note": NOT_OFFICIAL_NOTE,
        "cannot_measure": list(CANNOT_MEASURE),
        "exam_list_is_not_exhaustive": EXAM_LIST_IS_NOT_EXHAUSTIVE,
        "subject_list_is_not_exhaustive": SUBJECT_LIST_IS_NOT_EXHAUSTIVE,
    }


# ── gate band hone par: "wanted" key hi asli farak hai ──────────────────────
# Sirf `not_asked()` me `wanted` key hoti hai. `gate()` ke record me ye key
# hoti hi NAHI. Isse caller saaf-saaf farak kar sakta hai: "darwaza band tha"
# vs "lane chali par kuch nahi mila".
def not_asked(question: str = "") -> Dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "wanted": False,
        "asked": False,
        "ran": False,
        "reason": request_reason(question) if question else NOT_ASKED_REASON,
        "queries": [],
        "checks": [],
        "contract_points": CONTRACT_POINTS,
        "gemini_calls": GEMINI_CALLS,
        "network_used": NETWORK_USED,
        "provider_cost": PROVIDER_COST,
    }


def gate(question: str = "", paper: Any = "", plan: Any = "",
         syllabus: Any = "", sources: Iterable[Any] = (),
         evaluate: Optional[Any] = None,
         limit: int = MAX_STUDY_QUERIES) -> Dict[str, Any]:
    """Ek hi darwaza: farmaish exam ki hai? to query + poori naap wapas.

    Farmaish exam/padhai ki na ho to `not_asked()` — aur usme `wanted=False`
    hota hai, jo `gate()` ke jawab me kabhi nahi hota.
    """
    if not is_request(question):
        return not_asked(question)
    ask = ask_of(question)
    record = measure(ask=ask, paper=paper, plan=plan, syllabus=syllabus,
                     sources=sources, evaluate=evaluate)
    rows = lane_queries(ask, limit=limit)
    record["ran"] = True
    record["ask"] = ask.to_dict()
    record["reason"] = ask.reason
    record["queries"] = [row["query"] for row in rows]
    record["lane_queries"] = rows
    record["lead_queries"] = lead_queries(ask)
    return record


















