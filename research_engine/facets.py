"""FACETS — ek bade sawaal ke ALAG-ALAG research hisse, bina kisi topic list ke.

Naapi hui bimari (2026-08-24, intel ke Grand-Unified sawaal par):

  `relevance.topic_of()` poore sawaal se top-8 shabd nikaalta hai. 1617-token,
  16-section wale sawaal par wo aath shabd nikle:
      model, consciousness, reality, theories, behaviour, human, life, attention
  Yaani wahi shabd jo har section me hain — aur ek bhi wo shabd nahi jo kisi
  section ko ALAG karta hai (dopamine, individuation, Nash equilibrium, entropy,
  freemasonry, remote viewing, decoherence, hedonic...). Nateeja naapa gaya:
  15 me se 11 bilkul sahi sources ka relevance 0.000, aur report "RESEARCH
  INCOMPLETE" — jabki sources sahi the.

Asli baat: aisa sawaal EK topic nahi hota, wo 10-20 alag research sawaalon ka
jhund hota hai. Ek source poore jhund se match nahi karega — wo ek hisse ka
gehra jawab hoga. Isliye:

  * sawaal ko HISSON (segments) me toda jaata hai — line, numbered heading aur
    sentence ke aadhaar par (bhasha ka dhaancha, kisi topic ki list se nahi),
  * har hisse ke content shabd nikaalte hain,
  * har shabd ka "kitne hisson me aaya" (document frequency) gina jaata hai —
    yahi sawaal ke ANDAR ka IDF hai. Jo shabd har hisse me hai wo dhaancha hai
    ("model", "human"); jo ek-do hisse me hai wahi us hisse ki PEHCHAAN hai
    ("dopamine", "freemasonry"). Ye poori tarah general hai: koi field, koi
    kitaab, koi vyakti hard-code nahi hai, isliye jo topic intel ne kabhi
    bataya hi nahi wo bhi apna facet paa jaata hai.

Ye module sirf naap-tol hai — na koi claim banata hai, na kuch padhta hai, na
ek bhi Gemini call. Zero network, pure Python.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

from .domain import stem, tokens
from .lenses import (framework_phrases, hyphenated_compounds, is_stopword,
                     quoted_phrases, suffix_concepts)
from .lenses import TERM_CONNECTORS as _TERM_CONNECTORS
# "Aam shabd" ki paribhasha poore project me EK hi rahe — wahi set jise
# query_builder aadha wazan deta hai. (query_builder sirf local_language import
# karta hai, isliye ye import circular nahi hai.)
from .query_builder import is_generic_word as _is_generic

# Ek facet ke andar itne pehchaan-shabd. Ye ginti scoring ka denominator NAHI
# hai (relevance apna alag chhota denominator rakhti hai), isliye zyada shabd
# rakhne se ratio nahi girta — sirf us hisse ki pehchaan poori hoti hai.
MAX_TERMS_PER_FACET = 20
# Itne facet se aage jaana budget kharch karna hai; 16-section sawaal bhi isme
# aa jaata hai kyunki chhote hisse merge ho jaate hain.
MAX_FACETS = 24
# Ek block itne content shabd se bada ho jaaye to use sentence par aage toda
# jaata hai — warna ek hi facet me do alag section ghus jaate hain.
MAX_TOKENS_PER_BLOCK = 90
# Toda hua tukda kam se kam itna bada ho, warna aage wale se jud jaaye.
MIN_TOKENS_PER_BLOCK = 22
# Ek hisse me itne content shabd hone chahiye tab wo apna facet banta hai.
MIN_TERMS_PER_FACET = 3
# Facet banane layak sawaal — isse chhote sawaal ka ek hi facet hota hai (khud
# sawaal), isliye purana behaviour bilkul waisa hi rehta hai.
MIN_QUESTION_TOKENS = 60
# Kitne hisson me aane par shabd "dhaancha" maan liya jaaye (pehchaan nahi).
# Anupaat me — 4 hisse wale sawaal aur 40 hisse wale sawaal ka paimana ek nahi
# ho sakta.
STRUCTURAL_DF_RATIO = 0.34

_LINE_SPLIT = re.compile(r"(?:\r?\n)+")
# "7. Power, Geopolitics..." / "B) Moderate evidence" — naya section shuru.
_HEADING = re.compile(r"^\s*(?:\d{1,3}|[A-Za-z])[.)]\s+\S")
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!;])\s+")


def _content_count(text: str) -> int:
    return sum(1 for t in tokens(text) if not is_stopword(t))


def _blocks(text: str) -> List[str]:
    """Sawaal ke BLOCK — nayi line + numbered heading ke aadhaar par.

    Do dhaanche milte hain aur dono sambhalne hote hain:

      * heading-wala sawaal ("1. Consciousness..." / "2. Brain...") — heading ke
        neeche ki saari lines USI section ki hain, isliye wo ek hi block me
        rehti hain aur us section ke pehchaan-shabd ek saath aate hain,
      * bina-heading wala sawaal (har section apni ek lambi line me) — wahan
        nayi line hi seema hai, isliye har line apna block banti hai.

    Faisla sirf dhaanche par hai: koi topic, kitaab, field ya vyakti ka naam
    kahin nahi, isliye jo topic intel ne naam se bataya hi nahi wo bhi apna
    block paata hai.
    """
    out: List[str] = []
    sticky = False
    for line in _LINE_SPLIT.split(text or ""):
        piece = line.strip(" \t-•*")
        if not piece:
            continue
        if _HEADING.match(piece):
            out.append(piece)
            sticky = True                     # heading ke neeche ka sab isi ka
        elif sticky and out:
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def _split_long(block: str, target: int = MAX_TOKENS_PER_BLOCK) -> List[str]:
    """Bahut bade block ko vaakya par toda jaaye, warna do section ek facet me."""
    if _content_count(block) <= target:
        return [block]
    chunks: List[str] = []
    current: List[str] = []
    count = 0
    for sentence in _SENTENCE_SPLIT.split(block):
        piece = sentence.strip()
        if not piece:
            continue
        current.append(piece)
        count += _content_count(piece)
        if count >= target:
            chunks.append(" ".join(current))
            current, count = [], 0
    if current:
        tail = " ".join(current)
        if chunks and count < MIN_TERMS_PER_FACET:
            chunks[-1] = f"{chunks[-1]} {tail}"
        else:
            chunks.append(tail)
    return chunks


def segments(question: str) -> List[str]:
    """Sawaal ke hisse — bhasha ke dhaanche se, topic se nahi."""
    blocks = _blocks(question or "")
    # Jab sawaal me koi seema hi nahi mili (ek hi paragraph, ek hi line), tab
    # vaakya hi seema hai — isliye chhota target. Jahan heading/line ne seema
    # de di hai, wahan poora section ek facet rehta hai.
    target = MAX_TOKENS_PER_BLOCK if len(blocks) > 1 else MIN_TOKENS_PER_BLOCK
    out: List[str] = []
    for block in blocks:
        for part in _split_long(block, target):
            if _content_count(part) < MIN_TERMS_PER_FACET and out:
                out[-1] = f"{out[-1]} {part}"   # chhota tukda pichhle se jud jaaye
                continue
            out.append(part)
    return out


@dataclass(frozen=True)
class Facet:
    """Sawaal ka ek hissa: uske pehchaan-shabd aur ek ready search query."""
    key: str
    label: str
    terms: Tuple[str, ...]
    phrases: Tuple[str, ...] = ()
    segment: str = ""
    weight: float = 1.0
    # Har term kitne hisson me aaya (terms ke usi kram me). Isse scoring wala
    # module bina dobara ginti kiye jaan sakta hai kaun shabd kitna khaas hai.
    term_df: Tuple[int, ...] = ()
    # STRONG term = akele match par bhi bharosa kiya ja sakta hai: sirf isi ek
    # hisse me aaya (df 1), lamba (specialist shabdkosh), aur morphology se
    # concept-jaisa. "hermeticism", "neuroplasticity", "psycho-cybernetics"
    # aise hain; "vibration", "based", "interpretation" jaan-boojh kar NAHI —
    # wo aam shabd hain jo bilkul alag field ke source me bhi aa jaate hain.
    strong: Tuple[str, ...] = ()

    def df_of(self, term: str) -> int:
        for known, value in zip(self.terms, self.term_df):
            if known == term:
                return max(1, value)
        return 1

    def query(self, limit: int = 5) -> str:
        """Is hisse ki search query — sirf VISHAY ke shabd, nirdesh/nishedh nahi.

        Naapi hui galti: sawaal ki nishedh-line ("do not treat 'CIA investigated
        X' as 'CIA proved X'.") se ek phrase nikal kar query ban gaya tha —
        "CIA investigated X CIA proved X. altered intelligence investigation".
        Aisi query se search engine ko koi topic nahi milta. Isliye ab do parat:
          1. phrase tab hi lega jab wo NAAM jaisa ho (`is_query_safe_phrase`),
          2. term me research-PROCESS ke shabd (investigation, evidence...) aur
             aam shabd baad me aate hain — topic ke shabd pehle.
        """
        parts: List[str] = []
        used: set = set()
        for phrase in self.phrases[:2]:
            words = [w.casefold() for w in phrase.split()]
            if len(words) < 2 or not is_query_safe_phrase(phrase):
                continue
            # Do phrase ka matlab ek hi ho ("secret societies power networks" +
            # "secret societies elite networks") to query me dono na jaayein.
            if used & set(words):
                continue
            used |= set(words)
            parts.append(phrase)

        def _rank(term: str) -> Tuple[int, int]:
            # 0 = topic ka shabd, 1 = process/aam shabd (query me baad me).
            soft = 1 if (is_discourse_word(term) or _is_generic(term)) else 0
            return (soft, self.terms.index(term))

        for term in sorted(self.terms, key=_rank):
            if len(parts) >= limit:
                break
            if not any(term in p.split() for p in parts):
                parts.append(term)
        return " ".join(parts[:limit])

    def to_dict(self) -> Dict:
        return {"key": self.key, "label": self.label, "terms": list(self.terms),
                "phrases": list(self.phrases), "query": self.query(),
                "term_df": list(self.term_df), "strong": list(self.strong),
                "weight": round(self.weight, 3)}


# Research-prompt ka DHAANCHA — nirdesh dene wale shabd, kisi topic ka naam
# nahi. Inhe hataana zaroori hai kyunki ye har sawaal me aate hain aur facet ki
# query ko "examine whether these principles" jaisa kachra bana dete hain.
# (Topic/kitaab/vyakti ka naam is set me kabhi nahi aayega — wahi intel ki
# shart hai: naam na diya ho to bhi app khud soche.)
_SCAFFOLD = frozenset({
    "your", "yours", "must", "should", "shall", "could", "might", "would",
    "following", "these", "those", "each", "every", "other", "others",
    "another", "above", "below", "itself", "themselves", "everything",
    "anything", "something", "nothing", "someone", "whether", "where",
    "while", "within", "without", "either", "neither", "cannot", "using",
    "used", "both", "same", "different", "possible", "important", "relevant",
    "critically", "clearly", "example", "examples", "section", "sections",
    "part", "parts", "point", "points", "list", "lists", "ask", "asks",
    "examine", "analyze", "analyse", "determine", "compare", "compares",
    "construct", "constructs", "integrate", "integrates", "apply", "applies",
    "distinguish", "identify", "develop", "describe", "consider", "suppose",
    "produce", "present", "explain", "explains", "solve", "solves",
    "incorporate", "incorporates", "assume", "assumes", "then", "finally",
    "first", "second", "third", "next", "also", "task", "tasks",
    "including", "include", "includes", "concerning", "regarding", "given",
    "various", "particular", "certain", "specific", "overall", "additionally",
    "moreover", "however", "therefore", "instead", "rather",
})
# "-ly" wala shabd (adverb) topic nahi hota: "systematically", "automatically".
_ADVERB_MIN = 7
# tf ki chhat — 3 baar aur 9 baar aaye shabd me farq karne ki zaroorat nahi,
# aur bina chhat ke ek dohraya gaya aam shabd poora facet khaa sakta hai.
_TF_CAP = 3
# Itna lamba shabd hi "specialist shabdkosh" maana jaata hai. Ye Zipf ka seedha
# istemaal hai (lamba shabd aam bhasha me durlabh hota hai) — koi topic list
# nahi, isliye jo naam intel ne diya hi nahi wo bhi strong ban sakta hai.
STRONG_TERM_MIN_LEN = 11
# STRONG shabd sawaal ke itne hisson se zyada me nahi hona chahiye. Naapa gaya:
# "information" 7 hisson me hai aur "intelligence" 4 me — ye is sawaal ke aam
# shabd hain, kisi ek hisse ki pehchaan nahi; unka akela match kaafi maan lena
# bilkul alag field ke paper ko andar le aata. "neuroplasticity" (3),
# "individuation" (2), "hermeticism" (1) isi paimane se andar rehte hain.
STRONG_MAX_DF = 3


def _is_scaffold(word: str) -> bool:
    low = word.casefold()
    if low in _SCAFFOLD:
        return True
    return len(low) >= _ADVERB_MIN and low.endswith("ly")


# Har research paper ke abstract me aane wale DISCOURSE shabd. Ye topic ke shabd
# nahi hain, kisi bhi field ki baat karne ke shabd hain. Inhe facet ke terms se
# nikaalna galat hoga (sawaal me ye asli baat ka hissa bhi hote hain, aur score
# me inka thoda yogdaan theek hai), par inka akela match kisi source ko "is
# hisse ka jawab" keh dene ka saboot NAHI hai.
#
# Naapa gaya: "The Corpus Hermeticum" aur gearbox-vibration ka paper dono f15 se
# ['based', 'interpretation', 'vibration'] par match ho rahe the — kyunki mere
# harness ke boilerplate "should not be interpreted" me 'interpretation' ka root
# mil jaata tha. Asli snippets me bhi yahi hota hai.
_DISCOURSE = frozenset({
    "interpretation", "interpretations", "evidence", "theory", "theories",
    "framework", "frameworks", "analysis", "analyses", "research", "study",
    "studies", "approach", "approaches", "context", "contexts", "factor",
    "factors", "effect", "effects", "result", "results", "finding", "findings",
    "implication", "implications", "conclusion", "conclusions", "question",
    "questions", "claim", "claims", "concept", "concepts", "idea", "ideas",
    "principle", "principles", "method", "methods", "methodology",
    "literature", "review", "data", "paper", "papers", "report", "reports",
    "argument", "arguments", "discussion", "limitation", "limitations",
    "outcome", "outcomes", "measure", "measures", "measured", "sample",
    "detail", "details",
    # Research ki PROCESS ke shabd — ye kaam ke naam hain, vishay ke nahi. Inka
    # akela match har paper me lag jaata hai ("we investigated...", "validation
    # study", "replication attempt"), isliye ye bhi saboot nahi hain.
    "investigate", "investigates", "investigated", "investigation",
    "investigations", "validation", "validate", "validated", "replication",
    "replicate", "replicated", "verification", "observation", "observations",
    "documentation", "speculation", "speculative", "inference", "inferences",
    "information",
})


def is_discourse_word(word: str) -> bool:
    """Kya ye shabd har field ke abstract me aata hai (topic ka shabd nahi)?"""
    return str(word or "").strip().casefold() in _DISCOURSE


def _concept_boost(text: str) -> Dict[str, int]:
    """Kaun shabd 'concept jaisa' hai — morphology aur bade akshar se, list se nahi.

    2 = hyphen-compound / concept-suffix / quoted / framework phrase ka hissa
        ("dopamine-driven", "hermeticism", "Nash equilibrium"), YA sawaal me
        bade akshar se likha gaya naam ("Freemasonry", "Gateway", "Jung").
        Naam ko kam wazan dena naapi hui galti thi: har `-ation` wale shabd ke
        peechhe chala jaata tha aur cut me kat jaata tha, isliye "freemasonry"
        apne hi section ke facet me nahi bacha aur Freemasonry ka documented
        history wala paper 0.087 par gir gaya.
    0 = baaki.
    """
    boost: Dict[str, int] = {}
    for phrase in (*quoted_phrases(text), *hyphenated_compounds(text),
                   *framework_phrases(text), *suffix_concepts(text)):
        for word in tokens(str(phrase or "")):
            if len(word) >= 4:
                boost[word] = 2
            for part in word.split("-"):     # "dopamine-driven" → dopamine, driven
                if len(part) >= 4:
                    boost[part] = 2
    for match in re.findall(r"\b[A-Z][A-Za-z]{3,}\b", text or ""):
        word = match.casefold()
        if boost.get(word, 0) < 2:
            boost[word] = 2
    return boost


def _content_terms(text: str) -> List[str]:
    return list(_term_counts(text))


def _term_counts(text: str) -> Dict[str, int]:
    """Is hisse ke content shabd + unki ginti (tf).

    tf isliye chahiye: jo shabd is hisse me BAAR-BAAR aaya hai wahi is hisse ka
    asli vishay hai. Sirf "kam df" par bharosa karna naapa hua galti thi —
    "dopamine" teen section me aata hai kyunki wo sawaal ka kendra hai, aur usi
    wajah se wo ek-baar-aaye shabdon se peechhe chala jaata tha.
    """
    seen: Dict[str, int] = {}
    for token in tokens(text):
        word = token.strip("-")
        if len(word) < 4 or is_stopword(word) or _is_scaffold(word):
            continue
        seen[word] = seen.get(word, 0) + 1
        # "dopamine-driven" ka asli concept "dopamine" hai, aur source usme
        # hyphen ke bina likha hota hai ("phasic dopamine encoded reward...").
        # Isliye compound ke hisse bhi apne term bante hain — inka df alag gina
        # jaata hai, isliye jo hissa har jagah aata hai wo khud dhaancha ban kar
        # bahar ho jaata hai.
        if "-" in word:
            for part in word.split("-"):
                if len(part) >= 4 and not is_stopword(part) and not _is_scaffold(part):
                    seen[part] = seen.get(part, 0) + 1
    return seen


# Query me "X", "Y", "A/B" jaise placeholder aksar nishedh-line se aate hain
# ("do not treat 'CIA investigated X' as 'CIA proved X'"). Do akshar se chhota
# token kisi topic ka naam nahi hota.
_PHRASE_MIN_WORD = 3
_PHRASE_MAX_WORDS = 6
_SENTENCE_MARKS = ".;:!?"


def is_query_safe_phrase(phrase: str) -> bool:
    """Kya ye phrase SEARCH QUERY me daalne layak hai (naam jaisa, vaakya nahi)?

    Poori tarah dhaanche par faisla — kisi topic/nishedh ki list nahi:
      * vaakya-chinh (.;:!?) ho to wo vaakya hai, naam nahi,
      * 6 se zyada shabd = vaakya,
      * EK-AKSHAR ka token placeholder hai ("X", "Y") — sirf asli ek-akshar
        connector ("a") chhoot paata hai. Ye check `is_stopword` se pehle chalta
        hai kyunki lenses ka stopword set placeholder "x"/"y" ko bhi stopword
        maanta hai, aur usi wajah se "CIA proved X" query me pahunch gaya tha
        (naapa gaya: facet f5 ki query "CIA proved X standard treat ..." thi,
        jabki is module ka wada tha ki aisa kachra query nahi banega),
      * chhota jodne wala shabd ("of", "and", "in") chalega,
      * nirdesh ka shabd ("your", "following") ho to ye sawaal ka aadesh hai,
        topic ka naam nahi,
      * kam se kam ek shabd topic-jaisa ho (process/aam shabd nahi).
    """
    clean = re.sub(r"\s+", " ", str(phrase or "")).strip()
    if not clean or any(mark in clean for mark in _SENTENCE_MARKS):
        return False
    words = [w for w in (t.strip("-'\"()[]") for t in clean.split()) if w]
    if not words or len(words) > _PHRASE_MAX_WORDS:
        return False
    for word in words:
        if _is_scaffold(word):
            return False
        if len(word) < 2 and word.casefold() not in _TERM_CONNECTORS:
            return False      # X / Y jaisa placeholder
        if len(word) < _PHRASE_MIN_WORD and not is_stopword(word):
            return False      # baaki chhote token bhi naam ke hisse nahi hote
    return any(len(w) >= 4 and not is_stopword(w) and not is_discourse_word(w)
               and not _is_scaffold(w) and not _is_generic(w) for w in words)


def _phrases_in(text: str) -> List[str]:
    out: List[str] = []
    for phrase in (*quoted_phrases(text), *hyphenated_compounds(text),
                   *framework_phrases(text), *suffix_concepts(text)):
        clean = re.sub(r"\s+", " ", str(phrase or "")).strip()
        if clean and clean.casefold() not in {p.casefold() for p in out}:
            out.append(clean)
    return out[:4]


@lru_cache(maxsize=64)
def build(question: str) -> Tuple[Facet, ...]:
    """Sawaal ke facets — deterministic aur cached."""
    text = question or ""
    if len(tokens(text)) < MIN_QUESTION_TOKENS:
        return ()

    parts = segments(text)
    if len(parts) < 2:
        return ()

    per_part = [(_term_counts(part), part) for part in parts]
    df: Dict[str, int] = {}
    for counts, _ in per_part:
        for term in set(stem(t) for t in counts):
            df[term] = df.get(term, 0) + 1

    total = max(1, len(per_part))
    structural_cut = max(2, int(total * STRUCTURAL_DF_RATIO))

    facets: List[Facet] = []
    for index, (counts, part) in enumerate(per_part):
        terms = list(counts)
        boost = _concept_boost(part)
        # Pehla chhanni: jo shabd sawaal ke bahut hisson me hai wo DHAANCHA hai,
        # pehchaan nahi — usse pehle hi nikaal do.
        distinct = [t for t in terms if df.get(stem(t), 1) <= structural_cut]
        # Phir kram — teen paimane, isi kram me:
        #   1. morphology (hyphen-compound / concept-suffix / quoted / bada
        #      akshar) — ye shabd "concept jaisa" hai,
        #   2. is hisse me kitni BAAR aaya (tf) — jo hissa apne andar ek shabd
        #      dohra raha hai, wahi us hisse ka asli vishay hai,
        #   3. tab df (kam = zyada pehchaan-wala), tab lambai.
        # Sirf df par kram rakhna naapa hua galti thi: "dopamine" teen section
        # me aata hai kyunki wo sawaal ka KENDRA hai, aur usi wajah se wo
        # ek-baar-aaye "gratification" se peechhe chala jaata tha aur 14 ki cut
        # me kat jaata tha — jabki source me wahi shabd likha hota hai.
        ranked = sorted(
            distinct or terms,
            key=lambda t: (-boost.get(t, 0), -min(counts.get(t, 1), _TF_CAP),
                           df.get(stem(t), 1), -len(t)),
        )
        chosen = ranked[:MAX_TERMS_PER_FACET]
        if len(chosen) < MIN_TERMS_PER_FACET:
            continue
        rarity = sum(1.0 / (1 + df.get(stem(t), 1)) for t in chosen)
        phrases = tuple(_phrases_in(part))
        label = (phrases[0] if phrases else " ".join(chosen[:3]))
        # STRONG = specialist shabdkosh ka shabd: pehchaan-wala (structural cut
        # ke andar), lamba (11+ akshar — Zipf: lamba shabd aam bhasha me durlabh
        # hota hai), concept-jaisa, aur discourse shabd nahi. Chaar shart ek
        # saath, isliye "neuroplasticity"/"individuation"/"hermeticism" strong
        # hain par "vibration" (9 akshar) aur "interpretation" (discourse) nahi —
        # yahi wo do shabd the jinki wajah se gearbox-vibration ka paper is
        # sawaal me 0.355 pa gaya tha.
        strong = tuple(t for t in chosen
                       if len(t) >= STRONG_TERM_MIN_LEN
                       and boost.get(t, 0) >= 2
                       and not is_discourse_word(t)
                       and df.get(stem(t), 1) <= min(STRONG_MAX_DF, structural_cut))
        facets.append(Facet(
            key=f"f{index + 1}",
            label=label[:80],
            terms=tuple(chosen),
            phrases=phrases,
            segment=part[:400],
            weight=round(min(1.0, rarity / max(1.0, len(chosen) * 0.5)), 3),
            term_df=tuple(max(1, df.get(stem(t), 1)) for t in chosen),
            strong=strong,
        ))

    facets.sort(key=lambda f: f.weight, reverse=True)
    return tuple(facets[:MAX_FACETS])


def facet_terms(question: str) -> List[List[str]]:
    return [list(f.terms) for f in build(question)]


def facet_queries(question: str, limit: int = 8, terms: int = 5) -> List[str]:
    """Har facet ki apni search query — yahi 'har hisse par alag research'."""
    out: List[str] = []
    seen = set()
    for facet in build(question):
        query = facet.query(limit=terms)
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= limit:
            break
    return out


def distinctive_terms(question: str, limit: int = 24) -> List[str]:
    """Poore sawaal ke sabse pehchaan-wale shabd (har facet se bari-bari)."""
    facets = build(question)
    out: List[str] = []
    seen = set()
    for depth in range(MAX_TERMS_PER_FACET):
        for facet in facets:
            if depth >= len(facet.terms):
                continue
            term = facet.terms[depth]
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(term)
            if len(out) >= limit:
                return out
    return out


def summary(question: str) -> Dict:
    """Report/audit ke liye — kya-kya hissa mana gaya (evidence nahi, plan hai)."""
    facets = build(question)
    return {
        "count": len(facets),
        "method": "deterministic_segment_idf",
        "model_used": False,
        "facets": [f.to_dict() for f in facets],
        "note": ("sawaal ke hisse uske apne dhaanche se nikle hain; ye search "
                 "plan hai, koi evidence ya claim nahi"),
    }
