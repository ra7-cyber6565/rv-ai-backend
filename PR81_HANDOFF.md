# PR #81 — continuation handoff

Read this together with `AGENTS.md`, `AI_HANDOFF.md`, `MAX_MODE_CONTRACT.md` and `docs/PR81_ACCEPTANCE.md` before changing the live-trading repair branch.

## Purpose

PR #81 is a measured-defect repair for the deployed unified Max trading acceptance path. It is **not** a new feature wave and must not be merged merely because offline CI is green.

PR: `#81 Fix Max live trading acceptance defects`
Branch: `fix/live-trading-acceptance-20260908`
Base at PR creation: `831dbc7209253e58bbfa0ec79b9efe8e130bf523`

## Last fully green pre-live-lane head

`0a75e6a048b1f032206f3b9a8e02e907b6ad3649` passed all five required workflows:

- Foundation `34308257586`
- AI-1 `34308257669`
- AI-2 `34308257731`
- Model Reality `34308257676`
- Anti-confirmation `34308257595`

Foundation's opt-in hosted live step was skipped on that run. Therefore this is software/host evidence, not PR #81 live acceptance.

## Repairs already present before the new live lane

- Technical Python/Pine/backtest `script` intent is kept out of creative dialogue coverage.
- Trading hypothesis structure copies only explicit trading/backtest details; it does not invent thresholds/results.
- Specialist handoff accounting can use already-successful synthesis as a bounded fallback consumer when analysis did not complete; missing/truncated/no-consumer cases remain incomplete.
- Final trading acceptance requires actual requested model/testing/script deliverables.
- Actionable numeric thresholds are classified as user-supplied, source-cited, LAB-measured, provisional, or unsupported; unsupported thresholds block acceptance.

## New acceptance work added after `0a75e6a...`

The existing hosted live gate was audited and found insufficient for PR #81 because its fixed live question is superconductivity, not trading. A superconductivity-only live receipt cannot prove the trading repairs.

The branch now adds:

- `scripts/run_pr81_trading_live_acceptance.py`
  - one fixed, non-arbitrary US100/XAUUSD `MAXIMUM` question;
  - exercises the normal public `AgentManager` path;
  - requires a real Python technical-script deliverable;
  - audits trading contract activation, requested model/testing points, threshold provenance, fail-closed PARTIAL semantics, six-worker Max execution and specialist-handoff accounting;
  - emits only booleans/counters and answer SHA-256, never answer/source/provider/credential text.
- `tests/test_pr81_trading_live_acceptance.py`
  - covers successful structural acceptance, missing script, false COMPLETE, unsupported threshold fail-closed behavior, handoff gap/truncation and creative contamination.
- `scripts/run_hosted_live_gate.py`
  - after COMPANY and COMPANY_PLUS live gates pass, runs the fixed Max trading lane;
  - a failed company prerequisite prevents spending another six-worker Max allocation;
  - overall hosted live PASS now requires the `trading_max` lane to pass too.
- `docs/PR81_ACCEPTANCE.md`
  - binds draft-exit acceptance to a fresh exact-head hosted receipt containing passing `trading_max` evidence.

The last material code/doc commit before this handoff note is `dde681786bdeed84b588c4219b11d5754a52185f`. Any commit at or after this handoff note is a **new head** and must be verified on its own; do not inherit the green state of `0a75e6a...`.

## Current truthful status

`VERIFICATION PENDING` for the new trading live-lane head until all five required exact-head workflows finish.

Even after exact-head CI is green, PR #81 must remain draft until a manual hosted workflow dispatch runs with:

- `live_company=true`
- `reviewed_commit=<the exact current full PR head SHA>`

The GitHub connection available to the previous agent could inspect/rerun workflow jobs but did not expose a workflow-dispatch start action, so no live dispatch was fabricated.

After that run, inspect the sanitized `hosted-live-receipt` and require:

1. COMPANY live gate pass.
2. COMPANY_PLUS live gate pass.
3. `trading_max.passed == true`.
4. No skipped live step.
5. Receipt revision equals the reviewed exact PR head.

Only then reconsider draft status/merge. After merge, wait for and verify the exact production deployment before claiming the repair deployed.

## Production warning

Railway production was inspected read-only. The `web` service was healthy on main, but the production environment had six pre-existing staged changes and no attached persistent volume. Do not blindly accept those staged changes. PR #81 live validation is a GitHub-hosted exact-head gate and does not require mutating Railway.

## Ledger / completion honesty

This repair does not promote the whole app or any broad requirement to COMPLETE. The main requirement ledger remains conservative. Independent held-out answer-quality grading, persistent production storage/restore, production-compatible isolated executor evidence, hard end-to-end acceptance and any remaining PARTIAL/MISSING/BLOCKED ledger rows remain separate completion work.
