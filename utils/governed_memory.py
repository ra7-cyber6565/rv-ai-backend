"""Project-scoped inspectable memory with provenance and correction propagation.

Generated conclusions are unverified records. Source corrections invalidate every
registered derived run, including final checkpoints and previously saved API results.
"""
from __future__ import annotations
import json
import time
from .research_runtime import RuntimeStore, digest


class GovernedMemory:
    KINDS = {"preference", "project_state", "source", "execution", "hypothesis", "conclusion"}

    def __init__(self, runtime=None):
        self.runtime = runtime or RuntimeStore()
        with self.runtime.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS memory_entries (
                project TEXT, id TEXT, kind TEXT, body TEXT, trust TEXT,
                status TEXT, created REAL, expires REAL, revision INTEGER,
                PRIMARY KEY(project,id));
              CREATE TABLE IF NOT EXISTS memory_refs (
                project TEXT, id TEXT, source TEXT, PRIMARY KEY(project,id,source));
              CREATE TABLE IF NOT EXISTS run_sources (
                project TEXT, run TEXT, source TEXT, PRIMARY KEY(project,run,source));
              CREATE TABLE IF NOT EXISTS invalidated_runs (
                project TEXT, run TEXT, at REAL, reason TEXT, PRIMARY KEY(project,run));
              CREATE TABLE IF NOT EXISTS source_corrections (
                project TEXT, source TEXT, at REAL, reason TEXT, PRIMARY KEY(project,source));
            """)

    def put(self, project, kind, body, *, sources=(), record_id=None, user_supplied=False):
        if kind not in self.KINDS or not isinstance(body, dict):
            raise ValueError("invalid memory record")
        text = json.dumps(body, ensure_ascii=False, allow_nan=False)
        if len(text.encode()) > 64000 or len(sources) > 80:
            raise ValueError("memory record too large")
        refs = sorted({str(s) for s in sources if isinstance(s, str) and 0 < len(s) <= 2000})
        identity = record_id or digest([kind, body])
        trust = "USER_SUPPLIED_UNVERIFIED" if user_supplied else "GENERATED_UNVERIFIED"
        with self.runtime.transaction() as db:
            count = db.execute("SELECT count(*) FROM memory_entries WHERE project=?", (project,)).fetchone()[0]
            existing = db.execute("SELECT revision FROM memory_entries WHERE project=? AND id=?", (project, identity)).fetchone()
            if count >= 1000 and not existing:
                raise ValueError("project memory limit reached; export/delete old records")
            revision = existing[0] + 1 if existing else 1
            db.execute("INSERT OR REPLACE INTO memory_entries VALUES(?,?,?,?,?,?,?,?,?)",
                       (project, identity, kind, text, trust, "UNVERIFIED", time.time(), time.time()+30*86400, revision))
            db.execute("DELETE FROM memory_refs WHERE project=? AND id=?", (project, identity))
            db.executemany("INSERT INTO memory_refs VALUES(?,?,?)", [(project, identity, s) for s in refs])
        return identity

    def inspect(self, project):
        with self.runtime.db() as db:
            rows = db.execute("SELECT * FROM memory_entries WHERE project=? ORDER BY created,id", (project,)).fetchall()
            records = []
            for row in rows:
                data = dict(row)
                data["body"] = json.loads(data["body"])
                data["sources"] = [r[0] for r in db.execute("SELECT source FROM memory_refs WHERE project=? AND id=?", (project, row["id"]))]
                if data["expires"] < time.time() and data["status"] == "UNVERIFIED":
                    data["status"] = "REVALIDATION_DUE"
                records.append(data)
            return {"schema_version": 1, "records": records, "count": len(records),
                "scope": "governed research records", "generated_text_is_evidence": False,
                "retention": "up to 1000 records/project; 30-day revalidation; no automatic trust promotion"}

    def record_result(self, project, run, result):
        sources = sorted({str(s.get("url")) for s in result.get("sources", [])
                          if isinstance(s, dict) and s.get("url")})[:80]
        # This is a compact memory hint. The canonical result remains in its job.
        self.put(project, "conclusion", {"run_id": run, "question": str(result.get("question", ""))[:1000],
            "summary": str(result.get("answer", ""))[:8000], "reported_status": result.get("status"),
            "not_evidence": True}, sources=sources, record_id="run_" + run)
        with self.runtime.transaction() as db:
            db.executemany("INSERT OR IGNORE INTO run_sources VALUES(?,?,?)", [(project, run, s) for s in sources])
            runtime = db.execute("SELECT deadline,limits FROM runs WHERE project=? AND run=?", (project, run)).fetchone()
            started = runtime["deadline"] - json.loads(runtime["limits"])["seconds"] if runtime else 0
            for source in sources:
                correction = db.execute("SELECT at,reason FROM source_corrections WHERE project=? AND source=?", (project, source)).fetchone()
                if correction and correction["at"] >= started:
                    db.execute("INSERT OR REPLACE INTO invalidated_runs VALUES(?,?,?,?)", (project, run, correction["at"], correction["reason"]))
                    db.execute("UPDATE memory_entries SET status='REASSESSMENT_REQUIRED' WHERE project=? AND id=?", (project, "run_" + run))

    def invalidate_source(self, project, source, reason):
        if not source or len(source) > 2000 or not reason.strip() or len(reason) > 1000:
            raise ValueError("source and correction reason required")
        with self.runtime.transaction() as db:
            db.execute("INSERT OR REPLACE INTO source_corrections VALUES(?,?,?,?)", (project, source, time.time(), reason))
            affected = db.execute("SELECT DISTINCT run FROM run_sources WHERE project=? AND source=?", (project, source)).fetchall()
            db.execute("UPDATE memory_entries SET status='REASSESSMENT_REQUIRED',revision=revision+1 WHERE project=? AND id IN (SELECT id FROM memory_refs WHERE project=? AND source=?)", (project, project, source))
            for row in affected:
                db.execute("INSERT OR REPLACE INTO invalidated_runs VALUES(?,?,?,?)", (project, row[0], time.time(), reason))
            return {"affected_runs": [row[0] for row in affected], "status": "REASSESSMENT_REQUIRED",
                    "reason": reason, "source": source}

    def reassessment(self, project, run):
        with self.runtime.db() as db:
            row = db.execute("SELECT at,reason FROM invalidated_runs WHERE project=? AND run=?", (project, run)).fetchone()
            return dict(row) if row else None

    def delete(self, project, record_id):
        with self.runtime.transaction() as db:
            row = db.execute("SELECT body FROM memory_entries WHERE project=? AND id=?", (project, record_id)).fetchone()
            if row is None:
                return False
            body = json.loads(row[0])
            run = body.get("run_id")
            if run:
                # Delete derived prompt-bearing checkpoints, and invalidate the
                # archived result so future API reads cannot serve stale context.
                db.execute("DELETE FROM stages WHERE project=? AND run=?", (project, run))
                db.execute("INSERT OR REPLACE INTO invalidated_runs VALUES(?,?,?,?)", (project, run, time.time(), "Dependent memory was deleted."))
            db.execute("DELETE FROM memory_refs WHERE project=? AND id=?", (project, record_id))
            db.execute("DELETE FROM memory_entries WHERE project=? AND id=?", (project, record_id))
            return True

    def context(self, project, question):
        import re
        from research_engine.source_prompt_guard import quote_untrusted
        terms = set(re.findall(r"\w{3,}", question.casefold()))
        rows = []
        for row in self.inspect(project)["records"]:
            if row["status"] != "UNVERIFIED":
                continue
            text = json.dumps(row["body"], ensure_ascii=False)
            overlap = len(terms & set(re.findall(r"\w{3,}", text.casefold())))
            if overlap:
                rows.append((overlap, row["created"], text))
        text = "\n".join(v[2] for v in sorted(rows, reverse=True)[:3])
        return ("UNTRUSTED MEMORY HINTS — not evidence, authority or verified facts:\n" +
                quote_untrusted(text, limit=8000)) if text else ""
