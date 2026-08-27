"""Evidence-gated procedural memory for reusable research methods.

A procedure is not promoted merely because it was generated once. Versions are
fingerprinted, outcomes are recorded across contexts, failures are classified,
and promotion requires repeated successful evidence under explicit thresholds.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence


_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,200}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class ProceduralMemory:
    def __init__(self, directory: str, project_id: str = "default"):
        self.directory = os.path.abspath(directory)
        self.project_id = _safe_id(project_id, "project_id")
        self._data: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.project_id)
        return os.path.join(self.directory, f"{safe}.procedures.json")

    def _blank(self) -> Dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_id": self.project_id,
            "procedures": {},
            "outcomes": [],
            "updated_at": _now(),
        }

    def load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        if not os.path.exists(self.path):
            self._data = self._blank()
            return self._data
        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("schema_version") != _SCHEMA_VERSION or data.get("project_id") != self.project_id:
            raise ValueError("invalid procedural memory schema/project")
        if not isinstance(data.get("procedures"), dict) or not isinstance(data.get("outcomes"), list):
            raise ValueError("invalid procedural memory structure")
        self._data = data
        return data

    def save(self) -> None:
        data = self.load()
        data["updated_at"] = _now()
        os.makedirs(self.directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".procedure_", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)

    def add_version(
        self,
        procedure_id: str,
        *,
        name: str,
        steps: Sequence[str],
        preconditions: Sequence[str] = (),
        failure_checks: Sequence[str] = (),
        provenance_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        procedure_id = _safe_id(procedure_id, "procedure_id")
        clean_steps = tuple(str(item).strip() for item in steps if str(item).strip())
        if not str(name).strip() or not clean_steps:
            raise ValueError("procedure name and at least one step are required")
        recipe = {
            "name": str(name).strip(),
            "steps": clean_steps,
            "preconditions": tuple(str(item).strip() for item in preconditions if str(item).strip()),
            "failure_checks": tuple(str(item).strip() for item in failure_checks if str(item).strip()),
        }
        fingerprint = _fingerprint(recipe)
        versions = self.load()["procedures"].setdefault(procedure_id, [])
        for version in versions:
            if version["fingerprint"] == fingerprint:
                return dict(version)
        record = {
            "procedure_id": procedure_id,
            "version": len(versions) + 1,
            **recipe,
            "provenance_ids": sorted({_safe_id(item, "provenance_id") for item in provenance_ids}),
            "fingerprint": fingerprint,
            "status": "CANDIDATE",
            "created_at": _now(),
        }
        versions.append(record)
        return dict(record)

    def record_outcome(
        self,
        procedure_id: str,
        version: int,
        *,
        run_id: str,
        context_id: str,
        success: bool,
        metrics: Optional[Mapping[str, float]] = None,
        failure_class: str = "",
        evidence_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        procedure_id = _safe_id(procedure_id, "procedure_id")
        run_id = _safe_id(run_id, "run_id")
        context_id = _safe_id(context_id, "context_id")
        versions = self.load()["procedures"].get(procedure_id, [])
        if not 1 <= int(version) <= len(versions):
            raise KeyError(f"unknown procedure version: {procedure_id} v{version}")
        if any(row.get("run_id") == run_id for row in self.load()["outcomes"]):
            raise ValueError("run_id already recorded")
        if not success and not str(failure_class).strip():
            raise ValueError("failed outcomes require failure_class")
        normalized_metrics: Dict[str, float] = {}
        for key, value in (metrics or {}).items():
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"metric {key} must be finite")
            normalized_metrics[str(key)] = number
        row = {
            "procedure_id": procedure_id,
            "version": int(version),
            "run_id": run_id,
            "context_id": context_id,
            "success": bool(success),
            "metrics": normalized_metrics,
            "failure_class": str(failure_class).strip(),
            "evidence_ids": sorted({_safe_id(item, "evidence_id") for item in evidence_ids}),
            "recorded_at": _now(),
        }
        self.load()["outcomes"].append(row)
        return dict(row)

    def evidence_summary(self, procedure_id: str, version: int) -> Dict[str, Any]:
        procedure_id = _safe_id(procedure_id, "procedure_id")
        rows = [
            row for row in self.load()["outcomes"]
            if row["procedure_id"] == procedure_id and row["version"] == int(version)
        ]
        successes = sum(1 for row in rows if row["success"])
        failures = len(rows) - successes
        contexts = {row["context_id"] for row in rows}
        failure_rate = failures / len(rows) if rows else None
        return {
            "runs": len(rows),
            "successes": successes,
            "failures": failures,
            "distinct_contexts": len(contexts),
            "failure_rate": round(failure_rate, 6) if failure_rate is not None else None,
            "failure_classes": sorted({row["failure_class"] for row in rows if row["failure_class"]}),
        }

    def evaluate_promotion(
        self,
        procedure_id: str,
        version: int,
        *,
        min_successes: int = 3,
        min_distinct_contexts: int = 2,
        max_failure_rate: float = 0.25,
    ) -> Dict[str, Any]:
        if min_successes < 1 or min_distinct_contexts < 1 or not 0 <= max_failure_rate <= 1:
            raise ValueError("invalid promotion thresholds")
        summary = self.evidence_summary(procedure_id, version)
        reasons = []
        if summary["successes"] < min_successes:
            reasons.append("insufficient successful runs")
        if summary["distinct_contexts"] < min_distinct_contexts:
            reasons.append("insufficient context diversity")
        if summary["failure_rate"] is None or summary["failure_rate"] > max_failure_rate:
            reasons.append("failure rate exceeds threshold or is unknown")
        promoted = not reasons
        versions = self.load()["procedures"].get(procedure_id, [])
        if not 1 <= int(version) <= len(versions):
            raise KeyError(f"unknown procedure version: {procedure_id} v{version}")
        versions[int(version) - 1]["status"] = "PROMOTED" if promoted else "CANDIDATE"
        versions[int(version) - 1]["promotion_evidence"] = summary
        return {"promoted": promoted, "reasons": reasons, "summary": summary}

    def recommend(self, *, promoted_only: bool = True) -> List[Dict[str, Any]]:
        rows = []
        for versions in self.load()["procedures"].values():
            for version in versions:
                if promoted_only and version.get("status") != "PROMOTED":
                    continue
                rows.append(dict(version))
        return sorted(rows, key=lambda row: (row["procedure_id"], row["version"]))

    def duplicate_recipe_groups(self) -> List[Dict[str, Any]]:
        """Return non-destructive consolidation candidates by exact fingerprint."""
        groups: Dict[str, List[str]] = {}
        for procedure_id, versions in self.load()["procedures"].items():
            for version in versions:
                groups.setdefault(version["fingerprint"], []).append(f"{procedure_id}:v{version['version']}")
        return [
            {"fingerprint": fingerprint, "members": sorted(members)}
            for fingerprint, members in sorted(groups.items()) if len(members) > 1
        ]
