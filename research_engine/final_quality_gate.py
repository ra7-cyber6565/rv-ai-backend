"""Deterministic final-answer quality gate.

This module is intentionally independent from retrieval, Gemini, synthesis and
the web UI.  It consumes the *structured facts* recorded by those layers and
answers one question: may this result be presented as a complete/verified
research answer?

The gate fails closed.  Missing audit data is never silently interpreted as a
successful check.  It also keeps three concepts separate:

* a network/model job finished;
* the requested answer is complete;
* the scientific claims are sufficiently supported.

No network call or model call is made here, so the contract is cheap to run in
every response path and can be covered by offline regression tests.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


CONTRACT_VERSION = "1.0"

CATEGORY_WEIGHTS: Dict[str, int] = {
    "requirement_coverage": 10,
    "source_relevance": 15,
    "claim_citation": 15,
    "scientific_reasoning": 12,
    "calculation_validation": 10,
    "original_hypotheses": 15,
    "experiment_falsification": 10,
    "confidence_honesty": 5,
    "ux_clarity": 5,
    "reliability_privacy": 3,
}

assert sum(CATEGORY_WEIGHTS.values()) == 100

DEFAULT_REQUIRED_SECTIONS: Tuple[str, ...] = (
    "direct_answer",
    "established_knowledge",
    "supporting_evidence",
    "counter_evidence",
    "unknowns",
    "conclusion",
    "sources",
)

SECTION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "direct_answer": ("seedha jawab", "direct answer"),
    "established_knowledge": (
        "research se kya pata chala",
        "established knowledge",
        "established evidence",
    ),
    "supporting_evidence": ("evidence kya kehta hai", "supporting evidence"),
    "counter_evidence": (
        "iske against kya mila",
        "evidence against",
        "counter evidence",
        "counter-evidence",
    ),
    "calculations": ("calculations", "quantitative checks", "hisaab"),
    "unknowns": ("kya abhi unknown hai", "what remains unknown", "unknowns"),
    "conclusion": ("final conclusion", "evidence-based conclusion"),
    "sources": ("sources", "references"),
    "original_hypotheses": (
        "app original research lab",
        "app ki khud generate ki hui research hypotheses",
        "app-generated research hypotheses",
    ),
    "audit": ("audit & limits", "research quality", "quality audit"),
}

NOVELTY_STATUSES = {
    "KNOWN IDEA",
    "KNOWN VARIANT",
    "MINOR MODIFICATION",
    "POSSIBLY NOVEL — NO CLOSE MATCH FOUND",
    "POSSIBLY NOVEL - NO CLOSE MATCH FOUND",
    "NOVELTY UNVERIFIED",
    "REJECTED AS DUPLICATE",
}

RAW_TECHNICAL_MARKERS: Tuple[str, ...] = (
    "resourceexhausted",
    "deadlineexceeded",
    "traceback",
    "quota_id",
    "quota_metric",
    "google.api_core",
    "generativelanguage",
    "protobuf",
    "stacktrace",
    "technical details (developer",
    "analysis failed (model=",
)

ABSOLUTE_NOVELTY_RE = re.compile(
    r"(?:100\s*%\s*(?:new|novel|nayi)|duniya\s+mein\s+pehli|"
    r"world(?:'s)?\s+first|research\s+exist\s+hi\s+nahi)",
    re.IGNORECASE,
)
NUMERIC_CONFIDENCE_RE = re.compile(
    r"(?:confidence|bharosa|success|probability|chance)[^\n%]{0,45}"
    r"\b(?:[1-9]\d?(?:\.\d+)?|100)\s*%",
    re.IGNORECASE,
)
NO_SOURCE_RE = re.compile(r"\[NO[- ]SOURCE\]", re.IGNORECASE)
VERIFIED_RE = re.compile(r"(?:✅\s*)?\bVERIFIED\b|saboot\s+ka\s+star\s*:\s*✅", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _plain_mapping(value: Any) -> Dict[str, Any]:
    """Return a shallow dict without importing the engine's model classes."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    if dataclasses.is_dataclass(value):
        converted = dataclasses.asdict(value)
        return dict(converted) if isinstance(converted, Mapping) else {}
    return {}


