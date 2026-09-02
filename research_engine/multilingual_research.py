"""Honest multilingual search planning without pretending to translate books.

The public research indexes used by Infinity are mostly English-first.  Sending
Hindi/Hinglish (or another script) to every paper connector as-is often returns
zero results, but silently calling a glossary a "translation" is equally bad.

This module therefore does three bounded, deterministic things:

* preserves the user's original wording;
* makes controlled English search seeds only for terms whose mapping is known;
* records when full-text language review/translation is still required.

It never bypasses copyright/paywalls and it never claims that an arbitrary book
was translated or read.  A later model/human translation step may consume this
plan, but must keep the original passage beside the translation.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Sequence, Tuple

from .local_language import normalize


_SCRIPT_RANGES: Tuple[Tuple[str, int, int], ...] = (
    ("devanagari", 0x0900, 0x097F),
    ("bengali", 0x0980, 0x09FF),
    ("gurmukhi", 0x0A00, 0x0A7F),
    ("gujarati", 0x0A80, 0x0AFF),
    ("tamil", 0x0B80, 0x0BFF),
    ("telugu", 0x0C00, 0x0C7F),
    ("kannada", 0x0C80, 0x0CFF),
    ("malayalam", 0x0D00, 0x0D7F),
    ("arabic", 0x0600, 0x06FF),
    ("cyrillic", 0x0400, 0x04FF),
    ("cjk", 0x3400, 0x9FFF),
)

_ROMAN_HINDI = {
    "kya", "kaise", "kyun", "dimag", "dimaag", "mann", "man", "atma",
    "chetna", "avchetan", "vyavahar", "neend", "dhyan", "yaad", "tej",
    "batao", "samjhao", "karo", "chahiye", "sakta", "hai", "hain",
}

# Long phrases come first.  These mappings are search vocabulary, not a claim
# of complete or literary translation.
_PHRASE_GLOSSARY: Tuple[Tuple[str, str], ...] = (
    ("दिमाग तेज", "cognitive performance"),
    ("dimag tej", "cognitive performance"),
    ("dimaag tej", "cognitive performance"),
    ("अवचेतन मन", "subconscious mind"),
    ("subconscious mind", "subconscious mind"),
    ("अचेतन मन", "unconscious mind"),
    ("unconscious mind", "unconscious mind"),
    ("चेतन मन", "conscious mind"),
    ("conscious mind", "conscious mind"),
    ("मानव व्यवहार", "human behavior"),
    ("human behaviour", "human behavior"),
    ("छाया कार्य", "shadow work"),
    ("shadow work", "shadow work"),
    ("सात चक्र", "seven chakras"),
    ("7 चक्र", "seven chakras"),
    ("गुप्त समाज", "secret societies"),
    ("नई विश्व व्यवस्था", "new world order"),
    ("न्यू वर्ल्ड ऑर्डर", "new world order"),
    ("साजिश सिद्धांत", "conspiracy theories"),
    ("षड्यंत्र सिद्धांत", "conspiracy theories"),
    ("गुप्त विज्ञान", "occult history"),
    ("आध्यात्मिक आवृत्ति", "spiritual frequency claim"),
)

_TOKEN_GLOSSARY = {
    # mind / cognition
    "दिमाग": "brain", "मस्तिष्क": "brain", "dimag": "brain", "dimaag": "brain",
    "मन": "mind", "mann": "mind", "चेतना": "consciousness", "chetna": "consciousness",
    "अवचेतन": "subconscious", "avchetan": "subconscious",
    "अचेतन": "unconscious", "याददाश्त": "memory", "याद": "memory",
    "yaad": "memory", "ध्यान": "attention", "dhyan": "attention",
    "नींद": "sleep", "neend": "sleep", "व्यवहार": "behavior",
    "vyavahar": "behavior", "तेज": "performance", "tej": "performance",
    # traditions / philosophy / history
    "आध्यात्मिकता": "spirituality", "अध्यात्म": "spirituality",
    "रहस्यवाद": "mysticism", "गूढ़": "esotericism", "तंत्र": "tantra",
    "चक्र": "chakra", "चक्रों": "chakras", "आत्मा": "self",
    "atma": "self", "दिव्य": "divine", "चिंगारी": "spark",
    "दर्शन": "philosophy", "तत्वमीमांसा": "metaphysics",
    "व्यक्तित्वीकरण": "individuation", "छाया": "shadow",
    # records / claims
    "साजिश": "conspiracy", "षड्यंत्र": "conspiracy", "गुप्त": "secret",
    "समाज": "society", "दस्तावेज": "documents", "अवर्गीकृत": "declassified",
    "आवृत्ति": "frequency", "कंपन": "vibration", "हर्ट्ज": "hertz",
    # common instructions (kept out of the final seed)
    "पढ़ो": "", "पढ़ना": "", "बताओ": "", "खोजो": "", "research": "",
}

_WORD_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)
_MAX_QUERY_CHARS = 200


def _unique(values: Iterable[str], limit: int = 12) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


def _bounded_query(value: str) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= _MAX_QUERY_CHARS:
        return clean
    return clean[:_MAX_QUERY_CHARS].rsplit(" ", 1)[0].strip()


def scripts(text: str) -> List[str]:
    found: List[str] = []
    for char in str(text or ""):
        point = ord(char)
        for name, start, end in _SCRIPT_RANGES:
            if start <= point <= end and name not in found:
                found.append(name)
                break
    if re.search(r"[A-Za-z]", str(text or "")):
        found.insert(0, "latin")
    return found or ["unknown"]


def language_profile(text: str) -> Dict:
    normalized = normalize(text or "")
    found_scripts = scripts(normalized)
    roman_tokens = {token.lower() for token in re.findall(r"[A-Za-z]+", normalized)}
    roman_hindi_hits = sorted(roman_tokens & _ROMAN_HINDI)

    if "devanagari" in found_scripts:
        primary = "hindi_or_related_devanagari"
    elif found_scripts == ["latin"] and len(roman_hindi_hits) >= 2:
        primary = "roman_hindi_or_hinglish"
    elif found_scripts == ["latin"]:
        primary = "english_or_other_latin"
    elif len(found_scripts) > 1:
        primary = "mixed_or_multilingual"
    else:
        primary = "non_english_language_unresolved"

    return {
        "primary": primary,
        "scripts": found_scripts,
        "roman_hindi_signals": roman_hindi_hits[:10],
        "original_preserved": True,
    }


def controlled_english_terms(text: str) -> Tuple[List[str], List[str]]:
    """Return ``(known English terms, matched originals)`` for search only."""
    normalized = unicodedata.normalize("NFKC", normalize(text or "")).lower()
    terms: List[str] = []
    matched: List[str] = []
    consumed = normalized
    for original, english in _PHRASE_GLOSSARY:
        if original.casefold() not in normalized.casefold():
            continue
        matched.append(original)
        if english:
            terms.append(english)
        consumed = consumed.replace(original.casefold(), " ")
    for token in _WORD_RE.findall(consumed):
        mapped = _TOKEN_GLOSSARY.get(token.casefold())
        if mapped is None:
            continue
        matched.append(token)
        if mapped:
            terms.append(mapped)
    return _unique(terms), _unique(matched)


def build_multilingual_plan(
    question: str,
    base_query: str,
    english_anchors: Sequence[str] = (),
) -> Dict:
    profile = language_profile(question)
    mapped, matched = controlled_english_terms(question)
    anchors = _unique([*mapped, *english_anchors], limit=10)
    original = re.sub(r"\s+", " ", normalize(question or "")).strip()

    variants: List[Dict] = []
    if base_query:
        variants.append({
            "query": _bounded_query(base_query),
            "language": "original_or_normalized",
            "method": "planner_base",
        })
    if anchors:
        variants.append({
            "query": _bounded_query(" ".join(anchors)),
            "language": "english",
            "method": "controlled_glossary_and_profile_anchors",
        })

    if profile["primary"] in {"english_or_other_latin"} and not matched:
        status = "translation_not_needed_or_language_unresolved_latin"
    elif matched:
        status = "glossary_assisted_search_only"
    else:
        status = "translation_required_for_semantic_full_text_review"

    book_seeds = _unique([
        original if len(original) <= _MAX_QUERY_CHARS else "",
        " ".join(anchors) if anchors else base_query,
    ], limit=2)
    book_queries = [
        _bounded_query(f"{seed} public domain full text")
        for seed in book_seeds if seed
    ]

    return {
        **profile,
        "translation_status": status,
        "matched_glossary_terms": matched,
        "english_search_terms": anchors,
        "query_variants": variants,
        "book_queries": _unique(book_queries, limit=2),
        "full_text_language_policy": (
            "Original passage must be preserved beside any translation. "
            "Glossary-assisted search is not full-text translation; unread or "
            "untranslated text must be reported as such."
        ),
        "legal_access_only": True,
        "paywall_or_copyright_bypass": False,
    }

