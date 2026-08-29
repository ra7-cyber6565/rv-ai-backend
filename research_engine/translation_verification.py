"""Independent translation verification for evidence-bearing passages.

The verifier does not translate text itself. It evaluates two or more
independently produced target-language renderings of the same committed source
text before a translated passage may support an unattended strong claim.
Agreement is a consistency signal, not proof of factual truth or perfect
semantic equivalence.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Sequence, Tuple


VERDICT_OK = "AGREEMENT_OK"
VERDICT_REVIEW = "REVIEW_REQUIRED"
VERDICT_INSUFFICIENT = "INSUFFICIENT_INDEPENDENCE"

_NUM_RE = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?(?:%|°[CFK]?)?", re.IGNORECASE)
_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
_NEGATION = {
    "no", "not", "never", "none", "without", "cannot", "can't", "isn't",
    "नहीं", "नही", "मत", "बिना", "न",
}


def source_text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _normalise(text: str) -> str:
    return " ".join(word.casefold() for word in _WORD_RE.findall(text or ""))


def _numbers(text: str) -> List[str]:
    return [match.group(0).replace(",", "").casefold()
            for match in _NUM_RE.finditer(text or "")]


def _negations(text: str) -> List[str]:
    tokens = set(_normalise(text).split())
    return sorted(tokens & _NEGATION)


def _similarity(a: str, b: str) -> float:
    na, nb = _normalise(a), _normalise(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(a=na, b=nb, autojunk=False).ratio()
    wa, wb = set(na.split()), set(nb.split())
    union = wa | wb
    jaccard = len(wa & wb) / len(union) if union else 0.0
    return max(0.0, min(1.0, 0.65 * ratio + 0.35 * jaccard))


def _pairwise(values: Sequence["TranslationCandidate"]) -> List[Tuple[int, int]]:
    return [(i, j) for i in range(len(values)) for j in range(i + 1, len(values))]


@dataclass(frozen=True)
class TranslationCandidate:
    translator_id: str
    text: str
    source_hash: str
    source_language: str
    target_language: str
    method: str = "model"
    revision: str = ""

    def to_dict(self) -> Dict:
        return {
            "translator_id": self.translator_id,
            "text": self.text,
            "source_hash": self.source_hash,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "method": self.method,
            "revision": self.revision,
        }


@dataclass
class TranslationVerification:
    verdict: str
    review_required: bool
    reason: str
    source_hash: str
    source_language: str
    target_language: str
    translator_ids: List[str] = field(default_factory=list)
    pairwise_agreement: List[Dict] = field(default_factory=list)
    number_checks: List[Dict] = field(default_factory=list)
    critical_term_checks: List[Dict] = field(default_factory=list)
    disagreement_flags: List[str] = field(default_factory=list)
    agreement_score: float = 0.0
    truth_proven: bool = False

    def to_dict(self) -> Dict:
        return {
            "method": "translation",
            "verification_verdict": self.verdict,
            "review_required": bool(self.review_required),
            "reason": self.reason,
            "source_hash": self.source_hash,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "translator_ids": list(self.translator_ids),
            "pairwise_agreement": [dict(row) for row in self.pairwise_agreement],
            "number_checks": [dict(row) for row in self.number_checks],
            "critical_term_checks": [dict(row) for row in self.critical_term_checks],
            "disagreement_flags": list(self.disagreement_flags),
            "agreement_score": round(float(self.agreement_score), 4),
            "truth_proven": False,
            "confidence_semantics": (
                "independent-translation consistency signal; NOT proof of factual truth "
                "or perfect semantic equivalence"
            ),
        }


class TranslationVerifier:
    """Fail-closed verifier for independent translations of one source text."""

    def __init__(self, *, min_pair_agreement: float = 0.58,
                 min_mean_agreement: float = 0.68):
        self.min_pair_agreement = max(0.0, min(1.0, float(min_pair_agreement)))
        self.min_mean_agreement = max(0.0, min(1.0, float(min_mean_agreement)))

    def verify(
        self,
        source_text: str,
        candidates: Iterable[TranslationCandidate],
        *,
        critical_terms: Sequence[str] = (),
    ) -> TranslationVerification:
        rows = list(candidates)
        expected_hash = source_text_hash(source_text)
        source_langs = {str(row.source_language or "").strip() for row in rows}
        target_langs = {str(row.target_language or "").strip() for row in rows}
        ids = [str(row.translator_id or "").strip() for row in rows]
        unique_ids = {value for value in ids if value}

        def early(verdict: str, reason: str, *, flags: Sequence[str] = ()):
            return TranslationVerification(
                verdict=verdict,
                review_required=verdict != VERDICT_OK,
                reason=reason,
                source_hash=expected_hash,
                source_language=(next(iter(source_langs)) if len(source_langs) == 1 else ""),
                target_language=(next(iter(target_langs)) if len(target_langs) == 1 else ""),
                translator_ids=sorted(unique_ids),
                disagreement_flags=list(flags),
            )

        if len(rows) < 2 or len(unique_ids) < 2:
            return early(VERDICT_INSUFFICIENT,
                         "kam se kam do distinct translator IDs chahiye")
        if any(not row.text.strip() for row in rows):
            return early(VERDICT_REVIEW, "ek ya adhik translation khaali hai",
                         flags=["empty_translation"])
        if any(row.source_hash != expected_hash for row in rows):
            return early(VERDICT_REVIEW,
                         "candidate translations same committed source text se bound nahi hain",
                         flags=["source_hash_mismatch"])
        if len(source_langs) != 1 or "" in source_langs:
            return early(VERDICT_REVIEW, "source-language metadata inconsistent/missing",
                         flags=["source_language_mismatch"])
        if len(target_langs) != 1 or "" in target_langs:
            return early(VERDICT_REVIEW, "target-language metadata inconsistent/missing",
                         flags=["target_language_mismatch"])

        pairs: List[Dict] = []
        pair_scores: List[float] = []
        flags: List[str] = []
        for i, j in _pairwise(rows):
            score = _similarity(rows[i].text, rows[j].text)
            pair_scores.append(score)
            pairs.append({
                "translator_a": rows[i].translator_id,
                "translator_b": rows[j].translator_id,
                "agreement": round(score, 4),
            })
            if score < self.min_pair_agreement:
                flags.append(
                    f"low_pair_agreement:{rows[i].translator_id}:{rows[j].translator_id}"
                )
            if bool(_negations(rows[i].text)) != bool(_negations(rows[j].text)):
                flags.append(
                    f"negation_disagreement:{rows[i].translator_id}:{rows[j].translator_id}"
                )

        source_numbers = _numbers(source_text)
        number_checks: List[Dict] = []
        for row in rows:
            translated_numbers = _numbers(row.text)
            missing = [number for number in source_numbers if number not in translated_numbers]
            extras = [number for number in translated_numbers if number not in source_numbers]
            number_checks.append({
                "translator_id": row.translator_id,
                "source_numbers": source_numbers,
                "translation_numbers": translated_numbers,
                "missing": missing,
                "extra": extras,
                "preserved": not missing and not extras,
            })
            if missing or extras:
                flags.append(f"number_disagreement:{row.translator_id}")

        term_checks: List[Dict] = []
        for raw_term in critical_terms:
            term = _normalise(str(raw_term or ""))
            if not term:
                continue
            per = []
            for row in rows:
                present = term in _normalise(row.text)
                per.append({"translator_id": row.translator_id, "present": present})
            term_checks.append({"term": str(raw_term), "translations": per})
            if not all(item["present"] for item in per):
                flags.append(f"critical_term_disagreement:{raw_term}")

        mean_agreement = (sum(pair_scores) / len(pair_scores)) if pair_scores else 0.0
        independent_methods = {
            (str(row.method or "").strip().lower(), str(row.revision or "").strip())
            for row in rows
        }
        if len(independent_methods) < 2:
            flags.append("translator_implementation_not_distinct")

        flags = sorted(set(flags))
        ok = (
            not flags
            and pair_scores
            and min(pair_scores) >= self.min_pair_agreement
            and mean_agreement >= self.min_mean_agreement
        )
        verdict = VERDICT_OK if ok else VERDICT_REVIEW
        reason = (
            "independent translations agree on wording, numbers and critical terms"
            if ok else
            "translation disagreement/independence gate requires review before strong-claim use"
        )
        return TranslationVerification(
            verdict=verdict,
            review_required=not ok,
            reason=reason,
            source_hash=expected_hash,
            source_language=next(iter(source_langs)),
            target_language=next(iter(target_langs)),
            translator_ids=sorted(unique_ids),
            pairwise_agreement=pairs,
            number_checks=number_checks,
            critical_term_checks=term_checks,
            disagreement_flags=flags,
            agreement_score=mean_agreement,
            truth_proven=False,
        )
