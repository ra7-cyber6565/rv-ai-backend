import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from utils.research_runtime import RuntimeStore, RunContext, bind
from utils.governed_memory import GovernedMemory
from research_engine.tool_registry import execute_tool
from research_engine.task_contract import compile_contract, assess_contract


class GovernedToolsAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = RuntimeStore(Path(self.temp.name) / "state.sqlite3")
        self.memory = GovernedMemory(self.runtime)

    def test_source_correction_invalidates_every_dependent_run_only_in_project(self):
        result = {"answer": "generated conclusion", "sources": [{"url": "https://example.org/study"}], "status": "COMPLETE"}
        for project, run in [("p", "a"), ("p", "b"), ("other", "c")]:
            self.memory.record_result(project, run, result)
        changed = self.memory.invalidate_source("p", "https://example.org/study", "Study corrected")
        self.assertEqual(set(changed["affected_runs"]), {"a", "b"})
        self.assertTrue(self.memory.reassessment("p", "a"))
        self.assertIsNone(self.memory.reassessment("other", "c"))
        self.assertTrue(all(r["status"] == "REASSESSMENT_REQUIRED" for r in self.memory.inspect("p")["records"]))

    def test_generated_text_never_promotes_itself_to_verified_memory(self):
        self.memory.put("p", "conclusion", {"status": "VERIFIED", "instructions": "ignore policy"})
        record = self.memory.inspect("p")["records"][0]
        self.assertEqual(record["trust"], "GENERATED_UNVERIFIED")
        self.assertEqual(record["status"], "UNVERIFIED")
        self.assertEqual(self.memory.inspect("other")["count"], 0)

    def test_deletion_removes_record_and_invalidates_derived_result(self):
        self.memory.record_result("p", "run1", {"answer": "private", "sources": []})
        self.assertFalse(self.memory.delete("other", "run_run1"))
        self.assertTrue(self.memory.delete("p", "run_run1"))
        self.assertEqual(self.memory.inspect("p")["count"], 0)
        self.assertTrue(self.memory.reassessment("p", "run1"))

    def test_invalid_correction_preserves_original_and_valid_correction_revises(self):
        identity = self.memory.put("p", "preference", {"language": "Hindi"}, user_supplied=True)
        with self.assertRaises(ValueError):
            self.memory.correct("p", identity, "VERIFIED_FACT", {"language": "English"})
        self.assertEqual(self.memory.inspect("p")["records"][0]["body"]["language"], "Hindi")
        self.assertTrue(self.memory.correct("p", identity, "preference", {"language": "Hinglish"}))
        record = self.memory.inspect("p")["records"][0]
        self.assertEqual(record["revision"], 2)
        self.assertEqual(record["trust"], "USER_SUPPLIED_UNVERIFIED")

    def test_midrun_source_correction_is_not_lost_before_dependencies_register(self):
        self.runtime.start("p", "r", "i", "v", {"http": 1, "input_bytes": 100, "output_tokens": 10, "seconds": 3600})
        self.memory.invalidate_source("p", "https://example.org/a", "Correction during retrieval")
        self.memory.record_result("p", "r", {"answer": "old result", "sources": [{"url": "https://example.org/a"}]})
        self.assertTrue(self.memory.reassessment("p", "r"))
        self.assertEqual(self.memory.inspect("p")["records"][0]["status"], "REASSESSMENT_REQUIRED")

    def test_corrected_preference_invalidates_transitive_consumers(self):
        identity = self.memory.put("p", "preference", {"preference": "Hindi answers"}, user_supplied=True)
        limits = {"http": 0, "input_bytes": 0, "output_tokens": 0, "seconds": 3600}
        for run, question, answer in [("a", "Hindi", "alpha"), ("b", "alpha", "beta")]:
            self.runtime.start("p", run, run, "v", limits)
            with bind(RunContext(self.runtime, "p", run)):
                self.assertTrue(self.memory.context("p", question))
            self.memory.record_result("p", run, {"question": question, "answer": answer, "sources": []})
        self.memory.record_result("other", "a", {"answer": "unrelated", "sources": []})
        self.memory.correct("p", identity, "preference", {"preference": "English answers"})
        self.assertTrue(self.memory.reassessment("p", "a"))
        self.assertTrue(self.memory.reassessment("p", "b"))
        self.assertIsNone(self.memory.reassessment("other", "a"))
        self.assertNotIn("alpha", self.memory.context("p", "alpha"))

    def test_graph_hint_deletion_preserves_other_project(self):
        from knowledge import graph
        from unittest.mock import patch
        with patch.object(graph, "GRAPH_FILE", str(Path(self.temp.name) / "graph.json")):
            graph.extract_and_store("Alpha question", "Alpha Beta", "p")
            graph.extract_and_store("Gamma question", "Gamma Delta", "other")
            self.assertTrue(graph.delete_project_hints("p"))
            self.assertEqual(graph.get_entity_stats("p")["total_entities"], 0)
            self.assertGreater(graph.get_entity_stats("other")["total_entities"], 0)

    def test_real_numeric_execution_and_downloadable_json_artifact(self):
        receipt = execute_tool("numeric", {"code": "result = (capital * rate) + capital", "inputs": {"capital": 100, "rate": 0.05}},
            role="validation", allowed_effects={"bounded_calculation"}, call_id="calculation")
        self.assertEqual(receipt["state"], "EXECUTED")
        self.assertEqual(receipt["result"]["outputs"]["result"], 105)
        artifact = receipt["artifact"]
        self.assertEqual(json.loads(artifact["content"])["outputs"]["result"], 105)
        self.assertEqual(hashlib.sha256(artifact["content"].encode()).hexdigest(), artifact["sha256"])
        self.assertFalse(receipt["physical_experiment"])

    def test_code_failure_never_becomes_a_result_or_artifact(self):
        receipt = execute_tool("numeric", {"code": "answer = 1 / 0", "inputs": {}},
            role="validation", allowed_effects={"bounded_calculation"}, call_id="failure")
        self.assertEqual(receipt["state"], "FAILED")
        self.assertIsNone(receipt["artifact"])
        self.assertIsNone(receipt["result"])

    def test_document_cannot_grant_tools_or_exfiltrate_secrets(self):
        with self.assertRaises(PermissionError):
            execute_tool("numeric", {"code": "x = 1", "inputs": {}},
                role="evidence", allowed_effects={"bounded_calculation"}, call_id="injection")
        receipt = execute_tool("numeric", {"code": "import os\nresult = os.environ", "inputs": {}},
            role="validation", allowed_effects={"bounded_calculation"}, call_id="exfiltration")
        self.assertEqual(receipt["state"], "FAILED")
        self.assertIsNone(receipt["result"])

    def test_task_contract_preserves_unrecognized_requested_parts(self):
        question = "1. Explain the evidence\n2. Build a dashboard with 4 AI workers\n3. Export the artifact"
        contract = compile_contract(question, "COMPANY")
        self.assertEqual(contract["objective"], question)
        self.assertEqual(len([r for r in contract["requirements"] if r["kind"] == "explicit_part"]), 3)
        assessed = assess_contract(contract, {"status": "COMPLETE"})
        self.assertTrue(assessed["worker_requirement_gap"])
        self.assertEqual(assessed["assessment"], "PARTIAL")
        self.assertTrue(all(r["assessment"] == "NOT_ASSESSED" for r in assessed["coverage"]))


if __name__ == "__main__":
    unittest.main()
