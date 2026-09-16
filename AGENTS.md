# Agent instructions — Infinity Research AI

Before doing any work in this repository, read **`AI_HANDOFF.md` completely**.

That file is the continuation authority for current integration state, verified evidence, pending blockers, user constraints and the project definition of DONE.

For any research-mode, orchestration, UI-mode, agent-company, or capability-routing change, also read **`MAX_MODE_CONTRACT.md` completely**. The public product contract is `Chat | Max`; Max is the unified strongest bounded research entrypoint and legacy weaker presets must not be re-exposed as separate normal-user decisions unless the user explicitly changes that requirement.

## Non-negotiable continuation rules

- PR #79 is merged; do not treat its old branch as the current broad completion vehicle. Follow the newest authority recorded in `AI_HANDOFF.md` plus the current `main` SHA.
- Do not restart or duplicate features already listed as implemented in `AI_HANDOFF.md`, `MAX_MODE_CONTRACT.md`, and `docs/INFINITY_REQUIREMENT_LEDGER.md`.
- Passing unit/CI tests does not equal production completion.
- Never reuse green workflow receipts from an older SHA to certify a newer SHA.
- Do not call the project DONE until the exact integrated revision satisfies the `Definition of DONE` in `AI_HANDOFF.md`.
- Preserve PARTIAL / MISSING / BLOCKED / NOT TESTED states honestly.
- Do not fabricate live runs, scientific validation, model-quality results, deployment status or success probabilities.
- Preserve the user's ₹0-only/no-silent-paid-fallback constraint.
- Do not silently delete retained user data to free capacity.
- Avoid heavy laptop setup/downloads as the default continuation path.
- Do not reset, delete or overwrite other agents' branches or the user's unavailable local/uncommitted work.

## Read order before editing

1. `AI_HANDOFF.md`
2. `MAX_MODE_CONTRACT.md` when research modes/orchestration are involved
3. current continuation at the top of `WORK_STATUS.md`
4. `docs/INFINITY_REQUIREMENT_LEDGER.md`
5. current `main` SHA, relevant PR/branch, and exact-head CI
6. relevant runtime/validation docs named in `AI_HANDOFF.md`

## After material work

Update the durable handoff/status/ledger and PR evidence as required by `AI_HANDOFF.md`. If the new head has not finished exact-head verification, mark it **VERIFICATION PENDING** instead of inheriting an older PASS.
