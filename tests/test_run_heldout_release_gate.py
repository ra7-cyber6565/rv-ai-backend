import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from tools.run_heldout_release_gate import main
from utils.research_runtime import digest


BASE_SHA = "a" * 40
CAND_SHA = "b" * 40


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


class HeldoutReleaseGateCliTests(unittest.TestCase):
    def payloads(self):
        manifest = {
            "task_ids": ["a", "b"],
            "split": "untouched_holdout",
            "used_for_tuning": False,
        }
        baseline, candidate = [], []
        for index, task_id in enumerate(manifest["task_ids"]):
            common = {
                "task_id": task_id,
                "trial": 0,
                "execution_kind": "LIVE",
                "grader": "HUMAN",
                "coverage": 0.9,
                "citation_support": None,
                "abstention_appropriate": None,
                "http_budget": 8,
                "seconds_budget": 60,
                "latency_seconds": 2.0,
            }
            baseline.append({
                **common,
                "task_success": 0.4,
                "revision": BASE_SHA,
                "output_sha256": h(f"base-output-{index}"),
                "grade_sha256": h(f"base-grade-{index}"),
                "private_note": "raw-row-must-not-appear",
            })
            candidate.append({
                **common,
                "task_success": 0.8,
                "revision": CAND_SHA,
                "output_sha256": h(f"cand-output-{index}"),
                "grade_sha256": h(f"cand-grade-{index}"),
                "private_note": "raw-row-must-not-appear",
            })
        policy = {
            "schema_version": 1,
            "primary_metric": "task_success",
            "min_tasks": 2,
            "primary_min_effect": 0.1,
            "primary_candidate_min": 0.6,
            "primary_max_tasks_worse_fraction": 0.5,
            "required_execution_kind": "LIVE",
            "allowed_graders": ["HUMAN"],
            "non_regression": {
                "coverage": {"max_drop": 0.02, "candidate_min": 0.8,
                             "max_tasks_worse_fraction": 0.5},
            },
        }
        campaign = {
            "schema_version": 1,
            "campaign_id": "cli-test",
            "baseline_revision": BASE_SHA,
            "candidate_revision": CAND_SHA,
            "grader_spec_sha256": h("grader"),
            "outputs_frozen_before_grading": True,
            "holdout_targets_hidden_during_generation": True,
            "grader_frozen_before_candidate_scoring": True,
        }
        return manifest, baseline, candidate, policy, campaign

    def write_inputs(self, root):
        names = ("manifest", "baseline", "candidate", "policy", "campaign")
        payloads = self.payloads()
        paths = {}
        for name, payload in zip(names, payloads):
            path = root / f"{name}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths[name] = path
        return paths, payloads

    def argv(self, paths, payloads, receipt, *, policy_hash=None):
        manifest, _, _, policy, _ = payloads
        return [
            "--manifest", str(paths["manifest"]),
            "--baseline", str(paths["baseline"]),
            "--candidate", str(paths["candidate"]),
            "--policy", str(paths["policy"]),
            "--campaign", str(paths["campaign"]),
            "--expected-manifest-sha256", digest(manifest),
            "--expected-policy-sha256", policy_hash or digest(policy),
            "--receipt-file", str(receipt),
            "--draws", "100",
        ]

    def test_pass_writes_only_sanitized_receipt_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths, payloads = self.write_inputs(root)
            receipt = root / "receipt.json"
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(self.argv(paths, payloads, receipt))
            self.assertEqual(code, 0)
            self.assertIn("HELDOUT_RELEASE_PASS", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            saved = receipt.read_text(encoding="utf-8")
            self.assertNotIn("raw-row-must-not-appear", saved)
            parsed = json.loads(saved)
            self.assertEqual(parsed["decision"], "PASS")
            expected_candidate_file = hashlib.sha256(paths["candidate"].read_bytes()).hexdigest()
            self.assertEqual(
                parsed["input_artifacts_sha256"]["candidate"], expected_candidate_file)
            self.assertRegex(parsed["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_bad_frozen_policy_hash_returns_invalid_without_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths, payloads = self.write_inputs(root)
            receipt = root / "receipt.json"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main(self.argv(paths, payloads, receipt, policy_hash="0" * 64))
            self.assertEqual(code, 4)
            self.assertIn("HELDOUT_RELEASE_INVALID", stderr.getvalue())
            self.assertFalse(receipt.exists())

    def test_malformed_pairing_returns_invalid_not_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths, payloads = self.write_inputs(root)
            candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))[:-1]
            paths["candidate"].write_text(json.dumps(candidate), encoding="utf-8")
            receipt = root / "receipt.json"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main(self.argv(paths, payloads, receipt))
            self.assertEqual(code, 4)
            self.assertIn("HELDOUT_RELEASE_INVALID", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
