"""Persistent scientific memory and living-belief infrastructure.

This is deliberately evidence/accounting infrastructure rather than an LLM prompt.
It provides immutable prediction registration, temporal facts, versioned beliefs,
truth-debt accounting, model graveyard/champion-challenger state, calibration,
dependency shock propagation, and a hash-chained append-only audit trail.

It uses only the Python standard library and atomic local JSON writes so the
foundation remains zero-cost and inspectable.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


_SCHEMA_VERSION = 1
_ALLOWED_DIRECTIONS = {">", ">=", "<", "<=", "=="}
_ALLOWED_MODEL_STATUS = {"candidate", "champion", "challenger", "rejected", "retired"}
_ALLOWED_BELIEF_STATUS = {"ACTIVE", "SUPERSEDED", "REJECTED", "UNCERTAIN"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str, field: str = "id") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > 200:
        raise ValueError(f"{field} is too long")
    if not re.fullmatch(r"[A-Za-z0-9_.:@/+~-]+", text):
        raise ValueError(f"{field} contains unsupported characters")
    return text


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _probability(value: Any, field: str = "confidence") -> float:
    number = _finite_number(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return number


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _default_directory() -> str:
    configured = str(os.getenv("SCIENTIFIC_MEMORY_DIR", "")).strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    try:
        from utils.storage_paths import ensure_layout
        layout = ensure_layout()
        root = layout.get("research_memory") or layout.get("root")
        if root:
            return os.path.join(root, "scientific")
    except Exception:
        pass
    return os.path.abspath("./research_memory/scientific")


@dataclass(frozen=True)
class PromotionDecision:
    promoted: bool
    champion_id: str
    challenger_id: str
    reasons: Tuple[str, ...]


class ScientificMemory:
    """Durable, fail-closed state for scientific claims and model lifecycle."""

    def __init__(self, project_id: str = "default", directory: Optional[str] = None):
        self.project_id = _safe_id(project_id or "default", "project_id")
        self.directory = os.path.abspath(directory or _default_directory())
        self._data: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.project_id)
        return os.path.join(self.directory, f"{safe}.scientific.json")

    @staticmethod
    def _blank(project_id: str) -> Dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_id": project_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "audit_chain": [],
            "temporal_facts": {},
            "beliefs": {},
            "assumptions": {},
            "predictions": {},
            "models": {},
            "dependencies": [],
            "node_reliability": {},
        }

    def load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if not os.path.exists(self.path):
            self._data = self._blank(self.project_id)
            return self._data

        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("scientific memory root must be an object")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported scientific memory schema version")
        if data.get("project_id") != self.project_id:
            raise ValueError("scientific memory project_id mismatch")
        for key, expected in self._blank(self.project_id).items():
            if key not in data:
                raise ValueError(f"scientific memory missing required field: {key}")
            if key in {"created_at", "updated_at", "schema_version", "project_id"}:
                continue
            if not isinstance(data[key], type(expected)):
                raise ValueError(f"scientific memory field {key} has invalid type")
        self._verify_audit_chain(data.get("audit_chain") or [])
        self._data = data
        return self._data

    def save(self) -> None:
        data = self.load()
        data["updated_at"] = _now_iso()
        os.makedirs(self.directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="scientific_", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _verify_audit_chain(chain: Sequence[Mapping[str, Any]]) -> None:
        previous = "GENESIS"
        for index, event in enumerate(chain, start=1):
            if not isinstance(event, Mapping):
                raise ValueError("audit chain event must be an object")
            if event.get("previous_hash") != previous:
                raise ValueError(f"audit chain broken at event {index}")
            payload = {
                "sequence": event.get("sequence"),
                "at": event.get("at"),
                "kind": event.get("kind"),
                "object_id": event.get("object_id"),
                "details_hash": event.get("details_hash"),
                "previous_hash": event.get("previous_hash"),
            }
            expected = _sha256(payload)
            if event.get("event_hash") != expected:
                raise ValueError(f"audit chain hash mismatch at event {index}")
            previous = expected

    def _append_audit(self, kind: str, object_id: str, details: Mapping[str, Any]) -> str:
        data = self.load()
        chain = data["audit_chain"]
        previous = chain[-1]["event_hash"] if chain else "GENESIS"
        payload = {
            "sequence": len(chain) + 1,
            "at": _now_iso(),
            "kind": str(kind),
            "object_id": str(object_id),
            "details_hash": _sha256(details),
            "previous_hash": previous,
        }
        event_hash = _sha256(payload)
        chain.append({**payload, "event_hash": event_hash})
        return event_hash

    def audit_integrity(self) -> Dict[str, Any]:
        chain = self.load()["audit_chain"]
        self._verify_audit_chain(chain)
        return {
            "valid": True,
            "events": len(chain),
            "head_hash": chain[-1]["event_hash"] if chain else "GENESIS",
        }

    # ---- temporal knowledge -------------------------------------------------

    def record_temporal_fact(
        self,
        fact_id: str,
        *,
        subject: str,
        predicate: str,
        object_value: Any,
        valid_from: str,
        valid_to: Optional[str] = None,
        context: str = "",
        evidence_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        fact_id = _safe_id(fact_id, "fact_id")
        if not str(subject).strip() or not str(predicate).strip() or not str(valid_from).strip():
            raise ValueError("subject, predicate and valid_from are required")
        if valid_to and str(valid_to) < str(valid_from):
            raise ValueError("valid_to must not precede valid_from")
        fact = {
            "fact_id": fact_id,
            "subject": str(subject).strip(),
            "predicate": str(predicate).strip(),
            "object": object_value,
            "valid_from": str(valid_from),
            "valid_to": str(valid_to) if valid_to else None,
            "context": str(context or "")[:2000],
            "evidence_ids": sorted({_safe_id(item, "evidence_id") for item in evidence_ids}),
            "recorded_at": _now_iso(),
        }
        store = self.load()["temporal_facts"]
        existing = store.get(fact_id)
        if existing and _sha256({k: v for k, v in existing.items() if k != "recorded_at"}) != _sha256(
            {k: v for k, v in fact.items() if k != "recorded_at"}
        ):
            raise ValueError("temporal fact id is immutable; use a new fact_id for a changed assertion")
        store[fact_id] = existing or fact
        if not existing:
            self._append_audit("temporal_fact_recorded", fact_id, fact)
        return dict(store[fact_id])

    def facts_at(self, when: str, *, subject: Optional[str] = None) -> List[Dict[str, Any]]:
        when = str(when)
        out = []
        for fact in self.load()["temporal_facts"].values():
            if subject is not None and fact.get("subject") != subject:
                continue
            if fact["valid_from"] <= when and (fact.get("valid_to") is None or when <= fact["valid_to"]):
                out.append(dict(fact))
        return sorted(out, key=lambda item: (item["subject"], item["predicate"], item["fact_id"]))

    # ---- versioned beliefs --------------------------------------------------

    def add_belief_version(
        self,
        belief_id: str,
        *,
        statement: str,
        confidence: float,
        evidence_ids: Sequence[str] = (),
        reason: str,
        status: str = "ACTIVE",
    ) -> Dict[str, Any]:
        belief_id = _safe_id(belief_id, "belief_id")
        confidence = _probability(confidence)
        status = str(status).upper()
        if status not in _ALLOWED_BELIEF_STATUS:
            raise ValueError(f"unsupported belief status: {status}")
        if not str(statement).strip() or not str(reason).strip():
            raise ValueError("statement and reason are required")
        store = self.load()["beliefs"].setdefault(belief_id, [])
        if store and store[-1].get("status") == "ACTIVE":
            store[-1]["status"] = "SUPERSEDED"
            store[-1]["superseded_at"] = _now_iso()
        version = {
            "belief_id": belief_id,
            "version": len(store) + 1,
            "statement": str(statement).strip(),
            "confidence": confidence,
            "evidence_ids": sorted({_safe_id(item, "evidence_id") for item in evidence_ids}),
            "reason": str(reason).strip()[:4000],
            "status": status,
            "created_at": _now_iso(),
        }
        version["content_hash"] = _sha256(
            {k: v for k, v in version.items() if k not in {"created_at", "content_hash"}}
        )
        store.append(version)
        self.load()["node_reliability"][belief_id] = confidence
        self._append_audit("belief_version_added", belief_id, version)
        return dict(version)

    def belief_history(self, belief_id: str) -> List[Dict[str, Any]]:
        belief_id = _safe_id(belief_id, "belief_id")
        return [dict(item) for item in self.load()["beliefs"].get(belief_id, [])]

    # ---- truth debt ---------------------------------------------------------

    def register_assumption(
        self,
        assumption_id: str,
        *,
        text: str,
        confidence: float,
        downstream_ids: Sequence[str] = (),
        severity: float = 1.0,
        evidence_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        assumption_id = _safe_id(assumption_id, "assumption_id")
        confidence = _probability(confidence)
        severity = _finite_number(severity, "severity")
        if severity < 0:
            raise ValueError("severity must be >= 0")
        record = {
            "assumption_id": assumption_id,
            "text": str(text).strip(),
            "confidence": confidence,
            "severity": severity,
            "downstream_ids": sorted({_safe_id(item, "downstream_id") for item in downstream_ids}),
            "evidence_ids": sorted({_safe_id(item, "evidence_id") for item in evidence_ids}),
            "resolved": False,
            "resolution": None,
            "created_at": _now_iso(),
        }
        if not record["text"]:
            raise ValueError("assumption text is required")
        store = self.load()["assumptions"]
        if assumption_id in store:
            raise ValueError("assumption_id already exists")
        store[assumption_id] = record
        self._append_audit("assumption_registered", assumption_id, record)
        return dict(record)

    def resolve_assumption(self, assumption_id: str, *, resolution: str, supported: bool) -> None:
        assumption_id = _safe_id(assumption_id, "assumption_id")
        record = self.load()["assumptions"].get(assumption_id)
        if not record:
            raise KeyError(assumption_id)
        if record.get("resolved"):
            raise ValueError("assumption is already resolved")
        record["resolved"] = True
        record["supported"] = bool(supported)
        record["resolution"] = str(resolution).strip()[:4000]
        record["resolved_at"] = _now_iso()
        self._append_audit("assumption_resolved", assumption_id, record)

    def truth_debt_report(self) -> Dict[str, Any]:
        items = []
        total = 0.0
        for record in self.load()["assumptions"].values():
            if record.get("resolved"):
                continue
            impact = max(1, len(record.get("downstream_ids") or []))
            debt = (1.0 - float(record["confidence"])) * float(record["severity"]) * impact
            total += debt
            items.append({
                "assumption_id": record["assumption_id"],
                "confidence": record["confidence"],
                "severity": record["severity"],
                "downstream_count": len(record.get("downstream_ids") or []),
                "debt": round(debt, 6),
            })
        items.sort(key=lambda item: item["debt"], reverse=True)
        return {"total_truth_debt": round(total, 6), "unresolved": len(items), "items": items}

    # ---- prediction registry and calibration -------------------------------

    def preregister_prediction(
        self,
        prediction_id: str,
        *,
        hypothesis_id: str,
        condition: str,
        metric: str,
        direction: str,
        threshold: float,
        evaluation_after: str,
        protocol_hash: str,
    ) -> Dict[str, Any]:
        prediction_id = _safe_id(prediction_id, "prediction_id")
        hypothesis_id = _safe_id(hypothesis_id, "hypothesis_id")
        direction = str(direction).strip()
        if direction not in _ALLOWED_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(_ALLOWED_DIRECTIONS)}")
        if not str(condition).strip() or not str(metric).strip() or not str(protocol_hash).strip():
            raise ValueError("condition, metric and protocol_hash are required")
        record = {
            "prediction_id": prediction_id,
            "hypothesis_id": hypothesis_id,
            "condition": str(condition).strip(),
            "metric": str(metric).strip(),
            "direction": direction,
            "threshold": _finite_number(threshold, "threshold"),
            "evaluation_after": str(evaluation_after).strip(),
            "protocol_hash": str(protocol_hash).strip(),
            "registered_at": _now_iso(),
            "resolved": False,
            "outcome": None,
        }
        frozen = {k: v for k, v in record.items() if k not in {"registered_at", "resolved", "outcome"}}
        record["registration_hash"] = _sha256(frozen)
        store = self.load()["predictions"]
        if prediction_id in store:
            existing = store[prediction_id]
            if existing.get("registration_hash") != record["registration_hash"]:
                raise ValueError("registered prediction is immutable")
            return dict(existing)
        store[prediction_id] = record
        self._append_audit("prediction_registered", prediction_id, frozen)
        return dict(record)

    @staticmethod
    def _threshold_pass(direction: str, observed: float, threshold: float) -> bool:
        if direction == ">":
            return observed > threshold
        if direction == ">=":
            return observed >= threshold
        if direction == "<":
            return observed < threshold
        if direction == "<=":
            return observed <= threshold
        return observed == threshold

    def resolve_prediction(
        self,
        prediction_id: str,
        *,
        observed_value: float,
        evaluated_at: Optional[str] = None,
        evidence_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        prediction_id = _safe_id(prediction_id, "prediction_id")
        record = self.load()["predictions"].get(prediction_id)
        if not record:
            raise KeyError(prediction_id)
        if record.get("resolved"):
            raise ValueError("prediction is already resolved")
        observed = _finite_number(observed_value, "observed_value")
        outcome = {
            "observed_value": observed,
            "passed": self._threshold_pass(record["direction"], observed, float(record["threshold"])),
            "evaluated_at": str(evaluated_at or _now_iso()),
            "evidence_ids": sorted({_safe_id(item, "evidence_id") for item in evidence_ids}),
        }
        record["resolved"] = True
        record["outcome"] = outcome
        self._append_audit("prediction_resolved", prediction_id, outcome)
        return dict(outcome)

    def calibration_report(self) -> Dict[str, Any]:
        rows = []
        for prediction in self.load()["predictions"].values():
            if not prediction.get("resolved"):
                continue
            hypothesis_id = prediction.get("hypothesis_id")
            histories = self.load()["beliefs"].get(hypothesis_id, [])
            if not histories:
                continue
            confidence = float(histories[-1]["confidence"])
            rows.append((confidence, 1.0 if prediction["outcome"]["passed"] else 0.0))
        if not rows:
            return {"count": 0, "brier_score": None, "mean_confidence": None, "observed_rate": None}
        brier = sum((confidence - outcome) ** 2 for confidence, outcome in rows) / len(rows)
        return {
            "count": len(rows),
            "brier_score": round(brier, 6),
            "mean_confidence": round(sum(c for c, _ in rows) / len(rows), 6),
            "observed_rate": round(sum(o for _, o in rows) / len(rows), 6),
        }

    # ---- model graveyard and champion/challenger ----------------------------

    def register_model(
        self,
        model_id: str,
        *,
        metrics: Mapping[str, float],
        holdout_id: str,
        implementation_hash: str,
        independent_validation_ids: Sequence[str] = (),
        status: str = "candidate",
    ) -> Dict[str, Any]:
        model_id = _safe_id(model_id, "model_id")
        status = str(status).lower()
        if status not in _ALLOWED_MODEL_STATUS:
            raise ValueError(f"unsupported model status: {status}")
        if not metrics:
            raise ValueError("metrics are required")
        normalized_metrics = {
            str(key): _finite_number(value, f"metrics[{key}]") for key, value in metrics.items()
        }
        record = {
            "model_id": model_id,
            "metrics": normalized_metrics,
            "holdout_id": _safe_id(holdout_id, "holdout_id"),
            "implementation_hash": str(implementation_hash).strip(),
            "independent_validation_ids": sorted(
                {_safe_id(item, "independent_validation_id") for item in independent_validation_ids}
            ),
            "status": status,
            "registered_at": _now_iso(),
            "rejection_reasons": [],
        }
        if not record["implementation_hash"]:
            raise ValueError("implementation_hash is required")
        store = self.load()["models"]
        if model_id in store:
            raise ValueError("model_id already exists")
        store[model_id] = record
        self._append_audit("model_registered", model_id, record)
        return dict(record)

    def reject_model(self, model_id: str, *, reasons: Sequence[str]) -> None:
        model_id = _safe_id(model_id, "model_id")
        record = self.load()["models"].get(model_id)
        if not record:
            raise KeyError(model_id)
        clean = [str(item).strip()[:1000] for item in reasons if str(item).strip()]
        if not clean:
            raise ValueError("at least one rejection reason is required")
        record["status"] = "rejected"
        record["rejection_reasons"] = clean
        record["rejected_at"] = _now_iso()
        self._append_audit("model_rejected", model_id, {"reasons": clean})

    def model_graveyard(self) -> List[Dict[str, Any]]:
        rows = [
            dict(model) for model in self.load()["models"].values()
            if model.get("status") == "rejected"
        ]
        return sorted(rows, key=lambda item: item["model_id"])

    def promote_challenger(
        self,
        champion_id: str,
        challenger_id: str,
        *,
        objectives: Mapping[str, str],
        require_independent_validation: bool = True,
        require_distinct_holdout: bool = False,
    ) -> PromotionDecision:
        champion_id = _safe_id(champion_id, "champion_id")
        challenger_id = _safe_id(challenger_id, "challenger_id")
        models = self.load()["models"]
        champion = models.get(champion_id)
        challenger = models.get(challenger_id)
        if not champion or not challenger:
            raise KeyError("champion or challenger model not registered")
        reasons: List[str] = []

        if challenger.get("status") == "rejected":
            reasons.append("challenger is rejected")
        if require_independent_validation and not challenger.get("independent_validation_ids"):
            reasons.append("challenger has no independent validation")
        if require_distinct_holdout and challenger.get("holdout_id") == champion.get("holdout_id"):
            reasons.append("challenger did not use a distinct holdout")
        if not objectives:
            reasons.append("no objective metrics defined")

        for metric, direction in objectives.items():
            if metric not in champion["metrics"] or metric not in challenger["metrics"]:
                reasons.append(f"missing objective metric: {metric}")
                continue
            old = float(champion["metrics"][metric])
            new = float(challenger["metrics"][metric])
            if direction == "max":
                if not new > old:
                    reasons.append(f"{metric} did not improve")
            elif direction == "min":
                if not new < old:
                    reasons.append(f"{metric} did not improve")
            else:
                reasons.append(f"invalid objective direction for {metric}: {direction}")

        promoted = not reasons
        if promoted:
            champion["status"] = "retired"
            champion["retired_at"] = _now_iso()
            challenger["status"] = "champion"
            challenger["promoted_at"] = _now_iso()
            kind = "challenger_promoted"
        else:
            kind = "challenger_rejected_for_promotion"
        self._append_audit(
            kind,
            challenger_id,
            {"champion_id": champion_id, "objectives": dict(objectives), "reasons": reasons},
        )
        return PromotionDecision(promoted, champion_id, challenger_id, tuple(reasons))

    # ---- dependency graph / shock propagation -------------------------------

    def set_node_reliability(self, node_id: str, reliability: float) -> None:
        node_id = _safe_id(node_id, "node_id")
        self.load()["node_reliability"][node_id] = _probability(reliability, "reliability")
        self._append_audit(
            "node_reliability_set", node_id, {"reliability": self.load()["node_reliability"][node_id]}
        )

    def add_dependency(self, dependent_id: str, dependency_id: str, *, weight: float = 1.0) -> None:
        dependent_id = _safe_id(dependent_id, "dependent_id")
        dependency_id = _safe_id(dependency_id, "dependency_id")
        if dependent_id == dependency_id:
            raise ValueError("self dependency is not allowed")
        weight = _probability(weight, "weight")
        edge = {"dependent_id": dependent_id, "dependency_id": dependency_id, "weight": weight}
        edges = self.load()["dependencies"]
        if edge not in edges:
            edges.append(edge)
            self._append_audit("dependency_added", dependent_id, edge)

    def propagate_dependency_shock(
        self,
        source_id: str,
        *,
        new_reliability: float,
    ) -> Dict[str, Any]:
        source_id = _safe_id(source_id, "source_id")
        new_reliability = _probability(new_reliability, "new_reliability")
        data = self.load()
        reliabilities = data["node_reliability"]
        old_source = float(reliabilities.get(source_id, 1.0))
        reliabilities[source_id] = new_reliability

        adjacency: Dict[str, List[Tuple[str, float]]] = {}
        for edge in data["dependencies"]:
            adjacency.setdefault(edge["dependency_id"], []).append(
                (edge["dependent_id"], float(edge["weight"]))
            )

        impacted: Dict[str, Dict[str, float]] = {}
        queue: List[Tuple[str, float]] = [(source_id, max(0.0, old_source - new_reliability))]
        best_loss: Dict[str, float] = {source_id: max(0.0, old_source - new_reliability)}
        while queue:
            parent, parent_loss = queue.pop(0)
            for child, weight in adjacency.get(parent, []):
                propagated_loss = parent_loss * weight
                if propagated_loss <= best_loss.get(child, -1.0) + 1e-15:
                    continue
                best_loss[child] = propagated_loss
                old = float(reliabilities.get(child, 1.0))
                new = max(0.0, min(1.0, old - propagated_loss))
                reliabilities[child] = new
                impacted[child] = {
                    "old_reliability": round(old, 6),
                    "new_reliability": round(new, 6),
                    "loss": round(old - new, 6),
                }
                queue.append((child, old - new))

        result = {
            "source_id": source_id,
            "old_source_reliability": round(old_source, 6),
            "new_source_reliability": round(new_reliability, 6),
            "impacted": impacted,
        }
        self._append_audit("dependency_shock_propagated", source_id, result)
        return result
