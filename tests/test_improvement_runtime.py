import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.improvement_runtime import ImprovementStore, canonical, validate_suite, strict_json
from utils.research_runtime import RuntimeStore


def suite():
    return {"schema": 1, "provenance": "SYNTHETIC", "cases": [
        {"id": "negative", "group": "target", "input": -4, "expected": 4},
        {"id": "positive", "group": "regression", "input": 3, "expected": 3},
        {"id": "type_guard", "group": "safety", "input": "bad", "expected": {"error": "number required"}},
    ]}


def implementation(fixed):
    operation = "abs(x)" if fixed else "x"
    return {"runtime": "python", "entrypoint": "main.py", "files": {"main.py":
        "import json\nfrom pathlib import Path\n"
        "x=json.loads(Path('/inputs/case.json').read_text())\n"
        f"y={operation} if type(x) in (int,float) else {{'error':'number required'}}\n"
        "Path('answer.json').write_text(json.dumps(y))\n"}}


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ImprovementStore(RuntimeStore(Path(self.temp.name)/"state.sqlite3"))

    def test_observed_failure_has_private_idempotent_project_scoped_proposal(self):
        result = {"question": "SECRET_QUESTION", "answer": "SECRET_ANSWER", "task_contract": {"assessment": "PARTIAL"},
            "verification": {"research_company": {"workers": [{"status": "FAILED", "error": "SECRET_API_KEY",
                "report": {"hypotheses": [{"plan_completeness": "INCOMPLETE"}]}}]}}}
        proposals = self.store.observe("p", "run", result)
        self.assertEqual(len(proposals), 3)
        self.assertEqual(proposals, self.store.observe("p", "run", result))
        self.assertNotIn("SECRET", json.dumps(self.store.inspect("p")))
        self.assertEqual(self.store.inspect("other"), {"proposals": []})
        self.assertTrue(all(p["evaluation"] == "NOT_TESTED" and not p["automatic_apply_allowed"] for p in proposals))

    def test_success_does_not_manufacture_a_failure(self):
        self.assertEqual(self.store.observe("p", "ok", {"task_contract": {"assessment": "SATISFIED"}}), [])

    def test_suite_rejects_missing_regressions_and_nonfinite_or_duplicate_json(self):
        raw = suite(); raw["cases"][1]["group"] = "target"
        with self.assertRaises(ValueError):
            validate_suite(canonical(raw))
        for value in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(value)

    def test_disabled_backend_does_not_consume_holdout_or_call_program(self):
        proposal = self.store.observe("p", "run", failed=True)[0]
        path = Path(self.temp.name)/"suite.json"; path.write_bytes(canonical(suite()))
        with patch.dict(os.environ, {"INFINITY_BUILD_EXECUTOR": "", "INFINITY_IMPROVEMENT_SUITE": str(path),
             "INFINITY_IMPROVEMENT_SUITE_SHA256": hashlib.sha256(path.read_bytes()).hexdigest()}):
            receipt = self.store.evaluate("p", proposal["id"], implementation(False), implementation(True))
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertFalse(receipt["holdout_consumed"])
        with self.store.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM improvement_trials").fetchone()[0], 0)

    def test_operator_commitment_and_project_scope_are_required(self):
        proposal = self.store.observe("p", "run", failed=True)[0]
        with self.assertRaises(ValueError):
            self.store.evaluate("other", proposal["id"], implementation(False), implementation(True))
        path = Path(self.temp.name)/"suite.json"; path.write_bytes(canonical(suite()))
        with patch.dict(os.environ, {"INFINITY_IMPROVEMENT_SUITE": str(path), "INFINITY_IMPROVEMENT_SUITE_SHA256": "wrong"}), self.assertRaises(ValueError):
            self.store.evaluate("p", proposal["id"], implementation(False), implementation(True))


@unittest.skipUnless(os.environ.get("INFINITY_REAL_EXECUTOR_TEST") == "1", "actual isolated trial runs in mandatory CI lane")
class RealImprovementTrialTests(unittest.TestCase):
    def test_actual_regression_is_rejected_even_when_target_is_fixed(self):
        with tempfile.TemporaryDirectory() as root:
            store = ImprovementStore(RuntimeStore(Path(root)/"state.sqlite3"))
            proposal = store.observe("p", "gap", failed=True)[0]
            path = Path(root)/"suite.json"; path.write_bytes(canonical(suite()))
            bad = implementation(True)
            bad["files"]["main.py"] = bad["files"]["main.py"].replace("abs(x)", "(abs(x) if x < 0 else 999)")
            with patch.dict(os.environ, {"INFINITY_IMPROVEMENT_SUITE": str(path),
                 "INFINITY_IMPROVEMENT_SUITE_SHA256": hashlib.sha256(path.read_bytes()).hexdigest()}):
                result = store.evaluate("p", proposal["id"], implementation(False), bad)
            self.assertEqual(result["state"], "FAIL", result)
            self.assertTrue(result["validation"]["original_failure_fixed"])
            self.assertFalse(result["validation"]["regression_suite_passed"])
            self.assertFalse(result["validation"]["eligible_for_external_approval"])

    def test_observed_failure_to_actual_protected_trial_and_one_use_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            store = ImprovementStore(RuntimeStore(Path(root)/"state.sqlite3"))
            proposal = store.observe("p", "actual-fixture-gap", {"task_contract": {"assessment": "PARTIAL"}})[0]
            path = Path(root)/"suite.json"; path.write_bytes(canonical(suite()))
            env = {"INFINITY_IMPROVEMENT_SUITE": str(path), "INFINITY_IMPROVEMENT_SUITE_SHA256": hashlib.sha256(path.read_bytes()).hexdigest()}
            with patch.dict(os.environ, env):
                receipt = store.evaluate("p", proposal["id"], implementation(False), implementation(True))
                self.assertEqual(receipt["state"], "CONDITIONAL_PASS", receipt)
                self.assertTrue(receipt["validation"]["original_failure_fixed"])
                self.assertTrue(receipt["validation"]["regression_suite_passed"])
                self.assertEqual(len(receipt["executions"]), 12)
                self.assertTrue(all(r["state"] == "EXECUTED" for r in receipt["executions"]))
                self.assertFalse(receipt["automatic_apply_allowed"])
                self.assertEqual(receipt["data_provenance"], "SYNTHETIC")
                self.assertEqual(store.inspect("p")["proposals"][0]["state"], "EVALUATED")
                with self.assertRaises(ValueError):
                    store.evaluate("p", proposal["id"], implementation(False), implementation(True))
            renamed = suite()
            for row in renamed["cases"]:
                row["id"] += "_renamed"
            path.write_bytes(canonical(renamed))
            env["INFINITY_IMPROVEMENT_SUITE_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.dict(os.environ, env), self.assertRaises(ValueError):
                store.evaluate("p", proposal["id"], implementation(False), implementation(True))


if __name__ == "__main__":
    unittest.main()
