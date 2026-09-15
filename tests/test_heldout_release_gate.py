import hashlib
import unittest

from utils.heldout_release_gate import HeldoutGateError, assess_release
from utils.research_runtime import digest


BASE_SHA = "1" * 40
CAND_SHA = "2" * 40


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


class HeldoutReleaseGateTests(unittest.TestCase):
    def fixture(self, *, tasks=8, execution_kind="LIVE", grader="HUMAN"):
        manifest = {
            "schema_version": 1,
            "benchmark_id": "quality-v1",
            "task_ids": [f"task-{i}" for i in range(tasks)],
            "split": "untouched_holdout",
            "used_for_tuning": False,
        }
        baseline, candidate = [], []
        for i, task_id in enumerate(manifest["task_ids"]):
            common = {
                "task_id": task_id,
                "trial": 0,
                "execution_kind": execution_kind,
                "grader": grader,
                "coverage": 0.90,
                "citation_support": 0.90,
                "abstention_appropriate": 0.90,
                "http_budget": 8,
                "seconds_budget": 60,
                "latency_seconds": 2.0,
            }
            baseline.append({
                **common,
                "task_success": 0.50,
                "revision": BASE_SHA,
                "output_sha256": h(f"baseline-output-{i}"),
                "grade_sha256": h(f"baseline-grade-{i}"),
                "private_note": "must-not-leak",
            })
            candidate.append({
                **common,
                "task_success": 0.70,
                "revision": CAND_SHA,
                "output_sha256": h(f"candidate-output-{i}"),
                "grade_sha256": h(f"candidate-grade-{i}"),
                "private_note": "must-not-leak",
            })
        policy = {
            "schema_version": 1,
            "primary_metric": "task_success",
            "min_tasks": min(6, tasks),
            "primary_min_effect": 0.10,
            "primary_candidate_min": 0.60,
            "primary_max_tasks_worse_fraction": 0.25,
            "required_execution_kind": "LIVE",
            "allowed_graders": ["HUMAN"],
            "non_regression": {
                "coverage": {"max_drop": 0.02, "candidate_min": 0.80,
                             "max_tasks_worse_fraction": 0.25},
                "citation_support": {"max_drop": 0.02, "candidate_min": 0.80,
                                     "max_tasks_worse_fraction": 0.25},
                "abstention_appropriate": {"max_drop": 0.02,
                                           "max_tasks_worse_fraction": 0.25},
                "latency_seconds": {"max_increase": 1.0,
                                    "max_tasks_worse_fraction": 0.50},
            },
        }
        campaign = {
            "schema_version": 1,
            "campaign_id": "campaign-001",
            "baseline_revision": BASE_SHA,
            "candidate_revision": CAND_SHA,
            "grader_spec_sha256": h("grader-spec-v1"),
            "outputs_frozen_before_grading": True,
            "holdout_targets_hidden_during_generation": True,
            "grader_frozen_before_candidate_scoring": True,
        }
        return manifest, baseline, candidate, policy, campaign

    def assess(self, manifest, baseline, candidate, policy, campaign, *, draws=200):
        return assess_release(
            manifest, baseline, candidate, policy, campaign,
            expected_manifest_hash=digest(manifest),
            expected_policy_hash=digest(policy),
            draws=draws,
        )

    def test_clear_live_human_improvement_passes_without_leaking_rows(self):
        m, a, b, p, c = self.fixture()
        receipt = self.assess(m, a, b, p, c)
        self.assertEqual(receipt["decision"], "PASS")
        self.assertTrue(receipt["release_allowed"])
        self.assertEqual(receipt["tasks"], 8)
        self.assertGreater(receipt["primary"]["bootstrap_95_interval"][0], 0.10)
        self.assertNotIn("must-not-leak", str(receipt))
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")

    def test_tuned_or_gold_bearing_holdout_is_rejected(self):
        m, a, b, p, c = self.fixture()
        m["used_for_tuning"] = True
        with self.assertRaisesRegex(HeldoutGateError, "untouched"):
            self.assess(m, a, b, p, c)
        m["used_for_tuning"] = False
        m["gold_answer"] = "hidden target"
        with self.assertRaisesRegex(HeldoutGateError, "grading-target"):
            self.assess(m, a, b, p, c)

    def test_frozen_policy_hash_cannot_be_changed_after_campaign(self):
        m, a, b, p, c = self.fixture()
        frozen = digest(p)
        p["primary_min_effect"] = 0.01
        with self.assertRaisesRegex(HeldoutGateError, "policy changed"):
            assess_release(m, a, b, p, c,
                           expected_manifest_hash=digest(m),
                           expected_policy_hash=frozen, draws=200)

    def test_rows_must_bind_full_revision_and_output_grade_hashes(self):
        m, a, b, p, c = self.fixture()
        b[0]["revision"] = BASE_SHA
        with self.assertRaisesRegex(HeldoutGateError, "declared revision"):
            self.assess(m, a, b, p, c)
        b[0]["revision"] = CAND_SHA
        b[0]["output_sha256"] = "not-a-hash"
        with self.assertRaisesRegex(HeldoutGateError, "SHA-256"):
            self.assess(m, a, b, p, c)

    def test_fixture_campaign_cannot_authorize_live_release(self):
        m, a, b, p, c = self.fixture(execution_kind="FIXTURE")
        receipt = self.assess(m, a, b, p, c)
        self.assertEqual(receipt["decision"], "INCONCLUSIVE")
        self.assertFalse(receipt["release_allowed"])
        self.assertTrue(any("execution provenance" in x for x in receipt["inconclusive_reasons"]))

    def test_uncalibrated_model_grader_cannot_authorize_release(self):
        m, a, b, p, c = self.fixture(grader="MODEL_ASSISTED_UNCALIBRATED")
        p["allowed_graders"] = ["MODEL_ASSISTED_UNCALIBRATED"]
        receipt = self.assess(m, a, b, p, c)
        self.assertEqual(receipt["decision"], "INCONCLUSIVE")
        self.assertTrue(any("uncalibrated" in x for x in receipt["inconclusive_reasons"]))

    def test_primary_interval_crossing_practical_threshold_is_inconclusive(self):
        m, a, b, p, c = self.fixture(tasks=2)
        p["min_tasks"] = 2
        p["primary_candidate_min"] = 0.30
        p["primary_max_tasks_worse_fraction"] = 1.0
        b[0]["task_success"] = 0.40  # delta -0.10
        b[1]["task_success"] = 0.80  # delta +0.30
        receipt = self.assess(m, a, b, p, c, draws=1000)
        self.assertEqual(receipt["decision"], "INCONCLUSIVE")
        self.assertTrue(any("practical-effect" in x for x in receipt["inconclusive_reasons"]))

    def test_primary_clearly_below_effect_threshold_fails(self):
        m, a, b, p, c = self.fixture()
        p["primary_candidate_min"] = 0.50
        p["primary_max_tasks_worse_fraction"] = 1.0
        for row in b:
            row["task_success"] = 0.55  # constant +0.05; policy requires +0.10
        receipt = self.assess(m, a, b, p, c)
        self.assertEqual(receipt["decision"], "FAIL")
        self.assertFalse(receipt["release_allowed"])
        self.assertTrue(any("practical-effect" in x for x in receipt["failures"]))

    def test_clear_non_regression_failure_blocks_release(self):
        m, a, b, p, c = self.fixture()
        for row in b:
            row["coverage"] = 0.50
        receipt = self.assess(m, a, b, p, c)
        self.assertEqual(receipt["decision"], "FAIL")
        self.assertTrue(any("coverage" in x for x in receipt["failures"]))

    def test_missing_required_metric_is_inconclusive_not_a_zero(self):
        m, a, b, p, c = self.fixture()
        for row in b:
            row["citation_support"] = None
        receipt = self.assess(m, a, b, p, c)
        self.assertEqual(receipt["decision"], "INCONCLUSIVE")
        self.assertTrue(any("citation_support" in x for x in receipt["inconclusive_reasons"]))

    def test_false_freeze_attestation_and_same_revision_are_rejected(self):
        m, a, b, p, c = self.fixture()
        c["outputs_frozen_before_grading"] = False
        with self.assertRaisesRegex(HeldoutGateError, "attestation"):
            self.assess(m, a, b, p, c)
        c["outputs_frozen_before_grading"] = True
        c["candidate_revision"] = BASE_SHA
        with self.assertRaisesRegex(HeldoutGateError, "must differ"):
            self.assess(m, a, b, p, c)


if __name__ == "__main__":
    unittest.main()
