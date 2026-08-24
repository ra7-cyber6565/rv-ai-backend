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
from typing import Callable, Dict, List, Optional

from .depth import DepthConfig
from .domain import detect as domain_detect
from . import lenses as lens_mod
from .local_language import normalize
from .patents import patent_intent
from .query_builder import is_instruction_prompt, search_query, topic_terms
from .requested import parse_requests
from .specialist_domains import (
    build_specialist_plan,
    phrase_hit,
    specialist_classification,
    specialist_queries,
)

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
    # Patent providers ki list connector layer ke paas hai (kaunsa provider key
    # ke bina chal sakta hai, ye wahi jaanta hai). Import LAZY hai aur object ek
    # baar banta hai: planner ka wada "rule-based aur sasta" hai, aur connectors
    # package import karna network ya key kuch nahi maangta — par har call par
    # naya object banana bekaar hai.
    _PATENT_FACADE = None

    # ── open lens selection (2026-08-23) ─────────────────────────────────────
    #
    # `specialist_domains.detect_profiles()` ek CLOSED keyword list hai. Naapa
    # gaya: intel ke 12 example sawaalon me se 10 par `specialist=False,
    # domain=generic` — "psycho-cybernetics", "default mode network", "naval
    # ravikant", "ramanujan", "einstein", "picasso" aur "ved puran rishi muni"
    # tak. List me 500 shabd jodne se deewar khisakti hai, hatti nahi.
    #
    # Isliye planner ab har sawaal par lens plan banata hai (research_engine/
    # lenses.py): "is sawaal par kaun se discipline / framework / thinker /
    # source-family lagti hai". Deterministic raasta HAMESHA chalta hai (₹0,
    # koi network nahi). `lens_generate` set ho to ek bounded model call bhi
    # hoti hai; fail/quota par chup-chaap deterministic par gir jaata hai.
    #
    # Lens list EVIDENCE NAHI hai — sirf search plan aur scoring vocabulary.
    lens_generate: Optional[Callable[..., str]] = None

    def lens_plan(self, question: str, base_query: str = "") -> Dict:
        """Cached lens plan. Ek sawaal par model call ek hi baar hoti hai."""
        key = (question or "")[:600]
        cached = getattr(self, "_lens_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        plan = lens_mod.build_lens_plan(
            question, base_query or self.clean_query(question),
            generate=self.lens_generate,
            allow_model=self.lens_generate is not None,
        )
        self._lens_cache = (key, plan)
        return plan

    def absorb_corpus_lenses(self, question: str, records) -> Dict:
        """Round ke baad: mile hue sources se naye lens seekho (₹0, model-free).

        Ye "padhte-padhte seekhna" hai — jo author/venue/dohraye gaye phrase
        ASLI sources me mile, wo agle round ki queries me chale jaate hain.
        Scoring anchor JAAN-BOOJHKAR nahi badalta (ek run ke beech scoring
        badalne se round-1 aur round-2 ke score tulnaayog nahi rehte), isliye
        `plan()` ka `lens_scoring_query` jaisa tha waisa hi rehta hai.
        """
        key = (question or "")[:600]
        cached = getattr(self, "_lens_cache", None)
        base = cached[1] if (cached and cached[0] == key) else self.lens_plan(question)
        try:
            extra = lens_mod.lenses_from_sources(records, question=question)
            merged = lens_mod.merge_corpus_lenses(base, extra)
        except Exception:
            return base  # lens ek sudhaar hai, zaroorat nahi
        self._lens_cache = (key, merged)
        return merged

    @property
    def _patent_providers(self):
        cls = type(self)
        if cls._PATENT_FACADE is None:
            from .connectors import PatentDiscoveryConnector  # noqa: PLC0415
            cls._PATENT_FACADE = PatentDiscoveryConnector()
        return cls._PATENT_FACADE

    # ── 1 + 2. classify + fields ──────────────────────────────────────────────
    def classify(self, question: str) -> Dict:
        # Pehle local shorthand khol lo — warna "reserch" ya "smjao" kisi keyword
        # se match nahi karta aur sawaal galat classify ho jaata hai.
        q = normalize(question or "").lower()
        detected: List[str] = []
        fields: List[str] = []

        for qtype, keywords in QUESTION_TYPES.items():
            # Exact phrase boundary matters here.  The old substring rule made
            # ``physics`` match inside ``metaphysics`` and ``science`` match
            # ``occult sciences``.  That silently routed philosophical/history
            # questions through hard-science connectors and evidence rules.
            if any(phrase_hit(q, kw) for kw in keywords):
                detected.append(qtype)
                for f in FIELD_MAP.get(qtype, []):
                    if f not in fields:
                        fields.append(f)

        specialist = specialist_classification(question)
        for qtype in specialist.get("question_types", []):
            if qtype not in detected:
                detected.append(qtype)
        for field in specialist.get("relevant_fields", []):
            if field not in fields:
                fields.append(field)

        # Strict domain profiles know important scientific topics that the old
        # flat keyword list never named (for example superconductivity).  The
        # previous substring bug accidentally classified such questions as
        # technical because ``ai`` appeared inside an unrelated word.  Once
        # substring matching was correctly removed, that accidental route also
        # disappeared.  Restore it explicitly from the real domain detector.
        dplan = domain_detect(question)
        domain_type = {
            "superconductivity": "scientific",
            "materials_physics": "scientific",
            "medicine_health": "medical",
            "biology_genetics": "scientific",
            "cs_ml": "technical",
            "energy_climate": "scientific",
            "economics": "financial",
            "chemistry": "scientific",
            "space": "scientific",
            "engineering": "technical",
            "archaeology_history": "historical",
        }.get(dplan.key)
        if domain_type and domain_type not in detected:
            detected.append(domain_type)
            for field in FIELD_MAP.get(domain_type, []):
                if field not in fields:
                    fields.append(field)

        if not detected:
            detected = ["factual"]
            fields = list(FIELD_MAP["factual"])

        primary = detected[:3]
        if len(detected) >= 3:
            primary = detected[:3] + ["multidisciplinary"]

        return {
            "question_types": primary,
            "all_detected_types": detected,
            "relevant_fields": fields[:10] if specialist.get("active") else fields[:6],
            "is_scientific": any(t in detected for t in
                                 ("scientific", "medical", "mathematical", "technical")),
            "is_medical": "medical" in detected,
            "is_multidisciplinary": len(detected) >= 3,
            "needs_books": (any(phrase_hit(q, h) for h in _BOOK_HINTS)
                            or "historical" in detected
                            or bool(specialist.get("needs_books"))),
            "is_creative": "creative" in detected,
            "is_unresolved": "unresolved_research" in detected,
            "specialist_active": bool(specialist.get("active")),
            "specialist_profile_keys": list(specialist.get("profile_keys", [])),
            "specialist_expected_lanes": list(specialist.get("expected_lanes", [])),
            "specialist_empirical_data_useful": bool(
                specialist.get("empirical_data_useful")),
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
        if cls.get("specialist_active"):
            subs.append(
                f"{core} — primary text/official document kya kehta hai, aur "
                "independent evidence asal mein kya establish karta hai?"
            )
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
        §4 + §15 ke baad ka behaviour.

        PURANA: round 1 mein SIRF ek query jaati thi (cleaned question), aur
        broadening par arXiv ek hi ambiguous phrase par utar aata tha
        (`all:"room-temperature"`), jisse room-temperature ferroelectricity
        jaisi cheezein aa gayi.

        AB: agar sawaal ka field pehchana gaya (domain.py), to round 1 mein hi
        structured expansion jaati hai — har query domain anchor ke saath
        ("room temperature superconductivity ambient pressure", "high pressure
        hydride superconductivity", ...). Round 2/3 ke liye branch-wise queries
        rotate hoti hain, aur ye sab DETERMINISTIC hai: reasoning model band ho
        to bhi discovery refine hoti rehti hai.
        """
        cls = cls or self.classify(question)
        base = self.clean_query(question)
        specialist_qs = specialist_queries(question, base, round_no=round_no, limit=4)
        if specialist_qs:
            return specialist_qs
        plan = domain_detect(question)

        # §11 — round 2 se opposition side bhi dhoondhna ZAROORI hai. Pehle
        # (known domain wale path par) sirf support-side branch queries jaati
        # thi, aur phir bhi report "apparent agreement" likh deti thi. Ab
        # criticism/contradictory query khud pipeline ka hissa hai, aur consensus
        # gate isi query ko dekh kar decide karta hai.
        counter_query = f"{base} contradictory findings criticism limitations"

        if plan.is_known:
            if round_no <= 1:
                # Round 1 = SAWAAL + uske alag-alag search intents (transport,
                # grid, computing, mechanism...). Pehle sirf `expanded_queries`
                # jaati thi, jo branch queries hi thi par intent ke roop mein
                # na plan hoti thi na report hoti thi. Ab intent-wise chalti
                # hai: focus intents pehle, aur base query kabhi nahi girti.
                intents = plan.search_intents(base, limit=3)
                qs = [base] + [i["query"] for i in intents]
            else:
                qs = ([base]
                      + plan.fallback_queries(base, round_no=round_no, limit=2)
                      + [counter_query])
            out, seen = [], set()
            for q in qs:
                key = (q or "").strip().lower()
                if q and key not in seen:
                    seen.add(key)
                    out.append(q)
            if out:
                return out[:4]

        # ── generic sawaal: yahin closed list ki deewar dikhti thi ────────────
        # Domain profile match nahi hua aur specialist list me bhi kuch nahi —
        # pehle poore round 1 me SIRF `[base]` jaata tha, yaani "psycho-
        # cybernetics self image" jaise sawaal ke liye ek hi andhi query. Ab
        # lens plan se concept/framework/thinker wali queries bhi jaati hain.
        # Lens kuch na de (pure English generic sawaal) to list bilkul pehle
        # jaisi rehti hai — yaani ye change us case me no-op hai.
        lens = self.lens_plan(question, base)
        lens_qs = [q for q in lens_mod.lens_queries(lens, base, round_no=round_no,
                                                   limit=4)
                   if (q or "").strip().lower() != (base or "").strip().lower()]

        if round_no <= 1:
            return [base, *lens_qs][:4] if lens_qs else [base]

        queries = []
        fields = cls.get("relevant_fields", [])
        if round_no == 2:
            if fields:
                queries.append(f"{base} {fields[0]}")
            queries.append(f"{base} evidence study")
            queries.append(counter_query)
            if cls.get("is_scientific"):
                queries.append(f"{base} systematic review")
        else:
            if len(fields) > 1:
                queries.append(f"{base} {fields[1]}")
            queries.append(f"{base} criticism limitations")
            queries.append(f"{base} contradictory findings")
        # Lens queries round 2+ me bhi jodte hain, par HAMESHA purani queries ke
        # BAAD — taaki jo behaviour benchmark me naapa gaya tha wo pehle jaisa
        # hi pehle number par rahe, aur lens sirf khaali jagah bhare.
        merged: List[str] = []
        seen_q = set()
        for q in [*queries, *lens_qs]:
            key = (q or "").strip().lower()
            if q and key not in seen_q:
                seen_q.add(key)
                merged.append(q)
        return merged[:4]

    # ── 5. connector plan ─────────────────────────────────────────────────────
    def connector_plan(self, cls: Dict, config: DepthConfig,
                       question: str = "") -> Dict:
        """
        §3 — domain-aware routing. Har sawal pe har connector chalana bewakoofi
        hai; ab wo bewakoofi CODE mein rok di gayi hai.

        Live failure: superconductivity ke sawaal par who_gho, world_bank aur
        data_gov_in chale (kyunki "scientific" + MAXIMUM), aur unhone maternal
        deaths, NHA estimate aur sunbed regulation laakar evidence pack ganda
        kar diya. Ab domain profile decide karta hai kaun chalega — aur jo band
        hua wo report mein wajah ke saath likha jaata hai (chupchaap nahi).
        """
        high_depth = config.name in {"MAXIMUM", "MARATHON"}
        specialist = build_specialist_plan(
            question or cls.get("question") or "",
            self.clean_query(question or cls.get("question") or ""),
        )

        papers: List[str] = []
        if config.use_papers:
            papers = ["openalex", "crossref"]
            if cls.get("is_medical"):
                papers.append("pubmed")
            if cls.get("is_scientific"):
                papers += ["arxiv", "doaj"]
            if high_depth:
                papers.append("semantic_scholar")

        books: List[str] = []
        if config.use_books or cls.get("needs_books"):
            books = ["internet_archive", "open_library"]
            if high_depth:
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
            if high_depth:
                datasets += ["world_bank", "huggingface", "data_gov_in"]

        # Interpretive/history/tradition questions do not become better merely
        # by adding unrelated generic datasets.  Empirical mind/frequency
        # questions keep the data tier; other specialist profiles disable it.
        if specialist.get("active"):
            profile_keys = set(specialist.get("profile_keys", []))
            if "mind_cognition" in profile_keys:
                datasets = [name for name in datasets
                            if name in {"zenodo", "data_gov", "who_gho"}]
            elif "frequency_claims" in profile_keys and cls.get("is_scientific"):
                datasets = [name for name in datasets
                            if name in {"zenodo", "data_gov"}]
            else:
                datasets = []

        dplan = domain_detect(question or cls.get("question") or "")
        intents = dplan.search_intents(self.clean_query(question or ""), limit=8)
        papers, drop_p = dplan.route(sorted(set(papers)), "papers")
        books, drop_b = dplan.route(sorted(set(books)), "books")
        datasets, drop_d = dplan.route(sorted(set(datasets)), "datasets")
        dropped = drop_p + drop_b + drop_d

        # Patents (₹0 patent batch, point 3) — routing ka poora faisla
        # `patents.patent_intent()` ka hai, aur wo DETERMINISTIC hai (koi LLM
        # nahi). Rule saaf hai: "Har generic question par patent connector
        # wastefully call mat karna." Isliye patent tier tabhi bharta hai jab
        #   (a) depth mode patents allow karta ho (QUICK nahi), AUR
        #   (b) sawaal mein patent/prior-art ki baat seedhe ho, ya wo
        #       invention-jaisa (technical cheez + banane/novelty ka iraada) ho.
        # Jab patent search NAHI hoti, tab bhi wajah plan mein likhi jaati hai —
        # taaki report mein "patent dekha hi nahi, aur ye kyun" saaf rahe.
        patents: List[str] = []
        intent = patent_intent(question or cls.get("question") or "")
        patent_reason = intent.get("reason", "")
        if not getattr(config, "use_patents", True):
            patent_reason = (f"{config.name} mode mein patent search band hai "
                             f"(patent APIs slow + fair-use limited hain)")
        elif intent.get("wanted"):
            # Key-gated provider ko list mein daalna hi nahi jab key nahi hai:
            # wo har round "no_key" log karta, jo shor hai. Key ho to wo apne
            # aap plan mein aa jaata hai.
            patents = self._patent_providers.available_names()
            if not patents:
                patent_reason = ("patent search chahiye thi par koi patent "
                                 "provider available nahi hai")

        # arXiv ko is field mein prathmikta chahiye to use sabse aage laao —
        # discovery ka wall-clock budget pehle sabse kaam ke connector par lage.
        prefer = list(dplan.profile.connectors)
        if prefer:
            papers.sort(key=lambda n: (prefer.index(n) if n in prefer else 99, n))

        return {
            "web": True,
            "papers": papers,
            "books": books,
            "datasets": datasets,
            # patents alag tier hai — patent legal document hai, science proof nahi
            "patents": patents,
            "patent_intent": {"wanted": bool(patents),
                              "kind": intent.get("kind", ""),
                              "signals": list(intent.get("signals", [])),
                              "reason": patent_reason},
            # §3 ka disclosure — kaun band hua aur kyun
            "domain": dplan.key,
            "domain_label": dplan.profile.label,
            "sub_domains": [b.key for b in dplan.focus_branches()],
            # §3 (2026-08-21) — ek sawaal, kai alag literatures. Har intent ki
            # apni query hoti hai, aur report mein saaf likha jaata hai kis
            # intent par search hui. Ye list deterministic hai.
            "search_intents": [{"key": i["key"], "label": i["label"],
                                "query": i["query"], "focus": i["focus"]}
                               for i in intents],
            "intent_note": dplan.intent_note(intents),
            "useful_source_types": list(dplan.profile.source_types),
            "skipped_connectors": sorted(set(dropped)),
            "routing_note": dplan.routing_note(dropped),
            # Specialist/archival/book queries remain separate from ordinary
            # web/paper queries so their evidence lanes can be audited.
            "specialist_profile_keys": list(specialist.get("profile_keys", [])),
            "specialist_expected_lanes": list(specialist.get("expected_lanes", [])),
            "official_archive_queries": list(
                specialist.get("official_archive_queries", [])),
            "book_queries": list(specialist.get("book_queries", [])),
            "legal_access_only": bool(specialist.get("legal_access_only", True)),
        }

    # ── poora plan ────────────────────────────────────────────────────────────
    def plan(self, question: str, config: DepthConfig) -> Dict:
        cls = self.classify(question)
        base_query = self.clean_query(question)
        specialist = build_specialist_plan(question, base_query)
        lens = self.lens_plan(question, base_query)
        return {
            **cls,
            "topic_terms": self.topic_terms(question),
            "sub_questions": self.sub_questions(question, cls),
            "queries": self.search_queries(question, cls, round_no=1),
            "connectors": self.connector_plan(cls, config, question),
            "depth": config.to_dict(),
            "specialist": specialist,
            # Open lens plan — closed keyword list ke bahar ka raasta. Ye search
            # plan hai, evidence NAHI (`verified: False`). Scoring anchor isi se
            # banta hai, aur wahi cross-lingual relevance ka fix hai.
            "lens": lens,
            "lens_scoring_query": lens_mod.scoring_query(lens),
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
