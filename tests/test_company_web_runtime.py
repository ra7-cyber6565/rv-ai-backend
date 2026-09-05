"""Execute the shipped JavaScript boundaries with hostile fixture report data."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_company_rendering_escapes_model_text_and_all_modes_keep_wait_limits():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node runtime unavailable; JavaScript behavior was not executed")
    page = Path(__file__).resolve().parents[1] / "web" / "index.html"
    script = r'''
const fs=require("fs"),vm=require("vm"),assert=require("assert");
const page=fs.readFileSync(process.argv[1],"utf8");
function body(name){const marker="function "+name+"(";const start=page.indexOf(marker);assert(start>=0);
  const tail=page.slice(start);const next=tail.indexOf("\nfunction ",marker.length);
  return next<0?tail:tail.slice(0,next);}
const ctx={};vm.runInNewContext([body("esc"),body("htmlText"),body("companyHtml")].join("\n"),ctx);
const attack='<img src=x onerror="alert(1)">';
const report={summary:attack,claims:[{kind:attack,text:attack,source_ids:[attack]}],
  hypotheses:[{hypothesis:attack,prediction:attack,baseline:attack,test:attack,falsification:attack}],
  limitations:[attack],contract_issues:[attack],assumptions:[attack],contradictions:[attack],remaining_questions:[attack]};
const html=ctx.companyHtml({verification:{research_company:{completed_workers:1,requested_workers:4,
  accounting_complete:false,workers:[{role:attack,status:attack,report}]}}});
assert(!html.includes('<img'));assert(html.includes('&lt;img'));
assert(html.includes('TEST PROPOSED'));assert(html.includes('usage receipt'));
assert(html.includes('Assumptions'));assert(html.includes('Contradictions'));assert(html.includes('Remaining questions'));
assert.strictEqual(ctx.companyHtml({}),"");
const declarations=page.split("\n").filter(line=>line.trim().startsWith("const longMode=")||
  line.trim().startsWith("const hardDeadline=")).join("\n");
assert(declarations.includes("longMode"));
for(const mode of ["QUICK","DEEP","MAXIMUM","CUSTOM","MARATHON","COMPANY","COMPANY_PLUS"]){
  const result=vm.runInNewContext(declarations+"\n({hardDeadline,stallMinutes});",
    {requestedMode:mode,Date:{now:()=>0}});
  const long=["MARATHON","COMPANY","COMPANY_PLUS"].includes(mode);
  assert.strictEqual(result.hardDeadline,(long?60:30)*60*1000);
  assert.strictEqual(result.stallMinutes,long?10:6);
}
'''
    result = subprocess.run([node, "-e", script, str(page)], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stderr
