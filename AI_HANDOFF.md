# Infinity Research AI — AI Handoff / Continuation Authority

**Purpose:** This is the first file any future AI/agent must read before changing this repository. It exists to stop half-finished parallel work, stale completion claims, duplicate implementations, and branch/deployment confusion.

## 1. Current integration authority — updated 2026-09-07

- Repository: `ra7-cyber6565/rv-ai-backend`
- PR #79 `Add bounded AI Company research with 4/6 specialists and chief validation` is now **MERGED**.
- Final validated PR head before merge: `9a740b61e48f61ea8acf718fb585bf1be105f688`.
- All five required exact-head workflows passed on that head: Foundation, AI-1, AI-2, Model Reality, Anti-confirmation.
- Merge commit on `main`: `d6cf73fc1ead003aec6abcc085930713ac4a4388`.
- Merge tree: `4bbaae0154f3ee508e82cea774f2032765628eb0`.
- Railway production service `web` auto-deployed that exact merge commit successfully.
- Railway deployment id: `decfc39e-2e34-4867-ad27-17fd07785c65`.
- Production deployment status: **SUCCESS**; application startup completed.
- Public production API `/api/v1/depth-modes` was queried after deploy and returned both `COMPANY` and `COMPANY_PLUS` modes.
- Railway environment exposes the expected Gemini key variable names plus `GEMINI_ZERO_COST_CONFIRMED`; secret values were not exposed or copied.

After any commit newer than the merge commit above, do **not** inherit this green/deployed status automatically. Re-run the required exact-head gates and re-verify production revision identity.

## 2. What is implemented and merged

The existing app has been extended rather than replaced. Major merged areas include:

- `COMPANY`: four specialist workers + chief synthesis.
- `COMPANY_PLUS`: six specialist workers + chief synthesis.
- AI-1 evidence/research governance and AI-2 quantitative validation integrated in the main research path.
- Typed claims, hypotheses, dissent, worker IDs, timestamps, input hashes and bounded raw-draft references.
- Detailed hypothesis/test planning including mechanisms, assumptions, variables/units, controls, confounders, uncertainty, power/stopping/replication fields where supplied/applicable.
- Shared budgets, bounded concurrency, fail-closed PARTIAL behavior for missing workers/handoffs.
- Durable SQLite research stages/events/checkpoints and bounded resume/cancel behavior.
- Source/memory invalidation and governed private memory controls.
- Atomic application quotas/reservations for generation attempts and I/O accounting.
- Confirmed-free provider routing remains mandatory; no paid fallback is permitted.
- Server-owned tool roles/effects/arguments, numeric AST execution and JSON artifacts.
- Operator-enabled isolated Python/Node builds with bounded Docker execution, ZIP artifacts, source/output hashes and isolation/resource controls.
- Improvement proposals from observed failures/missing deliverables with protected baseline/candidate evaluation. No automatic production rewrite/apply/merge/deploy.
- Stored-data preservation is default-on for verified archives, durable history, expired checkpoints, improvement proposals and unfinished reading files. Full stores pause new work instead of silently deleting retained user data.
- Hosted/manual validation contracts, host launcher, localhost API smoke and CI-based isolated executor verification.
- Root `AGENTS.md` and this file are the permanent continuation entrypoint for future coding agents.

Detailed ledgers/docs:
- `WORK_STATUS.md`
- `docs/INFINITY_REQUIREMENT_LEDGER.md`
- `docs/AI_COMPANY_RESEARCH.md`
- `docs/RELIABILITY_RUNTIME.md`
- `docs/ISOLATED_BUILDS_AND_IMPROVEMENT.md`
- `docs/COMPANY_HOST_SETUP.md`
- `docs/HOSTED_VALIDATION.md`

## 3. Verification evidence

On exact PR head `9a740b61e48f61ea8acf718fb585bf1be105f688` all five required workflows passed.

Foundation included:
- advanced research quality regression: PASS
- strict zero-cost foundation gate: PASS
- Windows company host launcher parse: PASS
- actual isolated builds, protected improvement trials and localhost API lane: PASS
- hosted live validation step: intentionally skipped on automatic PR run
- foundation receipt upload: PASS

Earlier preserved Foundation evidence for the same integration lineage recorded 4,197 full-suite passes, 594 focused passes, 1,047 advanced passes, 42/42 offline API smoke, 10/10 isolated-build tests, 7/7 protected-improvement tests and 20/20 localhost Uvicorn/session/access smoke. Counts overlap and are not summed.

