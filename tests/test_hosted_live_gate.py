"""Offline authority/receipt/privacy contracts, not live provider evidence."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_hosted_live_gate as gate

SHA = 'a'*40

def environment():
    return dict(GITHUB_ACTIONS='true',GITHUB_EVENT_NAME='workflow_dispatch',RUNNER_ENVIRONMENT='github-hosted',
                RUNNER_OS='Linux',GITHUB_REPOSITORY=gate.REPOSITORY,INFINITY_REPOSITORY_PRIVATE='false',
                INFINITY_HOSTED_LIVE_REQUESTED='true',INFINITY_REVIEWED_COMMIT=SHA,GITHUB_SHA=SHA,
                GITHUB_RUN_ID='123',GITHUB_RUN_ATTEMPT='1',GEMINI_MODEL='fixture-model')

def proofs():
    common=dict(code_revision=SHA,repository_clean=True,ci_run_id='123',ci_run_attempt='1')
    foundation=dict(common,passed=True,offline_zero_cost=True,
        stages=[dict(name=n,status='passed',returncode=0) for n in gate.REQUIRED_STAGES])
    host=dict(common,host_tests={label:dict(passed=True,tests_run=n,skipped=0,exit_status=0) for label,n in [('isolated_builds',10),('protected_improvement',7)]},
        localhost_smoke=dict(complete=True,expected_code_revision=SHA,deployed_code_revision=SHA,
                             checks=[dict(name='fixture_'+str(i),passed=True) for i in range(20)]),
        runtimes={language:dict(ready=True,image='sha256:'+'b'*64) for language in ['python','node']})
    return foundation,host


class HostedLiveGateTests(unittest.TestCase):
    def test_selection_rejects_automatic_private_self_hosted_and_mismatched_runs(self):
        good=environment(); identity=dict(clean=True,revision=SHA)
        self.assertEqual(gate.selection(good,identity),[])
        for key,value in [('GITHUB_EVENT_NAME','pull_request'),('RUNNER_ENVIRONMENT','self-hosted'),
                          ('INFINITY_REPOSITORY_PRIVATE','true'),('INFINITY_HOSTED_LIVE_REQUESTED','false'),
                          ('GITHUB_SHA','b'*40),('GITHUB_RUN_ID','')]:
            with self.subTest(key=key):
                self.assertTrue(gate.selection(dict(good,**{key:value}),identity))
        self.assertTrue(gate.selection(good,dict(identity,clean=False)))

    def test_source_and_workflow_attempt_bound_proofs(self):
        f,h=proofs(); self.assertEqual(set(gate.validate_receipts(f,h,environment())),{'python','node'})
        for key,value in [('code_revision','b'*40),('ci_run_id','122'),('ci_run_attempt','2'),('repository_clean',False)]:
            for which in ('foundation','host'):
                a,b=copy.deepcopy(f),copy.deepcopy(h)
                (a if which=='foundation' else b)[key]=value
                with self.subTest(key=key,which=which),self.assertRaises(gate.HostedGateBlocked):
                    gate.validate_receipts(a,b,environment())

    def test_zero_skipped_empty_and_failed_prerequisites_never_pass(self):
        for field,value in [('tests_run',0),('tests_run',True),('skipped',1),('exit_status',1),('passed',False)]:
            f,h=proofs();h['host_tests']['isolated_builds'][field]=value
            with self.subTest(field=field),self.assertRaises(gate.HostedGateBlocked):
                gate.validate_receipts(f,h,environment())
        f,h=proofs(); f['stages']=[]
        with self.assertRaises(gate.HostedGateBlocked):gate.validate_receipts(f,h,environment())
        f,h=proofs();h['localhost_smoke']['checks'][0]['passed']=False
        with self.assertRaises(gate.HostedGateBlocked):gate.validate_receipts(f,h,environment())

    def test_public_summary_does_not_forward_provider_or_source_payload(self):
        summary=gate.summarize({'COMPANY':dict(passed=False,receipt={'answer':'PRIVATE_SOURCE','secret':'PRIVATE_KEY',
            'checks':[dict(name='worker_check',passed=False,detail='PRIVATE_SOURCE')]})})
        self.assertNotIn('PRIVATE',json.dumps(summary))

    def test_preflight_never_calls_models_and_execution_needs_both_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);env=dict(environment(),RUNNER_TEMP=temp,INFINITY_DATA_ROOT=str(base/'live'),INFINITY_PREREQUISITE_ROOT=str(base/'proof'))
            (base/'proof'/'audit').mkdir(parents=True)
            f,h=proofs()
            for name,record in [('foundation_gate_ci.json',f),('company_host_latest.json',h)]:
                (base/'proof'/'audit'/name).write_text(json.dumps(record))
            with patch.dict(os.environ,env,clear=True),patch.object(gate,'repository_identity',return_value=dict(clean=True,revision=SHA)),patch.object(gate,'preflight',return_value={'ready':True}),patch.object(gate,'run_live_modes') as live,patch.object(gate,'run_trading_live') as trading,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gate.main([]),0);live.assert_not_called();trading.assert_not_called()
                live.return_value={'COMPANY':dict(passed=True,receipt={'checks':[]})}
                self.assertEqual(gate.main(['--execute']),1)
                trading.assert_not_called()
                live.return_value={m:dict(passed=True,receipt={'checks':[]}) for m in ['COMPANY','COMPANY_PLUS']}
                trading.return_value={'schema':2,'passed':True,'checks':[
                    dict(name=name,passed=True) for name in gate.REQUIRED_TRADING_CHECKS]}
                self.assertEqual(gate.main(['--execute']),0)
                trading.assert_called_once()
                result=json.loads((base/'live'/'audit'/'hosted_live_gate.json').read_text())
                self.assertTrue(result['passed']);self.assertFalse(result['release_ready'])
                self.assertFalse(result['production_deployed'])
                trading.return_value={'passed':True}
                self.assertEqual(gate.main(['--execute']),1)
                trading.return_value={'schema':2,'passed':False,'checks':[
                    dict(name=name,passed=False) for name in gate.REQUIRED_TRADING_CHECKS]}
                self.assertEqual(gate.main(['--execute']),1)
                trading.side_effect=ValueError('PRIVATE_PROVIDER_BODY')
                self.assertEqual(gate.main(['--execute']),2)
                failed=json.loads((base/'live'/'audit'/'hosted_live_gate.json').read_text())
                self.assertFalse(failed['passed'])
                self.assertEqual(failed['failure_code'],'hosted_operation_failed')
                self.assertEqual(failed['diagnostics']['errors'][0]['kind'],'value_error')
                self.assertTrue(any(frame['module']=='scripts.run_hosted_live_gate'
                                    for frame in failed['diagnostics']['errors'][0]['frames']))
                self.assertNotIn('PRIVATE',json.dumps(failed))

    def test_missing_eligibility_cannot_execute(self):
        with patch.dict(os.environ,{},clear=True),patch.object(gate,'run_live_modes') as live,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(gate.main(['--execute']),2);live.assert_not_called()

    def test_preflight_diagnostics_allowlist_blockers_and_reject_private_payloads(self):
        self.assertIsNone(gate.summarize_preflight({})['storage_ready'])
        result = gate.summarize_preflight({
            "ready": False, "storage_validated": True, "storage_ready": True,
            "model_layers_configured": True, "model_layers_usable_now": "PRIVATE_KEY",
            "blockers": ["Gemini credential(s) present (GEMINI_ZERO_COST_CONFIRMED missing/false)",
                         "runtime storage is unavailable or unwritable", "PRIVATE_KEY", {"secret": "PRIVATE_SOURCE"}],
            "path": "PRIVATE_PATH",
        })
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(result["model_layers_configured"], 0)
        self.assertEqual(result["model_layers_usable_now"], 0)
        self.assertEqual(result["blocker_codes"], ["gemini_zero_cost_confirmation_required",
                         "storage_unavailable", "unclassified_preflight_blocker"])

    def test_blocked_preflight_persists_specific_settings_and_storage_without_models(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            env = dict(environment(), RUNNER_TEMP=temp, INFINITY_DATA_ROOT=str(base/'live'),
                       INFINITY_PREREQUISITE_ROOT=str(base/'proof'), ZERO_COST_ONLY='true',
                       GEMINI_API_KEY='PRIVATE_TEST_KEY', GEMINI_ZERO_COST_CONFIRMED="'true'")
            (base/'proof'/'audit').mkdir(parents=True)
            f, h = proofs()
            for name, record in [('foundation_gate_ci.json', f), ('company_host_latest.json', h)]:
                (base/'proof'/'audit'/name).write_text(json.dumps(record))
            readiness = dict(ready=False, storage_validated=True, storage_ready=True,
                             blockers=['Gemini credential(s) present (GEMINI_ZERO_COST_CONFIRMED missing/false)'])
            output = io.StringIO()
            with patch.dict(os.environ, env, clear=True), patch.object(gate, 'repository_identity', return_value=dict(clean=True, revision=SHA)), patch.object(gate, 'preflight', return_value=readiness), patch.object(gate, 'run_live_modes') as live, patch.object(gate, 'run_trading_live') as trading, contextlib.redirect_stdout(output):
                self.assertEqual(gate.main(['--execute']), 2)
            live.assert_not_called(); trading.assert_not_called()
            result = json.loads((base/'live'/'audit'/'hosted_live_gate.json').read_text())
            self.assertFalse(result['live_test_performed'])
            self.assertFalse(result['settings']['checks']['gemini_confirmation_flag_accepted'])
            self.assertTrue(result['preflight']['storage_ready'])
            self.assertEqual(result['preflight']['blocker_codes'], ['gemini_zero_cost_confirmation_required'])
            self.assertNotIn('PRIVATE', output.getvalue())

    def test_trading_receipt_is_allowlisted_and_cannot_self_certify(self):
        good = {"schema": 2, "passed": True, "checks": [
            {"name": name, "passed": True, "detail": "PRIVATE_SOURCE"}
            for name in gate.REQUIRED_TRADING_CHECKS],
            "summary": {"status": "PRIVATE_KEY", "answer_sha256": "PRIVATE_ANSWER"},
            "answer": "PRIVATE_ANSWER"}
        clean = gate.summarize_trading(good)
        self.assertNotIn("PRIVATE", json.dumps(clean))
        self.assertTrue(clean["passed"])
        for change in ("missing", "duplicate", "failed", "bad_type", "schema"):
            row = copy.deepcopy(good)
            if change == "missing": row["checks"].pop()
            elif change == "duplicate": row["checks"][0] = row["checks"][1]
            elif change == "failed": row["checks"][0]["passed"] = False
            elif change == "bad_type": row["checks"][0]["passed"] = "true"
            else: row["schema"] = 1
            with self.subTest(change=change):
                self.assertFalse(gate.summarize_trading(row)["passed"])


if __name__ == '__main__':
    unittest.main()
