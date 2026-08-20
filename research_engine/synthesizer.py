"""
FinalSynthesizer — Spec Section 14 (Final Answer Format) + Section 12 (cross-disciplinary)

Do zimmedaari:

  1. PASS 7 prompt banana — "Chief Researcher" role, jo saare passes ko ek
     structured jawab mein badalta hai.

  2. Final answer ASSEMBLE karna. Ye asli trick hai: sections 4, 7, 8, 9, 11,
     12, 14 (conflicting evidence, hypotheses, evidence-against, verification,
     confidence, sources, coverage/limits) Gemini se NAHI aate — wo local
     engines se aate hain. Iska matlab:
        * Gemini fail ho jaaye ya quota khatam ho, tab bhi ye sections sach hain
        * Gemini in numbers ko hallucinate nahi kar sakta

Spec Section 17/18: aisa output nahi hona chahiye jo "dikhne mein Deep Research"
lage. Isliye har section ke andar real, computed data jaata hai — decoration nahi.

SECTION ORDER (Spec Section 14 ki literal list): spec ne jo 13 sections diye
hain, wahi order hai — 1 direct conclusion, 2 established facts, 3 strong
evidence, 4 conflicting evidence, 5 cross-disciplinary, 6 inferences,
7 new hypotheses, 8 evidence against hypotheses, 9 verification, 10 unknowns,
11 confidence, 12 sources, 13 next research. 14th section ("Coverage, Limits &
Honesty Report") hamara apna addition hai.

Gemini se sirf 7 sections mangte hain (1, 2, 3, 5, 6, 10, 13); baaki 7 system
banata hai. Model kis order mein likhe isse farak nahi padta — uske blob ko
headings par tod kar canonical order mein merge kiya jaata hai.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .citation import CITATION_INSTRUCTION, CitationEngine
from .explain_style import style_block
from .models import EvidencePack

SECTION_TITLES = [
    "1. Seedha Jawab (Direct Conclusion)",
    "2. Established Facts",
    "3. Strong Evidence (Evidence Analysis)",
    "4. Conflicting Evidence (sources ke beech)",
    "5. Cross-Disciplinary Explanation",
    "6. Inferences (evidence se nikale gaye — fact nahi)",
    "7. New Hypotheses (UNTESTED)",
    "8. Evidence Against Hypotheses & Jawab ki Weaknesses",
    "9. Verification Status",
    "10. Abhi Bhi Kya Unknown Hai",
    "11. Confidence & Evidence Level",
    "12. Sources / Citations",
    "13. Suggested Next Research / Experiment",
    "14. Coverage, Limits & Honesty Report",
]

# Ye sections SYSTEM banata hai (Gemini se nahi aate) — inke numbers computed
# hote hain, isliye model ka version inhe replace nahi kar sakta.
SYSTEM_OWNED = {3, 6, 7, 8, 10, 11, 13}

# markdown heading (## 3. Established Facts / ### Sources / #4 ...)
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*\**[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_HEADING_NUM_RE = re.compile(r"^(\d{1,2})\s*[\.\):\-]?\s*(.*)$")
# agar model heading par number na likhe to naam se pehchaano (pehla match jeetta
# hai — isliye zyada specific phrase pehle rakhi gayi hai, warna "evidence against
# hypotheses" bhi "hypothes" se match kar jaata)
_TITLE_HINTS = [
    ("seedha jawab", 0), ("direct answer", 0), ("direct conclusion", 0),
    ("established fact", 1),
    ("strong evidence", 2), ("evidence analysis", 2),
    ("conflicting evidence", 3), ("contradiction", 3),
    ("cross-disciplinary", 4), ("cross disciplinary", 4),
    ("inference", 5),
    ("against hypothes", 7), ("evidence against", 7),
    ("counter-evidence", 7), ("counter evidence", 7), ("weakness", 7),
    ("hypothes", 6),
    ("verification", 8),
    ("unknown", 9),
    ("confidence", 10), ("evidence level", 10),
    ("source", 11), ("citation", 11),
    ("next research", 12), ("next step", 12), ("practical", 12),
    ("coverage", 13), ("limits", 13), ("honesty", 13),
    ("experiment", 12),
]


class FinalSynthesizer:
    def __init__(self):
        self.citations = CitationEngine()

    # ── PASS 7 prompt ────────────────────────────────────────────────────────
    def prompt(self, question: str, analysis: str, critique: str, hypothesis_text: str,
               pack: EvidencePack, plan: Dict, memory_note: str = "") -> str:
        critique_block = f"\nCRITIC KE FINDINGS:\n{critique[:2500]}\n" if critique else ""
        hypothesis_block = (f"\nGENERATED HYPOTHESES (status: UNTESTED):\n"
                            f"{hypothesis_text[:2500]}\n") if hypothesis_text else ""
        memory_block = f"\n{memory_note}\n" if memory_note else ""

        return f"""You are a research assistant helping users understand complex topics in simple, natural language.