The merged production revision is `d6cf73fc1ead003aec6abcc085930713ac4a4388`; Railway deployment `decfc39e-2e34-4867-ad27-17fd07785c65` completed successfully and Uvicorn reported application startup complete. Production `/api/v1/depth-modes` returned `COMPANY` with 4 agents and `COMPANY_PLUS` with 6 agents.

**Important:** software CI + successful production deployment still do not prove live answer quality, scientific truth, profitability, independent replication, or universal completion.

## 4. What is still NOT complete

Do not mark the entire app COMPLETE while these acceptance items remain unresolved:

1. **Real live COMPANY acceptance run on the deployed merged revision.** A bounded live superconductivity acceptance run was about to be started, but the connected Railway AI-agent tool hit its account usage limit before it could create the session/job. This is a tool-access blocker, not a successful or failed app research run.
2. **Real COMPANY_PLUS live acceptance run** on the deployed merged revision.
3. **Independent held-out answer-quality/extraction benchmark** with frozen grading/ground truth.
4. **Persistent production storage** with real restart/restore/durability evidence. Current Railway web service has no attached volume according to the production service inspection on 2026-09-07.
5. **Production-compatible isolated executor** on a supported off-laptop host with exact-revision receipts. Railway web itself is not proof of the Docker-in-Docker executor path.
6. **Hard end-to-end research acceptance:** a demanding question must return all mandatory deliverables without being mislabeled COMPLETE when sections are missing.
7. **Safe comparison/integration of unavailable local Windows work** (`7e36911` plus any uncommitted/untracked files) if/when those files are supplied.
8. Any requirement still marked PARTIAL / MISSING / BLOCKED in `docs/INFINITY_REQUIREMENT_LEDGER.md`.

Current truthful release state: **MERGED + DEPLOYED + SOFTWARE/HOST VALIDATED; LIVE RESEARCH QUALITY NOT YET VERIFIED.**

## 5. Definition of DONE — mandatory

No AI may say `done`, `complete`, `100%`, `production ready`, or equivalent merely because code exists, CI is green, or deployment succeeded.

For this project, DONE requires all of the following on one traceable integrated revision:

1. Required code integrated and merged to `main`.
2. Required exact-head CI/workflows green.
3. Exact merged revision deployed to intended production service.
4. Deployed revision identity verified.
5. Confirmed-free live model/provider readiness verified without exposing secrets.
6. Real `COMPANY` and `COMPANY_PLUS` live research runs complete through the deployed public app path.
7. Independent held-out quality/extraction grading passes the predeclared acceptance contract.
8. Persistent storage/restart/restore behavior demonstrated on a production-compatible environment.
9. Required executor/isolation path demonstrated on its actual supported host.
10. End-to-end hard acceptance questions return all mandatory sections; incomplete work must remain PARTIAL, never mislabeled COMPLETE.
11. Remaining ledger items are either VERIFIED, explicitly N/A with justification, or honestly documented as accepted external limitations.

## 6. Mandatory workflow for every future AI

Before editing:
1. Read `AGENTS.md`.
2. Read this file completely.
3. Read the top/current continuation in `WORK_STATUS.md`.
4. Read `docs/INFINITY_REQUIREMENT_LEDGER.md` for PARTIAL/MISSING/BLOCKED items.
5. Inspect current `main` SHA and exact-head workflows.
6. Inspect Railway production revision before claiming deployment state.
7. Do not start another broad feature wave until the remaining acceptance blockers above are closed or explicitly accepted.
8. Preserve user/local/parallel-agent work; do not reset/delete/overwrite it.

After any material change:
1. Update this file with new SHA and verification state.
2. Update `WORK_STATUS.md` and matching ledger rows.
3. Re-run required exact-head gates.
4. Record failures honestly; never weaken tests merely to obtain green CI.
5. Re-verify deployed revision after merge/deploy.

## 7. Completion order

Current completion order is:

`live COMPANY acceptance -> live COMPANY_PLUS acceptance -> independent quality benchmark -> persistent production storage/restore -> production executor receipts -> hard end-to-end acceptance -> remaining ledger closure`.

Do not restart already-merged AI Company implementation unless fixing a measured defect.

## 8. User constraints that must be preserved

- ₹0-only model/service path unless the user explicitly changes that requirement.
- No silent paid fallback or surprise billing.
- Do not delete existing user research/files merely to free capacity; pause admission when bounded retained storage is full.
- Avoid heavy laptop storage/compute setup as the default continuation path.
- Do not expose secrets in GitHub, UI, logs, APK or receipts.
- Do not fabricate tests, metrics, live execution, scientific validation or success probabilities.
- Human-facing answers should remain easy to understand while preserving evidence/audit detail.
