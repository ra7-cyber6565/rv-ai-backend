"""AI-1 Global Research & Evidence Director.

Deterministic, zero-provider-call governance layer.  It converts the core
research engine's measured artifacts into the exact 15-section AI-1 handoff and
adds source-family-specific deep-read/provenance auditing.  It never creates
missing research or upgrades metadata/snippets/descriptions into reads.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Mapping, MutableMapping, Sequence, Tuple

from .deep_source_integrity import build_deep_source_integrity_report

SCHEMA_VERSION = "ai1-research-packet-1.1"
ROLE = "GLOBAL RESEARCH & EVIDENCE DIRECTOR"
AGENT_ID = "AI-1 / RESEARCH-DIRECTOR"
MODE = "PARALLEL MULTI-AGENT RESEARCH COMPANY"

MISSING_SOURCE = "MISSING SOURCE"
FULL_TEXT_REQUIRED = "FULL TEXT REQUIRED"
MISSING_DATA = "MISSING DATA"
NOT_VERIFIED = "NOT VERIFIED"
UNKNOWN = "UNKNOWN"

EVIDENCE_GRADES = {
    "A": "Strong evidence",
    "B": "Moderate evidence",
    "C": "Plausible inference",
    "D": "Testable hypothesis",
    "E": "Unsupported/speculative",
}

PACKET_SECTION_NAMES: Tuple[str, ...] = (
    "1. Interpretation of User Goal",
    "2. Required Deliverables",
    "3. Relevant Knowledge Domains",
    "4. Relevant Experts / Thinkers / Schools",
    "5. Strongest Sources",
    "6. Claim-Evidence Matrix",
    "7. Contradictory Evidence",
    "8. Theory Components Worth Retaining",
    "9. Weak / Rejected Theories or Claims",
    "10. Important Mechanisms",
    "11. Missing Evidence",
    "12. Cross-Agent Alerts",
    "13. Highest-Value Second-Pass Research Tasks",
    "14. Confidence in Research Packet /100",
    "15. Exactly What Prevents a Higher Score",
)

_TRADING_WORDS = (
    "trading", "scalp", "scalping", "us100", "nas100", "nq", "mnq",
    "xauusd", "gold", "gc", "mgc", "order flow", "liquidity", "ict",
)
_TRADING_SCHOOLS = (
    "ICT primary teaching material", "Time Theory", "Smart Money Concepts",
    "Wyckoff", "Auction Market Theory", "Market Profile", "Volume Profile",
    "order flow / tape reading", "market microstructure", "quantitative finance",
    "momentum / mean reversion", "statistical arbitrage", "regime switching",
    "volatility modeling", "options/dealer positioning", "behavioral finance",
    "liquidity theory", "algorithmic execution",
)
_DOMAIN_RESEARCH_TARGETS: Mapping[str, Tuple[str, ...]] = {
    "scientific": ("experimental science", "causal inference", "replication research",
                   "systematic review / meta-analysis"),
    "medical": ("clinical epidemiology", "evidence-based medicine", "causal inference",
                "systematic review / meta-analysis"),
    "mathematical": ("mathematical modeling", "statistics", "optimization",
                     "uncertainty quantification"),
    "technical": ("computer science", "software engineering", "systems engineering",
                  "benchmarking"),
    "financial": ("finance", "econometrics", "market microstructure", "behavioral finance"),
    "psychological": ("cognitive science", "behavioral science", "neuroscience",
                      "replication research"),
    "historical": ("primary-source history", "historiography", "archival research",
                   "source criticism"),
    "philosophical": ("analytic philosophy", "history of ideas", "conceptual analysis"),
}
_MECHANISM_CUES = re.compile(
    r"\b(because|caus(?:e|es|ed|al)|mechanism|mediated|through|via|driven by|"
    r"results? from|leads? to|therefore|due to|because of|ke karan|ki wajah se|"
    r"iske karan|jis se)\b", re.IGNORECASE,
)


def _safe_dict(value: object) -> Dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_list(value: object) -> List:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _source_key(source: Mapping) -> str:
    return _text(source.get("source_id") or source.get("url") or source.get("doi")
                 or source.get("title"), 400).casefold()


def _source_pool(result: Mapping) -> List[Dict]:
    merged: List[Dict] = []
    seen = set()
    for bucket in ("sources", "citations", "uncited_sources"):
        for raw in _safe_list(result.get(bucket)):
            source = _safe_dict(raw)
            if not source:
                continue
            key = _source_key(source)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(source)
    return merged


def _access_depth(source: Mapping) -> str:
    """Fallback depth. Partial-page reads always beat a raw full_text marker."""
    explicit = _text(source.get("access_depth") or source.get("access_label"), 80).upper()
    if explicit:
        return explicit
    level = _text(source.get("read_level") or source.get("reading_level"), 40).casefold()
    pages = int(source.get("pages_read") or 0)
    total = int(source.get("pages_total") or 0)
    if total and pages and pages < total:
        return "RELEVANT SECTIONS REVIEWED"
    if level in {"claims", "sections"}:
        return "RELEVANT SECTIONS REVIEWED"
    if level == "full_text":
        return "FULL TEXT ACCESSED"
    if level == "abstract":
        return "ABSTRACT ONLY"
    if level == "snippet" or source.get("snippet"):
        return "SNIPPET ONLY"
    if source:
        return "METADATA ONLY"
    return UNKNOWN


def _source_type(source: Mapping) -> str:
    value = source.get("source_type") or source.get("type") or source.get("doc_kind")
    if isinstance(value, Mapping):
        value = value.get("value")
    return _text(value, 80).casefold() or "unknown"


def _source_hierarchy_rank(source: Mapping) -> int:
    kind = _source_type(source)
    connector = _text(source.get("connector"), 80).casefold()
    method = _text(source.get("methodology"), 80).casefold()
    title = _text(source.get("title"), 180).casefold()
    if source.get("is_primary") is True or "primary" in method:
        return 1
    if any(x in connector for x in ("gov", "official")) or any(
        x in title for x in ("official report", "government", "standard")
    ):
        return 2
    if kind in {"paper", "research_paper", "journal_article"} and source.get("peer_reviewed") is True:
        return 3
    if any(x in method for x in ("meta", "systematic_review", "systematic review")):
        return 4
    if kind == "book":
        return 5
    if kind == "dataset":
        return 6
    if any(x in kind for x in ("documentation", "manual", "standard")):
        return 7
    if kind in {"transcript", "interview", "lecture"}:
        return 8
    return 9


def _source_strength(source: Mapping) -> float:
    quality = float(source.get("quality_score") or 0.0)
    relevance = float(source.get("relevance_score") or 0.0)
    hierarchy = _source_hierarchy_rank(source)
    access_bonus = {
        "FULL TEXT ACCESSED": 0.20,
        "RELEVANT SECTIONS REVIEWED": 0.15,
        "ABSTRACT ONLY": 0.08,
        "SNIPPET ONLY": 0.03,
        "METADATA ONLY": 0.0,
    }.get(_access_depth(source), 0.0)
    return round(
        quality * 0.42 + relevance * 0.38 + access_bonus
        + (0.08 if source.get("is_primary") is True else 0.0)
        + (0.06 if source.get("peer_reviewed") is True else 0.0)
        + ((10 - hierarchy) * 0.006)
        - (1.0 if source.get("retracted") is True else 0.0), 4,
    )


def _source_limitations(source: Mapping) -> List[str]:
    limits: List[str] = []
    if source.get("retracted") is True:
        limits.append("retraction/withdrawal signal")
    if source.get("relevance_score") is not None and float(source.get("relevance_score") or 0) < 0.25:
        limits.append("low direct relevance")
    if _access_depth(source) in {"METADATA ONLY", "SNIPPET ONLY", "ABSTRACT ONLY"}:
        limits.append(FULL_TEXT_REQUIRED)
    if source.get("peer_reviewed") is None:
        limits.append("peer-review status unknown")
    if not source.get("methodology"):
        limits.append("methodology not established from available metadata/text")
    if source.get("rejected_reason"):
        limits.append("relevance gate concern: " + _text(source.get("rejected_reason"), 160))
    return limits or ["no additional limitation measured in exposed metadata"]


def _strongest_sources(sources: Sequence[Mapping], deep_report: Mapping, limit: int = 12) -> List[Dict]:
    deep_by_id = {
        _text(row.get("source_id"), 80): row
        for row in _safe_list(deep_report.get("sources")) if isinstance(row, Mapping)
    }
    ranked = sorted(sources, key=lambda s: (_source_strength(s), -_source_hierarchy_rank(s)),
                    reverse=True)
    out: List[Dict] = []
    for source in ranked[:limit]:
        sid = _text(source.get("source_id"), 40)
        verdict = source.get("domain_verdict")
        contribution = source.get("contribution")
        if not contribution and isinstance(verdict, Mapping):
            contribution = verdict.get("reason")
        deep = _safe_dict(deep_by_id.get(sid))
        out.append({
            "source_id": sid,
            "title": _text(source.get("title") or MISSING_SOURCE, 240),
            "contribution": _text(contribution, 300) or
                "Contribution must be read from the claim-evidence links; not guessed here.",
            "source_type": _source_type(source),
            "source_family": deep.get("source_family") or "unknown",
            "deep_source_status": deep.get("deep_status") or UNKNOWN,
            "evidence_quality": {
                "hierarchy_tier": _source_hierarchy_rank(source),
                "quality_score": source.get("quality_score"),
                "relevance_score": source.get("relevance_score"),
                "peer_reviewed": source.get("peer_reviewed"),
                "primary": source.get("is_primary"),
            },
            "full_text_status": _access_depth(source),
            "limitations": _source_limitations(source),
            "fabrication_guard": "metadata copied from runtime result only",
        })
    return out


def _claim_rows(result: Mapping) -> List[Dict]:
    checks = _safe_dict(_safe_dict(result.get("verification")).get("claim_checks"))
    rows = (_safe_list(checks.get("claims")) or _safe_list(checks.get("checks"))
            or _safe_list(checks.get("items")))
    return [_safe_dict(row) for row in rows if isinstance(row, Mapping)]


def _source_check_passes_ae(row: Mapping) -> bool:
    for src in _safe_list(row.get("source_checks")):
        if _safe_dict(src).get("passes_ae") is True:
            return True
    statuses = {}
    for check in _safe_list(row.get("checks")):
        check = _safe_dict(check)
        key = _text(check.get("check") or check.get("key"), 4).upper()
        if key:
            statuses[key] = _text(check.get("status"), 20).casefold()
    return bool(statuses) and all(statuses.get(k) == "pass" for k in "ABCDE")


def _grade_claim(row: Mapping) -> Tuple[str, str]:
    epistemic = _text(row.get("epistemic_type") or row.get("claim_type"), 60).casefold()
    verdict = _text(row.get("result") or row.get("verdict"), 80).casefold()
    if "hypothesis" in epistemic:
        return "D", EVIDENCE_GRADES["D"]
    if "speculation" in epistemic or "unsupported" in verdict or "contradicted" in verdict:
        return "E", EVIDENCE_GRADES["E"]
    if "inference" in epistemic:
        return "C", EVIDENCE_GRADES["C"]
    if _source_check_passes_ae(row) and "supported" in verdict and "partial" not in verdict:
        return "A", EVIDENCE_GRADES["A"]
    if "partial" in verdict or "source_reported" in verdict or _text(
        row.get("entailment_check"), 20).casefold() == "pass"
    ):
        return "B", EVIDENCE_GRADES["B"]
    if "unable" in verdict or "unver" in verdict or not verdict:
        return "C", EVIDENCE_GRADES["C"]
    return "E", EVIDENCE_GRADES["E"]


def _claim_matrix(result: Mapping) -> List[Dict]:
    matrix: List[Dict] = []
    for row in _claim_rows(result):
        grade, label = _grade_claim(row)
        spans = _safe_list(row.get("spans"))
        canonical = _safe_dict(row.get("canonical_span"))
        if canonical:
            spans = [canonical] + spans
        contradicting = []
        if row.get("contradicted"):
            contradicting.append(_safe_dict(row.get("contradiction_span")) or {
                "status": "contradicted; exact span not exposed"
            })
        claim_text = _text(row.get("text") or row.get("claim"), 1200)
        matrix.append({
            "claim_id": _text(row.get("claim_id"), 40),
            "claim": claim_text,
            "supporting_evidence": {
                "source_ids": _safe_list(row.get("source_ids") or row.get("cited_ids")),
                "evidence_spans": spans,
                "best_source": _text(row.get("best_source") or row.get("supporting_source_id"), 60),
            },
            "contradicting_evidence": contradicting,
            "source_quality": row.get("source_quality") or UNKNOWN,
            "mechanism": _text(row.get("mechanism"), 500) or (
                "claim itself contains an explicit mechanism cue"
                if _MECHANISM_CUES.search(claim_text) else UNKNOWN
            ),
            "applicability": row.get("applicability") or row.get("section") or UNKNOWN,
            "confidence_grade": grade,
            "confidence_label": label,
            "fact_promotion_allowed": grade in {"A", "B"},
            "promotion_guard": (
                "C/D/E MUST remain inference/hypothesis/speculation until stronger evidence exists"
                if grade in {"C", "D", "E"}
                else "A/B still require wording proportional to evidence; grade is not absolute truth"
            ),
            "runtime_result": row.get("result") or row.get("verdict") or UNKNOWN,
        })
    if matrix:
        return matrix
    return [{
        "claim_id": "", "claim": NOT_VERIFIED,
        "supporting_evidence": {"source_ids": [], "evidence_spans": []},
        "contradicting_evidence": [], "source_quality": UNKNOWN,
        "mechanism": UNKNOWN, "applicability": UNKNOWN,
        "confidence_grade": "E", "confidence_label": EVIDENCE_GRADES["E"],
        "fact_promotion_allowed": False,
        "promotion_guard": "No structured claim checks were exposed by this run.",
        "runtime_result": NOT_VERIFIED,
    }]


def _domains(result: Mapping, sources: Sequence[Mapping]) -> List[Dict]:
    names: List[str] = []
    for raw in _safe_list(result.get("relevant_fields")) + _safe_list(result.get("question_types")):
        name = _text(raw, 120)
        if name and name not in names:
            names.append(name)
    specialist = _safe_dict(result.get("specialist_research"))
    for lane in _safe_list(specialist.get("lanes")):
        lane = _safe_dict(lane)
        name = _text(lane.get("label") or lane.get("name") or lane.get("lane"), 120)
        if name and name not in names:
            names.append(name)
    if not names:
        names = [UNKNOWN]
    return [{
        "domain": name,
        "why_it_matters": "selected by the runtime planner/specialist evidence lanes",
        "source_count_visible_to_ai1": sum(
            1 for s in sources
            if name.casefold() in _text(s.get("title") or s.get("venue"), 300).casefold()
        ),
    } for name in names]


def _experts_and_schools(question: str, result: Mapping, sources: Sequence[Mapping]) -> Dict:
    authors: Counter = Counter()
    for source in sources:
        raw = source.get("authors")
        if isinstance(raw, str):
            raw = [raw]
        for author in _safe_list(raw):
            author = _text(author, 120)
            if author:
                authors[author] += 1
    schools: List[str] = []
    q = question.casefold()
    if any(word in q for word in _TRADING_WORDS):
        schools.extend(_TRADING_SCHOOLS)
    for qtype in _safe_list(result.get("question_types")):
        for item in _DOMAIN_RESEARCH_TARGETS.get(_text(qtype, 80).casefold(), ()):
            if item not in schools:
                schools.append(item)
    return {
        "evidence_linked_experts": [
            {"name": name, "source_occurrences": count,
             "status": "evidence-linked author; relevance still depends on source/claim gate"}
            for name, count in authors.most_common(12)
        ],
        "schools_or_research_traditions_to_test": [
            {"name": item, "status": "research target, not assumed correct",
             "rule": "retain only components that pass relevance/evidence/contradiction checks"}
            for item in schools
        ],
        "fame_guard": "No thinker is included merely for being famous.",
    }


def _required_deliverables(question: str, result: Mapping) -> Dict:
    ledger = _safe_dict(result.get("contract_ledger")) or _safe_dict(result.get("requested_ledger"))
    contract = _safe_dict(result.get("quality_contract"))
    return {
        "user_question": _text(question, 2000),
        "runtime_contract": contract or {"status": "No explicit structured quality contract exposed"},
        "delivery_ledger": ledger or {"status": "No structured delivery ledger exposed"},
        "unmet_items": _safe_list(ledger.get("unmet")),
        "guard": "Interesting research may not substitute for the requested deliverable.",
    }


def _contradictions(result: Mapping, matrix: Sequence[Mapping]) -> Dict:
    global_items = [_safe_dict(x) for x in _safe_list(result.get("contradictions"))
                    if isinstance(x, Mapping)]
    claim_items = [
        {"claim_id": row.get("claim_id"), "claim": row.get("claim"),
         "evidence": row.get("contradicting_evidence")}
        for row in matrix if row.get("contradicting_evidence")
    ]
    coverage = _safe_dict(result.get("coverage"))
    axes = _safe_dict(coverage.get("evidence_axes"))
    counter_state = _safe_dict(result.get("quality_context")).get("counter_search_performed")
    if counter_state is None:
        counter_state = _safe_dict(axes.get("summary")).get("counter_search_performed")
    return {
        "counter_search_performed": counter_state if counter_state is not None else UNKNOWN,
        "detected_contradictions": global_items,
        "claim_linked_contradictions": claim_items,
        "interpretation_rule": (
            "Disagreement must be investigated for sample, method, period/regime, definition, "
            "measurement, and statistical differences; contradiction count alone resolves nothing."
        ),
    }


def _theory_components(result: Mapping, matrix: Sequence[Mapping]) -> Tuple[List[Dict], List[Dict]]:
    retain: List[Dict] = []
    weak: List[Dict] = []
    for row in matrix:
        item = {
            "claim_id": row.get("claim_id"), "proposition": row.get("claim"),
            "evidence_grade": row.get("confidence_grade"), "status": row.get("runtime_result"),
        }
        if row.get("confidence_grade") in {"A", "B"}:
            retain.append(item)
        else:
            weak.append({**item, "rule": "Do not treat as established; strengthen, test, or reject."})
    rejects = _safe_dict(result.get("rejects"))
    for item in _safe_list(rejects.get("rejected") or rejects.get("items")):
        item = _safe_dict(item)
        weak.append({
            "proposition": _text(item.get("hypothesis") or item.get("text"), 1000),
            "evidence_grade": "E", "status": item.get("reason") or "rejected by runtime ledger",
            "rule": "Runtime rejection is not proof of real-world falsity.",
        })
    return retain, weak


def _mechanisms(matrix: Sequence[Mapping]) -> List[Dict]:
    out = []
    for row in matrix:
        claim = _text(row.get("claim"), 1200)
        if claim and claim != NOT_VERIFIED and _MECHANISM_CUES.search(claim):
            out.append({
                "claim_id": row.get("claim_id"), "mechanism_statement": claim,
                "evidence_grade": row.get("confidence_grade"),
                "status": "mechanism cue present in a checked claim; causal validity is not inferred",
            })
    return out or [{
        "mechanism_statement": UNKNOWN,
        "status": "No explicit evidence-linked mechanism was exposed in structured claim checks.",
    }]


def _missing_evidence(result: Mapping, sources: Sequence[Mapping], matrix: Sequence[Mapping],
                      contradictions: Mapping) -> List[Dict]:
    missing: List[Dict] = []
    if not sources:
        missing.append({"code": MISSING_SOURCE, "detail": "No source record is visible to AI-1."})
    shallow = [s for s in sources if _access_depth(s) in {
        "METADATA ONLY", "SNIPPET ONLY", "ABSTRACT ONLY"
    }]
    if shallow:
        missing.append({
            "code": FULL_TEXT_REQUIRED,
            "detail": f"{len(shallow)}/{len(sources)} visible sources are below section/full-text depth.",
            "source_ids": [_text(s.get("source_id"), 30) for s in shallow[:12]],
        })
    weak_claims = [row for row in matrix if row.get("confidence_grade") in {"C", "D", "E"}]
    if weak_claims:
        missing.append({
            "code": NOT_VERIFIED,
            "detail": f"{len(weak_claims)} claim(s) remain C/D/E and cannot be silently promoted to fact.",
            "claim_ids": [row.get("claim_id") for row in weak_claims[:12]],
        })
    if contradictions.get("counter_search_performed") is not True:
        missing.append({"code": MISSING_DATA,
                        "detail": "Counter-side search is absent or not machine-confirmed for this run."})
    summary = _safe_dict(_safe_dict(_safe_dict(result.get("coverage")).get("evidence_axes")).get("summary"))
    if int(summary.get("mandatory_missing") or 0) > 0:
        missing.append({"code": MISSING_DATA, "detail": "Mandatory evidence axes are still uncovered.",
                        "missing_axes": _safe_list(summary.get("missing_labels"))})
    if _safe_dict(result.get("source_integrity")).get("high_risk") is True:
        missing.append({"code": NOT_VERIFIED,
                        "detail": "Source-integrity high-risk signal requires review before a strong release label."})
    return missing


def _merge_missing(base: Sequence[Mapping], deep_report: Mapping) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    for raw in list(base) + _safe_list(deep_report.get("gaps")):
        item = _safe_dict(raw)
        key = (item.get("code"), item.get("source_id"), item.get("detail"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _task(title: str, reason: str, importance: int, information_gain: int,
          target_agent: str = "AI-1") -> Dict:
    importance = max(1, min(10, int(importance)))
    information_gain = max(1, min(10, int(information_gain)))
    return {
        "task": title, "why": reason, "importance": importance,
        "expected_information_gain": information_gain,
        "priority_score": importance * information_gain,
        "priority_formula": "Importance × Expected Information Gain",
        "route_to": target_agent,
    }


def _second_pass_tasks(missing: Sequence[Mapping], result: Mapping,
                       matrix: Sequence[Mapping], deep_report: Mapping) -> List[Dict]:
    tasks: List[Dict] = []
    codes = {item.get("code") for item in missing}
    if MISSING_SOURCE in codes:
        tasks.append(_task("Acquire directly relevant primary/official sources",
                           "No usable source foundation is visible.", 10, 10))
    if FULL_TEXT_REQUIRED in codes:
        tasks.append(_task("Obtain and inspect full text / relevant sections",
                           "Critical conclusions should not rest on title/snippet/abstract-only reading.", 10, 9))
    if any(row.get("confidence_grade") in {"C", "D", "E"} for row in matrix):
        tasks.append(_task("Strengthen unresolved claim-evidence links",
                           "C/D/E claims need stronger direct support or explicit testing before promotion.", 10, 10))
    if any(_text(item.get("detail"), 100).startswith("Counter-side") for item in missing):
        tasks.append(_task("Run targeted negative/replication/criticism search",
                           "Support-only search cannot justify a strong evidence label.", 9, 10))
    if any("axes" in _text(item.get("detail"), 200) for item in missing):
        tasks.append(_task("Fill mandatory evidence-axis gaps",
                           "Source count cannot substitute for missing evidence pathways.", 9, 9))
    experiment = _safe_dict(result.get("experiment_intelligence"))
    hypotheses = _safe_list(result.get("hypotheses"))
    if hypotheses and experiment.get("status") not in {"ASSESSMENT_READY", "READY", "COMPLETE"}:
        tasks.append(_task("Convert hypotheses into complete falsification tests",
                           "Hypotheses exist but the structured experiment packet is not fully ready.",
                           9, 9, "AI-2"))
    tasks.extend(_safe_dict(item) for item in _safe_list(deep_report.get("second_pass_tasks")))
    unique: Dict[Tuple[str, str, str], Dict] = {}
    for item in tasks:
        key = (_text(item.get("task"), 300), _text(item.get("route_to"), 30),
               _text(item.get("source_family"), 80))
        old = unique.get(key)
        if old is None or int(item.get("priority_score") or 0) > int(old.get("priority_score") or 0):
            unique[key] = item
    return sorted(unique.values(), key=lambda x: (
        int(x.get("priority_score") or 0), int(x.get("importance") or 0),
        int(x.get("expected_information_gain") or 0)
    ), reverse=True)


def _cross_agent_alerts(result: Mapping, matrix: Sequence[Mapping],
                        contradictions: Mapping, missing: Sequence[Mapping]) -> List[Dict]:
    alerts: List[Dict] = []
    hypotheses = _safe_list(result.get("hypotheses"))
    experiment = _safe_dict(result.get("experiment_intelligence"))
    if hypotheses or any(row.get("confidence_grade") == "D" for row in matrix):
        alerts.append({"agent": "AI-2", "alert": "Requires statistical/experimental testing.",
                       "evidence": {"hypotheses": len(hypotheses),
                                    "experiment_status": experiment.get("status") or UNKNOWN}})
    if any(row.get("mechanism") == UNKNOWN or row.get("confidence_grade") in {"C", "D"}
           for row in matrix):
        alerts.append({"agent": "AI-3",
                       "alert": "Mechanism/theory decomposition or hypothesis development remains useful.",
                       "evidence": "At least one checked claim lacks a verified mechanism or remains C/D."})
    integrity = _safe_dict(result.get("source_integrity"))
    if (_safe_list(contradictions.get("detected_contradictions"))
            or integrity.get("high_risk") is True
            or any(row.get("confidence_grade") == "E" for row in matrix)):
        alerts.append({"agent": "AI-4",
                       "alert": "Serious contradiction/failure-risk item requires adversarial red-team attention.",
                       "evidence": {
                           "contradictions": len(_safe_list(contradictions.get("detected_contradictions"))),
                           "source_integrity_high_risk": integrity.get("high_risk") is True,
                           "grade_e_claims": sum(1 for row in matrix if row.get("confidence_grade") == "E"),
                       }})
    return alerts


def _packet_confidence(result: Mapping, sources: Sequence[Mapping], matrix: Sequence[Mapping],
                       contradictions: Mapping, missing: Sequence[Mapping],
                       deep_report: Mapping) -> Dict:
    score = 0
    components: Dict[str, Dict] = {}
    source_score = 20 if sources else 0
    components["source_foundation"] = {"score": source_score, "max": 20}
    score += source_score

    deep = int(deep_report.get("deep_evidence_source_count") or 0)
    reading_score = 0 if not sources else round(20 * deep / len(sources))
    components["deep_reading"] = {
        "score": reading_score, "max": 20, "deep_sources": deep,
        "visible_sources": len(sources),
        "source_family_audit": "deep-source-integrity-1.0",
    }
    score += reading_score

    real_rows = [row for row in matrix if row.get("claim") != NOT_VERIFIED]
    verified = [row for row in real_rows if row.get("confidence_grade") in {"A", "B"}]
    claim_score = 0 if not real_rows else round(20 * len(verified) / len(real_rows))
    components["claim_evidence"] = {"score": claim_score, "max": 20,
                                    "A_or_B": len(verified), "claims": len(real_rows)}
    score += claim_score

    contradiction_score = 15 if contradictions.get("counter_search_performed") is True else 5
    if _safe_list(contradictions.get("detected_contradictions")):
        contradiction_score = min(15, contradiction_score + 2)
    components["contradiction_search"] = {"score": contradiction_score, "max": 15}
    score += contradiction_score

    known_quality = sum(1 for s in sources if s.get("quality_score") is not None)
    quality_score = 0 if not sources else round(10 * known_quality / len(sources))
    components["source_quality_metadata"] = {"score": quality_score, "max": 10}
    score += quality_score

    run_status = _text(result.get("status"), 80).upper()
    runtime_score = 10 if run_status == "COMPLETE" else (5 if run_status else 0)
    components["runtime_completion"] = {"score": runtime_score, "max": 10,
                                        "status": run_status or UNKNOWN}
    score += runtime_score
    components["packet_contract"] = {"score": 5, "max": 5}
    score += 5

    if not sources:
        score = min(score, 25)
    if not real_rows:
        score = min(score, 55)
    if _safe_dict(result.get("source_integrity")).get("high_risk") is True:
        score = min(score, 70)
    if int(deep_report.get("blocking_gap_count") or 0) > 0:
        score = min(score, 90)
    score = max(0, min(100, int(score)))
    return {
        "score": score, "scale": "/100",
        "meaning": "confidence in AI-1 packet/process completeness only",
        "not_a_truth_probability": True,
        "not_a_success_or_profitability_probability": True,
        "components": components,
        "unresolved_item_count": len(missing),
        "deep_source_blocking_gaps": int(deep_report.get("blocking_gap_count") or 0),
    }


def _blockers(confidence: Mapping, missing: Sequence[Mapping], result: Mapping) -> List[str]:
    blockers = [_text(item.get("code"), 80) + ": " + _text(item.get("detail"), 400)
                for item in missing]
    ledger = _safe_dict(result.get("contract_ledger")) or _safe_dict(result.get("requested_ledger"))
    if _safe_list(ledger.get("unmet")):
        blockers.append("Requested deliverable ledger still contains unmet items.")
    if int(confidence.get("score") or 0) >= 100 and blockers:
        blockers.append("Score is capped below 100 while unresolved blockers exist.")
    return blockers or ["No measured blocker remains in the exposed AI-1 packet fields."]


def _validate_packet(packet: Mapping) -> Dict:
    sections = _safe_dict(packet.get("sections"))
    missing_sections = [name for name in PACKET_SECTION_NAMES if name not in sections]
    order_ok = list(sections) == list(PACKET_SECTION_NAMES)
    promotion_violations = [
        row.get("claim_id") for row in _safe_list(sections.get("6. Claim-Evidence Matrix"))
        if isinstance(row, Mapping) and row.get("confidence_grade") in {"C", "D", "E"}
        and row.get("fact_promotion_allowed") is not False
    ]
    forbidden_claims = []
    serialized = repr(packet).casefold()
    for phrase in ("all literature read", "entire internet read", "backtest completed"):
        if phrase.casefold() in serialized:
            forbidden_claims.append(phrase)
    return {
        "valid": not missing_sections and order_ok and not promotion_violations and not forbidden_claims,
        "missing_sections": missing_sections,
        "section_order_ok": order_ok,
        "c_d_e_promotion_violations": promotion_violations,
        "fabrication_phrase_violations": forbidden_claims,
    }


def build_ai1_research_packet(question: str, result: Mapping) -> Dict:
    question = _text(question, 20_000)
    result = _safe_dict(result)
    sources = _source_pool(result)
    deep_report = build_deep_source_integrity_report(result, sources)
    matrix = _claim_matrix(result)
    contradiction_report = _contradictions(result, matrix)
    retain, weak = _theory_components(result, matrix)
    missing = _merge_missing(
        _missing_evidence(result, sources, matrix, contradiction_report), deep_report
    )
    second_pass = _second_pass_tasks(missing, result, matrix, deep_report)
    confidence = _packet_confidence(
        result, sources, matrix, contradiction_report, missing, deep_report
    )

    interpretation = {
        "exact_question": question,
        "outcome": "Build the strongest evidence foundation for downstream AI-2/AI-3/AI-4, not a replacement final answer.",
        "question_types": _safe_list(result.get("question_types")),
        "hidden_assumption_policy": "Unknown assumptions remain explicit; they are not silently filled.",
        "evidence_requirement": "Major claims must carry support, counter-evidence status, source quality, mechanism/applicability status and A-E grade.",
        "deep_source_requirement": (
            "Each visible source family must prove the kind of inspection it claims: text, claims, transcript, data or code."
        ),
    }

    sections: MutableMapping[str, object] = {}
    sections[PACKET_SECTION_NAMES[0]] = interpretation
    sections[PACKET_SECTION_NAMES[1]] = _required_deliverables(question, result)
    sections[PACKET_SECTION_NAMES[2]] = _domains(result, sources)
    sections[PACKET_SECTION_NAMES[3]] = _experts_and_schools(question, result, sources)
    sections[PACKET_SECTION_NAMES[4]] = _strongest_sources(sources, deep_report)
    sections[PACKET_SECTION_NAMES[5]] = matrix
    sections[PACKET_SECTION_NAMES[6]] = contradiction_report
    sections[PACKET_SECTION_NAMES[7]] = retain
    sections[PACKET_SECTION_NAMES[8]] = weak
    sections[PACKET_SECTION_NAMES[9]] = _mechanisms(matrix)
    sections[PACKET_SECTION_NAMES[10]] = missing or [{
        "code": "NONE_MEASURED", "detail": "No missing-evidence condition was measured in exposed fields."
    }]
    sections[PACKET_SECTION_NAMES[11]] = _cross_agent_alerts(result, matrix, contradiction_report, missing)
    sections[PACKET_SECTION_NAMES[12]] = second_pass
    sections[PACKET_SECTION_NAMES[13]] = confidence
    sections[PACKET_SECTION_NAMES[14]] = _blockers(confidence, missing, result)

    packet: Dict = {
        "schema_version": SCHEMA_VERSION,
        "agent_id": AGENT_ID, "role": ROLE, "mode": MODE,
        "is_final_user_answer": False,
        "parallel_rule": "AI-1 does not wait for AI-2/AI-3/AI-4.",
        "truth_policy": {
            "source_count_is_not_research_quality": True,
            "search_is_not_reading": True,
            "citation_is_not_entailment": True,
            "C_D_E_never_silently_become_fact": True,
            "dataset_metadata_is_not_data_inspection": True,
            "repo_metadata_is_not_code_inspection": True,
            "media_description_is_not_transcript": True,
            "transcript_is_not_audio_visual_analysis": True,
            "translation_requires_provenance": True,
            "missing_labels": [MISSING_SOURCE, FULL_TEXT_REQUIRED, MISSING_DATA,
                               NOT_VERIFIED, UNKNOWN],
        },
        "deep_source_integrity": deep_report,
        "sections": sections,
    }
    packet["validation"] = _validate_packet(packet)
    if not packet["validation"]["valid"]:
        conf = _safe_dict(sections[PACKET_SECTION_NAMES[13]])
        conf["score"] = min(int(conf.get("score") or 0), 40)
        sections[PACKET_SECTION_NAMES[14]] = list(
            _safe_list(sections[PACKET_SECTION_NAMES[14]])
        ) + ["AI-1 packet contract validation failed: " + repr(packet["validation"])]
    return packet


def attach_ai1_research_packet(question: str, result: Dict) -> Dict:
    if not isinstance(result, dict):
        return result
    try:
        result["ai1_research_packet"] = build_ai1_research_packet(question, result)
    except Exception as exc:  # fail closed; legacy answer must survive auxiliary audit
        result["ai1_research_packet"] = {
            "schema_version": SCHEMA_VERSION, "agent_id": AGENT_ID, "role": ROLE,
            "mode": MODE, "is_final_user_answer": False, "status": "ASSESSMENT_ERROR",
            "error": "AI-1 packet could not be completed; no missing evidence was invented.",
            "technical_error_type": type(exc).__name__,
            "deep_source_integrity": {"status": "ASSESSMENT_ERROR", "gaps": []},
            "sections": {name: UNKNOWN for name in PACKET_SECTION_NAMES},
            "validation": {"valid": False, "missing_sections": [], "section_order_ok": True,
                           "c_d_e_promotion_violations": [], "fabrication_phrase_violations": []},
        }
    return result
