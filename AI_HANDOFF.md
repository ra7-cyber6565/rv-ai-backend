# Infinity Research AI — AI Handoff / Continuation Authority

**Purpose:** This is the first file any future AI/agent must read before changing this repository. It exists to stop half-finished parallel work, stale completion claims, duplicate implementations, and branch/deployment confusion.

## 1. Current integration authority

- Repository: `ra7-cyber6565/rv-ai-backend`
- Primary completion vehicle: **PR #79** — `Add bounded AI Company research with 4/6 specialists and chief validation`
- Integration branch: `codex/research-company-20260905`
- Last fully verified PR head before this handoff update: `259e396e839663215de1338435963c936321c54a`
- Verified source tree for that head: `abd3bae7aefe422aa851aad5c918d72550096373`
- `main` at that verification point: `1d7eddaca3e5146184cfa4e1884c8dbc3564f84e`
- PR #79 status at that point: **OPEN / DRAFT / UNMERGED**.

After any commit newer than the head above, do **not** inherit old green status automatically. Re-run the required exact-head gates and update this file with the new SHA and receipts.

## 2. What is already implemented in PR #79

The existing app has been extended rather than replaced. Major implemented areas include:

- COMPANY mode: four specialist workers plus chief synthesis.
- COMPANY_PLUS mode: six specialist workers plus chief synthesis.
- AI-1 evidence/research governance and AI-2 quantitative validation remain integrated.
- Typed claims, hypotheses, dissent, worker IDs, timestamps, input hashes and bounded raw-draft references.
- Detailed hypothesis/test planning including mechanisms, assumptions, variables/units, controls, confounders, uncertainty, power/stopping/replication fields where supplied/applicable.
- Shared budgets, bounded worker concurrency and fail-closed PARTIAL behavior for missing workers/handoffs.
- Durable SQLite research stages/events/checkpoints and bounded resume/cancel behavior.
- Source/memory invalidation and governed private memory controls.
- Atomic application quotas/reservations for generation attempts and I/O accounting.
- Confirmed-free provider routing remains mandatory; no paid fallback is permitted.
- Server-owned tool roles/effects/arguments, numeric AST execution and JSON artifacts.
- Operator-enabled isolated Python/Node builds with bounded Docker execution, ZIP artifacts, source/output hashes and isolation/resource controls.
- Improvement proposals from observed failures/missing deliverables, with protected baseline/candidate evaluation. No automatic production rewrite/apply/merge/deploy.
- Stored-data preservation is default-on for verified archives, durable history, expired checkpoints, improvement proposals and unfinished reading files. Full stores pause new work instead of silently deleting retained user data.
- Hosted/manual validation contracts, host launcher, localhost API smoke and CI-based isolated executor verification.

See the detailed ledgers/docs instead of re-implementing these features:

- `WORK_STATUS.md`
- `docs/INFINITY_REQUIREMENT_LEDGER.md`
- `docs/AI_COMPANY_RESEARCH.md`
- `docs/RELIABILITY_RUNTIME.md`
- `docs/ISOLATED_BUILDS_AND_IMPROVEMENT.md`
- `docs/COMPANY_HOST_SETUP.md`
- `docs/HOSTED_VALIDATION.md`

## 3. Verified evidence on the last validated head

The last validated PR #79 head reported **all five exact-head workflows PASS**.

Foundation run `34093457137` recorded:

- 4,197 full-suite passes.
- 9 offline container cases explicitly skipped in the offline pass, then exercised in the mandatory real Linux/Docker lane.
- 594 focused passes.
- 1,047 advanced passes.
- 42/42 actual offline API smoke checks.
- 10/10 isolated-build tests in the mandatory Linux/Docker lane, zero skips there.
- 7/7 protected-improvement tests in that lane, zero skips there.
- 20/20 localhost Uvicorn/session/access smoke checks.
- 8/8 default-on data-preservation tests.
- Architecture/provider-bypass/domain fixture gates passed as recorded in PR #79.

Specialist/attestor workflows on that exact validated head also passed:

- AI-1 run `34093457113`
- AI-2 run `34093457039`
- Model reality run `34093457071`
- Anti-confirmation run `34093457097`

**Important:** these are software/host validation receipts. They are not proof of live model answer quality, scientific truth, profitability, production deployment, or universal completion.

## 4. What is NOT complete yet

Do not mark the app COMPLETE while any of the following remains unresolved:

