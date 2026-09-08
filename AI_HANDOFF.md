# Infinity Research AI — AI Handoff / Continuation Authority

**Purpose:** This is the first file any future AI/agent must read before changing this repository. It exists to stop half-finished parallel work, stale completion claims, duplicate implementations, and branch/deployment confusion.

## Active answer-acceptance repair — 2026-09-08

- Branch `codex/answer-scope-20260908` is based on main
  `831dbc7209253e58bbfa0ec79b9efe8e130bf523`; it does not change production.
- The user's superconductivity answer exposed a source-report fallback that did
  not distinguish 1 GPa from requested atmospheric conditions, a question quoted
  as a mechanism, and a public PARTIAL reason referring to the original COMPLETE
  label. Condition accounting, negative-follow-up preservation, question
  filtering and public status wording now have regression coverage.
- Condition mentions alone never establish scientific confirmation. This parser
  does not certify temperature/material matching, retraction or replication.
- Local stdlib pressure cases passed. Integrated exact-head CI is
  **VERIFICATION PENDING** at authoring; the new PR's exact head and workflow
  receipts are the authority. No new live research or deployment is claimed.
- Parallel Sol PR #81 was reviewed at
  `0a75e6a048b1f032206f3b9a8e02e907b6ad3649` (all five workflows green).
  Its craft/trading-hypothesis files are preserved on its branch. Those results
  do not certify this branch or the future combined revision.
- See `docs/ANSWER_CONDITION_ACCEPTANCE.md` for the measured defects, scope and
  remaining live acceptance work. All broader blockers in section 5 remain open.

## 1. Current integration authority — updated 2026-09-08

- Repository: `ra7-cyber6565/rv-ai-backend`.
- PR #79 (4/6-agent AI Company integration) is MERGED.
- PR #80 `Unify all research capabilities behind Chat and Max` is MERGED.
- Final validated PR #80 head before merge: `cc2004e9a8486f5477c10c7669bb8493407b6959`.
- All five required exact-head workflows passed on that head: Foundation, AI-1, AI-2, Model Reality, Anti-confirmation.
- PR #80 merge commit on `main`: `19ae77a7c0ce8a3eef7ce5b43073e2ea52e97249`.
- Railway production service `web` auto-deployed that exact merge commit successfully.
- Railway deployment id: `405df048-571a-49b0-80f6-39f1ef1e38ff`.
- Railway deployment status: **SUCCESS**; container startup began successfully.
- Production source remains GitHub repo `ra7-cyber6565/rv-ai-backend`, branch `main`.
- Production domain remains `web-production-0dd45.up.railway.app`.
- Railway environment exposes Gemini key variable names plus `GEMINI_ZERO_COST_CONFIRMED`; secret values are not copied into this repository or handoff.

After any commit newer than the merge commit above, do **not** inherit this green/deployed status automatically. Re-run required exact-head gates and re-verify production revision identity.

## 2. Public product contract now merged

The normal user-facing research choice is intentionally simplified to exactly two product modes:

1. `Chat` -> fast/normal `QUICK` path.
2. `Max` -> unified strongest bounded `MAXIMUM` path.

Legacy backend names (`DEEP`, old `MAXIMUM`, `MARATHON`, `COMPANY`, `COMPANY_PLUS`, `CUSTOM`) may remain accepted internally for compatibility/tests/admin use, but the normal user should not have to choose among them.

`MAXIMUM` is now the unified super-orchestrator contract. It must preserve the strongest useful capabilities already built in the repository:

- Marathon-style 5 configured research rounds.
- Up to 40 ranked sources and 16 legally accessible full-text reads under the bounded preset.
- Papers, books, datasets and patents when relevant.
- Counter-evidence / red-team work.
- Six specialist workers plus chief synthesis when an eligible confirmed-zero-cost model layer is usable.
- The six roles include the original Company-4 roles (`evidence`, `validation`, `mechanism`, `red_team`) plus Company+ extensions (`data_quality`, `implementation`). Do not duplicate the same four workers merely to claim both Company modes ran.
- AI-1 evidence/research governance and AI-2 validation remain downstream in the normal AgentManager path.
- Existing hypothesis, experiment/simulation, trading-model, physics, document/PDF/book, contradiction, verification and synthesis lanes remain available to the same Max run when applicability gates say they are relevant.
- Provider unavailability must not collapse the rest of Max. If no eligible model layer is currently usable, Company workers are skipped honestly while the Marathon-strength deterministic/core research path remains available.
- The Company chief uses the integrated zero-cost/fallback-capable reasoning router; it must not silently fall back to a weaker direct-provider-only path.

Permanent product/runtime contract: `MAX_MODE_CONTRACT.md`.

## 3. What is implemented and merged

Major merged areas include:

- Unified public Chat/Max product surface.
- COMPANY: four specialist workers + chief synthesis.
- COMPANY_PLUS: six specialist workers + chief synthesis.
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
- Root `AGENTS.md`, `MAX_MODE_CONTRACT.md`, and this file are permanent continuation entrypoints.

Detailed ledgers/docs:
- `WORK_STATUS.md`
- `docs/INFINITY_REQUIREMENT_LEDGER.md`
- `docs/AI_COMPANY_RESEARCH.md`
- `docs/RELIABILITY_RUNTIME.md`
- `docs/ISOLATED_BUILDS_AND_IMPROVEMENT.md`
- `docs/COMPANY_HOST_SETUP.md`
- `docs/HOSTED_VALIDATION.md`

## 4. Verification evidence

On exact PR #80 head `cc2004e9a8486f5477c10c7669bb8493407b6959` all five required workflows passed:

