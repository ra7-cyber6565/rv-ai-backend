import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_company_host as host


class CompanyHostLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "temp").mkdir()
        self.identity = "a" * 40

    def ready(self, live=False):
        return {"code_revision": self.identity, "repository_clean": True, "host_ready": True,
            "host_blockers": [], "live_preflight": {"ready": live}, "release_ready": False}

    def run_main(self, *args, ready=None, suites=None):
        output = io.StringIO()
        with patch.object(host, "setup_env"), patch.object(host, "inspect_host", return_value=ready or self.ready()), \
             patch.object(host, "run_isolation_suites", return_value=suites or {"builds": {"passed": True}}) as checks, \
             patch.object(host, "run_live_modes") as live, patch.object(host, "prepare") as prepare, \
             patch.object(host, "serve_local") as serve, contextlib.redirect_stdout(output):
            code = host.main(["--data-root", str(self.root), *args])
        receipt = json.loads((self.root / "audit" / "company_host_latest.json").read_text())
        return code, receipt, checks, live, prepare, serve

    def test_default_preflight_never_installs_tests_calls_models_or_starts_server(self):
        code, receipt, *actions = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(receipt["state"], "PREFLIGHT_READY")
        self.assertFalse(receipt["release_ready"])
        for action in actions:
            action.assert_not_called()

    def test_host_pass_cannot_turn_missing_model_eligibility_into_live_pass(self):
        code, receipt, checks, live, prepare, serve = self.run_main("--execute-host", "--execute-live", "--serve")
        self.assertEqual(code, 2)
        self.assertEqual(receipt["state"], "HOST_VALIDATED_LIVE_NOT_VERIFIED")
        checks.assert_called_once(); live.assert_not_called(); serve.assert_not_called()
        self.assertEqual(receipt["live_tests"], "NOT_TESTED")

    def test_host_failure_blocks_live_and_serving_even_with_eligible_model(self):
        code, receipt, checks, live, prepare, serve = self.run_main("--execute-host", "--execute-live", "--serve",
            ready=self.ready(True), suites={"builds": {"passed": False}})
        self.assertEqual(code, 2)
        self.assertEqual(receipt["state"], "HOST_TEST_FAILED")
        live.assert_not_called(); serve.assert_not_called()

    def test_skipped_or_zero_test_lane_cannot_certify_host(self):
        for summary in ("Ran 7 tests in 1s\nOK (skipped=2)", "OK"):
            with patch.object(host, "quiet_run", return_value=(0, summary)):
                result = host.run_isolation_suites()
            self.assertTrue(all(not row["passed"] for row in result.values()))

    def test_fresh_wrong_revision_live_receipt_rejected_and_second_call_not_spent(self):
        def fake(command, **kwargs):
            path = Path(command[command.index("--receipt")+1])
            self.assertFalse(path.exists())
            path.write_text(json.dumps({"passed": True, "code_revision": "b"*40, "repository_clean": True, "depth_mode": "COMPANY"}))
            return 0, ""
        with patch.object(host, "repository_identity", return_value={"clean": True, "revision": self.identity}), \
             patch.object(host, "quiet_run", side_effect=fake) as run:
            result = host.run_live_modes(self.root, self.identity)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(result["COMPANY"]["passed"])
        self.assertNotIn("COMPANY_PLUS", result)

    def test_both_modes_require_distinct_fresh_correctly_bound_receipts(self):
        paths = []
        def fake(command, **kwargs):
            path = Path(command[command.index("--receipt")+1]); paths.append(str(path))
            mode = command[command.index("--depth-mode")+1]
            path.write_text(json.dumps({"passed": True, "code_revision": self.identity, "repository_clean": True, "depth_mode": mode}))
            return 0, ""
        with patch.object(host, "repository_identity", return_value={"clean": True, "revision": self.identity}), \
             patch.object(host, "quiet_run", side_effect=fake):
            result = host.run_live_modes(self.root, self.identity)
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(row["passed"] for row in result.values()))

    def test_occupied_port_cannot_validate_an_unrelated_server(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            port = listener.getsockname()[1]
            with patch.object(host, "repository_identity", return_value={"clean": True, "revision": self.identity}), \
                 patch.object(host.subprocess, "Popen") as spawn, self.assertRaises(OSError):
                host.serve_local({"code_revision": self.identity}, self.root, port, smoke_only=True)
            spawn.assert_not_called()

    def test_invalid_expected_commit_does_not_prepare_anything(self):
        with patch.object(host, "prepare") as prepare, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            host.main(["--data-root", str(self.root), "--prepare", "--expected-commit", "unreviewed"])
        prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