1. Private confirmed-free model/provider configuration for the exact reviewed revision.
2. Manual live COMPANY / COMPANY_PLUS research dispatch on that exact revision.
3. Independent held-out answer-quality and extraction benchmark with frozen grading/ground truth.
4. Persistent production storage with real restore/durability evidence.
5. Production-compatible isolated executor on a supported off-laptop host with exact-revision receipts.
6. Exact-revision production deployment and deployed HTTP/API verification.
7. Hard end-to-end research acceptance: a demanding question must return all mandatory deliverables without being mislabeled COMPLETE when required sections are missing.
8. Safe comparison/integration of the user's unavailable local Windows commit/work (`7e36911` plus uncommitted/untracked files) if/when those files are supplied to this workspace.
9. Any requirement still marked PARTIAL / MISSING / BLOCKED in `docs/INFINITY_REQUIREMENT_LEDGER.md`.

Current release truth from the last validated head: `HOST_VALIDATED_LIVE_NOT_VERIFIED`; `release_ready=false`.

## 5. Definition of DONE — mandatory

No AI may say "done", "complete", "100%", "production ready", or equivalent merely because code exists or CI is green.

For this project, DONE requires all of the following on one traceable integrated revision:

1. Required code is integrated in the completion branch and then merged to `main`.
2. Exact-head required CI/workflows are green.
3. The exact merged revision is deployed to the intended production service.
4. Deployed revision identity is verified.
5. Confirmed-free live model/provider configuration is verified without exposing secrets.
6. Real COMPANY/COMPANY_PLUS live research runs complete through the public app path.
7. Independent held-out quality/extraction grading passes the predeclared acceptance contract.
8. Persistent storage/restart/restore behavior is demonstrated on the production-compatible environment.
9. Required executor/isolation path is demonstrated on its actual supported host.
10. End-to-end hard acceptance questions return all mandatory sections; incomplete work must remain PARTIAL, never mislabeled COMPLETE.
11. Remaining ledger items are either VERIFIED, explicitly N/A with justification, or honestly documented as accepted external limitations. No hidden MISSING/PARTIAL item may be silently ignored.

Until then use precise states such as CODE COMPLETE, TESTED, HOST VALIDATED, LIVE NOT VERIFIED, DEPLOYMENT PENDING, PARTIAL, BLOCKED, or INCONCLUSIVE.

## 6. Mandatory workflow for every future AI

Before editing:

1. Read this file completely.
2. Read the top/current continuation in `WORK_STATUS.md`.
3. Read `docs/INFINITY_REQUIREMENT_LEDGER.md` for current PARTIAL/MISSING/BLOCKED items.
4. Inspect PR #79 current head/status and compare it with `main`.
5. Inspect exact-head workflow results; never reuse a green receipt from an older SHA as proof for a newer SHA.
6. Do not start a new feature wave merely because a new idea exists. First ask whether it closes one of the remaining acceptance blockers.
7. Preserve other agents' branches and the user's unavailable local work. Do not reset/delete/overwrite it.

After any material change:

1. Update this file with the new current head SHA and verification state.
2. Update `WORK_STATUS.md` current continuation.
3. Update the matching rows in `docs/INFINITY_REQUIREMENT_LEDGER.md`.
4. Update PR #79 description with exact evidence and remaining blockers.
5. Run the required exact-head gates.
6. Record failures as failures; do not weaken tests simply to obtain green CI.
7. If a new head has not completed verification, explicitly mark it `VERIFICATION PENDING` rather than inheriting the prior head's PASS.

## 7. Single-thread completion rule

PR #79 is the current completion vehicle. Avoid creating another broad AI-3/AI-4/company/reliability feature branch while PR #79 still contains unresolved acceptance work, unless isolation is technically required for a specific blocker and the new branch is explicitly planned to merge back into PR #79.

New feature work must not outrank these acceptance blockers:

`integration -> exact-head CI -> live confirmed-free run -> independent quality benchmark -> persistent production storage/executor -> exact-revision deploy -> end-to-end acceptance`.

This ordering is intentionally strict so the project stops accumulating strong but unshipped half-completions.

## 8. User constraints that must be preserved

- ₹0-only model/service path unless the user explicitly changes that requirement.
- No silent paid fallback or surprise billing.
- Do not delete existing user research/files merely to free capacity; pause admission when bounded retained storage is full.
- Avoid heavy laptop storage/compute setup as the default continuation path.
- Do not expose secrets in GitHub, UI, logs, APK or receipts.
- Do not fabricate tests, metrics, live execution, scientific validation or success probabilities.
- Human-facing answers should remain easy to understand while preserving evidence/audit detail.

## 9. Why this file exists

The project previously accumulated many good PRs and thousands of passing tests while the deployed app still lagged behind the intended integrated system. This handoff file makes completion state explicit and durable so a new AI does not restart finished work, confuse tests with deployment, or abandon acceptance work halfway through.
