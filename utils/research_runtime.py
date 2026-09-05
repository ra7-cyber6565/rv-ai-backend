"""Durable, tenant-scoped research checkpoints and atomic application budgets.

SQLite is in the existing private data root. No prompt can enlarge these limits.
An attempt is charged BEFORE dispatch and never refunded after an ambiguous crash.
Limits are application ceilings, not a provider billing/quota oracle.
"""
from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


class RuntimeBlocked(RuntimeError):
    pass


class ResearchCancelled(RuntimeBlocked):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(_encode(value), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def code_version():
    # Bind recovery to shipped production source, including uncommitted changes.
    root = Path(__file__).resolve().parent.parent
    h = hashlib.sha256()
    for folder in ("research_engine", "utils", "api", "knowledge"):
        for path in sorted((root / folder).rglob("*.py")):
            h.update(str(path.relative_to(root)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def _encode(value):
    if dataclasses.is_dataclass(value):
        return {"__research_model__": type(value).__name__, "fields":
                {f.name: _encode(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return {"__research_tuple__": [_encode(v) for v in value]}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("unsupported checkpoint type")


def _decode(value):
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if isinstance(value, dict):
        if set(value) == {"__research_tuple__"}:
            return tuple(_decode(v) for v in value["__research_tuple__"])
        if set(value) == {"__research_model__", "fields"}:
            from research_engine import models
            allowed = {name: getattr(models, name) for name in
                       ("EvidencePack", "SourceRecord", "Passage", "Claim")}
            cls = allowed.get(value["__research_model__"])
            if cls is None:
                raise RuntimeBlocked("checkpoint model is not allowed")
            fields = {k: _decode(v) for k, v in value["fields"].items()}
            if cls is models.SourceRecord:
                fields["source_type"] = models.SourceType(fields["source_type"])
            if cls is models.Claim and "claim_type" in fields:
                fields["claim_type"] = models.ClaimType(fields["claim_type"])
            return cls(**fields)
        return {k: _decode(v) for k, v in value.items()}
    return value


class RuntimeStore:
    def __init__(self, path=None):
        if path is None:
            from utils.storage_paths import ensure_layout
            path = Path(ensure_layout()["research_memory"]) / "research_runtime.sqlite3"
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS runs (
                project TEXT, run TEXT, fingerprint TEXT, version TEXT,
                deadline REAL, cancelled INTEGER DEFAULT 0, limits TEXT,
                http INTEGER DEFAULT 0, input_bytes INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0, PRIMARY KEY(project,run));
              CREATE TABLE IF NOT EXISTS stages (
                project TEXT, run TEXT, stage TEXT, fingerprint TEXT,
                state TEXT, owner TEXT, updated REAL, payload TEXT, sha TEXT,
                PRIMARY KEY(project,run,stage));
              CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT,
                run TEXT, at REAL, kind TEXT, detail TEXT);
              CREATE TABLE IF NOT EXISTS provider_usage (
                provider TEXT, window INTEGER, http INTEGER,
                input_bytes INTEGER, output_tokens INTEGER,
                PRIMARY KEY(provider,window));
            """)

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def start(self, project, run, fingerprint, version, limits):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE project=? AND run=?", (project, run)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint or row["version"] != version:
                    raise RuntimeBlocked("resume inputs or code changed; start a new run")
                if json.loads(row["limits"]) != limits:
                    raise RuntimeBlocked("resume cannot enlarge or change resource limits")
            else:
                # Expired checkpoints cannot resume after their original deadline;
                # retain them for six further days for inspection, then prune.
                expired = db.execute("SELECT project,run FROM runs WHERE deadline<?", (time.time()-6*86400,)).fetchall()
                for old in expired:
                    for table in ("stages", "events", "runs"):
                        db.execute(f"DELETE FROM {table} WHERE project=? AND run=?", (old["project"], old["run"]))
                if db.execute("SELECT count(*) FROM runs").fetchone()[0] >= 2000:
                    raise RuntimeBlocked("runtime retention capacity reached")
                cancelled = db.execute("SELECT 1 FROM events WHERE project=? AND run=? AND kind='CANCEL_REQUESTED' LIMIT 1", (project, run)).fetchone()
                db.execute("INSERT INTO runs(project,run,fingerprint,version,deadline,limits,cancelled) VALUES(?,?,?,?,?,?,?)",
                           (project, run, fingerprint, version, time.time() + limits["seconds"], json.dumps(limits), int(bool(cancelled))))

    @staticmethod
    def _check(row):
        if row is None:
            raise RuntimeBlocked("research runtime is unavailable")
        if row["cancelled"]:
            raise ResearchCancelled("research was cancelled")
        if time.time() >= row["deadline"]:
            raise RuntimeBlocked("research elapsed-time budget exhausted")

    def check(self, project, run):
        with self.db() as db:
            self._check(db.execute("SELECT * FROM runs WHERE project=? AND run=?", (project, run)).fetchone())

    def cancel(self, project, run):
        with self.transaction() as db:
            db.execute("UPDATE runs SET cancelled=1 WHERE project=? AND run=?", (project, run))
            self._event(db, project, run, "CANCEL_REQUESTED", {})

    @staticmethod
    def _event(db, project, run, kind, detail):
        text = json.dumps(detail, sort_keys=True, ensure_ascii=False)
        if len(text) > 4000:
            raise ValueError("event payload too large")
        db.execute("INSERT INTO events(project,run,at,kind,detail) VALUES(?,?,?,?,?)",
                   (project, run, time.time(), kind, text))

    def reserve(self, project, run, provider, prompt, max_output_tokens):
        size = len(prompt.encode("utf-8"))
        if type(max_output_tokens) is not int or max_output_tokens < 0:
            raise ValueError("invalid output-token reservation")
        # Operator ceilings are shared across projects, keys, processes and retries.
        def setting(name, default):
            value = int(os.getenv(name, str(default)))
            if value < 1:
                raise RuntimeBlocked("invalid operator resource limit")
            return value
        caps = (setting("RESEARCH_PROVIDER_HTTP_PER_HOUR", 120),
                setting("RESEARCH_PROVIDER_INPUT_BYTES_PER_HOUR", 24000000),
                setting("RESEARCH_PROVIDER_OUTPUT_TOKENS_PER_HOUR", 720000))
        window = int(time.time() // 3600)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE project=? AND run=?", (project, run)).fetchone()
            self._check(row)
            limits = json.loads(row["limits"])
            amounts = (1, size, max_output_tokens)
            fields = ("http", "input_bytes", "output_tokens")
            if any(row[k] + v > limits[k] for k, v in zip(fields, amounts)):
                raise RuntimeBlocked("research call/input/output budget exhausted")
            usage = db.execute("SELECT * FROM provider_usage WHERE provider=? AND window=?", (provider, window)).fetchone()
            if usage and any(usage[k] + v > cap for k, v, cap in zip(fields, amounts, caps)):
                raise RuntimeBlocked("shared provider application budget exhausted")
            if any(v > cap for v, cap in zip(amounts, caps)):
                raise RuntimeBlocked("request exceeds provider application ceiling")
            db.execute("UPDATE runs SET http=http+1,input_bytes=input_bytes+?,output_tokens=output_tokens+? WHERE project=? AND run=?",
                       (size, max_output_tokens, project, run))
            db.execute("INSERT INTO provider_usage VALUES(?,?,?,?,?) ON CONFLICT(provider,window) DO UPDATE SET http=http+1,input_bytes=input_bytes+excluded.input_bytes,output_tokens=output_tokens+excluded.output_tokens",
                       (provider, window, 1, size, max_output_tokens))
            self._event(db, project, run, "REQUEST_RESERVED", {"provider": provider,
                "input_bytes": size, "max_output_tokens": max_output_tokens})

    def claim(self, project, run, stage, fingerprint, owner, *, replay_safe):
        with self.transaction() as db:
            self._check(db.execute("SELECT * FROM runs WHERE project=? AND run=?", (project, run)).fetchone())
            row = db.execute("SELECT * FROM stages WHERE project=? AND run=? AND stage=?", (project, run, stage)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise RuntimeBlocked("stage inputs changed")
                if row["state"] == "COMPLETED":
                    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha"]:
                        raise RuntimeBlocked("checkpoint checksum mismatch")
                    self._event(db, project, run, "CHECKPOINT_REUSED", {"stage": stage})
                    return True, _decode(json.loads(row["payload"]))
                if not replay_safe:
                    raise RuntimeBlocked("effect outcome unknown; reconciliation required before replay")
                if row["state"] == "RUNNING" and time.time() - row["updated"] < 900:
                    raise RuntimeBlocked("stage is already owned by another execution")
            db.execute("INSERT INTO stages VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(project,run,stage) DO UPDATE SET state='RUNNING',owner=excluded.owner,updated=excluded.updated",
                       (project, run, stage, fingerprint, "RUNNING", owner, time.time(), "", ""))
            self._event(db, project, run, "STAGE_RUNNING", {"stage": stage})
            return False, None

    def finish(self, project, run, stage, owner, value):
        payload = json.dumps(_encode(value), ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > 16000000:
            raise RuntimeBlocked("checkpoint exceeds 16 MB stage limit")
        with self.transaction() as db:
            self._check(db.execute("SELECT * FROM runs WHERE project=? AND run=?", (project, run)).fetchone())
            cap = max(0, int(os.environ.get("RESEARCH_CHECKPOINT_BYTES", "268435456")))
            used = db.execute("SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM stages").fetchone()[0]
            old = db.execute("SELECT length(CAST(payload AS BLOB)) FROM stages WHERE project=? AND run=? AND stage=?", (project, run, stage)).fetchone()
            if used - (old[0] if old else 0) + len(payload.encode()) > cap:
                raise RuntimeBlocked("shared checkpoint payload capacity reached")
            changed = db.execute("UPDATE stages SET state='COMPLETED',payload=?,sha=?,updated=? WHERE project=? AND run=? AND stage=? AND owner=? AND state='RUNNING'",
                (payload, hashlib.sha256(payload.encode()).hexdigest(), time.time(), project, run, stage, owner)).rowcount
            if changed != 1:
                raise RuntimeBlocked("stage ownership changed")
            self._event(db, project, run, "STAGE_COMPLETED", {"stage": stage})

    def fail(self, project, run, stage, owner):
        with self.transaction() as db:
            db.execute("UPDATE stages SET state='INTERRUPTED',updated=? WHERE project=? AND run=? AND stage=? AND owner=?",
                       (time.time(), project, run, stage, owner))
            self._event(db, project, run, "STAGE_INTERRUPTED", {"stage": stage})

    def recover(self, project, run):
        # Only the job runner holding its exclusive process lock may call this
        # after it has established that the old execution cannot still be alive.
        with self.transaction() as db:
            db.execute("UPDATE stages SET state='INTERRUPTED' WHERE project=? AND run=? AND state='RUNNING'", (project, run))

    def snapshot(self, project, run):
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE project=? AND run=?", (project, run)).fetchone()
            if row is None:
                return {"available": False}
            events = db.execute("SELECT sequence,at,kind,detail FROM events WHERE project=? AND run=? ORDER BY sequence DESC LIMIT 200", (project, run)).fetchall()
            return {"available": True, "run_id": run, "cancelled": bool(row["cancelled"]),
                "reserved_http_attempts": row["http"], "input_utf8_bytes": row["input_bytes"],
                "reserved_max_output_tokens": row["output_tokens"], "actual_tokens": "UNKNOWN",
                "limits": json.loads(row["limits"]), "events": [dict(e, detail=json.loads(e["detail"])) for e in reversed(events)],
                "event_durability": "SQLITE_TRANSACTION", "eligibility_enforced_by": "existing_confirmed_zero_cost_guard"}


_CURRENT = contextvars.ContextVar("research_runtime", default=None)


@dataclasses.dataclass(frozen=True)
class RunContext:
    store: RuntimeStore
    project: str
    run: str

    def wire(self):
        return {"path": self.store.path, "project": self.project, "run": self.run}


def current():
    return _CURRENT.get()


@contextlib.contextmanager
def bind(context):
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def check_cancelled():
    ctx = current()
    if ctx:
        ctx.store.check(ctx.project, ctx.run)


def reserve_request(provider, prompt, max_output_tokens=6000):
    ctx = current()
    if ctx:
        ctx.store.reserve(ctx.project, ctx.run, provider, prompt, max_output_tokens)


def checkpoint(stage, inputs, action, *, replay_safe=True, with_receipt=False):
    ctx = current()
    if ctx is None:
        value = action()
        return (value, False) if with_receipt else value
    owner = uuid.uuid4().hex
    found, result = ctx.store.claim(ctx.project, ctx.run, stage, digest(inputs), owner, replay_safe=replay_safe)
    if found:
        return (result, True) if with_receipt else result
    try:
        result = action()
        ctx.store.finish(ctx.project, ctx.run, stage, owner, result)
        return (result, False) if with_receipt else result
    except BaseException:
        ctx.store.fail(ctx.project, ctx.run, stage, owner)
        raise
