"""
FinalSynthesizer — INSAAN PEHLE, TECHNICAL BAAD MEIN.

Purana format spec ki 14 numbered sections chhaapta tha, aur pehli hi nazar mein
user ko "[FAIL] internal numeric consistency", "Evidence Pack", "Connector
status" jaisa system log dikh jaata tha. intel ka final rule (2026-08-20) isko
palat deta hai:

    "DO NOT MIX INTERNAL RESEARCH LOGS WITH THE MAIN ANSWER.
     HUMAN-FRIENDLY ANSWER FIRST. TECHNICAL DETAILS LAST."

Isliye ab report ka order ye hai (§12 ka mandatory order, 2026-08-22):

    Seedha jawab → Established knowledge → Ye kyun hota hai →
    Supporting evidence → Counterevidence → Calculations → Unknowns →
    Evidence-based conclusion → APP ORIGINAL RESEARCH LAB (app ki apni
    hypotheses + unka test plan, saaf warning ke saath) →
    Audit and limits → Sources

Do cheezein yahan jaan-boojh kar badli gayi hain (dark-matter run ki dikkat):
app ki apni hypotheses pehle evidence ke BEECH mein chhapti thi (padhne wale ko
lagta tha ki wo bhi research ka nateeja hai), aur Sources audit se pehle aata
tha. Ab hypotheses conclusion ke baad ek alag naam wale section mein hain, aur
Sources sabse aakhir mein.

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
from typing import Dict, List, Optional, Tuple, Union

from .answer_order import LAB_HEADING as ANSWER_LAB_HEADING
from .answer_order import LAB_WARNING, NO_CALC_REASONS, display_heading
from .citation import CITATION_INSTRUCTION, CitationEngine
from .claim_labels import LABEL_RULE_PROMPT
from .claim_labels import human_note as label_human_note
from .consensus_gate import CONSENSUS_UNAVAILABLE
from .explain_style import style_block
from .lab import lab_limits, lab_report_section
from .craft import craft_limits, craft_section
from .rejects import reject_limits, reject_section
from .models import EvidencePack
from .requested import prompt_block as requested_prompt_block
from .run_status import split_messages
from .specialist_domains import prompt_block as specialist_prompt_block

# §12 (2026-08-22) — headings ab DO baat kehti hain: pehle contract ka canonical
# naam, phir "—" ke baad wahi baat aasaan Hinglish mein. Isse do purani dikkatein
# ek saath khatam hoti hain: (a) `sections poore hain?` wala contract check
# canonical naam dhoondhta tha aur hamesha fail hota tha, (b) user ko English
# jargon-only heading samajh nahi aati thi. Index sirf section ki pehchan hai —
# chhapne ka kram `EMIT_ORDER` tay karta hai (§12 ka mandatory order).
SECTION_TITLES = [
    display_heading("direct_answer"),                     # 0
    display_heading("established_knowledge"),             # 1
    "Ye kyun hota hai?",                                  # 2 (extra, §12 ke bahar)
    display_heading("supporting_evidence"),               # 3
    display_heading("counterevidence"),                   # 4
    ANSWER_LAB_HEADING,                                   # 5 (§12: bilkul yahi shabd)
    "Hypothesis ko kaise test karenge?",                  # 6 (extra, LAB ke andar ki baat)
    display_heading("unknowns"),                          # 7
    display_heading("conclusion"),                        # 8
    display_heading("sources"),                           # 9
    display_heading("audit"),                             # 10
]
# §12 — Calculations ki heading bhi wahi jagah se aati hai, aur ye section HAMESHA
# chhapta hai (na bane to WAJAH ke saath).
CALC_HEADING = display_heading("calculations")

# §12 ka mandatory order: ... counterevidence → Calculations → Unknowns →
# conclusion → APP ORIGINAL RESEARCH LAB → Audit and limits → Sources.
# Pehle app ki apni hypotheses (5) evidence ke BEECH mein chhapti thi aur Sources
# audit se pehle aata tha — dono §12 se ulte the.
EMIT_ORDER: Tuple[int, ...] = (0, 1, 2, 3, 4, 7, 8, 5, 6, 10, 9)


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

    ("humari hypothes", 5), ("app original research lab", 5),
    ("original research lab", 5), ("new hypothes", 5), ("nayi hypothes", 5),
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
               pack: EvidencePack, plan: Dict, memory_note: str = "",
               evidence_first_block: str = "") -> str:
        critique_block = (f"\nCRITIC KE INTERNAL FINDINGS:\n{critique[:2500]}\n"
                          if critique else "")
        hypothesis_block = (f"\nGENERATED HYPOTHESES (status: UNTESTED):\n"
                            f"{hypothesis_text[:2500]}\n") if hypothesis_text else ""
        memory_block = f"\n{memory_note}\n" if memory_note else ""
        plan = plan or {}
        fields = ", ".join(plan.get("relevant_fields", [])[:4]) or "relevant areas"
        extras = requested_prompt_block(plan.get("requests"))
        specialist_rules = specialist_prompt_block(plan)
        evidence_first_prompt = (evidence_first_block or "").strip()

        return f"""Tum ek bahut acche teacher ho. Tumhara kaam research ka result
aam bhasha mein aise samjhana hai ki padhne wale ko poori baat samajh aa jaye.

SAWAL: {question}

INTERNAL RESEARCH NOTES (ye user ko dikhane ke liye NAHI hain — inhe copy mat
karo, inse samjho aur apne shabdon mein samjhao):
{analysis[:5000]}
{critique_block}{hypothesis_block}{memory_block}
SOURCES (sirf inhi IDs se cite karo):
{pack.to_prompt_block(max_chars_per_source=500)}

{evidence_first_prompt}

{CITATION_INSTRUCTION}

{LABEL_RULE_PROMPT}

