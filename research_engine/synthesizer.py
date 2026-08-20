"""
FinalSynthesizer — INSAAN PEHLE, TECHNICAL BAAD MEIN.

Purana format spec ki 14 numbered sections chhaapta tha, aur pehli hi nazar mein
user ko "[FAIL] internal numeric consistency", "Evidence Pack", "Connector
status" jaisa system log dikh jaata tha. intel ka final rule (2026-08-20) isko
palat deta hai:

    "DO NOT MIX INTERNAL RESEARCH LOGS WITH THE MAIN ANSWER.
     HUMAN-FRIENDLY ANSWER FIRST. TECHNICAL DETAILS LAST."

Isliye ab report ka order ye hai:

    Seedha jawab → Research se kya pata chala → Ye kyun hota hai →
    Evidence kya kehta hai → Iske against kya mila → Humari hypotheses →
    Hypothesis ko kaise test karenge → Kya abhi bhi unknown hai →
    Final conclusion → Sources → Research quality / technical audit

Kuch cheezein JAAN-BOOJH KAR waisi hi rahi hain:

  * Jo sections system compute karta hai (hypotheses, sources, audit) unhe model
    replace nahi kar sakta — warna Gemini numbers hallucinate kar sakta hai.
  * Har technical sachchai report se HATAYI nahi gayi, sirf neeche kar di gayi
    hai aur aam bhasha mein likhi gayi hai. PASS/FAIL andar chalta rahega, par
    user ko uska MATLAB dikhega ("Numbers ki checking mein ek problem mili hai...").
  * Jo baat nahi hui, wo saaf likhi jaati hai. "Ye research run complete nahi
    hua" chhupane wali cheez nahi hai.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Union

from .citation import CITATION_INSTRUCTION, CitationEngine
from .claim_labels import LABEL_RULE_PROMPT
from .claim_labels import human_note as label_human_note
from .consensus_gate import CONSENSUS_UNAVAILABLE
from .explain_style import style_block
from .models import EvidencePack
from .requested import prompt_block as requested_prompt_block
from .run_status import split_messages

# §16 ka order — headings mein number NAHI hai, kyunki user ko `## Seedha jawab`
# hi dikhna chahiye. Index hi order hai.
SECTION_TITLES = [
    "Seedha jawab",                          # 0
    "Research se kya pata chala?",           # 1
    "Ye kyun hota hai?",                     # 2
    "Evidence kya kehta hai?",               # 3
    "Iske against kya mila?",                # 4
    "Humari Hypotheses",                     # 5
    "Hypothesis ko kaise test karenge?",     # 6
    "Kya abhi unknown hai?",                 # 7
    "Final conclusion",                      # 8
    "Sources",                               # 9
    "Research quality / technical audit",    # 10
]

# Poore system ke haath mein: model ka version inhe replace nahi karega.
SYSTEM_OWNED = {5, 9, 10}
# Yahan pehle model ki baat, uske BAAD system ka computed hissa jodta hai.
SYSTEM_APPEND = {1, 3, 4, 6, 8}
# Ye sections model se maange jaate hain.
MODEL_SECTIONS = [0, 1, 2, 3, 4, 7, 8]

# Explicitly maangi hui extra sections (requested.py inhi headings ki demand
# karta hai). Ye canonical list ka hissa nahi hain, isliye alag keys.
EXTRA_MATH = "Mathematical Model"
EXTRA_CHAIN = "Second-Order Effects"

# markdown heading (## Seedha jawab / ### Sources / #4 ...)
_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]*\**[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_HEADING_NUM_RE = re.compile(r"^(\d{1,2})\s*[\.\):\-]?\s*(.*)$")

# Naam se pehchano (pehla match jeetta hai — isliye zyada specific phrase pehle).
# Purane English/spec-style naam bhi yahan hain, taaki model ka purana format
# bhi sahi jagah gire aur koi text kabhi na khoye.
_TITLE_HINTS: List[tuple] = [
    ("mathematical model", EXTRA_MATH), ("optimization model", EXTRA_MATH),
    ("optimisation model", EXTRA_MATH), ("math model", EXTRA_MATH),
    ("second-order", EXTRA_CHAIN), ("second order", EXTRA_CHAIN),
    ("effects chain", EXTRA_CHAIN), ("effect chain", EXTRA_CHAIN),

    ("seedha jawab", 0), ("seedha jwab", 0), ("direct answer", 0),
    ("direct conclusion", 0), ("short answer", 0), ("sidha jawab", 0),

    ("kaise test", 6), ("how to test", 6), ("test kaise", 6), ("test plan", 6),
    ("next research", 6), ("next step", 6), ("experiment", 6), ("aage kya", 6),

    ("against hypothes", 4), ("evidence against", 4), ("iske against", 4),
    ("counter-evidence", 4), ("counter evidence", 4), ("khilaf", 4),
    ("conflicting evidence", 4), ("contradict", 4), ("weakness", 4),

    ("humari hypothes", 5), ("new hypothes", 5), ("nayi hypothes", 5),
    ("hypothes", 5),

    ("kya pata chala", 1), ("research se kya", 1), ("established fact", 1),
    ("factual finding", 1), ("key finding", 1), ("findings", 1),
    ("inference", 1),

    ("kyun hota", 2), ("kyun hua", 2), ("ye kyun", 2), ("mechanism", 2),
    ("context", 2), ("cross-disciplinary", 2), ("cross disciplinary", 2),

    ("evidence kya kehta", 3), ("evidence quality", 3), ("strong evidence", 3),
    ("evidence analysis", 3), ("evidence audit", 3), ("source relevance", 3),

    ("unknown", 7), ("abhi bhi kya", 7), ("open question", 7),

    ("final conclusion", 8), ("nishkarsh", 8), ("conclusion", 8),

    ("source", 9), ("citation", 9), ("bibliograph", 9), ("reference", 9),

    ("research quality", 10), ("technical audit", 10), ("audit", 10),
    ("coverage", 10), ("limits", 10), ("honesty", 10), ("verification", 10),
    ("confidence", 10), ("evidence level", 10),
]

# §7 — in teen shabdon ka matlab har report mein ek baar samjhaya jaata hai.
_LABEL_EXPLAINER = (
    "**Neeche teen shabd baar-baar aayenge, unka matlab ye hai:**\n"
    "- **Fact** — jo baat research se already support hoti hai.\n"
    "- **Inference** — jo baat sources ko jodne par logically nikalti hai, "
    "lekin kisi ek source mein seedhe likhi nahi hai.\n"
    "- **Hypothesis** — ek possible idea jo research se nikla hai, lekin abhi "
    "prove nahi hua. Hypotheses neeche alag section mein hain."
)

# §7 — model aksar sirf "### Fact" likh deta hai. Bare label se farak samajh
# nahi aata, isliye heading mein hi uska matlab jod dete hain.
_SUBHEAD_EXPLAIN = {
    "fact": "Fact — jo research se already support hota hai",
    "facts": "Fact — jo research se already support hota hai",
    "inference": "Inference — sources ko jodne par jo logical conclusion nikalta hai",
    "inferences": "Inference — sources ko jodne par jo logical conclusion nikalta hai",
    "hypothesis": "Hypothesis — ek possible idea jo research se nikla hai, lekin abhi "
                  "prove nahi hua",
}

# §9 — contradiction ka matlab samjhana ZAROORI hai, sirf list karna kaafi nahi.
_WHY_DISAGREE = {
    "STANCE": ("Do sources ka rukh alag hai. Aisa aksar tab hota hai jab dono ne "
               "alag jagah, alag population ya alag samay par study ki ho, ya "
               "unka method hi alag ho — isliye dono apne data ke hisaab se "
               "theek ho sakte hain."),
    "NUMERIC": ("Dono ne alag number diya hai. Number alag hone ki aam wajah: "
                "alag city ya sample size, alag measurement method, ya alag "
                "saal ka data. Isliye ek number ko 'sahi' aur doosre ko "
                "'galat' kehna jaldbazi hogi."),
    "RECENCY": ("Purani aur nayi study ka result alag hai. Nayi study ke paas "
                "zyada ya behtar data ho sakta hai, par sirf 'nayi hai' isliye "
                "usko sahi maan lena bhi theek nahi — dekhna padta hai ki data "
                "aur method kaisa tha."),
}


class FinalSynthesizer:
    def __init__(self):
        self.citations = CitationEngine()
        # §10 — pichhle assemble() mein kaun-kaun se section nahi ban paaye.
        # Orchestrator ise ResearchResult mein bhejta hai.
        self.last_missing_sections: List[str] = []

    # ── synthesis prompt — "teacher ki tarah samjhao" ────────────────────────
    def prompt(self, question: str, analysis: str, critique: str, hypothesis_text: str,
               pack: EvidencePack, plan: Dict, memory_note: str = "") -> str:
        critique_block = (f"\nCRITIC KE INTERNAL FINDINGS:\n{critique[:2500]}\n"
                          if critique else "")
        hypothesis_block = (f"\nGENERATED HYPOTHESES (status: UNTESTED):\n"
                            f"{hypothesis_text[:2500]}\n") if hypothesis_text else ""
        memory_block = f"\n{memory_note}\n" if memory_note else ""
        plan = plan or {}
        fields = ", ".join(plan.get("relevant_fields", [])[:4]) or "relevant areas"
        extras = requested_prompt_block(plan.get("requests"))

        return f"""Tum ek bahut acche teacher ho. Tumhara kaam research ka result
