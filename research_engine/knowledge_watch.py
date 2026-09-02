"""Living-knowledge watch state machine.

Scheduling/network retrieval are intentionally separate concerns.  Given a
periodic observation of a known source, this module versions content, detects
material status/content changes, records retractions/removals/corrections, and
queues every dependent claim for revalidation exactly once until resolved.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence


_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,240}$")
_ALLOWED_STATUS = {"ACTIVE", "CORRECTED", "RETRACTED", "REMOVED", "UNKNOWN"}


def _stable_token(prefix: str, value: str) -> str:
    digest = hashlib.sha256(" ".join(str(value or "").split()).casefold().encode(
        "utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def update_from_research_run(
    watch: "KnowledgeWatch",
    *,
    pack: Any,
    claim_checks: Mapping[str, Any],
) -> Dict[str, Any]:
    """Persist stable A-E claim/source dependencies from a real run.

    Run-local ``S1``/``CL001`` labels are deliberately not persisted as global
    identity.  Claims use normalized text hashes and sources use DOI/URL/title
    identity.  Only same-source A-E support is linked.  The observation hashes
    stable provider metadata, not query-selected passages, so a different
    question cannot manufacture a content-change event.
    """
    sources = {str(getattr(row, "source_id", "") or ""): row
               for row in (getattr(pack, "sources", None) or [])}
    observed: set[str] = set()
    linked = 0
    queued: set[str] = set()
    skipped = 0
    for claim in list(claim_checks.get("claims") or []):
        if not isinstance(claim, Mapping) or not claim.get("same_source_ae_passed"):
            continue
        local_sid = str(claim.get("supporting_source_id") or "")
        source = sources.get(local_sid)
        text = str(claim.get("text") or claim.get("claim") or "").strip()
        if source is None or not text:
            skipped += 1
            continue
        identity = (str(getattr(source, "doi", "") or "").strip()
                    or str(getattr(source, "url", "") or "").strip()
                    or str(getattr(source, "title", "") or "").strip())
        if not identity:
            skipped += 1
            continue
        stable_sid = _stable_token("source", identity)
        stable_cid = _stable_token("claim", text)
        watch.link_claim(stable_cid, [stable_sid])
        linked += 1
        if stable_sid not in observed:
            metadata = {
                "identity": identity,
                "title": str(getattr(source, "title", "") or ""),
                "doi": str(getattr(source, "doi", "") or ""),
                "url": str(getattr(source, "url", "") or ""),
            }
            status = ("RETRACTED" if getattr(source, "retracted", None) is True
                      else "ACTIVE")
            receipt = watch.observe_source(
                stable_sid,
                content=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                status=status,
                version_label=str(getattr(source, "year", "") or ""),
                locator=str(getattr(source, "locator", "") or ""),
                note="stable metadata observation; selected passages excluded",
            )
            queued.update(receipt.get("queued_claim_ids") or [])
            observed.add(stable_sid)
    watch.save()
    return {
        "ran": True,
        "linked_claims": linked,
        "observed_sources": len(observed),
        "skipped_unstable_rows": skipped,
        "newly_queued_claims": sorted(queued),
        "pending_revalidations": len(watch.pending_revalidations()),
        "stable_identity": True,
        "selected_passages_hashed_as_source_content": False,
        "truth_proven": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} is empty or invalid")
    return text


def sha256_content(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, (bytes, bytearray)):
        raise ValueError("content must be bytes or text")
    return hashlib.sha256(bytes(content)).hexdigest()


class KnowledgeWatch:
    def __init__(self, directory: str, project_id: str = "default"):
        self.directory = os.path.abspath(directory)
        self.project_id = _safe_id(project_id, "project_id")
        self._data: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.project_id)
        return os.path.join(self.directory, f"{safe}.knowledge-watch.json")

    def _blank(self) -> Dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_id": self.project_id,
            "sources": {},
            "claim_sources": {},
            "revalidation_queue": {},
            "events": [],
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
            raise ValueError("invalid knowledge-watch schema/project")
        for field in ("sources", "claim_sources", "revalidation_queue"):
            if not isinstance(data.get(field), dict):
                raise ValueError(f"invalid knowledge-watch field: {field}")
        if not isinstance(data.get("events"), list):
            raise ValueError("invalid knowledge-watch events")
        self._data = data
        return data

    def save(self) -> None:
        data = self.load()
        data["updated_at"] = _now()
        os.makedirs(self.directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".watch_", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            if os.path.exists(temp):
                os.remove(temp)

    def link_claim(self, claim_id: str, source_ids: Sequence[str]) -> None:
        claim_id = _safe_id(claim_id, "claim_id")
        sources = sorted({_safe_id(item, "source_id") for item in source_ids})
        if not sources:
            raise ValueError("at least one source_id is required")
        self.load()["claim_sources"][claim_id] = sources

    def _dependent_claims(self, source_id: str) -> List[str]:
        return sorted(
            claim_id for claim_id, sources in self.load()["claim_sources"].items()
            if source_id in sources
        )

    def _event(self, source_id: str, kind: str, details: Mapping[str, Any]) -> Dict[str, Any]:
        event = {
            "sequence": len(self.load()["events"]) + 1,
            "at": _now(),
            "source_id": source_id,
            "kind": kind,
            "details": dict(details),
        }
        self.load()["events"].append(event)
        return event

    def _queue_dependents(self, source_id: str, event_kind: str) -> List[str]:
        queued = []
        for claim_id in self._dependent_claims(source_id):
            key = f"{claim_id}|{source_id}"
            existing = self.load()["revalidation_queue"].get(key)
            if existing and existing.get("status") == "PENDING":
                continue
            self.load()["revalidation_queue"][key] = {
                "claim_id": claim_id,
                "source_id": source_id,
                "trigger": event_kind,
                "status": "PENDING",
                "queued_at": _now(),
                "resolved_at": None,
                "replacement_evidence_ids": [],
            }
            queued.append(claim_id)
        return queued

    def observe_source(
        self,
        source_id: str,
        *,
        content: bytes | str | None,
        status: str = "ACTIVE",
        version_label: str = "",
        locator: str = "",
        note: str = "",
    ) -> Dict[str, Any]:
        source_id = _safe_id(source_id, "source_id")
        status = str(status).upper().strip()
        if status not in _ALLOWED_STATUS:
            raise ValueError(f"unsupported source status: {status}")
        if status in {"ACTIVE", "CORRECTED", "RETRACTED"} and content is None:
            raise ValueError(f"{status} observations require content bytes/text")
        digest = sha256_content(content) if content is not None else None
        sources = self.load()["sources"]
        previous = sources.get(source_id)

        if previous is None:
            kind = "NEW_SOURCE"
        elif previous["status"] == "REMOVED" and status != "REMOVED":
            kind = "RESTORED"
        elif status == "RETRACTED" and previous["status"] != "RETRACTED":
            kind = "RETRACTED"
        elif status == "REMOVED" and previous["status"] != "REMOVED":
            kind = "REMOVED"
        elif digest is not None and previous.get("content_sha256") != digest:
            kind = "CONTENT_CHANGED"
        elif version_label and previous.get("version_label") != version_label:
            kind = "VERSION_CHANGED"
        elif previous["status"] != status:
            kind = "STATUS_CHANGED"
        else:
            kind = "UNCHANGED"

        version_record = {
            "observed_at": _now(),
            "content_sha256": digest,
            "status": status,
            "version_label": str(version_label),
            "locator": str(locator),
            "note": str(note)[:2000],
        }
        history = list(previous.get("history", [])) if previous else []
        if kind != "UNCHANGED":
            history.append(version_record)
        sources[source_id] = {
            "source_id": source_id,
            **version_record,
            "history": history,
        }
        event = self._event(source_id, kind, {
            "previous_status": previous.get("status") if previous else None,
            "new_status": status,
            "previous_hash": previous.get("content_sha256") if previous else None,
            "new_hash": digest,
            "version_label": str(version_label),
        })
        material = kind in {"RETRACTED", "REMOVED", "CONTENT_CHANGED", "STATUS_CHANGED", "VERSION_CHANGED"}
        queued = self._queue_dependents(source_id, kind) if material else []
        return {"event": event, "material_change": material, "queued_claim_ids": queued}

    def pending_revalidations(self) -> List[Dict[str, Any]]:
        rows = [
            dict(row) for row in self.load()["revalidation_queue"].values()
            if row.get("status") == "PENDING"
        ]
        return sorted(rows, key=lambda row: (row["claim_id"], row["source_id"]))

    def resolve_revalidation(
        self,
        claim_id: str,
        source_id: str,
        *,
        outcome: str,
        replacement_evidence_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        claim_id = _safe_id(claim_id, "claim_id")
        source_id = _safe_id(source_id, "source_id")
        key = f"{claim_id}|{source_id}"
        row = self.load()["revalidation_queue"].get(key)
        if not row or row.get("status") != "PENDING":
            raise KeyError("no pending revalidation for claim/source")
        outcome = str(outcome).upper().strip()
        if outcome not in {"CONFIRMED", "WEAKENED", "REJECTED", "REPLACED", "UNRESOLVED"}:
            raise ValueError("unsupported revalidation outcome")
        replacements = sorted({_safe_id(item, "evidence_id") for item in replacement_evidence_ids})
        if outcome == "REPLACED" and not replacements:
            raise ValueError("REPLACED outcome requires replacement evidence")
        row.update({
            "status": "RESOLVED",
            "outcome": outcome,
            "replacement_evidence_ids": replacements,
            "resolved_at": _now(),
        })
        return dict(row)

    def source_history(self, source_id: str) -> List[Dict[str, Any]]:
        source_id = _safe_id(source_id, "source_id")
        source = self.load()["sources"].get(source_id)
        if not source:
            raise KeyError(source_id)
        return [dict(item) for item in source.get("history", [])]

    def events(self, *, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if source_id is not None:
            source_id = _safe_id(source_id, "source_id")
        return [
            dict(event) for event in self.load()["events"]
            if source_id is None or event["source_id"] == source_id
        ]