QUESTION: {question}

ANALYSIS:
{analysis[:5000]}
{critique_block}{hypothesis_block}{memory_block}
SOURCES (cite using these IDs only):
{pack.to_prompt_block(max_chars_per_source=500)}

{CITATION_INSTRUCTION}

{style_block(question, SECTION_TITLES)}

# BAAKI RULES
- Hypotheses par "UNTESTED HYPOTHESIS" likhna zaroori hai.
- Critic ke findings section 8 mein imaandaari se likho — apni tareef mat karo.
- Jis baat ka source nahi hai use [NO-SOURCE] mark karo.
- Tumhare paas {len(pack.sources)} sources hain, {pack.independent_source_count} independent origins ke.
- Evidence kamzor ho to ghumao mat — pehli line mein hi saaf bol do.

Write these 7 sections (system will add others):

## {SECTION_TITLES[0]}
(2-4 lines. SEEDHA jawab, pehli line mein hi. Koi bhoomika nahi. Agar evidence
kamzor hai to yahi bol do ki pakka jawab nahi hai.)

## {SECTION_TITLES[1]}
(Key facts ki bullet list. Har point: [S#] + simple explanation. Example:
- **[S1] Study ka naam:** kya paaya gaya — aam shabdon mein)

## {SECTION_TITLES[2]}
(Evidence ki quality simple shabdon mein: kitni studies thi, kis tarah ki thi,
kitna bharosa kiya ja sakta hai aur kyun. Jargon aaye to uska matlab saath likho.)

## {SECTION_TITLES[4]}
(Alag-alag fields ({", ".join(plan.get("relevant_fields", [])[:4]) or "relevant areas"})
is sawaal se kaise judti hain. Practical rakho — theory ka lecture nahi.)

## {SECTION_TITLES[5]}
(Jo baatein evidence se nikalti hain par sources mein seedhe likhi nahi hain.
Har point: [INFERENCE] + kis [S#] se nikli.)

## {SECTION_TITLES[9]}
(Kya abhi bhi pata nahi hai — thos likho. "More research needed" nahi, balki
"X pata nahi hai kyunki ...".)

## {SECTION_TITLES[12]}
(Aage kya karna chahiye: kaunsa experiment/study bachi hui baat settle karega?
Medical/legal ho to professional se milne ki salah do. Actionable rakho.)

Write the answer now:"""

    # ── local sections (Gemini-independent, isliye hamesha sach) ─────────────
    def _contradiction_section(self, contradictions: List[Dict]) -> str:
        if not contradictions:
            return ("Retrieved sources ke beech koi direct contradiction detect nahi hui.\n"
                    "(Detection rule-based hai — iska matlab ye nahi ki literature mein "
                    "contradiction nahi hai.)")
        lines = []
        for c in contradictions:
            ids = ", ".join(c.get("sources", []))
            lines.append(f"- [{c.get('severity', 'MEDIUM')}] {c.get('summary', '')}"
                         f"{f' ({ids})' if ids else ''}")
            if c.get("detail"):
                lines.append(f"  {c['detail']}")
        lines.append("\n(Ye automatic rule-based detection hai — verify karna zaroori hai.)")
        return "\n".join(lines)

    def _hypothesis_section(self, hypotheses: List[Dict]) -> str:
        if not hypotheses:
            return "Is sawal ke liye nayi hypothesis generate nahi ki gayi (zaroorat nahi thi)."
        lines = []
        for i, h in enumerate(hypotheses, 1):
            lines.append(f"### Hypothesis {i} — STATUS: {h.get('status', 'UNTESTED HYPOTHESIS')}")
            lines.append(f"- **Statement:** {h.get('statement', '')}")
            if h.get("reasoning"):
                lines.append(f"- **Reasoning:** {h['reasoning']}")
            if h.get("supporting_evidence"):
                lines.append(f"- **Supporting:** {h['supporting_evidence']}")
            if h.get("novelty"):
                lines.append(f"- **Novelty:** {h['novelty']}")
            if h.get("prediction"):
                lines.append(f"- **Prediction (agar sach hai to kya dikhega):** "
                             f"{h['prediction']}")
            if h.get("how_to_test"):
                lines.append(f"- **Test kaise ho:** {h['how_to_test']}")
            if h.get("risks"):
                lines.append(f"- **Risks:** {h['risks']}")
            if h.get("confidence_reasoning_based"):
                lines.append(f"- **Confidence (reasoning-based, proof nahi):** "
                             f"{h['confidence_reasoning_based']}")
            lines.append(f"- _{h.get('disclaimer', '')}_")
            lines.append("")
        lines.append("_(Har hypothesis ke KHILAF evidence agle section "
                     "(\"Evidence Against Hypotheses\") mein alag se hai.)_")
        return "\n".join(lines).strip()

    def _against_section(self, critique: Dict, hypotheses: List[Dict]) -> str:
        """
        Spec §14 ka item 8 — "Evidence against hypotheses". Do hisse hain:

          (a) har hypothesis ke khilaf jo evidence khud hypothesis engine ne
              nikala; agar kisi hypothesis ke khilaf kuch nahi likha gaya to ye
              **saaf bola jaata hai** (self-falsification adhoora hai) —
              khaali jagah chhod dena zyada bharosemand dikhta hai, isliye nahi
              karte.
          (b) critic pass ki weaknesses / missing evidence / alternative
              explanations, jo poore jawab par lagti hain.
        """
        lines: List[str] = []
        if hypotheses:
            lines.append("**Hypotheses ke khilaf:**")
            for i, h in enumerate(hypotheses, 1):
                against = (h.get("contradicting_evidence") or "").strip()
                if against:
                    lines.append(f"- Hypothesis {i}: {against}")
                else:
                    lines.append(f"- Hypothesis {i}: iske khilaf koi evidence list "
                                 "nahi hui — yaani self-falsification adhoora hai.")
            lines.append("")

        weakness_lines: List[str] = []
        for item in (critique or {}).get("weaknesses", [])[:6]:
            weakness_lines.append(f"- {item}")
        for item in (critique or {}).get("missing_evidence", [])[:4]:
            weakness_lines.append(f"- Missing evidence: {item}")
        for item in (critique or {}).get("alternative_explanations", [])[:4]:
            weakness_lines.append(f"- Alternative explanation: {item}")
        if not weakness_lines:
            weakness_lines.append(
                "- Critic pass is run mein nahi chali (call budget) — iska matlab ye "
                "jawab self-critique se nahi guzra hai, ise dhyan mein rakhein.")

        if hypotheses:
            lines.append("**Poore jawab ki weaknesses (critic se):**")
        lines.extend(weakness_lines)
        return "\n".join(lines)

    def _verification_section(self, verification: Dict) -> str:
        lines = [f"**Status: {verification.get('status', 'UNVERIFIABLE HERE')}**", ""]
        for check in verification.get("checks", []):
            passed = check.get("passed")
            mark = "PASS" if passed is True else ("FAIL" if passed is False else "N/A")
            line = f"- [{mark}] {check.get('check', '')}"
            if check.get("detail"):
                line += f" — {check['detail']}"
            lines.append(line)
        for warning in verification.get("warnings", []):
            lines.append(f"- WARNING: {warning}")

        # Spec Section 11 — statistics-presence audit (numbers verify/invent nahi)
        stats = verification.get("statistics") or {}
        if stats.get("sources_checked"):
            markers = stats.get("markers_found", {})
            shown = ", ".join(f"{k}: {v}" for k, v in markers.items() if v) or "koi nahi"
            lines.append(
                f"- Statistics in sources: "
                f"{stats.get('sources_with_statistics', 0)}/"
                f"{stats.get('sources_checked', 0)} sources ke available text mein "
                f"statistical reporting dikhi ({shown}). "
                f"{stats.get('note', '')}")

        # Spec Section 11 — datasets jinse user KHUD numbers verify kar sakta hai
        data = verification.get("data_for_verification") or []
        if data:
            lines.append("- Verification ke liye available data (raw datasets — "
                         "inse numbers khud check kiye ja sakte hain):")
            for d in data:
                lines.append(f"    - {d}")

        # Spec Section 11 — honest limits (simulation/backtest engine khud nahi chalata)
        for limit in verification.get("limits", []):
            lines.append(f"- LIMIT: {limit}")

        for test in verification.get("required_tests", []):
            lines.append("")
            lines.append(test)
        lines.append("")
        lines.append(f"_{verification.get('note', '')}_")
        return "\n".join(lines)

    def _coverage_section(self, coverage: Dict, honesty: Dict, discovery_note: str,
                          consensus: Dict, quota_note: str, warnings: List[str]) -> str:
        used = coverage.get("sources_used", 0)
        lines = [
            f"- Sources used: **{used}** "
            f"(independent origins: **{coverage.get('independent_sources', 0)}**, "
            f"candidates screened: **{coverage.get('candidates_discovered', 0)}**)",
            f"- Breakdown: {coverage.get('by_source_type', {})} | "
            f"user documents: {coverage.get('documents_from_user', 0)}, "
            f"external: {coverage.get('external_sources', 0)}",
            f"- Peer-reviewed: {coverage.get('peer_reviewed', 0)} | "
            f"Full text available: {coverage.get('full_text_available', 0)}",
            # Spec Section 7 — study design / retraction / COI ki asli ginti.
            # Ye line bhi counts se banti hai: jitne sources ka design pata nahi
            # chala, wo saaf "unknown" mein dikhte hain.
            f"- Source quality signals: {self._quality_line(coverage)}",
            # Spec Section 2: "search karna" aur "poora text padhna" alag
            # cheezein hain — isliye reading depth alag line mein, asli counts se
            f"- Reading depth: {self._reading_line(coverage)}",
            f"- Connectors searched: "
            f"{', '.join(coverage.get('connectors_searched', [])) or 'none'}",
            f"- Search rounds: {coverage.get('research_rounds', 1)}",
            f"- Consensus signal: {consensus.get('level', 'N/A')} "
            f"(support origins: {consensus.get('independent_supporting_origins', 0)}, "
            f"oppose origins: {consensus.get('independent_opposing_origins', 0)})",
            f"- Discovery log: {discovery_note or 'n/a'}",
            f"- Gemini usage: {quota_note}",
        ]
        if honesty.get("summary"):
            lines.append("- Citation check:")
            lines.append(honesty["summary"])
        for warning in warnings:
            lines.append(f"- WARNING: {warning}")
        lines += [
            "",
            "**Limits (imaandaari se):**",
            f"- {coverage.get('honesty_note') or 'Reading level ka data available nahi.'}",
            f"- {coverage.get('quality_signal_note') or 'Source quality signals ka data available nahi.'}",
            "- Karodon books ya paywalled papers ka poora text nahi padha gaya — "
            "system ne un tak search kiya, unhe padha nahi.",
            "- Paywalled/copyrighted content bypass nahi kiya gaya.",
            "- Reasoning ek hi AI model ke alag passes se aayi hai — ye independent "
            "human experts ki review nahi hai.",
            "- Jo bhi hypothesis di gayi hai wo untested hai; lab/clinical validation "
            "is system ke bahar ki cheez hai.",
            # Ye limit chhupane layak nahi hai: methodology tier publication TYPE
            # se nikla hai, poori methods section padh kar nahi.
            "- Study design/retraction ka pata metadata se chala hai (publication "
            "type, PubMed pubtype, Crossref flags) — har paper ka methods section "
            "padh kar nahi. Retraction ka signal na milna 'retracted nahi hai' "
            "ka saboot nahi hai.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _quality_line(coverage: Dict) -> str:
        """
        Spec Section 7 ki ek-line summary. Ye bhi asli counts se banti hai,
        isliye "sab strong evidence hai" jaisa jhooth nahi bol sakti.
        """
        methodologies = coverage.get("methodologies") or {}
        if not methodologies:
            return "data available nahi"
        total = sum(methodologies.values()) or 1
        unknown = methodologies.get("unknown", 0)
        bits = [f"strong design (RCT/meta-analysis level): "
                f"{coverage.get('strong_methodology_sources', 0)}/{total}",
                f"design pata nahi chala: {unknown}/{total}"]
        retracted = coverage.get("retracted_sources", 0)
        bits.append(f"RETRACTION signal: {retracted}" if retracted
                    else "retraction signal: 0")
        checked = coverage.get("coi_checked_sources", 0)
        bits.append(f"COI check ho saka: {checked}/{total} (sirf full text par possible)")
        return " | ".join(bits)

    @staticmethod
    def _reading_line(coverage: Dict) -> str:
        """
        Ye line coverage ke asli numbers se banti hai, hardcoded nahi hai —
        isliye ye kabhi "full text padha" ka jhootha dava nahi kar sakti.
        """
        levels = coverage.get("read_levels") or {}
        reading = coverage.get("reading") or {}
        if not levels:
            return "koi source nahi (kuch padha nahi gaya)"
        pretty = ", ".join(f"{level}: {count}" for level, count in levels.items())
        bits = [pretty]
        if reading.get("succeeded"):
            bits.append(f"{reading['succeeded']}/{reading.get('attempted', 0)} full-text "
                        f"fetch safal (~{reading.get('chars_read', 0):,} chars)")
        elif reading.get("attempted"):
            bits.append(f"0/{reading['attempted']} full-text fetch safal")
        if reading.get("skipped_over_budget"):
            bits.append(f"{reading['skipped_over_budget']} source depth budget ke bahar")
        return " | ".join(bits)

    # ── Gemini ke blob ko canonical sections mein todo ───────────────────────
    @staticmethod
    def _section_index(heading: str) -> Optional[int]:
        """Heading se section number nikaalo (number se, warna naam se)."""
        text = (heading or "").strip().strip("#*").strip()
        match = _HEADING_NUM_RE.match(text)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(SECTION_TITLES):
                return idx
        low = text.lower()
        for phrase, idx in _TITLE_HINTS:
            if phrase in low:
                return idx
        return None

    def split_model_sections(self, body: str) -> tuple:
        """
        Returns ({section_index: text}, leftover_text).

        Jo heading pehchani nahi gayi (ya jo section system khud banata hai), wo
        leftover mein jaati hai — DELETE nahi hoti. Model ka kaam chhupana nahi
        hai, sirf canonical order mein rakhna hai.
        """
        body = (body or "").strip()
        if not body:
            return {}, ""
        matches = list(_HEADING_RE.finditer(body))
        if not matches:
            return {}, body

        found: Dict[int, str] = {}
        leftovers: List[str] = []
        preamble = body[:matches[0].start()].strip()

        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            content = body[match.end():end].strip()
            idx = self._section_index(match.group(1))
            if idx is None:
                leftovers.append(body[match.start():end].strip())
                continue
            if idx in SYSTEM_OWNED:
                # Ye numbers system compute karta hai (citations, coverage,
                # verification). Model ka version replace nahi karega, par
                # chhupayenge bhi nahi — neeche note ke roop mein rahega.
                if content:
                    leftovers.append(f"**(model ka apna \"{SECTION_TITLES[idx]}\" "
                                     f"section):**\n{content}")
                continue
            if content:
                found[idx] = (found[idx] + "\n\n" + content) if idx in found else content

        if preamble:
            # heading bhoolne par bhi text na kho — direct answer maan lo
            if 0 in found:
                leftovers.insert(0, preamble)
            else:
                found[0] = preamble
        return found, "\n\n".join(p for p in leftovers if p).strip()

    # ── final assembly ───────────────────────────────────────────────────────
    def assemble(
        self,
        gemini_answer: str,
        pack: EvidencePack,
        evidence_level: str,
        confidence_note: str,
        contradictions: List[Dict],
        hypotheses: List[Dict],
        verification: Dict,
        coverage: Dict,
        honesty: Dict,
        consensus: Dict,
        discovery_note: str,
        quota_note: str,
        critique: Optional[Dict] = None,
        warnings: Optional[List[str]] = None,
    ) -> str:
        body = (gemini_answer or "").strip()
        model_sections, leftover = self.split_model_sections(body)

        # ── system ke sections (Gemini fail ho to bhi ye sach rehte hain) ──
        critique = critique or {}

        system_sections: Dict[int, str] = {
            3: self._contradiction_section(contradictions),
            6: self._hypothesis_section(hypotheses),
            7: self._against_section(critique, hypotheses),
            8: self._verification_section(verification),
            10: f"**Evidence level: {evidence_level}**\n{confidence_note}",
            11: (self.citations.render_bibliography(
                    pack,
                    cited_ids=[c.get("source_id") for c in honesty.get("cited", [])])
                 or "Koi source nahi mila."),
            13: self._coverage_section(coverage, honesty, discovery_note, consensus,
                                       quota_note, warnings or []),
        }

        if not body and 0 not in model_sections:
            model_sections[0] = (
                "Gemini reasoning is run mein available nahi thi (quota ya error). "
                "Neeche sirf wo cheezein hain jo system ne khud retrieve aur "
                "verify ki hain.")

        # ── canonical 1 → 14 order (Spec §14 ki literal list + hamara §14 honesty) ──
        parts: List[str] = []
        for idx, title in enumerate(SECTION_TITLES):
            content = system_sections.get(idx) or model_sections.get(idx, "")
            if not content and body and idx not in SYSTEM_OWNED:
                # Model ne ye section maanga jaane par bhi nahi diya — jhoothi
                # bharai karne se behtar hai saaf likhna
                content = "_(Reasoning model ne ye section nahi diya.)_"
            if content:
                parts.append(f"## {title}\n{content}")

        if leftover:
            parts.append("## Extra notes (reasoning model se, canonical sections ke bahar)\n"
                         + leftover)
        return "\n\n".join(parts)

    # ── Gemini bilkul available na ho ────────────────────────────────────────
    def extractive_summary(self, question: str, pack: EvidencePack, limit: int = 6) -> str:
        """Zero-Gemini fallback: sources ka honest extract, koi synthesis nahi."""
        if not pack.sources:
            return ("Is sawal par koi source retrieve nahi hua, aur Gemini reasoning bhi "
                    "available nahi thi. Isliye is jawab mein kuch bhi verified nahi hai.")
        lines = [f"## {SECTION_TITLES[0]}",
                 "Gemini synthesis available nahi thi, isliye neeche sirf retrieved "
                 "sources ka seedha extract hai (system ka apna interpretation nahi):", ""]
        for source in pack.sources[:limit]:
            snippet = (source.snippet or "").strip().replace("\n", " ")
            lines.append(f"- **{source.source_id}** {source.title}: {snippet[:300]}")
        return "\n".join(lines)
