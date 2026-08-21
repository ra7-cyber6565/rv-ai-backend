"""
ContradictionEngine — Spec Section 8 (Contradiction Detection)

Rule-based hai, zero Gemini call. Kaam:
    1. STANCE conflict  — ek source kehta hai "effective hai", dusra kehta hai
       "no significant effect".
    2. NUMERIC conflict — same cheez ke liye do sources bahut alag numbers dete
       hain (e.g. 12% vs 68%).
    3. RECENCY conflict — purana source vs naya source ulta keh rahe hain.

Honesty: ye detection *possible* contradiction batati hai, proof nahi. Isliye
har finding ke saath "rule-based detection" note jaata hai — Spec Section 7/8 ke
hisaab se overclaim nahi karna.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .consensus_gate import CONSENSUS_UNAVAILABLE
from .consensus_gate import evaluate as gate_consensus
from .models import EvidencePack, SourceRecord

_SUPPORT_CUES = (
    "effective", "significant improvement", "significantly improved", "increases",
    "increased", "improves", "improved", "beneficial", "reduces risk", "associated with",
    "supports", "confirmed", "efficacious", "positive effect", "faayda", "labh",
    # 2026-08-21 (cross-domain benchmark): upar ki poori list clinical-trial ki
    # angrezi thi ("efficacious", "reduces risk"). Engineering/archaeology/
    # economics/CS ke sources isi baat ko doosre shabdon mein kehte hain, isliye
    # unka stance NEUTRAL nikalta tha aur contradiction detect hi nahi hoti thi.
    # Ye cue jaan-boojh kar phrase-level hain (akela topic-shabd nahi), warna
    # har paper "SUPPORT" ban jaayega.
    "detected", "demonstrates", "demonstrated", "shows a", "shows that",
    "showed a", "showed that", "consistent with", "successfully reproduced",
    "reproduced the", "replicated", "confirms",
)
_OPPOSE_CUES = (
    "not effective", "ineffective", "no significant", "no effect", "no evidence",
    "failed to", "does not", "did not", "no association", "no benefit", "contradicts",
    "refuted", "disproved", "inconclusive", "no difference", "harmful", "adverse",
    "nuksan", "koi fayda nahi",
    # Domain-neutral "null result" ki bhaasha — har field mein milti hai.
    "not reproduced", "could not reproduce", "failed replication", "null result",
    "no detectable", "no measurable", "not preserved", "no useful", "no reduction",
    "no correlation", "no support for", "no improvement", "not statistically",
)
_HEDGE_CUES = ("may", "might", "suggests", "possible", "preliminary", "unclear",
               "further research", "limited evidence", "mixed")

# Neeche wale OPPOSE cue "null finding" ki seedhi ghoshna hain — inka matlab
# saaf hai. Aur _WEAK_SUPPORT_CUES wo shabd hain jo topic ke naam mein bhi aa
# jaate hain (jaise "minimum wage increases" — yahan "increases" claim nahi,
# sirf topic hai). Agar strong-oppose mila ho aur support ke naam par sirf yahi
# kamzor shabd hon, to stance OPPOSE hai — MIXED nahi. Warna ek asli null
# result sirf topic-shabd ki wajah se "mila-jula" ban jaata tha aur
# contradiction chhoot jaati thi.
_STRONG_OPPOSE_CUES = (
    "not effective", "ineffective", "no significant", "no effect", "no evidence",
    "failed to", "does not", "did not", "no association", "no benefit",
    "no difference", "refuted", "disproved", "not reproduced",
    "could not reproduce", "failed replication", "null result", "no detectable",
    "no measurable", "not preserved", "no useful", "no reduction",
    "no correlation", "no support for", "no improvement", "not statistically",
)
_WEAK_SUPPORT_CUES = ("increases", "increased", "improves", "improved",
                      "associated with")

# Support cue ke aage-peeche negation ho to wo support nahi hai:
# "no measurable improvement" mein "improvement" ko support maanna galat hai.
_NEGATORS = ("no ", "not ", "never ", "without ", "n't ", "neither ", "nor ",
             "failed to ", "unable to ", "cannot ", "could not ", "did not ",
             "does not ", "lack of ", "absence of ", "little ")

_NUM_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")
_YEAR_GAP = 6          # itne saal ka farq ho to recency conflict dekhte hain
_NUM_GAP = 20.0        # percentage points


@dataclass
class Contradiction:
    kind: str
    summary: str
    source_ids: List[str] = field(default_factory=list)
    detail: str = ""
    severity: str = "MEDIUM"

    def to_dict(self) -> Dict:
        return {
            "type": self.kind,
            "summary": self.summary,
            "sources": self.source_ids,
            "detail": self.detail,
            "severity": self.severity,
            "note": "rule-based detection — automatic hai, manually verify karna zaroori hai",
        }


class ContradictionEngine:
    # ── stance ───────────────────────────────────────────────────────────────
    def _all_negated(self, low: str, cue: str) -> bool:
        """
        Cue ki HAR jagah negation ke peeche hai ya nahi.

        "no measurable improvement in throughput" — yahan "improvement" ko
        support maanna galat hai. Sirf tab True jab cue ka koi bhi occurrence
        bina negation ke na ho (yani ek jagah bhi seedha daawa ho to support
        maana jaayega).
        """
        hits = 0
        negated = 0
        start = 0
        while True:
            i = low.find(cue, start)
            if i < 0:
                break
            hits += 1
            if any(n in low[max(0, i - 16):i] for n in _NEGATORS):
                negated += 1
            start = i + len(cue)
        return hits > 0 and negated == hits

    def stance(self, text: str) -> Tuple[str, List[str]]:
        low = (text or "").lower()
        # Pehle OPPOSE dekho — "not effective" ke andar "effective" bhi aata hai
        opposing = [c for c in _OPPOSE_CUES if c in low]
        supporting = [c for c in _SUPPORT_CUES if c in low and
                      not any(c in o for o in opposing) and
                      not self._all_negated(low, c)]
        hedging = [c for c in _HEDGE_CUES if c in low]

        if opposing and supporting:
            strong = [c for c in opposing if c in _STRONG_OPPOSE_CUES]
            if strong and all(c in _WEAK_SUPPORT_CUES for c in supporting):
                # Saaf null result + support ke naam par sirf topic-shabd →
                # ye MIXED nahi, OPPOSE hai.
                return "OPPOSE", opposing
            return "MIXED", opposing + supporting
        if opposing:
            return "OPPOSE", opposing
        if supporting:
            return "SUPPORT", supporting
        if hedging:
            return "HEDGED", hedging
        return "NEUTRAL", []

    def _percentages(self, text: str) -> List[float]:
        out = []
        for m in _NUM_RE.findall(text or ""):
            try:
                value = float(m)
            except ValueError:
                continue
            if 0.0 <= value <= 100.0:
                out.append(value)
        return out

    _STEM_SUFFIXES = ("ational", "ation", "ically", "ingly", "ities", "ility", "ising",
                      "izing", "ments", "ement", "ness", "ions", "ing", "ies", "ial",
                      "ic", "al", "ed", "es", "s")

    def _stem(self, word: str) -> str:
        """Halka stemmer — 'discrimination'/'discriminatory' ko paas laata hai."""
        for suffix in self._STEM_SUFFIXES:
            if len(word) - len(suffix) >= 5 and word.endswith(suffix):
                return word[: -len(suffix)]
        return word

    def _stems(self, text: str) -> set:
        return {self._stem(w) for w in re.findall(r"[a-z]{4,}", (text or "").lower())}

    def _topic_overlap(self, a: SourceRecord, b: SourceRecord) -> int:
        return len(self._stems(f"{a.title} {a.snippet}") &
                   self._stems(f"{b.title} {b.snippet}"))

    def _on_same_question(self, a: SourceRecord, b: SourceRecord, question: str,
                          min_shared: int = 1) -> bool:
        """
        Dono sources usi sawal ke keywords chhoote hain ya nahi.

        Zaroori kyun: pehle version pairwise word-overlap maangta tha, jisse do
        aise sources jo *ek hi sawal* ka ulta jawab dete hain lekin alag
        vocabulary use karte hain (ek "bias increased" bole, dusra "no
        association") skip ho jaate the — yani asli contradiction miss.
        Pack ek hi sawal ke liye bana hai, isliye question-level overlap kaafi
        hai; pairwise overlap ab sirf severity/caveat tay karta hai.
        """
        topic = {w for w in self._stems(question) if len(w) >= 4}
        if not topic:
            return True
        return (len(self._stems(f"{a.title} {a.snippet}") & topic) >= min_shared and
                len(self._stems(f"{b.title} {b.snippet}") & topic) >= min_shared)

    def _shared_topic(self, a: SourceRecord, b: SourceRecord, min_words: int = 3) -> bool:
        """Do sources ek hi baat pe baat kar rahe hain ya nahi — mota andaaza."""
        return self._topic_overlap(a, b) >= min_words

    # ── main ─────────────────────────────────────────────────────────────────
    def _methodology_comparison(self, s1: SourceRecord, s2: SourceRecord) -> Optional[str]:
        """
        Spec §8 enhancement: methodology compare karo conflicting sources ke beech.
        Returns comparison note ya None.
        """
        m1 = s1.methodology or "unknown"
        m2 = s2.methodology or "unknown"
        r1 = s1.methodology_rank
        r2 = s2.methodology_rank

        # Dono unknown — compare nahi kar sakte
        if m1 == "unknown" and m2 == "unknown":
            return None

        # Ek stronger design ka hai
        if r1 > r2:
            from .quality_signals import methodology_label
            return (f"Note: {s1.source_id} stronger design hai ({methodology_label(m1)}) "
                   f"vs {s2.source_id} ({methodology_label(m2)})")
        elif r2 > r1:
            from .quality_signals import methodology_label
            return (f"Note: {s2.source_id} stronger design hai ({methodology_label(m2)}) "
                   f"vs {s1.source_id} ({methodology_label(m1)})")

        return None

    def _sample_comparison(self, s1: SourceRecord, s2: SourceRecord) -> Optional[str]:
        """Extract sample size hints from snippet (if available)."""
        def _extract_n(text: str) -> Optional[int]:
            # Look for patterns like "N = 500" or "n=500" or "500 participants"
            patterns = [
                r'[Nn]\s*=\s*(\d+)',
                r'(\d+)\s+participants',
                r'sample\s+of\s+(\d+)',
                r'(\d+)\s+patients',
                r'(\d+)\s+subjects'
            ]
            for pattern in patterns:
                match = re.search(pattern, text or "")
                if match:
                    try:
                        return int(match.group(1))
                    except (ValueError, IndexError):
                        continue
            return None

        n1 = _extract_n(s1.snippet)
        n2 = _extract_n(s2.snippet)

        if n1 and n2:
            if n1 > n2 * 2:  # Significantly larger
                return f"Note: {s1.source_id} ki sample size kaafi badi hai (n≈{n1}) vs {s2.source_id} (n≈{n2})"
            elif n2 > n1 * 2:
                return f"Note: {s2.source_id} ki sample size kaafi badi hai (n≈{n2}) vs {s1.source_id} (n≈{n1})"

        return None

    def _temporal_comparison(self, s1: SourceRecord, s2: SourceRecord) -> Optional[str]:
        """Spec §8: newer study ko preference hint."""
        if not s1.year or not s2.year:
            return None

        gap = abs(s1.year - s2.year)
        if gap >= _YEAR_GAP:
            newer = s1 if s1.year > s2.year else s2
            older = s2 if s1.year > s2.year else s1
            return (f"Note: {newer.source_id} zyada recent hai ({newer.year}) — "
                   f"newer evidence ko generally preference milti hai medical/scientific fields mein")

        return None

    def detect(self, pack: EvidencePack) -> List[Contradiction]:
        sources = pack.sources
        found: List[Contradiction] = []
        if len(sources) < 2:
            return found

        stances: Dict[str, Tuple[str, List[str]]] = {
            s.source_id: self.stance(f"{s.title}. {s.snippet}") for s in sources
        }
        question = pack.question or ""

        for i, a in enumerate(sources):
            for b in sources[i + 1:]:
                # Same origin ke do sources ka "conflict" matlab nahi rakhta
                if a.independence_key == b.independence_key:
                    continue

                overlap = self._topic_overlap(a, b)
                stance_a, cues_a = stances[a.source_id]
                stance_b, cues_b = stances[b.source_id]

                if {stance_a, stance_b} == {"SUPPORT", "OPPOSE"}:
                    # STANCE ke liye pairwise vocabulary match zaroori nahi —
                    # sawal-level relevance kaafi hai (dono isi pack mein hain).
                    if not self._on_same_question(a, b, question):
                        continue
                    if overlap >= 3:
                        severity = "HIGH" if (a.peer_reviewed and b.peer_reviewed) else "MEDIUM"
                        caveats = []
                    else:
                        severity = "MEDIUM" if (a.peer_reviewed and b.peer_reviewed) else "LOW"
                        caveats = ["Dhyan do: in dono ka wording kaafi alag hai, ho "
                                  "sakta hai ye ek hi cheez na maap rahe hon — pehle "
                                  "scope compare karo."]

                    # Spec §8 enhancements
                    method_note = self._methodology_comparison(a, b)
                    if method_note:
                        caveats.append(method_note)

                    sample_note = self._sample_comparison(a, b)
                    if sample_note:
                        caveats.append(sample_note)

                    temporal_note = self._temporal_comparison(a, b)
                    if temporal_note:
                        caveats.append(temporal_note)

                    detail_parts = [f"{a.source_id}: {', '.join(cues_a[:3])}",
                                   f"{b.source_id}: {', '.join(cues_b[:3])}"]
                    if caveats:
                        detail_parts.append(" | ".join(caveats))

                    found.append(Contradiction(
                        kind="STANCE",
                        summary=f"{a.citation_label()} aur {b.citation_label()} "
                                f"ulti direction mein point kar rahe hain",
                        source_ids=[a.source_id, b.source_id],
                        detail=" | ".join(detail_parts),
                        severity=severity,
                    ))
                    continue

                # NUMERIC/RECENCY ke liye pairwise topic overlap zaroori hai,
                # warna alag-alag cheezon ke numbers compare hone lagenge.
                if overlap < 3:
                    continue

                nums_a = self._percentages(f"{a.title} {a.snippet}")
                nums_b = self._percentages(f"{b.title} {b.snippet}")
                if nums_a and nums_b:
                    gap = abs(max(nums_a) - max(nums_b))
                    if gap >= _NUM_GAP:
                        found.append(Contradiction(
                            kind="NUMERIC",
                            summary=f"Numbers match nahi karte: {a.source_id} "
                                    f"{max(nums_a):.0f}% vs {b.source_id} {max(nums_b):.0f}%",
                            source_ids=[a.source_id, b.source_id],
                            detail="Ho sakta hai dono alag cheez maap rahe hon — "
                                   "definitions check karo.",
                            severity="MEDIUM",
                        ))
                        continue

                if a.year and b.year and abs(a.year - b.year) >= _YEAR_GAP:
                    if {stance_a, stance_b} in ({"SUPPORT", "HEDGED"}, {"OPPOSE", "HEDGED"}):
                        older, newer = sorted([a, b], key=lambda s: s.year or 0)
                        found.append(Contradiction(
                            kind="RECENCY",
                            summary=f"{older.year} ka source aur {newer.year} ka source "
                                    f"alag confidence dikhate hain",
                            source_ids=[a.source_id, b.source_id],
                            detail="Naya evidence purane ko update kar sakta hai — "
                                   "newer source ko zyada weight do.",
                            severity="LOW",
                        ))

        # Ek jodi ek hi baar report ho
        unique: List[Contradiction] = []
        seen = set()
        for c in found:
            key = (c.kind, tuple(sorted(c.source_ids)))
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)
        return unique[:10]

    # ── consensus (Spec Section 7 + §11 gate) ────────────────────────────────
    def consensus_report(self, pack: EvidencePack,
                         contradictions: Optional[List[Contradiction]] = None,
                         contradiction_analysis_done: Optional[bool] = None,
                         reasoning_complete: Optional[bool] = None,
                         opposition_searched: Optional[bool] = None,
                         queries: Optional[List[str]] = None) -> Dict:
        """
        Sehmati ka level — par SIRF tab, jab §11 ki chhe shartein poori hon.

        `contradictions=None` = contradiction analysis chali hi nahi.
        `contradictions=[]`   = chali, kuch nahi mila. Dono alag baat hain, aur
        gate inhe alag hi treat karta hai.
        """
        stance_counts = {"SUPPORT": 0, "OPPOSE": 0, "MIXED": 0, "HEDGED": 0, "NEUTRAL": 0}
        keys_by_stance: Dict[str, set] = {k: set() for k in stance_counts}

        for s in pack.sources:
            stance, _ = self.stance(f"{s.title}. {s.snippet}")
            stance_counts[stance] += 1
            keys_by_stance[stance].add(s.independence_key)

        # "Independent" = alag origin, alag URL nahi
        independent_support = len(keys_by_stance["SUPPORT"])
        independent_oppose = len(keys_by_stance["OPPOSE"])

        if independent_support and not independent_oppose and independent_support >= 3:
            level = "APPARENT CONSENSUS"
        elif independent_support and independent_oppose:
            level = "DISPUTED"
        elif not independent_support and not independent_oppose:
            level = "NO CLEAR STANCE"
        else:
            level = "LEANING"

        # §11 — gate. Shartein poori na hon to level chhapta hi nahi. Raw level
        # `level_if_gate_passed` mein rehta hai (developer/audit ke liye), taaki
        # jaankari na khoye — par user ke jawab mein sehmati ka daawa nahi jaata.
        gate = gate_consensus(
            pack, contradictions=contradictions,
            contradiction_analysis_done=contradiction_analysis_done,
            reasoning_complete=reasoning_complete,
            opposition_searched=opposition_searched,
            queries=queries,
            independent_sources=pack.independent_source_count,
        )
        report = {
            "level": level if gate.passed else CONSENSUS_UNAVAILABLE,
            "stance_counts": stance_counts,
            "independent_supporting_origins": independent_support,
            "independent_opposing_origins": independent_oppose,
            "contradictions_found": len(contradictions or []),
            "contradiction_analysis_done": bool(
                contradiction_analysis_done if contradiction_analysis_done is not None
                else contradictions is not None),
            "gate_passed": gate.passed,
            "gate": gate.to_dict(),
            "unmet_conditions": list(gate.unmet_reasons),
            "note": gate.note(),
        }
        if not gate.passed:
            report["level_if_gate_passed"] = level
        return report
