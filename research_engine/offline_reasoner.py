"""Deterministic last-resort evidence reasoner (₹0, no model, no network).

Cloud/provider redundancy greatly reduces quota failures, but no collection of
free hosted APIs can guarantee that at least one will always be available. The
final safety net therefore lives inside the app itself: when Gemini + every
configured free provider + optional local Ollama produce no text, this module
still turns already-retrieved evidence into a useful, cited, human-readable
answer instead of an exception or blank template.

This is deliberately conservative. It does NOT invent mechanisms, general
knowledge, hypotheses or consensus. It ranks source text against the question,
uses only short source fragments, labels them honestly, and says what could not
be established. A local LLM remains the stronger no-quota reasoning fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from .models import EvidencePack


_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are", "was",
    "were", "have", "has", "had", "what", "why", "how", "can", "could", "would",
    "should", "about", "does", "which", "when", "where", "who", "its", "their",
    "kya", "hai", "hain", "ka", "ke", "ki", "ko", "me", "mein", "se", "par",
    "aur", "ye", "yah", "wo", "woh", "kaise", "kyun", "batao", "bataiye",
    "क्या", "है", "हैं", "का", "के", "की", "को", "में", "से", "पर", "और",
    "यह", "वह", "कैसे", "क्यों", "बताओ",
}

_INJECTION_MARKERS = (
    "ignore previous", "ignore all previous", "system prompt", "developer message",
    "you are chatgpt", "follow these instructions", "do not answer the user",
    "reveal your prompt", "jailbreak",
)

_MECHANISM_HINTS = (
    "because", "due to", "caused by", "mechanism", "associated with", "mediated by",
    "leads to", "results from", "therefore", "because of", "wajah", "karan", "कारण",
)


@dataclass(frozen=True)
class EvidenceSentence:
    source_id: str
    text: str
    score: float
    read_level: str
    quality: float
    relevance: float
    peer_reviewed: bool


def _tokens(text: str) -> List[str]:
    raw = re.findall(r"[^\W_]+", str(text or "").lower(), flags=re.UNICODE)
    out: List[str] = []
    for token in raw:
        if len(token) < 3 or token in _STOP or token in out:
            continue
        out.append(token)
    return out


def _sentences(text: str) -> Iterable[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    rows = re.split(r"(?<=[.!?।])\s+|\s*[•▪]\s*", clean)
    return [row.strip(" -\t") for row in rows if len(row.strip()) >= 35]


def _safe_fragment(text: str, max_words: int = 22, max_chars: int = 220) -> str:
    """Short source fragment: enough context, never a long copied passage."""
    words = str(text or "").split()
    clipped = " ".join(words[:max_words])
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars].rsplit(" ", 1)[0]
    if len(words) > max_words or len(str(text or "")) > len(clipped):
        clipped = clipped.rstrip(" ,;:") + "…"
    return clipped


def _unsafe_source_text(text: str) -> bool:
    low = str(text or "").lower()
    return any(marker in low for marker in _INJECTION_MARKERS)


def _source_allowed(source) -> bool:
    """Fail closed on sources already rejected or carrying a retraction signal."""
    if source is None:
        return False
    if getattr(source, "retracted", None) is True:
        return False
    if str(getattr(source, "rejected_reason", "") or "").strip():
        return False
    return True


def _reading_level(source) -> str:
    try:
        return str(source.reading_level() or "metadata")
    except Exception:
        return str(getattr(source, "read_level", "") or "metadata")


def _score(sentence: str, source, question_terms: Sequence[str]) -> float:
    low = sentence.lower()
    overlap = sum(1 for term in question_terms if term in low)
    coverage = overlap / max(1, min(8, len(question_terms)))
    rel = max(0.0, min(1.0, float(getattr(source, "relevance_score", 0.0) or 0.0)))
    quality = max(0.0, min(1.0, float(getattr(source, "quality_score", 0.0) or 0.0)))
    level = _reading_level(source)
    depth = {"full_text": 0.24, "abstract": 0.16, "snippet": 0.08}.get(level, 0.0)
    peer = 0.08 if getattr(source, "peer_reviewed", None) is True else 0.0
    penalty = 0.0
    if question_terms and overlap == 0 and rel < 0.45:
        penalty += 0.45
    return round(coverage * 1.7 + rel * 0.65 + quality * 0.35 + depth + peer - penalty, 6)


def _near_duplicate(a: str, b: str) -> bool:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return a[:90].lower() == b[:90].lower()
    return len(ta & tb) / max(1, len(ta | tb)) >= 0.72


class OfflineEvidenceReasoner:
    """Build a useful answer from retrieved evidence without any LLM call."""

    def __init__(self, max_findings: int = 5):
        self.max_findings = max(2, min(8, int(max_findings)))

    def _candidates(self, question: str, pack: EvidencePack) -> List[EvidenceSentence]:
        qterms = list(getattr(pack, "topic_terms", []) or []) or _tokens(question)[:10]
        source_map: Dict[str, object] = {
            str(getattr(s, "source_id", "")): s for s in (pack.sources or [])
            if str(getattr(s, "source_id", "")).strip()
        }
        texts: List[tuple[str, str]] = []

        # Processed passages are preferred because they are the actual context
        # used by evidence checks. Source snippets fill gaps when no passage exists.
        for passage in list(getattr(pack, "passages", []) or []):
            sid = str(getattr(passage, "source_id", "") or "")
            text = str(getattr(passage, "text", "") or "")
            source = source_map.get(sid)
            if _source_allowed(source) and text:
                texts.append((sid, text))
        passage_sources = {sid for sid, _ in texts}
        for source in pack.sources or []:
            sid = str(getattr(source, "source_id", "") or "")
            if not sid or sid in passage_sources or not _source_allowed(source):
                continue
            text = str(getattr(source, "snippet", "") or "")
            if text:
                texts.append((sid, text))

        rows: List[EvidenceSentence] = []
        for sid, text in texts:
            source = source_map.get(sid)
            if not _source_allowed(source) or _unsafe_source_text(text):
                continue
            level = _reading_level(source)
            if level == "metadata":
                continue
            for sentence in _sentences(text):
                if _unsafe_source_text(sentence):
                    continue
                score = _score(sentence, source, qterms)
                if score <= 0:
                    continue
                rows.append(EvidenceSentence(
                    source_id=sid,
                    text=sentence,
                    score=score,
                    read_level=level,
                    quality=float(getattr(source, "quality_score", 0.0) or 0.0),
                    relevance=float(getattr(source, "relevance_score", 0.0) or 0.0),
                    peer_reviewed=getattr(source, "peer_reviewed", None) is True,
                ))
        rows.sort(key=lambda row: (-row.score, row.source_id, row.text.lower()))
        return rows

    def _select(self, candidates: Sequence[EvidenceSentence]) -> List[EvidenceSentence]:
        picked: List[EvidenceSentence] = []
        per_source: Dict[str, int] = {}
        for row in candidates:
            if per_source.get(row.source_id, 0) >= 2:
                continue
            if any(_near_duplicate(row.text, old.text) for old in picked):
                continue
            picked.append(row)
            per_source[row.source_id] = per_source.get(row.source_id, 0) + 1
            if len(picked) >= self.max_findings:
                break
        return picked

    @staticmethod
    def _label(row: EvidenceSentence) -> str:
        # Even a full-text extract is called EVIDENCE, not ESTABLISHED. The
        # downstream A-E verifier decides whether stronger wording is earned.
        return "[EVIDENCE]" if row.read_level == "full_text" else "[SOURCE-REPORTED]"

    @staticmethod
    def _strength(pack: EvidencePack) -> str:
        allowed = [s for s in (pack.sources or []) if _source_allowed(s)]
        total = len(allowed)
        independent = len({getattr(s, "independence_key", "") for s in allowed})
        full = sum(1 for s in allowed if _reading_level(s) == "full_text")
        abstract = sum(1 for s in allowed if _reading_level(s) == "abstract")
        peer = sum(1 for s in allowed if getattr(s, "peer_reviewed", None) is True)
        return (
            f"Is fallback ke paas {total} usable retrieved source the; {independent} independent origin, "
            f"{full}/{max(1, total)} full-text level, {abstract}/{max(1, total)} abstract level aur "
            f"{peer}/{max(1, total)} peer-reviewed signal wale the. Ye ginti evidence ki depth "
            "batati hai; apne aap kisi claim ko proven nahi banati."
        )

    @staticmethod
    def _unknowns(pack: EvidencePack) -> List[str]:
        allowed = [s for s in (pack.sources or []) if _source_allowed(s)]
        total = len(allowed)
        full = sum(1 for s in allowed if _reading_level(s) == "full_text")
        independent = len({getattr(s, "independence_key", "") for s in allowed})
        rows: List[str] = []
        if total == 0:
            return ["Retrieved sources usable evidence gate pass nahi kar sake."]
        if full == 0:
            rows.append("Kisi usable source ka full text available nahi tha, isliye method/result context kaafi had tak unknown hai.")
        elif full < max(1, total // 3):
            rows.append(f"Sirf {full}/{total} usable sources full-text level tak padhe gaye; baaki claims ki depth limited hai.")
        if independent < 2:
            rows.append("Independent usable sources bahut kam hain, isliye ek source ki galti ko cross-check karna mushkil hai.")
        if not rows:
            rows.append("Model ke bina naya causal inference ya hypothesis invent nahi ki gayi; sirf retrieved evidence ka safe synthesis diya gaya hai.")
        return rows

    def synthesize(self, question: str, pack: EvidencePack) -> str:
        if not pack.sources:
            return (
                "## Seedha jawab\n"
                "Is sawal ke liye usable retrieved evidence nahi mila. Bina source aur bina "
                "available reasoning model ke guess dena galat hoga.\n\n"
                "## Abhi bhi kya pata nahi\n"
                "Is run se factual answer establish nahi hua. Agla safe step relevant public "
                "sources dhoondhna ya local reasoning model available karna hai.\n\n"
                "## Final conclusion\n"
                "[UNKNOWN] Is run ke data se pakka nateeja nahi nikala ja sakta."
            )

        candidates = self._candidates(question, pack)
        findings = self._select(candidates)
        if not findings:
            return (
                "## Seedha jawab\n"
                "Sources retrieve hue, lekin unke usable available text se sawal ka direct, "
                "safe answer extract nahi ho saka. Isliye guess nahi diya gaya.\n\n"
                "## Evidence kitna majboot hai\n"
                + self._strength(pack)
                + "\n\n## Final conclusion\n[UNKNOWN] Available source text direct conclusion ke liye enough nahi tha."
            )

        best = findings[0]
        intro = _safe_fragment(best.text)
        finding_lines = [
            f"- {self._label(row)} {_safe_fragment(row.text)} [{row.source_id}]"
            for row in findings
        ]

        mechanism = next(
            (row for row in findings if any(hint in row.text.lower() for hint in _MECHANISM_HINTS)),
            None,
        )
        if mechanism:
            mechanism_text = (
                f"{self._label(mechanism)} Source text mein mechanism/wajah se judi ye baat "
                f"mili: {_safe_fragment(mechanism.text)} [{mechanism.source_id}]"
            )
        else:
            mechanism_text = (
                "Available text mein mechanism ko safely explain karne layak direct evidence "
                "nahi mila; isliye causal story guess nahi ki gayi."
            )

        unknown_lines = "\n".join(f"- {row}" for row in self._unknowns(pack))
        return (
            "## Seedha jawab\n"
            f"Retrieved evidence mein sawal se sabse seedhi judi baat ye mili: "
            f"{intro} [{best.source_id}] Is fallback ne nayi facts invent nahi ki; "
            "neeche har factual line retrieved source se judi hai.\n\n"
            "## Research se kya pata chala\n"
            + "\n".join(finding_lines)
            + "\n\n## Ye kyun hota hai\n"
            + mechanism_text
            + "\n\n## Evidence kitna majboot hai\n"
            + self._strength(pack)
            + "\n\n## Kya evidence ke khilaf jaata hai\n"
            "Retrieved text se reliable counter-evidence ko model ke bina alag identify "
            "karna safe nahi tha; isliye koi fake disagreement nahi banaya gaya.\n\n"
            "## Abhi bhi kya pata nahi\n"
            + unknown_lines
            + "\n\n## Final conclusion\n"
            f"{self._label(best)} Available evidence ka sabse defensible current signal: "
            f"{intro} [{best.source_id}] Isse aage ka stronger conclusion tabhi lena chahiye "
            "jab claim-level verification aur enough source depth usse support kare."
        )


__all__ = ["EvidenceSentence", "OfflineEvidenceReasoner"]