- Foundation tests: PASS.
- AI-1 Research Director Gate: PASS.
- AI-2 Validation Director Gate: PASS.
- Model reality attestors: PASS.
- Anti-confirmation attestor: PASS.

Foundation caught a real integration regression during PR #80 development: making Company workers a mandatory dependency caused an offline/no-provider Max run to become unnecessarily incomplete. The runtime was changed so Max retains 5-round Marathon-strength core behavior when model workers are unavailable while still running six workers when an eligible model layer exists. A stale 3-round MAXIMUM regression test was updated to the new 5-round unified Max contract instead of weakening Max back to the old behavior.

The final merged production revision is `19ae77a7c0ce8a3eef7ce5b43073e2ea52e97249`; Railway deployment `405df048-571a-49b0-80f6-39f1ef1e38ff` reached SUCCESS.

**Important:** software CI + successful production deployment still do not prove live answer quality, scientific truth, profitability, independent replication, or universal completion.

## 5. What is still NOT complete

Do not mark the entire app COMPLETE while these acceptance items remain unresolved:

1. **Real live unified Max acceptance run on deployed merge `19ae77a7...`.** Run a demanding research question through the public Max path and verify that the expected integrated layers complete or fail honestly.
2. **Live worker/chief proof on the unified Max path.** When a confirmed-zero-cost model layer is usable, capture receipts showing the six specialist roles and chief actually executed on the deployed revision. If provider quota is unavailable, record that honestly rather than treating it as a software failure or success.
3. **Independent held-out answer-quality/extraction benchmark** with frozen grading/ground truth.
4. **Persistent production storage** with real restart/restore/durability evidence. Current Railway web service has no attached persistent volume according to the earlier production inspection unless this is changed later and re-verified.
5. **Production-compatible isolated executor** on a supported off-laptop host with exact-revision receipts. Railway web itself is not proof of the Docker-in-Docker executor path.
6. **Hard end-to-end research acceptance:** a demanding question must return all mandatory deliverables without being mislabeled COMPLETE when sections are missing.
7. **Safe comparison/integration of unavailable local Windows work** (`7e36911` plus any uncommitted/untracked files) if/when those files are supplied.
8. Any requirement still marked PARTIAL / MISSING / BLOCKED in `docs/INFINITY_REQUIREMENT_LEDGER.md`.

Current truthful release state: **UNIFIED MAX MERGED + EXACT-HEAD CI GREEN + PRODUCTION DEPLOYED; LIVE MAX ANSWER QUALITY / WORKER EXECUTION NOT YET FULLY VERIFIED.**

## 6. Definition of DONE — mandatory

No AI may say `done`, `complete`, `100%`, `production ready`, or equivalent merely because code exists, CI is green, or deployment succeeded.

For this project, DONE requires all of the following on one traceable integrated revision:

1. Required code integrated and merged to `main`.
2. Required exact-head CI/workflows green.
3. Exact merged revision deployed to intended production service.
4. Deployed revision identity verified.
5. Confirmed-free live model/provider readiness verified without exposing secrets.
6. Real unified Max live research run completes through the deployed public app path.
7. Where a model layer is usable, Max receipts demonstrate the integrated six-specialist + chief path rather than only a configuration claim.
8. Independent held-out quality/extraction grading passes the predeclared acceptance contract.
9. Persistent storage/restart/restore behavior demonstrated on a production-compatible environment.
10. Required executor/isolation path demonstrated on its actual supported host.
11. End-to-end hard acceptance questions return all mandatory sections; incomplete work must remain PARTIAL, never mislabeled COMPLETE.
12. Remaining ledger items are VERIFIED, explicitly N/A with justification, or honestly documented as accepted external limitations.

## 7. Mandatory workflow for every future AI

Before editing:
1. Read `AGENTS.md`.
2. Read `MAX_MODE_CONTRACT.md`.
3. Read this file completely.
4. Read the top/current continuation in `WORK_STATUS.md`.
5. Read `docs/INFINITY_REQUIREMENT_LEDGER.md` for PARTIAL/MISSING/BLOCKED items.
6. Inspect current `main` SHA and exact-head workflows.
7. Inspect Railway production revision before claiming deployment state.
8. Do not start another broad feature wave until the remaining acceptance blockers above are closed or explicitly accepted.
9. Preserve user/local/parallel-agent work; do not reset/delete/overwrite it.

After any material change:
1. Update this file with new SHA and verification state.
2. Update `WORK_STATUS.md` and matching ledger rows.
3. Re-run required exact-head gates.
4. Record failures honestly; never weaken tests merely to obtain green CI.
5. Re-verify deployed revision after merge/deploy.

## 8. Completion order

Current completion order is:

`live unified Max acceptance -> live six-worker/chief receipt -> independent quality benchmark -> persistent production storage/restore -> production executor receipts -> hard end-to-end acceptance -> remaining ledger closure`.

Do not restart already-merged Deep/Marathon/Company implementations unless fixing a measured defect. They are now internal capabilities of the unified Max product contract, not separate normal-user product choices.

## 9. User constraints that must be preserved

- ₹0-only model/service path unless the user explicitly changes that requirement.
- No silent paid fallback or surprise billing.
- Do not delete existing user research/files merely to free capacity; pause admission when bounded retained storage is full.
- Avoid heavy laptop storage/compute setup as the default continuation path.
- Do not expose secrets in GitHub, UI, logs, APK or receipts.
- Do not fabricate tests, metrics, live execution, scientific validation or success probabilities.
- Human-facing answers should remain easy to understand while preserving evidence/audit detail.