def _list_of_mappings(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_plain_mapping(item) for item in value]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "pass", "passed", "complete"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _meaningful(value: Any, minimum: int = 8) -> bool:
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    return len(str(value or "").strip()) >= minimum


def _headings(answer: str) -> List[str]:
    return [" ".join(match.lower().split()) for match in HEADING_RE.findall(answer or "")]


def _has_section(answer: str, section: str) -> bool:
    aliases = SECTION_ALIASES.get(section, (section.replace("_", " "),))
    headings = _headings(answer)
    return any(any(alias in heading for alias in aliases) for heading in headings)


@dataclass(frozen=True)
class QualityContract:
    """What the user asked for, separated from what the run delivered."""

    required_sections: Tuple[str, ...] = DEFAULT_REQUIRED_SECTIONS
    hypotheses_requested: int = 0
    original_hypotheses_required: bool = False
    calculations_required: bool = False
    counter_search_required: bool = True
    evidence_graph_required: bool = False
    minimum_directly_relevant_sources: int = 2
    minimum_average_relevance: float = 0.65

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "QualityContract":
        data = dict(raw or {})
        sections = data.get("required_sections") or DEFAULT_REQUIRED_SECTIONS
        if isinstance(sections, str):
            sections = [sections]
        return cls(
            required_sections=tuple(str(item) for item in sections if str(item).strip()),
            hypotheses_requested=max(0, _as_int(data.get("hypotheses_requested"))),
            original_hypotheses_required=_as_bool(data.get("original_hypotheses_required")),
            calculations_required=_as_bool(data.get("calculations_required")),
            counter_search_required=(
                True if "counter_search_required" not in data
                else _as_bool(data.get("counter_search_required"))
            ),
            evidence_graph_required=_as_bool(data.get("evidence_graph_required")),
            minimum_directly_relevant_sources=max(
                1, _as_int(data.get("minimum_directly_relevant_sources"), 2)
            ),
            minimum_average_relevance=min(
                1.0, max(0.0, _as_float(data.get("minimum_average_relevance"), 0.65))
            ),
        )


