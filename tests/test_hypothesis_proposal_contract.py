import unittest

from research_engine.hypothesis_contract import PLAN_FIELDS, complete_proposal
from research_engine.research_company import normalize_report, chief_handoff
import json


class HypothesisProposalTests(unittest.TestCase):
    def row(self):
        return {"mechanism": "A changes B through C", "assumptions": ["C is measured without intervention"],
            "applicability_boundaries": "Specified apparatus only", "supporting_source_ids": ["S1", "invented"],
            "status": "PASS", "actual_results": {"cured": True},
            "test_plan": {**{key: "specified "+key for key in PLAN_FIELDS},
                          "variables": [{"symbol": "t", "definition": "Elapsed time", "unit": "s", "role": "independent"}]}}

    def test_complete_schema_is_not_experimental_or_semantic_validation(self):
        result = complete_proposal(self.row(), ["S1"])
        self.assertEqual(result["plan_completeness"], "STRUCTURALLY_COMPLETE")
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertIsNone(result["actual_results"])
        self.assertEqual(result["semantic_plan_validation"], "NOT_ASSESSED")
        self.assertEqual(result["novelty"]["assessment"], "NOT_ESTABLISHED")
        self.assertEqual(result["supporting_source_ids"], ["S1"])
        self.assertEqual(result["unknown_source_ids"], ["invented"])

    def test_unknown_power_threshold_and_missing_units_stay_incomplete(self):
        row = self.row()
        row["test_plan"].update(power_sample_assumptions="TO BE ESTIMATED", decision_threshold="UNKNOWN",
                               variables=[{"symbol": "x", "definition": "value", "role": "dependent"}],
                               variables_applicability={"state": "NOT_APPLICABLE", "reason": "UNKNOWN"})
        result = complete_proposal(row, [])
        self.assertEqual(result["plan_completeness"], "INCOMPLETE")
        self.assertIn("variables_with_units_and_roles", result["missing_plan_fields"])
        self.assertIn("decision_threshold", result["missing_plan_fields"])
        self.assertNotIn("variables_applicability", result["test_plan"])

    def test_inapplicable_requires_reason_and_truncation_is_visible(self):
        row = self.row()
        row["test_plan"]["power_sample_assumptions"] = {"state": "NOT_APPLICABLE", "reason": "An exhaustive finite proof has no statistical sample"}
        self.assertEqual(complete_proposal(row, [])["plan_completeness"], "STRUCTURALLY_COMPLETE")
        row["test_plan"]["setup"] = "x" * 1201
        result = complete_proposal(row, [])
        self.assertEqual(result["plan_completeness"], "INCOMPLETE")
        self.assertIn("setup", result["truncated_plan_fields"])

    def test_worker_report_preserves_plan_and_mechanism(self):
        row = {**self.row(), **{k: "proposed "+k for k in ("hypothesis", "prediction", "baseline", "test", "falsification")}}
        raw = {"summary": "Draft", "claims": [], "hypotheses": [row], "limitations": [],
               "assumptions": [], "contradictions": [], "remaining_questions": []}
        report = normalize_report(json.dumps(raw), ["S1"])
        self.assertEqual(report["hypotheses"][0]["test_plan"]["replication_method"], "specified replication_method")
        self.assertEqual(report["hypotheses"][0]["mechanism"], row["mechanism"])

    def test_binary_download_does_not_crowd_out_chief_reasoning_or_modify_download(self):
        artifact = {"encoding": "base64", "content": "A"*24000, "sha256": "ARTIFACT_HASH"}
        company = {"workers": [{"role": "validation", "status": "DRAFT_READY", "report": {
            "summary": "TEST_RECEIPT", "tool_results": [{"state": "EXECUTED", "artifact": artifact}]}}]}
        prompt = chief_handoff(company)
        self.assertIn("ARTIFACT_HASH", prompt)
        self.assertIn("TEST_RECEIPT", prompt)
        self.assertNotIn("A"*100, prompt)
        self.assertEqual(len(artifact["content"]), 24000)
        self.assertEqual(company["handoff_truncated_roles"], [])


if __name__ == "__main__":
    unittest.main()
