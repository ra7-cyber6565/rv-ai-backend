"""
DeepResearchEngine — Spec Section 6 + 16 (orchestrator.py)

Poora pipeline yahan judta hai:

    SAFETY → PLAN → DOCUMENTS → DISCOVERY (always) → EVIDENCE PACK
    → [round 2/3 agar evidence kamzor] → CONTRADICTIONS
    → GEMINI PASSES (budget ke andar) → CITATION VERIFY → VERIFICATION
    → SYNTHESIS → MEMORY

Do sabse important design decisions:

1. DISCOVERY ALWAYS ON.
   Purane research_agent.py mein external search sirf tab chalti thi jab PDF
   context khaali ho (`if not retrieval["context"]`). Iska matlab PDF upload
   karte hi poora internet/academic side band ho jaata tha — jo Spec Section 2
   ka seedha ulta hai. Ab documents aur external sources DONO hamesha aate hain,
   aur dono ek hi evidence pack mein ek jaisa treat hote hain.

2. GEMINI KE BAHAR KI SACHCHAI.
   Contradictions, verification, citation check, coverage — sab local engines se
   aate hain. Isliye Gemini fail ho ya quota khatam ho, jawab ke ye hisse phir
   bhi asli rehte hain (Spec Section 17/18: dikhawe ka Deep Research nahi).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .citation import CitationEngine
from .advanced_discovery import ScientificDiscoveryEngine
from .claim_labels import downgrade as downgrade_labels
from .claim_labels import merge_reports as merge_label_reports
from .claim_verification import enforce_strict_labels
from .claim_verification import verify_answer as verify_claims
from .content_fetcher import ContentFetcher
from .contradiction import ContradictionEngine
from .critic import Critic
from .depth import get_depth_config, quota_note
from .evidence import EvidenceEngine
from .evidence_drafting import (
    audit_claims_against_manifest, build_evidence_draft_manifest,
)
from .gemini_reasoning import GeminiReasoning, QuotaExhausted
from .hypothesis import HypothesisEngine
from .knowledge_graph import KnowledgeGraphAdapter
from .models import EvidencePack, ResearchResult, SourceRecord
from .patents import novelty_note, novelty_overclaim
from . import physics_checks
from .planner import ResearchPlanner
from . import quality_producers as quality
from .evidence_axes import axes_for
from .evidence_axes import coverage as axis_coverage
from .evidence_axes import coverage_note as axis_coverage_note
from .evidence_axes import coverage_summary
from .evidence_axes import counter_search_done
from .evidence_axes import next_queries as axes_next_queries
from .requested import build_ledger, contract_ledger, delivery_evidence
from .requested import looks_like_chain
from .requested import looks_like_math_model, quality_contract
from .research_memory import ResearchMemory
from .research_state import build_state as build_research_state
from .research_state import inject_state_block, state_warnings
from .run_status import INCOMPLETE, evaluate as evaluate_status
from .run_status import human_reason, split_messages
from .source_discovery import SourceDiscovery
from .specialist_domains import build_evidence_lane_report
from .synthesizer import FinalSynthesizer
from .vector_search import VectorSearch
from .verification import VerificationEngine


class DeepResearchEngine:
    def __init__(self, project_id: str = "default", enable_kg: bool = True,
                 enable_memory: bool = True):
        self.project_id = project_id or "default"
        self.planner = ResearchPlanner()
        self.discovery = SourceDiscovery()
        self.evidence = EvidenceEngine()
        self.citations = CitationEngine()
        self.contradictions = ContradictionEngine()
        self.reader = ContentFetcher()
        self.critic = Critic()
        self.hypotheses = HypothesisEngine()
        self.verifier = VerificationEngine()
        self.synthesizer = FinalSynthesizer()
        self.scientific_discovery = ScientificDiscoveryEngine(self.planner)
        self.vectors = VectorSearch()
        self.graph = KnowledgeGraphAdapter(enabled=enable_kg)
        self.memory = ResearchMemory(self.project_id) if enable_memory else None

    # ── helpers ──────────────────────────────────────────────────────────────
    def _start_tracking(self, job_id: Optional[str], question: str) -> None:
        """
        Progress store mein job register karo.

        Ye zaroori hai: progress_tracker.update_stage() us job ko chup-chaap
        ignore kar deta hai jo register na ho. Pehle start_tracking sirf purane
        research_agent.py shim mein tha, isliye naye pipeline mein
        GET /progress/{id} hamesha "Job not found" deta tha.
        """
        if not job_id:
            return
        try:
            from utils import progress_tracker
            progress_tracker.start_tracking(job_id, question)
        except Exception:
            pass

    def _track(self, job_id: Optional[str], stage: str, note: str = "") -> None:
        if not job_id:
            return
        try:
            from utils import progress_tracker
            progress_tracker.update_stage(job_id, stage, note)
        except Exception:
            pass

    def _counts(self, job_id: Optional[str], **kwargs) -> None:
        if not job_id:
            return
        try:
            from utils import progress_tracker
            progress_tracker.set_counts(job_id, **kwargs)
        except Exception:
            pass

    def _safety(self, question: str) -> Dict:
        try:
            from safety.checks import check_safety
            return check_safety(question) or {}
        except Exception:
            return {"flags": [], "safe_to_proceed": True, "flag_count": 0}

    # ── 1. documents ─────────────────────────────────────────────────────────
    def _document_records(self, question: str, config) -> tuple:
        retrieval = self.vectors.retrieve(question, self.project_id,
                                          n_results=max(4, config.max_sources))
        records = self.evidence.records_from_retrieval(retrieval)
        note = (f"{len(records)} document chunks mile" if records
                else "koi uploaded document match nahi hua")
        if self.vectors.last_error:
            note += f" (vector search error: {self.vectors.last_error[:80]})"
        return records, note

    # ── 2. discovery (always on, multi-round) ────────────────────────────────
    def _discover(self, question: str, plan: Dict, config, doc_records: List[SourceRecord],
                  job_id: Optional[str] = None) -> Dict:
        external: List[SourceRecord] = []
        logs: List[Dict] = []
        connectors: List[str] = []
        seen = set(self.memory.seen_urls()) if self.memory else set()
        # Purane URLs ko discovery se skip nahi karte (wo abhi bhi relevant ho
        # sakte hain) — sirf duplicate rokne ke liye is-run ka set use hota hai.
        seen_this_run: set = set()
        rounds_run = 0
        sufficiency: Dict = {}
        pack: Optional[EvidencePack] = None
        # §11 — jo queries sach mein chali, unka record. Consensus gate isse
        # dekhta hai ki opposition-side search hui thi ya nahi.
        queries_run: List[str] = []

        # §15 — kis round mein search khud crash hua. Ye insaani warning banti
        # hai; raw exception text sirf `round_error_details` mein jaata hai aur
        # wahan se report ke sabse neeche "Technical details" block mein
        # (point 9: user ke padhne wale hisse mein protobuf/traceback kabhi nahi).
        round_errors: List[str] = []
        round_error_details: List[str] = []

        # §5 — retrieval ab "ek broad query" se nahi, SABOOT KE RAASTON se
        # chalti hai. `axis_queries` mein likha jaata hai ki kis axis par
        # kaunsi query gayi — isi se "dhoondha nahi" aur "dhoondha par nahi
        # mila" ka farq banta hai (dark-matter run mein CMB/BBN/Bullet Cluster
        # par ek bhi query gayi hi nahi thi, phir bhi answer COMPLETE tha).
        axes = axes_for(question)
        axis_queries: Dict[str, List[str]] = {}
        axis_records: List[Dict] = []
        # §5 — har round mein kitni axis queries? Pehle ye 3 par fix thi, aur
        # dark-matter jaise sawaal par 17 mandatory axes × 3 round × 3 query ka
        # matlab tha ki 8 axes par ek bhi query jaati hi nahi thi (report unhe
        # imaandaari se "search hi nahi hui" kehti thi, par kami rehti thi).
        # Ab budget axes ki ginti se banta hai: itni queries taaki available
        # rounds mein har mandatory axis ki baari aa jaaye. Upar 8 ki chhat hai
        # (connector budget asli constraint hai) aur QUICK mode sasta hi rehta
        # hai. Ye sab ₹0 search connectors par chalta hai.
        _mandatory_axes = sum(1 for a in axes if a.mandatory) or len(axes)
        if config.max_rounds <= 1:
            axis_budget = 3
        else:
            axis_budget = max(3, min(
                8, -(-_mandatory_axes // max(1, config.max_rounds))))

        for round_no in range(1, config.max_rounds + 1):
            rounds_run = round_no
            # `plan` classify() ke dict ka SUPERSET hai (planner.plan() mein
            # **cls spread hota hai), isliye ise seedha cls ki jagah dena safe
            # hai — planner ke andar saari fields .get() se padhi jaati hain.
            queries = self.planner.search_queries(question, plan, round_no=round_no)
            if not queries:
                # Planner ne kuch na diya to bhi search rukni nahi chahiye —
                # seedha sawal hi query ban jaata hai.
                queries = [question]
            # Har round mein axis queries jodte hain: pehle un axes ki jo abhi
            # cover nahi hue, aur ladder ki AGLI seedhi par (wahi query dobara
            # nahi). Ginti `axis_budget` se aati hai — QUICK par 3, gehre modes
            # par utni ki saare mandatory axes ki baari aa jaaye (max 8), kyunki
            # connector budget bhi asli constraint hai aur nirbharta ₹0
            # providers par hai.
            axis_base = self.planner.clean_query(question)
            for rung in axes_next_queries(axes, axis_records, axis_base,
                                          round_no=round_no,
                                          limit=axis_budget):
                query = rung["query"]
                if query and query not in queries:
                    queries.append(query)
                    axis_queries.setdefault(rung["axis_id"], []).append(query)

            for q in queries:
                if q and q not in queries_run:
                    queries_run.append(q)
            self._track(job_id, "DISCOVERING",
                        f"round {round_no}: {', '.join(queries)[:120]}")

            try:
                found = self.discovery.discover(
                    queries=queries,
                    plan=plan["connectors"],
                    max_per_connector=config.max_per_connector,
                    max_web=config.max_sources,
                    round_no=round_no,
                    exclude_urls=seen_this_run,
                    # Spec §13 — network par bhi rail. Har round ka apna budget.
                    budget_seconds=getattr(config, "discovery_seconds", None),
                )
            except Exception as exc:
                # §15 — ek round ka crash poori research ko nahi maar sakta.
                # Loop agla round chalata rehta hai, aur is round ke records
                # khaali maane jaate hain — "0 mila" nahi, "dekha hi nahi ja
                # saka". Audit mein insaani line jaati hai, raw exception sirf
                # sabse neeche ke technical block mein.
                round_errors.append(f"round {round_no}")
                round_error_details.append(
                    f"discovery round {round_no} crashed: "
                    f"{type(exc).__name__}: {exc}")
                logs.append({"connector": f"discovery round {round_no}",
                             "count": 0, "reason": "error",
                             "error": "ye round beech mein ruk gaya — raw "
                                      "wajah technical details mein hai"})
                found = {"records": [], "log": [], "connectors_searched": [],
                         "seen_urls": set()}
            external.extend(found["records"])
            logs.extend(found["log"])
            connectors = sorted(set(connectors) | set(found["connectors_searched"]))
            seen_this_run |= set(found.get("seen_urls", set()))

            pack = self.evidence.build_pack(
                question=question,
                doc_records=doc_records,
                external_records=external,
                max_sources=config.max_sources,
                max_per_origin=3,
                connectors_searched=connectors,
                rounds_run=round_no,
                chars_per_source=config.chars_per_source,
                queries=queries_run,
            )
            self._counts(job_id, sources=len(pack.sources),
                         documents=len(pack.document_sources()))

            sufficiency = self.evidence.needs_another_round(
                pack, is_scientific=plan.get("is_scientific", False))
            # §5 — per-axis coverage har round ke baad naapte hain, aur agla
            # round isi par targeted hota hai.
            axis_records = axis_coverage(axes, pack.sources, searched=axis_queries)
            axis_gaps = int(coverage_summary(axis_records).get("mandatory_missing") or 0)
            if round_no >= config.max_rounds:
                break
            # "Itne sources aa gaye" ab round rokne ki KAAFI wajah nahi hai —
            # pichhli baar 18 sources ke saath 7 zaroori raaste khaali the aur
            # loop pehle hi round mein "sufficient" keh kar ruk gaya tha.
            if sufficiency.get("sufficient") and not axis_gaps:
                break

            # Agla round shuru hone se PEHLE: jo sources ab tak ASLI ME mile,
            # unse naye lens seekho — author (jo naam 2+ sources me aaya),
            # venue se field, aur wo phrase jo 2+ ALAG sources me dohraya gaya.
            # Ek bhi model call nahi (intel ki shart: "gimini ka queta bhi
            # khatam na ho"). Ye sirf AGLI QUERIES badalta hai — scoring anchor
            # nahi, warna ek hi run me round-1 aur round-2 ke score tulnaayog
            # nahi rehte. Lens evidence NAHI hai: plan par `verified` False hi
            # rehta hai.
            try:
                self.planner.absorb_corpus_lenses(question, pack.sources)
            except Exception:
                pass  # lens ek sudhaar hai, zaroorat nahi — pipeline na ruke

        if pack is None:      # koi round hi nahi chala (max_rounds=0 jaisa case)
            pack = self.evidence.build_pack(
                question=question, doc_records=doc_records, external_records=[],
                max_sources=config.max_sources, rounds_run=0,
                chars_per_source=config.chars_per_source, queries=queries_run)
            axis_records = axis_coverage(axes, pack.sources, searched=axis_queries)

        return {
            "pack": pack, "log": logs, "rounds_run": rounds_run,
            "connectors": connectors, "sufficiency": sufficiency,
            "urls": sorted(seen_this_run - seen),
            "queries": queries_run,
            "round_errors": round_errors,
            "round_error_details": round_error_details,
            # §5 ka record — axes khud, per-axis coverage, aur kis axis par
            # kaunsi query gayi. Teeno report/gate ke liye machine-readable.
            "axes": [a.to_dict() for a in axes],
            "axis_coverage": axis_records,
            "axis_queries": {k: list(v) for k, v in axis_queries.items()},
            "axis_summary": coverage_summary(axis_records),
        }

    # ── prior art honesty (₹0 patent batch, point 8) ─────────────────────────
    # "Koi matching patent nahi mila" ka matlab "idea novel hai" NAHI hota.
    # Patent search coverage kabhi poori nahi hoti — applications 18 mahine tak
    # publish hi nahi hoti, har jurisdiction search nahi hui, aur provider
    # quota/timeout se ruk bhi sakta hai. Isliye engine yahan sirf itna likhta
    # hai: kaunse patent source SACH MEIN search hue, kaun ruk gaya, aur unme
    # kitne prior-art signal mile. Legal novelty/patentability ki opinion kabhi
    # nahi jaati (wo kaam patent attorney ka hai, engine ka nahi).
    def _patent_prior_art(self, plan: Dict, discovered: Dict,
                          pack: EvidencePack) -> Dict:
        requested = list(plan.get("patents") or [])
        intent = dict(plan.get("patent_intent") or {})
        out: Dict = {
            "requested": bool(requested),
            "providers_planned": requested,
            "providers_searched": [],
            "providers_stopped": [],
            "hits": 0,
            "families": 0,
            "reason": str(intent.get("reason", "")),
            "note": "",
        }
        if not requested:
            # Patent search maangi hi nahi gayi thi — ye koi kami nahi hai, par
            # wajah likhi rehni chahiye (planner ka apna reason).
            return out

        stopped_reasons = tuple(getattr(self.discovery, "_STOPPED_REASONS", ())
                                or ("rate_limited", "blocked", "timeout",
                                    "no_key", "deadline", "no_query", "error"))
        searched: List[str] = []
        stopped: List[str] = []
        for entry in discovered.get("log") or []:
            name = str(entry.get("connector", "") or "")
            if name not in requested:
                continue
            reason = str(entry.get("reason", "") or "")
            if reason in stopped_reasons or entry.get("error"):
                if name not in stopped:
                    stopped.append(name)
            elif name not in searched:
                searched.append(name)
        # Ek provider jo ek round mein chala aur doosre mein ruka — usse "chala"
        # hi maana jaata hai (uska data pack mein hai), par stopped list mein
        # bhi wo dikh jaata hai taaki adhoori coverage chhupe na.
        out["providers_searched"] = searched
        out["providers_stopped"] = [n for n in stopped]

        patents = pack.patent_sources() if hasattr(pack, "patent_sources") else []
        out["hits"] = len(patents)
        try:
            out["families"] = int(pack.patent_family_count())
        except Exception:          # pragma: no cover - purane pack objects
            out["families"] = len(patents)
        out["note"] = novelty_note(
            hit_count=out["hits"],
            providers_searched=searched,
            providers_stopped=out["providers_stopped"],
            families=out["families"],
        )
        return out

    # ── 3. gemini passes (budget-aware) ──────────────────────────────────────
    def _remember_dead_ends(self, question: str, discovered: Dict,
                            reading: Dict) -> None:
        """
        Jo raaste is sawal par bekaar gaye, unhe memory mein likho.

        Kya count hota hai dead end:
          * koi connector error de kar gira (API down, code bug)
          * koi connector CHALA HI NAHI (rate limit / key missing / timeout /
            time budget) — ye alag line se likha jaata hai, kyunki ise
            "0 result mila" likhna jhooth hai aur wo jhooth agle sawal ke
            prompt tak pahunch jaata hai
          * koi connector chala par sach mein 0 result diya
          * kisi source ka full text na mil paya (paywall / no free route)

        Ye BLOCK list nahi hai — agli baar connector phir bhi try hoga. Fayda
        sirf ye hai ki `context_note()` mein ye baat prompt tak pahunchti hai,
        aur user ko dikh jaata hai ki is topic par kya-kya nahi chala.
        """
        if not self.memory:
            return
        topic = question[:60]
        try:
            for entry in discovered.get("log", []):
                name = entry.get("connector", "unknown")
                reason = entry.get("reason") or ""
                if reason in SourceDiscovery._STOPPED_REASONS:
                    # search hui hi NAHI — ise "0 result mila" likhna jhooth hoga,
                    # aur wo jhooth agli baar prompt tak pahunch jaata hai
                    self.memory.remember_dead_end(
                        f"{name} ({topic})",
                        f"search chali hi nahi [{reason}]: {str(entry.get('error'))[:100]}")
                elif entry.get("error"):
                    self.memory.remember_dead_end(
                        f"{name} ({topic})", f"fail: {str(entry['error'])[:120]}")
                elif reason == "filtered":
                    self.memory.remember_dead_end(
                        f"{name} ({topic})",
                        "result aaye par sab topic se door the (relevance guard)")
                elif not entry.get("count"):
                    self.memory.remember_dead_end(
                        f"{name} ({topic})", "chala par 0 result mila")
            for entry in reading.get("entries", []):
                if not entry.get("ok") and entry.get("reason"):
                    self.memory.remember_dead_end(
                        f"full text: {(entry.get('title') or entry.get('url') or '')[:50]}",
                        str(entry["reason"])[:120])
        except Exception:
            # memory likhna research fail karne ka kaaran nahi hona chahiye
            pass

    @staticmethod
    def _split_hypotheses(text: str) -> tuple:
        """
        Synthesis output se '## Hypothesis N' blocks alag karo, taaki wo body
        mein bhi na dohrayen aur structured section 8 mein saaf render hon.
        """
        # Hypothesis parser jin common provider headings ko samajhta hai, body
        # splitter ko bhi wahi samajhne chahiye. Warna `## H1` final answer mein
        # reh jaata aur structured hypotheses khaali milti.
        heading = (
            r"(?:hypothesis(?:\s*#?\s*\d+)?|h\s*#?\s*\d+|"
            r"\d+\s*[\).:\-]?\s*hypothesis)"
        )
        match = re.search(r"^\s*#{1,6}\s*" + heading + r"\b", text or "",
                          re.IGNORECASE | re.MULTILINE)
        if not match:
            return text, ""
        return text[:match.start()].rstrip(), text[match.start():].strip()

    # ── maangi hui extra sections ka RECOVERY ────────────────────────────────
    # Pichhle live run ka pattern: analysis pass (pehli call) mein model ne
    # variables aur equations likhe the, par synthesis pass 429 ke baad adhoora
    # raha aur final answer mein wo hissa gayab ho gaya. Us haalat mein wo kaam
    # SACH MEIN ho chuka hai — use phenk dena do tarah se galat hai: user ki
    # maangi hui cheez gum ho jaati hai, aur ledger jhooth-mooth "nahi bana"
    # likhta hai. Isliye analysis se wahi block wapas nikaal kar canonical
    # heading ke neeche jod dete hain. Kuch NAYA generate nahi hota — jo text
    # pehle se model ne likha tha, wahi move hota hai.
    _MATH_TITLE_RE = re.compile(
        r"mathematic|optimi[sz]|equation|formula|model|गणित|समीकरण|मॉडल",
        re.IGNORECASE)
    _CHAIN_TITLE_RE = re.compile(
        r"second[\s\-]?order|chain|ripple|cascad|knock[\s\-]?on|downstream|"
        r"indirect|दूसरे\s*क्रम|श्रृंखला|अप्रत्यक्ष",
        re.IGNORECASE)
    _ANY_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]*(.+?)[ \t]*$", re.MULTILINE)

    @classmethod
    def _extract_block(cls, text: str, title_re) -> str:
        """
        Jis heading ka naam `title_re` se match kare, uska poora body lauta do
        (agli same-ya-upar level ki heading tak). Heading khud nahi lautti —
        canonical heading synthesizer lagata hai.
        """
        body = text or ""
        matches = list(cls._ANY_HEADING_RE.finditer(body))
        for index, match in enumerate(matches):
            if not title_re.search(match.group(2)):
                continue
            level = len(match.group(1))
            end = len(body)
            for later in matches[index + 1:]:
                if len(later.group(1)) <= level:
                    end = later.start()
                    break
            block = body[match.end():end].strip()
            if block:
                return block
        return ""

    def _recover_extras(self, requests: Dict, answer: str, analysis: str) -> tuple:
        """
        `(naya_answer, notes)` — jo maanga tha aur final answer mein nahi hai,
        par analysis mein hai, use wapas le aao.
        """
        text = answer or ""
        notes: List[str] = []
        plans = (
            ("wants_math_model", looks_like_math_model, self._MATH_TITLE_RE,
             "## Mathematical Model", "Mathematical model"),
            ("wants_second_order", looks_like_chain, self._CHAIN_TITLE_RE,
             "## Second-Order Effects", "Second-order effects ki chain"),
        )
        for key, detector, title_re, heading, label in plans:
            if not (requests or {}).get(key):
                continue
            if detector(text):
                continue
            block = self._extract_block(analysis or "", title_re)
            if not block or not detector(block):
                continue
            text = f"{text.rstrip()}\n\n{heading}\n{block}".strip()
            notes.append(f"{label} final answer mein nahi aaya tha, par research "
                         f"ke andar ban chuka tha — use wahan se wapas le kar "
                         f"jod diya gaya (naya kuch nahi likha gaya).")
        return text, notes

    @staticmethod
    def _evidence_text(pack: Optional[EvidencePack]) -> str:
        """
        §17 — jo text SACH mein sources se aaya hai, sirf wahi.

        Iska ek hi kaam hai: batana ki calculation ka koi input sources/question
        se aaya tha ya model ne khud gadha tha. Isliye yahan sirf snippet aur
        padhe gaye passages jaate hain — humara khud ka likha kuch nahi.
        """
        if pack is None:
            return ""
        parts: List[str] = []
        for src in getattr(pack, "sources", []) or []:
            for field_name in ("title", "snippet"):
                value = getattr(src, field_name, "") or ""
                if value:
                    parts.append(str(value))
        for passage in getattr(pack, "passages", []) or []:
            value = getattr(passage, "text", "") or ""
            if value:
                parts.append(str(value))
        return "\n".join(parts)

    def _run_passes(self, question: str, pack: EvidencePack, plan: Dict, config,
                    contradiction_dicts: List[Dict], memory_note: str,
                    job_id: Optional[str] = None,
                    counter_search_performed: Optional[bool] = None) -> Dict:
        """
        Budget mapping (free tier ka asli constraint):
            1 call  → sirf analysis (wahi final answer banta hai)
            2 calls → analysis + synthesis (critique synthesis prompt ke andar)
            3 calls → analysis + [critique (+hypothesis)] + synthesis
            4-5     → analysis + critique + dedicated hypothesis + synthesis
                      (sirf CUSTOM mode, jahan user khud budget badha sakta hai)
        """
        brain = GeminiReasoning(budget=config.gemini_calls)
        out = {"analysis": "", "critique_raw": "", "hypothesis_raw": "",
               "final": "", "errors": [], "calls": 0, "critique": {},
               "hypotheses": [],
               # Reasoning ka LEDGER — kaun-kaun se pass chalne the aur kaun sach
               # mein chale. Ye evidence honesty gate ko chahiye: pichhle live
               # test mein MAXIMUM ke 3 pass mein se sirf 1 chala tha (Gemini
               # 429), phir bhi report "✅ VERIFIED" chhaap rahi thi. Ginti
               # `calls_used` se nahi le sakte — wo "kitni API call hui" batata
               # hai, "kaam poora hua ya nahi" nahi.
               "planned_passes": [], "done_passes": [],
               # user ne kya maanga tha — report ke ledger tak jaata hai
               "requests": {}, "hypothesis_requested": False,
               "hypothesis_count": 0, "attempts": 0, "models_tried": [],
               "usage_note": "", "notes": [],
               # point 11/10 — evidence gate ki ginti aur (LLM na chale to)
               # system ka khud banaya deterministic research plan
               "hypothesis_gate": {}, "hypothesis_plan": {},
               # §9/§14 — wajah insaani bhasha mein + raw detail alag
               "failure_kind": "", "failure_reason": "",
               # §17 — calculation ke structured record (formula, inputs, units,
               # assumptions, result + teen alag check). `None` matlab extraction
               # chali hi nahi; khaali list matlab chali aur ek bhi hisaab nahi
               # mila. Ye farak hi wo jhooth rokta hai jisme report "numeric
               # sanity check passed" likh deti thi bina koi calculation ke.
               "calculations": None, "calculations_done": None,
               "technical_details": [], "api_accounting": {}}

        # P0-B — evidence exists BEFORE any model-generated factual prose.
        # The private manifest retains source text only for runtime audit;
        # the compact form exposes hashes/locators/counts without copying
        # source passages into API diagnostics.
        draft_manifest = build_evidence_draft_manifest(question, pack)
        evidence_first_block = draft_manifest.prompt_block()
        out["_evidence_first_manifest"] = draft_manifest
        out["evidence_first_manifest"] = draft_manifest.to_dict()

        # ── user ki EXPLICIT requests (planner ne rule-based nikaali hain) ────
        # Ye pichhle live run ka sabse bada sabak hai: prompt mein saaf likha tha
        # "kam se kam 3 nayi hypotheses banao", par engine ka andar ka
        # `should_generate()` heuristic "zaroorat nahi thi" keh kar 0 hypotheses
        # de gaya. Explicit request heuristic se OOPAR hai — user ne maanga hai
        # to banana hi hai, aur na bane to saaf likhna hai ki kyun nahi bana.
        requests = plan.get("requests") if isinstance(plan, dict) else {}
        requests = requests or {}
        out["requests"] = requests
        asked_count = int(requests.get("hypothesis_count") or 0)
        explicit_hypotheses = bool(requests.get("wants_hypotheses")) or asked_count > 0

        # grade_evidence ek human-readable string deta hai ("⚠️ MIXED — ..."),
        # isliye keyword nikaal kar bhejte hain.
        # check_reasoning=False jaan-boojh kar: ye grade reasoning se PEHLE nikal
        # raha hai, to "reasoning adhoora hai" yahan har baar sach hoga aur
        # hypothesis ka faisla galat kar dega. Final grade (step 9) par poora
        # gate lagta hai.
        graded = self.evidence.grade_evidence(
            pack, check_reasoning=False) if pack.sources else ""
        level_hint = next((word for word in ("UNVERIFIED", "VERIFIED", "STRONG",
                                             "MIXED", "WEAK") if word in graded), "")
        want_hypothesis = explicit_hypotheses or self.hypotheses.should_generate(
            plan, pack, contradiction_dicts, level_hint)
        # ── evidence gate (point 11) ─────────────────────────────────────────
        # Ab tak `hypothesis_count` sirf request ya flat default 2 tha. Uska
        # nateeja: 1 patle source par bhi 2-3 hypotheses maangi jaati thi, aur
        # model unhe bhar deta tha — yaani "hypothesis" naam par andaaza.
        # `gate` asli ginti karta hai (relevant source, kitne gehrai tak padhe,
        # takraav) aur uski wajah insaani bhasha mein deta hai.
        #
        # Jaan-boojh kar: explicit request ko gate ke SAATH mila kar dekha jaata
        # hai. User ne 3 maangi to 3 hi maangi jayengi — par sirf tab tak jab tak
        # evidence 3 ki ijaazat deta hai; warna ginti kategi aur gate ki wajah
        # prompt ke andar aur report mein jaayegi, taaki kami ka ilzaam galat
        # jagah (quota) par na jaaye.
        gate = self.hypotheses.gate(pack, requested=asked_count,
                                    contradictions=contradiction_dicts)
        out["hypothesis_gate"] = gate.to_dict()
        # Kitni maangi thi: explicit number ho to wahi, warna gate jitni imaandaari
        # se utha sakta hai (purana flat default 2 iski jagah tha).
        #
        # 2026-08-21 (cross-domain benchmark): purana rule "EXPLICIT request gate
        # se OOPAR hai" jhooth paida kar raha tha. 2 patle sources par bhi
        # "kam se kam 3 hypotheses banao" par model teen bhar deta tha — gate
        # allowed=1 kehta tha aur report mein teen chhapti thi. Maangi hui ginti
        # ab bhi poori izzat paati hai JAB evidence ijaazat de (aam haalat), par
        # evidence patla ho to ginti gate par kategi aur kami ka asli kaaran
        # (evidence, quota nahi) saaf likha jaayega.
        hypothesis_count = asked_count if asked_count else max(1, gate.allowed or 1)
        if asked_count and 0 < gate.allowed < asked_count:
            hypothesis_count = gate.allowed
            out["notes"].append(
                f"Aapne {asked_count} hypotheses maangi thi, par evidence ke hisaab "
                f"se sirf {gate.allowed} imaandaari se ban sakti hai: {gate.reason}")
        out["hypothesis_allowed"] = hypothesis_count
        if not explicit_hypotheses and gate.allowed <= 0:
            # 0 relevant source par hypothesis maangna hi galat hai — na maango,
            # aur wajah likh do (khaali template se behtar).
            want_hypothesis = False
            out["notes"].append(f"Nayi hypothesis nahi maangi gayi: {gate.reason}")
        out["hypothesis_requested"] = want_hypothesis
        out["hypothesis_count"] = asked_count

        # ── kya-kya chalna THA (budget + config se, quota se pehle) ───────────
        # Ye list neeche ke `if` conditions ko hi dohrati hai, isliye budget
        # badalne par dono jagah badalna padega — par yahi imaandaar tarika hai:
        # "3 calls ka budget tha" aur "3 pass zaroori the" ek baat nahi hai
        # (bina red team wale mode mein 3 pass plan hi nahi hote, aur unhe
        # "adhoora" batana bhi jhooth hoga).
        out["planned_passes"].append("analysis")
        if config.use_red_team and config.gemini_calls >= 3:
            out["planned_passes"].append("critique")
        # hypothesis ab LEDGER ka hissa hai. Pehle ye list mein hi nahi tha,
        # isliye 0 hypotheses aane par kahin darj nahi hota tha ki ek plan kiya
        # hua kaam fail hua hai — report seedha "zaroorat nahi thi" likh deti thi.
        #
        # Par plan sirf wahi kaam ban sakta hai jiske liye SACH mein ek raasta
        # hai. 1-call (QUICK) mode mein hypothesis ke do hi raaste hain: user ne
        # khud maanga ho (tab wo pass A ke prompt mein chala jaata hai), ya 2+
        # call ka budget ho (tab critique/synthesis prompt ke andar). In dono ke
        # bina "hypothesis planned tha" likhna khud ko jhoothi kami dena hai —
        # report "1/2 pass" dikha kar run ko adhoora bata deti thi, jabki us
        # mode mein wo pass chal hi nahi sakta.
        if want_hypothesis and (explicit_hypotheses or config.gemini_calls >= 2):
            out["planned_passes"].append("hypothesis")
        if config.gemini_calls >= 2:
            out["planned_passes"].append("synthesis")

        # ── PASS A: analysis ────────────────────────────────────────────────
        self._track(job_id, "SPECIALIST_ANALYSIS",
                    f"{len(pack.sources)} sources par reasoning (budget {config.gemini_calls})")
        try:
            if pack.sources:
                prompt = brain.prompt_analysis(question, pack, plan)
                if memory_note:
                    prompt = f"{memory_note}\n\n{prompt}"
                # P0-B is appended LAST so broad source/context text cannot
                # silently override the critical-claim preselection contract.
                prompt = f"{prompt}\n\n{evidence_first_block}"
                # EXPLICIT request ho to hypotheses PEHLI call mein hi maang lete
                # hain. Wajah: quota kabhi bhi khatam ho sakti hai (429 pichhli
                # baar pass 2 par hi laga tha). Pehli call sabse zyada chance
                # wali call hai, isliye user ki saaf-saaf maangi hui cheez usi
                # mein aani chahiye — baad ke passes par nahi chhodni chahiye.
                if explicit_hypotheses:
                    self._track(job_id, "HYPOTHESIS",
                                f"{hypothesis_count} hypotheses (pehli call ke andar)")
                    prompt += self.hypotheses.prompt_appendix(hypothesis_count)
                text = brain.generate(prompt, "analysis")
                if explicit_hypotheses and text:
                    body, hypothesis_part = self._split_hypotheses(text)
                    out["analysis"] = body or text
                    out["hypothesis_raw"] = hypothesis_part
                else:
                    out["analysis"] = text
            else:
                no_source_prompt = brain.prompt_no_sources(question, plan)
                no_source_prompt = f"{no_source_prompt}\n\n{evidence_first_block}"
                out["analysis"] = brain.generate(
                    no_source_prompt, "no-source answer")
        except QuotaExhausted as exc:
            out["errors"].append(str(exc))

        # ── PASS B: critique (+hypothesis) ──────────────────────────────────
        if out["analysis"] and brain.remaining >= 2 and config.use_red_team:
            self._track(job_id, "CRITIQUE", "self-falsification pass")
            prompt = self.critic.prompt(question, out["analysis"], pack, red_team=True)
            need_more = want_hypothesis and not out["hypothesis_raw"]
            if need_more:
                self._track(job_id, "HYPOTHESIS", "hypothesis generation (same call)")
                prompt += self.hypotheses.prompt_appendix(hypothesis_count)
            try:
                text = brain.generate(prompt, "critique")
            except QuotaExhausted as exc:
                text = ""
                out["errors"].append(str(exc))
            out["critique_raw"] = text
            if need_more:
                out["hypothesis_raw"] = text

        # ── PASS B2: dedicated hypothesis pass (sirf jab budget bacha ho) ────
        #
        # Spec Section 10 chahta hai ki hypothesis generation apna step ho.
        # 1-3 call wale modes mein iske liye call hi nahi bachti, isliye wahan
        # hypothesis critique/synthesis prompt ke appendix mein maangi jaati hai
        # (kam quota, wahi structured output). CUSTOM mode 5 calls tak jaa
        # sakta hai — tab ye poora dedicated prompt chalta hai, jisme sirf
        # hypothesis par focus hota hai.
        #
        # `remaining >= 2` zaroori hai: ek call synthesis ke liye bachani hai,
        # warna final answer hi nahi banega.
        if (want_hypothesis and not out["hypothesis_raw"] and out["analysis"]
                and brain.remaining >= 2):
            self._track(job_id, "HYPOTHESIS", "dedicated hypothesis pass (alag call)")
            try:
                out["hypothesis_raw"] = brain.generate(
                    self.hypotheses.prompt(question, out["analysis"], pack, plan,
                                           contradiction_dicts,
                                           count=hypothesis_count, gate=gate),
                    "hypothesis")
            except QuotaExhausted as exc:
                out["errors"].append(str(exc))

        # ── PASS C: synthesis ───────────────────────────────────────────────
        if out["analysis"] and brain.remaining >= 1:
            self._track(job_id, "SYNTHESIS", "final answer assemble ho raha hai")
            critique_text = out["critique_raw"]
            if not critique_text and config.use_red_team:
                # 2-call mode: critique ke liye alag call nahi bachi, isliye
                # synthesis prompt ke andar hi self-critique maang lete hain
                critique_text = ("(Critic pass ke liye call nahi bachi — final answer "
                                 "ke section 8 ke liye khud hi imaandaar weaknesses "
                                 "nikalo, tareef mat karo.)")
            prompt = self.synthesizer.prompt(question, out["analysis"], critique_text,
                                             out["hypothesis_raw"], pack, plan,
                                             memory_note,
                                             evidence_first_block=evidence_first_block)
            # DEEP mode mein hypothesis ke liye alag call nahi hoti — usi
            # synthesis call mein maang lete hain, aur baad mein body se
            # nikaal kar structured section 7 mein daal dete hain
            merge_hypothesis = want_hypothesis and not out["hypothesis_raw"]
            if merge_hypothesis:
                self._track(job_id, "HYPOTHESIS", "hypothesis (synthesis call ke andar)")
                prompt += self.hypotheses.prompt_appendix(hypothesis_count)
            try:
                text = brain.generate(prompt, "synthesis")
            except QuotaExhausted as exc:
                text = ""
                out["errors"].append(str(exc))
            if merge_hypothesis and text:
                body, hypothesis_part = self._split_hypotheses(text)
                out["final"] = body
                out["hypothesis_raw"] = hypothesis_part
            else:
                out["final"] = text

        # ── parse ───────────────────────────────────────────────────────────
        if out["critique_raw"]:
            out["critique"] = self.critic.parse(out["critique_raw"]).to_dict()
        # §17 — hisaab ka structured record. Ye hypothesis enrich se PEHLE
        # nikalna zaroori hai, kyunki confidence band ka ek reason code
        # ("NO_CALCULATION") isi par tika hai. Extraction deterministic hai:
        # koi LLM call nahi, aur jo formula/input likha hi nahi gaya use hum
        # khud se nahi bharte — record mein wo "missing" rehta hai.
        calc_source_text = "\n\n".join(t for t in (out["analysis"], out["final"])
                                       if t)
        calc_records = physics_checks.extract_calculations(
            calc_source_text, question=question,
            evidence_text=self._evidence_text(pack))
        out["calculations"] = [r.to_dict() for r in calc_records]
        out["calculations_done"] = physics_checks.calculations_done(calc_records)
        if out["calculations"]:
            out["errors"].extend(physics_checks.calculation_warnings(calc_records))
        if out["hypothesis_raw"]:
            parsed = self.hypotheses.parse(out["hypothesis_raw"],
                                           max_count=hypothesis_count)
            # §13-§18 — parse ke baad ka deterministic record: stable ID,
            # provenance (kaunse facts + kaunsa gap), mechanism, closest prior
            # work, novelty status (sirf whitelist ke labels), structured
            # experiment, confidence BAND (number nahi) aur validation status.
            # Ye step koi API call nahi karta — ₹0 aur repeatable.
            # `counter_search_performed` yahan zaroori hai: uske bina confidence
            # band MODERATE tak nahi ja sakta (§10 ka wahi rule).
            self.hypotheses.enrich(
                parsed, question=question, pack=pack, gate=gate,
                contradictions=contradiction_dicts,
                counter_search_performed=counter_search_performed,
                calculations_done=out["calculations_done"])
            out["hypotheses"] = [h.to_dict() for h in parsed]
            out["errors"].extend(self.hypotheses.honesty_check(parsed))
        # Maangi thi 3, mili 1 — ye chup-chaap nahi jaana chahiye. Aur wajah bhi
        # sahi honi chahiye: agar evidence hi patla tha to ilzaam quota par mat
        # daalo (gate ki asli ginti saath jaati hai).
        if asked_count and len(out["hypotheses"]) < asked_count:
            msg = (f"{len(out['hypotheses'])}/{asked_count} hypotheses hi ban paayi "
                   f"jo aapne maangi thi.")
            if not gate.sufficient and gate.reason:
                msg += f" Evidence ki haalat: {gate.reason}"
            out["errors"].append(msg)

        # ── point 10: LLM ke bina bhi kaam ka output ─────────────────────────
        # Pehle hypothesis pass fail hone par section mein khaali dhaancha ya
        # sirf "nahi ban paayi" jaata tha. Ab system khud (bina kisi API, ₹0)
        # ek research plan banata hai — open questions + agla kadam, sirf usi
        # cheez se jo retrieve hui. Ye plan hypothesis ka DAAWA nahi karta.
        short = len(out["hypotheses"]) < max(1, asked_count)
        if short and (want_hypothesis or gate.allowed <= 0):
            out["hypothesis_plan"] = self.hypotheses.fallback_plan(
                question, pack, contradiction_dicts, gate, plan)

        out["calls"] = brain.calls_used
        out["errors"].extend(brain.errors)
        out["attempts"] = brain.attempts
        out["models_tried"] = list(brain.models_tried)
        out["usage_note"] = brain.usage_note()
        # §9 — raw error user tak nahi jaata: wajah insaani bhasha mein, aur
        # protobuf/429 wali line sirf report ke sabse neeche.
        out["failure_kind"] = brain.failure_kind()
        out["failure_reason"] = brain.failure_reason()
        out["technical_details"] = brain.technical_details()
        out["api_accounting"] = brain.api_accounting()
        # notes = "retry ke baad chal gaya" type imaandaar jaankari. Ye ERROR
        # nahi hai, isliye warnings mein nahi daalte — audit section mein jaati hai.
        # `extend` (assignment nahi): gate ka note isse pehle add ho chuka hota
        # hai, aur `=` use karne se wo chup-chaap gum ho jaata tha.
        out["notes"].extend(brain.notes)

        # ── kya-kya SACH MEIN hua ────────────────────────────────────────────
        # Output se naapte hain, intention se nahi: call ho kar bhi khaali text
        # aa sakta hai (safety block / parse fail), aur wo pass "poora hua" nahi
        # hai. Sirf planned passes ko ginte hain, warna 2-call mode mein critique
        # ka na hona "failure" lagta — jabki wo design tha.
        produced = {"analysis": bool(out["analysis"]),
                    "critique": bool(out["critique_raw"]),
                    # hypothesis "hua" tabhi maana jaata hai jab jitni maangi thi
                    # utni mili — 3 maang kar 1 dena aadha kaam hai, poora nahi.
                    "hypothesis": len(out["hypotheses"]) >= max(1, asked_count),
                    "synthesis": bool(out["final"])}
        out["done_passes"] = [name for name in out["planned_passes"]
                              if produced.get(name)]
        return out

    # ── main ─────────────────────────────────────────────────────────────────
    def research(self, question: str, depth_mode: str = "DEEP",
                 custom: Optional[Dict] = None, job_id: Optional[str] = None) -> Dict:
        question = (question or "").strip()
        config = get_depth_config(depth_mode, custom)
        job_id = job_id or self.project_id
        warnings: List[str] = []

        if not question:
            return ResearchResult(
                question=question, answer="Sawal khaali hai.", mode=config.name,
                evidence_level="⚠️ UNVERIFIED — koi sawal nahi tha").to_dict()

        # 0. safety
        self._start_tracking(job_id, question)
        self._track(job_id, "PLANNING", "safety + classification")
        safety = self._safety(question)

        # 1. plan
        plan = self.planner.plan(question, config)

        # 1a. Scoring anchor. Hinglish/Devanagari sawaal par relevance scoring
        # literal token overlap karti thi, isliye perfect English paper ka score
        # 0.0 aata tha aur rank() zero source lautati thi (naapa gaya:
        # 'दिमाग तेज कैसे करें' → 0 kept). Lens plan ka English/framework
        # vocabulary yahan anchor ban kar scoring ko wo bhasha deta hai.
        # Pure-English sawaal par anchor khaali hota hai, yaani wahan ye line
        # bilkul no-op hai — purane benchmarks isliye nahi hilte.
        try:
            self.evidence.relevance.set_scoring_anchor(
                plan.get("lens_scoring_query") or "")
        except Exception:
            pass  # anchor ek sudhaar hai, zaroorat nahi — isse pipeline na ruke

        # 2. documents (hamesha)
        self._track(job_id, "PROCESSING", "uploaded documents check ho rahe hain")
        doc_records, doc_note = self._document_records(question, config)

        # 3. discovery (hamesha — PDF ho ya na ho)
        discovered = self._discover(question, plan, config, doc_records, job_id)
        pack: EvidencePack = discovered["pack"]
        discovery_note = self.discovery.discovery_note(discovered["log"])
        if not pack.sources:
            warnings.append("Kisi bhi source se relevant result nahi mila — jawab "
                            "sirf model ki general knowledge par hai, verified nahi.")
        if doc_note:
            discovery_note = f"{doc_note} | {discovery_note}"

        # 3a. PRIOR ART ka imaandaar bayaan (point 8). Ye discovery ke turant baad
        # banta hai, kyunki iske liye sirf log + pack chahiye — kisi LLM call ka
        # intezaar nahi. Quota khatam ho jaaye to bhi ye line report mein jaati hai.
        prior_art = self._patent_prior_art(plan, discovered, pack)
        if prior_art.get("requested") and not prior_art.get("providers_searched"):
            warnings.append(
                "Patent/prior-art search maangi gayi thi par koi patent provider "
                "chal nahi paaya"
                + (f" ({', '.join(prior_art['providers_stopped'])})"
                   if prior_art.get("providers_stopped") else "")
                + " — isliye is jawab mein prior art ke baare mein koi bhi dava "
                  "nahi hai, na 'mila' na 'nahi mila'.")

        # §15 — koi search round beech mein gir gaya. User ko sirf itna pata
        # chalna chahiye ki us round ka data MISSING hai (na ki "0 mila"), aur
        # raw exception ka ek shabd bhi yahan nahi aata (point 9).
        round_errors = discovered.get("round_errors") or []
        round_error_details = list(discovered.get("round_error_details") or [])
        if round_errors:
            warnings.append(
                f"{len(round_errors)} search round technical wajah se poora nahi "
                f"ho paaya ({', '.join(round_errors)}) — baaki rounds chalte rahe, "
                f"par utna data is jawab mein missing hai. Details audit section "
                f"mein hain.")

        sufficiency = discovered.get("sufficiency", {})
        if sufficiency and not sufficiency.get("sufficient"):
            for reason in sufficiency.get("reasons", [])[:3]:
                warnings.append(f"Evidence limit: {reason}")

        # 3a-bis. §5 — EVIDENCE AXIS COVERAGE ka insaani bayaan.
        #
        # Dark-matter run ki sabse badi chuppi yahi thi: report ne "18 sources"
        # ginaye aur ek baar bhi nahi kaha ki CMB, BBN, Bullet Cluster, lensing,
        # LSS aur dwarf galaxies par ek bhi saboot nahi tha. Ginti badi thi,
        # coverage lagbhag zero. Isliye ab ginti ke saath-saath ye bhi report
        # mein jaata hai ki KAUNSA SABOOT KA RAASTA KHAALI reh gaya.
        #
        # `axis_records` khaali ho to koi dava nahi hota: na "cover ho gaya",
        # na "nahi hua" — sirf "naapa nahi gaya" (tri-state rule).
        axis_records = list(discovered.get("axis_coverage") or [])
        axis_summary = dict(discovered.get("axis_summary") or {})
        axis_note = axis_coverage_note(axis_records) if axis_records else ""
        axis_counter_search = counter_search_done(axis_records)
        man_missing = axis_summary.get("mandatory_missing")
        if man_missing:
            labels = ", ".join(axis_summary.get("missing_labels") or [])
            warnings.append(
                f"Saboot ke {man_missing} zaroori raaste khaali hain"
                + (f" ({labels})" if labels else "")
                + f" — kul {axis_summary.get('axes_total', 0)} raaston mein se "
                  f"{axis_summary.get('axes_covered', 0)} par hi relevant source "
                  f"mila. Source ki ginti isse nahi dhakti: is jawab ko poora "
                  f"nahi maanein.")

        # 3b. READING (Spec Section 3/4/5) — top sources ka legally-free full
        # text. Ye Gemini ki ek bhi call nahi kharchta; iska budget alag hai
        # (config.max_fulltext). Yahi wo step hai jo "search kiya" ko "padha"
        # banata hai — aur jo nahi padh paye, uska honest reason bhi deta hai.
        self._track(job_id, "READING",
                    f"top {config.max_fulltext} sources ka full text padha ja raha hai")
        reading = self.reader.enrich(pack, max_sources=config.max_fulltext,
                                     budget_chars=config.chars_per_source * 2)
        if reading.get("note"):
            discovery_note = f"{discovery_note} | Reading: {reading['note']}"
        self._counts(job_id, full_text_read=reading.get("succeeded", 0))
        if reading.get("attempted") and not reading.get("succeeded"):
            warnings.append(
                "Kisi bhi source ka full text nahi mil paya — jawab sirf "
                "abstract/snippet level par hai. Wajah: "
                + (reading.get("entries", [{}])[0].get("reason", "unknown"))[:120])

        # Specialist topics get a deterministic, structured evidence boundary
        # before any model reasoning.  This does not upgrade source quality; it
        # only prevents official records, traditions, allegations and empirical
        # findings from being blended into one truth bucket.
        specialist_report = build_evidence_lane_report(question, plan, pack)
        if specialist_report.get("active"):
            self._track(job_id, "SPECIALIST_ANALYSIS",
                        "official/traditional/scientific/claim lanes alag ki ja rahi hain")
        if specialist_report.get("unknown_terms"):
            warnings.append(
                "Ek term ka meaning reliably resolve nahi hua ("
                + ", ".join(specialist_report["unknown_terms"])
                + ") — app ne uska matlab invent nahi kiya."
            )

        # 4. contradictions (local, free)
        self._track(job_id, "EVIDENCE_ANALYSIS", "contradiction + independence check")
        contradiction_objects = self.contradictions.detect(pack)
        contradiction_dicts = [c.to_dict() for c in contradiction_objects]
        # §11 — jo "takraav" jaanch kar hataye gaye (sirf saal ka farq, topic hi
        # alag, direction ulti nahi), unka hisaab audit mein jaata hai. Ye report
        # `detect()` ke baad hi padhni hai, warna pichhle run ka data mil jayega.
        contradiction_rejections = self.contradictions.rejection_report()
        self._counts(job_id, conflicts=len(contradiction_dicts))

        # 5. memory + knowledge graph hints
        memory_note = self.memory.context_note(question) if self.memory else ""
        graph_note = self.graph.related_note(question, self.project_id)
        if graph_note:
            memory_note = f"{memory_note}\n\n{graph_note}".strip()

        # 6. gemini passes
        passes = self._run_passes(question, pack, plan, config, contradiction_dicts,
                                  memory_note, job_id,
                                  counter_search_performed=axis_counter_search)
        # §9 — engine ke raw error (429/protobuf/exception class) warnings mein
        # nahi jaate. Warning insaani bhasha mein, raw line report ke sabse
        # neeche. Pichhle live run mein yahi text "Seedha jawab" ke neeche
        # chhap gaya tha.
        human_errors, technical_errors = split_messages(passes["errors"])
        warnings.extend(human_errors)
        # Wajah insaani bhasha mein. Ledger se aaye to wahan se, warna raw line
        # se padh kar — par kisi bhi haalat mein user ko warning MILNI chahiye.
        # Pehle raw line hat jaati thi aur uski jagah kuch nahi aata tha, yaani
        # failure chup-chaap gayab ho jaati thi.
        failure_reason = (passes.get("failure_reason")
                          or human_reason(passes["errors"]))
        if failure_reason and not any(failure_reason in w for w in warnings):
            warnings.append(
                f"AI reasoning model se poora kaam nahi ho paaya — "
                f"{failure_reason}.")
        elif technical_errors and not failure_reason:
            warnings.append("AI reasoning model se poora kaam nahi ho paaya — "
                            "kuch reasoning pass adhoore reh gaye.")
        self._counts(job_id, gemini_calls=passes["calls"])

        # Reasoning ka sach pack mein daalo — grade_evidence ka teesra honesty
        # gate ISI par tika hai. Pehle ye jaankari kahin record hi nahi hoti
        # thi, isliye "1 of 3 passes ran (quota 429)" ke saath bhi report
        # "✅ VERIFIED" chhaap deti thi. Ab adhoora reasoning top label rok deta
        # hai aur wajah bhi likhta hai.
        pack.reasoning_planned = len(passes["planned_passes"])
        pack.reasoning_done = len(passes["done_passes"])
        missing = [name for name in passes["planned_passes"]
                   if name not in passes["done_passes"]]
        # §9 — `reasoning_failures` seedha user ke saamne aata hai (banner,
        # confidence note, evidence level). Isliye yahan RAW error line kabhi
        # nahi daalte: sirf insaani wajah. Raw text ka ek hi ghar hai —
        # report ke sabse neeche "Technical details".
        pack.reasoning_failures = (
            ([f"{', '.join(missing)} pass poora nahi hua"] if missing else [])
            + ([failure_reason] if failure_reason else [])
            + human_errors[:2]
        )

        # §11 — consensus AB banta hai, reasoning ke BAAD. Pehle ye step 4 mein
        # banta tha, jahan ye pata hi nahi hota tha ki reasoning pass poore honge
        # ya quota se mar jayenge — aur wahi adhoora run "apparent agreement"
        # chhaap deta tha. Gate ko dono jaankari chahiye: contradiction analysis
        # chali (list mili, None nahi) aur reasoning poora hua ya nahi.
        consensus = self.contradictions.consensus_report(
            pack, contradiction_objects,
            contradiction_analysis_done=True,
            reasoning_complete=pack.reasoning_complete,
            queries=list(pack.search_queries or discovered.get("queries") or []),
        )
        if not consensus.get("gate_passed"):
            self._track(job_id, "EVIDENCE_ANALYSIS",
                        "consensus gate: shartein poori nahi — level nahi banaya")

        gemini_answer = passes["final"] or passes["analysis"]
        if not gemini_answer:
            # §8 (2026-08-21) — pehle yahan `extractive_summary()` chalta tha, jo
            # SIRF "## Seedha jawab" bharta tha. Nateeja: quota marne par report
            # ke teen insaani section ("Research se kya pata chala?", "Ye kyun
            # hota hai?", "Kya abhi unknown hai?") "kaunse hisse nahi ban paaye"
            # list mein chale jaate the aur jawab kamzor lagta tha — intel ki
            # exact shikayat.
            #
            # Ab engine ka apna offline reasoning chalta hai: wahi PADHE hue
            # sources, deterministic (wahi pack -> wahi jawab), ₹0, koi API nahi.
            # Ye STATUS nahi badalta — reasoning pass sach mein nahi chala, isliye
            # report ab bhi imaandaari se "RESEARCH INCOMPLETE" kehti hai. Farak
            # sirf itna hai ki koi section khaali nahi rehta.
            from .local_reasoning import compose as compose_offline

            gemini_answer = compose_offline(question, pack, plan,
                                            contradiction_dicts)
            warnings.append(
                "AI reasoning model is baar nahi chala (free limit khatam thi), "
                "isliye ye jawab engine ke apne offline reasoning se bana hai — "
                "sirf un sources se jo sach mein padhe gaye. Har section bhara "
                "hua hai, par multi-angle AI reasoning ka dava nahi hai.")
            if not gemini_answer.strip():
                # aakhri suraksha jaal — purana raasta, taaki jawab kabhi khaali
                # na jaaye
                gemini_answer = self.synthesizer.extractive_summary(question, pack)

        # 6b. maangi hui extra sections ka recovery (math model / second-order
        # chain). Ye Gemini ki ek bhi nayi call nahi karta — sirf analysis pass
        # ka pehle se likha hua block wapas laata hai.
        engine_notes: List[str] = [str(n) for n in passes.get("notes", [])]
        # Prior-art line report ke notes mein jaati hai (point 8). Ye Gemini ke
        # kisi output par nirbhar nahi hai — engine ka apna, deterministic bayaan.
        if prior_art.get("note"):
            engine_notes.append(prior_art["note"])
        requests: Dict = passes.get("requests") or {}
        gemini_answer, recovered = self._recover_extras(
            requests, gemini_answer, passes["analysis"])
        engine_notes.extend(recovered)

        # 6c. LABEL GATE (intel ka rule): "[ESTABLISHED]" sirf full text padhe
        # hue source par. Ye citation verify se PEHLE chalta hai, kyunki annotate
        # baad mein isi text par lagta hai — warna downgrade annotate ke markers
        # ko kaat sakta tha. Text kabhi nahi kaata jaata, sirf label badalta hai.
        #
        # §13 (2026-08-21): ab gate mein entailment bhi shaamil hai
        # (`check_entailment=True`). Matlab: poora text padh liya ho, par us text
        # mein claim ka support hi na dikhe, to bhi label ESTABLISHED nahi
        # rehta. Ye jaan-boojh kar sirf saaf FAIL par girata hai — jahan support
        # check HO HI NA SAKE wahan chup rehta hai aur wo baat claim-check block
        # mein alag se likhi jaati hai.
        #
        # STRICT PASS pehle chalta hai (2026-08-21): "poora text mila par support
        # nahi mila" wali line ka sahi label `[UNVERIFIED]` hai, `SOURCE-REPORTED`
        # nahi — kyunki "source ye report karta hai" bhi ek dava hai jo us source
        # ne kiya hi nahi. Depth-wala downgrade uske BAAD chalta hai, aur uska
        # apna default behaviour bilkul waisa hi hai.
        gemini_answer, strict_report = enforce_strict_labels(gemini_answer, pack)
        if strict_report.get("note"):
            warnings.append(strict_report["note"])
        gemini_answer, label_report = downgrade_labels(gemini_answer, pack,
                                                       check_entailment=True)
        if label_report.get("note"):
            warnings.append(label_report["note"])

        # 6d. NOVELTY OVERCLAIM (point 8). Prompt mein rule pehle se hai, par
        # bharosa uspar nahi. Model ne phir bhi "ye idea novel hai / patentable
        # hai" jaisa dava likh diya to text kaata nahi jaata — saath mein engine
        # ka sach likh diya jaata hai, taaki user ko dono dikhein.
        overclaims = novelty_overclaim(gemini_answer)
        if overclaims:
            line = ("Jawab mein novelty/patentability jaisa dava dikha "
                    f"(\"{overclaims[0]}\") — ye engine ka nateeja NAHI hai. "
                    "Patent search coverage kabhi poori nahi hoti aur legal "
                    "novelty ki opinion sirf patent attorney de sakta hai.")
            if prior_art.get("note"):
                line += f" Asli sthiti: {prior_art['note']}"
            elif not prior_art.get("requested"):
                line += (" Is sawaal par patent search chali bhi nahi thi"
                         + (f" ({prior_art['reason']})" if prior_art.get("reason")
                            else "") + ".")
            warnings.append(line)
            engine_notes.append(line)
        # Dono pass ka hisaab ek jagah. Warna strict pass jo lines pehle hi
        # [UNVERIFIED] kar chuka hai wo depth pass ko dikhti hi nahi, aur
        # `label_report` "checked: 0, downgraded: 0" bolta hai — jabki downgrade
        # hua tha. Audit ka aankda kaam se kam nahi hona chahiye.
        label_report = merge_label_reports(strict_report, label_report)

        # 6d. §13 / point 7 — paanch alag check (A–E) har labelled claim par.
        # Purana "citation verified" number sirf ye batata tha ki [S3] naam ka
        # source pack mein hai. Ye report usse ALAG hai: citation exists (A),
        # source relevant (B), claim entailed (C), reading depth (D), source
        # quality (E) — sab alag ginte hain, aur "verified" ka dava sirf C par
        # tikta hai. Poora module deterministic hai (₹0, koi API call nahi).
        #
        # §8 (2026-08-22): verification RAW model text par nahi, canonical
        # heading view par chalti hai. Critical claim ka faisla section se hota
        # hai ("Seedha jawab" / "final conclusion"), aur model apni heading khud
        # likhta hai — isliye raw text par har critical claim non-critical ban
        # jaati thi. Live dark-matter run mein iska nateeja tha:
        # `critical_claim_evidence_spans: []` aur
        # `critical_claim_spans_complete: None`, jabki usi jawab par seedha
        # verify karne se 1 critical claim milti hai. View sirf headings ka naam
        # badalta hai — ek shabd content nahi badalta, aur assembled answer use
        # na karne se audit block ki lines dobara nahi ginti.
        claim_source_text = gemini_answer
        view = getattr(self.synthesizer, "canonical_heading_view", None)
        if callable(view):
            try:
                claim_source_text = view(gemini_answer) or gemini_answer
            except Exception:                                # noqa: BLE001
                claim_source_text = gemini_answer
        claim_checks = verify_claims(claim_source_text, pack).to_dict()
        evidence_first_audit = audit_claims_against_manifest(
            claim_checks, passes.get("_evidence_first_manifest"))
        unmatched_preselected = int(
            evidence_first_audit.get("critical_claims_preselected_span_unmatched") or 0)
        if unmatched_preselected:
            warnings.append(
                f"{unmatched_preselected} same-source supported critical claim ka "
                "canonical span drafting se pehle preselected evidence mein nahi tha; "
                "verified/release gate fail-closed rahega.")
        if claim_checks.get("overclaims"):
            warnings.append(
                f"{len(claim_checks['overclaims'])} claim par label evidence se "
                f"zyada strong tha — unhe report mein wajah ke saath mark kiya "
                f"gaya hai.")

        # 7. citation verification (structural, Gemini par bharosa nahi)
        report = self.citations.verify(gemini_answer, pack)
        annotated = self.citations.annotate(gemini_answer, pack)
        claims = self.evidence.extract_claims(gemini_answer, pack)
        if report.invalid_ids:
            warnings.append(f"{len(report.invalid_ids)} citation invalid thi "
                            f"({', '.join(report.invalid_ids[:5])}) — answer mein "
                            f"mark kar diya gaya hai.")
        if report.used_legacy_url_match:
            warnings.append("Model ne [S#] format use nahi kiya — citations URL "
                            "match se nikaali gayi hain, isliye kam bharosemand hain.")

        # 8. verification (Spec Section 11)
        self._track(job_id, "SAFETY_CHECK", "verification + honesty checks")
        verification = self.verifier.verify(
            gemini_answer, pack,
            citation_ok=not report.invalid_ids,
            ungrounded_count=len(report.ungrounded_claims),
            hypotheses=passes["hypotheses"],
            cited_ids=[c.get("source_id") for c in report.cited if c.get("source_id")],
            # point 12 — sanity checks sirf quantitative sawal par chalein,
            # isliye sawal bhi bhejna zaroori hai.
            question=question,
        ).to_dict()
        # §13 — A–E ka poora record API/Android tak bhi jaana chahiye, sirf
        # report ke text mein nahi. `verification` dict pehle se result mein
        # jaata hai, isliye naya top-level field banane ki zaroorat nahi.
        verification["claim_checks"] = claim_checks
        verification["evidence_first_audit"] = evidence_first_audit
        verification["evidence_first_manifest"] = (
            passes.get("evidence_first_manifest") or {})
        # point 11 — kitni hypotheses evidence ke hisaab se banayi ja sakti thi,
        # ye ginti bhi API/Android tak jaani chahiye (report ke text ke alawa).
        if passes.get("hypothesis_gate"):
            verification["hypothesis_gate"] = passes["hypothesis_gate"]
        if passes.get("hypothesis_plan"):
            verification["hypothesis_plan"] = passes["hypothesis_plan"]

        # 9. grading + coverage
        # Pack-level counts alone must never print VERIFIED/STRONG when the
        # answer's actual conclusion claims failed A-E.  Both final reports are
        # passed only here; the earlier pre-reasoning grade intentionally remains
        # a source-pack diagnostic for hypothesis planning.
        evidence_level = self.evidence.grade_evidence(
            pack,
            claims,
            label_report=label_report,
            claim_checks=claim_checks,
        )

        # Advanced Scientific Discovery Engine.  This is a deterministic
        # assessment of the evidence/hypotheses already produced above: no new
        # provider/network call and no arbitrary code execution.  It stays a
        # structured API field so the human-first answer is not cluttered.
        remembered_hypotheses = (
            self.memory.known_hypotheses(question, limit=12)
            if self.memory else []
        )
        try:
            discovery_analysis = self.scientific_discovery.analyze(
                question=question,
                plan=plan,
                pack=pack,
                hypotheses=passes["hypotheses"],
                contradictions=contradiction_dicts,
                verification=verification,
                remembered_hypotheses=remembered_hypotheses,
            )
        except Exception as exc:
            # Research answer must survive an auxiliary assessment failure, but
            # the failure is explicit and never promoted to a successful gate.
            discovery_analysis = {
                "schema_version": "1.0",
                "status": "ASSESSMENT_ERROR",
                "reason": "advanced discovery assessment poora nahi ho paaya",
                "human_review_required": True,
            }
            technical_errors.append(
                f"advanced discovery assessment: {type(exc).__name__}")
        coverage = pack.coverage_report()
        coverage["evidence_table"] = self.evidence.evidence_table(claims)
        coverage["independence"] = self.evidence.independence_report(pack)
        # Patent evidence ka apna block — science ke numbers mein mila kar nahi.
        # UI/Android isse padh kar "prior-art signal" dikha sakte hain bina
        # report ka text parse karne ke.
        coverage["prior_art"] = dict(prior_art)
        by_type: Dict[str, int] = {}
        for source in pack.sources:
            key = source.source_type.value
            by_type[key] = by_type.get(key, 0) + 1
        coverage["by_source_type"] = by_type
        # §5 — coverage dict machine-readable hai (UI/Android/final gate isse
        # padhte hain). Yahan "kitne mile" ke saath "kaunsa raasta khaali hai"
        # bhi jaata hai, aur khaali record par sab `None` rehta hai.
        coverage["evidence_axes"] = {
            "axes": axis_records,
            "summary": axis_summary,
            "queries": dict(discovered.get("axis_queries") or {}),
            "note": axis_note,
        }
        coverage["peer_reviewed"] = sum(1 for s in pack.sources if s.peer_reviewed is True)
        coverage["full_text_available"] = sum(1 for s in pack.sources
                                              if s.full_text_available)
        # Spec Section 2 — "search kiya" vs "padha" ka farq numbers mein
        coverage["reading"] = {
            "attempted": reading.get("attempted", 0),
            "succeeded": reading.get("succeeded", 0),
            "failed": reading.get("failed", 0),
            "skipped_over_budget": reading.get("skipped", 0),
            "chars_read": reading.get("chars_read", 0),
            "note": reading.get("note", ""),
            "per_source": [
                {"source_id": e.get("source_id", ""), "read": bool(e.get("ok")),
                 "chars": e.get("chars", 0), "reason": e.get("reason", "")}
                for e in reading.get("entries", [])
            ],
        }
        coverage["specialist_research"] = specialist_report
        honesty = {
            "citations_verified": len(report.cited),
            "cited": report.cited,
            "summary": self.citations.honesty_report(report, pack),
        }

        # Spec Section 7 — retracted/withdrawn source ka warning top level par.
        # Ye sirf coverage ke andar dabaana theek nahi hoga: agar jawab kisi
        # retracted paper par tika hai, to ye sabse pehle dikhne wali baat hai.
        retracted = pack.retracted_sources()
        if retracted:
            cited_ids = {c.get("source_id") for c in report.cited}
            cited_retracted = [s.source_id for s in retracted if s.source_id in cited_ids]
            detail = (f"aur inme se {len(cited_retracted)} ko jawab mein cite bhi kiya "
                      f"gaya hai ({', '.join(cited_retracted)})"
                      if cited_retracted else
                      "inhe jawab mein cite nahi kiya gaya")
            warnings.append(
                f"{len(retracted)} source par retraction/withdrawal ka signal hai "
                f"({', '.join(s.source_id for s in retracted if s.source_id)}) — "
                f"{detail}. Retracted kaam ko evidence ki tarah use nahi karna chahiye.")

        # 9b. REQUESTED vs DELIVERED ledger. Delivered ko answer ke TEXT se
        # naapa jaata hai, "humne maang liya tha" se nahi — pichhla run isi wajah
        # se jhooth bol gaya tha. Wajah bhi asli record se aati hai (reasoning
        # note + Gemini errors), andaaze se nahi.
        ledger_reasons: List[str] = []
        if not pack.reasoning_complete:
            ledger_reasons.append(pack.reasoning_note())
        # §9 — ledger ka "why" bhi user ko dikhta hai, isliye insaani wajah hi
        # jaati hai (pehle yahan poora `passes["errors"]` raw chala jaata tha).
        if failure_reason:
            ledger_reasons.append(failure_reason)
        ledger_reasons.extend(human_errors)
        ledger = build_ledger(
            requests,
            delivered={
                "hypotheses": len(passes["hypotheses"]),
                "math_model": looks_like_math_model(gemini_answer),
                "second_order": looks_like_chain(gemini_answer),
                "red_team": bool(passes["critique_raw"]),
            },
            reasons=ledger_reasons,
        )
        for item in ledger.get("unmet", []):
            warnings.append(
                f"Aapki request poori nahi hui: {item.get('what')} → "
                f"{item.get('got')}."
                + (f" {item.get('why')}" if item.get("why") else ""))

        # 10. final answer assemble
        #
        # §1 — status pehle nikalta hai, phir report banti hai. Pehle report
        # "poori" lagti thi chahe 3 mein se 1 hi pass chala ho; ab UI ko
        # `RESEARCH INCOMPLETE` machine-readable roop mein milta hai aur wahi
        # baat report ke top par insaani bhasha mein bhi likhi jaati hai.
        run_status = evaluate_status(
            planned_passes=passes["planned_passes"],
            done_passes=passes["done_passes"],
            failure_kind=passes.get("failure_kind", ""),
            failure_reason=passes.get("failure_reason", ""),
            source_count=len(pack.sources),
            errors=passes["errors"],
            technical_details=list(passes.get("technical_details") or [])
            + technical_errors,
        )
        status_dict = run_status.to_dict()

        # §15 — crashed search round ka RAW text bhi report se gayab nahi hota,
        # par uska ghar sirf sabse neeche wala "Technical details" block hai.
        # Ye jaan-boojh kar `evaluate_status()` ko NAHI diya jaata: wo LLM ke
        # failure_kind ka faisla karta hai, aur network/connector ka crash LLM
        # ka dosh nahi hai — warna banner galat wajah bata deta.
        technical_lines = list(run_status.technical) + round_error_details

        # §1 — adhoore run par top label "VERIFIED" nahi ho sakta, chahe
        # citations theek hon. Grading already reasoning-gate lagata hai, ye
        # doosra taala hai taaki koi bhi raasta bacha na rah jaaye. Grader ki
        # apni wajah MITAYI nahi jaati — sirf status uske aage lag jaata hai.
        if run_status.code == INCOMPLETE and INCOMPLETE not in evidence_level:
            base = re.sub(r"^[^A-Za-z]+", "", (evidence_level or "").strip())
            evidence_level = f"⚠️ {INCOMPLETE} — {base}" if base else f"⚠️ {INCOMPLETE}"

        # §10 — counter-side search ke BINA top label ("VERIFIED"/"STRONG") mana
        # hai. Wajah seedhi hai: sirf support-side dhoond kar "verified" kehna
        # apne hi nateeje ki taraf jhukna hai. `axis_counter_search` teen haalat
        # rakhta hai — True (counter axis par query gayi), False (nahi gayi),
        # None (axes hi naape nahi gaye). True ke alawa dono mein label girta
        # hai, par wajah dono ki alag likhi jaati hai (jhooth se bachne ke liye).
        #
        # Match "✅ " ke saath hai, sirf shabd se nahi: "UNVERIFIED" ke andar bhi
        # "VERIFIED" chhupa hai, aur usse MIXED banana ULTA upgrade ho jaata.
        top_label = any((evidence_level or "").startswith(f"✅ {word}")
                        for word in ("VERIFIED", "STRONG"))
        if top_label and axis_counter_search is not True:

            why = ("counter-side (criticism/replication) search nahi chali"
                   if axis_counter_search is False else
                   "counter-side search ka koi record nahi hai")
            base = re.sub(r"^[^A-Za-z]+", "", (evidence_level or "").strip())
            evidence_level = f"🟡 MIXED — {why}, isliye 'verified' nahi keh sakta"
            if base:
                evidence_level += f" (ginti se banta tha: {base})"
            warnings.append(
                "Top label isliye nahi diya gaya: " + why + ". §10 ke hisaab se "
                "support aur counter side dono par search zaroori hai.")

        # §5 — zaroori evidence axis khaali ho to bhi top label mana hai. Ye
        # counter-search gate se ALAG taala hai: counter-side chal chuki ho phir
        # bhi CMB/BBN/lensing jaise raaste khaali reh sakte hain, aur us haalat
        # mein "verified" kehna sirf source-ginti par bharosa karna hai — yahi
        # pichhli dark-matter report ki sabse badi galti thi.
        if man_missing and any((evidence_level or "").startswith(f"✅ {word}")
                               for word in ("VERIFIED", "STRONG")):
            base = re.sub(r"^[^A-Za-z]+", "", (evidence_level or "").strip())
            labels = ", ".join((axis_summary.get("missing_labels") or [])[:4])
            evidence_level = (
                f"🟡 MIXED — saboot ke {man_missing} zaroori raaste khaali hain, "
                f"isliye 'verified' nahi keh sakta")
            if base:
                evidence_level += f" (ginti se banta tha: {base})"
            warnings.append(
                f"Top label isliye nahi diya gaya: {man_missing} zaroori evidence "
                f"raaste khaali hain"
                + (f" ({labels})" if labels else "")
                + ". Source ki ginti is kami ko nahi dhakti.")

        # §17 — reasoning pass ne jo calculation records nikaale the wahi aage
        # jaate hain (ek hi jagah se: answer aur audit dono, warna do alag
        # ginti dikhti). `None` matlab extraction chali hi nahi.
        calc_records = passes.get("calculations")
        if not calc_records:
            # LLM na chala ho (offline reasoning) to bhi hisaab dhoondhna hai —
            # warna quota marne par calculation ka record chup-chaap gayab ho
            # jaata. Yahan bhi kuch "bhara" nahi jaata: text mein hisaab nahi
            # hoga to list khaali hi rahegi.
            calc_records = physics_checks.calculation_records(
                gemini_answer, question=question,
                evidence_text=self._evidence_text(pack))

        answer = self.synthesizer.assemble(
            gemini_answer=annotated,
            pack=pack,
            evidence_level=evidence_level,
            confidence_note=self._confidence_note(pack, config, passes["calls"],
                                                  sufficiency),
            contradictions=contradiction_dicts,
            hypotheses=passes["hypotheses"],
            verification=verification,
            coverage=coverage,
            honesty=honesty,
            consensus=consensus,
            discovery_note=discovery_note,
            quota_note=f"{passes['calls']}/{config.gemini_calls} calls used "
                       f"({quota_note(config)})",
            critique=passes["critique"],
            warnings=warnings,
            ledger=ledger,
            label_report=label_report,
            notes=engine_notes,
            usage_note=passes.get("usage_note", ""),
            requests=requests,
            status=status_dict,
            technical_details=technical_lines,
            api_accounting=passes.get("api_accounting") or {},
            claim_checks=claim_checks,
            hypothesis_plan=passes.get("hypothesis_plan") or {},
            specialist_report=specialist_report,
            # §17 — jo hisaab sach mein mila, uska poora record jawab mein bhi
            # dikhta hai (formula, inputs+units, assumptions, result, aur teen
            # alag check). Khaali/None hone par section chhapta hi nahi.
            calculations=calc_records,
        )
        # Synthesizer hi jaanta hai kaunse section khaali reh gaye (§10) —
        # wahi list status mein bhi jaati hai, taaki UI aur report ek hi baat kahein.
        run_status.missing_sections = list(
            getattr(self.synthesizer, "last_missing_sections", []) or [])

        # 10b. §4 + §7 + §19 — quality contract, counters aur quality_context.
        #
        # Teen alag cheezein, jaan-boojh kar alag:
        #   • contract     = is sawaal se KYA maanga gaya tha (upfront rule)
        #   • quality_ctx  = asal mein KYA hua (counters + tri-state checks)
        #   • c_ledger     = dono ka milaan (kya poora hua, kya nahi, kya pata nahi)
        #
        # Sabse ahem baat: jo check chala hi nahi uska jawab `None` rehta hai,
        # `0` nahi. Pichhli dark-matter report isi jhooth par gir gayi thi —
        # "counter-search: 0" padh kar lagta tha ki dhoonda aur kuch nahi mila,
        # jabki dhoondha hi nahi gaya tha.
        contract = quality_contract(question, config=config, requests=requests)
        # §17 ke records upar ek hi baar nikle hain (`calc_records`) — yahan
        # dobara extraction jaan-boojh kar nahi ki jaati, warna answer aur audit
        # mein do alag ginti aa sakti thi.
        quality_ctx = quality.quality_context(
            pack=pack,
            # Counters model ke apne text se — final answer ke "Sources" block
            # mein har source ka [S#] hota hai, usse ginne par har uncited
            # source "cited" ban jaata (§7 ka asli bug).
            answer_text=annotated,
            verification=claim_checks,
            evidence_first_audit=evidence_first_audit,
            # §10 ka pehla hissa: counter-side search SACH mein chali ya nahi.
            # Ye axis record se aata hai (counter axis par kam se kam ek query),
            # "kisi source mein criticism shabd tha" se nahi. Axes naape na gaye
            # hon to `None` hi rehta hai — "nahi chali" nahi.
            counter_search=axis_counter_search,
            # §17 — asli calculation records (formula, inputs, units,
            # assumptions, result + unit/recalculation/sanity/invented check).
            # Khaali list ka matlab "dekha, koi hisaab nahi mila" hai; `None`
            # ka matlab "dekha hi nahi gaya" — dono alag baatein hain.
            calculations=calc_records,
            # §19 (2026-08-22 self-audit): pehle yahan `bool(recovered) or None`
            # tha — yaani recovery na lagi ho to field `None` ho jaati thi aur
            # audit use "check HO HI NAHI SAKA" mein gin leta tha. Wo galat tha:
            # `_recover_extras` HAR run mein chalta hai, to "recovery lagi ya
            # nahi" hamesha NAAPA hua sach hai. Ab `False` ka matlab "dekha,
            # recovery ki zaroorat nahi padi" — aur ye un-run check se alag
            # dikhta hai. Server-side recovery (job layer) baad mein isi field
            # ko OR karke True kar sakta hai, to jhooth banne ka rasta nahi hai.
            recovery_used=bool(recovered),
            # Ye JAAN-BOOJH KAR `None` hai: snapshot job-server (ChatGPT-owned
            # layer) sambhalta hai, engine ke andar uska koi record hi nahi hai.
            # `False` likhna "dekha, snapshot nahi bacha" ka jhootha dava hoga.
            progress_snapshot_preserved=None,
            hypotheses=passes["hypotheses"],
            contradictions=contradiction_dicts,
            contradiction_rejections=contradiction_rejections,
            axis_coverage=axis_records or None,
        )
        # Section titles / access-depth ke dave / hypothesis-fact mix sirf
        # assembled answer mein dikhte hain, isliye doosra scan wahan par.
        quality_ctx = quality.rescan_final_answer(quality_ctx, pack=pack,
                                                  final_answer=answer)
        # §19 — "check hi nahi hua" sirf audit dict mein reh jaata tha, user ke
        # jawab mein nahi. Live dark-matter report ki galti yahi thi: counter par
        # "0" chhapa jabki wo check chala hi nahi tha. Inject rescan ke BAAD hota
        # hai (warna block ka apna text hi dobara scan ho jaata) aur §20 state
        # block se PEHLE, taaki chaar state audit ke sabse upar hi rahein.
        answer = quality.inject_unknown_block(answer, quality_ctx)
        # §7 — "retrieved ≠ cited ≠ support dene wale" ki ginti bhi user ke jawab
        # mein. Ye producer (`context_block`) bana hua tha par isse production
        # mein koi bulaata hi nahi tha — sirf tests padhte the. Live report
        # sirf "N sources use hue" likhti thi, jo bilkul wahi galti hai jo §7
        # mana karta hai ("18 retrieved ko 18 used mat banao"). Inject unknown
        # block ke BAAD hota hai taaki ginti uske upar rahe, aur §20 state block
        # se PEHLE taaki chaar state sabse upar hi rahein.
        answer = quality.inject_context_block(answer, quality_ctx)
        # §9 — paanch claim-nateeje bhi jawab mein. Ye sirf `verification`
        # JSON mein pade rehte the, isliye user ko "citation mil gayi" aur "dava
        # sach nikla" ka farak kabhi dikhta hi nahi tha.
        answer = quality.inject_claim_block(answer, quality_ctx)

        delivered: Dict = {
            "sections_present": list(quality_ctx.get("sections_present") or []),
            "hypotheses": len(passes["hypotheses"]),
            "math_model": looks_like_math_model(gemini_answer),
            "second_order": looks_like_chain(gemini_answer),
            "red_team": bool(passes["critique_raw"]),
        }
        # Sirf wahi key bhejte hain jinka jawab humein SACH mein pata hai.
        # `counter_search_performed` aur `original_hypotheses` aage ke steps
        # (§10/§13) mein aayenge — tab tak ledger inhe "pata nahi" likhega, jo
        # "0 mila" se alag aur imaandaar baat hai.
        #
        # §17 — calculations ki ginti POORE hisaab ki hai (formula + inputs +
        # units + result, aur koi check fail na hua ho). Adhoora hisaab ledger
        # mein "bani" nahi ginta.
        calc_count = physics_checks.usable_calculation_count(calc_records)
        if calc_count is not None:
            delivered["calculations"] = calc_count
        for key in ("counter_search_performed", "directly_relevant_sources",
                    "average_relevance"):
            if quality_ctx.get(key) is not None:
                delivered[key] = quality_ctx[key]
        # §5 — axis coverage ledger tak jaata hai, sirf warning tak nahi. Ek bhi
        # zaroori raasta khaali ho to `answer_complete` aur `verified_allowed`
        # dono False ho jaate hain (DEEP/MAXIMUM mein). Naapa hi na gaya ho to
        # key bheji hi nahi jaati — ledger use "check nahi hua" likhega.
        for key in ("axes_mandatory_missing", "axes_total", "axes_covered"):
            if quality_ctx.get(key) is not None:
                delivered[key] = quality_ctx[key]
        if quality_ctx.get("axes_missing_labels"):
            delivered["axes_missing_labels"] = list(
                quality_ctx["axes_missing_labels"])
        # §4 ki saat naye demands (units, experiment design, falsification,
        # confidence, readiness, source depth, tulna ke pehlu, naam se maange
        # gaye target). Ye FINAL answer ke text par naapi jaati hain — kisi step
        # ke "ho gaya" keh dene par nahi. Jo naapi na ja sake uski key aati hi
        # nahi, isliye ledger us par "check nahi hua" likhta hai, "nahi mila"
        # nahi. `hypotheses=` tabhi bhejte hain jab hypothesis engine sach mein
        # chala ho — warna experiment design/falsification par False likhna
        # jhooth hoga.
        delivered.update(delivery_evidence(
            contract, answer,
            hypotheses=(passes["hypotheses"]
                        if (passes.get("hypothesis_requested")
                            or passes.get("hypotheses")) else None),
            calculations=list(calc_records or []),
            source_titles=[getattr(s, "title", "") for s in pack.sources]))
        c_ledger = contract_ledger(contract, delivered=delivered,
                                   reasons=ledger_reasons)
        # §4 — asked vs delivered ledger user ko DIKHNA chahiye, sirf result JSON
        # mein nahi. Ye assemble ke baad hi ban sakta hai (delivered counts final
        # answer par tike hain), isliye inject yahan hota hai — ginti wale block
        # ke upar, aur §20 state block ke neeche.
        answer = quality.inject_ledger_block(answer, c_ledger)

        # 10c. §20 — chaar ALAG state + unke beech ke conflicts.
        #
        # Yahan (assemble ke BAAD) banti hai kyunki ye c_ledger aur quality_ctx
        # ke FINAL numbers par tiki hai; pehle banane par audit mein do alag
        # ginti aa jaati. Block report ke audit section ke top par inject hota
        # hai — user ke jawab ke section chhoote bhi nahi, badalte bhi nahi.
        claim_counts = dict(quality_ctx.get("claim_results") or {})
        supported = None
        if quality_ctx.get("claim_results") is not None:
            supported = (claim_counts.get("SUPPORTED", 0)
                         + claim_counts.get("PARTIALLY SUPPORTED", 0))
        unsupported = None
        if quality_ctx.get("claim_results") is not None:
            unsupported = (claim_counts.get("UNSUPPORTED", 0)
                           + claim_counts.get("CONTRADICTED", 0)
                           + claim_counts.get("UNABLE TO VERIFY", 0))
        research_state = build_research_state(
            ledger=c_ledger,
            answer_text=answer,
            source_count=len(pack.sources),
            usable_source_count=quality_ctx.get("directly_relevant_sources"),
            # Tri-state: claim check chala hi nahi to `None` — "0 supported"
            # nahi. Yahi farq §20 ke conflict rule ko sach bolne deta hai.
            verification_ran=(None if quality_ctx.get("claim_results") is None
                              else True),
            supported_claims=supported,
            unsupported_claims=unsupported,
            contradictions=len(contradiction_dicts or []),
            counter_search=axis_counter_search,
            # prior-art ka record hypotheses ke andar hi hota hai
            # (`novelty_search.performed`), isliye yahan kuch pass nahi karte —
            # `build_state` khud wahi record padhta hai. Na chali ho to `None`
            # rehta hai, jhoota True nahi.
            hypotheses=passes["hypotheses"],
            top_label=evidence_level,
            recovered=bool(recovered),
        )
        state_dict = research_state.to_dict()
        # Conflict chhupta nahi: warning list mein bhi jaata hai (UI banner) aur
        # audit block mein bhi (report). Dono ek hi object se — do jagah do baat
        # nahi.
        for line in state_warnings(research_state):
            if line not in warnings:
                warnings.append(line)
        answer = inject_state_block(answer, research_state)

        # 11. memory + graph write (best effort)
        if self.memory:
            self.memory.remember_run(
                question=question, evidence_level=evidence_level,
                source_count=len(pack.sources), mode=config.name,
                connectors=discovered["connectors"],
                summary=(passes["analysis"] or "")[:400])
            if passes["hypotheses"]:
                self.memory.remember_hypotheses(question, passes["hypotheses"])
            self.memory.remember_discovery(question, discovery_analysis)
            self.memory.remember_urls(discovered["urls"])
            # Dead ends bhi yaad rakho (Spec Section 16). Ye sirf ek note hai,
            # block nahi — agli baar prompt mein dikh jaata hai ki is topic par
            # kya pehle bekaar gaya tha, taaki wahi galti dohrayi na jaaye.
            self._remember_dead_ends(question, discovered, reading)
            self.memory.save()
        self.graph.store(question, passes["analysis"] or gemini_answer, self.project_id)

        self._track(job_id, "COMPLETE",
                    f"{len(pack.sources)} sources, {passes['calls']} gemini calls")

        cited_sources = [c for c in report.cited]
        return ResearchResult(
            question=question,
            answer=answer,
            sources=cited_sources or [s.to_dict() for s in pack.sources],
            safety_flags=safety.get("flags", []),
            evidence_level=evidence_level,
            mode=config.name,
            question_types=plan.get("question_types", []),
            relevant_fields=plan.get("relevant_fields", []),
            citations=report.cited,
            uncited_sources=report.uncited,
            invalid_citations=report.invalid_ids,
            ungrounded_claims=report.ungrounded_claims,
            contradictions=contradiction_dicts,
            hypotheses=passes["hypotheses"],
            verification=verification,
            coverage=coverage,
            requested_ledger=ledger,
            label_report=label_report,
            discovery=discovery_analysis,
            specialist_research=specialist_report,
            gemini_calls_used=passes["calls"],
            warnings=warnings,
            status=run_status.code,
            status_reason=run_status.reason,
            failure_kind=run_status.failure_kind,
            missing_passes=list(run_status.missing_passes),
            missing_sections=list(run_status.missing_sections),
            technical_details=list(technical_lines),
            api_accounting=passes.get("api_accounting") or {},
            # §4/§7/§19 — ye teen dict machine-readable hain aur final gate
            # (ChatGPT-owned) inhe hi padhta hai. Inme koi bhi 0/True aisa nahi
            # hai jo "check nahi hua" ko chhupa raha ho.
            quality_contract=contract,
            quality_context=quality_ctx,
            contract_ledger=c_ledger,
            research_state=state_dict,
        ).to_dict()

    # ── confidence note ──────────────────────────────────────────────────────
    def _confidence_note(self, pack: EvidencePack, config, calls_used: int,
                         sufficiency: Dict) -> str:
        if not pack.sources:
            return ("Koi source retrieve nahi hua. Is jawab ko unverified maanein.")
        parts = [
            f"{len(pack.sources)} sources use hue, jinke "
            f"{pack.independent_source_count} independent origins hain.",
        ]
        peer = sum(1 for s in pack.sources if s.peer_reviewed is True)
        if peer:
            # §14 — denominator ke bina "4 peer-reviewed hain" zyada mazboot
            # lagta hai jitna hai. Kul ginti saath likhna hi imaandaar hai.
            parts.append(f"{peer}/{len(pack.sources)} peer-reviewed hain.")
        if pack.full_text_read_count:
            parts.append(f"{pack.full_text_read_count}/{len(pack.sources)} ka poora "
                         f"text padha gaya.")
        if not sufficiency.get("sufficient", True):
            parts.append("Evidence threshold poora nahi hua — confidence kam rakhein.")
        # Retrieval ka sach — "kitne sources mile" se zyada zaroori hai "wo
        # sawaal ke the ya nahi". Pichhli report mein 5 sources the aur ek bhi
        # topic ka nahi tha, par confidence note usme se kuch nahi kehta tha.
        parts.append(pack.relevance_note())
        if pack.full_text_read_count < 1:
            parts.append("Kisi source ka poora text nahi padha ja saka — ye jawab "
                         "abstract/snippet level ka hai.")
        # Budget (config.gemini_calls) ke bajaye ASLI planned passes se compare
        # karo: 2-call mode mein critique plan hi nahi hota, use "nahi chala"
        # batana galat hai.
        if not pack.reasoning_complete:
            parts.append(pack.reasoning_note())
        parts.append("Ye confidence retrieved evidence par hai, poore literature par nahi.")
        return " ".join(parts)