@dataclass(frozen=True)
class QualityIssue:
    code: str
    category: str
    severity: str
    message: str
    deduction: int = 0
    hard_cap: Optional[int] = None
    blocks_verified: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class FinalQualityReport:
    score: int
    status: str
    release_ready: bool
    verified_allowed: bool
    answer_complete: bool
    hard_cap: int
    category_scores: Dict[str, int]
    checks: Dict[str, bool]
    issues: Tuple[QualityIssue, ...]
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "score": self.score,
            "status": self.status,
            "release_ready": self.release_ready,
            "verified_allowed": self.verified_allowed,
            "answer_complete": self.answer_complete,
            "hard_cap": self.hard_cap,
            "category_scores": dict(self.category_scores),
            "checks": dict(self.checks),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class _Evaluation:
    def __init__(self) -> None:
        self.scores: Dict[str, int] = dict(CATEGORY_WEIGHTS)
        self.issues: List[QualityIssue] = []
        self.checks: Dict[str, bool] = {}
        self.hard_cap = 100

    def check(self, name: str, passed: bool) -> None:
        self.checks[name] = bool(passed)

    def issue(
        self,
        code: str,
        category: str,
        severity: str,
        message: str,
        *,
        deduction: int = 0,
        hard_cap: Optional[int] = None,
        blocks_verified: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if deduction:
            self.scores[category] = max(0, self.scores[category] - deduction)
        if hard_cap is not None:
            self.hard_cap = min(self.hard_cap, int(hard_cap))
        self.issues.append(QualityIssue(
            code=code,
            category=category,
            severity=severity,
            message=message,
            deduction=deduction,
            hard_cap=hard_cap,
            blocks_verified=blocks_verified,
            details=dict(details or {}),
        ))


class FinalQualityGate:
    """Fail-closed, deterministic evaluator for a completed research result."""

    def evaluate(
        self,
        result: Any,
        contract: Optional[QualityContract | Mapping[str, Any]] = None,
    ) -> FinalQualityReport:
        data = _plain_mapping(result)
        if isinstance(contract, QualityContract):
            spec = contract
        else:
            contract_data = contract or data.get("quality_contract") or {}
            spec = QualityContract.from_mapping(contract_data)

        state = _Evaluation()
        answer = str(data.get("answer") or "")
        sources = _list_of_mappings(data.get("sources"))
        coverage = _plain_mapping(data.get("coverage"))
        verification = _plain_mapping(data.get("verification"))
        labels = _plain_mapping(data.get("label_report"))
        ledger = _plain_mapping(data.get("requested_ledger"))
        quality_context = _plain_mapping(data.get("quality_context"))
        calculations = _list_of_mappings(
            quality_context.get("calculations") or data.get("calculations")
        )
        hypotheses = _list_of_mappings(data.get("hypotheses"))
        contradictions = _list_of_mappings(data.get("contradictions"))

        spec = self._merge_ledger_requirements(spec, ledger)
        self._check_requirements(state, data, answer, ledger, spec)
        self._check_sources(state, sources, coverage, quality_context, spec)
        self._check_claims(state, answer, verification, labels, quality_context)
        self._check_reasoning(state, contradictions, quality_context, spec)
        self._check_calculations(state, calculations, spec)
        self._check_hypotheses(state, answer, hypotheses, quality_context, spec)
        self._check_experiments(state, hypotheses, spec)
        self._check_confidence(state, data, answer, quality_context)
        self._check_ux(state, answer)
        self._check_reliability(state, data, quality_context)

        pre_false_verified_blockers = any(issue.blocks_verified for issue in state.issues)
        claims_verified = bool(VERIFIED_RE.search(str(data.get("evidence_level") or "") + "\n" + answer))
        false_verified = claims_verified and pre_false_verified_blockers
        state.check("verified_badge_consistent", not false_verified)
        if false_verified:
            state.issue(
                "FALSE_VERIFIED_BADGE",
                "confidence_honesty",
                "critical",
                "Result contains VERIFIED even though one or more blocking quality checks failed.",
                deduction=CATEGORY_WEIGHTS["confidence_honesty"],
                hard_cap=30,
            )

        raw_score = sum(state.scores.values())
        score = max(0, min(raw_score, state.hard_cap, 100))
        blockers = [issue for issue in state.issues if issue.blocks_verified]
        answer_complete = not any(
            issue.code in {
                "MANDATORY_SECTION_MISSING",
                "REQUESTED_DELIVERABLE_MISSING",
                "INCOMPLETE_STATUS_MISMATCH",
            }
            for issue in state.issues
        )
        verified_allowed = not blockers and answer_complete
        release_ready = score == 100 and verified_allowed and all(state.checks.values())
        if release_ready:
            status = "PASS_100"
        elif answer_complete and score >= 80:
            status = "BLOCKED_REVIEW"
        elif score >= 40:
            status = "PARTIAL"
        else:
            status = "FAIL"
        return FinalQualityReport(
            score=score,
            status=status,
            release_ready=release_ready,
            verified_allowed=verified_allowed,
            answer_complete=answer_complete,
            hard_cap=state.hard_cap,
            category_scores=dict(state.scores),
            checks=dict(state.checks),
            issues=tuple(state.issues),
        )

    @staticmethod
    def _merge_ledger_requirements(spec: QualityContract, ledger: Mapping[str, Any]) -> QualityContract:
        requested = spec.hypotheses_requested
        for item in _list_of_mappings(ledger.get("items")):
            label = str(item.get("what") or "")
            match = re.search(r"\b(\d+)\s+nayi\s+testable\s+hypoth", label, re.IGNORECASE)
            if match:
                requested = max(requested, int(match.group(1)))
        if requested == spec.hypotheses_requested:
            return spec
        return dataclasses.replace(
            spec,
            hypotheses_requested=requested,
            original_hypotheses_required=True,
        )

    @staticmethod
    def _check_requirements(
        state: _Evaluation,
        data: Mapping[str, Any],
        answer: str,
        ledger: Mapping[str, Any],
        spec: QualityContract,
    ) -> None:
        missing_sections = [section for section in spec.required_sections if not _has_section(answer, section)]
        if spec.calculations_required and not _has_section(answer, "calculations"):
            missing_sections.append("calculations")
        if spec.original_hypotheses_required and not _has_section(answer, "original_hypotheses"):
            missing_sections.append("original_hypotheses")
        missing_sections = list(dict.fromkeys(missing_sections))
        state.check("mandatory_sections_present", not missing_sections)
        if missing_sections:
            state.issue(
                "MANDATORY_SECTION_MISSING",
                "requirement_coverage",
                "critical",
                "One or more mandatory answer sections are missing.",
                deduction=CATEGORY_WEIGHTS["requirement_coverage"],
                hard_cap=40 if str(data.get("status") or "").upper() == "COMPLETE" else 60,
                details={"missing_sections": missing_sections},
            )

        unmet = _list_of_mappings(ledger.get("unmet"))
        state.check("requested_deliverables_met", not unmet)
        if unmet:
            state.issue(
                "REQUESTED_DELIVERABLE_MISSING",
                "requirement_coverage",
                "critical",
                "The requested-deliverables ledger contains unmet items.",
                deduction=CATEGORY_WEIGHTS["requirement_coverage"],
                hard_cap=40 if str(data.get("status") or "").upper() == "COMPLETE" else 60,
                details={"unmet": unmet},
            )

        status = str(data.get("status") or "").strip().upper()
        missing_passes = data.get("missing_passes") or []
        inconsistent = status == "COMPLETE" and bool(missing_passes or missing_sections or unmet)
        state.check("completion_status_consistent", not inconsistent)
        if inconsistent:
            state.issue(
                "INCOMPLETE_STATUS_MISMATCH",
                "requirement_coverage",
                "critical",
                "The job is labelled COMPLETE while required work is missing.",
                deduction=CATEGORY_WEIGHTS["requirement_coverage"],
                hard_cap=40,
            )

    @staticmethod
    def _check_sources(
        state: _Evaluation,
        sources: Sequence[Mapping[str, Any]],
        coverage: Mapping[str, Any],
        quality_context: Mapping[str, Any],
        spec: QualityContract,
    ) -> None:
        source_count = len(sources)
        state.check("sources_present", source_count > 0)
        if source_count == 0:
            state.issue(
                "NO_SOURCES",
                "source_relevance",
                "critical",
                "No source was available for a research answer.",
                deduction=CATEGORY_WEIGHTS["source_relevance"],
                hard_cap=25,
            )
            return

        average = coverage.get("avg_relevance")
        if average is None:
            values = [_as_float(source.get("relevance_score")) for source in sources]
            average = sum(values) / len(values) if values else 0.0
        average = _as_float(average)
        relevant_count = _as_int(
            quality_context.get("directly_relevant_sources"),
            _as_int(coverage.get("directly_relevant_sources"), _as_int(coverage.get("on_topic_sources"))),
        )
        relevant_ok = average >= spec.minimum_average_relevance and relevant_count >= spec.minimum_directly_relevant_sources
        state.check("source_relevance_sufficient", relevant_ok)
        if not relevant_ok:
            severe = average < 0.40 or relevant_count == 0
            state.issue(
                "IRRELEVANT_EVIDENCE_PACK",
                "source_relevance",
                "critical" if severe else "major",
                "The selected evidence pack does not meet the calibrated relevance floor.",
                deduction=10 if severe else 6,
                hard_cap=40 if severe else 70,
                details={
                    "average_relevance": round(average, 3),
                    "directly_relevant_sources": relevant_count,
                    "required_average": spec.minimum_average_relevance,
                    "required_sources": spec.minimum_directly_relevant_sources,
                },
            )

        accounting_keys = (
            "sources_retrieved",
            "sources_cited",
            "sources_supporting_critical_claims",
            "directly_relevant_sources",
        )
        accounting = {key: quality_context.get(key, coverage.get(key)) for key in accounting_keys}
        accounting_complete = all(value is not None for value in accounting.values())
        counts_consistent = accounting_complete and _as_int(accounting["sources_retrieved"]) == source_count
        state.check("source_accounting_complete", accounting_complete and counts_consistent)
        if not accounting_complete or not counts_consistent:
            state.issue(
                "SOURCE_ACCOUNTING_INCOMPLETE",
                "source_relevance",
                "major",
                "Retrieved, cited, relevant and critical-support source counts are not reconciled.",
                deduction=3,
                hard_cap=90,
                details={"accounting": accounting, "actual_sources": source_count},
            )

        retracted = _as_int(coverage.get("retracted_sources"))
        state.check("no_retracted_support", retracted == 0)
        if retracted:
            state.issue(
                "RETRACTED_SOURCE_USED",
                "source_relevance",
                "critical",
                "A retracted/withdrawn source remains in the evidence pack.",
                deduction=5,
                hard_cap=50,
                details={"count": retracted},
            )

    @staticmethod
    def _check_claims(
        state: _Evaluation,
        answer: str,
        verification: Mapping[str, Any],
        labels: Mapping[str, Any],
        quality_context: Mapping[str, Any],
    ) -> None:
        invalid = verification.get("invalid_citations") or quality_context.get("invalid_citations") or []
        fabricated = _as_int(verification.get("fabricated_citations"), len(invalid) if isinstance(invalid, list) else 0)
        state.check("no_fabricated_citations", fabricated == 0)
        if fabricated:
            state.issue(
                "FABRICATED_CITATION",
                "claim_citation",
                "critical",
                "One or more citations do not resolve to a source in the evidence pack.",
                deduction=CATEGORY_WEIGHTS["claim_citation"],
                hard_cap=20,
                details={"count": fabricated},
            )

        unsupported = _as_int(
            quality_context.get("unsupported_critical_claims"),
            _as_int(labels.get("a_e_failed"), _as_int(labels.get("entailment_blocked"))),
        )
        state.check("critical_claims_supported", unsupported == 0)
        if unsupported:
            state.issue(
                "CRITICAL_CLAIM_UNSUPPORTED",
                "claim_citation",
                "critical",
                "At least one critical claim failed source-entailment verification.",
                deduction=10,
                hard_cap=40,
                details={"count": unsupported},
            )

        no_source_count = _as_int(
            quality_context.get("critical_no_source_claims"),
            len(NO_SOURCE_RE.findall(answer)),
        )
        state.check("no_critical_no_source_claims", no_source_count == 0)
        if no_source_count:
            state.issue(
                "CRITICAL_NO_SOURCE_CLAIM",
                "claim_citation",
                "critical",
                "The final answer still contains unsupported NO-SOURCE claims.",
                deduction=8,
                hard_cap=50,
                details={"count": no_source_count},
            )

        access_depth_mismatch = _as_int(quality_context.get("access_depth_mismatches"))
        state.check("access_depth_labels_accurate", access_depth_mismatch == 0)
        if access_depth_mismatch:
            state.issue(
                "ACCESS_DEPTH_MISMATCH",
                "claim_citation",
                "critical",
                "A source/claim was labelled full-text verified despite shallower access.",
                deduction=8,
                hard_cap=40,
                details={"count": access_depth_mismatch},
            )

        evidence_spans = quality_context.get("critical_claim_evidence_spans")
        spans_present = _as_bool(quality_context.get("critical_claim_spans_complete")) or (
            isinstance(evidence_spans, list) and bool(evidence_spans)
        )
        state.check("critical_claim_evidence_spans_present", spans_present)
        if not spans_present:
            state.issue(
                "EVIDENCE_SPANS_MISSING",
                "claim_citation",
                "major",
                "Critical claims do not expose exact supporting passages/pages.",
                deduction=3,
                hard_cap=90,
            )

    @staticmethod
    def _check_reasoning(
        state: _Evaluation,
        contradictions: Sequence[Mapping[str, Any]],
        quality_context: Mapping[str, Any],
        spec: QualityContract,
    ) -> None:
        counter_done = _as_bool(quality_context.get("counter_search_performed"))
        state.check("counter_search_performed", counter_done or not spec.counter_search_required)
        if spec.counter_search_required and not counter_done:
            state.issue(
                "COUNTER_SEARCH_MISSING",
                "scientific_reasoning",
                "major",
                "Only support-side retrieval is recorded; an independent counter-search is required.",
                deduction=6,
                hard_cap=70,
            )

        invalid_contradictions = 0
        required = (
            "normalized_proposition",
            "source_a_claim",
            "source_b_claim",
            "opposing_direction",
            "evidence_spans",
        )
        for contradiction in contradictions:
            if not all(_meaningful(contradiction.get(key), 2) for key in required):
                invalid_contradictions += 1
        state.check("contradictions_are_proposition_based", invalid_contradictions == 0)
        if invalid_contradictions:
            state.issue(
                "FALSE_CONTRADICTION_RECORD",
                "scientific_reasoning",
                "major",
                "A contradiction lacks comparable opposing propositions and evidence spans.",
                deduction=4,
                hard_cap=80,
                details={"count": invalid_contradictions},
            )

        if spec.evidence_graph_required:
            graph_ok = _as_bool(quality_context.get("evidence_graph_complete"))
            state.check("evidence_graph_complete", graph_ok)
            if not graph_ok:
                state.issue(
                    "EVIDENCE_GRAPH_MISSING",
                    "scientific_reasoning",
                    "major",
                    "The requested evidence graph was not delivered.",
                    deduction=4,
                    hard_cap=70,
                )

    @staticmethod
    def _check_calculations(
        state: _Evaluation,
        calculations: Sequence[Mapping[str, Any]],
        spec: QualityContract,
    ) -> None:
        if not spec.calculations_required:
            state.check("required_calculations_validated", True)
            return
        required_fields = (
            "formula",
            "inputs",
            "units",
            "assumptions",
            "result",
            "uncertainty",
        )
        complete = bool(calculations)
        bad: List[int] = []
        unsupported_numeric = False
        for index, calculation in enumerate(calculations, 1):
            fields_ok = all(_meaningful(calculation.get(field), 1) for field in required_fields)
            checks_ok = (
                _as_bool(calculation.get("unit_check_passed"))
                and _as_bool(calculation.get("recalculation_passed"))
                and _as_bool(calculation.get("sanity_check_passed"))
            )
            if not fields_ok or not checks_ok:
                bad.append(index)
            if _as_bool(calculation.get("invented_input")):
                unsupported_numeric = True
        complete = complete and not bad
        state.check("required_calculations_validated", complete)
        if not complete:
            state.issue(
                "CALCULATION_VALIDATION_MISSING",
                "calculation_validation",
                "critical",
                "A required calculation is absent or not reproducible with formula, units and assumptions.",
                deduction=CATEGORY_WEIGHTS["calculation_validation"],
                hard_cap=50,
                details={"invalid_calculations": bad, "count": len(calculations)},
            )
        if unsupported_numeric:
            state.issue(
                "UNSUPPORTED_NUMERIC_INPUT",
                "calculation_validation",
                "critical",
                "A calculation uses an invented/unsupported numeric input.",
                deduction=CATEGORY_WEIGHTS["calculation_validation"],
                hard_cap=50,
            )

    @staticmethod
    def _check_hypotheses(
        state: _Evaluation,
        answer: str,
        hypotheses: Sequence[Mapping[str, Any]],
        quality_context: Mapping[str, Any],
        spec: QualityContract,
    ) -> None:
        required_count = spec.hypotheses_requested
        required = spec.original_hypotheses_required or required_count > 0
        if not required and not hypotheses:
            state.check("original_hypotheses_separated", True)
            state.check("hypothesis_novelty_audited", True)
            return

        separated = _has_section(answer, "original_hypotheses")
        state.check("original_hypotheses_separated", separated)
        if not separated:
            state.issue(
                "HYPOTHESIS_NOT_SEPARATED",
                "original_hypotheses",
                "critical",
                "App-generated hypotheses are not isolated from sourced facts and inferences.",
                deduction=6,
                hard_cap=60,
            )

        count_ok = len(hypotheses) >= required_count if required_count else bool(hypotheses)
        state.check("requested_hypothesis_count_met", count_ok)
        if not count_ok:
            state.issue(
                "HYPOTHESIS_COUNT_SHORTFALL",
                "original_hypotheses",
                "major",
                "Fewer original hypotheses were delivered than requested.",
                deduction=5,
                hard_cap=70,
                details={"requested": required_count, "delivered": len(hypotheses)},
            )

        missing_contract: Dict[int, List[str]] = {}
        for index, hypothesis in enumerate(hypotheses, 1):
            missing: List[str] = []
            for field_name in (
                "hypothesis_id",
                "statement",
                "provenance",
                "mechanism",
                "source_claim_disclaimer",
                "closest_prior_work",
                "novelty_search",
                "novelty_status",
                "assumptions",
                "prediction",
            ):
                if not _meaningful(hypothesis.get(field_name), 2):
                    missing.append(field_name)
            novelty_status = str(hypothesis.get("novelty_status") or "").strip().upper()
            if novelty_status and novelty_status not in NOVELTY_STATUSES:
                missing.append("valid_novelty_status")
            if missing:
                missing_contract[index] = missing

        novelty_ok = not missing_contract
        state.check("hypothesis_novelty_audited", novelty_ok)
        if not novelty_ok:
            state.issue(
                "NOVELTY_AUDIT_MISSING",
                "original_hypotheses",
                "critical",
                "A hypothesis lacks provenance, nearest prior work, novelty search or a bounded novelty label.",
                deduction=8,
                hard_cap=50,
                details={"hypotheses": missing_contract},
            )

        absolute_claim = bool(ABSOLUTE_NOVELTY_RE.search(answer))
        state.check("no_absolute_novelty_claim", not absolute_claim)
        if absolute_claim:
            state.issue(
                "ABSOLUTE_NOVELTY_OVERCLAIM",
                "original_hypotheses",
                "critical",
                "The answer claims global/absolute novelty without an exhaustive worldwide proof.",
                deduction=8,
                hard_cap=50,
            )

        fact_mix = _as_int(quality_context.get("hypothesis_fact_mix_count"))
        state.check("hypotheses_not_mixed_with_facts", fact_mix == 0)
        if fact_mix:
            state.issue(
                "HYPOTHESIS_FACT_MIXING",
                "original_hypotheses",
                "critical",
                "App-generated hypotheses were presented inside established/source-reported claims.",
                deduction=8,
                hard_cap=60,
                details={"count": fact_mix},
            )

    @staticmethod
    def _check_experiments(
        state: _Evaluation,
        hypotheses: Sequence[Mapping[str, Any]],
        spec: QualityContract,
    ) -> None:
        if not hypotheses and not spec.original_hypotheses_required:
            state.check("hypothesis_tests_falsifiable", True)
            return
        required_fields = (
            "dataset_or_sample",
            "control_or_baseline",
            "measured_variables",
            "parameter_range",
            "statistical_metric",
            "success_threshold",
            "failure_threshold",
            "falsification_condition",
        )
        missing: Dict[int, List[str]] = {}
        for index, hypothesis in enumerate(hypotheses, 1):
            experiment = _plain_mapping(hypothesis.get("experiment"))
            absent = [field for field in required_fields if not _meaningful(experiment.get(field), 1)]
            if absent:
                missing[index] = absent
        valid = bool(hypotheses) and not missing
        state.check("hypothesis_tests_falsifiable", valid)
        if not valid:
            state.issue(
                "EXPERIMENT_OR_FALSIFIER_INCOMPLETE",
                "experiment_falsification",
                "major",
                "A hypothesis lacks a bounded dataset/control/metric/threshold/falsification plan.",
                deduction=CATEGORY_WEIGHTS["experiment_falsification"],
                hard_cap=70,
                details={"hypotheses": missing},
            )

    @staticmethod
    def _check_confidence(
        state: _Evaluation,
        data: Mapping[str, Any],
        answer: str,
        quality_context: Mapping[str, Any],
    ) -> None:
        numeric = bool(NUMERIC_CONFIDENCE_RE.search(answer))
        calibrated = _as_bool(quality_context.get("numeric_confidence_calibrated"))
        honest = not numeric or calibrated
        state.check("numeric_confidence_calibrated", honest)
        if not honest:
            state.issue(
                "UNCALIBRATED_NUMERIC_CONFIDENCE",
                "confidence_honesty",
                "critical",
                "A numeric confidence/success percentage is shown without calibration evidence.",
                deduction=CATEGORY_WEIGHTS["confidence_honesty"],
                hard_cap=50,
            )

        status = str(data.get("status") or "").upper()
        status_honest = status not in {"", "PENDING"}
        state.check("research_status_present", status_honest)
        if not status_honest:
            state.issue(
                "RESEARCH_STATUS_MISSING",
                "confidence_honesty",
                "major",
                "The result does not expose a final job/answer status.",
                deduction=2,
                hard_cap=90,
            )

    @staticmethod
    def _check_ux(state: _Evaluation, answer: str) -> None:
        repeated_direct = sum(1 for heading in _headings(answer) if "seedha jawab" in heading or "direct answer" in heading)
        duplicate = repeated_direct > 1
        state.check("no_duplicate_recovery_answer", not duplicate)
        if duplicate:
            state.issue(
                "DUPLICATE_RECOVERY_OUTPUT",
                "ux_clarity",
                "major",
                "Recovery assembled the direct answer more than once.",
                deduction=3,
                hard_cap=90,
            )

        footer_repeats = max(
            answer.lower().count("evidence ka level:"),
            answer.lower().count("saboot ka star:"),
        )
        state.check("no_duplicate_evidence_footer", footer_repeats <= 1)
        if footer_repeats > 1:
            state.issue(
                "DUPLICATE_EVIDENCE_FOOTER",
                "ux_clarity",
                "major",
                "Evidence/recovery footer is repeated.",
                deduction=2,
                hard_cap=90,
            )

        citations_are_readable = not bool(re.search(r"\]\[S\d+\]", answer, re.IGNORECASE))
        state.check("citations_readable", citations_are_readable)
        if not citations_are_readable:
            state.issue(
                "CITATION_FORMAT_CROWDED",
                "ux_clarity",
                "minor",
                "Adjacent citations are rendered without separators.",
                deduction=1,
                hard_cap=99,
                blocks_verified=False,
            )

    @staticmethod
    def _check_reliability(
        state: _Evaluation,
        data: Mapping[str, Any],
        quality_context: Mapping[str, Any],
    ) -> None:
        answer = str(data.get("answer") or "")
        leaked = [marker for marker in RAW_TECHNICAL_MARKERS if marker in answer.lower()]
        state.check("no_raw_developer_logs", not leaked)
        if leaked:
            state.issue(
                "RAW_DEVELOPER_LOG_LEAK",
                "reliability_privacy",
                "major",
                "Raw provider/developer diagnostics leaked into the user-facing answer.",
                deduction=CATEGORY_WEIGHTS["reliability_privacy"],
                hard_cap=90,
                details={"markers": leaked},
            )

        recovery_used = _as_bool(quality_context.get("recovery_used"))
        if recovery_used:
            snapshot_ok = _as_bool(quality_context.get("progress_snapshot_preserved"))
            state.check("recovery_progress_preserved", snapshot_ok)
            if not snapshot_ok:
                state.issue(
                    "RECOVERY_PROGRESS_MISSING",
                    "reliability_privacy",
                    "major",
                    "A recovered result did not preserve its final research-progress snapshot.",
                    deduction=2,
                    hard_cap=90,
                )
        else:
            state.check("recovery_progress_preserved", True)


def evaluate_final_quality(
    result: Any,
    contract: Optional[QualityContract | Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Convenience API for orchestrator/job-route integration."""
    return FinalQualityGate().evaluate(result, contract).to_dict()


__all__ = [
    "CATEGORY_WEIGHTS",
    "CONTRACT_VERSION",
    "FinalQualityGate",
    "FinalQualityReport",
    "QualityContract",
    "QualityIssue",
    "evaluate_final_quality",
]