aam bhasha mein aise samjhana hai ki padhne wale ko poori baat samajh aa jaye.

SAWAL: {question}

INTERNAL RESEARCH NOTES (ye user ko dikhane ke liye NAHI hain — inhe copy mat
karo, inse samjho aur apne shabdon mein samjhao):
{analysis[:5000]}
{critique_block}{hypothesis_block}{memory_block}
SOURCES (sirf inhi IDs se cite karo):
{pack.to_prompt_block(max_chars_per_source=500)}

{CITATION_INSTRUCTION}

{LABEL_RULE_PROMPT}

{style_block(question, SECTION_TITLES)}

# SABSE ZAROORI RULE — PEHLE INSAAN, BAAD MEIN TECHNICAL
- Apne jawab mein system ka andar ka kaam MAT likho: pipeline, pass, connector,
  evidence pack, source ID list, retrieval, API, quota, "[PASS]", "[FAIL]",
  diagnostics — inme se kuch bhi tumhare text mein nahi aana chahiye. Ye sab
  system khud neeche technical section mein likhega.
- Pehli line se hi kaam ki baat. Bhoomika, "is report mein hum dekhenge",
  "prastut vishleshan" jaisa kuch nahi.
- Har result ko samjhao: kya pata chala, ye kyun hota hai, kya support karta hai,
  kya khilaf jaata hai, iska matlab kya hai, kya limitation hai.
- Jahan madad ho wahan simple example do ("Example se samjho: ...").
- Numbers, uncertainty, methodology aur limitations ko SIMPLE karo — hatao mat.
- Jargon ki jagah matlab likho. "Correlation is not causation" ki jagah:
  "do cheezein saath badh rahi hain, iska matlab ye nahi ki ek doosri ko cause
  kar rahi hai."
- Tumhare paas {len(pack.sources)} sources hain, {pack.independent_source_count} independent origins ke.
  Evidence kamzor ho to pehli line mein hi saaf bol do.
{extras}

Ye sections likho (baaki system khud jodega):

## {SECTION_TITLES[0]}
(3-6 line. Seedha jawab, pehli line mein. Agar pakka jawab nahi ban raha to
saaf likho ki abhi pakka jawab nahi hai aur kyun.)

