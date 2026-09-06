"""Observed-failure proposals and one-use, host-graded isolated patch trials.

No generated code, result flag or proposal can change the grader, production
source, permissions, budgets or release gates. The operator owns the suite.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import time
import zipfile

from .research_runtime import RuntimeStore, code_version, digest
from .isolated_execution import DockerExecutor, validate_request

_ACTIONS = {
    "worker_failure": "Reproduce the failed worker with a development fixture; propose a bounded adapter fix.",
    "report_contract": "Repair the parser or draft prompt against development examples without relaxing required fields.",
    "incomplete_plan": "Complete missing plan fields using supplied data; retain unknown quantities and proposed-test labels.",
    "blocked_tool": "Check executor readiness and supplied inputs; do not bypass tool permissions or resource limits.",
    "missing_deliverable": "Repair request decomposition or execution for the uncovered output; keep the coverage gate.",
    "research_failure": "Reproduce the failed research stage in an isolated development case before proposing a patch.",
}
_GROUPS = {"target", "regression", "safety"}


class ImprovementStore:
    def __init__(self, store=None):
        self.store = store or RuntimeStore()
        with self.store.db() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS improvement_proposals (
                project TEXT, id TEXT, run TEXT, created REAL, payload TEXT,
                PRIMARY KEY(project,id));
              CREATE TABLE IF NOT EXISTS improvement_trials (
                suite_hash TEXT PRIMARY KEY, project TEXT, proposal TEXT,
                pair_hash TEXT, state TEXT, receipt TEXT);
              CREATE TABLE IF NOT EXISTS improvement_case_uses (
                case_hash TEXT PRIMARY KEY, suite_hash TEXT);
            """)

    def observe(self, project, run, result=None, *, failed=False):
        from research_engine.autonomous_debugging import StageObservation, diagnose_stage_failures
        result = result if isinstance(result, dict) else {}
        counts = {}
        def count(key):
            counts[key] = counts.get(key, 0) + 1
        company = (result.get("verification") or {}).get("research_company") or {}
        for worker in company.get("workers", [])[:6]:
            if worker.get("status") not in {"DRAFT_READY", "COMPLETED"}:
                count("worker_failure")
            report = worker.get("report") or {}
            if report.get("contract_issues"):
                count("report_contract")
            if any(h.get("plan_completeness") == "INCOMPLETE" for h in report.get("hypotheses", [])):
                count("incomplete_plan")
            if any(t.get("state") != "EXECUTED" for t in report.get("tool_results", [])):
                count("blocked_tool")
        if (result.get("task_contract") or {}).get("assessment") == "PARTIAL":
            count("missing_deliverable")
        if failed:
            count("research_failure")
        if not counts:
            return []
        diagnosis = diagnose_stage_failures([StageObservation(key, "FAIL", error_class=key) for key in counts])
        version = code_version()
        proposals = []
        with self.store.transaction() as db:
            for category, number in sorted(counts.items()):
                identity = digest([project, run, category])[:32]
                payload = {"id": identity, "category": category, "state": "PROPOSED", "observations": number,
                    "code_hash": version, "diagnosis_hash": diagnosis.diagnosis_hash,
                    "root_cause_proven": False, "next_action": _ACTIONS[category],
                    "evidence_status": "OBSERVED_SOFTWARE_FAILURE_OR_GAP", "evaluation": "NOT_TESTED",
                    "automatic_apply_allowed": False, "automatic_merge_allowed": False,
                    "automatic_deploy_allowed": False}
                db.execute("INSERT OR IGNORE INTO improvement_proposals VALUES(?,?,?,?,?)",
                           (project, identity, run, time.time(), json.dumps(payload)))
                proposals.append(json.loads(db.execute("SELECT payload FROM improvement_proposals WHERE project=? AND id=?", (project, identity)).fetchone()[0]))
            db.execute("DELETE FROM improvement_proposals WHERE project=? AND id NOT IN (SELECT id FROM improvement_proposals WHERE project=? ORDER BY created DESC LIMIT 100)", (project, project))
        return proposals

    def inspect(self, project):
        with self.store.db() as db:
            return {"proposals": [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM improvement_proposals WHERE project=? ORDER BY created DESC LIMIT 100", (project,))]}

    def evaluate(self, project, proposal_id, baseline, candidate):
        """Operator entrypoint. Case expectations never enter the container."""
        from research_engine.autonomous_debugging import PatchCandidate, validate_patch_candidates
        from research_engine.holdout_vault import HoldoutVault
        if not any(p["id"] == proposal_id for p in self.inspect(project)["proposals"]):
            raise ValueError("unknown project proposal")
        bundles = {}
        for label, bundle in (("baseline", baseline), ("candidate", candidate)):
            if not isinstance(bundle, dict) or set(bundle) != {"runtime", "files", "entrypoint"}:
                raise ValueError("implementation requires runtime, files and entrypoint")
            if bundle["runtime"] != "python":
                raise ValueError("protected trials currently support Python only")
            files, entrypoint = validate_request(**bundle)
            if "case.json" in files or any(p.startswith("case.json/") for p in files):
                raise ValueError("case.json is evaluator-owned")
            bundles[label] = {"runtime": "python", "files": files, "entrypoint": entrypoint}
        # Freeze implementations before opening the operator-selected final data.
        pair_hash = digest(bundles)
        expected_hash = os.environ.get("INFINITY_IMPROVEMENT_SUITE_SHA256", "")
        suite_path = os.environ.get("INFINITY_IMPROVEMENT_SUITE", "")
        if not suite_path or not Path(suite_path).is_absolute():
            raise ValueError("operator must configure an absolute protected suite path")
        with open(suite_path, "rb") as handle:
            raw = handle.read(128001)
        suite_hash = hashlib.sha256(raw).hexdigest()
        if len(raw) > 128000 or suite_hash != expected_hash:
            raise ValueError("protected suite size or SHA256 commitment mismatch")
        suite = validate_suite(raw)
        case_hashes = [digest([case["input"], case["expected"]]) for case in suite["cases"]]
        if len(set(case_hashes)) != len(case_hashes):
            raise ValueError("duplicate protected cases")
        executor = DockerExecutor(self.store)
        readiness = executor.readiness("python")
        if not readiness["ready"]:
            return {"state": "BLOCKED", "reason": readiness["reason"], "holdout_consumed": False}
        image = readiness["image"]
        # Atomic global one-use reservation survives crashes, even before receipt.
        # Retained commitments are intentional: pruning would permit test reuse.
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM improvement_trials WHERE suite_hash=?", (suite_hash,)).fetchone():
                raise ValueError("protected suite already consumed; use new independently held-out cases")
            if any(db.execute("SELECT 1 FROM improvement_case_uses WHERE case_hash=?", (h,)).fetchone() for h in case_hashes):
                raise ValueError("protected cases already consumed; renaming or reordering does not create a new holdout")
            db.execute("INSERT INTO improvement_trials VALUES(?,?,?,?,?,NULL)",
                       (suite_hash, project, proposal_id, pair_hash, "CONSUMED"))
            db.executemany("INSERT INTO improvement_case_uses VALUES(?,?)", [(h, suite_hash) for h in case_hashes])
        vault = HoldoutVault(str(Path(self.store.path).parent / "improvement-holdouts"))
        receipt = {"state": "INCONCLUSIVE", "holdout_consumed": True, "pair_hash": pair_hash,
            "suite_hash": suite_hash, "execution": "SOFTWARE_EXECUTION", "data_provenance": suite["provenance"],
            "scientific_or_live_model_quality": "NOT_ASSESSED", "automatic_apply_allowed": False,
            "automatic_merge_allowed": False, "automatic_deploy_allowed": False}
        try:
            sealed = vault.create(suite_hash, raw, dataset_label="operator protected software cases")
            protocol = {"grader": "host_exact_json_v1", "repeats": 2, "groups": sorted(_GROUPS), "image": image,
                        "resource_policy_hash": digest(Path(__file__).with_name("isolated_execution.py").read_text())}
            frozen = vault.freeze_candidate(suite_hash, candidate_id=proposal_id,
                implementation_hash=pair_hash, protocol_hash=digest(protocol), evaluator_instructions=protocol)
            def grade(dataset, packet):
                cases = validate_suite(dataset)["cases"]
                outcomes = {label: [] for label in bundles}
                executions, end = [], time.monotonic() + 900
                for index, case in enumerate(cases):
                    # Alternating order avoids always giving the candidate a warmer host.
                    labels = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
                    for repeat in range(2):
                        for label in labels:
                            if time.monotonic() >= end:
                                raise TimeoutError("protected evaluation deadline")
                            bundle = bundles[label]
                            payload = {**bundle["files"], "case.json": canonical(case["input"]).decode()}
                            run = executor.run("python", payload, bundle["entrypoint"])
                            good = run.get("state") == "EXECUTED" and run.get("cleanup_confirmed") is True and (run.get("executor") or {}).get("image") == image
                            value = None
                            if good:
                                try:
                                    archive = base64.b64decode(run["artifact"]["content"], validate=True)
                                    with zipfile.ZipFile(io.BytesIO(archive)) as z:
                                        value = strict_json(z.read("output/answer.json"))
                                except (ValueError, KeyError, OSError, zipfile.BadZipFile):
                                    good = False
                            passed = good and canonical(value) == canonical(case["expected"])
                            outcomes[label].append({"case": index, "repeat": repeat, "group": case["group"],
                                "passed": passed, "executed": good, "output_hash": digest(value) if good else None})
                            executions.append({"label": label, "case": index, "repeat": repeat, "state": run["state"],
                                "cleanup_confirmed": run.get("cleanup_confirmed", False), "input_sha256": run.get("input_sha256"),
                                "artifact_sha256": (run.get("artifact") or {}).get("sha256"),
                                "seconds": max(0, run.get("finished_at", 0)-run.get("started_at", 0))})
                def group_pass(label, group):
                    return all(r["passed"] for r in outcomes[label] if r["group"] == group)
                repeatable = all(all(len({r["output_hash"] for r in rows if r["case"] == i and r["executed"]}) == 1 and
                                     all(r["executed"] for r in rows if r["case"] == i)
                                     for i in range(len(cases))) for rows in outcomes.values())
                metrics = {label+"_pass_rate": sum(r["passed"] for r in rows)/len(rows) for label, rows in outcomes.items()}
                validation = validate_patch_candidates([PatchCandidate(proposal_id, "Isolated implementation proposal",
                    digest(bundles["candidate"]), ("isolated_implementation",))], lambda _: {
                    "original_failure_fixed": not group_pass("baseline", "target") and group_pass("candidate", "target"),
                    "regression_suite_passed": group_pass("candidate", "regression") and all(not a["passed"] or b["passed"] for a,b in zip(outcomes["baseline"], outcomes["candidate"])),
                    "safety_suite_passed": group_pass("candidate", "safety") and all(e["cleanup_confirmed"] for e in executions),
                    "reproducibility_check_passed": repeatable, "metrics": metrics})[0]
                # Exact software-case results only; a functional fix is not a model quality claim.
                return {"validation": asdict(validation), "case_count": len(cases), "repeats": 2,
                    "executions": executions, "outcomes": outcomes, "protocol": protocol,
                    "scope": "operator supplied cases only; external release gates remain mandatory"}
            evaluated = vault.evaluate(suite_hash, evaluator_token=sealed.evaluator_token, evaluator=grade)
            receipt.update(evaluated.result, result_hash=evaluated.result_hash, freeze_hash=frozen["freeze_hash"])
            receipt["state"] = "CONDITIONAL_PASS" if receipt["validation"]["eligible_for_external_approval"] else "FAIL"
        except Exception as exc:
            # No raw exception text: it can include a private path or case label.
            receipt.update(state="INCONCLUSIVE", failure_class=type(exc).__name__)
        with self.store.transaction() as db:
            db.execute("UPDATE improvement_trials SET state=?,receipt=? WHERE suite_hash=?", (receipt["state"], json.dumps(receipt), suite_hash))
            row = db.execute("SELECT payload FROM improvement_proposals WHERE project=? AND id=?", (project, proposal_id)).fetchone()
            if row:
                proposal = json.loads(row[0])
                proposal.update(state="EVALUATED", evaluation=receipt)
                db.execute("UPDATE improvement_proposals SET payload=? WHERE project=? AND id=?", (json.dumps(proposal), project, proposal_id))
        return receipt


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def strict_json(raw):
    def reject(value):
        raise ValueError("nonfinite JSON")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj
    return json.loads(raw, parse_constant=reject, object_pairs_hook=unique)


def validate_suite(raw):
    suite = strict_json(raw)
    if not isinstance(suite, dict) or suite.get("schema") != 1 or suite.get("provenance") not in {"SYNTHETIC", "OPERATOR_HELD_OUT"}:
        raise ValueError("suite requires schema 1 and explicit provenance")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not 3 <= len(cases) <= 6:
        raise ValueError("suite requires 3..6 cases")
    ids, groups = set(), set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "group", "input", "expected"}:
            raise ValueError("invalid case schema")
        if not isinstance(case["id"], str) or not 1 <= len(case["id"]) <= 80 or case["id"] in ids or case["group"] not in _GROUPS:
            raise ValueError("invalid case ID or group")
        if len(canonical(case)) > 20000:
            raise ValueError("case too large")
        ids.add(case["id"]); groups.add(case["group"])
    if groups != _GROUPS:
        raise ValueError("target, regression and safety cases are mandatory")
    return suite
