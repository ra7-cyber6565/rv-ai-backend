"""
ResearchPlanner — Spec Section 1

Kaam:
    1. Question ko classify karo (factual/scientific/medical/... multidisciplinary)
    2. Relevant FIELDS identify karo — har subject nahi, sirf relevant
    3. Sub-questions banao
    4. Search queries banao (Hinglish filler hataao, round 2/3 ke liye expand karo)
    5. Decide karo kaun-kaun se connectors chalane hain

Poora module rule-based aur FREE hai — ek bhi Gemini call nahi.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .depth import DepthConfig
from .local_language import normalize
from .query_builder import is_instruction_prompt, search_query, topic_terms
from .requested import parse_requests

# Query ki upper limit. OpenAlex ne live test mein HTTP 400 diya tha kyunki
# poora 2000-character prompt URL parameter mein chala gaya tha.
_MAX_QUERY_CHARS = 200

# ── Spec Section 1: question types ───────────────────────────────────────────
QUESTION_TYPES: Dict[str, List[str]] = {
    "medical": ["cancer", "disease", "bimari", "dawa", "medicine", "treatment", "symptom",
                "health", "vitamin", "protein", "brain", "cells", "doctor", "diet",
                "fasting", "depression", "neuroplasticity", "immunity", "vaccine"],
    "scientific": ["science", "physics", "chemistry", "biology", "quantum", "atom",
                   "molecule", "evolution", "gravity", "energy", "experiment", "vigyan",
                   "battery", "climate", "genome", "reaction", "catalyst"],
    "mathematical": ["calculate", "equation", "formula", "probability", "statistics",
                     "math", "algebra", "geometry", "integral", "derivative", "percent",
                     "average", "kitna", "ratio"],
    "historical": ["history", "itihas", "ancient", "empire", "war", "century", "sant",
                   "civilization", "medieval", "colonial", "revolution", "samrajya",
                   "raja", "dynasty", "lok devta"],
    "psychological": ["behavior", "mind", "mental", "emotion", "psychology", "cognitive",
                      "depression", "anxiety", "personality", "motivation", "trauma",
                      "feelings", "bias"],
    "technical": ["code", "software", "hardware", "algorithm", "programming", "computer",
                  "network", "database", "api", "system", "ai", "machine learning",
                  "model", "training data", "llm", "neural"],
    "financial": ["economy", "stock", "investment", "market", "money", "finance", "gdp",
                  "inflation", "bank", "trade", "arthik", "profit", "cost", "salary"],
    "sociological": ["society", "culture", "social", "community", "gender", "race",
                     "inequality", "discrimination", "political", "policy", "samaj",
                     "caste", "religion", "law", "rights"],
    "prediction": ["future", "predict", "forecast", "will happen", "hoga", "chance",
                   "trend", "kya hoga", "aage"],
    "philosophical": ["meaning", "consciousness", "ethics", "moral", "existence",
                      "philosophy", "truth", "reality", "naitikta", "free will"],
    "creative": ["design", "invent", "create", "banao", "naya idea", "story", "imagine",
                 "ban sakta", "kya ban sakta hai"],
    "unresolved_research": ["unsolved", "unknown", "mystery", "open problem", "cure",
                            "ilaj", "why does", "kyon hota", "no one knows", "hypothesis"],
}

FIELD_MAP: Dict[str, List[str]] = {
    "medical": ["Medicine", "Biology", "Biochemistry", "Public Health"],
    "scientific": ["Physics", "Chemistry", "Biology", "Materials Science"],
    "mathematical": ["Mathematics", "Statistics", "Computer Science"],
    "historical": ["History", "Anthropology", "Political Science", "Sociology"],
    "psychological": ["Psychology", "Neuroscience", "Behavioral Science"],
    "technical": ["Computer Science", "Engineering", "Data Science", "Statistics"],
    "financial": ["Economics", "Finance", "Statistics", "Political Science"],
    "sociological": ["Sociology", "Psychology", "Political Science", "Ethics", "Law"],
    "prediction": ["Statistics", "Data Science", "Forecasting"],
    "philosophical": ["Philosophy", "Ethics", "Psychology", "Neuroscience"],
    "creative": ["Design", "Engineering", "Materials Science"],
    "unresolved_research": ["Research Methodology", "Domain-specific literature"],
    "factual": ["General Knowledge"],
}

# Hinglish filler — poore phrase/word ke roop mein hataao (substring se nahi,
# warna "kya" hatane se "Rajasthan" jaise words ke andar ka text bigadta hai)
_FILLER_PHRASES = [
    "ke baare mein bataiye", "ke baare mein batao", "ke baare mein", "ke bare me",
    "mujhe batao", "please batao", "kya hota hai", "kya hai", "kaun hai", "kaun the",
    "kya kar sakta hai", "ke bare mein", "detail mein batao", "explain karo",
    "tell me about", "what is", "who is", "explain",
]
_FILLER_WORDS = {"kya", "hai", "batao", "bataiye", "mujhe", "please", "the", "ka",
                 "ki", "ke", "se", "mein", "me", "aur", "kaise", "kyon", "kaun"}

_BOOK_HINTS = ("book", "kitab", "kitaab", "granth", "mahagranth", "shastra", "veda",
               "author", "likha", "novel", "literature", "chapter")


class ResearchPlanner:
    # ── 1 + 2. classify + fields ──────────────────────────────────────────────
    def classify(self, question: str) -> Dict:
        # Pehle local shorthand khol lo — warna "reserch" ya "smjao" kisi keyword
        # se match nahi karta aur sawaal galat classify ho jaata hai.
        q = normalize(question or "").lower()
        detected: List[str] = []
        fields: List[str] = []

        for qtype, keywords in QUESTION_TYPES.items():
            if any(kw in q for kw in keywords):
                detected.append(qtype)
                for f in FIELD_MAP.get(qtype, []):
                    if f not in fields:
                        fields.append(f)

        if not detected:
            detected = ["factual"]
            fields = list(FIELD_MAP["factual"])

        primary = detected[:3]
        if len(detected) >= 3:
            primary = detected[:3] + ["multidisciplinary"]

        return {
            "question_types": primary,
            "all_detected_types": detected,
            "relevant_fields": fields[:6],
            "is_scientific": any(t in detected for t in
                                 ("scientific", "medical", "mathematical", "technical")),
            "is_medical": "medical" in detected,
            "is_multidisciplinary": len(detected) >= 3,
            "needs_books": any(h in q for h in _BOOK_HINTS) or "historical" in detected,
            "is_creative": "creative" in detected,
            "is_unresolved": "unresolved_research" in detected,
        }

    # ── 3. sub-questions (free, rule-based) ───────────────────────────────────
    def sub_questions(self, question: str, cls: Optional[Dict] = None) -> List[str]:
        """
        `cls` classify() ka dict hai — ya uska SUPERSET (plan() ka poora dict bhi
        chalta hai, orchestrator wahi paas karta hai). Isliye har field .get() se
        padhi jaati hai: ek missing key se poora research round girna nahi chahiye.
        """
        cls = cls or self.classify(question)
        core = self.clean_query(question)
        subs = [
            f"{core} — established facts aur evidence kya hai?",
            f"{core} — mechanism/wajah kya hai?",
        ]
        if cls.get("is_scientific"):
            subs.append(f"{core} — peer-reviewed studies kya kehti hain, methodology kya thi?")
        if cls.get("is_multidisciplinary"):
            fields = ", ".join(cls.get("relevant_fields", [])[:3])
            subs.append(f"{core} — {fields} ke nazariye kaise connect hote hain?")
        if cls.get("is_medical"):
            subs.append(f"{core} — clinical evidence, risks aur contraindications kya hain?")
        if cls.get("is_unresolved") or cls.get("is_creative"):
            subs.append(f"{core} — kya abhi tak unknown hai aur kaun sa test isse settle karega?")
        subs.append(f"{core} — kaun sa evidence is baat ke KHILAF jaata hai?")
        return subs[:6]

    # ── 4. search queries ─────────────────────────────────────────────────────
    def clean_query(self, question: str) -> str:
        """
        Sawaal se search-worthy query banao.

        DO RAASTE, jaan-boojh kar:

        1. LAMBA, instruction-style prompt ("...research papers khojo, 3
           hypotheses banao, HYPOTHESIS label karo..."): iska poora text query
           banana do galtiyan karta tha — (a) 2000-character query se OpenAlex ne
           HTTP 400 diya, aur (b) connectors ke content_terms() ne prompt ke
           PEHLE 6 shabd uthaye, jo filler the ("मान लो मानव सभ्यता को अगले 100
           वर्षों"), isliye search "human civilization next years" par chali —
           energy par nahi. Aise prompt ke liye query_builder topic terms
           nikaalta hai.

        2. CHHOTA, seedha sawaal ("cancer ki nai dawa par research kya kehti
           hai"): iska purana filler-strip raasta pehle se theek kaam karta hai,
           isliye use CHHEDA NAHI GAYA. Naya scoring chhote sawaal par lagane ki
           koi zaroorat nahi thi, aur risk tha ki asli shabd ud jaaye.
        """
        if is_instruction_prompt(question):
            topic = search_query(question, max_chars=_MAX_QUERY_CHARS)
            if len(topic) >= 3:
                return topic

        q = " " + normalize(question or "").lower().strip() + " "
        for phrase in _FILLER_PHRASES:
            q = q.replace(" " + phrase + " ", " ")
        tokens = [t for t in re.findall(r"[\w\-']+", q) if t not in _FILLER_WORDS]
        cleaned = " ".join(tokens).strip()
        # Kabhi khaali query mat bhejo — warna search 0 results dega
        if len(cleaned) < 3:
            cleaned = (question or "").strip()
        # Aur kabhi bahut LAMBI bhi mat bhejo — ye wahi 400 wali galti hai.
        if len(cleaned) > _MAX_QUERY_CHARS:
            topic = search_query(question, max_chars=_MAX_QUERY_CHARS)
            cleaned = topic if len(topic) >= 3 else \
                cleaned[:_MAX_QUERY_CHARS].rsplit(" ", 1)[0]
        return cleaned

    def topic_terms(self, question: str, limit: int = 8) -> List[str]:
        """
        Sawaal ka topic — relevance guard aur report isi list ko dekhte hain.
        (Wrapper hai taaki baaki code ko query_builder import na karna pade.)
        """
        return topic_terms(question, limit=limit)

    def search_queries(self, question: str, cls: Optional[Dict] = None,
                       round_no: int = 1) -> List[str]:
        """
        Round 1: seedha cleaned query.
        Round 2+: Spec Section 2 ka "search expand karo" — field terms aur
        evidence/contradiction angle add karo.

        `cls` classify() ka dict ya uska superset (plan() ka dict) — dono chalte
        hain, kyunki plan() ke andar **cls spread hota hai. Fields .get() se
        padhte hain taaki round 2 kabhi KeyError se na ruke.
        """
        cls = cls or self.classify(question)
        base = self.clean_query(question)
        if round_no <= 1:
            return [base]

        queries = []
        fields = cls.get("relevant_fields", [])
        if round_no == 2:
            if fields:
                queries.append(f"{base} {fields[0]}")
            queries.append(f"{base} evidence study")
            if cls.get("is_scientific"):
                queries.append(f"{base} systematic review")
        else:
            if len(fields) > 1:
                queries.append(f"{base} {fields[1]}")
            queries.append(f"{base} criticism limitations")
            queries.append(f"{base} contradictory findings")
        return [q for q in queries if q][:3]

    # ── 5. connector plan ─────────────────────────────────────────────────────
    def connector_plan(self, cls: Dict, config: DepthConfig) -> Dict:
        """Har sawal pe har connector chalana bewakoofi hai — relevant chuno."""
        papers: List[str] = []
        if config.use_papers:
            papers = ["openalex", "crossref"]
            if cls.get("is_medical"):
                papers.append("pubmed")
            if cls.get("is_scientific"):
                papers += ["arxiv", "doaj"]
            if config.name == "MAXIMUM":
                papers.append("semantic_scholar")

        books: List[str] = []
        if config.use_books or cls.get("needs_books"):
            books = ["internet_archive", "open_library"]
            if config.name == "MAXIMUM":
                books.append("google_books")

        # Datasets (Spec §2 + §11) — raw data jispar claims tikte hain. Har sawal
        # ke liye har dataset source chalana bekaar hai; question type se chuno.
        # data_gov_in ko plan mein tabhi daalte hain jab key milne ki sambhavna
        # ho ya MAXIMUM ho — key na hone par wo honestly "ruka" report karta hai,
        # chup-chaap "0 result" nahi banta.
        datasets: List[str] = []
        if config.use_datasets:
            types = set(cls.get("all_detected_types", []))
            datasets = ["zenodo", "data_gov"]          # general, keyless
            if cls.get("is_medical") or "scientific" in types:
                datasets.append("who_gho")
            if types & {"financial", "sociological", "prediction", "historical",
                        "medical"}:
                datasets.append("world_bank")
            if "technical" in types:
                datasets.append("huggingface")
            if config.name == "MAXIMUM":
                datasets += ["world_bank", "huggingface", "data_gov_in"]

        return {
            "web": True,
            "papers": sorted(set(papers)),
            "books": sorted(set(books)),
            "datasets": sorted(set(datasets)),
        }

    # ── poora plan ────────────────────────────────────────────────────────────
    def plan(self, question: str, config: DepthConfig) -> Dict:
        cls = self.classify(question)
        return {
            **cls,
            "topic_terms": self.topic_terms(question),
            "sub_questions": self.sub_questions(question, cls),
            "queries": self.search_queries(question, cls, round_no=1),
            "connectors": self.connector_plan(cls, config),
            "depth": config.to_dict(),
            # Prompt mein user ne jo CHEEZEIN saaf-saaf maangi hain (3 hypotheses,
            # mathematical model, second-order chain, red-team) — wo yahin plan ke
            # andar aa jaati hain, taaki prompt banane wale aur report banane wale
            # dono ek hi list dekhein. Ye rule-based hai, ek bhi Gemini call nahi.
            "requests": parse_requests(question),
        }


# ── backwards compatibility ──────────────────────────────────────────────────
def classify_question(question: str) -> Dict:
    """Purana helper (agents/research_agent.py isse import karta tha)."""
    cls = ResearchPlanner().classify(question)
    return {
        "question_types": cls["question_types"],
        "relevant_fields": cls["relevant_fields"],
        "is_scientific": cls["is_scientific"],
    }
