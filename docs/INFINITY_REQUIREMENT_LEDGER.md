# Infinity implementation and acceptance ledger

Specification: user attachment `Pasted markdown(20260905-064523).md`, received
2026-09-05. Scope: all 22 sections remain tracked. PR #79 implements a bounded
research-team path in the existing application. **This ledger does not declare
the entire specification complete.** A partial status is not an external blocker;
remaining engineering work is named separately from unavailable live evidence.

## Current continuation — reliability runtime

The original inventory below records the first company implementation. These
current changes supersede its corresponding gap descriptions; unchanged empirical
gaps remain open. Exact final results belong to PR #79, not inferred from filenames.

| IDs | Current implementation / acceptance evidence | Remaining limit |
|---|---|---|
| R01, R21, R22 | Preserve reviewed head; extend same app/PR; `RELIABILITY_RUNTIME.md` has configuration, commands and evidence scope | Full vision not universally complete |
| R02, R17 | `task_contract.py`: original request, explicit parts, types, dependencies, coverage; private UI stop/resume and numeric downloads | Heuristic parsing; arbitrary-part completion stays NOT_ASSESSED |
| R03, R04 | Real workers gain stable IDs, durable raw envelope checkpoints and typed numeric tool receipts | Shared corpus/model diversity and live quality remain unproved |
| R05 | Discovery and enriched reading are typed/hash-checked checkpoints | Fresh OCR/table/equation ground truth still required |
| R06, R08, R09, R11 | Existing claim, hypothesis, complete-test-plan and domain guards retained; numeric execution never promotes clinical truth | External semantic/scientific validation and adequate statistical data still required |
| R07, R14 | `governed_memory.py`: scoped provenance/trust/expiry, inspect/export/delete and source-to-dependent-run invalidation; stale API answers blocked | Legacy memory/graph/archive erasure not covered by new per-record endpoint |
| R10, R16 | `tool_registry.py`: fixed role/effect/argument checks; actual restricted AST calculations with artifact hashes | General arbitrary-code isolation/build backend unavailable |
| R12, R13 | `research_runtime.py`: atomic per-run and shared-provider HTTP/input-byte/output-token reservations before retries; Gemini output cap/SDK retry control | Application caps are not verified provider quota; legacy direct entry points and actual input-token accounting remain open |
| R15 | SQLite stages/events; same-input/code recovery, cancellation, bounded resume, non-replay of ambiguous effects | In-flight request ends at timeout; unfinished reads may rerun; same deadline persists |
| R18, R20 | Frozen paired-evaluation harness; protected supplied holdout, task-cluster uncertainty, missing denominators; changes stay reviewable PR proposals | No live matched baseline/holdout campaign or validated automated promotion loop |
| R19 | New process budget, restart, cancellation, correction, tool injection/failure/artifact and evaluation tests complement original 18-case map | Full integrated CI plus declared external-data/live cases remain separate evidence |

Local evidence during development: 10 actual SQLite/process runtime tests PASS;
3 synthetic paired-evaluation tests PASS; architecture/provider audits and JS
syntax PASS. Governed-tool suite initially could not import because the refreshed
workspace lacks dependencies; network approval cancelled installation. No such
blocked check is counted as PASS. See exact-head CI in PR #79 for final results.

Every whole-requirement status below remains conservative: implementing a new
subcomponent does not automatically close the rest of a PARTIAL requirement.

Evidence register:

