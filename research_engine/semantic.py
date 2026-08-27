"""
Halka semantic similarity — bina model, bina network, bina nayi dependency.

Kyun: §5 kehta hai relevance sirf lexical overlap par nahi chal sakti. Poora
embedding model free tier par nahi aa sakta (RAM + download + latency), isliye
yahan teen sasti cheezein milti hain jo asli galtiyan pakadti hain:

  1. WEIGHTED OVERLAP — aam shabd ("study", "analysis", "temperature") ka weight
     kam, field-specific shabd ka weight zyada.
  2. BIGRAM MATCH — "room temperature" aur "temperature room" ek nahi. Phrase
     match hi asli farak dikhata hai (ferroelectricity vs superconductivity).
  3. CONCEPT EXPANSION — "Tc" ~ "critical temperature", "hydride" ~ "hydrogen":
     ek chhoti si concept table, taaki alag-alag shabd wali ek hi baat match ho.

Sab kuch deterministic hai, isliye test likhna aasan hai.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .domain import stem, stems, tokens

# Bahut aam academic/reporting shabd — inka match kuch sabit nahi karta
_LOW_VALUE = {
    "studi", "analysi", "analys", "research", "paper", "report", "review",
    "result", "method", "data", "datum", "new", "novel", "recent", "advance",
    "using", "use", "base", "high", "low", "effect", "system", "approach",
    "model", "case", "test", "measur", "observ", "propert", "applic",
    "temperature", "material", "structur", "process", "type", "level",
    "number", "estimat", "information", "kya", "hai", "aur", "ka", "ki",
    "ke", "par", "mein", "se", "ek", "the", "and", "for", "with", "from",
    "that", "this", "are", "was", "can", "has", "how", "what", "why",
}

# Ek hi baat ke alag naam. Sirf wahi jodi jo asli confusion kam karti hai.
_CONCEPTS: Dict[str, Tuple[str, ...]] = {
    "tc": ("critical temperature", "transition temperature"),
    "superconduct": ("zero resistance", "meissner", "cooper pair"),
    "hydride": ("hydrogen rich", "superhydride"),
    "cuprate": ("copper oxide",),
    "ambient": ("atmospheric pressure", "room temperature"),
    "machine learn": ("neural network", "deep learn"),
    "mortalit": ("death", "fatalit"),
    "epidemiolog": ("incidence", "prevalence"),
}


def _weight(token: str) -> float:
    if token in _LOW_VALUE:
        return 0.25
    if len(token) <= 3:
        return 0.4
    return 1.0


def bigrams(text: str) -> Set[str]:
    toks = [stem(t) for t in tokens(text)]
    return {f"{a} {b}" for a, b in zip(toks, toks[1:])}


def expand(bag: Set[str]) -> Set[str]:
    """Concept table se related shabd bhi bag mein daal do."""
    out = set(bag)
    for key, friends in _CONCEPTS.items():
        if key in bag:
            for f in friends:
                out.update(stem(p) for p in f.split())
    return out


def similarity(query: str, text: str) -> float:
    """
    0..1. Weighted token overlap (query ki taraf se normalised) + bigram bonus.
    Query ke shabd kitne cover hue — yahi asli sawaal hai, isliye denominator
    query ka weight hai, text ki lambai ka nahi (warna lamba abstract jeet jata).
    """
    return round(_with_script_bridge(query, text, _literal(query, text)), 4)


def _literal(query: str, text: str) -> float:
    """Wahi purana literal overlap — bridge ke bina (recursion-free)."""
    q_bag = {t for t in (stem(x) for x in tokens(query)) if t}
    if not q_bag:
        return 0.0
    t_bag = expand(stems(text))
    if not t_bag:
        return 0.0

    total = sum(_weight(t) for t in q_bag)
    hit = sum(_weight(t) for t in q_bag if t in t_bag)
    base = hit / total if total else 0.0

    q_bi, t_bi = bigrams(query), bigrams(text)
    if q_bi:
        shared = len(q_bi & t_bi)
        base = min(1.0, base + 0.15 * min(shared, 3) / 3.0 * (1.0 if shared else 0.0))
    return base


# Script-pul se mila match literal match se THODA kam pakka hai (transliteration
# me do alag shabd ek jaise skeleton de sakte hain), isliye usko poora weight
# nahi milta. Ye number kisi probability ka daawa nahi — sirf ek discount hai.
_BRIDGE_TRUST = 0.9
# Ek hi bridged shabd par poora score dena jhooth hoga, isliye cross-script pass
# ke liye kam se kam do English shabd chahiye.
_MIN_CROSS_TOKENS = 2


def _ascii_side(query: str) -> str:
    """Query ka wo hissa jo English/Latin me hai (anchor + loanword + naam)."""
    return " ".join(t for t in tokens(query) if t.isascii())


def _with_script_bridge(query: str, text: str, base: float) -> float:
    """Sawaal aur text ki script alag ho to `lang_bridge` ka mel bhi gino.

    **Zero-regression:** dono taraf pure ASCII ho to `needs_bridge` False deta
    hai aur `base` waisa ka waisa laut jaata hai — isliye English↔English ke
    naape hue benchmark hil hi nahi sakte. Bridge fail ho jaaye to bhi purana
    score lautta hai; scoring kisi naye module ke bharose nahi rukti.

    Do parat yahan judti hain:
      1. **skeleton mel** — transliterated shabd/naam (क्वांटम = quantum) apne
         aap match ho jaate hain.
      2. **cross-script coverage** — sawaal Devanagari/Bangla me ho aur source
         pura English ho, to sawaal ke us script wale shabd English text me
         mil hi nahi sakte. Unhe "miss" ginna source ko user ki bhasha ki saza
         dena hai. Isliye tab sirf sawaal ke English hisse (bridge/anchor se
         aaye shabd) ka coverage bhi naapa jaata hai — discount ke saath, aur
         kam se kam do shabd hone par.
    """
    try:
        from . import lang_bridge
        if not lang_bridge.needs_bridge(query, text):
            return base
        bridged, _hits = lang_bridge.bridged_overlap(query, text)
        best = max(base, bridged * _BRIDGE_TRUST)
        if str(text or "").isascii() and not str(query or "").isascii():
            latin = _ascii_side(query)
            if len(latin.split()) >= _MIN_CROSS_TOKENS:
                best = max(best, _literal(latin, text) * _BRIDGE_TRUST)
        return best
    except Exception:
        return base


def best_similarity(query: str, texts: Iterable[str]) -> float:
    return max((similarity(query, t) for t in texts if t), default=0.0)


def coverage(sub_questions: Sequence[str], text: str,
             floor: float = 0.25) -> Tuple[int, List[int]]:
    """
    Kitne sub-questions ko ye text sach mein touch karta hai.
    (§2 — "relevant only if its CONTENT helps answer at least one sub-question")
    """
    hits: List[int] = []
    for i, sq in enumerate(sub_questions):
        if similarity(sq, text) >= floor:
            hits.append(i)
    return len(hits), hits
