# Agent instructions — Infinity Research AI

Before doing any work in this repository, read **`AI_HANDOFF.md` completely**.

That file is the continuation authority for current integration state, verified evidence, pending blockers, user constraints and the project definition of DONE.

## Non-negotiable continuation rules

- Current broad completion vehicle is **PR #79** / branch `codex/research-company-20260905` unless `AI_HANDOFF.md` records a later superseding authority.
- Do not restart or duplicate features already listed as implemented in `AI_HANDOFF.md` and `docs/INFINITY_REQUIREMENT_LEDGER.md`.
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
2. current continuation at the top of `WORK_STATUS.md`
3. `docs/INFINITY_REQUIREMENT_LEDGER.md`
4. PR #79 current head/status and exact-head CI
5. relevant runtime/validation docs named in `AI_HANDOFF.md`

## After material work

Update the durable handoff/status/ledger and PR evidence as required by `AI_HANDOFF.md`. If the new head has not finished exact-head verification, mark it **VERIFICATION PENDING** instead of inheriting an older PASS.