- E0: base main `1d7eddaca3e5146184cfa4e1884c8dbc3564f84e`, Foundation
  [run 33852832167](https://github.com/ra7-cyber6565/rv-ai-backend/actions/runs/33852832167), PASS.
- E1: first company head `01b55305`, Foundation
  [run 33950193751](https://github.com/ra7-cyber6565/rv-ai-backend/actions/runs/33950193751):
  4112 pytest cases passed, one browser source-pattern case failed; architecture
  audit also found its old Marathon pattern. The full gate was FAIL.
- E2: on that same head, AI-1, AI-2, model-reality and anti-confirmation CI passed.
  These are software checks, not four live research agents or scientific proof.
- E3: 61 relevant local cases passed after the browser-check repair, with blank
  credentials and native connect/send syscalls denied. Includes execution of
  shipped JavaScript for hostile report rendering and seven mode wait limits.
- E4: `tests/test_research_company.py`, `tests/test_company_web_runtime.py`,
  `tests/test_live_zero_cost_gate.py`, `tests/test_windows_launchers.py` are the
  ongoing extension's reproducible acceptance cases. Final exact-head results
  belong to the PR checks and PR description; file existence is not a pass.
- E5: source inspection of the locations below; inspection alone establishes
  structure/limitations, not successful runtime behavior.
- E6: live providers, production host RAM/latency, real document retrieval and
  held-out answer-quality comparison: **NOT TESTED** in this work.

An unrestricted local suite and Python-only isolation attempt were rejected by
automatic approval review after Google endpoint traffic. Those runs are not
passes. A subsequent kernel-isolated full local gate stalled on SDK retries,
timed out its focused stage and was interrupted. Exact-head CI is recorded
separately; none of these outcomes is hidden or converted into a pass.

## Requirements

Each record includes location, observed behavior, remaining gap, change/next
action, acceptance check and evidence. Status concerns the entire numbered
requirement, not just its most convenient subcomponent.

### R01 — Project preservation and truth: IMPLEMENTED_AND_TESTED

Location: `WORK_STATUS.md`, current Git tree, PR #79. Observed: isolated branch
from verified main, 13 initial changed files, existing engine retained, unrelated
PRs untouched. Change: record current evidence and this ledger. Acceptance: clean
versioned change set and traceable checks. Evidence: E0–E5. No app-wide maturity
conclusion follows from repository access.

### R02 — Task contract and dependency graph: PARTIAL

Location: `research_engine/requested.py`, `planner.py`, `result_coverage_gate.py`.
Observed: explicit request parsing, domain/language planning and missing-output
coverage gates exist and run in the main flow. Gap: a universal typed task DAG
covering arbitrary coding, artifacts, freshness and cross-tool dependencies is
not established. Next change: extend existing request records and executor
dependencies. Acceptance: mixed multi-deliverable tasks preserve every item;
irrelevant science checks are explicitly inapplicable. Evidence: E1, E5; no
held-out task-contract accuracy was measured.

### R03 — Real research team: PARTIAL

Location: `research_company.py`, `company_worker.py`, `orchestrator.py`, depth/API
and web controls. Observed: four/six separate worker processes, chief handoff,
bounded concurrency, IDs, timestamps, actual router receipts and failures.
Change: connect existing ScientistSociety to production. Gap: workers share
retrieval; distinct model/provider availability and live quality remain unproved.
Acceptance: four simultaneous fixtures, failed-worker downgrade, private job
submission and live worker/chief receipts. Evidence: E3–E6.

### R04 — Disciplined collaboration and artifacts: PARTIAL

Location: `research_company.py`, existing durable `utils/research_jobs.py`.
Observed: separate initial contexts, typed drafts, assumptions/dissent/questions,
hash-addressed bounded raw outputs, sequenced events and chief evidence review.
Gap: events become durable with the final job result; mid-run crash checkpoints
and independently versioned external artifact storage are not implemented here.
Next change: transactional checkpoints tied to project, input and code versions.
Acceptance: crash between worker completion and chief execution, then verified
recovery without re-running completed work. Evidence: E4, E5; crash recovery is
not claimed from the in-memory event list.

### R05 — Deep source acquisition: PARTIAL

Location: `source_discovery.py`, `content_fetcher.py`, `processing/`, `models.py`,
`source_prompt_guard.py`. Observed: existing multilingual/source-derived search,
books/papers, legal full text, read-depth labels, PDF/OCR handling and limits.
Change: company workers consume this existing guarded corpus. Gap: actual newly
retrieved OCR/tables/equations, all locators and extraction fidelity were not
re-audited end-to-end. Next: provenance-labelled document corpus with extraction
ground truth. Acceptance: missing pages/unreadable tables remain explicit;
selected passages never become a whole-book-read claim. Evidence: E1, E5, E6.

### R06 — Claim-level evidence: PARTIAL

Location: `claim_verification.py`, `evidence_drafting.py`, `epistemic_governance.py`.
Observed: source/span, label, critical-claim and zero-eligible achievement gates;
worker source-ID checks explicitly do not establish entailment. Gap: calibrated
semantic support and methodology/population matching need external evaluation.
Next: labelled claim-span fixture and held-out audits. Acceptance: URL-valid but
unsupported claims fail, zero eligible checks never earn achievement. Evidence:
E1, E4, E5; deterministic/model-assisted checks are not human review.

### R07 — Contradictions and dependence: PARTIAL

Location: `contradiction.py`, `source_integrity.py`, `deep_source_integrity.py`.
Observed: structured contradiction/source-origin analyses and independence
checks; chief is told to retain unresolved conflicts. Gap: source corrections
do not have a demonstrated end-to-end invalidation path through every stored
answer/index. Next: connect invalidation events to dependent stored artifacts.
Acceptance: copied studies count once; correction downgrades all affected cached
conclusions. Evidence: E1, E5; full cache invalidation NOT TESTED.

### R08 — Hypothesis quality: PARTIAL

Location: `hypothesis.py`, `advanced_discovery.py`, company mechanism/red-team
roles. Observed: candidate parsing, gate/rejection/tournament machinery and
baseline/prediction/falsification fields. Gap: distinctness, causal adequacy and
novelty quality are not established by schema checks. Next: source-grounded
candidate benchmark with null explanations and blinded review. Acceptance:
unsupported novelty/success claims remain blocked; no forced winner. Evidence:
E1, E3–E6.

### R09 — Complete test plans: PARTIAL

Location: `validation_contracts.py`, AI-2 hardening modules, `lab.py`.
Observed: test-plan completeness and applicability guards; worker hypotheses
remain INCONCLUSIVE / TEST_PROPOSED. Gap: all detailed power, stopping-rule and
identifiability fields are not guaranteed for every domain. Next: extend existing
contracts using representative datasets. Acceptance: incomplete plans and tests
that cannot distinguish candidates remain incomplete/inconclusive. Evidence:
E1, E4, E5; no invented sample sizes or decision thresholds.

### R10 — Real execution and isolation: PARTIAL

Location: `lab.py`, `code_sandbox.py`, numeric execution modules. Observed: bounded
numeric checks and an AST interpreter without Python exec/eval, imports, network
or filesystem primitives. Existing chief pipeline retains lab/rejection results.
Gap: arbitrary program/build execution in an OS/container sandbox is MISSING;
the specialist subprocess is SDK isolation, not an untrusted-code sandbox.
Next: provision and validate an isolated executor before exposing general code
tools. Acceptance: hostile code cannot access network/files/processes; numerical
correctness and scientific adequacy remain separate. Evidence: E1, E4, E5.

### R11 — Domain-specific validation: PARTIAL

Location: `lab.py`, `trademodel.py`, `exammodel.py`, `craft.py`, scientific and
medical label guards. Observed: existing domain fixtures, temporal trading tests,
numeric constraints and treatment/physical-validation distinctions. Gap: current
market feeds, real engineering tolerances, clinical evidence and human creative
preference evaluation are external datasets, not supplied in this task. Next:
run scoped domain benchmarks with appropriate data. Acceptance: no profit/cure
guarantee or simulated-to-physical promotion. Evidence: E1, E4–E6.

### R12 — Resource-aware effort: PARTIAL

Location: `depth.py`, `research_company.py`, `reasoning_router*.py`.
Observed: separate worker call allocations plus reserved chief budget prevent
double-spending the per-run logical-call allowance; worker/time/source/concurrency
limits are finite. Gap: central provider-wide token/HTTP retry quota reservation
across concurrent jobs and empirically calibrated information-gain routing are
MISSING. Next: add provider-quota leases once actual quota semantics are known;
keep unvalidated utility estimates labelled heuristic. Acceptance: competing
workers/jobs cannot spend the same provider allowance. Evidence: E3–E5; logical
calls are explicitly different from HTTP attempts.

### R13 — Strict zero-cost operation: PARTIAL

Location: `utils/zero_cost_guard.py`, existing router and live preflight; company
worker preflight. Observed: company workers require eligible confirmed-free
configuration and fail without a model call when none exists. Live gate now
accepts company modes. Gap: current account eligibility, remaining quotas and
live fallback behavior are NOT TESTED; central quotas remain R12 work. Next:
execute the confirmed-₹0 gate on the configured user deployment. Acceptance:
unconfirmed/nonfree/no-quota paths cannot become successful live company runs.
Evidence: E1, E4–E6. No paid fallback is introduced.

### R14 — Memory and context: PARTIAL

Location: `research_memory.py`, `scientific_memory.py`, `memory_governance.py`.
Observed: project memory and separate governance/decay/failure-ledger primitives.
Gap: complete production wiring for review/correction/export/deletion across all
derived stores is not established. Next: trace each write/read/delete boundary,
then implement missing API/index invalidation paths. Acceptance: hypotheses do
not become facts and deletion reaches derived indexes. Evidence: E1, E5;
complete user-facing governance is NOT_ASSESSED.

### R15 — Long-running recovery and cancellation: PARTIAL

Location: `utils/research_jobs.py`, `api/job_routes.py`, progress/recovery UI.
Observed: capability-protected durable final results, bounded job queue,
process-lock protection and honest `interrupted` status after restart. Gap:
stage rehydration, user cancellation and side-effect idempotency are MISSING;
company events do not repair that gap. Next: implement durable checkpoints and
cooperative cancellation through discovery/workers/chief. Acceptance: interrupt
after a completed stage; resume without repeating its side effect. Evidence:
E1, E4, E5. A saved final result is not restart recovery.

### R16 — Tool and data security: PARTIAL

Location: API project/job guards, upload/network/storage guards, source prompt
guard and approved provider adapters. Observed: private project/job capabilities,
escaped report rendering and blocked direct provider bypasses. Gap: a unified
typed tool registry with per-worker effect permissions for arbitrary tools is
MISSING. Next: add the registry before enabling such tools. Acceptance: document
instructions cannot grant authority; typed arguments/effects are checked outside
the model. Evidence: E1, E3–E5; fixture quoting does not prove universal prompt-
injection resistance.

### R17 — Useful, inspectable answer: PARTIAL

Location: synthesizer/presentation guards and `web/index.html`. Observed: Hinglish
answer, expandable source/lab/process/audit views and company reports; planned
tests and actual lab records are separate. Change: extend existing process view,
retain raw draft references. Gap: end-user usability and every generated artifact
type are not verified. Next: assess real mixed requests on desktop/mobile.
Acceptance: missing deliverables stay visible and hostile text stays escaped.
Evidence: E1, E3–E6.

### R18 — Before/after evaluation: BLOCKED

Location: existing tests/benchmarks, proposed paired research evaluation.
Observed: software regressions can be compared; no live answer-quality before/
after experiment was performed. Blockers: representative frozen tasks/data,
untouched holdout, grading ground truth and available confirmed-free models.
Next: supply/freeze those inputs and run matched-budget plus deployment-budget
single-versus-multiworker comparisons. Acceptance: denominators, uncertainty,
repeated trials, latency, cost and abstention all reported. Evidence: E0–E6.
No maturity percentage or quality uplift is inferred from test counts.

### R19 — Acceptance scenarios: PARTIAL

Location: mapped cases below. Observed: many existing fixture checks plus new
worker failure, malformed output, usage and browser execution cases. Gap: real
restart/side-effect replay, global quota competition and end-user artifact build
remain uncovered. Next: close the mapped MISSING cases with behavior tests.
Acceptance: all 18 scenarios have execution evidence and declared scope, not
merely test filenames. Evidence: E1, E3–E6.

### R20 — Controlled improvement: PARTIAL

Location: Git/PR workflow, quality-release gates, memory governance primitives.
Observed: versioned reviewable changes, regression gates and draft promotion
boundary; no production permissions or spending rules were autonomously changed.
Gap: a validated automatic proposal/evaluation/rollback loop is MISSING.
Next: add proposals against protected evaluation cases without production
self-modification. Acceptance: no grader/evaluation leakage or weakened gates.
Evidence: E0–E5.

### R21 — Integrated stages: PARTIAL

Location: current PR and this ledger. Observed: source-to-workers-to-chief-to-lab
integration exists; existing foundation/security retained. Gap: later recovery,
memory, multimodal and provider quota work remains explicitly tracked here.
Next: R12/R15/R16 engineering, then dataset-backed evaluations. Acceptance:
stage completion cannot erase later requirements. Evidence: E1–E5.

### R22 — Concrete deliverables and evidence: PARTIAL

Location: PR #79, `docs/AI_COMPANY_RESEARCH.md`, new/updated tests and live scripts.
Observed: working code path, configuration/budget disclosure, runnable private
job API and Windows preflight/live commands. No migration or paid service added.
Gap: final-head CI and actual live/provider/host measurements are separate
requirements. Next: inspect exact-head CI, then run confirmed-₹0 company checks
on the reviewed deployment. Acceptance: usable outputs, exact revision receipts,
failures and remaining engineering all disclosed. Evidence: E3–E6.

## The 18 requested acceptance cases

“Existing fixture” names a reproducible check family included in E1's software
run. It does not imply live external data or whole-feature completeness.

| Case | Acceptance evidence / next test | Current scope |
|---|---|---|
| 1. Contradictory source | `test_structured_contradictions.py`, `test_p0c_claim_level_contradiction.py` | Existing fixture |
| 2. Copied study | `test_source_integrity.py`, `test_ai1_deep_source_integrity.py` | Existing fixture |
| 3. Broken PDF/OCR/table | `test_pdf_sparse_sampling.py`; expand page/table ground truth | PARTIAL; full OCR/table fidelity not established |
| 4. Valid URL, unsupported claim | `test_claim_verification.py`, `test_evidence_verification.py` | Existing fixture |
| 5. Zero eligible claims | `test_evidence_first_release_contract.py`, `test_claim_label_accounting.py` | Existing fixture |
| 6. Incomplete hypothesis plan | `test_research_company.py`, AI-2 validation tests | Fixture |
| 7. Failed code/simulation | `test_code_sandbox.py`, simulation and lab checks | Existing constrained-executor fixture |
| 8. Four workers with failure | `test_research_company.py`, live-gate receipt checks | Fixture; live NOT TESTED |
| 9. Timeout/malformed/no free model | `test_research_company.py` | Fixture plus actual no-model child process |
| 10. Parallel budget competition | Company fixed disjoint logical allocations tested | PARTIAL; provider-wide token/HTTP leases missing |
| 11. Prompt injection/exfiltration | `test_source_prompt_guard.py`, company handoff and JS runtime checks | Fixture; not a live attack-rate claim |
| 12. Resume without repeated effect | Durable final job and interrupted-state tests only | MISSING stage/effect replay acceptance |
| 13. Source correction invalidation | Source/memory primitives have fixtures | MISSING complete cached-answer invalidation acceptance |
| 14. Trading look-ahead leakage | Existing lab/trading/data-forensics checks | Fixture; no new live strategy backtest |
| 15. Hypothesis promoted to cure | Company status-coercion test; physical-reality guards | Fixture; no clinical validation |
| 16. Missing requested output | Existing requested/coverage/final quality gates | Existing fixture |
| 17. Insufficient evidence | Existing fail-closed claim/quality tests | Existing fixture |
| 18. Usable generated artifact | This PR's executable JS/API path; raw draft artifacts | PARTIAL; arbitrary builds/artifacts not supported |

## Before/after and operational limits

Before, code inspection found no production ScientistSociety dispatch in the
question flow. After, fixture execution demonstrates four concurrent specialist
jobs, six-worker budgeting, typed chief handoff and missing-worker downgrade.
This is a functional integration result, **not** a measured answer-quality gain.
The earlier base/PR suite totals are not a matched quality benchmark.

New dependencies: none in the app. Native child processes cost RAM; concurrency
can be reduced with `RESEARCH_COMPANY_CONCURRENCY=1..4`. Actual peak RAM, token
consumption, latency percentiles and provider rate limits are UNKNOWN until
measured on the real configured host. Windows launcher syntax is statically
checked here; PowerShell/live execution on the user's laptop is NOT TESTED.

A software CI PASS will not close R12/R14/R15/R16 engineering gaps or E6's live
and empirical gaps. Those requirements remain visible after this PR.
