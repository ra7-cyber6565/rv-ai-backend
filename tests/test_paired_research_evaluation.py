import unittest
from utils.paired_evaluation import evaluate
from utils.research_runtime import digest


class PairedEvaluationAcceptance(unittest.TestCase):
    def fixture(self):
        manifest = {"task_ids": ["a", "b"], "split": "development"}
        base = [{"task_id": t, "trial": i, "execution_kind": "FIXTURE", "grader": "DETERMINISTIC",
                 "task_success": 0, "coverage": 1, "citation_support": None, "abstention_appropriate": None,
                 "http_budget": 8, "seconds_budget": 60, "latency_seconds": 2} for t in ("a", "b") for i in (0, 1)]
        return manifest, base, [dict(r, task_success=1) for r in base]

    def test_known_synthetic_difference_is_not_a_live_success_claim(self):
        m, a, b = self.fixture()
        result = evaluate(m, a, b, expected_manifest_hash=digest(m), draws=100)
        self.assertEqual(result["paired_trials"], 4)
        self.assertEqual(result["metrics"]["task_success"]["eligible_tasks"], 2)
        self.assertEqual(result["metrics"]["task_success"]["delta_candidate_minus_baseline"], 1)
        self.assertEqual(result["metrics"]["citation_support"]["eligible_tasks"], 0)
        self.assertEqual(result["execution_kinds"], ["FIXTURE"])
        self.assertTrue(result["decision"].startswith("INCONCLUSIVE"))

    def test_unequal_budgets_and_missing_tasks_are_rejected(self):
        m, a, b = self.fixture()
        with self.assertRaises(ValueError):
            evaluate(m, a, b[:-1], expected_manifest_hash=digest(m))
        b[0]["http_budget"] = 9
        with self.assertRaises(ValueError):
            evaluate(m, a, b, expected_manifest_hash=digest(m))

    def test_manifest_changes_and_tuned_holdouts_are_rejected(self):
        m, a, b = self.fixture()
        old = digest(m)
        m["split"] = "untouched_holdout"
        m["used_for_tuning"] = True
        with self.assertRaises(ValueError):
            evaluate(m, a, b, expected_manifest_hash=old)
        with self.assertRaises(ValueError):
            evaluate(m, a, b, expected_manifest_hash=digest(m))


if __name__ == "__main__":
    unittest.main()
