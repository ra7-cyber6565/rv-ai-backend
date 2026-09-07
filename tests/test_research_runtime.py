"""Real SQLite/process tests; no provider calls or mocked durability."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from utils.research_runtime import (RuntimeStore, RunContext, RuntimeBlocked,
    ResearchCancelled, bind, checkpoint, digest, reserve_request)


class RuntimeAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RuntimeStore(Path(self.temp.name) / "state.sqlite3")
        self.limits = {"http": 3, "input_bytes": 1000, "output_tokens": 300, "seconds": 3600}
        self.store.start("p", "r", "input", "v1", self.limits)
        self.ctx = RunContext(self.store, "p", "r")

    def test_parallel_processes_cannot_double_spend(self):
        source = """import sys
from utils.research_runtime import RuntimeStore,RuntimeBlocked
s=RuntimeStore(sys.argv[1])
try:
 s.reserve('p','r','fixture','abc',10)
 print('RESERVED')
except RuntimeBlocked:
 print('BLOCKED')
"""
        def run(_):
            p = subprocess.run([sys.executable, "-c", source, self.store.path],
                               capture_output=True, text=True, timeout=15)
            self.assertEqual(p.returncode, 0, p.stderr)
            return p.stdout.strip()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, range(12)))
        self.assertEqual(results.count("RESERVED"), 3)
        self.assertEqual(results.count("BLOCKED"), 9)
        self.assertEqual(self.store.snapshot("p", "r")["reserved_http_attempts"], 3)

    def test_provider_ceiling_is_shared_across_projects(self):
        self.store.start("other", "s", "input", "v1", self.limits)
        with patch.dict(os.environ, {"RESEARCH_PROVIDER_HTTP_PER_HOUR": "1"}):
            self.store.reserve("p", "r", "fixture", "abc", 10)
            with self.assertRaises(RuntimeBlocked):
                self.store.reserve("other", "s", "fixture", "abc", 10)
        self.assertEqual(self.store.snapshot("other", "s")["reserved_http_attempts"], 0)

    def test_restart_reuses_committed_effect_once(self):
        effects = []
        with bind(self.ctx):
            first = checkpoint("artifact_write", {"x": 1},
                               lambda: effects.append(1) or {"artifact": "sha"}, replay_safe=False)
        fresh = RunContext(RuntimeStore(self.store.path), "p", "r")
        with bind(fresh):
            again = checkpoint("artifact_write", {"x": 1},
                               lambda: effects.append(2), replay_safe=False)
        self.assertEqual(first, again)
        self.assertEqual(effects, [1])

    def test_ambiguous_effect_is_not_replayed_after_crash(self):
        self.store.claim("p", "r", "external_write", digest({}), "dead-process", replay_safe=False)
        self.store.recover("p", "r")
        with bind(self.ctx), self.assertRaisesRegex(RuntimeBlocked, "reconciliation"):
            checkpoint("external_write", {}, lambda: self.fail("must not duplicate"), replay_safe=False)

    def test_interrupted_read_can_resume_without_repeating_completed_read(self):
        effects = []
        with bind(self.ctx):
            checkpoint("read_a", {}, lambda: effects.append("a") or "saved")
        self.store.claim("p", "r", "read_b", digest({}), "dead-process", replay_safe=True)
        self.store.recover("p", "r")
        with bind(self.ctx):
            self.assertEqual(checkpoint("read_a", {}, lambda: self.fail("repeated")), "saved")
            checkpoint("read_b", {}, lambda: effects.append("b"))
        self.assertEqual(effects, ["a", "b"])

    def test_cancel_is_durable_and_stops_new_reservations(self):
        self.store.cancel("p", "r")
        with self.assertRaises(ResearchCancelled):
            RuntimeStore(self.store.path).reserve("p", "r", "fixture", "a", 10)
        self.assertEqual(self.store.snapshot("p", "r")["reserved_http_attempts"], 0)

    def test_cancel_before_runtime_start_is_not_lost(self):
        self.store.cancel("p", "future")
        self.store.start("p", "future", "i", "v", self.limits)
        with self.assertRaises(ResearchCancelled):
            self.store.check("p", "future")

    def test_cancelled_stage_cannot_publish_checkpoint(self):
        self.store.claim("p", "r", "late", digest({}), "owner", replay_safe=True)
        self.store.cancel("p", "r")
        with self.assertRaises(ResearchCancelled):
            self.store.finish("p", "r", "late", "owner", {"answer": "too late"})
        with self.store.db() as db:
            self.assertNotEqual(db.execute("SELECT state FROM stages WHERE stage='late'").fetchone()[0], "COMPLETED")

    def test_checkpoint_bytes_are_shared_across_projects_and_use_utf8(self):
        from unittest.mock import patch
        self.store.start("other", "second", "i", "v", self.limits)
        with patch.dict(os.environ, {"RESEARCH_CHECKPOINT_BYTES": "12"}):
            with bind(self.ctx):
                checkpoint("first", {}, lambda: "ééé")  # Eight UTF-8 bytes including quotes.
            with bind(RunContext(self.store, "other", "second")):
                with self.assertRaisesRegex(RuntimeBlocked, "payload capacity"):
                    checkpoint("second", {}, lambda: "ééé")

    def test_resume_rejects_changed_inputs_version_and_budgets(self):
        for fingerprint, version, limits in [("new", "v1", self.limits),
                ("input", "v2", self.limits), ("input", "v1", dict(self.limits, http=4))]:
            with self.assertRaises(RuntimeBlocked):
                self.store.start("p", "r", fingerprint, version, limits)

    def test_corrupt_checkpoint_fails_closed(self):
        with bind(self.ctx):
            checkpoint("x", {}, lambda: {"truth": "unknown"})
        with self.store.db() as db:
            db.execute("UPDATE stages SET payload='{}'")
        with bind(self.ctx), self.assertRaisesRegex(RuntimeBlocked, "checksum"):
            checkpoint("x", {}, lambda: self.fail("corruption cannot silently retry"))

    def test_no_prompt_or_secret_in_events(self):
        with bind(self.ctx):
            reserve_request("fixture", "private document SECRET_CANARY", 10)
        receipt = self.store.snapshot("p", "r")
        self.assertNotIn("SECRET_CANARY", json.dumps(receipt))
        self.assertEqual(receipt["actual_tokens"], "UNKNOWN")
        self.assertFalse(self.store.snapshot("other", "r")["available"])


if __name__ == "__main__":
    unittest.main()