{specialist_rules}

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
            # §11 — takraav ka structured hissa: kis baat par, kaun kya keh raha
            # hai, aur saboot ka tukda kahan se aaya. Bina in teen cheezon ke
            # "takraav" likhna hi pichhli report ki galti thi (wahan sirf saal
            # alag the aur usi ko contradiction bata diya gaya tha).
            if c.get("normalized_proposition"):
                body.append(f"_Kis baat par:_ {c['normalized_proposition']}")
            if c.get("source_a_claim") and c.get("source_b_claim"):
                sids = list(c.get("sources") or ["A", "B"])
                a_id = sids[0] if sids else "A"
                b_id = sids[1] if len(sids) > 1 else "B"
                body.append(f"- {a_id} kehta hai: {c['source_a_claim']}")
                body.append(f"- {b_id} kehta hai: {c['source_b_claim']}")
            refs = [str(r) for r in (c.get("evidence_span_refs") or []) if str(r).strip()]
            if refs:
                body.append(f"_Saboot kahan se:_ {', '.join(refs)}")
            # §11 — method ki line DONO haalat mein chhapti hai. Pehle khaali
            # `method_difference` par line hi gayab ho jaati thi, jisse padhne
            # wale ko lagta tha ki method compare ho chuka hai aur farq nahi
            # mila. Ab "compare nahi ho paaya" bhi saaf likha jaata hai.
            if c.get("method_difference"):
                body.append(f"_Method ka farq:_ {c['method_difference']}")
            elif c.get("method_comparison_why"):
                body.append(f"_Method ka farq:_ {c['method_comparison_why']}")
            for note in (c.get("context_notes") or [])[:2]:
                if str(note).strip():
                    body.append(f"_Context:_ {note}")
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
    # `fallback` 2026-08-21 (point 10) mein juda: LLM quota/error se mar jaaye to
    # yahan pehle khaali "hypothesis nahi bani" line jaati thi. Ab uski jagah
    # system ka khud banaya research plan (`hypothesis.fallback_plan()`) chhapta
    # hai — wo AI hypothesis nahi hai aur khud ko hypothesis bolta bhi nahi.
    def _hypothesis_section(self, hypotheses: List[Dict],
                            requests: Optional[Dict] = None,
                            reasons: Optional[List[str]] = None,
                            pack: Optional[EvidencePack] = None,
                            fallback: Optional[Dict] = None) -> str:
        requests = requests or {}
        asked = int(requests.get("hypothesis_count") or 0)
        plan_text = ""
        if isinstance(fallback, dict) and not fallback.get("is_hypothesis", False):
            plan_text = str(fallback.get("text") or "").strip()
        if not hypotheses:
            # Purani report yahan likhti thi: "nayi hypothesis generate nahi ki
            # gayi (zaroorat nahi thi)". Jab user ne saaf-saaf 3 maangi thi, wo
            # line jhooth thi. Ab dono haalat alag-alag likhi jaati hain.
            if asked or requests.get("wants_hypotheses"):
                why = "; ".join(str(r) for r in (reasons or [])[:3]) \
                    or "wajah record nahi hui"
                target = f"{asked} " if asked else ""
                head = (f"❌ Aapne {target}nayi hypotheses maangi thi, lekin is run "
                        f"mein ek bhi poori nahi ban paayi. Ye \"zaroorat nahi thi\" "
                        f"wali baat nahi hai — zaroorat thi.\n\n"
                        f"**Asli wajah:** {why}\n\n"
                        f"Isliye is section ko adhoora maanein. Quota/error theek "
                        f"hone ke baad dobara chalane par ye ban jayengi.")
                return f"{head}\n\n{plan_text}" if plan_text else head
            if plan_text:
                return plan_text
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
            hid = str(h.get("hypothesis_id") or "").strip()
            head = f"### Hypothesis {i} — {title}"
            if hid:
                # §13 — har hypothesis ka apna stable ID, taaki baad ke run mein
                # bhi usi hypothesis ki baat ho sake.
                head = f"### {hid} — {title}"
            body: List[str] = [head]
            # #117 — jo hypothesis reject hui, uska nishaan card ke sabse UPAR.
            # Card mitaya nahi jaata (record rehna chahiye), par padhne wale ko
            # pehli line me hi pata chalna chahiye ki ise aage nahi badhaya ja
            # raha, aur KIS NAAP par. Poori tafseel `###` reject block me hai.
            if h.get("rejected"):
                reason = str(h.get("reject_reason") or "").strip()
                body.append(f"> ❌ **REJECT — aage nahi badhaya:** {reason}")
                if h.get("reject_reopen_if"):
                    body.append(f"> Wapas kab aa sakti hai: {h['reject_reopen_if']}")
            # §13/§2 — sabse pehle ye saaf ho jaana chahiye ki ye APP ka apna
            # idea hai, kisi source ka claim nahi. Pichhli report mein ye baat
            # neeche dabi rehti thi, isliye log ise "research finding" samajh
            # lete the.
            if h.get("source_claim_disclaimer"):
                body.append(f"> {h['source_claim_disclaimer']}")
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
            # §13 — provenance: kaunse facts par tika hai, aur kahan knowledge
            # gap tha. Iske bina "ye idea kahan se aaya" ek dawa bhar hai.
            prov = h.get("provenance") if isinstance(h.get("provenance"), dict) else {}
            facts = [str(f) for f in (prov.get("facts_used") or []) if str(f).strip()]
            if facts:
                body.append("**Kaunse sources ke facts se bana:** "
                            + ", ".join(facts[:8]))
            if str(prov.get("gap") or "").strip():
                body.append("**Kis jagah knowledge gap tha:** "
                            + self._join_prose(str(prov["gap"])))
            if str(h.get("mechanism") or "").strip():
                # §13 — mechanism: "kaise hoga" ka jawab. Sirf "ho sakta hai"
                # likhna hypothesis nahi, guess hai.
                body.append("**Ye kaam kaise karega (mechanism):** "
                            + self._join_prose(str(h["mechanism"])))
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
            # point 11: experiment aur falsification ab alag-alag dikhte hain.
            # Pehle dono "how to test" ke andar mile-jule the, isliye user ko
            # pata hi nahi chalta ki inme se kya missing hai.
            experiment = str(h.get("experiment") or "").strip()
            if experiment and experiment not in (h.get("how_to_test") or ""):
                body.append("**Zaroori experiment / simulation:** "
                            + self._join_prose(experiment))
            # §16 — experiment ki ek line chhaap dene se plan CHALAYA JA SAKNE
            # WALA lagta tha, jabki spec ke kai hisse (dataset, metric, hadd,
            # replication) likhe hi nahi gaye hote. Ledger door alag section
            # mein tha, isliye padhne wale tak baat pahunchti nahi thi. Ab kaunsa
            # hissa missing hai, wahi card par saaf likha jaata hai.
            gaps = [str(x).strip() for x in
                    (h.get("experiment_spec_missing_human") or []) if str(x).strip()]
            if gaps:
                body.append("**Is plan mein kya likha hi nahi gaya (isliye ise "
                            "ready-to-run plan na maanein):** "
                            + "; ".join(gaps[:11]))
            falsify = str(h.get("falsification_test") or "").strip()
            if falsify:
                body.append("**Kaunsa result ise galat sabit kar dega:** "
                            + self._join_prose(falsify))
            if h.get("if_true"):
                body.append("**Agar ye sahi hua:** " + self._join_prose(h["if_true"]))
            if h.get("if_false"):
                body.append("**Agar ye galat hua:** " + self._join_prose(h["if_false"]))
            # §14/§15 — novelty ka faisla app ka deterministic label hai, model
            # ka shabd nahi. Model ki apni "novelty" line neeche context ke liye
            # rehti hai, par pehle whitelist wala status dikhta hai.
            nov_status = str(h.get("novelty_status") or "").strip()
            if nov_status:
                line = f"**Novelty status:** {nov_status}"
                if str(h.get("novelty_why") or "").strip():
                    line += f" — {h['novelty_why']}"
                body.append(line)
            prior = [p for p in (h.get("closest_prior_work") or [])
                     if isinstance(p, dict)]
            if prior:
                bits = []
                for p in prior[:3]:
                    ref = str(p.get("source_id") or "").strip() or "source"
                    same = str(p.get("same") or "").strip()
                    diff = str(p.get("difference") or "").strip()
                    piece = f"{ref}"
                    if same:
                        piece += f" — milta hua hissa: {same}"
                    if diff:
                        piece += f"; farak: {diff}"
                    bits.append(piece)
                body.append("**Isse sabse milti-julti purani research:** "
                            + " | ".join(bits))
            elif nov_status:
                body.append("**Isse sabse milti-julti purani research:** retrieved "
                            "sources mein koi close match nahi mila — iska matlab "
                            "\"duniya mein pehli\" nahi, sirf itna ki humne jo "
                            "sources padhe unme nahi tha.")
            nsearch = h.get("novelty_search") if isinstance(
                h.get("novelty_search"), dict) else {}
            if nsearch:
                if nsearch.get("performed") is True:
                    dbs = ", ".join(str(d) for d in (nsearch.get("databases") or [])) \
                        or "record nahi hui"
                    body.append(f"**Prior-art search:** hui — databases: {dbs}.")
                else:
                    body.append("**Prior-art search:** is run mein prior-art "
                                "search nahi chali, isliye novelty verified nahi "
                                "hai (sirf 'pata nahi' hai).")
            if h.get("novelty"):
                body.append(f"**Model ne novelty par kya kaha:** {h['novelty']}")
            band = str(h.get("confidence_band") or "").strip()
            conf = h.get("confidence") if isinstance(h.get("confidence"), dict) else {}
            if band:
                # §18 — confidence BAND, number nahi. Percentage ke peeche koi
                # calculation nahi hoti, isliye wo jhoothi precision hai.
                line = f"**Kitna bharosa (band, percentage nahi):** {band}"
                reasons_txt = [str(r) for r in (conf.get("reasons") or [])
                               if str(r).strip()]
                if reasons_txt:
                    line += " — wajah: " + "; ".join(reasons_txt[:4])
                body.append(line)
                if str(conf.get("model_said") or "").strip():
                    body.append("_(Model ne khud "
                                f"\"{conf['model_said']}\" kaha tha — wo uska "
                                "andaza hai, isliye upar app ka apna band diya "
                                "gaya hai.)_")
            elif h.get("confidence_reasoning_based"):
                body.append(f"**Kitna bharosa (sirf reasoning par, proof nahi):** "
                            f"{h['confidence_reasoning_based']}")
            exp_struct = h.get("experiment_structured") if isinstance(
                h.get("experiment_structured"), dict) else {}
            exp_missing = [str(m) for m in (exp_struct.get("missing") or [])
                           if str(m).strip()]
            if exp_missing:
                # §16 — adhoore test plan ko falsification test kehna hi pichhli
                # badi galti thi. Ab kami ka naam liya jaata hai.
                body.append("⚠️ **Test plan mein ye hisse nahi aaye:** "
                            + ", ".join(exp_missing)
                            + ". Isliye ise poora falsification test nahi maana "
                              "ja sakta.")
            missing = [str(m) for m in (h.get("missing_fields") or []) if str(m).strip()]
            if missing:
                body.append("⚠️ **Is hypothesis mein ye cheezein nahi aayi:** "
                            + ", ".join(missing)
                            + ". Yaani ise poori tarah testable nahi maana ja sakta.")
            if h.get("safety_sensitive") is True:
                body.append("⚠️ **Safety-sensitive:** ye hypothesis medical/"
                            "chemical/biological ya safety se judi hai — bina "
                            "expert review aur risk assessment iske aage koi "
                            "kadam nahi lena chahiye.")
            # §16 — do alag baatein ek hi jagah: ye cheez kya hai (untested
            # hypothesis) aur uska validation kahan tak pahuncha (plan bhi hai
            # ya nahi). Pehle dono ko mila diya jaata tha.
            status_line = (f"**Current status: "
                           f"{h.get('status') or 'UNTESTED HYPOTHESIS'}** — "
                           f"abhi real-world test nahi hua.")
            if str(h.get("validation_status") or "").strip():
                status_line += f" Validation: {h['validation_status']}."
            body.append(status_line)

            blocks.append("\n\n".join(body))
        if asked and len(hypotheses) < asked:
            blocks.append(f"⚠️ Aapne {asked} maangi thi, {len(hypotheses)} ban paayi — "
                          f"isliye ye list adhoori hai.")
        if plan_text:
            # Kuch hypotheses bani par request poori nahi hui — tab poora
            # "hypothesis nahi bani" wala block lagana galat hoga (bani to hai),
            # isliye sirf khule sawaal + agla kadam jodte hain.
            blocks.append(self._plan_tail(fallback))
        return "\n\n".join(blocks)

    @staticmethod
    def _plan_tail(fallback: Optional[Dict]) -> str:
        data = fallback or {}
        questions = [str(q).strip() for q in (data.get("questions") or [])
                     if str(q).strip()]
        steps = [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()]
        lines = ["**Jo is list ke baad bhi baaki hai** (ye system ne gina hai, "
                 "AI ka idea nahi):"]
        if questions:
            lines.extend(f"- {q}" for q in questions[:5])
        if steps:
            lines.append("")
            lines.append("**Agla kadam:**")
            lines.extend(f"{i}. {s}" for i, s in enumerate(steps[:4], 1))
        if str(data.get("note") or "").strip():
            lines.append("")
            lines.append(f"_{data['note']}_")
        return "\n".join(lines)

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
        # Structured hissa poora bana ho to wahi behtar hai (§16 ke chaar naam
        # saaf-saaf). Warna asli text hi imaandaar jawab hai. Dhyaan: dict mein
        # ab `text` HAMESHA hota hai (structured ke saath bhi), isliye pehle
        # `text` dekh lena structured prose ko dabaa deta tha.
        if pred.get("structured") and bits:
            return " ".join(bits)
        if pred.get("text"):
            return str(pred["text"]).strip()
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
        """
        "Kitna gehra padha gaya" — har ginti apne denominator ke saath (§14).

        Sirf "3 source ka poora text mila" padh kar user maan leta hai ki kaam
        gehra hua. Par agar kul 18 source the, to wo 3/18 hai — matlab bilkul
        badal jaata hai. Isliye har line mein "kul kitne mein se" likhna zaroori
        hai.
        """
        levels = (coverage or {}).get("read_levels") or {}
        full = int(levels.get("full_text", 0) or 0)
        abstract = int(levels.get("abstract", 0) or 0)
        snippet = int(levels.get("snippet", 0) or 0)
        meta = int(levels.get("metadata", 0) or 0)
        if not (full or abstract or snippet or meta):
            return ("**Kitna gehra padha gaya:** iska data available nahi hai, "
                    "isliye is jawab ko kam bharosemand maanein.")
        total = full + abstract + snippet + meta
        lines = [f"**Kitna gehra padha gaya (isi se confidence tay hoti hai) — "
                 f"kul {total} sources par:**"]
        if full:
            lines.append(f"- {full}/{total} source ka POORA text mila. Inpar sabse "
                         f"zyada bharosa kiya ja sakta hai, kyunki claim seedha "
                         f"wahan se check hui hai.")
        if abstract:
            lines.append(f"- {abstract}/{total} source ka sirf abstract mila — yaani "
                         f"paper ka summary padha gaya, poora method nahi. Aisi baat "
                         f"\"source ye report karta hai\" level ki hoti hai.")
        if snippet:
            lines.append(f"- {snippet}/{total} source se sirf ek chhota snippet mila. "
                         f"Ye ishara deta hai, saboot nahi.")
        if meta:
            lines.append(f"- {meta}/{total} source ka sirf title/metadata mila — inse "
                         f"content ki koi guarantee nahi hai.")
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
    def _test_section(self, hypotheses: List[Dict], verification: Dict,
                      fallback: Optional[Dict] = None) -> str:
        lines: List[str] = []
        if hypotheses:
            lines.append("**Hypothesis-wise test plan:**")
            for i, h in enumerate(hypotheses, 1):
                bits: List[str] = []
                if h.get("how_to_test"):
                    bits.append(self._join_prose(h["how_to_test"]))
                # point 11: `experiment` alag field hai — test plan mein isse
                # chhodna hi wo purani kami thi jisme "test kaise karein" ka
                # jawab sirf ek line ka reh jaata tha.
                if h.get("experiment") and h.get("experiment") != h.get("how_to_test"):
                    bits.append(self._join_prose(str(h["experiment"])))
                pred_text = self._prediction_text(h)
                if pred_text:
                    bits.append(pred_text)
                if h.get("falsification_test"):
                    bits.append("Galat sabit karne wala result: "
                                + self._join_prose(str(h["falsification_test"])))
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
        # point 10: hypothesis na bane (LLM quota/error) to bhi is section mein
        # kaam ki cheez honi chahiye — system ka deterministic agla-kadam plan.
        steps = [str(s).strip() for s in ((fallback or {}).get("steps") or [])
                 if str(s).strip()] if not hypotheses else []
        if steps:
            lines.append("")
            lines.append("**Nayi hypothesis nahi bani, isliye system ka agla-kadam "
                         "plan (ye AI ka idea nahi, sources ki haalat se nikla hai):**")
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
        if not lines:
            lines.append("Is jawab ke liye koi alag test plan nahi bana, kyunki nayi "
                         "hypothesis is run mein nahi bani.")
        return "\n".join(lines)

    # ── §13 + §14: sources ki imaandaar list ─────────────────────────────────
    # §9 (2026-08-21): "FULL-TEXT VERIFIED" label HATA diya gaya hai. Wo ek hi
    # shabd mein do baatein keh raha tha — "text mil gaya" aur "claim verify ho
    # gaya" — aur pichhle run mein abstract-only source par bhi chhap gaya tha.
    # Ab access depth ka poora vocabulary models.ACCESS_DEPTH_LABELS mein ek hi
    # jagah hai, aur verification uska hissa nahi hai.
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
            lines.append(f"- Kitna padha gaya: {s.access_depth_note()}.")
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
        # point 12 — maths/physics sanity checks
        "physical limits":
            "numbers kisi physical deewar (0 kelvin, light speed, 100%) ko todte "
            "hain ya nahi",
        "unit conversion":
            "ek hi value do units mein likhi gayi ho to dono match karte hain ya nahi",
        "comparison direction":
            "'zyada/kam' wali tulna unit badalne ke baad bhi sahi rehti hai ya nahi",
        "superconductivity range":
            "Tc aur pressure aaj tak measure hui range ke andar hain ya nahi",
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
        "physical limits":
            "Jawab ka ek number physical limit hi tod raha hai",
        "unit conversion":
            "Ek hi value do units mein alag-alag likhi gayi hai",
        "comparison direction":
            "Tulna ulti hai — unit convert karne par claim palat jaata hai",
        "superconductivity range":
            "Tc/pressure ka number aaj tak measure hui range se bahar hai",
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
        # §14 — har ginti ke saath denominator. "2 check theek nikle" se pata hi
        # nahi chalta ki kul 3 the ya 30; "2/3" se poori tasveer dikhti hai.
        total = len(checks)
        if failed:
            lines.append("")
            word = "cheez" if len(failed) == 1 else "cheezein"
            lines.append(f"**{len(failed)}/{total} {word} mein problem mili hai:**")
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
            lines.append(f"**{len(passed)}/{total} check theek nikle**, jaise: {names}.")
        if unknown:
            lines.append("")
            lines.append(f"**{len(unknown)}/{total} cheez check hi nahi ho paayi** — "
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
        # point 12 — maths/physics sanity pass ka ek line ka honest summary.
        # Non-quantitative sawal par ye jaan-boojh kar kuch nahi likhta.
        physics = verification.get("physics") or {}
        if physics.get("applicable") and str(physics.get("note") or "").strip():
            lines.append("")
            lines.append(f"**Maths/physics sanity check:** {physics['note']}")
        return "\n".join(lines).strip()

    # ── §17: calculation ka poora record, user ke saamne ─────────────────────
    #
    # Kyun: dark-matter run mein "numeric sanity check passed" chhapa tha par
    # jawab mein na formula tha, na inputs, na units. Ab ulta niyam hai — jo
    # hisaab dikhaya jaayega uska formula, input, unit, assumption aur nateeja
    # saamne hoga, aur teen check ALAG-ALAG dikhenge (unit theek likhe? dobara
    # jodne par wahi jawab? koi number humne khud gadha?). Jo check na chal
    # paaya uske liye "pata nahi" likhte hain, "pass" nahi.
    _CALC_WORDS = {
        True: "haan", False: "nahi", None: "check nahi ho paaya",
    }

    def _calculation_section(self, calculations: Optional[List[Dict]]) -> str:
        if not calculations:
            return ""
        lines: List[str] = []
        for i, calc in enumerate(calculations, start=1):
            if not isinstance(calc, dict):
                continue
            lines.append(f"### Calculation {i}")
            formula = str(calc.get("formula") or "").strip()
            lines.append(f"**Formula:** `{formula}`" if formula
                         else "**Formula:** likha hi nahi gaya tha — isliye ise "
                              "verified hisaab nahi maana ja sakta.")
            inputs = calc.get("inputs") or {}
            units = calc.get("units") or {}
            if inputs:
                pretty = ", ".join(
                    f"{name} = {value:g} {str(units.get(name) or '').strip()}".strip()
                    for name, value in list(inputs.items())[:8])
                lines.append(f"**Inputs (units ke saath):** {pretty}")
            else:
                lines.append("**Inputs:** kaunsa number kahan se aaya, ye likha "
                             "nahi gaya tha.")
            assumptions = [str(a).strip() for a in (calc.get("assumptions") or [])
                           if str(a).strip()]
            if assumptions:
                lines.append("**Kya maan kar chale (assumptions):**")
                lines.extend(f"- {a}" for a in assumptions[:4])
            else:
                lines.append("**Assumptions:** koi assumption likha nahi gaya — "
                             "yaani ye hisaab kis haalat mein sach hai, wo saaf "
                             "nahi hai.")
            result = str(calc.get("result") or "").strip()
            unit_of_result = str((units or {}).get("result") or "").strip()
            if result:
                line = f"**Result:** {result}"
                if not unit_of_result:
                    line += " _(nateeje ka unit nahi likha gaya)_"
                lines.append(line)
            else:
                lines.append("**Result:** koi nateeja saaf likha nahi gaya.")
            uncertainty = str(calc.get("uncertainty") or "").strip()
            lines.append(f"**Uncertainty:** {uncertainty}" if uncertainty
                         else "**Uncertainty:** nahi di gayi — isliye ye number "
                              "'exact' nahi samajhna.")
            recomputed = str(calc.get("recomputed") or "").strip()
            checks = [
                ("Unit theek likhe hain?", calc.get("unit_check_passed"), ""),
                ("Dobara jodne par wahi jawab aata hai?",
                 calc.get("recalculation_passed"),
                 f" (humara recompute: {recomputed})" if recomputed else ""),
                ("Physical limit / conversion check theek?",
                 calc.get("sanity_check_passed"), ""),
            ]
            lines.append("**Alag-alag check:**")
            for label, value, extra in checks:
                lines.append(f"- {label} **{self._CALC_WORDS.get(value)}**{extra}")
            invented = calc.get("invented_input")
            if invented is True:
                lines.append("- ⚠️ Kam se kam ek input aisa hai jo question ya "
                             "sources mein nahi mila — wo model ka apna anumaan "
                             "hai, verified data nahi.")
            elif invented is False:
                lines.append("- Saare inputs question ya sources se aaye hain "
                             "(koi number khud se nahi gadha gaya).")
            else:
                lines.append("- Inputs kahan se aaye, ye check nahi ho paaya.")
            notes = [str(n).strip() for n in (calc.get("notes") or [])
                     if str(n).strip()]
            if notes:
                lines.append("**Kami / wajah:** " + "; ".join(notes[:3]) + ".")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _no_calculation_note(pack: Optional[EvidencePack] = None,
                             ledger: Optional[Dict] = None,
                             requests: Optional[Dict] = None) -> str:
        """§12 — hisaab na bane to bhi section rehta hai, WAJAH ke saath.

        Pehle `_calculation_section` khaali string deta tha aur poori section
        gayab ho jaati thi. Gayab section apne aap mein ek jhooth hai: user ko
        pata hi nahi chalta ki hisaab hua tha aur fail ho gaya, ya hisaab ki
        zaroorat hi nahi thi. Teen wajah alag-alag likhi jaati hain
        (`answer_order.NO_CALC_REASONS`), kyunki teenon ka matlab alag hai.
        """
        asked = any(
            isinstance(item, dict) and item.get("key") == "calculations"
            for item in ((ledger or {}).get("items") or [])
        )
        if not asked:
            asked = bool((requests or {}).get("wants_math_model"))
        reasoning_ok = True
        try:
            reasoning_ok = bool(pack.reasoning_complete)
        except Exception:                        # noqa: BLE001
            reasoning_ok = True
        if asked and not reasoning_ok:
            key = "no_reasoning"
        elif asked:
            key = "no_inputs"
        else:
            key = "not_asked"
        return f"_Koi calculation is jawab mein nahi hai._ {NO_CALC_REASONS[key]}"

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
        """
        Source quality ki ginti — hamesha "kul kitne mein se" ke saath (§14).

        "4 source peer-reviewed hai" apne aap mein achha lagta hai; "4/15" sach
        batata hai. Denominator wahi hai jitne sources jawab mein use hue.
        """
        bits: List[str] = []
        count = FinalSynthesizer._count
        used = count((coverage or {}).get("sources_used", 0))
        if not used:
            used = len(getattr(pack, "sources", []) or []) if pack else 0
        of = f"/{used}" if used else ""
        peer = count((coverage or {}).get("peer_reviewed", 0))
        if peer:
            bits.append(f"- {peer}{of} source peer-reviewed hai (yaani doosre "
                        f"researchers ne use check kiya tha).")
        strong = count((coverage or {}).get("strong_methodology_sources", 0))
        if strong:
            bits.append(f"- {strong}{of} source ka study design mazboot hai "
                        f"(review/trial jaisa).")
        retracted = count((coverage or {}).get("retracted_sources", 0))
        if retracted:
            bits.append(f"- ⚠️ {retracted}{of} source par retraction ka signal hai.")
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
        assurance = coverage.get("research_assurance") or {}
        if assurance.get("active"):
            percent = assurance.get("research_process_coverage_percent", 0)
            target = assurance.get("target_percent", 0)
            state = ("target poora hua" if assurance.get("target_met")
                     else "target poora nahi hua")
            lines.append(
                f"- MARATHON research-process coverage: {percent}% (target "
                f"{target}%; {state}). Ye answer ki truth probability, trading "
                f"profitability ya hypothesis success probability nahi hai."
            )
            saturation = assurance.get("saturation") or {}
            if saturation.get("reason"):
                lines.append(f"- Bounded saturation: {saturation['reason']}.")
            gaps = assurance.get("gaps") or []
            if gaps:
                lines.append("- Process gaps: " + ", ".join(str(x) for x in gaps) + ".")
        # §5 — "kitne mile" ke baad hi "kaunsa saboot mila hi nahi". Ye lines
        # `evidence_axes.coverage_note()` se aati hain; axes naape na gaye hon to
        # ye block chhapta hi nahi (khaali heading/jhoothi tasalli se bachne ke liye).
        axis_note = ((coverage.get("evidence_axes") or {}).get("note") or "").strip()
        if axis_note:
            lines.append("")
            lines.append("**Saboot ke raaste (evidence axes):**")
            for row in axis_note.splitlines():
                row = row.strip()
                if not row:
                    continue
                if row.startswith("•"):
                    # "•" markdown bullet nahi hai — aisi line pichhli line ke
                    # saath chipak jaati hai. Nested "-" hi theek se render hota hai.
                    lines.append(f"  - {row.lstrip('• ').strip()}")
                else:
                    lines.append(f"- {row}")
        # §6 — "kitne mile" se zyada zaroori: unmein se kitne sach mein sawaal ki
        # baat test karte hain. Ye block sirf tab chhapta hai jab relevance gate
        # asli mein chala ho (`prop` khaali = gate chala hi nahi), warna 0 likhna
        # jhooth hota — pichhli report mein yahi confusion tha: 18 source "mile"
        # likha tha aur unmein calibration/exoplanet papers bhi gine ja rahe the.
        prop = coverage.get("proposition_test") or {}
        if prop:
            lines.append("")
            lines.append("**Sources sawaal ko test karte hain ya nahi (relevance gate):**")
            lines.append(f"- Test karte hain: {prop.get('tests_proposition', 0)} | "
                         f"nahi karte: {prop.get('does_not_test', 0)} | "
                         f"faisla nahi ho saka: {prop.get('undecided', 0)}.")
            lines.append("- Aakhri ginti ka matlab 'theek hai' nahi hai — utna "
                         "metadata hi mila tha ki faisla ho paata.")
            failed = prop.get("failed_dimensions") or {}
            if failed:
                worst = sorted(failed.items(), key=lambda kv: -int(kv[1] or 0))[:4]
                lines.append("- Kis cheez par fail hue: "
                             + ", ".join(f"{k}: {v}" for k, v in worst) + ".")
            codes = coverage.get("relevance_reject_codes") or {}
            if codes:
                lines.append("- Kis wajah se hataye gaye: "
                             + ", ".join(f"{k}: {v}" for k, v in codes.items()) + ".")
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

    # ── §13 — claim-level A–E block ──────────────────────────────────────────
    _CHECK_WORDS = {
        "A": "citation likhi hui hai aur wo source asli pack mein maujood hai",
        "B": "wo source is sawaal se juda hua hai",
        "C": "us source ke text mein is claim ka support asli mein mila",
        "D": "us source ko kaafi gehrai tak padha gaya",
        "E": "us source ki quality itni hai ki uspar dava tik sake",
    }

    def _claim_check_block(self, claim_checks: Optional[Dict]) -> str:
        """
        A–E ka user-facing hissa — denominator ke saath, bina jargon ke.

        Ye dict `claim_verification.VerificationReport.to_dict()` se aata hai.
        Khaali/None hone par section chhapti hi nahi (§10: khaali heading nahi).
        """
        data = claim_checks or {}
        total = int(data.get("total_claims") or 0)
        if not total:
            return ""
        genuine = int(data.get("genuine_support") or 0)
        reported = int(data.get("source_reported") or 0)
        cited_only = int(data.get("cited_only") or 0)
        unsupported = int(data.get("unsupported") or 0)
        not_checkable = int(data.get("entailment_not_checkable") or 0)

        lines = [
            f"Is jawab ki **{total}** aisi lines thi jo 'ye baat sach hai' ka dava "
            f"karti hain. Har line par paanch alag sawaal poochhe gaye:",
            "",
        ]
        for key in ("A", "B", "C", "D", "E"):
            row = (data.get("check_counts") or {}).get(key) or {}
            lines.append(
                f"- **{key}** — {self._CHECK_WORDS[key]}: "
                f"{int(row.get('pass') or 0)} par haan, "
                f"{int(row.get('fail') or 0)} par nahi, "
                f"{int(row.get('unknown') or 0)} par check ho hi nahi saka")
        lines += [
            "",
            f"Iska nateeja: **{genuine}** claim par poora text padh kar support "
            f"mila, **{reported}** sirf 'source ye report karta hai' level par "
            f"hain, **{cited_only}** mein citation to thi par us text mein support "
            f"nahi dikha, aur **{unsupported}** ke peeche koi valid source hi "
            f"nahi tha.",
        ]
        if not_checkable:
            lines.append(
                f"**{not_checkable}** claim ka support check HO HI NAHI SAKA "
                f"(us source ka text system ke paas nahi tha) — inhe "
                f"jaan-boojh kar 'verified' nahi gina gaya.")
        lines.append(
            "_Yahan sabse zaroori baat: sirf **C** hi 'asli support' dikhata hai. "
            "**A** pass hona itna hi batata hai ki citation likhne ka tareeka "
            "theek tha — na ki baat sahi hai. Aur **C** ek text-matching check "
            "hai (shabd + number milaan), insaani padhai nahi._")

        overclaims = [o for o in (data.get("overclaims") or []) if isinstance(o, dict)]
        if overclaims:
            lines.append("")
            lines.append(f"⚠️ **{len(overclaims)} jagah label zarurat se zyada strong "
                         f"tha** (established/fact, jabki upar ke check usse support "
                         f"nahi karte):")
            for item in overclaims[:5]:
                claim = str(item.get("claim") or "").strip()
                reason = str(item.get("reason") or "").strip()
                lines.append(f"- {claim[:150]}" + (f" — {reason[:130]}" if reason else ""))
        return "\n".join(lines)

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
                       claim_checks: Optional[Dict] = None,
                       missing_sections: Optional[List[str]] = None,
                       lab_report: Optional[Dict] = None,
                       reject_report: Optional[Dict] = None,
                       craft_report: Optional[Dict] = None) -> str:
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

        # §13 / point 7 — paanch check ALAG-ALAG. Pehle "citation verified" ek
        # hi number tha, aur uska matlab sirf itna tha ki [S3] naam ka source
        # pack mein maujood hai. Ab A–E alag chhapte hain, aur saaf likha hai ki
        # sirf C "asli support" dikhata hai.
        claim_text = self._claim_check_block(claim_checks)
        if claim_text:
            blocks.append("### Har claim ki paanch-check jaanch (A–E)\n" + claim_text)

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
        # #116 — LAB ki seema NAAPI hui hai: kitne test pass/fail hue aur kaunsa
        # test data ke bina chala hi nahi. Ye line general disclaimer nahi hai,
        # isliye ye us run ke asli nateeje se banti hai.
        for lab_line in lab_limits(lab_report)[:4]:
            tail.append(f"- {lab_line}")
        # #117 — reject ki ginti bhi audit me. "Kitni hataayi, kis wajah se,
        # kitni bina naap ke nikli" — teesri line hi wo bug pakadti hai jisme
        # koi hypothesis chup-chaap gir jaaye.
        for reject_line in reject_limits(reject_report)[:4]:
            tail.append(f"- {reject_line}")
        # #121 — CRAFT ki seema bhi NAAPI hui hai: kya-kya naapa gaya, kya naapa
        # hi nahi ja saka, aur revision chali ya nahi. Iske bina audit me
        # creative kaam par ek generic line lagti thi jo aadhi galat hai.
        for craft_line in craft_limits(craft_report)[:5]:
            tail.append(f"- {craft_line}")
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
        """
        API ka hisaab — teen ALAG ginti, aur har number ka denominator.

        Pehle is block ki pehli line "Reasoning pass: 3/3" hoti thi. Wo padh kar
        lagta tha ki teen baar AI ne sochha — jabki 429 wale run mein teeno pass
        khaali laut aaye the. Ab saaf likha hai: kitne maange, kitne se sach mein
        output aaya, aur network par kitni baar gaye. Zero-call run par bhi chup
        nahi rehte — wahan ye ₹0 ka saboot hai, isliye alag se likha jaata hai.
        """
        if not accounting:
            return ""
        acc = dict(accounting)
        asked = int(acc.get("passes_requested") or 0)
        got = int(acc.get("passes_with_output") or 0)
        attempts = int(acc.get("actual_http_attempts") or 0)
        lines = [
            f"- Reasoning pass maange gaye: **{acc.get('logical_reasoning_calls', 0)}"
            f"/{acc.get('budget', 0)}** (budget ke against).",
        ]
        if asked:
            lines.append(
                f"- Inmein se output sach mein aaya: **{got}/{asked}**"
                + (f" — khaali laute: {', '.join(str(p) for p in (acc.get('empty_output_passes') or [])[:5])}."
                   if got < asked else "."))
        lines.append(f"- Asli HTTP attempts (network par gaye): **{attempts}**")
        if attempts:
            lines += [
                f"- Inmein safal: **{acc.get('successful_calls', 0)}/{attempts}**",
                f"- Inmein fail: "
                f"**{acc.get('failed_http_attempts', acc.get('failed_attempts', 0))}"
                f"/{attempts}**",
                # Ye do line jaan-boojh kar ALAG hain: wahi model dobara maarna
                # retry hai, doosre model par jaana fallback. Pehle dono ek hi
                # "Retry" number mein mil kar jhootha hisaab dete the.
                f"- Same model par dobara koshish (retry): "
                f"**{acc.get('same_model_retries', 0)}**",
                f"- Doosre model par shift (fallback, retry NAHI): "
                f"**{acc.get('model_switches', 0)}**",
            ]
        else:
            lines.append("- Yaani is run mein ek bhi API call nahi hui — jo bana wo "
                         "system ke apne (offline, deterministic) logic se bana. "
                         "Iska cost ₹0 hai.")
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
        counted_by = str(acc.get("counted_by") or "").strip()
        if counted_by:
            lines.append(f"- _Ye ginti {counted_by} — isliye ise provider ke bill se "
                         f"milane par thoda antar ho sakta hai._")
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

    def canonical_heading_view(self, text: str) -> str:
        """
        Model ke text ko canonical headings ke saath dobara likho — SIRF
        claim verification ke liye. Ye view user ko kabhi nahi dikhta.

        Kyun zaroori hai: koi claim "critical" hai ya nahi, ye us section se
        tay hota hai jisme wo likhi hai (seedha jawab / final conclusion).
        Model apni marzi ki heading likhta hai (`### Fact — ...`), isliye RAW
        model text par verification chalane se har critical claim non-critical
        ban jaati thi — live dark-matter run mein `critical_claims: 0` aaya,
        jabki wahi text final answer par 1 critical deta hai. Usse §8 ke
        evidence spans khaali reh jaate the aur `critical_claim_spans_complete`
        "pata nahi" par atak jaata tha.

        Assembled (final) answer par verification chalana bhi theek nahi hota:
        usme audit block ki apni lines bhi claim ban kar ginne lagti hain, aur
        jawab ke andar do alag ginti aa jaati.

        Content ek shabd bhi nahi badalta — sirf heading ka naam canonical hota
        hai, aur bina heading wala leftover text sabse pehle (section = khaali,
        yaani "critical nahi") rakha jaata hai.
        """
        raw = text or ""
        try:
            found, leftover = self.split_model_sections(raw)
        except Exception:                                    # noqa: BLE001
            return raw
        if not found:
            return raw
        parts: List[str] = []
        if leftover.strip():
            parts.append(leftover.strip())
        for key in sorted(k for k in found if isinstance(k, int)):
            title = (SECTION_TITLES[key] if 0 <= key < len(SECTION_TITLES)
                     else str(key))
            parts.append(f"## {title}\n{found[key]}".rstrip())
        for key in [k for k in found if not isinstance(k, int)]:
            parts.append(f"## {key}\n{found[key]}".rstrip())
        return "\n\n".join(p for p in parts if p.strip())

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
                 api_accounting: Optional[Dict] = None,
                 claim_checks: Optional[Dict] = None,
                 hypothesis_plan: Optional[Dict] = None,
                 calculations: Optional[List[Dict]] = None,
                 lab_report: Optional[Dict] = None,
                 reject_report: Optional[Dict] = None,
                 craft_report: Optional[Dict] = None) -> str:
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
                                                       reasons, pack,
                                                       hypothesis_plan)
                parts.append(engine_text)
                # #116 — LAB stage ka apna nateeja usi section ke andar, ek
                # `###` block me. Ye model ka text nahi hai: ye app ne KHUD
                # chalaye hue test ka record hai, aur iske bina "hypothesis
                # UNTESTED" hi dikhta reh jaata tha.
                lab_text = lab_report_section(lab_report)
                if lab_text:
                    parts.append(lab_text)
                # #117 — reject-list usi section me: kaunsi hypothesis aage nahi
                # badhi, aur KIS NAAP par. Pehle drop chup-chaap hota tha.
                reject_text = reject_section(reject_report)
                if reject_text:
                    parts.append(reject_text)
                # #121 — CRAFT: agar is run me kuch BANAYA gaya tha (gaana/
                # kavita/letter...), to us draft ka naapa hua record bhi yahin
                # `###` block me aata hai. Ye "acha bana hai" nahi kehta —
                # sirf dhaancha (matra/tuk/hook/dohraav) ka hisaab dikhata hai,
                # aur jo naapa hi nahi ja sakta wo naam se likh deta hai.
                craft_text = craft_section(craft_report)
                if craft_text:
                    parts.append(craft_text)
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
                    claim_checks=claim_checks,
                    missing_sections=missing_sections,
                    lab_report=lab_report,
                    reject_report=reject_report,
                    craft_report=craft_report)
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
                    engine_text = self._test_section(hypotheses, verification,
                                                     hypothesis_plan)
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
        printed = [i for i in EMIT_ORDER if i in bodies]
        first = printed[0] if printed else 0
        slot = {index: place for place, index in enumerate(EMIT_ORDER)}

        def _last_printed(candidates) -> int:
            available = [i for i in printed if i in candidates]
            return max(available, key=lambda i: slot[i]) if available else first

        extras_after = _last_printed({0, 1, 2})
        # Leftover text main answer ke hisse mein rehna chahiye — LAB (5) ke baad
        # nahi, warna model ka text app ki apni soch jaisa dikhne lagta hai.
        leftover_after = _last_printed({0, 1, 2, 3, 4, 7, 8})
        # §17 + §12 — calculation block counter-evidence ke BAAD aur Unknowns se
        # PEHLE, ek fixed jagah par. Wajah: hisaab evidence ka hissa hai, app ki
        # apni soch ka nahi. Aur ye section KABHI gayab nahi hota (neeche dekho).
        calc_block = self._calculation_section(calculations)
        if not str(calc_block).strip():
            calc_block = self._no_calculation_note(pack, ledger, requests)
        calc_done = False

        out: List[str] = []
        for index in EMIT_ORDER:
            # §12 — Calculations ki jagah fixed hai aur ye HAMESHA chhapta hai.
            # Pehle hisaab na banne par poora section gayab ho jaata tha, aur
            # gayab section se user ko pata hi nahi chalta tha ki hisaab hua tha
            # ya nahi — wahi chup-chaap gayab hona pichhli baar jhooth ban gaya.
            if index == 7 and not calc_done:
                out.append(f"## {CALC_HEADING}")
                out.append(calc_block)
                calc_done = True
            if index not in bodies:
                continue
            title = SECTION_TITLES[index]
            out.append(f"## {title}")
            if index == 0:
                banner = self._status_banner(pack, ledger, status, missing_sections)
                if banner:
                    out.append(banner)
            # §12/§13 — APP ORIGINAL RESEARCH LAB ke sar par warning, section ke
            # content se PEHLE. Ye hissa report ka sabse galat-samajha jaane wala
            # hissa tha: app ki hypotheses established evidence jaisi padhi ja
            # rahi thin.
            if index == 5:
                out.append(LAB_WARNING)
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

        if not calc_done:                      # defensive: EMIT_ORDER badal jaaye
            out.append(f"## {CALC_HEADING}")
            out.append(calc_block)

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
                         f"_{source.access_depth_note()}_")
        lines.append("")
        lines.append("Inhe jodkar koi conclusion humne nahi nikala — wo kaam reasoning "
                     "pass ka tha, jo is baar poora nahi hua.")
        return "\n\n".join(lines)
