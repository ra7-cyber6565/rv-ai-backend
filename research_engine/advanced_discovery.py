"""Deterministic Advanced Scientific Discovery Engine.

This layer does not invent new facts and does not make another model/network
call.  It turns the evidence, hypotheses and verification results already
produced by :mod:`research_engine.orchestrator` into an auditable research
decision record:

* problem decomposition and an evidence graph;
* conservative novelty screening (against checked evidence/memory only);
* hypothesis tournament, falsification and virtual-experiment plans;
* a sandboxed numeric-expression executor (never arbitrary Python);
* bounded recursive next-query planning;
* confidence calibration, weakest-link analysis and a TRL/reality ladder;
* domain-specific validation requirements.

Every score is a prioritisation aid, not a probability that an idea is true.
Real novelty, safety, efficacy and feasibility still require literature search,
experiments and qualified human review.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .domain import detect as detect_domain
from .models import EvidencePack, SourceRecord


_WORD_RE = re.compile(r"[a-z0-9\u0900-\u097f][a-z0-9_\-\u0900-\u097f]*", re.I)
_SOURCE_RE = re.compile(r"\[\s*(S\d+)\s*\]", re.I)
_NEGATIVE_STATUS_RE = re.compile(
    r"FAIL|ERROR|INVALID|UNVERIFIED|INCOMPLETE|REQUIRES PHYSICAL TEST", re.I
)
_HIGH_RISK_DOMAINS = {"medicine", "biology"}


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if len(w) > 2}


def _similarity(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _bounded_text(value: Any, limit: int = 600) -> str:
    return " ".join(str(value or "").split())[:limit]


def _source_ids(text: str, valid: Iterable[str]) -> List[str]:
    allowed = {str(item).upper() for item in valid}
    out: List[str] = []
    for match in _SOURCE_RE.findall(text or ""):
        sid = match.upper()
        if sid in allowed and sid not in out:
            out.append(sid)
    return out


def _prediction_text(hypothesis: Mapping[str, Any]) -> str:
    prediction = hypothesis.get("prediction")
    if isinstance(prediction, Mapping):
        fields = [
            prediction.get("text"),
            " ".join(str(v) for v in prediction.get("variables", []) or []),
            prediction.get("expected_outcome"),
            prediction.get("measurement_method"),
            prediction.get("falsification_condition"),
        ]
        return _bounded_text(" ".join(str(x or "") for x in fields), 1200)
    return _bounded_text(prediction, 1200)


@dataclass(frozen=True)
class NumericExecutionPolicy:
    max_expression_chars: int = 240
    max_ast_nodes: int = 80
    max_variables: int = 24
    max_abs_input: float = 1e12
    max_abs_result: float = 1e18
    max_power: float = 12.0


class SafeNumericExecutor:
    """Evaluate bounded numeric expressions, never arbitrary Python code."""

    _BINARY = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Mod: lambda a, b: a % b,
    }
    _UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}
    _FUNCTIONS = {
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
    }

    def __init__(self, policy: Optional[NumericExecutionPolicy] = None):
        self.policy = policy or NumericExecutionPolicy()

    def policy_report(self) -> Dict[str, Any]:
        return {
            "mode": "numeric-expression-only",
            "arbitrary_python": False,
            "imports": False,
            "filesystem": False,
            "network": False,
            "subprocess": False,
            "randomness": False,
            "limits": {
                "expression_chars": self.policy.max_expression_chars,
                "ast_nodes": self.policy.max_ast_nodes,
                "variables": self.policy.max_variables,
                "absolute_result": self.policy.max_abs_result,
            },
        }

    def evaluate(self, expression: str,
                 variables: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
        expr = str(expression or "").strip()
        values = dict(variables or {})
        if not expr:
            return {"ok": False, "error": "empty_expression"}
        if len(expr) > self.policy.max_expression_chars:
            return {"ok": False, "error": "expression_too_long"}
        if len(values) > self.policy.max_variables:
            return {"ok": False, "error": "too_many_variables"}
        clean: Dict[str, float] = {}
        for name, value in values.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,39}", str(name)):
                return {"ok": False, "error": "invalid_variable_name"}
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return {"ok": False, "error": "non_numeric_variable"}
            number = float(value)
            if not math.isfinite(number) or abs(number) > self.policy.max_abs_input:
                return {"ok": False, "error": "variable_out_of_bounds"}
            clean[str(name)] = number
        try:
            tree = ast.parse(expr, mode="eval")
        except (SyntaxError, ValueError):
            return {"ok": False, "error": "invalid_expression"}
        if sum(1 for _ in ast.walk(tree)) > self.policy.max_ast_nodes:
            return {"ok": False, "error": "expression_too_complex"}
        try:
            result = self._eval(tree.body, clean)
            if not math.isfinite(result) or abs(result) > self.policy.max_abs_result:
                raise ValueError("result_out_of_bounds")
        except ZeroDivisionError:
            return {"ok": False, "error": "division_by_zero"}
        except (ArithmeticError, OverflowError, TypeError, ValueError) as exc:
            error = str(exc) if str(exc) in {
                "unknown_name", "unsupported_syntax", "result_out_of_bounds",
                "power_out_of_bounds", "invalid_function_arguments",
            } else "numeric_error"
            return {"ok": False, "error": error}
        return {"ok": True, "value": result, "expression": expr}

    def _eval(self, node: ast.AST, values: Mapping[str, float]) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("unsupported_syntax")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise ValueError("unknown_name")
            return float(values[node.id])
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UNARY:
            return float(self._UNARY[type(node.op)](self._eval(node.operand, values)))
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left, values), self._eval(node.right, values)
            if isinstance(node.op, ast.Pow):
                if abs(right) > self.policy.max_power or abs(left) > self.policy.max_abs_input:
                    raise ValueError("power_out_of_bounds")
                return float(left ** right)
            fn = self._BINARY.get(type(node.op))
            if fn is None:
                raise ValueError("unsupported_syntax")
            return float(fn(left, right))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = self._FUNCTIONS.get(node.func.id)
            if fn is None or node.keywords:
                raise ValueError("unsupported_syntax")
            args = [self._eval(arg, values) for arg in node.args]
            if not args or len(args) > 8:
                raise ValueError("invalid_function_arguments")
            return float(fn(*args))
        raise ValueError("unsupported_syntax")


class ProblemDecomposer:
    def __init__(self, planner: Any):
        self.planner = planner

    def decompose(self, question: str, plan: Mapping[str, Any]) -> Dict[str, Any]:
        domain_plan = detect_domain(question)
        sub_questions = self.planner.sub_questions(question, dict(plan))
        branches = domain_plan.focus_branches() or domain_plan.branches()
        branch_items = [
            {"key": branch.key, "label": branch.label, "search_query": branch.query}
            for branch in branches[:12]
        ]
        return {
            "question": question,
            "domain": domain_plan.key,
            "domain_description": domain_plan.describe(),
            "sub_questions": sub_questions[:8],
            "domain_branches": branch_items,
            "required_counter_evidence": True,
            "bounded": True,
        }


class EvidenceGraphBuilder:
    def build(self, pack: EvidencePack, hypotheses: Sequence[Mapping[str, Any]],
              contradictions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        valid = set(pack.valid_ids)
        for source in pack.sources[:40]:
            nodes.append({
                "id": source.source_id,
                "kind": "source",
                "title": _bounded_text(source.title, 180),
                "read_level": source.reading_level(),
                "relevance": round(float(source.relevance_score or 0.0), 3),
                "quality": round(float(source.quality_score or 0.0), 3),
                "retracted": source.retracted is True,
            })
        for index, hypothesis in enumerate(hypotheses[:12], 1):
            hid = f"H{index}"
            nodes.append({"id": hid, "kind": "hypothesis",
                          "label": _bounded_text(hypothesis.get("statement"), 220)})
            support = _source_ids(str(hypothesis.get("supporting_evidence") or ""), valid)
            against = _source_ids(str(hypothesis.get("contradicting_evidence") or ""), valid)
            for sid in support:
                edges.append({"from": sid, "to": hid, "relation": "supports"})
            for sid in against:
                edges.append({"from": sid, "to": hid, "relation": "challenges"})
        for index, contradiction in enumerate(contradictions[:20], 1):
            cid = f"C{index}"
            summary = _bounded_text(contradiction.get("summary") or contradiction, 260)
            nodes.append({"id": cid, "kind": "contradiction", "label": summary})
            ids = _source_ids(str(contradiction), valid)
            for sid in ids:
                edges.append({"from": sid, "to": cid, "relation": "participates_in"})
        return {
            "nodes": nodes,
            "edges": edges,
            "source_nodes": len(pack.sources[:40]),
            "hypothesis_nodes": min(len(hypotheses), 12),
            "contradiction_nodes": min(len(contradictions), 20),
            "note": "Graph sirf retrieved evidence ke explicit links dikhata hai; edge proof nahi hai.",
        }


class NoveltyChecker:
    def assess(self, hypothesis: Mapping[str, Any], pack: EvidencePack,
               remembered: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
        statement = str(hypothesis.get("statement") or "")
        candidates: List[Tuple[float, str, str]] = []
        for source in pack.sources:
            compared = f"{source.title} {source.snippet}"
            candidates.append((_similarity(statement, compared), source.source_id, "source"))
        for index, item in enumerate(remembered[:20], 1):
            compared = str(item.get("statement") or "")
            candidates.append((_similarity(statement, compared), f"M{index}", "memory"))
        candidates.sort(key=lambda row: (-row[0], row[1]))
        best = candidates[0] if candidates else (0.0, "", "")
        score = best[0]
        if score >= 0.72:
            state = "likely_already_described"
        elif score >= 0.38:
            state = "partially_overlaps_checked_material"
        else:
            state = "no_close_match_in_checked_material"
        return {
            "state": state,
            "closest_match": best[1],
            "closest_match_kind": best[2],
            "lexical_overlap": round(score, 3),
            "global_novelty_proven": False,
            "note": "Ye sirf retrieved sources aur project memory ki screening hai; patent/global novelty search nahi.",
        }


class FalsificationEngine:
    def assess(self, hypothesis: Mapping[str, Any]) -> Dict[str, Any]:
        experiment = _bounded_text(
            hypothesis.get("experiment") or hypothesis.get("how_to_test"), 1000)
        criterion = _bounded_text(hypothesis.get("falsification_test"), 800)
        prediction = _prediction_text(hypothesis)
        missing = []
        if len(prediction) < 15:
            missing.append("measurable prediction")
        if len(experiment) < 20:
            missing.append("experiment/simulation plan")
        if len(criterion) < 15:
            missing.append("explicit rejection condition")
        return {
            "falsifiable": not missing,
            "prediction": prediction,
            "test": experiment,
            "reject_if": criterion,
            "missing": missing,
            "note": "Pass hone ka matlab hypothesis sach nahi; sirf itna ki ise galat sabit karne layak test likha hai.",
        }


class VirtualExperimentDesigner:
    def design(self, hypothesis: Mapping[str, Any], domain: str) -> Dict[str, Any]:
        prediction = hypothesis.get("prediction")
        pred = prediction if isinstance(prediction, Mapping) else {}
        variables = [str(v)[:120] for v in (pred.get("variables") or [])[:12]]
        measurement = _bounded_text(pred.get("measurement_method"), 500)
        outcome = _bounded_text(pred.get("expected_outcome"), 500)
        test = _bounded_text(
            hypothesis.get("experiment") or hypothesis.get("how_to_test"), 1000)
        controls = "Matched negative/baseline control aur pre-registered comparison rule required."
        oversight = []
        if domain in _HIGH_RISK_DOMAINS:
            oversight.extend(["qualified domain expert review", "ethics approval where humans/animals are involved"])
        if not variables:
            oversight.append("variables must be specified before execution")
        if not measurement:
            oversight.append("measurement method must be specified before execution")
        return {
            "status": "DESIGN_ONLY",
            "variables": variables,
            "expected_outcome": outcome,
            "measurement": measurement,
            "procedure_from_hypothesis": test,
            "controls": controls,
            "replication": "Independent repeats and a held-out confirmation run required.",
            "oversight": oversight,
            "auto_execution_allowed": False,
            "reason": "Real-world experiment, clinical action, hardware control aur wet-lab execution human approval ke bina nahi chalega.",
        }


class ConfidenceCalibrator:
    @staticmethod
    def _access_score(pack: EvidencePack) -> float:
        weights = {"metadata": 0.1, "snippet": 0.25, "abstract": 0.55, "full_text": 1.0}
        if not pack.sources:
            return 0.0
        return sum(weights.get(s.reading_level(), 0.0) for s in pack.sources) / len(pack.sources)

    def calibrate(self, pack: EvidencePack, hypothesis: Mapping[str, Any],
                  verification: Mapping[str, Any], novelty: Mapping[str, Any],
                  falsification: Mapping[str, Any]) -> Dict[str, Any]:
        support = len(_source_ids(str(hypothesis.get("supporting_evidence") or ""), pack.valid_ids))
        components = {
            "relevance": _clamp(pack.avg_relevance),
            "access_depth": _clamp(self._access_score(pack)),
            "independence": _clamp(pack.independent_source_count / 3.0),
            "explicit_support": _clamp(support / 2.0),
            "falsifiability": 1.0 if falsification.get("falsifiable") else 0.25,
            "novelty_screening": 0.35 if novelty.get("state") == "likely_already_described" else 0.65,
        }
        score = (
            components["relevance"] * 0.20
            + components["access_depth"] * 0.20
            + components["independence"] * 0.15
            + components["explicit_support"] * 0.20
            + components["falsifiability"] * 0.20
            + components["novelty_screening"] * 0.05
        )
        caps: List[Dict[str, Any]] = []
        if not pack.sources:
            caps.append({"cap": 0.10, "reason": "no retrieved evidence"})
        if pack.full_text_read_count == 0:
            caps.append({"cap": 0.45, "reason": "no full text was read"})
        if not hypothesis.get("is_complete"):
            caps.append({"cap": 0.55, "reason": "hypothesis fields are incomplete"})
        status = str(verification.get("status") or "")
        claim_gate = verification.get("claim_checks") or {}
        if _NEGATIVE_STATUS_RE.search(status) or claim_gate.get("gate_passed") is False:
            caps.append({"cap": 0.35, "reason": "verification/claim gate did not pass"})
        if caps:
            score = min(score, min(float(item["cap"]) for item in caps))
        score = round(_clamp(score), 3)
        if score < 0.25:
            label = "very_low_pre_validation"
        elif score < 0.45:
            label = "low_pre_validation"
        elif score < 0.65:
            label = "guarded_pre_validation"
        else:
            label = "moderate_pre_validation"
        return {
            "score": score,
            "label": label,
            "components": {k: round(v, 3) for k, v in components.items()},
            "caps": caps,
            "real_world_success_probability": None,
            "note": "Score sirf research priority hai, sach hone ya real-world success ki probability nahi.",
        }


class HypothesisTournament:
    def rank(self, entries: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        ranked: List[Dict[str, Any]] = []
        for index, entry in enumerate(entries, 1):
            confidence = entry.get("confidence") or {}
            falsification = entry.get("falsification") or {}
            experiment = entry.get("experiment") or {}
            novelty = entry.get("novelty") or {}
            feasibility = 1.0
            if experiment.get("oversight"):
                feasibility -= min(0.35, 0.08 * len(experiment["oversight"]))
            completeness = 1.0 if entry.get("hypothesis", {}).get("is_complete") else 0.4
            novelty_factor = 0.25 if novelty.get("state") == "likely_already_described" else 0.65
            score = (
                float(confidence.get("score") or 0.0) * 45
                + (1.0 if falsification.get("falsifiable") else 0.2) * 25
                + completeness * 15
                + feasibility * 10
                + novelty_factor * 5
            )
            ranked.append({
                "hypothesis_id": f"H{index}",
                "priority_score": round(score, 1),
                "falsifiable": bool(falsification.get("falsifiable")),
                "confidence_label": confidence.get("label", ""),
                "note": "priority_score probability nahi hai",
            })
        ranked.sort(key=lambda item: (-item["priority_score"], item["hypothesis_id"]))
        for rank, item in enumerate(ranked, 1):
            item["rank"] = rank
        return {
            "ranking": ranked,
            "winner": ranked[0]["hypothesis_id"] if ranked else "",
            "winner_means": "sabse pehle test karne ki priority; proven truth nahi",
        }


class WeakestLinkAnalyzer:
    def analyze(self, entries: Sequence[Mapping[str, Any]], pack: EvidencePack,
                verification: Mapping[str, Any]) -> Dict[str, Any]:
        candidates: List[Tuple[float, str, str]] = []
        if not pack.sources:
            candidates.append((0.0, "evidence", "koi source retrieve nahi hua"))
        else:
            candidates.extend([
                (_clamp(pack.avg_relevance), "relevance", "source-topic match"),
                (_clamp(pack.independent_source_count / 3.0), "independence", "independent origins"),
                (_clamp(pack.full_text_read_count / max(1, len(pack.sources))), "access_depth", "full-text coverage"),
            ])
        claim_checks = verification.get("claim_checks") or {}
        if claim_checks.get("gate_passed") is False:
            candidates.append((0.0, "claim_verification", "A-E claim gate failed"))
        for index, entry in enumerate(entries, 1):
            if not (entry.get("falsification") or {}).get("falsifiable"):
                candidates.append((0.1, f"H{index}_falsifiability", "explicit reject condition missing"))
        if not candidates:
            return {"key": "not_assessed", "score": None, "reason": "insufficient structured inputs"}
        score, key, reason = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
        return {"key": key, "score": round(score, 3), "reason": reason,
                "release_effect": "Is link ko strong kiye bina discovery claim ko promote na karein."}


class AlternativePathGenerator:
    def generate(self, entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for index, entry in enumerate(entries[:6], 1):
            hypothesis = entry.get("hypothesis") or {}
            assumptions = _bounded_text(hypothesis.get("assumptions"), 300)
            counter = _bounded_text(hypothesis.get("contradicting_evidence"), 300)
            out.append({
                "for": f"H{index}",
                "path": "competing-explanation-first",
                "action": "Pehle strongest competing explanation ko same measurement aur control se test karo.",
                "assumption_to_relax": assumptions,
                "counter_evidence_to_explain": counter,
                "new_claim_created": False,
            })
        return out


class RealityLadder:
    def assess(self, pack: EvidencePack, entries: Sequence[Mapping[str, Any]],
               plan: Mapping[str, Any], verification: Mapping[str, Any]) -> Dict[str, Any]:
        applicable = bool(plan.get("is_scientific") or "technical" in (plan.get("question_types") or []))
        if not entries:
            level = 1
            reason = "testable hypothesis output nahi bana"
        elif pack.full_text_read_count <= 0:
            level = 1
            reason = "idea/test plan hai, par full-text evidence nahi padha gaya"
        elif any((entry.get("falsification") or {}).get("falsifiable") for entry in entries):
            level = 2
            reason = "concept aur falsifiable test plan defined hai"
        else:
            level = 1
            reason = "falsification condition incomplete hai"
        claim_checks = verification.get("claim_checks") or {}
        if (level >= 2 and pack.independent_source_count >= 3
                and claim_checks.get("gate_passed") is True):
            level = 3
            reason = "analytical evidence package aur independent support hai; experimental proof abhi nahi"
        labels = {1: "idea / observation", 2: "testable concept", 3: "analytical proof-of-concept"}
        return {
            "applicable": applicable,
            "level": level,
            "label": labels[level],
            "reason": reason,
            "max_inferred_without_experiment": 3,
            "next_requirement": "independent real experiment/simulation result with preregistered acceptance criteria",
            "note": "Literature-only run se TRL 4-9 infer nahi kiya jaata.",
        }


class DomainValidator:
    def validate(self, question: str, pack: EvidencePack,
                 hypotheses: Sequence[Mapping[str, Any]],
                 verification: Mapping[str, Any]) -> Dict[str, Any]:
        domain_plan = detect_domain(question)
        rejected = [s for s in pack.sources if (s.domain_verdict or {}).get("rejected")]
        requirements: List[str] = []
        if domain_plan.key in _HIGH_RISK_DOMAINS:
            requirements.extend(["ethics/safety review", "qualified clinical/domain expert", "no treatment claim from AI output"])
        elif domain_plan.key == "superconductivity":
            requirements.extend(["unit/physical-limit checks", "pressure and temperature conditions", "replication/retraction search"])
        elif domain_plan.key in {"engineering", "energy"}:
            requirements.extend(["boundary conditions", "failure-mode analysis", "independent prototype/simulation validation"])
        elif domain_plan.key in {"economics", "cs_ai"}:
            requirements.extend(["held-out validation", "baseline comparison", "dataset/assumption shift check"])
        else:
            requirements.extend(["domain expert review", "counter-evidence search"])
        status = str(verification.get("status") or "")
        return {
            "domain": domain_plan.key,
            "strict_domain_gate": domain_plan.strict,
            "sources_rejected_inside_final_pack": len(rejected),
            "verification_status": status,
            "requirements_before_real_world_use": requirements,
            "hypotheses_with_missing_fields": sum(bool(h.get("missing_fields")) for h in hypotheses),
            "passed_for_real_world_use": False,
            "note": "Automated validation research triage hai; professional approval ka replacement nahi.",
        }


class RecursiveResearchPlanner:
    def __init__(self, planner: Any):
        self.planner = planner

    def plan(self, question: str, plan: Mapping[str, Any], pack: EvidencePack,
             contradictions: Sequence[Mapping[str, Any]],
             verification: Mapping[str, Any], entries: Sequence[Mapping[str, Any]],
             max_additional_iterations: int = 2) -> Dict[str, Any]:
        gaps: List[str] = []
        if pack.full_text_read_count == 0:
            gaps.append("full-text evidence")
        if pack.independent_source_count < 3:
            gaps.append("independent sources")
        if not contradictions:
            gaps.append("explicit counter-evidence/replication search")
        if (verification.get("claim_checks") or {}).get("gate_passed") is False:
            gaps.append("failed claim-level A-E checks")
        if any(not (entry.get("falsification") or {}).get("falsifiable") for entry in entries):
            gaps.append("falsification criteria")
        next_queries: List[str] = []
        for round_no in (2, 3):
            for query in self.planner.search_queries(question, dict(plan), round_no=round_no):
                if query not in next_queries and query not in (pack.search_queries or []):
                    next_queries.append(query)
        stop = not gaps
        return {
            "iterations_already_executed": int(pack.rounds_run or 0),
            "max_additional_iterations": max(0, min(int(max_additional_iterations), 2)),
            "execute_automatically": False,
            "stop_now": stop,
            "stop_reason": "required structured gaps clear hain" if stop else "gaps remain",
            "gaps": gaps,
            "next_queries": next_queries[:8],
            "note": "Loop bounded hai; naya network/model work next approved research run mein hi hoga.",
        }


class ScientificDiscoveryEngine:
    """Compose every advanced discovery check into one stable API record."""

    schema_version = "1.0"

    def __init__(self, planner: Any):
        self.planner = planner
        self.decomposer = ProblemDecomposer(planner)
        self.graph = EvidenceGraphBuilder()
        self.novelty = NoveltyChecker()
        self.falsification = FalsificationEngine()
        self.experiments = VirtualExperimentDesigner()
        self.executor = SafeNumericExecutor()
        self.calibration = ConfidenceCalibrator()
        self.tournament = HypothesisTournament()
        self.weakest = WeakestLinkAnalyzer()
        self.alternatives = AlternativePathGenerator()
        self.reality = RealityLadder()
        self.domain = DomainValidator()
        self.recursive = RecursiveResearchPlanner(planner)

    def analyze(self, *, question: str, plan: Mapping[str, Any], pack: EvidencePack,
                hypotheses: Sequence[Mapping[str, Any]],
                contradictions: Sequence[Mapping[str, Any]],
                verification: Mapping[str, Any],
                remembered_hypotheses: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
        domain_key = detect_domain(question).key
        entries: List[Dict[str, Any]] = []
        for index, hypothesis in enumerate(hypotheses[:6], 1):
            novelty = self.novelty.assess(hypothesis, pack, remembered_hypotheses)
            falsification = self.falsification.assess(hypothesis)
            experiment = self.experiments.design(hypothesis, domain_key)
            confidence = self.calibration.calibrate(
                pack, hypothesis, verification, novelty, falsification)
            entries.append({
                "id": f"H{index}",
                "hypothesis": dict(hypothesis),
                "novelty": novelty,
                "falsification": falsification,
                "experiment": experiment,
                "confidence": confidence,
            })
        tournament = self.tournament.rank(entries)
        return {
            "schema_version": self.schema_version,
            "status": "ASSESSMENT_READY" if entries else "NO_TESTABLE_HYPOTHESES",
            "problem_decomposition": self.decomposer.decompose(question, plan),
            "evidence_graph": self.graph.build(pack, hypotheses, contradictions),
            "hypotheses": entries,
            "tournament": tournament,
            "weakest_link": self.weakest.analyze(entries, pack, verification),
            "alternative_paths": self.alternatives.generate(entries),
            "recursive_research": self.recursive.plan(
                question, plan, pack, contradictions, verification, entries),
            "reality_ladder": self.reality.assess(pack, entries, plan, verification),
            "domain_validation": self.domain.validate(
                question, pack, hypotheses, verification),
            "simulation_executor": {
                "status": "AVAILABLE_NOT_AUTO_EXECUTED",
                "policy": self.executor.policy_report(),
            },
            "global_novelty_claimed": False,
            "real_world_success_probability_claimed": False,
            "human_review_required": True,
        }