## {SECTION_TITLES[1]}
(Research se nikli baatein aam bhasha mein. Do sub-headings zaroori hain:
### Fact — jo research se already support hota hai
### Inference — sources ko jodne par jo logical conclusion nikalta hai
Har point ke saath chhota [S#] citation, aur ek line mein uska matlab.)

## {SECTION_TITLES[2]}
(Wajah aur mechanism. {fields} ko aapas mein jodo, par lecture nahi — kaam ki
baat. Jahan ye tumhara logical conclusion hai wahan [INFERENCE] likho.)

## {SECTION_TITLES[3]}
(Evidence kitna majboot hai aur kyun: kitni studies, kis tarah ki, kitna bharosa
kiya ja sakta hai. Ye sab normal bhasha mein — table ya code jaisa nahi.)

## {SECTION_TITLES[4]}
(Jo evidence conclusion ke KHILAF jaata hai, use poore vaakyon mein samjhao.
"Counter-evidence: S7, S12" jaisa likhna manaa hai — batao ki us source ne kya
kaha aur wo alag kyun hai.)

## {SECTION_TITLES[7]}
(Kya abhi bhi pata nahi hai — thos likho. "More research needed" nahi, balki
"X pata nahi hai kyunki ...".)

## {SECTION_TITLES[8]}
(2-5 line ka final conclusion. Jitna evidence hai utna hi dava karo. Agar baat
adhoori hai to yahi likho ki ye preliminary hai.)

Ab jawab likho:"""

    # ── §15: adhoora run chhupana nahi hai ───────────────────────────────────
    def _status_banner(self, pack: EvidencePack, ledger: Optional[Dict] = None,
                       status: Optional[Dict] = None,
                       missing_sections: Optional[List[str]] = None) -> str:
        """
        Sabse pehle dikhne wali imaandaar line — par aam bhasha mein, log ki
        tarah nahi. Agar run poora hua hai to ye khaali rehti hai (bina wajah
        darana bhi theek nahi hai).

        §9: `status` mila ho to uska banner SABSE PEHLE jaata hai (wahi ek line
        hai jo user ko batati hai ki is result ko final answer na maane), aur
        raw API error yahan kabhi nahi aata — wo report ke sabse neeche jaata hai.
        """
        reasons: List[str] = []
        if not pack.sources:
            reasons.append("kisi bhi source se relevant result nahi mila, isliye ye "
                           "jawab sirf model ki general knowledge par hai")
        elif getattr(pack, "full_text_read_count", 0) < 1:
            reasons.append("kisi bhi source ka poora text nahi padha ja saka — sirf "
                           "abstract ya chhota snippet mila, isliye baat 'source ye "
                           "kehta hai' level par hai")
        if not getattr(pack, "reasoning_complete", True):
            try:
                reasons.append(pack.reasoning_note())
            except Exception:                    # noqa: BLE001
                reasons.append("reasoning ke saare step poore nahi ho paaye")
        for item in (ledger or {}).get("unmet", []):
            what = item.get("what", "")
            got = item.get("got", "")
            why = item.get("why", "")
            line = f"aapne jo maanga tha wo poora nahi mila — {what}: **{got}**"
            if why:
                line += f" ({why})"
            reasons.append(line)
        if missing_sections:
            reasons.append("ye hisse is run mein ban hi nahi paaye: "
                           + ", ".join(missing_sections[:6]))

        head = str((status or {}).get("banner") or "").strip()
        code = str((status or {}).get("status") or "").strip()
        # §9 ka doosra taala: banner ke andar RAW API text kabhi nahi. Koi bhi
        # caller galti se protobuf/429 line bhej de to wo yahin chhan jaati hai
        # (uska ghar report ke sabse neeche "Technical details" hai).
        reasons, _dropped = split_messages(reasons)
        if not reasons and not head:
            return ""

        lines: List[str] = []
        if head:
            lines += [f"> ⚠️ **{code or 'RESEARCH INCOMPLETE'}**", ">", f"> {head}"]
        else:
            lines += ["> ⚠️ **Ye research run complete nahi hua.**"]
        if reasons:
            lines.append(">")
            for reason in reasons[:6]:
                lines.append(f"> - {reason}")
        lines += [
            ">",
            "> Isliye neeche diya gaya conclusion **preliminary** hai, fully "
            "verified final conclusion nahi. Poori detail sabse neeche "
            "\"Research quality / technical audit\" mein hai.",
        ]
        return "\n".join(lines)

    # ── §9: contradiction sirf list nahi, uski WAJAH bhi ─────────────────────
    def _contradiction_section(self, contradictions: List[Dict]) -> str:
        if not contradictions:
            return ("Jo sources is run mein mile, unke beech seedha aapsi "
                    "contradiction nahi mila. Iska matlab ye nahi ki poore "
                    "literature mein disagreement nahi hai — ye check sirf inhi "
                    "sources par chala hai.")
        blocks: List[str] = []
        for c in contradictions:
            ids = ", ".join(c.get("sources", []))
            head = c.get("summary", "").strip() or "Do sources aapas mein alag baat kehte hain"
            body = [f"**{head}**" + (f" ({ids})" if ids else "")]
            if c.get("detail"):
                body.append(str(c["detail"]))
            why = _WHY_DISAGREE.get(str(c.get("type", "")).upper())
            if why:
                body.append(f"_Ye farak kyun ho sakta hai:_ {why}")
            else:
                body.append("_Ye farak kyun ho sakta hai:_ aksar wajah alag city, "
                            "alag population, alag samay ya alag method hoti hai — "
                            "isliye ek ko sahi aur doosre ko galat kehna jaldbazi hai.")
            blocks.append("\n\n".join(body))
        blocks.append("_Ye farak automatic tareeke se pakda gaya hai (rule-based), "
                      "isliye khud ek baar dekh lena behtar hai._")
        return "\n\n".join(blocks)

    # ── §6: hypothesis ko bacche ko samjhane wale tarike se likho ────────────
    def _hypothesis_section(self, hypotheses: List[Dict],
                            requests: Optional[Dict] = None,
                            reasons: Optional[List[str]] = None,
                            pack: Optional[EvidencePack] = None) -> str:
        requests = requests or {}
        asked = int(requests.get("hypothesis_count") or 0)
        if not hypotheses:
            # Purani report yahan likhti thi: "nayi hypothesis generate nahi ki
            # gayi (zaroorat nahi thi)". Jab user ne saaf-saaf 3 maangi thi, wo
            # line jhooth thi. Ab dono haalat alag-alag likhi jaati hain.
            if asked or requests.get("wants_hypotheses"):
                why = "; ".join(str(r) for r in (reasons or [])[:3]) \
                    or "wajah record nahi hui"
                target = f"{asked} " if asked else ""
                return (f"❌ Aapne {target}nayi hypotheses maangi thi, lekin is run "
                        f"mein ek bhi poori nahi ban paayi. Ye \"zaroorat nahi thi\" "
                        f"wali baat nahi hai — zaroorat thi.\n\n"
                        f"**Asli wajah:** {why}\n\n"
                        f"Isliye is section ko adhoora maanein. Quota/error theek "
                        f"hone ke baad dobara chalane par ye ban jayengi.")
            return ("Is sawal par nayi hypothesis banane ki zaroorat nahi padi: "
                    "sources ke beech koi khaas disagreement nahi tha aur sawal "
                    "unsolved-research type ka nahi hai. Agar aap chahte hain to "
                    "prompt mein saaf likh dein (jaise \"kam se kam 3 nayi "
                    "hypotheses banao\") — phir ye zaroor banengi.")

        blocks: List[str] = []
        for i, h in enumerate(hypotheses, 1):
            statement = (h.get("statement") or "").strip()
            simple = (h.get("simple") or "").strip()
            title = self._short_title(statement or simple)
            body: List[str] = [f"### Hypothesis {i} — {title}"]
            if simple:
                body.append(f"**Simple words mein:** {simple}")
                if statement and statement.lower() != simple.lower():
                    body.append(f"**Poora statement:** {statement}")
            else:
                body.append(f"**Statement:** {statement}")
                body.append("_(Iska simple-language explanation model ne nahi diya, "
                            "isliye ye technical hi hai.)_")
            if h.get("reasoning"):
                body.append("**Ye idea kahan se aaya:** "
                            + self._join_prose(h["reasoning"]))
            body.append("**Is idea ko support karne wali research:** "
                        + self._evidence_prose(
                            h.get("supporting_evidence"), pack,
                            "abhi koi direct research support list nahi hui — "
                            "yaani ye sirf ek idea hai."))
            body.append("**Iske against evidence:** "
                        + self._evidence_prose(
                            h.get("contradicting_evidence"), pack,
                            "iske khilaf kuch list nahi kiya gaya, matlab "
                            "self-check adhoora raha."))
            if h.get("risks"):
                body.append("**Problem / risk:** " + self._join_prose(h["risks"]))
            if h.get("assumptions"):
                body.append("**Humari assumption:** "
                            + self._join_prose(h["assumptions"]))
            test_bits = []
            if h.get("how_to_test"):
                test_bits.append(self._join_prose(h["how_to_test"]))
            pred_text = self._prediction_text(h)
            if pred_text:
                test_bits.append(f"Agar ye sahi hai to ye dikhna chahiye — {pred_text}")
            if test_bits:
                body.append("**Isko test kaise karenge:** " + " ".join(test_bits))
            if h.get("if_true"):
                body.append("**Agar ye sahi hua:** " + self._join_prose(h["if_true"]))
            if h.get("if_false"):
                body.append("**Agar ye galat hua:** " + self._join_prose(h["if_false"]))
            if h.get("novelty"):
                body.append(f"**Kitna naya hai:** {h['novelty']}")
            if h.get("confidence_reasoning_based"):
                body.append(f"**Kitna bharosa (sirf reasoning par, proof nahi):** "
                            f"{h['confidence_reasoning_based']}")
            body.append(f"**Current status: {h.get('status', 'UNTESTED HYPOTHESIS')}** — "
                        f"abhi real-world test nahi hua.")
            blocks.append("\n\n".join(body))
        if asked and len(hypotheses) < asked:
            blocks.append(f"⚠️ Aapne {asked} maangi thi, {len(hypotheses)} ban paayi — "
                          f"isliye ye list adhoori hai.")
        return "\n\n".join(blocks)

    @staticmethod
    def _short_title(text: str, limit: int = 80) -> str:
        """Hypothesis ka chhota, padhne-layak naam (heading ke liye)."""
        clean = re.sub(r"\s+", " ", (text or "")).strip()
        clean = re.sub(r"\[[^\]]{1,40}\]", "", clean).strip(" .:-")
        if not clean:
            return "naam nahi diya gaya"
        first = re.split(r"(?<=[a-zऀ-ॿ])\.\s", clean)[0]
        return first[:limit].rstrip(" ,.;:") + ("…" if len(first) > limit else "")

    @staticmethod
    def _prediction_text(h: Dict) -> str:
        """
        Prediction ko normal vaakya banao.

        `hypothesis.py` structured prediction ho to dict deta hai
        ({variables, expected_outcome, measurement_method,
        falsification_condition}), warna {"text": ..., "structured": False}.
        Dono ko seedha f-string mein daalna user ko raw dict dikha deta tha —
        wahi §2/§3 ka ulta hai.
        """
        pred = h.get("prediction")
        if isinstance(pred, str):
            return pred.strip()
        if not isinstance(pred, dict):
            return ""
        if pred.get("text"):
            return str(pred["text"]).strip()
        bits: List[str] = []
        variables = [str(v).strip() for v in (pred.get("variables") or []) if str(v).strip()]
        if variables:
            bits.append("Measure kya karna hai: " + ", ".join(variables) + ".")
        if pred.get("expected_outcome"):
            bits.append(f"Kya dikhna chahiye: {pred['expected_outcome']}.")
        if pred.get("measurement_method"):
            bits.append(f"Kaise measure karenge: {pred['measurement_method']}.")
        if pred.get("falsification_condition"):
            bits.append("Kaunsa result isse galat sabit kar dega: "
                        f"{pred['falsification_condition']}.")
        return " ".join(bits)

    # ── §16 item 9: final conclusion ─────────────────────────────────────────
    @staticmethod
    def _join_prose(value, empty: str = "") -> str:
        """
        List/dict/str ko ek padhne-layak line banao.

        Kyun: hypothesis ke `risks`, `assumptions`, `how_to_test`, `if_true`,
        `if_false`, `supporting_evidence` — ye sab LIST hote hain. Inhe seedha
        f-string mein daalne se user ko `['a', 'b']` dikh jaata tha, jo §2/§3
        (insaan ki bhasha) ka seedha ulta hai.
        """
        if value is None:
            return empty
        if isinstance(value, str):
            return re.sub(r"\s+", " ", value).strip() or empty
        if isinstance(value, dict):
            value = [f"{k}: {v}" for k, v in value.items() if str(v).strip()]
        try:
            items = [re.sub(r"\s+", " ", str(v)).strip() for v in value]
        except TypeError:
            items = [re.sub(r"\s+", " ", str(value)).strip()]
        items = [i for i in items if i]
        if not items:
            return empty
        out = []
        for item in items:
            out.append(item if item.endswith((".", "!", "?", ":", ";")) else item + ".")
        return " ".join(out)

    def _evidence_prose(self, ids, pack: Optional[EvidencePack] = None,
                        empty: str = "") -> str:
        """
        §8: evidence ko "S7, S12" ki tarah nahi, source ke naam ke saath poore
        vaakya mein likho. ID bracket mein saath rehti hai, taaki Sources list
        se milaya ja sake.
        """
        if isinstance(ids, str):
            ids = [ids] if ids.strip() else []
        clean = [str(i).strip() for i in (ids or []) if str(i).strip()]
        if not clean:
            return empty
        bits: List[str] = []
        for sid in clean[:6]:
            source = None
            if pack is not None:
                try:
                    source = pack.by_id(sid)
                except Exception:            # noqa: BLE001
                    source = None
            if source is not None and (getattr(source, "title", "") or ""):
                year = f", {source.year}" if getattr(source, "year", None) else ""
                bits.append(f"{self._short_title(source.title, 70)}{year} [{sid}]")
            else:
                bits.append(f"[{sid}]" if not sid.startswith("[") else sid)
        extra = f" (aur {len(clean) - 6} aur)" if len(clean) > 6 else ""
        if len(bits) == 1:
            return f"{bits[0]}{extra}"
        return "; ".join(bits) + extra

    def _conclusion_block(self, evidence_level: str, confidence_note: str,
                          pack: EvidencePack, ledger: Optional[Dict] = None) -> str:
        level = (evidence_level or "").strip()
        plain = {
            "STRONG": "Evidence kaafi mazboot hai — kai sources ek hi baat kehte hain "
                      "aur unmein se kuch ka poora text bhi padha gaya.",
            "MODERATE": "Evidence theek-theek hai — direction saaf hai, par sab kuch "
                        "poori tarah confirm nahi hua.",
            "WEAK": "Evidence kamzor hai — jo mila wo ishara deta hai, saboot nahi.",
            "MIXED": "Evidence mila-jula hai — kuch sources ek taraf jaate hain, kuch "
                     "doosri taraf.",
            "INSUFFICIENT": "Evidence itna kam hai ki iske bharose koi pakka nateeja "
                            "nahi nikala ja sakta.",
            "NONE": "Is sawal par koi kaam ka source hi nahi mila.",
        }.get(level.upper(), "")
        lines: List[str] = []
        if plain:
            lines.append(plain)
        elif level:
            lines.append(f"Evidence ka level: {level}.")
        if confidence_note:
            lines.append(str(confidence_note).strip())
        if not pack.reasoning_complete:
            lines.append("Ek baat saaf rakhni zaroori hai: ye research run poora nahi "
                         "hua, isliye upar ka nateeja **preliminary** hai — final "
                         "verified conclusion nahi.")
        unmet = (ledger or {}).get("unmet") or []
        if unmet:
            names = "; ".join(
                str(u.get("what") if isinstance(u, dict) else u) for u in unmet[:4])
            lines.append("Aapne jo cheezein saaf-saaf maangi thi, unmein se ye poori "
                         f"nahi ho paayi: {names}.")
        if not lines:
            lines.append("Is run se koi bharosemand nateeja nahi nikla.")
        return "\n\n".join(lines)

    @staticmethod
    def _access_block(coverage: Dict, pack: EvidencePack) -> str:
        levels = (coverage or {}).get("read_levels") or {}
        full = int(levels.get("full_text", 0) or 0)
        abstract = int(levels.get("abstract", 0) or 0)
        snippet = int(levels.get("snippet", 0) or 0)
        meta = int(levels.get("metadata", 0) or 0)
        if not (full or abstract or snippet or meta):
            return ("**Kitna gehra padha gaya:** iska data available nahi hai, "
                    "isliye is jawab ko kam bharosemand maanein.")
        lines = ["**Kitna gehra padha gaya (isi se confidence tay hoti hai):**"]
        if full:
            lines.append(f"- {full} source ka POORA text mila. Inpar sabse zyada "
                         f"bharosa kiya ja sakta hai, kyunki claim seedha wahan se "
                         f"check hui hai.")
        if abstract:
            lines.append(f"- {abstract} source ka sirf abstract mila — yaani paper ka "
                         f"summary padha gaya, poora method nahi. Aisi baat "
                         f"\"source ye report karta hai\" level ki hoti hai.")
        if snippet:
            lines.append(f"- {snippet} source se sirf ek chhota snippet mila. Ye "
                         f"ishara deta hai, saboot nahi.")
        if meta:
            lines.append(f"- {meta} source ka sirf title/metadata mila — inse content "
                         f"ki koi guarantee nahi hai.")
        if not full:
            lines.append("- Kisi bhi source ka poora text nahi padha ja saka, isliye is "
                         "report mein koi baat \"humne khud confirm kiya\" level par "
                         "nahi hai.")
        return "\n".join(lines)

    # ── §8 + §9: khilaf wali baat poore vaakyon mein ─────────────────────────
    def _against_section(self, critique: Dict, hypotheses: List[Dict],
                         contradictions: List[Dict],
                         pack: Optional[EvidencePack] = None) -> str:
        parts: List[str] = ["### Research aapas mein kahan alag hai",
                            self._contradiction_section(contradictions)]

        if hypotheses:
            lines = ["### Hypotheses ke khilaf kya mila"]
            for i, h in enumerate(hypotheses, 1):
                against = self._evidence_prose(h.get("contradicting_evidence"), pack)
                title = self._short_title(h.get("statement") or h.get("simple") or "", 60)
                if against:
                    lines.append(f"- **Hypothesis {i} ({title}):** iske khilaf ye mila — "
                                 f"{against}")
                else:
                    lines.append(f"- **Hypothesis {i} ({title}):** iske khilaf koi "
                                 f"evidence list nahi hua. Iska matlab ye NAHI ki "
                                 f"khilaf kuch nahi hai — matlab ye ki khud ki "
                                 f"jaanch adhoori rahi.")
            parts.append("\n".join(lines))

        weakness: List[str] = []
        for item in (critique or {}).get("weaknesses", [])[:6]:
            weakness.append(f"- {self._join_prose(item)}")
        for item in (critique or {}).get("missing_evidence", [])[:4]:
            weakness.append("- Jo evidence hona chahiye tha par mila nahi: "
                            + self._join_prose(item))
        for item in (critique or {}).get("alternative_explanations", [])[:4]:
            weakness.append("- Ek doosri possible explanation: "
                            + self._join_prose(item))
        if not weakness:
            weakness.append("- Is run mein critical review (red-team) pass poora nahi "
                            "chala, isliye ye jawab apni hi jaanch se nahi guzra hai. "
                            "Ise dhyan mein rakhein.")
        parts.append("### Is jawab ki apni kamzoriyan\n" + "\n".join(weakness))
        return "\n\n".join(parts)

    # ── §16 item 7: test kaise karenge ───────────────────────────────────────
    def _test_section(self, hypotheses: List[Dict], verification: Dict) -> str:
        lines: List[str] = []
        if hypotheses:
            lines.append("**Hypothesis-wise test plan:**")
            for i, h in enumerate(hypotheses, 1):
                bits: List[str] = []
                if h.get("how_to_test"):
                    bits.append(self._join_prose(h["how_to_test"]))
                pred_text = self._prediction_text(h)
                if pred_text:
                    bits.append(pred_text)
                if h.get("if_false"):
                    bits.append("Galat hone ka signal: "
                                + self._join_prose(h["if_false"]))
                lines.append(f"- **Hypothesis {i}:** " + (" ".join(bits) or
                             "test ka tarika nahi diya gaya — matlab ise abhi "
                             "test-karne-layak sawal mein badla nahi gaya hai."))
        required = [str(t).strip() for t in (verification or {}).get("required_tests", [])
                    if str(t).strip()]
        if required:
            lines.append("")
            lines.append("**System ke hisaab se ye check hona zaroori hai:**")
            for test in required[:4]:
                lines.append(test if test.startswith(("-", "*", "#")) else f"- {test}")
        if not lines:
            lines.append("Is jawab ke liye koi alag test plan nahi bana, kyunki nayi "
                         "hypothesis is run mein nahi bani.")
        return "\n".join(lines)

    # ── §13 + §14: sources ki imaandaar list ─────────────────────────────────
    _ACCESS_WORDS = {
        "full_text": "FULL-TEXT VERIFIED — poora text padha gaya",
        "abstract": "ABSTRACT REVIEWED — sirf abstract (summary) padha gaya",
        "snippet": "SNIPPET ONLY — sirf ek chhota hissa mila",
        "metadata": "METADATA ONLY — sirf title/details mile, content nahi",
    }
    _KIND_WORDS = {
        "paper": "research paper",
        "web": "web page",
        "book": "kitab",
        "dataset": "dataset (raw numbers)",
        "document": "aapka khud ka uploaded document",
        "video": "video",
        "news": "news article",
    }

    def _sources_section(self, pack: EvidencePack, honesty: Optional[Dict] = None) -> str:
        if not pack.sources:
            return ("Is run mein ek bhi source retrieve nahi hua. Isliye upar likhi "
                    "koi bhi baat kisi source se verify nahi hui hai.")
        cited_raw = (honesty or {}).get("cited") or []
        cited_ids = {c.get("source_id") if isinstance(c, dict) else str(c)
                     for c in cited_raw}
        blocks: List[str] = []
        for s in pack.sources:
            title = (s.title or s.url or "naam nahi mila").strip()
            head = f"**[{s.source_id}] {title}**"
            if s.url:
                head += f"  \n{s.url}"
            about: List[str] = [self._KIND_WORDS.get(
                getattr(s.source_type, "value", str(s.source_type)),
                getattr(s.source_type, "value", "source"))]
            if s.year:
                about.append(f"saal {s.year}")
            if s.publisher or s.venue:
                about.append(str(s.publisher or s.venue))
            if s.peer_reviewed is True:
                about.append("peer-reviewed")
            lines = [head, f"- Ye kya hai: {', '.join(about)}."]
            took = re.sub(r"\s+", " ", (s.snippet or "")).strip()
            if took:
                lines.append("- Isse kya liya gaya: "
                             + took[:220] + ("…" if len(took) > 220 else ""))
            else:
                lines.append("- Isse kya liya gaya: kuch nahi — content mila hi nahi.")
            lines.append(f"- Kitna padha gaya: {self._ACCESS_WORDS.get(s.reading_level(), s.reading_level())}.")
            rel = float(getattr(s, "relevance_score", 0.0) or 0.0)
            rel_word = ("sawal se seedha juda hua" if rel >= 0.6 else
                        "thoda sa juda hua" if rel >= 0.3 else
                        "kam juda hua — ise halke se lein")
            lines.append(f"- Sawal se kitna juda hai: {rel_word} (score {rel:.2f}).")
            if s.retracted is True:
                lines.append("- ⚠️ Is kaam par retraction/withdrawal ka signal hai — "
                             "ise evidence ki tarah nahi lena chahiye.")
            lines.append("- Jawab mein use hua: "
                         + ("haan, cite kiya gaya hai." if s.source_id in cited_ids
                            else "nahi, sirf background mein raha."))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    # ── §11: audit ko insaan ki bhasha mein likho ────────────────────────────
    _CHECK_WORDS = {
        "internal numeric consistency":
            "answer ke andar ke numbers aapas mein match karte hain ya nahi",
        "citation validity":
            "jo sources cite hue, wo sach mein evidence pack mein hain ya nahi",
        "claims grounded in sources":
            "har factual baat ke saath source laga hai ya nahi",
        "cited sources retraction-free":
            "cite kiye gaye kaam mein koi wapas liya gaya (retracted) paper hai ya nahi",
    }
    # Fail hone par label nahi, seedhi problem-wali baat likhni hai (§11 ka
    # GOOD example): "Ek number ki consistency mein problem mili hai..."
    _CHECK_PROBLEM = {
        "internal numeric consistency":
            "Answer ke andar do numbers aapas mein match nahi kar rahe",
        "citation validity":
            "Kuch citations evidence records se match nahi hue",
        "claims grounded in sources":
            "Kuch factual baatein kisi source se judi hui nahi hain",
        "cited sources retraction-free":
            "Cite kiye gaye kaam mein retraction ka signal mila",
    }
    _STATUS_WORDS = {
        "MATH ERROR FOUND": "Ek calculation galat nikli — detail neeche hai.",
        "REQUIRES PHYSICAL TEST": "Iska poora jawab computer par check nahi ho sakta; "
                                  "iske liye asli lab ya field test chahiye.",
        "COMPUTATIONALLY VERIFIED": "Jo bhi computer par check hona possible tha, "
                                    "wo sab check ho gaya.",
        "COMPUTATIONALLY VERIFIED (partial)": "Kuch cheezein computer par check ho gayi, "
                                              "kuch reh gayi.",
        "SOURCE GROUNDED": "Baatein sources se judi hain, par calculation-level "
                           "checking possible nahi thi.",
        "LOGICALLY CONSISTENT": "Jawab andar se aapas mein consistent hai, lekin asli "
                                "test se verify nahi hua.",
        "UNVERIFIABLE HERE": "Is jawab ko yahan verify karne ka koi seedha tarika "
                             "nahi tha.",
    }

    def _numbers_check(self, verification: Dict) -> str:
        verification = verification or {}
        checks = [c for c in verification.get("checks", []) if isinstance(c, dict)]
        failed = [c for c in checks if c.get("passed") is False]
        passed = [c for c in checks if c.get("passed") is True]
        unknown = [c for c in checks if c.get("passed") is None]
        lines: List[str] = []
        status = str(verification.get("status") or "").strip()
        if status:
            lines.append(self._STATUS_WORDS.get(status, f"Verification status: {status}."))
        if failed:
            lines.append("")
            word = "cheez" if len(failed) == 1 else "cheezein"
            lines.append(f"**{len(failed)} {word} mein problem mili hai:**")
            for c in failed[:6]:
                name = str(c.get("check") or "")
                head = self._CHECK_PROBLEM.get(
                    name, f"Is check mein problem mili — {self._CHECK_WORDS.get(name, name)}")
                detail = re.sub(r"\s+", " ", str(c.get("detail") or "")).strip().rstrip(".")
                if detail:
                    lines.append(f"- {head}: {detail}. Isse ek baar source se khud "
                                 f"milaa lena behtar hai.")
                else:
                    lines.append(f"- {head}. Detail record nahi hui.")
        if passed:
            names = ", ".join(self._CHECK_WORDS.get(str(c.get("check")), str(c.get("check")))
                              for c in passed[:4])
            lines.append("")
            lines.append(f"**{len(passed)} check theek nikle**, jaise: {names}.")
        if unknown:
            lines.append("")
            lines.append(f"**{len(unknown)} cheez check hi nahi ho paayi** — "
                         "yaani uske baare mein hum na haan keh sakte hain na naa.")
        if not checks:
            lines.append("Is jawab mein aisa kuch nahi tha jise numbers ke level par "
                         "check kiya ja sakta — isliye ye checking nahi hui.")
        for warn in verification.get("warnings", [])[:4]:
            lines.append(f"- ⚠️ {warn}")

        # Spec §11 — ye do block §16 restructure ke baad render hona band ho gaye
        # the (compute to ho rahe the, dikh nahi rahe the). Wapas laaye gaye hain,
        # par ab insaan ki bhasha mein.
        stats = verification.get("statistics") or {}
        stat_note = str(stats.get("note") or "").strip()
        if stat_note:
            lines.append("")
            lines.append(f"**Statistics in sources:** {stat_note}")
            markers = {k: v for k, v in (stats.get("markers_found") or {}).items()
                       if v}
            if markers:
                lines.append("- Jo dikha: "
                             + ", ".join(f"{k.replace('_', ' ')} ({v} source)"
                                         for k, v in markers.items()) + ".")
        datasets = [str(d).strip() for d in
                    (verification.get("data_for_verification") or []) if str(d).strip()]
        if datasets:
            lines.append("")
            lines.append("**Khud check karne ke liye available data** (system ne inhe "
                         "verify nahi kiya, sirf raasta diya hai):")
            lines.extend(f"- {d}" for d in datasets[:6])
        return "\n".join(lines).strip()

    # ── coverage: "kitna kaam asli mein hua" ─────────────────────────────────
    @staticmethod
    def _reading_line(coverage: Dict) -> str:
        reading = (coverage or {}).get("reading") or {}
        if not reading:
            return ""
        got = int(reading.get("succeeded", 0) or 0)
        tried = int(reading.get("attempted", 0) or 0)
        failed = int(reading.get("failed", 0) or 0)
        skipped = int(reading.get("skipped_over_budget", 0) or 0)
        chars = int(reading.get("chars_read", 0) or 0)
        bits = [f"- Full text kholne ki koshish {tried} source par hui, "
                f"kaamyab {got} par."]
        if failed:
            bits.append(f"- {failed} par text nahi mila (paywall, PDF fail, ya site "
                        f"ne block kiya).")
        if skipped:
            bits.append(f"- {skipped} source time/budget ki wajah se chhod diye gaye.")
        if chars:
            bits.append(f"- Kul milakar {chars:,} characters ka text asli mein process hua.")
        return "\n".join(bits)

    @staticmethod
    def _count(value) -> int:
        """Coverage se int ya list — dono se ginti nikaalo, crash bina."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, (list, tuple, set, dict)):
            return len(value)
        try:
            return int(str(value).strip() or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _quality_line(coverage: Dict, pack: EvidencePack) -> str:
        bits: List[str] = []
        count = FinalSynthesizer._count
        peer = count((coverage or {}).get("peer_reviewed", 0))
        if peer:
            bits.append(f"- {peer} source peer-reviewed hai (yaani doosre "
                        f"researchers ne use check kiya tha).")
        strong = count((coverage or {}).get("strong_methodology_sources", 0))
        if strong:
            bits.append(f"- {strong} source ka study design mazboot hai "
                        f"(review/trial jaisa).")
        retracted = count((coverage or {}).get("retracted_sources", 0))
        if retracted:
            bits.append(f"- ⚠️ {retracted} source par retraction ka signal hai.")
        note = pack.quality_signal_note() if pack else ""
        if note:
            bits.append(f"- {note}")
        return "\n".join(bits)

    def _coverage_section(self, coverage: Dict, pack: EvidencePack,
                          discovery_note: str = "") -> str:
        coverage = coverage or {}
        lines = [
            f"- {coverage.get('candidates_discovered', 0)} possible sources dekhe gaye, "
            f"unmein se {coverage.get('sources_used', 0)} kaam ke nikle.",
            f"- Inmein {coverage.get('independent_sources', 0)} alag-alag origin ke hain "
            f"— yaani ek hi jagah ki copies ko humne alag evidence nahi gina.",
            f"- Search ke {coverage.get('research_rounds', 0)} round chale.",
        ]
        connectors = coverage.get("connectors_searched") or []
        if isinstance(connectors, (str, int)):     # defensive: kabhi count aa jaye
            connectors = [connectors]
        if connectors:
            lines.append(f"- Kahan-kahan dhoonda: {', '.join(str(c) for c in connectors)}.")
        by_type = coverage.get("by_source_type") or {}
        if by_type:
            pretty = ", ".join(f"{self._KIND_WORDS.get(k, k)}: {v}"
                              for k, v in by_type.items())
            lines.append(f"- Kis tarah ke sources: {pretty}.")
        if discovery_note:
            lines.append(f"- {discovery_note}")
        table = coverage.get("evidence_table") or {}
        if table.get("total_claims"):
            lines.append(f"- Jawab ki {table['total_claims']} claims mein se "
                         f"{table.get('grounded_claims', 0)} par source laga hua hai.")
        for extra in (self._reading_line(coverage), self._quality_line(coverage, pack)):
            if extra:
                lines.append(extra)
        return "\n".join(lines)

    # ── "aapne jo maanga tha" ka honest hisaab ───────────────────────────────
    @staticmethod
    def _ledger_block(ledger: Optional[Dict]) -> str:
        ledger = ledger or {}
        if not ledger.get("any_requested"):
            return ""
        lines = [str(line) for line in (ledger.get("lines") or []) if str(line).strip()]
        if not lines:
            return ""
        return ("Aapne prompt mein jo cheezein saaf-saaf maangi thi, unka seedha "
                "hisaab:\n" + "\n".join(lines))

    _CONSENSUS_WORDS = {
        "APPARENT CONSENSUS": "Jitne sources mile, unmein aapas mein sehmati dikhti hai "
                              "(ye poore literature ka survey nahi hai, sirf inhi "
                              "sources ki baat hai).",
        "DISPUTED": "Sources aapas mein sehmat nahi hain — kuch ek taraf hain, kuch "
                    "doosri taraf.",
        "LEANING": "Sources ek taraf jhukte hain, par ye pakki sehmati nahi hai.",
        "NO CLEAR STANCE": "Sources ne is sawal par koi saaf position hi nahi li.",
    }

    def _audit_section(self, pack: EvidencePack, verification: Dict, coverage: Dict,
                       honesty: Optional[Dict] = None, consensus: Optional[Dict] = None,
                       discovery_note: str = "", quota_note: str = "",
                       warnings: Optional[List[str]] = None,
                       ledger: Optional[Dict] = None,
                       label_report: Optional[Dict] = None,
                       notes: Optional[List[str]] = None,
                       usage_note: str = "",
                       status: Optional[Dict] = None,
                       technical_details: Optional[List[str]] = None,
                       api_accounting: Optional[Dict] = None,
                       missing_sections: Optional[List[str]] = None) -> str:
        blocks: List[str] = []
        numbers = self._numbers_check(verification)
        if numbers:
            blocks.append("### Numbers ki checking\n" + numbers)

        source_bits: List[str] = []
        summary = (honesty or {}).get("summary") or ""
        if summary:
            source_bits.append(str(summary).strip())
        level = str((consensus or {}).get("level") or "").strip()
        if level:
            # §11 — gate fail hua to level ki jagah wahi ek vaakya jaata hai, aur
            # neeche shartein. "Sehmati ka level: Consensus evaluate nahi kiya ja
            # saka." jaisa bewakoofi wala vaakya nahi banna chahiye.
            if level == CONSENSUS_UNAVAILABLE or level.lower().startswith(
                    "consensus evaluate nahi"):
                bits = [CONSENSUS_UNAVAILABLE]
                unmet = [str(u).strip() for u in
                         ((consensus or {}).get("unmet_conditions") or [])
                         if str(u or "").strip()]
                if unmet:
                    bits.append("Ye shartein poori nahi hui:\n"
                                + "\n".join(f"- {u}" for u in unmet[:6]))
                bits.append("Retrieved links ka dher scientific consensus nahi "
                            "hota, isliye koi sehmati-level nahi banaya gaya.")
                source_bits.append("\n\n".join(bits))
            else:
                source_bits.append(self._CONSENSUS_WORDS.get(
                    level.upper(),
                    f"Sources ke beech sehmati ka level: {level} — yaani ye baat sirf "
                    f"inhi sources par tiki hai, poore literature par nahi."))
        consensus_note = str((consensus or {}).get("note") or "").strip()
        if consensus_note and not str(
                (consensus or {}).get("level") or "").strip().lower().startswith(
                    "consensus evaluate nahi"):
            source_bits.append(consensus_note)
        independence = (coverage or {}).get("independence") or {}
        repeated = independence.get("repeated_origins") or {}
        if repeated:
            source_bits.append(f"{len(repeated)} jagah aisi hai jahan se ek se zyada "
                               f"source aaye — unhe alag-alag saboot nahi maana gaya.")
        if source_bits:
            blocks.append("### Sources ki checking\n" + "\n\n".join(source_bits))

        coverage_text = self._coverage_section(coverage, pack, discovery_note)
        if coverage_text:
            blocks.append("### Kitna kaam asli mein hua\n" + coverage_text)

        # NOTE: "kitna gehra padha gaya" (§14) audit mein nahi, section 3
        # ("Evidence kya kehta hai?") mein jaata hai — kyunki wo confidence ki
        # baat hai aur user ko pehle samajh aani chahiye, technical tail mein
        # dabani nahi chahiye.
        ledger_text = self._ledger_block(ledger)
        if ledger_text:
            blocks.append("### Aapne jo maanga tha, uska hisaab\n" + ledger_text)

        ai_bits: List[str] = []
        try:
            reasoning_note = pack.reasoning_note()
        except Exception:                        # noqa: BLE001
            reasoning_note = ""
        if reasoning_note:
            ai_bits.append(f"- {reasoning_note}")
        code = str((status or {}).get("status") or "").strip()
        if code:
            ai_bits.append(f"- Is run ka status: **{code}**"
                           + (f" — {(status or {}).get('reason')}"
                              if (status or {}).get("reason") else ""))
        if quota_note:
            ai_bits.append(f"- {quota_note}")
        if usage_note:
            ai_bits.append(f"- {usage_note}")
        for note in (notes or [])[:5]:
            ai_bits.append(f"- {note}")
        label_note = label_human_note(label_report) if label_report else ""
        if label_note:
            ai_bits.append(f"- {label_note}")
        if ai_bits:
            blocks.append("### Reasoning (AI) passes ka sach\n" + "\n".join(ai_bits))

        # §14 — API ka hisaab bilkul saaf: logical pass vs asli HTTP attempts.
        acc_text = self._api_accounting_block(api_accounting)
        if acc_text:
            blocks.append("### API calls ka asli hisaab\n" + acc_text)

        # §10 — jo section ban hi nahi paayi, uska naam ek jagah (khaali heading
        # chhapne se behtar hai naam gin kar bata dena)
        if missing_sections:
            blocks.append("### Kaunse hisse nahi ban paaye\n"
                          + "\n".join(f"- {s}" for s in missing_sections[:11])
                          + "\n\nInke liye reasoning model ka output nahi mila, "
                            "isliye khaali heading chhapne ki jagah unhe hata "
                            "diya gaya.")

        # §9 — warning bhi insaani bhasha mein. Jo line technical hai wo yahan
        # se nikal kar sabse neeche "technical details" mein chali jaati hai.
        raw_warnings = [str(w).strip() for w in (warnings or []) if str(w).strip()]
        human_warnings, tech_from_warnings = split_messages(raw_warnings)
        if human_warnings:
            blocks.append("### Baaki warnings\n"
                          + "\n".join(f"- ⚠️ {w}" for w in human_warnings[:10]))

        limits = (verification or {}).get("limits") or []
        note = (verification or {}).get("note") or ""
        tail: List[str] = [f"- {l}" for l in limits[:4]]
        if note:
            tail.append(f"- {note}")
        # Ye teen line HAMESHA jaati hain. Purane version mein bhi thi, aur inhe
        # hataana seedha jhooth ban jaata: system ki asli seema yahi hai.
        tail += [
            "- Karodon books ya paywalled papers ka poora text nahi padha gaya — "
            "system ne un tak search kiya, unhe padha nahi.",
            "- Paywalled/copyrighted content bypass nahi kiya gaya.",
            "- Study design aur retraction ka pata metadata se chala hai (publication "
            "type, PubMed pubtype, Crossref flags) — har paper ka methods section "
            "padh kar nahi. Retraction ka signal na milna 'retracted nahi hai' ka "
            "saboot nahi hai.",
            "- Reasoning ke alag-alag passes ek hi AI model ne kiye hain. Inhe "
            "independent human experts ki review ki tarah nahi lena chahiye — asli "
            "verification sources se hoti hai, roles se nahi.",
        ]
        blocks.append("### Is checking ki apni limits\n" + "\n".join(tail))

        # ── SABSE NEECHE: raw technical detail (§9) ───────────────────────────
        # Ye jaan-boojh kar report ka aakhri block hai. Pehle ye protobuf/429
        # text seedha "Seedha jawab" ke neeche chhap raha tha, jo user ke liye
        # bekaar aur darane wala tha.
        tech_lines: List[str] = []
        for line in list(technical_details or []) + list(tech_from_warnings):
            clean = " ".join(str(line or "").split())
            if clean and clean not in tech_lines:
                tech_lines.append(clean)
        for line in (status or {}).get("technical_details", []) or []:
            clean = " ".join(str(line or "").split())
            if clean and clean not in tech_lines:
                tech_lines.append(clean)
        if tech_lines:
            blocks.append("### Technical details (developer ke liye — user ke jawab "
                          "ka hissa nahi)\n"
                          + "\n".join(f"- `{l[:300]}`" for l in tech_lines[:8]))

        return "\n\n".join(blocks) if blocks else (
            "Is run ka koi technical record available nahi hai.")

    # ── §14: API ka hisaab (andaaza nahi, ginti) ─────────────────────────────
    @staticmethod
    def _api_accounting_block(accounting: Optional[Dict]) -> str:
        if not accounting:
            return ""
        acc = dict(accounting)
        rows = [
            ("Reasoning pass (logical calls)",
             f"{acc.get('logical_reasoning_calls', 0)}/{acc.get('budget', 0)}"),
            ("Asli HTTP attempts", acc.get("actual_http_attempts", 0)),
            ("Safal calls", acc.get("successful_calls", 0)),
            ("Fail attempts", acc.get("failed_attempts", 0)),
            ("Retry", acc.get("retries", 0)),
        ]
        lines = [f"- {label}: **{value}**" for label, value in rows]
        tried = acc.get("models_tried") or []
        if tried:
            lines.append(f"- Model try kiye gaye: {', '.join(str(t) for t in tried)}")
        blocked = acc.get("blocked_models") or {}
        if blocked:
            lines.append("- Is run mein band kiye gaye model: "
                         + ", ".join(f"{n} ({k})" for n, k in sorted(blocked.items())))
        summary = str(acc.get("failure_summary") or "").strip()
        if summary:
            lines.append(f"- Failure ka hisaab: {summary}")
        if acc.get("stopped_early"):
            lines.append("- API key/permission fail hone ke baad aage koshish nahi ki gayi.")
        return "\n".join(lines)

    # ── model ke output ko sections mein baanto ──────────────────────────────
    @staticmethod
    def _section_index(title: str) -> Optional[Union[int, str]]:
        """
        Heading ka naam padh kar batao wo kaunsi section hai.

        PEHLE naam dekhte hain, BAAD mein number. Purana code ulta karta tha,
        aur ab headings mein number hi nahi hai — to number-first rehne par
        model ka "## 1. Seedha jawab" jaisa purana format galat jagah girta.
        """
        raw = (title or "").strip().strip("*_# ").strip()
        if not raw:
            return None
        low = raw.lower()
        for hint, index in _TITLE_HINTS:
            if hint in low:
                return index
        match = _HEADING_NUM_RE.match(raw)
        if match:
            rest = (match.group(2) or "").lower()
            for hint, index in _TITLE_HINTS:
                if hint in rest:
                    return index
            number = int(match.group(1))
            if 1 <= number <= len(SECTION_TITLES):
                return number - 1
        return None

    def split_model_sections(self, text: str) -> tuple:
        """
        Model ke text ko `{index_or_key: content}` aur `leftover` mein todo.

        Leftover kabhi phenka nahi jaata — assemble() use "Extra notes" ke neeche
        rakh deta hai. Ye jaan-boojh kar hai: model kabhi bahut kaam ki baat bina
        heading ke likh deta hai, aur use chup-chaap gira dena content chori hai.
        """
        found: Dict[Union[int, str], str] = {}
        if not (text or "").strip():
            return found, ""
        matches = list(_HEADING_RE.finditer(text))
        if not matches:
            return found, text.strip()
        leftover_parts: List[str] = []
        head = text[:matches[0].start()].strip()
        if head:
            leftover_parts.append(head)

        # Model kabhi `##` se sections likhta hai, kabhi `###` se. Jis level par
        # canonical sections mile, wahi "main level" hai; usse gehri headings
        # (jaise `### Fact` / `### Inference`) section ke ANDAR ki hain — unhe
        # alag section maan lena §7 ka farak mita deta tha.
        levels = [(len(m.group(1)), self._section_index(m.group(2).strip()))
                  for m in matches]
        main_level = min([lvl for lvl, key in levels if key is not None] or [2])

        current: Optional[Union[int, str]] = None
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            level = len(match.group(1))
            title = match.group(2).strip()
            body = text[match.end():end].strip()
            key = self._section_index(title)

            if level > main_level and current is not None:
                # §7: khaali "Fact"/"Inference"/"Hypothesis" label kaafi nahi —
                # heading mein hi uska matlab likha jaata hai.
                nice = _SUBHEAD_EXPLAIN.get(title.strip().strip(":—- ").lower(), title)
                piece = f"### {nice}" + (f"\n{body}" if body else "")
                found[current] = f"{found.get(current, '')}\n\n{piece}".strip()
                continue
            if key is None:
                if body:
                    leftover_parts.append(f"**{title}**\n{body}")
                continue
            current = key
            if not body:
                found.setdefault(key, "")
                continue
            if found.get(key):
                found[key] = f"{found[key]}\n\n{body}"
            else:
                found[key] = body
        return found, "\n\n".join(leftover_parts).strip()

    # ── final report ─────────────────────────────────────────────────────────
    _MISSING = "_(Reasoning model ne ye section nahi diya.)_"
    # §10 — sirf explainer/boilerplate wali section ko "bhari hui" nahi maanenge.
    # Section 1 ke saath sirf label ka matlab samjhane wala block aata hai; wo
    # content nahi hai, isliye model text na ho to poori section chhod dete hain.
    _EXPLAINER_ONLY = {1}

    def assemble(self, gemini_answer: str, pack: EvidencePack, evidence_level: str,
                 confidence_note: str, contradictions: List[Dict],
                 hypotheses: List[Dict], verification: Dict, coverage: Dict,
                 honesty: Dict, consensus: Dict, discovery_note: str = "",
                 quota_note: str = "", critique: Optional[Dict] = None,
                 warnings: Optional[List[str]] = None,
                 ledger: Optional[Dict] = None,
                 label_report: Optional[Dict] = None,
                 notes: Optional[List[str]] = None,
                 usage_note: str = "",
                 requests: Optional[Dict] = None,
                 status: Optional[Dict] = None,
                 technical_details: Optional[List[str]] = None,
                 api_accounting: Optional[Dict] = None) -> str:
        """
        Poori report banao — INSAAN PEHLE, TECHNICAL BAAD MEIN.

        Naye parameters (ledger, label_report, notes, usage_note, requests,
        status, technical_details, api_accounting) sab optional hain, taaki
        purane callers bina badle chalte rahein.

        §10: jis section mein na model ka text hai, na system ka computed
        content — wo section CHHAP HI NAHI hoti. Uska naam ek jagah (top banner
        + audit) saaf likh diya jaata hai. Pehle wahan khaali heading aur
        "_(Reasoning model ne ye section nahi diya.)_" chhapta tha, jisse report
        bhari hui lagti thi par kuch batati nahi thi.
        """
        found, leftover = self.split_model_sections(gemini_answer or "")
        reasons = [str(n) for n in (notes or [])]
        try:
            if not pack.reasoning_complete:
                reasons.insert(0, pack.reasoning_note())
        except Exception:                        # noqa: BLE001
            pass
        for item in (ledger or {}).get("unmet", []):
            if isinstance(item, dict) and item.get("why"):
                reasons.append(str(item["why"]))

        # ── pehle har section ka content banao, phir decide karo kya chhapega ──
        bodies: Dict[int, List[str]] = {}
        missing_sections: List[str] = []
        for index, title in enumerate(SECTION_TITLES):
            model_text = str(found.get(index, "") or "").strip()
            parts: List[str] = []
            engine_text = ""

            if index == 0:
                parts.append(model_text or (
                    "Is sawal ka pakka jawab is run se nahi nikla. Neeche jo mila wo "
                    "hai, aur jo nahi mil paaya wo bhi saaf likha hai."))
            elif index == 5:
                engine_text = self._hypothesis_section(hypotheses, requests,
                                                       reasons, pack)
                parts.append(engine_text)
            elif index == 9:
                engine_text = self._sources_section(pack, honesty)
                parts.append(engine_text)
            elif index == 10:
                engine_text = self._audit_section(
                    pack=pack, verification=verification, coverage=coverage,
                    honesty=honesty, consensus=consensus,
                    discovery_note=discovery_note, quota_note=quota_note,
                    warnings=warnings, ledger=ledger, label_report=label_report,
                    notes=notes, usage_note=usage_note, status=status,
                    technical_details=technical_details,
                    api_accounting=api_accounting,
                    missing_sections=missing_sections)
                parts.append(engine_text)
            else:
                if index == 1:
                    engine_text = _LABEL_EXPLAINER
                elif index == 3:
                    engine_text = self._access_block(coverage, pack)
                elif index == 4:
                    engine_text = self._against_section(critique or {}, hypotheses,
                                                        contradictions)
                elif index == 6:
                    engine_text = self._test_section(hypotheses, verification)
                elif index == 8:
                    engine_text = self._conclusion_block(evidence_level,
                                                         confidence_note, pack, ledger)
                # §10: model ne kuch nahi diya aur system ka bhi asli content
                # nahi hai -> section hi mat banao (naam neeche list ho jaayega)
                usable_engine = (str(engine_text or "").strip()
                                 and index not in self._EXPLAINER_ONLY)
                if not model_text and not usable_engine:
                    missing_sections.append(title)
                    continue
                if model_text:
                    parts.append(model_text)
                if str(engine_text or "").strip():
                    parts.append(engine_text)

            bodies[index] = [p for p in parts if str(p).strip()]

        # ── ab asli output ────────────────────────────────────────────────────
        # §10 ke saath ek khatra aaya: pehle extra sections (math model /
        # second-order chain) aur model ka bina-heading text section 2 aur 8 ke
        # "andar" chhapte the. Agar wahi section skip ho jaaye to ye content
        # CHUP-CHAAP GAYAB ho jaata — aur "content kabhi delete nahi hota" is
        # project ka pakka niyam hai. Isliye anchor wo section hai jo SACH MEIN
        # chhap raha hai (uske aas-paas ka sabse kareebi).
        printed = sorted(bodies)
        first = printed[0] if printed else 0
        extras_after = max([i for i in printed if i <= 2], default=first)
        leftover_after = max([i for i in printed if i <= 8], default=extras_after)

        out: List[str] = []
        for index, title in enumerate(SECTION_TITLES):
            if index not in bodies:
                continue
            out.append(f"## {title}")
            if index == 0:
                banner = self._status_banner(pack, ledger, status, missing_sections)
                if banner:
                    out.append(banner)
            out.extend(bodies[index])

            # Explicitly maangi hui extra sections — "Ye kyun hota hai?" ke turant
            # baad, taaki wo main answer ka hissa lagein, technical tail ka nahi.
            if index == extras_after:
                for key, heading in ((EXTRA_MATH, "Mathematical model — simple "
                                                  "shabdon mein"),
                                     (EXTRA_CHAIN, "Ek cheez se doosri cheez tak ka "
                                                   "asar (second-order effects)")):
                    body = str(found.get(key, "") or "").strip()
                    if body:
                        out.append(f"## {heading}")
                        out.append(body)

            # Model ka bina-heading likha text kabhi delete nahi hota.
            if index == leftover_after and leftover:
                out.append("## Extra notes (model se, canonical sections ke bahar)")
                out.append(leftover)

        # Caller (orchestrator) ko bhi chahiye — API/UI mein `missing_sections`
        # structured roop mein jaata hai, taaki frontend ko text parse na karna pade.
        self.last_missing_sections = list(missing_sections)
        return "\n\n".join(part for part in out if str(part).strip())

    # ── Gemini bilkul na chale to bhi kuch dena hai ──────────────────────────
    def extractive_summary(self, question: str, pack: EvidencePack,
                           max_sources: int = 6) -> str:
        """
        Zero-Gemini fallback: sources ke apne shabd, bina kisi naye claim ke.

        Ye jaan-boojh kar "summary" hai, "answer" nahi — jab reasoning model hi
        na chala ho, to jawab banane ka koi imaandaar tarika nahi bachta.
        """
        if not pack.sources:
            return ("## Seedha jawab\n\nIs sawal par koi source nahi mila aur reasoning "
                    "model bhi nahi chala, isliye is waqt koi bharosemand jawab nahi "
                    "diya ja sakta.")
        lines = [
            "## Seedha jawab",
            "",
            "Reasoning model is run mein nahi chala, isliye neeche jo hai wo humara "
            "banaya hua jawab NAHI hai — ye seedha sources ke apne shabd hain. "
            f"Sawal tha: {question}",
            "",
            "### Sources ne khud kya kaha",
        ]
        for source in pack.sources[:max_sources]:
            text = re.sub(r"\s+", " ", (source.snippet or "")).strip()
            if not text:
                continue
            head = f"**[{source.source_id}] {source.title or source.url}**"
            lines.append(f"{head}  \n{text[:300]}{'…' if len(text) > 300 else ''}  \n"
                         f"_{self._ACCESS_WORDS.get(source.reading_level(), source.reading_level())}_")
        lines.append("")
        lines.append("Inhe jodkar koi conclusion humne nahi nikala — wo kaam reasoning "
                     "pass ka tha, jo is baar poora nahi hua.")
        return "\n\n".join(lines)

